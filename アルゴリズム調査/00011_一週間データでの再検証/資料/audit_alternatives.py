"""追加した保存区間の格子・NTを、独立全玉会計と未来打切りで点検する。"""

from __future__ import annotations

import argparse
import json
import pickle

import numpy as np

import reference
import run_alternatives as runner

grid, pair, metrics = runner.grid_engine, runner.pair_engine, runner.metrics
risk = reference.import_v14('risk_guard')
with reference.module_aliases(dict(reference=reference, risk_guard=risk)):
    old_guard_audit = reference.source_module(reference.OLD / 'audit_guard.py', 'v16_audit_guard_formula')
with reference.module_aliases(dict(audit_guard=old_guard_audit, metrics=metrics, pair_engine=pair)):
    old_extensions = reference.source_module(reference.OLD / 'audit_extensions.py', 'v16_audit_pair_formula')


def audit_grid(prepared: dict, results: dict, configs: dict, sessions: list[str]) -> dict:
    """機能: 固定代表格子の全行含み会計と、未来を削除した確定脚の不変性を調べる。

    引数: prepared/results/configs (dict)、sessions (list[str])。返り値: 監査件数 (dict)。
    """
    methods = [name for name in ['G01_T10', 'G10_A05', 'G16_A10', 'G18_A05'] if name in configs]
    if not methods:
        methods = list(configs)[:4]
    cell_count = row_count = prefix_count = 0
    for session in sessions:
        for symbol in reference.SYMBOLS:
            ready = prepared[(session, symbol)]
            mult = grid.MULTIPLIERS[symbol]
            for method in methods:
                config = configs[method]
                result = results[(method, session, symbol)]
                raw, summary = result['raw'], result['summary']
                equity, atr, gross, realized, _, dd, dda = old_guard_audit.independent_account(raw, ready['last'])
                expected = dict(net_yen=equity[-1] * mult, closed_net_yen=realized[-1] * mult,
                                open_yen=(equity[-1] - realized[-1]) * mult,
                                max_drawdown_yen=dd * mult, max_drawdown_atr=dda,
                                gross_peak=gross.max(), open_count=gross[-1])
                for name, value in expected.items():
                    np.testing.assert_allclose(summary[name], value, rtol=1e-8, atol=1e-5)
                assert gross.max() <= config['max_legs']
                assert gross[-1] == 0, '完全保存区間が未返済で終わっています'
                cell_count += 1
                row_count += len(equity)
                for fraction in (.373, .737):
                    count = int(len(ready['seq']) * fraction)
                    truncated = dict(ready)
                    for name in ['seq', 'time_s', 'last', 'atr']:
                        truncated[name] = ready[name][:count]
                    replay = grid.simulate(truncated, config)
                    full_closed = raw[(raw[:, 14] == 1) & (raw[:, 6] < count)]
                    prefix_closed = replay['raw'][replay['raw'][:, 14] == 1]
                    np.testing.assert_allclose(full_closed, prefix_closed, rtol=1e-10, atol=1e-6,
                                               equal_nan=True)
                    prefix_count += 1
    return dict(全行会計セル数=cell_count, 全行会計価格行数=row_count, 未来打切り比較数=prefix_count,
                全玉枚数制限=True, 完全区間内全返済=True)


