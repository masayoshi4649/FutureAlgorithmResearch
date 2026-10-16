"""全31完了の根許可後だけ、全2108口座の会計と8期間の安定性を検算する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 元候補対応と独立会計分解 as P
import 現在支持59列の独立照合 as Q

A = R.module('旧94安定性独立式を99へ接続', R.OLD / '全53親会計と安定性及び一軸経路分解.py')


def previous_null(ident: str, config: dict, current: dict) -> dict:
    """
    機能: L0及びA0十八条件を対応する98旧条件の全31会計・注文・保有状態と完全照合する。
    引数: ident(str)、config/current(dict)は新99設定と台帳集合。
    返り値: dict。旧正式結果は読み取り専用で、再生しない。
    """
    old_id = config['previous_clock_id']
    previous, paths = {}, {}
    for part in ('front', 'back'):
        path = R.ROOT / 'work/wave_v98' / part / 'ledgers' / (old_id + '.pkl')
        previous.update(R.read(path))
        paths[str(path.relative_to(R.ROOT))] = R.digest(path)
    assert previous.keys() == current.keys()
    fields = ('orders', 'trades', 'events', 'stats', 'slots', 'trace_changes',
        'range_state_changes', 'risk_state_changes', 'price_source_changes',
        'range_parent_diagnostics', 'loss_reentry_events', 'trend_exit_state_changes',
        'trend_parent_diagnostics', 'watch_state_changes', 'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_changes', 'entry_policy_events')
    hashes = ('curve_SHA256', 'source_curve_SHA256', 'target_trace_SHA256', 'source_curve_column_SHA256', 'watch_state_SHA256', 'entry_policy_state_SHA256')
    for key in current:
        for name in fields:
            assert np.array_equal(current[key][name], previous[key][name], equal_nan=True), (ident, key, name)
        for name in hashes:
            assert current[key][name] == previous[key][name], (ident, key, name)
    return dict(旧対照=old_id, 全62口座一致=True, 旧台帳SHA256=paths)


def main() -> None:
    """
    機能: 全34の注文・親会計・料金・元候補・安定性と前16固定参考を独立照合する。
    引数: --根許可後(bool)は全31正式完了通知後の実行に必須。
    返り値: None。正式売買、条件追加、主及び参考の差替えは行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    material = R.material()
    results = assembled['results']
    checks, stable, nulls, fingerprints, support_checks = {}, {}, {}, {}, {}
    support_cache = {}
    for config in fixed['条件']:
        ident = config['id']
        ledger = R.load_ledgers(ident)
        result = results[ident]
        checks[ident] = R.BASE.check(result, ledger, fixed)
        support_checks[ident] = {}
        for key, value in ledger.items():
            if key not in support_cache: support_cache[key] = Q.base_matrix(key, material)
            support_checks[ident]['|'.join(key)] = Q.check(key, value, config, material, support_cache[key])
            P.origin_map(value, material['prices'][key])
            assert len(value['watch_state_columns']) == 50
            active = value['watch_state_columns'].index('active') + 1
            assert value['watch_state_changes'][-1, active] == 0
            assert all(int(trade[1]) == 0 for trade in value['trades'])
            assert len(value['entry_policy_state_columns']) == 40
            assert len(value['entry_policy_event_columns']) == 50
            paused = value['entry_policy_state_columns'].index('paused') + 1
            assert value['entry_policy_state_changes'][-1, paused] == 0
        stable[ident] = {}
        for period, sessions in R.partitions(fixed['全31']).items():
            for symbol in R.SYMBOLS:
                trades = np.concatenate([ledger[session, symbol]['trades'] for session in sessions])
                metric = result['periods'][period][symbol]
                for source, label in enumerate(('J2', 'O06')):
                    R.equal(R.totals(trades[trades[:, 1] == source]), metric['sources'][label])
                for side, label in ((1, '買い'), (-1, '売り')):
                    R.equal(R.totals(trades[trades[:, 4] == side]), metric['directions'][label])
            values = A.stability(result['rows'], config, material['prices'], sessions)
            A.verify_nested(values, result['stability'][period])
            stable[ident][period] = values
        if config['entry_support_lane'] == 'L0':
            nulls[ident] = previous_null(ident, config, ledger)
        for part in ('front', 'back'):
            for folder, suffix in (('results', 'json'), ('ledgers', 'pkl')):
                path = R.WORK / part / folder / f'{ident}.{suffix}'
                fingerprints[str(path.relative_to(R.ROOT))] = R.digest(path)
        print(f'{ident}: 全62親会計・元候補対応・支持59源・8期間安定性を独立照合', flush=True)
    selected = A.selection(results, fixed, stable)
    assert len(nulls) == 18
    both80 = [ident for ident, value in results.items() if all(
        value['periods']['全31'][symbol]['profit_share'] is not None
        and value['periods']['全31'][symbol]['profit_share'] >= .8 for symbol in R.SYMBOLS)]
    active80 = [ident for ident in both80 if all(results[ident]['periods']['全31'][symbol]['campaigns'] >= 20
        and results[ident]['periods']['全31'][symbol]['active_sessions'] >= 8 for symbol in R.SYMBOLS)]
    assert both80 == assembled['both80'] and active80 == assembled['活動充足の両80']
    R.save('全34条件全31の独立親会計と安定性及びL0旧対照一致.json', dict(
        全合格=True, 条件数=34, 口座=34 * 62, 商品期間群=34 * 8 * 2,
        注文=sum(value['注文'] for value in checks.values()), 親=sum(value['親'] for value in checks.values()),
        会計照合=checks, 元候補原本源一致=True, L0旧対照一致=nulls, 独立安定性=stable,
        現在支持59源及び買売入力の独立照合=support_checks,
        前16固定参考=selected, 両商品金額80=both80, 活動充足両80=active80,
        主=fixed['主'], 主変更=False, 参考事後差替え=False,
        注意=['待機枠は実建玉ではない。約定親の会計と待機イベントを分ける。',
            '活動を減らした円損失縮小、無取引、新規価格改善を同じ成功として扱わない。',
            '全31は既知。全行清算時価と入力prefixの重複監査は行わず独立監査の証跡を参照。',
            '政策40状態と補助10旗の全行再現を親会計の一致から証明したとは言わない。'],
        正式結果SHA256=fingerprints, 計算コードSHA256=R.digest(Path(__file__)),
        独立安定性式SHA256=R.digest(R.OLD / '全53親会計と安定性及び一軸経路分解.py'), **R.provenance()))


if __name__ == '__main__':
    main()
