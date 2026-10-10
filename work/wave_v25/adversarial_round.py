"""発見済み候補へ同じ反証を適用し、都合のよい変更条件を採用しない。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse
import hashlib
import math
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
sys.path.insert(0, str(OLD))
import engine
import managers
import research
import discovery_runner as runner

INPUTS, OLD_DIRECTIONS, SPECS, FEATURES = {}, {}, {}, {}
OBSERVED = None
VALIDATION_SHA = ''


def initialize() -> None:
    """機能: 各ワーカーの基準入力と隔離した観測価格エンジンを読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, OLD_DIRECTIONS, SPECS, OBSERVED, FEATURES, VALIDATION_SHA
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    OLD_DIRECTIONS = pickle.loads((OLD / 'directions.pkl').read_bytes())
    SPECS = runner.read(HERE / '探索条件の固定.json')
    FEATURES = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    VALIDATION_SHA = runner.digest(HERE / '反証仕様の固定.json')
    import engine_observed_v25
    OBSERVED = engine_observed_v25


def load_state(identifier: str) -> dict:
    """機能: 発見段階で保存した原本行ごとの方向を読み込む。

    引数: identifier (str)。返り値: 区間別方向 (dict)。
    """
    with np.load(HERE / 'directions' / f'{identifier}.npz') as archive:
        return {tuple(key.split('|')): archive[key] for key in archive.files}


def lagged(ready: dict, state: np.ndarray, seconds: int) -> np.ndarray:
    """機能: 未来の信号を用いず方向だけを指定秒数遅らせる。

    引数: ready (dict)、state (ndarray)、seconds (int)。返り値: 遅延方向 (ndarray)。
    """
    if seconds < 0:
        raise ValueError('負の遅延は禁止です')
    if seconds == 0:
        return state.copy()
    pos = np.searchsorted(ready['time_s'], ready['time_s'] - seconds, side='right') - 1
    out = np.zeros(len(pos), dtype=np.int8)
    good = pos >= 0
    out[good] = state[pos[good]]
    return out


def random_direction(ready: dict, seed: int, cadence: int, gate: np.ndarray | None = None) -> np.ndarray:
    """機能: 時刻だけで独立した売買方向を作り、任意で元信号の発火時刻に限定する。

    引数: ready (dict)、seed/cadence (int)、gate (ndarray|None)。返り値: 方向 (ndarray)。
    gateはその行の中立/非中立だけを参照する。未来の発火頻度や損益を使わない。
    """
    # 同じセッションの両銘柄で同一乱数を使い、共通市場方向を対照から取り除かない。
    identity = f'v25|{seed}|{ready["session"]}|{cadence}'.encode()
    generator = np.random.default_rng(int.from_bytes(hashlib.sha256(identity).digest()[:8], 'little'))
    blocks = np.maximum(0, np.floor((ready['time_s'] - ready['start']) / cadence).astype(np.int64))
    values = (generator.integers(0, 2, size=int(blocks[-1]) + 1, dtype=np.int64) * 2 - 1).astype(np.int8)
    out = values[blocks]
    out[ready['time_s'] < ready['start'] + 1200] = 0
    if gate is not None:
        out[gate == 0] = 0
    return out


