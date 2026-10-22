"""十九間隔の新七百二十会計と旧四十引用を保存台帳から独立確認する。"""

import argparse
from collections import Counter
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PRIOR = ROOT/'work/stability122_20261017'
sys.path.insert(0,str(PRIOR/'audit'))
import saved_accounting122 as previous

core = previous.core
PREVIOUS_SHA = 'be68d9b40a3f105efdb886287503a325a2a8353799fff1f5e8f50b356cedf2ed'
BASELINE_SHA = 'ea3632b2e7bf2e9eb3e73addfede7f87deda0069efb30e4a3fd2647550dbab72'
READS = Counter()


def statistics(rows: list) -> dict:
    """
    機能: 全四十場分母と活動分母を分け、利益集中と枚数の変化を表示する。
    引数: rows(list[dict])は一条件の保存済み四十小会計。
    返り値: dictは固定定義の統計。上位条件の再選抜や評価分母変更はしない。
    """
    assert len(rows) == 40
    positive = [row for row in rows if row['net'] > 0]
    active = [row for row in rows if row['entries'] > 0]
    inactive = [row for row in rows if row['entries'] == 0]
    assert all(row['net'] == row['fees'] == 0 for row in inactive)
    excluded = sorted(positive,key=lambda row:(-row['net'],row['session']))[:3]
    excluded_sessions = {row['session'] for row in excluded}
    remaining = [row for row in rows if row['session'] not in excluded_sessions]
    net = float(sum(row['net'] for row in rows))
    quantity = int(sum(row['entries'] for row in rows))
    return dict(sessions=40,profit=float(sum(row['profit'] for row in rows)),
        loss=float(sum(row['loss'] for row in rows)),net=net,
        positive=len(positive),negative=sum(row['net']<0 for row in rows),flat=sum(row['net']==0 for row in rows),
        black_rate_all=len(positive)/40,active=len(active),inactive=len(inactive),
        active_zero=sum(row['entries']>0 and row['net']==0 for row in rows),
        black_rate_active=len(positive)/len(active) if active else None,
        median=float(np.median([row['net'] for row in rows])),worst=float(min(0,min(row['net'] for row in rows))),
        mean=net/40,mean_positive=float(np.mean([row['net'] for row in positive])) if positive else None,
        entries=quantity,mean_entries=quantity/40,median_entries=float(np.median([row['entries'] for row in rows])),
        mean_max_long=float(np.mean([row['max_long'] for row in rows])),mean_max_short=float(np.mean([row['max_short'] for row in rows])),
        max_long=float(max(row['max_long'] for row in rows)),max_short=float(max(row['max_short'] for row in rows)),
        fees=float(sum(row['fees'] for row in rows)),net_per_lot=net/quantity if quantity else None,
        worst_drawdown=float(max(row['max_drawdown'] for row in rows)),
        excluded_top3=[dict(session=row['session'],net=row['net']) for row in excluded],
        remaining_sessions=len(remaining),net_without_top3=float(sum(row['net'] for row in remaining)),
        median_without_top3=float(np.median([row['net'] for row in remaining])))


def entry_geometry(q: dict, orders: np.ndarray, spec: dict) -> None:
    """
    機能: 実新規のrank別距離と因果的に存在する待機極値を確認する。
    引数: q(dict)は正常気配、orders(np.ndarray)は十八列、spec(dict)は初回幅と間隔。
    返り値: None。未保存の取消状態は作り直さず独立期待線人工へ委譲する。
    """
    core.check(np.all(orders[:,1] == 1),'123通常台帳は新規のみ')
    pairs = {(int(row[2]),int(row[10])) for row in orders}
    core.check(len(pairs) == len(orders),'123同じ建方向rankを重複保有しない')
    values, first_indices = np.unique(q['last'],return_index=True)
    decisions = core.positions(q['row'],orders[:,3],'123入口判断')
    decoded = orders[:,17]-orders[:,2]*(spec['initial']+orders[:,10]*spec['spacing'])
    index = np.searchsorted(values,decoded)
    core.check(np.all(index < len(values)),'123初回とrank間隔を引いた極値が過去価格範囲内')
    core.near(values[index],decoded,'123待機極値は正常Lastの実在値')
    core.check(np.all(first_indices[index] <= decisions),'123未来Lastを待機極値へ使わない')
    core.check(np.all(orders[:,2]*(q['last'][decisions]-orders[:,17]) >= -1e-6),
               '123当時Lastが初回とrank間隔の発火線へ到達')


