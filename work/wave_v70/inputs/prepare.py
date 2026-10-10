"""損益を参照せず、四ティック入口と二つの旧入口部品を管理比較用に固定する。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD_INPUTS = ROOT / 'work/wave_v69/prepared/inputs.pkl'
OLD_TICKS = ROOT / 'work/wave_v69/signals/signals.pkl'
IDS = ('T1L1', 'T2L0', 'T3L1', 'T4L0', 'E01P', 'R01P')
TICK_INDEX = (1, 2, 5, 6)


def digest(path: Path) -> str:
    """機能: 読み取り専用素材と実装の内容指紋を計算する。

    引数: path(Path)。返り値: SHA256の16進文字列(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def save(name: str, value: object) -> None:
    """機能: 今作業の入力領域だけへ日本語JSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    target = (HERE / name).resolve()
    assert target.is_relative_to(HERE)
    target.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


def pulse(level: np.ndarray) -> np.ndarray:
    """機能: 非ゼロ開始と方向変更だけを独立入口候補にする。

    引数: level(ndarray[int8])。返り値: 前行との変化で発火する列(ndarray[int8])。
    保有状態、以前の出口、将来の取引損益を引数に取らない。
    """
    previous = np.r_[np.int8(0), level[:-1]]
    return np.where((level != 0) & (level != previous), level, 0).astype(np.int8)


def model(ready: dict, bars: pd.DataFrame, end: float | None = None) -> dict:
    """機能: 確定1分足から公開済みEMA15/60の間隔と傾きを作る。

    引数: ready(dict)、bars(DataFrame)、end(float|None)。
    返り値: 公開時刻・間隔ATR比・長期線3本差分ATR比(dict)。
    足は開始時刻+120秒で公開し、公開時刻以前の因果ATRのみ使う。
    """
    release = pd.to_datetime(bars.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120.
    finish = float(ready['time_s'][-1]) if end is None else float(end)
    valid = bars.closed.astype(str).str.lower().eq('true').to_numpy(copy=True)
    valid &= (release >= ready['start'] + 120.) & (release <= finish)
    close = bars.loc[valid, 'close'].astype(float).reset_index(drop=True)
    release = release[valid]
    assert np.all(np.diff(release) > 0)
    rows = np.searchsorted(ready['time_s'], release, side='right') - 1
    atr = np.full(len(release), np.nan)
    have = rows >= 0
    atr[have] = ready['atr'][rows[have]]
    fast = close.ewm(span=15, adjust=False, min_periods=15).mean()
    slow = close.ewm(span=60, adjust=False, min_periods=60).mean()
    return dict(time_s=release, gap=(fast.to_numpy() - slow.to_numpy()) / atr,
                slow=slow.diff(3).to_numpy() / atr)


def expand(source: dict, targets: np.ndarray, delay: float) -> dict:
    """機能: 自市場又は追加60秒遅延の相手市場を過去方向へ対応させる。

    引数: source(dict)、targets(ndarray[float64])、delay(float)。
    返り値: 対象行までに公開されたgap/slow列(dict)。未来補間をしない。
    """
    rows = np.searchsorted(source['time_s'] + delay, targets, side='right') - 1
    valid = rows >= 0
    out = {}
    for name in ('gap', 'slow'):
        values = np.full(len(targets), np.nan)
        values[valid] = source[name][rows[valid]]
        out[name] = values
    assert np.all((source['time_s'][rows[valid]] + delay) <= targets[valid])
    return out


def rearm(level: np.ndarray, own: dict, peer: dict) -> np.ndarray:
    """機能: 旧入口方向に加え両市場のEMA開始条件が今も成立した方向だけ残す。

    引数: level(ndarray[int8])、own/peer(dict)。返り値: R01入口部品列(ndarray[int8])。
    条件は両市場の短長差0.15ATR超、長期線3本傾き0.02ATR超で固定する。
    """
    keep = ((own['gap'] * level > .15) & (peer['gap'] * level > .15)
            & (own['slow'] * level > .02) & (peer['slow'] * level > .02))
    return np.where(keep, level, 0).astype(np.int8)


def main() -> None:
    """機能: 保存56口座の入口だけを再接続して因果性・符号対称性を照合する。

    引数: なし。返り値: なし(None)。現在API、旧取引台帳、新しい損益は開かない。
    """
    sys.dont_write_bytecode = True
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('通信は禁止されています'))
    socket.create_connection = socket.socket.connect
    assert not (HERE / 'signals.pkl').exists(), '入口の生成は完了済みです'
    inputs = pickle.loads(OLD_INPUTS.read_bytes())
    ticks = pickle.loads(OLD_TICKS.read_bytes())
    entry, old_hashes, match = {}, {}, []
    for folder in sorted((ROOT / 'work/wave_v67/prepared').iterdir()):
        signal_path, input_path = folder / 'signals.pkl', folder / 'new_inputs.pkl'
        if not signal_path.exists():
            continue
        archive = pickle.loads(signal_path.read_bytes())['entry']
        raw = pickle.loads(input_path.read_bytes())
        assert not set(entry) & set(archive)
        for key in archive:
            np.testing.assert_array_equal(inputs[key]['seq'], raw[key]['seq'])
            np.testing.assert_array_equal(inputs[key]['time_s'], raw[key]['time_s'])
            np.testing.assert_array_equal(inputs[key]['atr'], raw[key]['atr'])
            match.append(dict(session=key[0], symbol=key[1], 行順時計ATR一致=True))
        entry.update(archive)
        for path in (signal_path, input_path):
            old_hashes[str(path.relative_to(ROOT)).replace('\\', '/')] = digest(path)
    assert set(entry) == set(ticks) == set(inputs) and len(inputs) == 56
    bars = {k: pd.read_csv(ROOT / 'candle_1min' / k[1] / (k[0] + '.csv')) for k in inputs}
    models = {k: model(r, bars[k]) for k, r in inputs.items()}
    source_files = [OLD_INPUTS, OLD_TICKS, Path(__file__),
                    ROOT / 'work/wave_v69/signals/core.py', ROOT / 'work/wave_v69/signals/入口仕様.json',
                    ROOT / 'work/wave_v69/signals/入口の実原本因果照合.json',
                    ROOT / 'work/wave_v47/component_signals.py', ROOT / 'work/wave_v27/hierarchy_signals.py',
                    ROOT / 'work/wave_v27/hierarchy_design_fixed.json', ROOT / 'work/wave_v23/signals.py',
                    ROOT / 'work/wave_v49/gates/gate_replay.py']
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in source_files}
    hashes.update(old_hashes)
    hashes.update({str((ROOT / 'candle_1min' / k[1] / (k[0] + '.csv')).relative_to(ROOT)).replace('\\', '/'):
                   digest(ROOT / 'candle_1min' / k[1] / (k[0] + '.csv')) for k in inputs})
    meta = dict(固定時刻=datetime.now(timezone.utc).isoformat(), 入口ID順序=IDS,
        入口説明={
            'T1L1': '中値8呼値の進行後、両気配を伴い4呼値戻った方向。',
            'T2L0': '4呼値進行→2呼値押し→2呼値戻りで元方向へ再開。',
            'T3L1': '近傍板の表示量が最良量1倍以上回復し、接近後に両気配が4呼値反転。',
            'T4L0': '近傍板補充価格を2呼値越え、両気配の進行とOFIが一致。',
            'E01P': '旧E01の入口方向stateが非ゼロ開始又は方向変更した時。旧出口時計は参照しない。',
            'R01P': '旧E01入口方向に加え、両市場EMA開始条件が今も成立したstateの非ゼロ開始又は方向変更。'},
        比較範囲='全28セッション・56口座。既知範囲の管理比較であり未見検証ではない。',
        入口選び='損益を参照せず root 指定の4ティック入口と、既存の E01/R01 入口部品を固定。',
        E01原規則='H019相当: 確定1分足EMA15/60の間隔0.15ATR、長期3本傾き0.02ATR。相手主方向を60秒追加遅延で確認。解放済み中値30秒進行0.05ATR超、入口TTL120秒、開始20分。',
        R01条件='入口方向に対し自他のEMA間隔0.15ATR超・長期傾き0.02ATR超。確定足は開始時刻+120秒、相手追加60秒。',
        パルス化='旧E01/R01完全再現ではなく、入口部品の独立管理対照。state の0→±1又は反転行だけを候補とする。',
        保有数量='TOPIXミニ10枚・NK225マイクロ20枚は親管理器で固定。入口配列は数量を持たない。',
        再利用='ティック4系列は前作業の凍結配列の列選択。E01 stateは旧入口のみの凍結配列を原本行順で接続。',
        参照しない情報=['旧取引台帳の新規・返済行','新しい管理方式の損益','未来価格','現在API'],
        API取得数=0, 実注文数=0, SHA256=hashes)
    save('入口仕様.json', meta)
    output, levels, audits = {}, {}, []
    for key, ready in sorted(inputs.items()):
        peer_key = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
        own = expand(models[key], ready['time_s'], 0.)
        peer = expand(models[peer_key], ready['time_s'], 60.)
        old_level = entry[key]
        r_level = rearm(old_level, own, peer)
        six = np.vstack((ticks[key][list(TICK_INDEX)], pulse(old_level), pulse(r_level)))
        assert six.shape == (6, len(ready['seq'])) and six.dtype == np.int8
        assert np.isin(six, [-1, 0, 1]).all()
        cut = len(ready['seq']) // 2
        # ----------------------------------------
        # 新しいパルス接続器は過去だけで計算でき、未来変更と符号反転でも一致する。
        np.testing.assert_array_equal(pulse(old_level[:cut]), six[4, :cut])
        np.testing.assert_array_equal(pulse(-old_level), -six[4])
        finish = float(ready['time_s'][cut - 1])
        prefix_models = {k: model(inputs[k], bars[k], finish) for k in (key, peer_key)}
        a = expand(prefix_models[key], ready['time_s'][:cut], 0.)
        b = expand(prefix_models[peer_key], ready['time_s'][:cut], 60.)
        prefix = pulse(rearm(old_level[:cut], a, b))
        np.testing.assert_array_equal(prefix, six[5, :cut])
        changed = old_level.copy()
        changed[cut:] *= -1
        np.testing.assert_array_equal(pulse(changed)[:cut], six[4, :cut])
        changed_bars = {k: bars[k].copy() for k in (key, peer_key)}
        for k in changed_bars:
            release = pd.to_datetime(changed_bars[k].time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120.
            changed_bars[k].loc[release > finish, 'close'] *= 1.2
        future_models = {k: model(inputs[k], changed_bars[k]) for k in (key, peer_key)}
        a = expand(future_models[key], ready['time_s'], 0.)
        b = expand(future_models[peer_key], ready['time_s'], 60.)
        np.testing.assert_array_equal(pulse(rearm(changed, a, b))[:cut], six[5, :cut])
        mirror_own = {name: -value for name, value in own.items()}
        mirror_peer = {name: -value for name, value in peer.items()}
        np.testing.assert_array_equal(pulse(rearm(-old_level, mirror_own, mirror_peer)), -six[5])
        output[key], levels[key] = six, np.vstack((old_level, r_level))
        audits.append(dict(session=key[0], symbol=key[1], 原本行数=len(ready['seq']),
            候補数={name: int(np.count_nonzero(six[j])) for j, name in enumerate(IDS)},
            切断一致=True, 未来変更一致=True, 符号反転一致=True, 旧原本対応=True))
    for name, data in (('signals.pkl', output), ('levels.pkl', levels)):
        (HERE / name).write_bytes(pickle.dumps(data, pickle.HIGHEST_PROTOCOL))
    save('入口接続の検査.json', dict(全合格=True, 口座数=56, 検査=audits, 原本一致=match,
        旧ティック因果検査='wave_v69/signals/入口の実原本因果照合.json をそのまま継承。入口配列の再探索なし。',
        旧E01因果検査='wave_v67 prepared の各信号監査を継承。今回のパルス接続は追加の途中切断・未来変更・符号反転を実施。',
        API取得数=0, 損益参照=False,
        出力SHA256={name: digest(HERE / name) for name in ('signals.pkl', 'levels.pkl', '入口仕様.json')}))
    print('56口座・6入口の凍結と因果接続検査を完了しました', flush=True)


if __name__ == '__main__':
    main()
