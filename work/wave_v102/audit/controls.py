"""旧101の八条件を全量・一枚固定・一枚開始の増玉へ完全照合する。"""

from pathlib import Path

import common
import compare_utils as checks
import support


def main() -> None:
    """
    機能: 旧八条件の全496口座を旧101保存注文・曲線・旧状態・支持・増玉へ照合する。
    引数: なし。本体書込完了通知後だけ実行する。
    返り値: None。新しい初回幅余裕又は停止線据置の正式損益は生成しない。
    """
    old_count = common.old_immutable()
    catalog = common.module('102旧八null条件',common.BASE/'catalog.py')
    configs = [config for config in catalog.catalog() if 'trend_growth_cushion_basis' not in config]
    assert len(configs) == 8 and {config['id'] for config in configs} == {
        f'{mode}_{quantity}_{exit_name}' for mode,quantity in
        (('G0','Q1'),('G1','Q1'),('G2','Q1'),('G0','QFULL')) for exit_name in ('X1','X3')}
    old_catalog = common.module('不変101八対照の設定',common.ROOT/'work/wave_v101/catalog.py')
    old_configs = {config['id']:config for config in old_catalog.catalog()}
    for config in configs:
        assert {key:value for key,value in config.items() if key != 'previous_growth_id'} == old_configs[config['previous_growth_id']]
    data = common.module('102旧八null入力',common.BASE/'data.py')
    strategy = common.module('102旧八null戦略',common.BASE/'strategy.py')
    material = data.load_inputs()
    prepared = strategy.prepare(material,configs[0])
    assert len(prepared) == 62
    for key,value in prepared.items():
        support.verify_material(key,material,value)
    before = checks.prepared_sha(prepared)
    counts = dict(条件=8,口座=0,注文=0,決済親=0,cohort=0,原板行=0)
    paths = []
    for config in configs:
        old = {}
        for part in ('front','back'):
            path = common.ROOT/'work/wave_v101'/part/'ledgers'/(config['previous_growth_id']+'.pkl')
            old.update(common.read(path))
            paths.append(path)
        assert set(old) == set(prepared)
        for key in sorted(old):
            actual = strategy.play(config,key,prepared)
            saved = old[key]
            for name in ('orders','trades','events','stats','slots','range_parent_diagnostics',
                         'loss_reentry_events','trend_parent_diagnostics','entry_parent_diagnostics',
                         'entry_wait_events','entry_policy_events','entry_cap_parent_diagnostics',
                         'growth_events','growth_cohorts','growth_parent_diagnostics'):
                checks.exact(actual[name],saved[name],config['id']+'/'+str(key)+'/'+name)
            for name,field in (
                ('curve','curve_SHA256'),('source_curve','source_curve_SHA256'),
                ('target_trace','target_trace_SHA256'),('range_state_trace','range_state_SHA256'),
                ('risk_state_trace','risk_state_SHA256'),('price_source_trace','price_source_SHA256'),
                ('trend_exit_state_trace','trend_exit_state_SHA256'),('watch_state_trace','watch_state_SHA256'),
                ('entry_policy_state_trace','entry_policy_state_SHA256'),('entry_cap_state_trace','entry_cap_state_SHA256'),
                ('growth_state_trace','growth_state_SHA256')):
                assert checks.array_sha(actual[name]) == saved[field],(config['id'],key,name)
            checks.exact(actual['entry_support_state_trace'],saved['entry_support_state_trace'],'支持59完全一致')
            assert actual['entry_support_input_SHA256'] == saved['entry_support_input_SHA256']
            for name in ('growth_state_columns','growth_event_columns','growth_event_codes',
                         'growth_cohort_columns','growth_parent_columns','entry_support_columns'):
                assert actual[name] == saved[name],(config['id'],key,name)
            assert checks.array_sha(prepared[key]['signal']['event']) == saved['trend_event_SHA256']
            counts['口座'] += 1
            counts['注文'] += len(actual['orders'])
            counts['決済親'] += len(actual['trades'])
            counts['cohort'] += len(actual['growth_cohorts'])
            counts['原板行'] += len(prepared[key]['record']['time_s'])
        print(config['id']+': 旧101の全62口座と注文・旧70・cohort・価格上限・支持が完全一致',flush=True)
    assert counts['口座'] == 496 and checks.prepared_sha(prepared) == before
    common.old_immutable()
    paths += [common.BASE/name for name in ('engine.py','strategy.py','data.py','catalog.py')]
    paths += [Path(__file__),common.HERE/'common.py',common.HERE/'compare_utils.py',common.HERE/'support.py',
              common.ROOT/'work/wave_v101/事前固定.json']
    common.save(common.HERE/'旧八対照の101全496口座と旧経済及び増玉支持の完全一致.json',dict(
        合格=True,検査件数=counts,公差=0,旧101固定依存=old_count,共有prepared不変=True,
        共有preparedSHA256=before,新政策正式損益=0,API取得=0,実注文=0,
        SHA256=common.fingerprints(paths)))


if __name__ == '__main__':
    main()
