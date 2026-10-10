"""条件付き短縮の同期・線進行を合成で反証し、固定A0だけを旧26入力と照合する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wave_v33'))
import dynamic_atr_engine_audit as helpers
sys.path.insert(0, str(HERE.parent / 'wave_v34'))
import engine_scheduler as previous
import scheduler_engine_audit as base
sys.path.insert(0, str(HERE))
import engine_conditional as engine

OLD_FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve', 'prepare_events', 'entry_preparations')
C = {name: i for i, name in enumerate(engine.CONDITIONAL_COLUMNS)}
T = {name: i for i, name in enumerate(engine.TRAIL_EVENT_COLUMNS)}


def digest(path: Path) -> str:
    """機能: 読取対象の変更を検知する指紋を求める。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_rows(direction: np.ndarray) -> np.ndarray:
    """機能: 合成根拠を当該行に公開する参照行列を作る。

    引数: direction (ndarray[int8])。返り値: 参照行 (ndarray[int64])。
    """
    return np.where(direction != 0, np.arange(len(direction)), -1).astype(np.int64)


def paired(ready: dict, state: np.ndarray, cfg: dict, tracking: np.ndarray,
           deterioration: np.ndarray, mode: int, observed: bool = False) -> tuple:
    """機能: 現在の入力から独立影を再生成して実側へ新設行だけ渡す。

    引数: ready/cfg (dict)、state/tracking/deterioration (ndarray)、mode (int)、observed (bool)。
    返り値: 影・実・許可列 (tuple[dict,dict,ndarray])。
    """
    shadow = engine.run(ready, state, cfg, True, width_mode=0, observed_fill=observed)
    allowed = base.mask_from(shadow, len(state))
    actual = engine.run(ready, state, cfg, True, width_mode=mode, observed_fill=observed,
                        trail_atr=tracking, prepare_allow=allowed, deterioration=deterioration,
                        deterioration_source=source_rows(deterioration))
    return shadow, actual, allowed


def synchronization(ready: dict, shadow: dict, actual: dict, allowed: np.ndarray) -> None:
    """機能: 全準備・全新規が一致し、実全返済が影より遅れないことを検査する。

    引数: ready/shadow/actual (dict)、allowed (ndarray[bool])。返り値: なし (None)。
    """
    base.links(ready, actual, allowed, shadow)
    np.testing.assert_array_equal(actual['prepare_events'], shadow['prepare_events'])
    np.testing.assert_array_equal(actual['entry_preparations'], shadow['entry_preparations'])
    np.testing.assert_array_equal(actual['orders'][actual['orders'][:, 7] == 1],
                                  shadow['orders'][shadow['orders'][:, 7] == 1])
    assert len(actual['cycles']) == len(shadow['cycles'])
    np.testing.assert_array_equal(actual['cycles'][:, [0, 1, 4, 5, 8]], shadow['cycles'][:, [0, 1, 4, 5, 8]])
    assert np.all(actual['cycles'][:, 2] <= shadow['cycles'][:, 2]), '実返済が固定幅の影より遅れた'


