"""増玉なし旧全量だけを旧100の二条件へ全経済で照合する。"""

from pathlib import Path

import common
import compare_utils as checks
import support


def main() -> None:
    """
    機能: G0_QFULL二条件の全124口座を旧100保存注文・曲線・旧状態・支持へ照合する。
    引数: なし。本体書込完了通知後だけ実行する。
    返り値: None。新増玉又は絶対小数量の正式損益は生成しない。
    """
    old_count = common.old_immutable()
    catalog = common.module('101全量null条件',common.BASE/'catalog.py')
    configs = [config for config in catalog.catalog() if config['trend_initial_quantity'] is None]
    assert len(configs) == 2 and all(config['trend_growth_mode'] == 0 for config in configs)
    data = common.module('101全量null入力',common.BASE/'data.py')
    strategy = common.module('101全量null戦略',common.BASE/'strategy.py')
    material = data.load_inputs()
    prepared = strategy.prepare(material,configs[0])
    assert len(prepared) == 62
    for key,value in prepared.items():
        support.verify_material(key,material,value)
    before = checks.prepared_sha(prepared)
    counts = dict(条件=2,口座=0,注文=0,決済親=0,原板行=0)
    paths = []
    for config in configs:
        old = {}
        for part in ('front','back'):
            path = common.ROOT/'work/wave_v100'/part/'ledgers'/(config['previous_price_cap_id']+'.pkl')
            old.update(common.read(path))
            paths.append(path)
        assert set(old) == set(prepared)
        for key in sorted(old):
            actual = strategy.play(config,key,prepared)
            saved = old[key]
            for name in ('orders','trades','events','stats','slots','range_parent_diagnostics',
                         'loss_reentry_events','trend_parent_diagnostics','entry_parent_diagnostics',
                         'entry_wait_events','entry_policy_events','entry_cap_parent_diagnostics'):
                checks.exact(actual[name],saved[name],config['id']+'/'+str(key)+'/'+name)
            for name,field in (
                ('curve','curve_SHA256'),('source_curve','source_curve_SHA256'),
                ('target_trace','target_trace_SHA256'),('range_state_trace','range_state_SHA256'),
                ('risk_state_trace','risk_state_SHA256'),('price_source_trace','price_source_SHA256'),
                ('trend_exit_state_trace','trend_exit_state_SHA256'),('watch_state_trace','watch_state_SHA256'),
                ('entry_policy_state_trace','entry_policy_state_SHA256'),('entry_cap_state_trace','entry_cap_state_SHA256')):
                assert checks.array_sha(actual[name]) == saved[field],(config['id'],key,name)
            checks.exact(actual['entry_support_state_trace'],saved['entry_support_state_trace'],'支持59完全一致')
            assert actual['entry_support_input_SHA256'] == saved['entry_support_input_SHA256']
            assert checks.array_sha(prepared[key]['signal']['event']) == saved['trend_event_SHA256']
            counts['口座'] += 1
            counts['注文'] += len(actual['orders'])
            counts['決済親'] += len(actual['trades'])
            counts['原板行'] += len(prepared[key]['record']['time_s'])
        print(config['id']+': 旧100の全62口座と注文・旧20・価格上限・支持が完全一致',flush=True)
    assert counts['口座'] == 124 and checks.prepared_sha(prepared) == before
    common.old_immutable()
    paths += [common.BASE/name for name in ('engine.py','strategy.py','data.py','catalog.py')]
    paths += [Path(__file__),common.HERE/'common.py',common.HERE/'compare_utils.py',common.HERE/'support.py',
              common.ROOT/'work/wave_v100/事前固定.json']
    common.save(common.HERE/'旧全量二対照の100全124口座と旧経済及び支持と上限の完全一致.json',dict(
        合格=True,検査件数=counts,公差=0,旧100固定依存=old_count,共有prepared不変=True,
        共有preparedSHA256=before,増玉正式損益=0,絶対小数量正式損益=0,API取得=0,実注文=0,
        SHA256=common.fingerprints(paths)))


if __name__ == '__main__':
    main()
