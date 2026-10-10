"""仮想運転の新設だけを許可する接続を独立生成・照合する。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent / 'wave_v33'))
import accounting_audit_v2 as baseline
sys.path.insert(0, str(HERE))
import engine_scheduler as engine

OLD_FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve')
EXTRA_FIELDS = ('prepare_events', 'entry_preparations')


def replay(ready: dict, state: np.ndarray, tracking: np.ndarray, config: dict, spec: dict) -> dict:
    """機能: 実運転に依存しない影を再生し、新設行だけの許可で実運転する。

    引数: ready/config/spec (dict)、state/tracking (ndarray)。返り値: 実結果に影と許可を付けた辞書 (dict)。
    影へ追跡用遅延ATRは渡さず、初期ATRだけで旧固定A0を運転する。
    """
    shadow = engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=spec['observed_fill'])
    allow = np.zeros(len(state), dtype=np.bool_)
    allow[shadow['prepare_events'][:, 1].astype(np.int64)] = True
    actual = engine.run(ready, state, config, detail=True, width_mode=spec['dynamic_trail_atr'],
                        observed_fill=spec['observed_fill'], trail_atr=tracking,
                        prepare_allow=allow if spec['gated'] else None)
    actual['shadow'], actual['allow'] = shadow, allow
    return actual


def same_results(actual: dict, expected: dict, fields: tuple = OLD_FIELDS) -> None:
    """機能: 指定した台帳・曲線の全配列を欠測も含めて厳密照合する。

    引数: actual/expected (dict)、fields (tuple[str])。返り値: なし (None)。
    """
    for name in fields:
        baseline.exact(actual[name], expected[name], name)


def preparation_links(ready: dict, state: np.ndarray, config: dict, actual: dict, gated: bool) -> dict:
    """機能: 原本価格から準備値を再計算し、約定の新設起点と影の同じ準備を照合する。

    引数: ready/config/actual (dict)、state (ndarray)、gated (bool)。返り値: 照合件数 (dict)。
    """
    prepared, linked = actual['prepare_events'], actual['entry_preparations']
    baseline.exact(prepared[:, 0], np.arange(len(prepared)), '新設ID連番')
    rows = prepared[:, 1].astype(np.int64)
    assert len(rows) == len(set(rows)) and np.all(np.diff(rows) > 0)
    assert np.all(rows >= 0) and np.all(rows < len(state))
    assert np.isin(prepared[:, 2], (-1, 1)).all()
    baseline.exact(prepared[:, 2], state[rows], '新設方向')
    atr = np.maximum(ready['atr'][rows], 2 * ready['tick'])
    baseline.exact(prepared[:, 4], atr, '新設A0')
    unrounded = (ready['last'][rows] + prepared[:, 2] * config['entry_atr'] * atr) / ready['tick']
    level = np.where(prepared[:, 2] > 0, np.ceil(unrounded - 1e-9), np.floor(unrounded + 1e-9)) * ready['tick']
    baseline.exact(prepared[:, 3], level, '原本から新設価格')
    baseline.exact(prepared[:, 5], ready['time_s'][rows] + config['ttl_seconds'], '新設期限')
    assert np.all(prepared[:, 6] == config['initial_qty'])
    assert np.all(ready['time_s'][rows] >= ready['start'] + config['warmup_min'] * 60.)
    assert np.all(ready['time_s'][rows] < ready['limit'] - config['entry_cutoff_min'] * 60.)
    assert np.all(actual['curve'][rows, 2:4] == 0)
    opened = actual['orders'][actual['orders'][:, 7] == 1]
    assert len(opened) == len(linked) == len(actual['cycles'])
    source_by_row = {int(r[1]): r for r in actual['shadow']['prepare_events']}
    shadow_fill = {int(r[3]): r for r in actual['shadow']['entry_preparations']}
    shadow_orders = {int(r[2]): r for r in actual['shadow']['orders'] if r[7] == 1}
    if gated:
        assert actual['allow'][rows].all()
        for row in prepared:
            baseline.exact(row[1:], source_by_row[int(row[1])][1:], '影と実の新設属性')
    for opening, entry in zip(opened, linked, strict=True):
        campaign, filled, identity, fresh = map(int, entry)
        event = prepared[identity]
        assert fresh == int(event[1]) and fresh <= opening[1] < filled
        assert opening[0] == filled and opening[2] == campaign
        assert opening[3] == event[2] and opening[4] == event[6]
        assert actual['cycles'][campaign, 5] == event[4]
        if gated:
            assert fresh in shadow_fill, '実が新規約定した準備は影も約定する'
            sf = shadow_fill[fresh]
            so = shadow_orders[int(sf[0])]
            assert filled == int(sf[1])
            baseline.exact(opening[[0, 1, 3, 4, 5, 6, 7]], so[[0, 1, 3, 4, 5, 6, 7]], '影と実の採用新規約定')
    return dict(新設数=len(prepared), 新規起点数=len(linked), 影新設数=len(actual['shadow']['prepare_events']),
                準備独立値一致=True, 約定起点一致=True, 影新設対応一致=gated)


def prefix_equal(actual: dict, changed: dict, count: int) -> None:
    """機能: 影から再生成した許可を含め、切断前の全結果が同じか検査する。

    引数: actual/changed (dict)、count (int)。返り値: なし (None)。
    """
    for a, b in ((actual, changed), (actual['shadow'], changed['shadow'])):
        baseline.prefix_equal(a, b, count)
        for name, column in (('prepare_events', 1), ('entry_preparations', 1)):
            baseline.exact(a[name][a[name][:, column] < count], b[name][b[name][:, column] < count], '未来不変/' + name)
    baseline.exact(actual['allow'][:count], changed['allow'][:count], '影許可の未来不変')


def future_checks(ready: dict, state: np.ndarray, tracking: np.ndarray, config: dict, spec: dict, actual: dict) -> None:
    """機能: 切断・未来値改変ごとに影を再生し、実から影へ逆向き依存しない接続を検査する。

    引数: ready/config/spec/actual (dict)、state/tracking (ndarray)。返り値: なし (None)。
    """
    count = max(2, int(len(state) * .37))
    truncated = replay(baseline.previous.clipped(ready, count), state[:count], tracking[:count], config, spec)
    prefix_equal(actual, truncated, count)
    count = max(2, int(len(state) * .73))
    changed = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
    changed['last'][count:] += np.nan_to_num(ready['atr'][count:] * 3., nan=10 * ready['tick'])
    changed['atr'][count:] *= 1.7
    direction = state.copy(); direction[count:] = np.where(direction[count:] == 0, 1, -direction[count:])
    at = tracking.copy(); at[count:] = 50000.
    altered = replay(changed, direction, at, config, spec)
    prefix_equal(actual, altered, count)


def reflection(ready: dict, state: np.ndarray, tracking: np.ndarray, config: dict, spec: dict, actual: dict) -> None:
    """機能: 影と実を同時に上下反射し、許可・起点・約定・損益の対称性を確認する。

    引数: ready/config/spec/actual (dict)、state/tracking (ndarray)。返り値: なし (None)。
    """
    offset = 2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick']
    reflected = dict(ready, last=offset - ready['last'])
    mirror = replay(reflected, -state, tracking, config, spec)
    baseline.exact(actual['allow'], mirror['allow'], '反射影許可')
    for left, right in ((actual, mirror), (actual['shadow'], mirror['shadow'])):
        baseline.previous.reconstruct(reflected, right, ready['symbol'])
        a, b = left['orders'], right['orders']
        baseline.previous.close(a[:, [0, 1, 2, 4, 6, 7]], b[:, [0, 1, 2, 4, 6, 7]], '反射注文')
        baseline.previous.close(a[:, 3], -b[:, 3], '反射方向')
        baseline.previous.close(a[:, 5], offset - b[:, 5], '反射価格')
        a, b = left['trades'], right['trades']
        baseline.previous.close(a[:, [0, 1, 3, 6, 7, 8, 9, 10]], b[:, [0, 1, 3, 6, 7, 8, 9, 10]], '反射返済')
        baseline.previous.close(a[:, 2], -b[:, 2], '反射元玉')
        baseline.previous.close(a[:, 4:6], offset - b[:, 4:6], '反射建値返済')
        baseline.previous.close(left['curve'][:, [0, 1, 4]], right['curve'][:, [0, 1, 4]], '反射曲線')
        baseline.previous.close(left['curve'][:, [2, 3]], right['curve'][:, [3, 2]], '反射在庫')
        baseline.exact(left['entry_preparations'], right['entry_preparations'], '反射新規起点')
        a, b = left['prepare_events'], right['prepare_events']
        baseline.exact(a[:, [0, 1, 4, 5, 6]], b[:, [0, 1, 4, 5, 6]], '反射新設')
        baseline.exact(a[:, 2], -b[:, 2], '反射新設方向')
        baseline.previous.close(a[:, 3], offset - b[:, 3], '反射新設価格')
        for name in ('initial_atr', 'current_atr', 'used_width_atr', 'initial_risk', 'current_atr_source_row', 'trail_source_row'):
            i = engine.ATR_COLUMNS.index(name)
            baseline.exact(left['atr_curve'][:, i], right['atr_curve'][:, i], '反射ATR/' + name)