def independent_lines(ready: dict, result: dict, cfg: dict, tracking: np.ndarray,
                      deterioration: np.ndarray, mode: int) -> None:
    """機能: 原価格・ATR・悪化列だけから追跡候補とイベントを別式で復元する。

    引数: ready/result/cfg (dict)、tracking/deterioration (ndarray)、mode (int)。返り値: なし (None)。
    エンジンの候補計算関数は呼ばず、保有組ごとの極値と有利側累積値を使う。
    """
    tick = ready['tick']; expected_events = []
    opens = {int(row[2]): row for row in result['orders'] if row[7] == 1}
    for cycle in result['cycles']:
        campaign, first, last = map(int, cycle[:3]); direction = int(cycle[8]); a0 = cycle[5]
        anchor = opens[campaign][5]; extreme = anchor; at = a0; at_source = -1
        floor = np.nan; line_source = -1; evidence_row = -1; evidence_source = -1
        for row in range(first, last):
            if np.isfinite(tracking[row]) and tracking[row] > 0:
                at = max(tracking[row], 2 * tick); at_source = row
            price = ready['last'][row]
            allowed = mode == 1 or (mode == 2 and deterioration[row] == -direction)
            used = min(a0, at) if allowed else a0
            prior = floor; fixed = np.nan; extra = np.nan; selected = np.nan; advanced = 0; kind = 0
            if np.isfinite(price) and price > 0:
                extreme = max(extreme, price) if direction > 0 else min(extreme, price)
                if direction * (extreme - anchor) >= 1.5 * a0:
                    value = (extreme - direction * 3 * a0) / tick
                    fixed = (np.floor(value + 1e-9) if direction > 0 else np.ceil(value - 1e-9)) * tick
                    selected = fixed; candidate_kind = 1
                    if allowed:
                        value = (extreme - direction * 3 * used) / tick
                        extra = (np.floor(value + 1e-9) if direction > 0 else np.ceil(value - 1e-9)) * tick
                        if direction * (extra - fixed) > 0:
                            selected = extra; candidate_kind = 2 if mode == 1 else 3
                    if not np.isfinite(floor) or direction * (selected - floor) > 0:
                        floor = selected; line_source = row; advanced = 1; kind = candidate_kind
                        evidence_row = row if kind == 3 else -1
                        evidence_source = row if kind == 3 else -1
                        expected_events.append([row, campaign, direction, prior, fixed, extra, floor, kind,
                                                a0, at, used, at_source, evidence_row, evidence_source,
                                                int(deterioration[row]) if kind == 3 else 0])
            expected = [direction, deterioration[row], row if deterioration[row] else -1, int(allowed),
                        a0, at, used, prior, fixed, extra, selected, floor, advanced, kind,
                        at_source, line_source, evidence_row, evidence_source]
            np.testing.assert_allclose(result['conditional_curve'][row], expected, atol=1e-9, rtol=0, equal_nan=True)
            assert result['atr_curve'][row, helpers.A['initial_risk']] == cfg['initial_qty'] * a0
    expected = np.array(expected_events, dtype=float).reshape((-1, len(T)))
    np.testing.assert_allclose(result['trail_events'], expected, atol=1e-9, rtol=0, equal_nan=True)


def checked_case(case: tuple, deterioration: np.ndarray, mode: int, observed: bool = False,
                 reflect: bool = True) -> tuple:
    """機能: 合成入力の同期・会計・別式・買売反射をまとめて検査する。

    引数: case (tuple)、deterioration (ndarray)、mode (int)、observed/reflect (bool)。
    返り値: 影・実結果 (tuple[dict,dict])。
    """
    ready, state, cfg, tracking = case
    shadow, actual, allowed = paired(ready, state, cfg, tracking, deterioration, mode, observed)
    synchronization(ready, shadow, actual, allowed)
    helpers.account(ready, actual, cfg); helpers.account(ready, shadow, cfg)
    independent_lines(ready, actual, cfg, tracking, deterioration, mode)
    if reflect:
        mirrored = deepcopy(ready); mirrored['last'] = 20000. - ready['last']
        opposite_shadow, opposite, gate = paired(mirrored, -state, cfg, tracking, -deterioration, mode, observed)
        synchronization(mirrored, opposite_shadow, opposite, gate)
        helpers.account(mirrored, opposite, cfg)
        independent_lines(mirrored, opposite, cfg, tracking, -deterioration, mode)
        np.testing.assert_allclose(actual['trades'][:, 10], opposite['trades'][:, 10], atol=1e-7, rtol=0)
        np.testing.assert_array_equal(actual['orders'][:, [0, 1, 2, 4, 6, 7]], opposite['orders'][:, [0, 1, 2, 4, 6, 7]])
        np.testing.assert_array_equal(actual['orders'][:, 3], -opposite['orders'][:, 3])
        np.testing.assert_allclose(actual['orders'][:, 5] + opposite['orders'][:, 5], 20000., atol=1e-7, rtol=0)
    return shadow, actual


def prefix(result: dict, reference: dict, cut: int) -> None:
    """機能: 切断前の旧結果と新しい追跡記録が一致することを検査する。

    引数: result/reference (dict)、cut (int)。返り値: なし (None)。
    """
    base.prefix_equal(result, reference, cut)
    np.testing.assert_array_equal(result['conditional_curve'][:cut], reference['conditional_curve'][:cut])
    np.testing.assert_array_equal(result['trail_events'][result['trail_events'][:, 0] < cut],
                                  reference['trail_events'][reference['trail_events'][:, 0] < cut])