def audit_pair(prepared: dict, results: dict, configs: dict, sessions: list[str]) -> dict:
    """機能: NTの原本約定・数量・厳密分解と、代表全行会計・未来削除を確認する。

    引数: prepared/results/configs (dict)、sessions (list[str])。返り値: 監査件数 (dict)。
    """
    leg_count = cycle_count = full_count = full_rows = prefix_count = 0
    for session in sessions:
        for method, config in configs.items():
            result = results[(method, session, 'NT')]
            for leg in result['legs']:
                tape = prepared[(session, leg['symbol'])]
                assert leg['entry_time'] > leg['entry_order']
                assert leg['complete'] and leg['exit_time'] > leg['exit_order']
                if config['executable_integer']:
                    assert leg['quantity'] == int(leg['quantity'])
                for name in ['entry', 'exit']:
                    i = np.searchsorted(tape['seq'], leg[name + '_seq'])
                    assert tape['seq'][i] == leg[name + '_seq']
                    np.testing.assert_allclose([tape['time_s'][i], tape['last'][i]],
                                               [leg[name + '_time'], leg[name + '_price']])
                factor = leg['side'] * leg['quantity'] * leg['multiplier']
                np.testing.assert_allclose(factor * (leg['exit_price'] - leg['entry_price']),
                                           leg['net_yen'], atol=1e-5)
                leg_count += 1
            for cycle in result['cycles']:
                legs = [x for x in result['legs'] if x['cycle_id'] == cycle['cycle_id']]
                np.testing.assert_allclose([sum(x['net_yen'] for x in legs),
                                           cycle['relative_yen'] + cycle['common_residual_yen'],
                                           cycle['beta_relative_yen'] + cycle['beta_rounding_yen']],
                                          cycle['net_yen'], atol=1e-5)
                assert cycle['gross_standard'] <= 20 + 1e-8 and cycle['complete']
                cycle_count += 1
        methods = [name for name in ['NT_ratio_mr_Z1.5_S0', 'NT_ratio_mom_Z1_S1',
                                    'NT_residual_mr_Z2_S2', 'NT_ratio_mom_Z1.5_S5'] if name in configs]
        if not methods:
            methods = list(configs)[:4]
        tapes = [prepared[(session, s)] for s in reference.SYMBOLS]
        ready = pair.prepare_session(session, tapes=tapes)
        for method in methods:
            result = pair.run(ready, configs[method], detail=True)
            independent = old_extensions.pair_full_account(ready, result)
            full_count += 1
            full_rows += len(independent)
            for fraction in (.373, .737):
                cut = ready['clocks'][int(len(ready['clocks']) * fraction)] + 15.
                prefix_tapes = [{key: value[tape['time_s'] <= cut] for key, value in tape.items()}
                                for tape in ready['tapes']]
                truncated = pair.prepare_session(session, tapes=prefix_tapes)
                count = len(truncated['clocks'])
                np.testing.assert_allclose(ready['prices'][:count], truncated['prices'], equal_nan=True)
                np.testing.assert_allclose(ready['features'][:count], truncated['features'], equal_nan=True)
                replay = pair.run(truncated, configs[method], detail=True)
                last = min(t['time_s'][-1] for t in prefix_tapes)
                old_closed = [leg for leg in result['legs'] if leg['complete'] and leg['exit_time'] <= last]
                new_closed = [leg for leg in replay['legs'] if leg['complete'] and leg['exit_time'] <= last]
                assert old_closed == new_closed
                np.testing.assert_allclose(result['full_curve'][result['full_curve'][:, 0] <= last],
                                           replay['full_curve'][replay['full_curve'][:, 0] <= last], atol=1e-6)
                prefix_count += 1
    return dict(原本価格と数量確認脚数=leg_count, 損益恒等式確認サイクル数=cycle_count,
                全行会計セル数=full_count, 原本と時計行数=full_rows, 未来打切り比較数=prefix_count,
                完全区間内全返済=True)


def main() -> None:
    """機能: 追加探索区間か、開封済み固定条件だけの保留区間を監査する。

    引数: CLIの段階 (str)。返り値: None。APIは呼ばず既存再生結果だけを監査する。
    """
    parser = argparse.ArgumentParser(description='週追加区間の格子・NT監査')
    parser.add_argument('--phase', choices=['development', 'holdout'], default='development')
    args = parser.parse_args()
    prepared = reference.load_inputs(args.phase)
    sessions = reference.DEVELOPMENT[7:] if args.phase == 'development' else [reference.HOLDOUT]
    suffix = '' if args.phase == 'development' else '_保留'
    audit = dict(成功=True, 対象区間=sessions, 原本通信回数=0)
    for name, function in [('格子', audit_grid), ('NT', audit_pair)]:
        catalog_path = reference.OUT / f'{name}{suffix}条件一覧.json'
        if not catalog_path.exists():
            continue
        configs = {cfg['id']: cfg for cfg in json.loads(catalog_path.read_text(encoding='utf-8'))}
        with (reference.OUT / f'{name}{suffix}_再生結果.pkl').open('rb') as stream:
            results = pickle.load(stream)
        audit[name] = function(prepared, results, configs, sessions)
    runner.write_json(reference.OUT / f'格子とNT{suffix}_追加区間会計監査.json', audit)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
