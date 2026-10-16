"""人工と正式で同じ全注文会計・期間集計・保存終端を通す102独立監査CLI。"""

import argparse
from pathlib import Path
import traceback
import numpy as np

import common
import cohort_sources
import compare_utils as checks
import financial
import runtime_oracle
import storage
import summaries
import support

REPRESENTATIVES = ('B1_T0_Q1_X1','B1_T1_Q1_X1','B2_T1_Q1_X3','G0_Q1_X1')


def restore(record: dict, ledger: dict) -> dict:
    """
    機能: 全注文から独立curveを生成し、保存疎列を全原行へ戻して署名を確認する。
    引数: record/ledger(dict)は保存原板と台帳。
    返り値: dict。監査用復元出力。未来fill・latentを正答生成へ使わない。
    """
    output = dict(ledger)
    curve,source_curve,_,_ = financial.curves(record,np.asarray(ledger['orders']))
    for name,value in [('curve',curve),('source_curve',source_curve)]:
        assert checks.array_sha(value) == ledger[name+'_SHA256'],name+'/全原板指紋'
        output[name] = value
    names = [('target_trace','trace_changes','target_trace_SHA256'),
             ('range_state_trace','range_state_changes','range_state_SHA256'),
             ('risk_state_trace','risk_state_changes','risk_state_SHA256'),
             ('price_source_trace','price_source_changes','price_source_SHA256'),
             ('trend_exit_state_trace','trend_exit_state_changes','trend_exit_state_SHA256'),
             ('watch_state_trace','watch_state_changes','watch_state_SHA256'),
             ('entry_policy_state_trace','entry_policy_state_changes','entry_policy_state_SHA256'),
             ('entry_cap_state_trace','entry_cap_state_changes','entry_cap_state_SHA256'),
             ('growth_state_trace','growth_state_changes','growth_state_SHA256'),
             ('growth_gate_state_trace','growth_gate_state_changes','growth_gate_state_SHA256')]
    for name,sparse,fingerprint in names:
        dense = financial.expand(np.asarray(ledger[sparse]),len(record['time_s']))
        assert checks.array_sha(dense) == ledger[fingerprint],name+'/状態復元指紋'
        output[name] = dense
    return output


def verify_bundle(config: dict, prepared: dict, ledgers: dict,
                  periods: dict, expected: dict, replay: bool) -> tuple:
    """
    機能: 人工と正式で同じ全注文・cohort会計と全8期間及び安定性を検算する。
    引数: config/prepared/ledgers/periods/expected(dict)、replay(bool)は独立原行再生有無。
    返り値: tuple[dict,dict]。独立全結果と検査件数。
    """
    rows = []
    counts = dict(口座=0,注文=0,決済親=0,cohort=0,全原板会計=0,独立原行再生=0,商品期間=0)
    assert set(prepared) == set(ledgers)
    for key in sorted(ledgers):
        value,ledger = prepared[key],ledgers[key]
        output = restore(value['record'],ledger)
        finance = financial.verify_account(value['record'],config,output)
        cohort_sources.verify(value,config,output)
        selected,allowed = support.selected(value,config)
        support.verify_trace(value,config,selected,allowed,output)
        storage.verify(output,ledger,value)
        if replay:
            runtime_oracle.compare(value,config,output)
            counts['独立原行再生'] += 1
        rows.append(summaries.row(key,value['record'],config,output))
        counts['口座'] += 1
        for name in ('注文','決済親','cohort','全原板会計'):
            counts[name] += finance['counts'][name]
    prices = {key:value['record'] for key,value in prepared.items()}
    result = dict(config=config,rows=rows,
        periods={name:{symbol:summaries.aggregate(rows,symbol,sessions) for symbol in common.SYMBOLS}
                 for name,sessions in periods.items()},
        stability={name:summaries.stability(rows,config,prices,sessions) for name,sessions in periods.items()})
    checks.same(result,expected,config['id']+'/全会計と8期間及び安定性')
    counts['商品期間'] = len(periods)*len(common.SYMBOLS)
    return result,counts


