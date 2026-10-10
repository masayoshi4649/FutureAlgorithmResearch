"""新設行同期の境界と旧通常運転の同値だけを検査し、新しい実相場格子は試さない。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wave_v33'))
import engine_dynamic_atr as previous
import dynamic_atr_engine_audit as helpers
sys.path.insert(0, str(HERE))
import engine_scheduler as engine

OLD_FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve')
P = {name: i for i, name in enumerate(engine.PREPARE_COLUMNS)}
E = {name: i for i, name in enumerate(engine.ENTRY_PREPARATION_COLUMNS)}


def digest(path: Path) -> str:
    """機能: ファイルの変更確認用指紋を返す。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(actual: dict, expected: dict, fields: tuple = OLD_FIELDS) -> None:
    """機能: 指定した全結果の全要素を厳密照合する。

    引数: actual/expected (dict)、fields (tuple[str])。返り値: なし (None)。
    """
    for field in fields:
        np.testing.assert_array_equal(actual[field], expected[field], err_msg=field)


def mask_from(shadow: dict, count: int) -> np.ndarray:
    """機能: 影の新設行だけを許可し、約定や途中更新の行は利用しない。

    引数: shadow (dict)、count (int)。返り値: 許可列 (ndarray[bool])。
    """
    result = np.zeros(count, dtype=np.bool_)
    result[shadow['prepare_events'][:, P['row']].astype(int)] = True
    return result


def paired(ready: dict, state: np.ndarray, cfg: dict, at: np.ndarray,
           width_mode: int = 1, observed: bool = False, detail: bool = True) -> tuple:
    """機能: 独立固定A0の新設行と実側を接続する。

    引数: ready/cfg (dict)、state/at (ndarray)、width_mode (int)、observed/detail (bool)。
    返り値: 影、実結果、許可列 (tuple[dict,dict,ndarray])。
    """
    shadow = engine.run(ready, state, cfg, detail, width_mode=0, observed_fill=observed)
    allowed = mask_from(shadow, len(state))
    actual = engine.run(ready, state, cfg, detail, width_mode=width_mode,
                        observed_fill=observed, trail_atr=at, prepare_allow=allowed)
    return shadow, actual, allowed


def fixture(prices: list[float], times: list[float] | None = None,
            tracking: list[float] | None = None) -> tuple:
    """機能: 同期注文を比較する人工価格・公開ATR・場末次行を作る。

    引数: prices (list[float])、times/tracking (list[float]|None)。
    返り値: ready、方向、設定、追跡ATR (tuple)。
    """
    ready, state, cfg, at = helpers.fixture(prices, trail=tracking)
    if times is not None:
        ready['time_s'] = np.array(times + [10000., 10001.])
    return ready, state, cfg, at


def links(ready: dict, result: dict, allowed: np.ndarray | None = None, shadow: dict | None = None) -> None:
    """機能: 全新設・約定の起点と、許可時の影との準備全値を検算する。

    引数: ready/result (dict)、allowed (ndarray|None)、shadow (dict|None)。返り値: なし (None)。
    """
    prepared = result['prepare_events']
    linked = result['entry_preparations']
    np.testing.assert_array_equal(prepared[:, P['prepare_id']], np.arange(len(prepared)))
    rows = prepared[:, P['row']].astype(int)
    assert len(rows) == len(set(rows)) and np.all(np.diff(rows) > 0)
    assert np.all(prepared[:, P['expiry_time']] == ready['time_s'][rows] + 300.)
    assert np.all(ready['time_s'][rows] >= ready['start'] + 1200.)
    assert np.all(ready['time_s'][rows] < ready['limit'] - 300.)
    if allowed is not None:
        assert allowed[rows].all()
    if shadow is not None:
        origin = {int(row[P['row']]): row for row in shadow['prepare_events']}
        for row in prepared:
            np.testing.assert_array_equal(row[1:], origin[int(row[P['row']])][1:])
    opened = result['orders'][result['orders'][:, 7] == 1]
    assert len(linked) == len(opened)
    for opening, entry in zip(opened, linked):
        identity, fresh, filled = int(entry[E['prepare_id']]), int(entry[E['prepare_row']]), int(entry[E['fill_row']])
        source = prepared[identity]
        assert fresh == source[P['row']] and 0 <= fresh <= opening[1] < filled
        assert opening[0] == filled and opening[2] == entry[E['campaign']]
        assert opening[3] == source[P['side']] and opening[4] == source[P['qty']]
        cycle = result['cycles'][result['cycles'][:, 0] == opening[2]]
        if len(cycle):
            assert cycle[0, 5] == source[P['initial_atr']]


