"""正式小metadata・表示source・純比較算術だけを結果前に確認する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load_source(name: str) -> object:
    """
    機能: 私有表示sourceだけを読み込み、金融実装/mainは実行しない。
    引数: name(str)はreport/report_viewの名前。
    返り値: moduleは表示又は表示QA。結果・input・台帳・APIは読まない。
    """
    spec = importlib.util.spec_from_file_location('金融前109_'+name, HERE/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """
    機能: 正式16源metadata接続と、ON/OFFの金額差/無親Noneを人工確認する。
    引数: なし。根freeze済み小plan/fixedだけを読む。
    返り値: None。実金融を未確認のまま合格したとは記載しない。
    """
    report, view = load_source('report'), load_source('report_view')
    plan_path, fixed_path = HERE/'engine/試行計画.json', HERE/'engine/金融事前固定.json'
    raw_plan, raw_fixed = plan_path.read_bytes(), fixed_path.read_bytes()
    plan_sha = hashlib.sha256(raw_plan).hexdigest()
    assert plan_sha == 'd885ef91d84e19ed0a89b76f18f616517921f49db4b459dbdf551cbcf601c3bd'
    plan, fixed = json.loads(raw_plan.decode('utf-8')), json.loads(raw_fixed.decode('utf-8'))
    assert fixed['正式freeze'] and plan['正式freeze'] and fixed['計画SHA256'] == plan_sha
    assert fixed['source_SHA256'] == plan['spec']['implementation'] and len(fixed['source_SHA256']) == 16
    assert all(report.digest(ROOT/p) == sha for p, sha in fixed['source_SHA256'].items())
    assert report.HELPERS.case_hashes(fixed['configs']) == fixed['case_SHA256']
    assert len(fixed['configs']) == 12 and all(report.parameters(c) for c in fixed['configs'])
    assert report.SCHEMA_READY and view.SCHEMA_READY and report.TITLE == view.TITLE
    assert report.ACCOUNTING_TITLE == view.ACCOUNTING_TITLE and report.PUBLIC == view.PUBLIC
    assert report.digest(report.SELECTION_PLAN) == report.SELECTION_SHA
    assert report.digest(report.COMPARISON_PATH) == report.COMPARISON_SHA
    base_artificial = report.artificial()
    sessions = ['2026-01-01_Day', '2026-01-01_Night', '2026-01-02_Day']
    case = dict(rows=[], parents=[], metrics={}, directions={})
    saved = {}
    for symbol in report.SYMBOLS:
        rows = [dict(session=t, symbol=symbol, profit=max(net, 0), loss=max(-net, 0), net=net,
            campaigns=int(net != 0), winning_campaigns=int(net > 0), losing_campaigns=int(net < 0),
            winning_lots=report.CAPACITY[symbol] if net > 0 else 0,
            losing_lots=report.CAPACITY[symbol] if net < 0 else 0, fees=0.) for t, net in zip(sessions, (1000., -500., 0.))]
        prior = [dict(r, profit=max(net, 0), loss=max(-net, 0), net=net) for r, net in zip(rows, (650., -250., 0.))]
        current_metric, old_metric = report.metrics(rows, sessions, symbol), report.metrics(prior, sessions, symbol)
        case['rows'].extend(rows)
        case['parents'].extend(dict(symbol=symbol, session=r['session'], entry_quantity=report.CAPACITY[symbol]) for r in rows if r['campaigns'])
        case['metrics'][symbol] = current_metric
        case['directions'][symbol] = dict(long=dict(利益=1000., 損失=500., 収支=500., 親数=2), short=dict(利益=0., 損失=0., 収支=0., 親数=0))
        saved[symbol] = dict(買売=dict(long=dict(利益=650., 損失=250., 収支=400., 親数=2), short=dict(利益=0., 損失=0., 収支=0., 親数=0)))
        for field, tag in (('full', '全場'), ('top3', '上位三除外')):
            metric = old_metric[field]
            saved[symbol][tag] = dict(aggregate=dict(利益=metric['profit'], 損失=metric['loss'], 収支=metric['net'],
                親数=metric['campaigns'], 黒字場=metric['positive'], 赤字場=metric['negative'], 無取引場=metric['no_trade']),
                economic=dict(mean_session_net_yen=metric['mean_session_net'], session_count=metric['sessions'],
                    by_session=[dict(session=r['session'], net_yen=r['net'], parent_count=r['campaigns'],
                        mean_initial_quantity=report.CAPACITY[symbol] if r['campaigns'] else None,
                        net_capacity_points=r['net']/(report.CAPACITY[symbol]*report.MULTIPLIER[symbol])) for r in prior]))
    fixture = dict(cases={'人工OFF': case}, paired_saved_on={'人工OFF': dict(saved_on=saved)}, sessions=sessions)
    actual, expected = report.reference_rows(fixture), view.comparison_expectations(fixture)
    assert actual == expected
    assert actual['aggregate'][0][9] == '100' and actual['directional'][0][9] == '100'
    assert actual['session_net'][0][5] == '350' and actual['session_net'][1][5] == '-250'
    assert actual['session_net'][2][5] == '0' and actual['session_net'][2][8] == '未定義'
    proof = dict(全合格=True, 正式plan_SHA256=plan_sha, 正式fixed_SHA256=hashlib.sha256(raw_fixed).hexdigest(),
        表示source_SHA256=report.digest(HERE/'report.py'), QA_source_SHA256=report.digest(HERE/'report_view.py'),
        選定SHA256=report.SELECTION_SHA, 比較SHA256=report.COMPARISON_SHA, 金融source_SHA256=fixed['source_SHA256'],
        source条件=16, 新OFF条件=12, 候補外ON条件=12, 純算術=base_artificial, 独立表示比較人工=5,
        各場旧net差='by_sessionの保存netだけ算術比較', 未測='旧場別P/L・親共通対応・入口退出時刻・途中全経路',
        金融結果読取=0, 旧108本文=0, input=0, ledger=0, API=0, 公開=0, Chrome=0)
    output = HERE/'表示preparedの形式接続と純比較人工_v2.json'
    assert not output.exists(), '結果前のprepared証跡を上書きしない。'
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 表示source_SHA256=proof['表示source_SHA256'], QA_source_SHA256=proof['QA_source_SHA256'],
        prepared_SHA256=report.digest(output), 金融=0, input=0, ledger=0, API=0, 公開=0, Chrome=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