def saturation(orders: np.ndarray, proxy: np.ndarray, session: str, method: str) -> dict:
    """
    機能: 途中返済なしの両側上限到達と固定建値差を保存玉から算術確認する。
    引数: orders/proxy(np.ndarray)は新規と代理、session/method(str)は対象。
    返り値: dictは枚数と同枚数時の建値差・終端気配幅・費用の恒等式。
    """
    long = orders[orders[:,2] == 1]
    short = orders[orders[:,2] == -1]
    result = dict(session=session,method=method,long=len(long),short=len(short),
        both_caps=len(long)==len(short)==10,balanced=len(long)==len(short) and len(long)>0)
    if result['balanced']:
        qty = len(long)
        basis = float(short[:,7].sum()-long[:,7].sum())
        spread = float(proxy[0,16]-proxy[0,15])
        net = float(proxy[:,12].sum())
        core.near(basis*1000-qty*spread*1000-len(orders)*82,net,'123同枚数の固定建値差と気配幅及び全料')
        result.update(buy_average=float(long[:,7].mean()),sell_average=float(short[:,7].mean()),
            sell_minus_buy_average=basis/qty,locked_basis_gross=basis*1000,terminal_spread=spread,
            spread_liability=qty*spread*1000,fees=len(orders)*82,net=net,
            first_all_held_row=int(np.max(orders[:,4])))
    return result