def prefix_equal(result: dict, reference: dict, cut: int) -> None:
    """機能: 原本行の切断より前の準備・約定・返済・曲線を比較する。

    引数: result/reference (dict)、cut (int)。返り値: なし (None)。
    """
    for name in ('curve', 'atr_curve'):
        np.testing.assert_array_equal(result[name][:cut], reference[name][:cut])
    for name, column in (('trades', 7), ('cycles', 2), ('orders', 0), ('prepare_events', P['row']), ('entry_preparations', E['fill_row'])):
        np.testing.assert_array_equal(result[name][result[name][:, column] < cut], reference[name][reference[name][:, column] < cut])


def synthetic() -> list[dict]:
    """機能: 新設行だけの同期を各注文境界・欠測・反射・未来変更で検査する。

    引数: なし。返り値: 日本語検査記録 (list[dict])。
    """
    checks = []
    first = fixture([100., 101., 120., 113., 113., 114., 107., 110., 111.],
                    [0., 1., 2., 3., 303., 304., 600., 900., 901.],
                    [4., 4., 2., 2., 2., 2., 2., 2., 2.])
    r, s, cfg, at = first
    shadow, actual, allowed = paired(r, s, cfg, at)
    assert actual['cycles'][0, 2] == 3 and shadow['cycles'][0, 2] == 6
    np.testing.assert_array_equal(actual['prepare_events'][:, P['row']], [0, 7])
    normal = engine.run(r, s, cfg, True, width_mode=1, trail_atr=at)
    assert 4 in normal['prepare_events'][:, P['row']]
    helpers.account(r, actual, cfg); helpers.account(r, shadow, cfg)
    links(r, actual, allowed, shadow)
    checks.append({'検査': '実先返済後は自身の5分休止が終わっても影の次新設まで待機し、影は独立継続', '一致': True})

    # ----------------------------------------
    later = fixture([100., 101., 120., 107., 107., 106., 90., 90., 90., 91., 120., 107., 100., 101.],
                    [0., 1., 2., 3., 303., 304., 305., 603., 606., 607., 608., 609., 909., 910.],
                    [4., 4., 10., 10., 10., 10., 10., 10., 10., 10., 10., 10., 10., 10.])
    r, s, cfg, at = later
    shadow, actual, allowed = paired(r, s, cfg, at)
    assert shadow['cycles'][0, 2] == 3 and actual['cycles'][0, 2] == 6
    np.testing.assert_array_equal(shadow['prepare_events'][:, P['row']], [0, 4, 7, 12])
    np.testing.assert_array_equal(actual['prepare_events'][:, P['row']], [0, 12])
    np.testing.assert_array_equal(actual['entry_preparations'][:, E['fill_row']], [1, 13])
    assert r['time_s'][7] - r['time_s'][6] < 300 <= r['time_s'][8] - r['time_s'][6]
    helpers.account(r, actual, cfg); links(r, actual, allowed, shadow)
    checks.append({'検査': '影先返済時は実保有と自身休止中の新設を見送り、休止明けでも見送った未約定や約定済み影へ途中参加しない', '一致': True})

    # ----------------------------------------
    r, s, cfg, at = fixture([100., 99., 98., 99., 105., 95.])
    allowed = np.zeros(len(s), dtype=bool); allowed[0] = True
    result = engine.run(r, s, cfg, True, prepare_allow=allowed)
    assert result['orders'][0, 0] == 3 and result['orders'][0, 1] == 2 and result['orders'][0, 5] == 99
    np.testing.assert_array_equal(result['entry_preparations'][0], [0, 3, 0, 0])
    assert len(result['prepare_events']) == 1
    links(r, result, allowed); helpers.account(r, result, cfg)
    checks.append({'検査': '許可がFalseに戻っても既設注文は追跡更新して約定し、新設IDは追跡更新行で変わらない', '一致': True})
    none = engine.run(r, s, cfg, True, prepare_allow=np.zeros(len(s), dtype=bool))
    assert all(len(none[k]) == 0 for k in ('trades', 'orders', 'cycles', 'prepare_events', 'entry_preparations'))
    checks.append({'検査': '全行不許可では新設も保有も発生しない', '一致': True})

    # ----------------------------------------
    r, s, cfg, at = fixture([100., 99., 99., 100., 100., 101.], [0., 299., 300., 301., 600., 601.])
    both = np.zeros(len(s), dtype=bool); both[[0, 2]] = True
    result = engine.run(r, s, cfg, True, prepare_allow=both)
    assert result['entry_preparations'][0, E['prepare_row']] == 2
    np.testing.assert_array_equal(result['prepare_events'][:, P['row']], [0, 2])
    only = both.copy(); only[2] = False
    rejected = engine.run(r, s, cfg, True, prepare_allow=only)
    assert len(rejected['orders']) == 0
    s[1] = 0
    cancel = engine.run(r, s, cfg, True, prepare_allow=only)
    assert len(cancel['orders']) == 0
    checks.append({'検査': '通常のTTL失効・方向不一致取消を維持し、失効後の再新設にはその行の新しい許可が必要', '一致': True})

    # ----------------------------------------
    tied = fixture([100., 101., 120., 113., 107.], [0., 0., 0., 0., 0.], [4., 4., 2., 2., 2.])
    for data in (first, later, tied):
        r, s, cfg, at = data
        for mode in (0, 1):
            for observed in (False, True):
                shadow, result, allowed = paired(r, s, cfg, at, mode, observed)
                links(r, result, allowed, shadow)
                helpers.account(r, result, cfg)
                reflected = dict(r, last=300. - r['last'])
                reflected_shadow, mirror, reflected_allow = paired(reflected, -s, cfg, at, mode, observed)
                np.testing.assert_array_equal(allowed, reflected_allow)
                np.testing.assert_array_equal(result['entry_preparations'], mirror['entry_preparations'])
                np.testing.assert_array_equal(result['prepare_events'][:, [0, 1, 4, 5, 6]], mirror['prepare_events'][:, [0, 1, 4, 5, 6]])
                np.testing.assert_array_equal(result['prepare_events'][:, 2], -mirror['prepare_events'][:, 2])
                np.testing.assert_allclose(result['prepare_events'][:, 3] + mirror['prepare_events'][:, 3], 300.)
                np.testing.assert_array_equal(result['trades'][:, [0, 1, 3, 6, 7, 8, 9, 10]], mirror['trades'][:, [0, 1, 3, 6, 7, 8, 9, 10]])
                helpers.account(reflected, mirror, cfg)
                if observed:
                    np.testing.assert_array_equal(result['orders'][:, 5], r['last'][result['orders'][:, 0].astype(int)])
                if mode == 0:
                    # At診断列まで旧6一致させる恒等対照は、影と同じready.atrを渡す。
                    identical = engine.run(r, s, cfg, True, observed_fill=observed, prepare_allow=allowed)
                    same(identical, shadow, tuple(shadow))
    checks.append({'検査': '3人工相場×固定/現在×指定/観測で同時刻行順・飛値・部分返済・場末・売買反射・全玉会計を確認', '一致': True})

    # ----------------------------------------
    r, s, cfg, at = later
    shadow, result, allowed = paired(r, s, cfg, at)
    cut = 8
    shorter = {key: value[:cut].copy() if isinstance(value, np.ndarray) else value for key, value in r.items()}
    short_shadow, short_actual, short_allow = paired(shorter, s[:cut], cfg, at[:cut])
    prefix_equal(short_shadow, shadow, cut); prefix_equal(short_actual, result, cut)
    np.testing.assert_array_equal(short_allow, allowed[:cut])
    changed = deepcopy(r); changed['last'][cut:] = 5000.; changed['atr'][cut:] = 90.
    changed_s = s.copy(); changed_s[cut:] = -1
    changed_at = at.copy(); changed_at[cut:] = .01
    future_shadow, future_actual, future_allow = paired(changed, changed_s, cfg, changed_at)
    prefix_equal(future_shadow, shadow, cut); prefix_equal(future_actual, result, cut)
    np.testing.assert_array_equal(future_allow[:cut], allowed[:cut])
    compact_shadow, compact, compact_allow = paired(r, s, cfg, at, detail=False)
    same(compact, result, ('trades', 'cycles', 'orders', 'stats', 'prepare_events', 'entry_preparations'))
    np.testing.assert_array_equal(compact_allow, allowed)
    checks.append({'検査': '影の将来返済を含む未来価格/入口ATR/At/方向の削除・改変で過去の両運転と許可不変、詳細省略でも台帳不変', '一致': True})

    # ----------------------------------------
    r, s, cfg, at = fixture([100., np.nan, 101., 120., 110., 110.], tracking=[np.nan, 1., np.nan, 2., np.nan, 0.])
    for mode in (0, 1):
        current = engine.run(r, s, cfg, True, width_mode=mode, trail_atr=at)
        reference = previous.run(r, s, cfg, True, width_mode=mode, trail_atr=at)
        same(current, reference)
        only = np.zeros(len(s), dtype=bool); only[0] = True
        controlled = engine.run(r, s, cfg, True, width_mode=mode, trail_atr=at, prepare_allow=only)
        links(r, controlled, only)
        assert controlled['orders'][0, 0] == 2
    r, s, cfg, at = fixture([100., 100., 101., 110.])
    r['atr'][0] = np.nan
    only = np.zeros(len(s), dtype=bool); only[0] = True
    missing = engine.run(r, s, cfg, True, prepare_allow=only)
    assert len(missing['prepare_events']) == 0
    checks.append({'検査': '欠測価格で新設/約定せず、入口ATR欠測時は許可を繰越さず、At欠測保持は旧6結果と一致', '一致': True})
    for allowed in (np.ones(len(s), dtype=np.int8), np.ones(len(s) - 1, dtype=bool), np.ones((len(s), 1), dtype=bool), [True] * len(s)):
        try:
            engine.run(r, s, cfg, prepare_allow=allowed)
        except ValueError:
            pass
        else:
            raise AssertionError('許可配列の不正入力を受け入れた')
    checks.append({'検査': '許可の型・次元・長さを検査し、非対応形式を拒否', '一致': True})
    return checks