def replay(name: str, direction: dict, management: dict, observed: bool = False, cap_one: bool = False) -> dict:
    """機能: 対照を同じ原本・全玉管理で再生し金額と枚数を検算する。

    引数: name (str)、direction/management (dict)、observed/cap_one (bool)。返り値: 結果 (dict)。
    """
    rows = []
    module = OBSERVED if observed else engine
    for key, ready in INPUTS.items():
        config = managers.make_config(management, key[1], ready)
        if cap_one:
            config['audit_cap'] = 1
            config['initial_qty'] = 1
            config['add_qty'] = min(config['add_qty'], 1)
            config['cover_add'] = min(config['cover_add'], 1)
        result = module.run(ready, direction[key], config)
        row = research.summarize(result, config, key[1], key[0], name)
        row['two_largest_cycle_profits'] = sorted(
            [float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        rows.append(row)
    return {'case': name, 'symbols': runner.diagnostics(rows), 'rows': rows}


def acceptable(result: dict, pf: float = 1.20) -> bool:
    """機能: 感度条件でも両銘柄で最低限の収支と損益比が残るか判定する。

    引数: result (dict)、pf (float)。返り値: 条件通過 (bool)。
    """
    return all(r['net_yen'] > 0 and (r['money_ratio'] or 0) >= pf for r in result['symbols'].values())


def audit(candidate: dict) -> dict:
    """機能: 一候補に基準再現・遅延・観測約定・近傍・部品交換を施す。

    引数: candidate (dict)。返り値: 反証結果 (dict)。
    """
    path = HERE / 'adversarial' / f'{candidate["id"]}.json.gz'
    if path.exists():
        saved = runner.read(path)
        assert saved['validation_sha'] == VALIDATION_SHA, '異なる反証版の結果は再利用できません'
        return saved
    state = load_state(candidate['signal_id'])
    management = next(x for x in SPECS['managers'] if x['id'] == candidate['manager_id'])
    standard = next(x for x in managers.manager_catalog() if x['id'] == 'G08')
    cases = [replay('基準再現', state, management)]
    for symbol in ['TOPIX', 'NK225']:
        for field in ['net_yen', 'gross_profit_yen', 'gross_loss_yen', 'closed_units']:
            assert cases[0]['symbols'][symbol][field] == candidate['symbols'][symbol][field]
    for seconds in [1, 5, 15]:
        delayed = {key: lagged(ready, state[key], seconds) for key, ready in INPUTS.items()}
        cases.append(replay(f'方向{seconds}秒遅延', delayed, management))
    cases.append(replay('観測価格約定', state, management, observed=True))
    neighbors, skipped = [], []
    for parameter in ['entry_atr', 'stop_atr', 'main_trail']:
        if parameter == 'entry_atr' and management['changes'].get('entry_mode', 0) == 2:
            skipped.append('成行新規ではentry_atrを使用しないため近傍件数へ含めない')
            continue
        for factor in [.8, 1.2]:
            changes = dict(management['changes'])
            changes[parameter] = changes.get(parameter, managers.BASE[parameter]) * factor
            result = replay(f'{parameter}×{factor}', state, dict(management, changes=changes))
            neighbors.append(result)
            cases.append(result)
    cases.append(replay('方向だけ反転', {key: -value for key, value in state.items()}, management))
    cases.append(replay('F32へ方向を交換', OLD_DIRECTIONS['F32'], management))
    cases.append(replay('管理をG08へ交換', state, standard))
    cases.append(replay('固定F32_G08', OLD_DIRECTIONS['F32'], standard))
    cases.append(replay('片方向1枚へ保有制限', state, management, cap_one=True))
    for side in [-1, 1]:
        directions = {key: np.where(ready['time_s'] >= ready['start'] + 1200, side, 0).astype(np.int8) for key, ready in INPUTS.items()}
        cases.append(replay('常時買い' if side > 0 else '常時売り', directions, management))
    flags = []
    if candidate['failures']:
        flags.append('発見の最低条件未達')
    if not all(acceptable(c) for c in cases[1:5]):
        flags.append('遅延または観測約定で損益比1.20未満か非黒字')
    if sum(acceptable(c) for c in neighbors) < math.ceil(len(neighbors) * 5 / 6):
        flags.append('使用する注文近傍の5/6以上で耐性を維持できない')
    import signal_diagnostics
    signal_spec = next(x for x in SPECS['signals'] if x['id'] == candidate['signal_id'])
    signal_neighbors = []
    for variant in signal_diagnostics.direction_variants(signal_spec, INPUTS, FEATURES):
        value = replay(variant['id'], variant['directions'], management)
        value.update(kind=variant['kind'], description=variant['description'])
        cases.append(value)
        if variant['kind'] == 'neighbor':
            signal_neighbors.append(value)
    if not signal_neighbors:
        flags.append('有効な信号近傍が未検証')
    elif sum(acceptable(c) for c in signal_neighbors) < math.ceil(len(signal_neighbors) * .75):
        flags.append('信号近傍の75%以上で耐性を維持できない')
    for symbol in ['TOPIX', 'NK225']:
        base = candidate['symbols'][symbol]
        if base['two_start_days_removed_net'] < 0:
            flags.append(f'{symbol}:最大2開始日除外で赤字')
        if -base['worst_session'] > .5 * base['gross_profit_yen']:
            flags.append(f'{symbol}:最悪セッション損失が総利益の半分超')
        if np.median([c['symbols'][symbol]['net_yen'] for c in cases[1:4]]) < .5 * base['net_yen']:
            flags.append(f'{symbol}:遅延3条件の収支中央値が基準の半分未満')
        if np.median([c['symbols'][symbol]['net_yen'] for c in neighbors]) < .5 * base['net_yen']:
            flags.append(f'{symbol}:注文近傍の収支中央値が基準の半分未満')
        if signal_neighbors and np.median([c['symbols'][symbol]['net_yen'] for c in signal_neighbors]) < .5 * base['net_yen']:
            flags.append(f'{symbol}:信号近傍の収支中央値が基準の半分未満')
        if min(c['symbols'][symbol]['net_yen'] for c in neighbors + signal_neighbors) < -.25 * base['net_yen']:
            flags.append(f'{symbol}:近傍の最悪損失が基準利益の25%超')
    result = {'candidate': candidate, 'cases': cases, 'first_stage_failures': flags,
              '注文近傍数': len(neighbors), '近傍除外': skipped,
              '信号近傍数': len(signal_neighbors), '信号変形の記録': signal_diagnostics.last_diagnostics(),
              'validation_sha': VALIDATION_SHA,
              '解釈': '条件変更は反証用。良い変更後条件を採用し直さない。売買方向反転は価格経路反射と別物。'}
    runner.save(path, result)
    return result


def randomized(candidate: dict) -> dict:
    """機能: 価格を使わない方向と、発火時刻だけ同じ無関係方向で対照する。

    引数: candidate (dict)。返り値: 固定64乱数×２方式の分布と全区間結果 (dict)。
    """
    path = HERE / 'randomized' / f'{candidate["id"]}.json.gz'
    if path.exists():
        saved = runner.read(path)
        assert saved['validation_sha'] == VALIDATION_SHA, '異なる反証版の結果は再利用できません'
        return saved
    state = load_state(candidate['signal_id'])
    management = next(x for x in SPECS['managers'] if x['id'] == candidate['manager_id'])
    results, prefix_count = [], 0
    for gated in [False, True]:
        for seed in range(64):
            directions = {}
            for key, ready in INPUTS.items():
                gate = state[key] if gated else None
                directions[key] = random_direction(ready, seed, 1800, gate)
                if seed == 0:
                    cut = len(ready['time_s']) // 2
                    short = dict(ready, time_s=ready['time_s'][:cut])
                    expected = random_direction(short, seed, 1800, gate[:cut] if gate is not None else None)
                    np.testing.assert_array_equal(expected, directions[key][:cut])
                    prefix_count += 1
            result = replay(f'{"発火時刻だけ一致" if gated else "30分コイントス"}_{seed:02d}', directions, management)
            result.update(seed=seed, gated=gated)
            results.append(result)
    summary = []
    for gated in [False, True]:
        subset = [r for r in results if r['gated'] == gated]
        row = {'発火時刻限定': gated, '試行数': 64, 'symbols': {}}
        for symbol in ['TOPIX', 'NK225']:
            net = np.array([r['symbols'][symbol]['net_yen'] for r in subset])
            ref = candidate['symbols'][symbol]
            row['symbols'][symbol] = {'net_percentiles': np.percentile(net, [0, 5, 50, 95, 100]).tolist(),
                                     'net_at_least_candidate': int((net >= ref['net_yen']).sum()),
                                     'pf_at_least_candidate': sum(
                                         (r['symbols'][symbol]['money_ratio'] >= (ref['money_ratio'] or 0))
                                         if r['symbols'][symbol]['money_ratio'] is not None
                                         else r['symbols'][symbol]['gross_profit_yen'] > 0 for r in subset),
                                     'positive_profit_without_loss': sum(r['symbols'][symbol]['gross_profit_yen'] > 0 and r['symbols'][symbol]['gross_loss_yen'] == 0 for r in subset)}
        row['両銘柄収支が候補以上'] = sum(all(r['symbols'][s]['net_yen'] >= candidate['symbols'][s]['net_yen'] for s in ['TOPIX', 'NK225']) for r in subset)
        summary.append(row)
    output = {'candidate': candidate, 'summary': summary, 'prefix一致数': prefix_count, 'results': results,
              'validation_sha': VALIDATION_SHA,
              '両銘柄で同じ時間区分の乱数方向を共有': True,
              '解釈': '64乱数は同じ既知期間を共有する。正式な有意確率ではない。発火時刻対照は候補のタイミング情報を残す。'}
    runner.save(path, output)
    return output


def main() -> None:
    """機能: 固定候補へ一律に反証を行い、通過した異なる思想を無関係対照へ進める。

    引数: workers (int)、random (bool) コマンド引数。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=10)
    parser.add_argument('--random', action='store_true')
    args = parser.parse_args()
    for name in ['adversarial', 'randomized']:
        (HERE / name).mkdir(exist_ok=True)
    freeze = HERE / '反証仕様の固定.json'
    if not freeze.exists():
        files = [Path(__file__), HERE / 'signal_diagnostics.py', HERE / 'engine_observed_v25.py',
                 HERE / 'discovery_signals.py', HERE / 'discovery_managers.py',
                 HERE / '探索条件の固定.json', HERE / '反証前の候補固定.json',
                 OLD / 'managers.py', OLD / 'research.py', OLD / 'engine.py']
        runner.save(freeze, {'条件': '基準再現、方向遅延1/5/15秒、観測価格約定、使用する注文3変数各±20%、信号近傍、部品交換、相手情報対照、反転と常時方向、通過12思想の固定64乱数×2対照',
                            '候補の追加禁止': True, '未知検証ではない': True,
                            'SHA256': {str(p.relative_to(HERE.parent)): runner.digest(p) for p in files}})
    for relative, expected in runner.read(freeze)['SHA256'].items():
        assert runner.digest(HERE.parent / relative) == expected, f'反証条件の固定後変更: {relative}'
    selected = runner.read(HERE / '反証前の候補固定.json')['反証候補']
    if args.random:
        first = runner.read(HERE / '一次反証の結果.json')
        passed = [x['candidate'] for x in first if not x['first_stage_failures']]
        selected, seen = [], set()
        for c in sorted(sorted(passed, key=lambda value: value['id']), key=runner.score, reverse=True):
            family = (c['signal_family'], c['manager_family'])
            if family not in seen:
                seen.add(family)
                selected.append(c)
            if len(selected) == 12:
                break
        runner.save(HERE / '無関係対照前の候補固定.json', selected)
    operation, outputs = (randomized if args.random else audit), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(operation, c): c['id'] for c in selected}
        for future in as_completed(futures):
            result = future.result()
            if args.random:
                outputs.append({k: v for k, v in result.items() if k != 'results'})
            else:
                outputs.append({k: v for k, v in result.items() if k != 'cases'})
            print(f'{len(outputs)}/{len(selected)} {futures[future]} 完了', flush=True)
    runner.save(HERE / ('無関係対照の要約.json' if args.random else '一次反証の結果.json'), outputs)


if __name__ == '__main__':
    main()