def main(result: Path, expected_sha: str, output: Path) -> None:
    """
    機能: 根指定の完成結果と新四十NPZを各一読保全し全七百二十会計を確認する。
    引数: result(Path)は完成JSON、expected_sha(str)は根指定値、output(Path)は未使用自所有先。
    返り値: None。原市場・旧NPZ・戦略エンジン・試行台帳は読取又は実行しない。
    """
    core.check(not output.exists(),'123所有出力先未使用')
    core.check(core.sha(Path(previous.__file__).read_bytes()) == PREVIOUS_SHA,'123既代理監査source不変')
    core.check(core.sha(Path(core.__file__).read_bytes()) == previous.CORE_SHA,'123既独立算術source不変')
    raw = result.read_bytes()
    READS['完成結果'] += 1
    core.check(core.sha(raw) == expected_sha,'123根指定完成SHA')
    owned = output/'owned'
    owned.mkdir(parents=True)
    (owned/'完成結果.json').write_bytes(raw)
    data = json.loads(raw)
    core.check(data['passed'] and len(data['specs']) == 19 and len(data['runs']) == 720
        and len(data['cache']) == len(data['sessions']) == 40,'123十九unique新七百二十口座')
    core.check(data['financial_accounts'] == 720 and data['reused_baseline_accounts'] == 40
        and data['original_market_reads'] == data['API'] == data['実注文'] == 0,'123新金融と引用の由来')
    core.check(tuple(data['order_columns']) == core.ORDER_COLUMNS and tuple(data['lot_columns']) == core.LOT_COLUMNS
        and tuple(data['curve_columns']) == core.CURVE_COLUMNS and tuple(data['proxy_columns']) == previous.PROXY_COLUMNS,
        '123通常と代理の列契約')
    fixed = json.loads((WORK/'固定計画.json').read_text(encoding='utf-8'))
    proposal = json.loads((WORK/'試行計画.json').read_text(encoding='utf-8'))
    checked = json.loads((WORK/'事前照合の全出力.json').read_text(encoding='utf-8'))
    registered = json.loads((WORK/'正式登録の全出力.json').read_text(encoding='utf-8'))
    actual = json.loads(registered['stdout'])
    core.check(checked['終了コード'] == registered['終了コード'] == 0 and json.loads(checked['stdout'])['提案完全'] is True
        and actual['id'] == proposal['id'] and actual['spec'] == proposal['spec'],'123登録実体と完全提案')
    sources = {path:core.sha((ROOT/path).read_bytes()) for path in data['sources']}
    core.check(sources == data['sources'] == fixed['sources'] == proposal['spec']['implementation'],'123全正式源開始拘束')
    raw = (ROOT/fixed['input_manifest']['path']).read_bytes()
    core.check(core.sha(raw) == fixed['input_manifest']['sha256'],'123coverage目録SHA')
    meta = json.loads(raw)
    planned = {item['session']:item for item in meta['inputs']}
    refs = {ref['session']:ref for ref in data['cache']}
    core.check(len(planned) == len(refs) == 40 and set(planned) == set(refs) == set(data['sessions']), '123全場とcache一意')
    core.check(all((refs[s]['input_path'],refs[s]['input_sha256']) == (item['path'],item['sha256'])
        for s,item in planned.items()),'123四十固定入力参照同値')
    core.check(data['baseline'] == fixed['baseline'],'123基準四十行は固定前同値')
    prior_raw = (PRIOR/'audit/result/owned/完成結果.json').read_bytes()
    READS['既所有基準結果'] += 1
    core.check(core.sha(prior_raw) == BASELINE_SHA == data['baseline']['sha256'],'123既所有122基準SHA')
    baseline = [row for row in json.loads(prior_raw)['runs'] if row['method'] == 'HOLD_CLOSE_6M']
    core.check(len(baseline) == 40 and baseline == data['baseline']['rows'],'123旧四十会計は完全引用')
    binding = (ROOT/fixed['artificial_audit']['path']).read_bytes()
    core.check(core.sha(binding) == fixed['artificial_audit']['sha256'] and json.loads(binding)['passed'],
        '123独立期待線人工の正式固定')
    runtime = json.loads((WORK/'実行プロセスの期待線と通常高速確認.json').read_text(encoding='utf-8'))
    core.check(runtime['passed'] and runtime['comparisons'] == len(runtime['cases']) == 19
        and all(case['entries'] > 0 for case in runtime['cases']),'123本番プロセス十九非空人工')
    core.check(runtime['engine_sha256'] == sources['work/stability123_20261017/engine123.py']
        and runtime['core_sha256'] == sources['work/stability123_20261017/core123.py'],'123人工と金融実装同一')
    core_text = (WORK/'core123.py').read_text(encoding='utf-8')
    core.check('line=anchor[s,j]+side*(initial+level[s,j]*spacing)*step' in core_text,
        '123源は初回とrank間隔の期待式を使用')
    loader = importlib.util.spec_from_file_location('audit123_catalog',WORK/'catalog123.py')
    catalog = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(catalog)
    core.check(catalog.specifications() == fixed['specs'] == data['specs'],'123十九固定仕様')
    reused = [index for index,spec in enumerate(data['specs']) if spec['reused']]
    core.check(reused == [2] and data['specs'][2]['id'] == 'I3_G3','123旧3pt基準は一つだけ引用')
    loader = importlib.util.spec_from_file_location('audit123_contract',ROOT/'work/stability120_20261017/catalog120.py')
    contract = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(contract)
    rows = {(row['session'],row['method']):row for row in data['runs']}
    core.check(len(rows) == 720 and all(row['symbol'] == 'TOPIX' for row in data['runs']),'123新全口座一意')
    reports, locks = [], []
    for number,ref in enumerate(data['cache']):
        session = ref['session']
        path = (ROOT/ref['path']).resolve()
        core.check(path.is_relative_to((WORK/'measurement').resolve()),'123新measurementだけ一読')
        raw = path.read_bytes()
        READS['新小cache'] += 1
        core.check(core.sha(raw) == ref['sha256'],'123小cache同bytes')
        (owned/(session+'.npz')).write_bytes(raw)
        with np.load(BytesIO(raw),allow_pickle=False) as stored:
            arrays = {name:stored[name].copy() for name in stored.files}
        expected_keys = {f'{i}__{key}' for i in range(19) if i not in reused for key in ('orders','lots','curves','proxy_lots')}
        expected_keys |= {'quotes__'+key for key in ('row','time','last','bid','ask')}
        core.check(set(arrays) == expected_keys,'123十八新条件だけを保存し旧基準配列なし')
        quotes = {key:arrays['quotes__'+key] for key in ('row','time','last','bid','ask')}
        setting = contract.settings('TOPIX',session)
        accepted,_ = previous.valid_quotes_e(quotes,setting)
        for index,spec in enumerate(data['specs']):
            if spec['reused']:
                continue
            o,l,c,p = [arrays[f'{index}__{key}'] for key in ('orders','lots','curves','proxy_lots')]
            answer = previous.audit_account(quotes,o,l,c,p,rows[session,spec['id']],setting,'CLOSE_PROXY',planned[session]['terminal_proxy'])
            entry_geometry(accepted,o,spec)
            reports.append(dict(session=session,method=spec['id'],**answer))
            locks.append(saturation(o,p,session,spec['id']))
        print(f'{number+1}/40 十八新条件の独立保存会計一致',flush=True)
    core.check(sources == {path:core.sha((ROOT/path).read_bytes()) for path in sources},'123正式源終端不変')
    core.check(core.sha(Path(previous.__file__).read_bytes()) == PREVIOUS_SHA,'123既代理算術終端不変')
    unclosed = [row for row in reports if row['reported_unclosed']]
    proof = dict(passed=not unclosed,result_sha256=expected_sha,
        source_sha256=core.sha(Path(__file__).read_bytes()),prior_accounting_source_sha256=PREVIOUS_SHA,
        sources=sources,checks=dict(core.CHECKS),reads=dict(READS),new_accounts=len(reports),
        reused_baseline_accounts=40,unclosed_accounts=unclosed,reconstructed=reports,
        original_market_reads=0,old_npz_reads=0,financial_replay=0,registry_changes=0,
        留保='保存台帳算術と実新規資格の確認。取消済み未約定anchor状態の全履歴は保存されないため、源の初回+rank間隔式と金融前独立期待線人工へ委譲。代理は実引け約定ではなく同じ既知40場の価格代用仮定。')
    target = output/'新七百二十口座と旧四十引用の独立会計監査.json'
    core.save(target,proof)
    statistics_by_method = {}
    for spec in data['specs']:
        subset = baseline if spec['reused'] else [row for row in data['runs'] if row['method'] == spec['id']]
        statistics_by_method[spec['id']] = dict(family=spec['family'],initial=spec['initial'],spacing=spec['spacing'],
            reused=spec['reused'],**statistics(subset))
    core.save(output/'十九条件の全四十場統計と両側上限固定建値差.json',dict(passed=True,
        statistics=statistics_by_method,saturation=locks,financial_replay=0,
        留保='総net/総枚数は補助で、独立した固定枚数戦略の成績ではない。基準40は保存引用で新720へ加えない。'))
    compact = {name:{key:value[key] for key in ('net','positive','negative','inactive','median','worst','entries','net_without_top3')}
               for name,value in statistics_by_method.items()}
    print(json.dumps(dict(passed=not unclosed,accounts=len(reports),sha256=core.sha(target.read_bytes()),
        reads=dict(READS),statistics=compact),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    main(args.result,args.sha256,args.output)