def compatibility() -> dict:
    """機能: 既知H019の通常A0/AtとA0同期恒等だけを全26入力で照合する。

    引数: なし。返り値: 比較件数 (dict)。実相場の新At制御を再生しない。
    """
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    counts = {'通常A0旧6一致': 0, '通常At旧6一致': 0, 'A0制御旧6一致': 0, '新設準備対応検査': 0}
    with np.load(HERE.parent / 'wave_v27/directions/H019.npz') as archive:
        for key, ready in inputs.items():
            state = archive['|'.join(key)]
            cfg = helpers.config(key[1], ready)
            for mode in (0, 1):
                actual = engine.run(ready, state, cfg, True, width_mode=mode)
                reference = previous.run(ready, state, cfg, True, width_mode=mode)
                same(actual, reference)
                links(ready, actual)
                counts['通常A0旧6一致' if mode == 0 else '通常At旧6一致'] += 1
                if mode == 0:
                    allowed = mask_from(actual, len(state))
                    controlled = engine.run(ready, state, cfg, True, prepare_allow=allowed)
                    same(controlled, actual, tuple(actual))
                    links(ready, controlled, allowed, actual)
                    helpers.account(ready, controlled, cfg)
                    counts['A0制御旧6一致'] += 1
                    counts['新設準備対応検査'] += 1
    assert all(value == 26 for value in counts.values())
    return counts


