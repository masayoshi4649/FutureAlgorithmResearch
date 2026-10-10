"""管理方式による再エントリー数の差を除くため、共通60分枠の入口を固定する。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import numba
from numba import njit

import prepare


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
numba.config.CACHE_DIR = str(HERE / 'numba_cache')


@njit(cache=True)
def candidates(times: np.ndarray, bid: np.ndarray, ask: np.ndarray, signal: np.ndarray,
               reset: np.ndarray, start: float, limit: float) -> tuple:
    """機能: 予約・成立・後続約定・固定60分休止を原本順に処理する。

    引数: times/bid/ask/signal/reset(ndarray)、start/limit(float)。
    返り値: fill方向・予約気配・発注判断行・予約行・終了時監査値(tuple)。
    実際の管理途中損益、返済時刻、原本終端による将来清算を参照しない。
    """
    n = len(times)
    output_side = np.zeros(n, np.int8)
    output_anchor = np.zeros(n)
    output_decision = np.full(n, -1, np.int64)
    output_source = np.full(n, -1, np.int64)
    parent_side = 0
    parent_row = -1
    anchor = 0.
    pending = False
    pending_row = -1
    lock_until = -1e30
    submitted = triggered = canceled = filled = 0
    for i in range(n):
        good = np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i] > 0. and ask[i] >= bid[i]
        # ----------------------------------------
        # 先に確定済み発注を執行する。価格の戻り・当行resetでは成立済み注文を消さない。
        if pending and i > pending_row and good:
            if times[i] >= limit - 300.:
                canceled += 1
            else:
                output_side[i] = parent_side
                output_anchor[i] = anchor
                output_decision[i] = pending_row
                output_source[i] = parent_row
                lock_until = times[i] + 3630.
                filled += 1
            parent_side = 0
            pending = False
        # ----------------------------------------
        # 未成立予約はTTL・時刻・品質で取消。取消後の同観測信号による新規予約を許す。
        if not pending and parent_side != 0:
            if times[i] - times[parent_row] >= 120. or times[i] >= limit - 300. or reset[i]:
                parent_side = 0
                canceled += 1
            elif good and i > parent_row:
                quote = ask[i] if parent_side == 1 else bid[i]
                if parent_side * (quote - anchor) >= 0.:
                    pending = True
                    pending_row = i
                    triggered += 1
        # ----------------------------------------
        # 共通の管理枠はfillから3600秒＋30秒。各管理の早期利確で枠を短縮しない。
        if (not pending and parent_side == 0 and good and not reset[i] and signal[i] != 0
                and times[i] >= start + 300. and times[i] < limit - 300. and times[i] >= lock_until):
            parent_side = int(signal[i])
            parent_row = i
            anchor = ask[i] if parent_side == 1 else bid[i]
            submitted += 1
    return output_side, output_anchor, output_decision, output_source, np.array([
        parent_side, int(pending), pending_row, parent_row, submitted, triggered, canceled, filled])


def artificial() -> dict:
    """機能: 成立後戻り、TTL、reset、固定休止、末尾pendingを人工経路で検査する。

    引数: なし。返り値: 検査結果(dict)。
    """
    tests = []
    args = (np.arange(7.) + 500., np.array([100., 101., 99., 103., 104., 105., 106.]),
            np.array([101., 102., 100., 104., 105., 106., 107.]),
            np.ones(7, np.int8), np.zeros(7, bool), 0., 9999.)
    output = candidates(*args)
    np.testing.assert_array_equal(np.flatnonzero(output[0]), [2])
    assert output[0][2] == 1 and output[1][2] == 101. and output[2][2] == 1 and output[3][2] == 0
    tests.append('予約行・成立行・fill行分離と成立後価格戻り取消なし')
    cut = tuple(v[:2] if isinstance(v, np.ndarray) else v for v in args)
    end = candidates(*cut)
    assert end[4][1] == 1 and not end[0].any()
    tests.append('原本末尾が成立直後でもpendingを未来清算しない')
    t = np.array([500., 501., 502., 4131., 4132., 4133., 4134.])
    out = candidates(t, *args[1:])
    np.testing.assert_array_equal(np.flatnonzero(out[0]), [2, 6])
    tests.append('fill後3630秒未満は同方向・反対方向とも再開せず境界から予約')
    # ----------------------------------------
    # TTL/品質による取消後、同じ行の別候補を予約できる。
    args2 = (np.array([500., 620., 621., 622.]), np.array([100., 99., 100., 101.]),
             np.array([101., 100., 101., 102.]), np.ones(4, np.int8), np.zeros(4, bool), 0., 9999.)
    out = candidates(*args2)
    assert out[3][3] == 1 and out[4][6] == 1
    tests.append('TTL120秒取消後の同観測候補による再予約')
    reset = np.array([False, True, False, False])
    args3 = (np.arange(4.) + 500., args2[1], args2[2], args2[3], reset, 0., 9999.)
    out = candidates(*args3)
    assert out[4][6] == 1 and not out[0].any() and out[4][1] == 1
    tests.append('未成立予約reset取消と予約当行の監視禁止')
    bad_bid = args[1].copy()
    bad_bid[2] = np.nan
    out = candidates(args[0], bad_bid, *args[2:])
    assert out[2][3] == 1 and out[3][3] == 0
    tests.append('成立済み注文は無効気配を飛ばし次有効原本行でfill')
    return dict(全合格=True, 検査=tests)


def main() -> None:
    """機能: 全6入口の共通スケジュールを固定し、切断・未来変更を照合する。

    引数: なし。返り値: なし(None)。取引損益・現在APIを参照しない。
    """
    sys.dont_write_bytecode = True
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('通信は禁止されています'))
    socket.create_connection = socket.socket.connect
    assert not (HERE / 'schedule.pkl').exists(), '共通入口は生成完了済みです'
    inputs = pickle.loads(prepare.OLD_INPUTS.read_bytes())
    features_path = ROOT / 'work/wave_v69/prepared/features.pkl'
    features = pickle.loads(features_path.read_bytes())
    signals = pickle.loads((HERE / 'signals.pkl').read_bytes())
    spec = dict(固定時刻=datetime.now(timezone.utc).isoformat(), 入口ID順序=prepare.IDS,
        用途='管理単独比較の共通60分枠。旧v69の出口に応じた通し再開とは違う。早期利確で次campaign数が増える効果を除く。',
        親='入口信号行の買いask/売りbidでstop予約。予約当行は監視せず次有効行以降で条件成立、その次有効行で新規fill。',
        成立後='価格が戻っても確定済み発注を取り消さない。無効気配は飛ばし、当行resetは成立済みfillを取り消さない。',
        未成立取消='予約120秒経過、reset、limit-300秒以後で取消。取消後同じ観測行の新しい候補は予約可能。',
        期間='start+300秒以後、limit-300秒未満。fillがlimit-300秒以後なら取消。',
        共通枠='初回fill時刻+3630秒まで次campaignの親予約を禁止。出口時刻・管理損益には依存しない。',
        配列='key=(session,symbol)→6入口順のlist[ndarray[float64,Nevents,5]]。列順fill_i,decision_i,source_i,side,anchor。fill行だけを格納する。',
        時計='原本CurrentPriceTimeの代理時計。同時刻でもseq順に処理。保存末尾を見て注文を消す処理なし。',
        API取得数=0, 損益参照=False,
        SHA256={str(p.relative_to(ROOT)).replace('\\', '/'): prepare.digest(p) for p in
                (Path(__file__), prepare.OLD_INPUTS, features_path, HERE / 'signals.pkl',
                 ROOT / 'work/wave_v69/engine.py')})
    prepare.save('共通入口スケジュール仕様.json', spec)
    prepare.save('共通入口の人工経路検査.json', artificial())
    output, records = {}, []
    for key, ready in sorted(inputs.items()):
        f = features[key]
        np.testing.assert_array_equal(ready['seq'], f['seq'])
        np.testing.assert_array_equal(ready['time_s'], f['time_s'])
        n = len(ready['seq'])
        arrays = []
        for j, code in enumerate(prepare.IDS):
            args = (ready['time_s'], f['bid'], f['ask'], signals[key][j], f['reset'], ready['start'], ready['limit'])
            full = candidates(*args)
            cut = n // 2
            clipped = tuple(a[:cut] if isinstance(a, np.ndarray) else a for a in args)
            short = candidates(*clipped)
            for a, b in zip(full[:4], short[:4]):
                np.testing.assert_array_equal(a[:cut], b)
            changed = list(args)
            for field in (1, 2):
                changed[field] = args[field].copy()
                changed[field][cut:] += 50. * ready['tick']
            changed[3] = args[3].copy()
            changed[3][cut:] *= -1
            changed[4] = args[4].copy()
            changed[4][cut:] = True
            future = candidates(*changed)
            for a, b in zip(full[:4], future[:4]):
                np.testing.assert_array_equal(a[:cut], b[:cut])
            fill = np.flatnonzero(full[0])
            assert np.all(full[3][fill] < full[2][fill]) and np.all(full[2][fill] < fill)
            assert np.all(np.diff(ready['time_s'][fill]) >= 3630.)
            anchor = np.where(full[0][fill] == 1, f['ask'][full[3][fill]], f['bid'][full[3][fill]])
            np.testing.assert_array_equal(anchor, full[1][fill])
            arrays.append(np.column_stack((fill, full[2][fill], full[3][fill], full[0][fill], full[1][fill])))
            records.append(dict(session=key[0], symbol=key[1], source=code, 初回fill数=len(fill),
                切断一致=True, 未来変更一致=True, 予約成立約定行分離=True, 再開禁止3630秒=True,
                末尾状態=full[4].tolist()))
        output[key] = arrays
    (HERE / 'schedule.pkl').write_bytes(pickle.dumps(output, pickle.HIGHEST_PROTOCOL))
    prepare.save('共通入口スケジュール検査.json', dict(全合格=True, 口座数=56, 系列数=336, 検査=records,
        候補別初回数={code: sum(r['初回fill数'] for r in records if r['source'] == code) for code in prepare.IDS},
        API取得数=0, 損益参照=False,
        出力SHA256=prepare.digest(HERE / 'schedule.pkl')))
    print('56口座×6入口の共通60分枠と因果性を固定しました', flush=True)


if __name__ == '__main__':
    main()