def frozen_line_negative() -> dict:
    """機能: 条件偽の時に固定線まで凍結する壊れた実装を合成反例で拒否する。

    引数: なし。返り値: 拒否理由と行番号 (dict)。元実装は変更しない。
    """
    original = (HERE / 'engine_conditional.py').read_text(encoding='utf-8')
    old = 'if np.isfinite(par[3]) and d*(extreme-anchor)>=par[18]*a:'
    assert original.count(old) == 1
    # 一度始動した後、条件が偽なら固定3A0の新しい高安追跡まで止めてしまう負例。
    broken = original.replace(old, old[:-1] + ' and (not np.isfinite(main_floor) or shortening):')
    path = HERE / '合成負例_固定線凍結.py'; path.write_text(broken, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('conditional_frozen_mutant', path)
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    ready, state, cfg, at = base.fixture([100., 101., 110., 120., 107.])
    bad = np.zeros(len(state), dtype=np.int8)
    shadow, good, mask = paired(ready, state, cfg, at, bad, 2)
    wrong = module.run(ready, state, cfg, True, width_mode=2, trail_atr=at, prepare_allow=mask,
                       deterioration=bad, deterioration_source=source_rows(bad))
    assert good['cycles'][0, 2] == shadow['cycles'][0, 2] == 4
    assert wrong['cycles'][0, 2] > shadow['cycles'][0, 2]
    rejected = False
    try:
        synchronization(ready, shadow, wrong, mask)
    except AssertionError:
        rejected = True
    assert rejected
    return {'検査': '条件偽で固定線を凍結する壊れた実装を拒否', '一致': True,
            '正常返済行': int(good['cycles'][0, 2]), '壊れた返済行': int(wrong['cycles'][0, 2]),
            '正常更新線': good['conditional_curve'][3, C['final_level']],
            '凍結された線': wrong['conditional_curve'][3, C['final_level']],
            '負例SHA256': digest(path)}


def synthetic() -> list[dict]:
    """機能: 結果を選ばず固定した人工経路と境界で機構を反証する。

    引数: なし。返り値: 検査記録 (list[dict])。新実相場は使用しない。
    """
    checks = []
    # ----------------------------------------
    # ATRがA0を超えても固定より遅くならず、早期返済後も次の影準備へ完全同期する。
    paths = [
        base.fixture([100., 101., 120., 113., 113., 114., 107., 110., 111.],
                     [0., 1., 2., 3., 303., 304., 600., 900., 901.],
                     [4., 4., 2., 2., 2., 20., 20., 20., 20.]),
        base.fixture([100., 101., 120., 107., 107., 106., 90., 90., 90., 91., 120., 107.],
                     [0., 1., 2., 3., 303., 304., 305., 603., 606., 607., 608., 609.],
                     [4., 4., 10., 10., 10., 10., 2., 2., 2., 2., 2., 2.]),
        base.fixture([100., 100., 101., 110., 110., 95., 95., 96.],
                     [0., 0., 0., 1., 1., 2., 302., 303.], [4., 4., 4., 2., 20., 2., 2., 2.])]
    for case in paths:
        for mode in (1, 2):
            for observed in (False, True):
                bad = -case[1]
                checked_case(case, bad, mode, observed)
    checks.append({'検査': '拡縮・飛値・同値時刻・早期全返済・自身休止・部分返済・場末で全新規準備が影と一致', '一致': True, '組合せ': 12})

    # ----------------------------------------
    case = base.fixture([100., 101., 120., 110., 110.], tracking=[4., 4., 4., 2., 2.])
    bad = np.zeros(len(case[1]), dtype=np.int8); bad[3] = -1
    shadow, result = checked_case(case, bad, 2)
    assert not np.any(result['orders'][:, 0] == 3)
    assert result['trades'][-1, 7] == 4 and result['trades'][-1, 5] == 110
    assert result['conditional_curve'][3, C['advance_kind']] == 3
    assert result['conditional_curve'][3, C['final_level']] == 114
    checks.append({'検査': '同一価格で悪化確認とATR縮小が揃っても新線は次行から、既通過は次行観測価格', '一致': True})

    case = base.fixture([100., 101., 110., 110., 110., 109.], tracking=[4., 4., 4., 2., 20., 20.])
    bad = np.zeros(len(case[1]), dtype=np.int8); bad[3] = -1
    _, result = checked_case(case, bad, 2)
    np.testing.assert_array_equal(result['conditional_curve'][2:5, C['final_level']], [98., 104., 104.])
    assert result['conditional_curve'][4, C['shortening_enabled']] == 0
    assert result['conditional_curve'][4, C['line_evidence_row']] == 3
    checks.append({'検査': '悪化解除・ATR拡大でも既設短縮線と過去根拠を維持し、条件発生と実線進行を区別', '一致': True})

    ready, state, cfg, at = case
    remembered_source = source_rows(bad); remembered_source[3] = 1
    shadow = engine.run(ready, state, cfg, True)
    mask = base.mask_from(shadow, len(state))
    full = engine.run(ready, state, cfg, True, width_mode=2, trail_atr=at,
                      prepare_allow=mask, deterioration=bad, deterioration_source=remembered_source)
    small = engine.run(ready, state, cfg, False, width_mode=2, trail_atr=at,
                       prepare_allow=mask, deterioration=bad, deterioration_source=remembered_source)
    source_event = full['trail_events'][full['trail_events'][:, T['advance_kind']] == 3][0]
    assert source_event[T['evidence_row']] == 3 and source_event[T['evidence_source_row']] == 1
    assert full['conditional_curve'][4, C['line_evidence_source_row']] == 1
    base.same(full, small, ('trades', 'cycles', 'orders', 'stats', 'prepare_events', 'entry_preparations', 'trail_events'))
    assert small['conditional_curve'].shape == (1, len(C))
    wrong_side = engine.run(ready, state, cfg, True, width_mode=2, trail_atr=at, deterioration=state)
    no_shortening = engine.run(ready, state, cfg, True, width_mode=0, trail_atr=at)
    base.same(wrong_side, no_shortening, OLD_FIELDS)
    checks.append({'検査': '過去の根拠参照行を持続記録・詳細省略でもイベント一致・保有と同方向の悪化列では追加しない', '一致': True})

    case = base.fixture([100., 101., 106., 106., 107., 107.], tracking=[4., 4., 2., 2., 2., 2.])
    _, result = checked_case(case, -case[1], 2)
    assert not result['atr_curve'][1:4, helpers.A['trail_active']].any()
    assert result['atr_curve'][4, helpers.A['trail_level']] == 101
    checks.append({'検査': 'Atが小さくても1.5A0前には始動せず初期リスク・部分利確閾値はA0のまま', '一致': True})

    case = base.fixture([100., 101., 102., 103., 104., 105., 106., 107.],
                        tracking=[np.nan, np.nan, 3., np.nan, np.inf, -1., 0., .5])
    _, result = checked_case(case, -case[1], 2)
    np.testing.assert_array_equal(result['atr_curve'][1:8, helpers.A['current_atr']], [4., 3., 3., 3., 3., 3., 2.])
    checks.append({'検査': '初期欠測A0・直前有効At維持・2呼値下限', '一致': True})

    # ----------------------------------------
    # 価格欠測行には新線を置かず、公開Atだけ保持する。旧版の曲線欠測形式を維持する。
    case = base.fixture([100., 101., 110., np.nan, 110., 100.], tracking=[4., 4., 4., 2., np.nan, 20.])
    ready, state, cfg, at = case; bad = -state
    shadow, result, allowed = paired(ready, state, cfg, at, bad, 2)
    synchronization(ready, shadow, result, allowed)
    independent_lines(ready, result, cfg, at, bad, 2)
    assert not (result['orders'][:, 0] == 3).any() and not (result['trail_events'][:, 0] == 3).any()
    assert result['conditional_curve'][3, C['current_atr']] == 2
    checks.append({'検査': '価格欠測は約定と線更新を行わずAt公開値だけを保持', '一致': True})

    # ----------------------------------------
    random_count = 0; future_count = 0
    for seed in range(16):
        rng = np.random.default_rng(seed); n = 300
        prices = (1000 + np.cumsum(rng.choice([-4., -2., 0., 2., 4.], n))).tolist()
        tracking = rng.choice([2., 3., 4., 8., np.nan], n).tolist()
        case = base.fixture(prices, np.arange(n, dtype=float).tolist(), tracking)
        ready, state, cfg, at = case
        ready['time_s'] = np.r_[np.arange(n) * 20., 10000., 10001.]
        state[:] = np.repeat(rng.choice([-1, 0, 1], 7), 50)[:len(state)]
        bad = rng.choice([-1, 0, 1], len(state)).astype(np.int8)
        for cap in (10, 20):
            cfg = deepcopy(cfg); cfg['audit_cap'] = cap; cfg['initial_qty'] = cap // 2
            for mode in (1, 2):
                for observed in (False, True):
                    shadow, result = checked_case((ready, state, cfg, at), bad, mode, observed)
                    random_count += 1
                    if cap == 10 and not observed:
                        cut = 137
                        shortened = {k: v[:cut].copy() if isinstance(v, np.ndarray) else v for k, v in ready.items()}
                        ps, pa, _ = paired(shortened, state[:cut], cfg, at[:cut], bad[:cut], mode)
                        prefix(pa, result, cut); prefix(ps, shadow, cut)
                        changed = deepcopy(ready); changed['last'][cut:] = 1500. + np.arange(len(state) - cut)
                        changed['atr'][cut:] = 40.
                        changed_state = state.copy(); changed_state[cut:] *= -1
                        changed_at = at.copy(); changed_at[cut:] = 50.
                        changed_bad = bad.copy(); changed_bad[cut:] *= -1
                        fs, fa, _ = paired(changed, changed_state, cfg, changed_at, changed_bad, mode)
                        prefix(fa, result, cut); prefix(fs, shadow, cut)
                        future_count += 1
    checks.append({'検査': '固定16seed人工経路×枚数2×方式2×価格モデル2で全準備新規一致・早い又は同時返済・会計・左右反射', '一致': True, '組合せ': random_count})
    checks.append({'検査': '影を再生成した未来切断と未来価格/初期ATR/At/入口/悪化方向改変で過去不変', '一致': True, '組合せ': future_count})
    checks.append(frozen_line_negative())

    # ----------------------------------------
    ready, state, cfg, at = base.fixture([100., 101., 110., 100.])
    bad = -state; failures = 0
    for kwargs in ({'width_mode': 3}, {'deterioration': bad.astype(float)},
                   {'deterioration': bad, 'deterioration_source': np.arange(len(bad), dtype=np.int64) + 1},
                   {'deterioration': bad, 'deterioration_source': np.full(len(bad), -1, dtype=np.int64)}):
        try:
            engine.run(ready, state, cfg, **kwargs)
        except ValueError:
            failures += 1
    assert failures == 4
    checks.append({'検査': '不正モード・方向型・未来根拠行・非中立の不明根拠行を拒否', '一致': True, '件数': failures})
    return checks


def compatibility() -> dict:
    """機能: 既知H019固定A0の旧8結果と制御恒等だけを全26入力で確認する。

    引数: なし。返り値: 互換比較数 (dict)。新しい最小幅の実相場損益は計算しない。
    """
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    count = 0
    with np.load(HERE.parent / 'wave_v27/directions/H019.npz') as archive:
        for key, ready in inputs.items():
            state = archive['|'.join(key)]; cfg = helpers.config(key[1], ready)
            reference = previous.run(ready, state, cfg, True, width_mode=0)
            actual = engine.run(ready, state, cfg, True, width_mode=0)
            base.same(actual, reference, OLD_FIELDS)
            mask = base.mask_from(actual, len(state))
            controlled = engine.run(ready, state, cfg, True, width_mode=0, prepare_allow=mask)
            base.same(controlled, actual, tuple(actual))
            synchronization(ready, actual, controlled, mask)
            count += 1
    assert count == 26
    return {'固定A0通常の旧8完全一致': count, '固定A0同期の全10完全一致': count}


def main() -> None:
    """機能: 合成と許可された旧A0同値だけを実行し、監査記録を保存する。

    引数: --synthetic-only (bool)。返り値: なし (None)。現在APIと保存ライブは禁止。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--synthetic-only', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = helpers.deny; socket.create_connection = helpers.deny
    urllib.request.OpenerDirector.open = helpers.deny
    sources = [HERE.parent / 'wave_v34/engine_scheduler.py', HERE.parent / 'wave_v23/inputs.pkl',
               HERE.parent / 'wave_v27/directions/H019.npz', HERE.parent / 'wave_v30/探索条件の固定.json']
    before = {str(path): digest(path) for path in sources}
    checks = synthetic()
    matches = {} if args.synthetic_only else compatibility()
    assert before == {str(path): digest(path) for path in sources}
    result = {'全合格': not args.synthetic_only, '合成全合格': True, '合成件数': len(checks), '合成検査': checks,
              '旧固定互換': matches, '新最小幅条件の実相場再生': False, '成績選抜': False,
              '現在保存物使用': False, 'API取得数': 0, '元ファイル不変': True, '元SHA256': before,
              'engine_SHA256': digest(HERE / 'engine_conditional.py'), '監査実装SHA256': digest(Path(__file__)),
              'CONDITIONAL_COLUMNS': engine.CONDITIONAL_COLUMNS, 'TRAIL_EVENT_COLUMNS': engine.TRAIL_EVENT_COLUMNS}
    (HERE / 'conditional_engine_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'合成件数': len(checks), '旧固定互換': matches, '新実相場なし': True}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