def main() -> None:
    """機能: 合成と既知通常方式の互換を監査し、指紋と検査件数を保存する。

    引数: --synthetic-only (bool)。返り値: なし (None)。新実相場格子・現在データは利用しない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--synthetic-only', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = helpers.deny
    socket.create_connection = helpers.deny
    urllib.request.OpenerDirector.open = helpers.deny
    sources = [HERE.parent / name for name in ('wave_v33/engine_dynamic_atr.py', 'wave_v33/dynamic_atr_engine_audit.py',
                                              'wave_v23/inputs.pkl', 'wave_v27/directions/H019.npz', 'wave_v30/探索条件の固定.json')]
    before = {str(p): digest(p) for p in sources}
    assert before[str(sources[0])] == 'cf4381e04704ae77d2bcaa824e7f66bad092648276faf40de014fdfd974ec35b'
    checks = synthetic()
    compatible = {} if args.synthetic_only else compatibility()
    assert before == {str(p): digest(p) for p in sources}
    result = {'全合格': not args.synthetic_only, '合成全合格': True, '合成件数': len(checks), '合成検査': checks,
              '既知互換': compatible, '新しいAt制御の実相場再生': False, '成績による選別': False,
              '現在保存物使用': False, 'API取得数': 0, '元ファイル不変': True, '元SHA256': before,
              'engine_SHA256': digest(HERE / 'engine_scheduler.py'), '検査実装SHA256': digest(Path(__file__)),
              'PREPARE_COLUMNS': engine.PREPARE_COLUMNS, 'ENTRY_PREPARATION_COLUMNS': engine.ENTRY_PREPARATION_COLUMNS}
    (HERE / 'scheduler_engine_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('合成', len(checks), '件、通常旧6結果/A0同期', compatible, '新At制御実相場なし。', flush=True)


if __name__ == '__main__':
    main()