def main() -> None:
    """
    機能: 通常監査CLIを人工又は根許可後の正式で実行し、終端保存・再読込まで確認する。
    引数: CLI --artificial又は--formal。
    返り値: None。不一致で安全停止。API/実注文/正式売買の新規生成を行わない。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--artificial',action='store_true')
    mode.add_argument('--formal',action='store_true')
    args = parser.parse_args()
    catalog = common.module('102独立CLI条件',common.BASE/'catalog.py')
    strategy = common.module('102独立CLI戦略',common.BASE/'strategy.py')
    research = common.module('102独立CLI根保存',common.BASE/'research.py')
    accounting = common.module('102独立CLI根会計',common.BASE/'accounting.py')
    conditions = catalog.catalog()
    assert len(conditions) == 20
    paths = [common.BASE/name for name in ('catalog.py','strategy.py','engine.py','research.py','accounting.py','data.py')]
    paths += [common.HERE/name for name in ('common.py','compare_utils.py','financial.py','math_oracle.py',
              'summaries.py','support.py','storage.py','runtime_oracle.py','watch.py','cohort_sources.py','full.py')]
    signatures = common.fingerprints(paths)
    results,counts = {},{}
    representatives = list(REPRESENTATIVES)
    if args.artificial:
        import artificial
        prepared = {( '2099-01-01_Day',symbol):artificial.fixture(symbol) for symbol in common.SYMBOLS}
        period_map = {name:['2099-01-01_Day'] for name in ('全31','前16','後15','旧30','後14','追加1','デイ','ナイト')}
        signatures.update(common.fingerprints([common.HERE/'artificial.py']))
        for config in conditions:
            outputs = {key:strategy.play(config,key,prepared) for key in prepared}
            ledgers = {key:research.ledger(output,prepared[key]) for key,output in outputs.items()}
            path = common.HERE/'cli_fixture'/(config['id']+'.pkl')
            research.save(path,ledgers)
            loaded = common.read(path)
            for key in outputs:
                storage.verify(outputs[key],loaded[key],prepared[key])
            rows = [accounting.account(key,outputs[key]) for key in sorted(outputs)]
            expected = dict(config=config,rows=rows,
                periods={name:{symbol:accounting.aggregate(rows,symbol,sessions) for symbol in common.SYMBOLS}
                         for name,sessions in period_map.items()},
                stability={name:research.stability(rows,config,prepared,sessions) for name,sessions in period_map.items()})
            result,checked = verify_bundle(config,prepared,loaded,period_map,expected,True)
            results[config['id']] = result
            for name,amount in checked.items():
                counts[name] = counts.get(name,0)+amount
            signatures.update(common.fingerprints([path]))
            print(config['id']+': 通常人工CLI/根ledger保存/全8期間/安定性/全玉会計が一致',flush=True)
        assert counts['口座'] == 40 and counts['商品期間'] == 320
        destination = common.HERE/'人工40口座の独立通常CLIと全8期間及び根台帳の保存終端.json'
    else:
        fixed_path = common.BASE/'事前固定.json'
        fixed = common.read(fixed_path)
        assert fixed['条件'] == conditions and fixed['全31既知'] and fixed['新未見確認場数'] == 0
        for relative,wanted in fixed['SHA256'].items():
            assert common.sha(common.ROOT/relative) == wanted,relative
        data = common.module('102正式独立入力',common.BASE/'data.py')
        prepared = strategy.prepare(data.load_inputs(),conditions[0])
        selected_path = common.BASE/'前16参考代表.json'
        selected = common.read(selected_path)
        assert selected['後15正式損益前選定'] and selected['全31既知']
        representatives = list(dict.fromkeys((*representatives,selected['selected'])))
        analysis_path = common.BASE/'analysis/比較結果.json'
        analysis = common.read(analysis_path)
        period_map = {name:fixed[name] for name in ('全31','前16','後15','旧30','後14','追加1')}
        period_map.update(デイ=[s for s in fixed['全31'] if s.endswith('_Day')],
                          ナイト=[s for s in fixed['全31'] if s.endswith('_Night')])
        for config in conditions:
            ledgers,part_results = {},{}
            for part in ('front','back'):
                result_path = common.BASE/part/'results'/(config['id']+'.json')
                ledger_path = common.BASE/part/'ledgers'/(config['id']+'.pkl')
                part_results[part] = common.read(result_path)
                assert part_results[part]['config'] == config
                assert common.sha(ledger_path) == part_results[part]['ledger_SHA256']
                ledgers.update(common.read(ledger_path))
                signatures.update(common.fingerprints([result_path,ledger_path]))
            result,checked = verify_bundle(config,prepared,ledgers,period_map,
                analysis['results'][config['id']],config['id'] in representatives)
            for part,name in [('front','前16'),('back','後15')]:
                checks.same([row for row in result['rows'] if row['session'] in fixed[name]],part_results[part]['rows'])
            results[config['id']] = result
            for name,amount in checked.items():
                counts[name] = counts.get(name,0)+amount
            print(config['id']+': 全31台帳/親cohort/全原板/8期間の独立会計が一致',flush=True)
        assert counts['口座'] == 1240 and counts['商品期間'] == 320 and len(prepared) == 62
        assert counts['独立原行再生'] == len(representatives)*62
        for relative,wanted in fixed['SHA256'].items():
            assert common.sha(common.ROOT/relative) == wanted,relative
        signatures.update(common.fingerprints([fixed_path,selected_path,analysis_path]))
        destination = common.HERE/'全20全31の増玉注文と親cohort及び全原板会計の独立検算.json'
    assert common.fingerprints(paths) == {key:signatures[key] for key in common.fingerprints(paths)}
    common.save(destination,dict(合格=True,人工専用=args.artificial,検査件数=counts,全会計=results,
        代表条件=representatives,
        原行再生の範囲='人工全20。本番はB1_T1_Q1_X1/B1_T0_Q1_X1/B2_T1_Q1_X3/G0_Q1_X1及び前16参考の重複除去。',
        状態の範囲='保存70/74/25/24と別19は全列復元。cohort25と親の物理22列を全口座で実注文/原板へ戻す。代表は保有数理11項目・別19門番全列・初回/追加/最初停止を独立算定。旧70全補助flagsの独立検算とはしない。',
        人工CLIの範囲='監査通常mainと共通verify_bundle、根のledger/save/account/aggregate/stability具体関数を全8期間・保存再読込・analysis構造比較まで通す。根assemble.mainの実前後段を人工31場へ水増しして証明したとはしない。',
        全31既知=True,未見場数=0,新正式売買生成=0,API取得=0,実注文=0,SHA256=signatures))
    print('監査通常CLIの全比較と最終保存/再読込が合格。',flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        serial = 1
        failure = common.HERE/f'通常CLI不合格_{serial:05d}.json'
        while failure.exists():
            serial += 1
            failure = common.HERE/f'通常CLI不合格_{serial:05d}.json'
        common.save(failure,dict(合格=False,例外型=type(error).__name__,原因=str(error),
            詳細=traceback.format_exc(),正式売買の新規生成=0,API取得=0,実注文=0,
            SHA256=common.fingerprints([Path(__file__),common.HERE/'common.py'])))
        raise
