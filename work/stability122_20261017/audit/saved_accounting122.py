"""通常返済と引け代理精算を混ぜず、保存八十会計を独立算術で確認する。"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import importlib.util
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PRIOR = ROOT/'work/stability120_20261017'
sys.path.insert(0, str(PRIOR/'audit'))
import saved_accounting120 as core
from qualifications120e import qualifications, valid_quotes_e

CORE_SHA = '3cf2c6727301b401a548b501ece268d62e996ec92528f35bb6b7897f2e78d16e'
BASELINE_SHA = 'ade79de8165fefe68d6f6be861b38f991fc650bb6b658e70329cf667b9bacd1c'
PROXY_COLUMNS = ('uid','side','rung','entry_decision_row','entry_row','entry_time','entry_price',
    'reference_row','reference_time','exit_price','gross','fees','net','planned_exit_time',
    'reference_last','reference_bid','reference_ask')
READS = Counter()
JST = timezone(timedelta(hours=9))


def normal_summary(row: dict, lots: np.ndarray) -> dict:
    """
    機能: 通常台帳で独立算術に必要な未表示内訳だけを付加する。
    引数: row(dict)は保存小会計、lots(np.ndarray)は通常十九列。
    返り値: dictは追加した純実現内訳。既存集計値を上書きしない。
    """
    answer = dict(row)
    extra = dict(realized_net=float(lots[:,13].sum()),
        forced_loss=float(np.maximum(-lots[lots[:,14]==9,13],0).sum()),
        forced_profit=float(np.maximum(lots[lots[:,14]==9,13],0).sum()),
        trail_net=float(lots[lots[:,14]==1,13].sum()))
    for name, value in extra.items():
        if name in answer:
            core.near(answer[name], value, '122保存済み通常内訳の'+name)
        else:
            answer[name] = value
    return answer


def expected_proxy(q: dict, orders: np.ndarray, setting: dict) -> np.ndarray:
    """
    機能: 正常気配の最後を参照して各UIDの別終了会計を独立構成する。
    引数: q(dict)は正常気配、orders(np.ndarray)は実新規のみ、setting(dict)は契約値。
    返り値: np.ndarrayは十七列の代理玉。通常の返済注文を生成しない。
    """
    target = setting['session_end']
    core.check(target-360 <= q['time'][-1] <= target, '122代理の参照は引け直前六分以内')
    fee = math.floor(setting['fee']+1e-9)
    certificate = []
    for entry in orders:
        side = entry[2]
        price = q['bid'][-1] if side == 1 else q['ask'][-1]
        gross = side*(price-entry[7])*setting['multiplier']
        certificate.append([entry[0],side,entry[10],entry[3],entry[4],entry[6],entry[7],
            q['row'][-1],q['time'][-1],price,gross,2*fee,gross-2*fee,target,
            q['last'][-1],q['bid'][-1],q['ask'][-1]])
    return np.asarray(certificate,float).reshape(-1,17)


def audit_account(quotes: dict, orders: np.ndarray, lots: np.ndarray, curve: np.ndarray,
                  proxy: np.ndarray, row: dict, setting: dict, kind: str, coverage: dict) -> dict:
    """
    機能: 全気配時価と通常約定を先に確認し、代理は別台帳・別終端事象として確認する。
    引数: quotes(dict)、通常orders/lots/curveとproxy(np.ndarray)、row/setting/coverage(dict)、kind(str)。
    返り値: dictは通常実返済と代理清算の枚数を分離した小診断。
    """
    q, rejected = valid_quotes_e(quotes, setting)
    core.near(row['clock_rejected'], rejected, '122正常Last時計BBOの棄却数')
    core.near(row['step'], 1.0, '122幅は一pt固定')
    core.check(proxy.ndim == 2 and proxy.shape[1] == 17, '122代理十七列')
    entries = orders[orders[:,1]==1]
    context = row['context']
    normalized = normal_summary(row,lots)
    normalized['clock_rejected'] = 0
    first_mid = (q['bid'][0]+q['ask'][0])/2
    spec = dict(mode=14, fraction=1.0/first_mid)
    fee = math.floor(setting['fee']+1e-9)
    if kind == 'EARLY':
        core.check(context['kind'] == 'EARLY' and context['approximation'] is False
                   and context['scheduled_time'] == setting['close_time'] and context['base_unclosed'] == 0,
                   '122通常終端の意味を保持')
        core.check(len(proxy) == row['proxy_count'] == 0 and len(lots) == row['regular_closed'] == len(entries)
                   and np.all(lots[:,14] == 9), '122通常側は全玉時刻返済だけ')
        answer = core.audit_account(q,orders,lots,curve,normalized,setting,spec)
        exits = orders[orders[:,1]==2]
        positions = core.positions(q['row'],exits[:,3],'122通常返済判断')
        core.check(np.all(q['time'][positions] >= setting['close_time']), '122早期返済を予定時刻前へ遡らない')
        core.check(not np.any(orders[:,9] == 1), '122途中の利益追尾注文なし')
        cleared = len(lots)
        proxy_count = 0
    else:
        core.check(kind == context['kind'] == 'CLOSE_PROXY' and context['measured'] is True,
                   '122引け側は測定資格のある代理会計')
        core.check(len(lots) == row['regular_closed'] == 0 and len(orders) == len(entries)
                   and np.all(orders[:,1] == 1), '122代理側の通常台帳に架空返済なし')
        core.check(row['proxy_count'] == context['base_unclosed'] == len(entries), '122全入口UIDを代理対象へ保持')
        # ----------------------------------------
        # 通常曲線は清算前の在庫。代理後summaryをそのまま通常曲線へ当てはめない。
        normalized.update(net=float(curve[-1,2]), cash=-fee*len(entries),profit=0.,loss=0.,fees=fee*len(entries),
            closed_lots=0,wins=0,losses=0,unclosed=len(entries),held_entry_fees=fee*len(entries),
            last_equity=float(curve[-1,2]),realized_net=0.,long_net=0.,short_net=0.)
        answer = core.audit_account(q,orders,lots,curve,normalized,setting,spec)
        certificate = expected_proxy(q,orders,setting)
        core.near(proxy,certificate,'122代理全UID十七列は最終正常BBOと全費用に一致')
        core.check(len(set(proxy[:,0])) == len(proxy) and set(proxy[:,0]) == set(entries[:,0]),
                   '122全UIDを一度だけ代理清算')
        target = setting['session_end']
        expected_context = dict(scheduled_time=target,reference_row=int(q['row'][-1]),
            reference_time=float(q['time'][-1]),age_seconds=float(target-q['time'][-1]),
            reference_last=float(q['last'][-1]),reference_bid=float(q['bid'][-1]),reference_ask=float(q['ask'][-1]))
        for key,value in expected_context.items():
            core.near(context[key],value,'122代理参照の'+key)
        core.check(context['approximation'] == (q['time'][-1] < target), '122代理と実時刻同値を区別')
        core.near(context['reference_row'],coverage['row'],'122事前coverage原rowと同じ')
        core.near(context['reference_time'],coverage['epoch'],'122事前coverage時計と同じ')
        core.near(context['reference_bid'],coverage['bid'],'122事前coverage買気配と同じ')
        core.near(context['reference_ask'],coverage['ask'],'122事前coverage売気配と同じ')
        values = certificate[:,12]
        proxy_net = float(values.sum())
        expected_summary = dict(net=proxy_net,cash=proxy_net,profit=float(np.maximum(values,0).sum()),
            loss=float(np.maximum(-values,0).sum()),fees=2*fee*len(entries),closed_lots=len(entries),
            wins=int(np.count_nonzero(values>0)),losses=int(np.count_nonzero(values<0)),unclosed=0,
            held_entry_fees=0,last_equity=proxy_net,long_net=float(values[certificate[:,1]==1].sum()),
            short_net=float(values[certificate[:,1]==-1].sum()),last_time=float(q['time'][-1]))
        for key,value in expected_summary.items():
            core.near(row[key],value,'122代理後の小会計'+key)
        core.near(-fee*len(entries)+sum(certificate[:,10]-fee),proxy_net,'122新規料と返済料の二重計上なし')
        core.near(proxy_net,curve[-1,2],'122終端代理額と最終全玉清算時価が一致')
        core.near(curve[-1,3],-fee*len(entries),'122清算前曲線cashに将来の返済を混ぜない')
        core.near(curve[-1,5]+curve[-1,6],len(entries),'122清算前曲線の在庫を消さない')
        terminal = context['terminal_event']
        core.check(terminal['scheduled_time'] == target and terminal['long'] == terminal['short'] == 0
                   and '代理' in terminal['source'] and '実約定原行ではない' in terminal['source'], '122別終端事象の代理とゼロ在庫')
        core.near(terminal['equity'],proxy_net,'122代理終端事象の資産')
        core.near(terminal['cash'],proxy_net,'122代理終端事象の現金')
        last_reference = float(sum(entry[2]*(q['last'][-1]-entry[7])*setting['multiplier']-2*fee for entry in entries))
        core.near(context['last_price_reference_net'],last_reference,'122Last参考をBBO代理会計へ混ぜない')
        core.check(not np.any(orders[:,9] == 1), '122引け側も途中利益返済なし')
        cleared = 0
        proxy_count = len(certificate)
    qualifications(q,orders,row,setting,dict(mode=2,trail=float('inf')))
    return dict(entries=len(entries),regular_closed=cleared,proxy_closed=proxy_count,
        regular_open_before_proxy=len(entries)-cleared,reported_unclosed=int(row['unclosed']),
        net=float(row['net']),fees=float(row['fees']),max_drawdown=float(row['max_drawdown']),
        normal_accounting=answer,approximation=bool(context['approximation']))


def metrics(rows: list) -> dict:
    """
    機能: 同じ四十場分母で二条件と旧基準の結果を要約する。
    引数: rows(list[dict])は一条件の保存小会計。
    返り値: dictは損益・場数・費用。条件の選び直しはしない。
    """
    return dict(sessions=len(rows),profit=sum(row['profit'] for row in rows),loss=sum(row['loss'] for row in rows),
        net=sum(row['net'] for row in rows),positive=sum(row['net']>0 for row in rows),
        negative=sum(row['net']<0 for row in rows),flat=sum(row['net']==0 for row in rows),
        fees=sum(row['fees'] for row in rows),worst=min(row['net'] for row in rows))


def pure() -> None:
    """
    機能: 手書き一玉で代理の両気配と往復料・六分境界を検査する。
    引数: なし。
    返り値: None。エンジン又は市場資料は読取しない。
    """
    q = dict(row=np.array([1,2]),time=np.array([0.,40.]),last=np.array([100.,104.]),
        bid=np.array([100.,103.]),ask=np.array([100.5,104.5]))
    setting = dict(session_end=400.,fee=41.8,multiplier=1000.)
    entries = np.array([[1,1,1,0,1,0,0,100.5,41,0,0,1,100.25,100,100,100.5,0,100]],float)
    expected = np.array([[1,1,0,0,1,0,100.5,2,40,103,2500,82,2418,400,104,103,104.5]],float)
    core.near(expected_proxy(q,entries,setting),expected,'122人工はLastでなくbidへ全料付き代理清算')
    invalid = dict(setting,session_end=401.)
    try:
        expected_proxy(q,entries,invalid)
    except AssertionError:
        core.check(True,'122人工六分超は未測定を要求')
    else:
        raise AssertionError('六分超の代理を許容しました')
    core.save(HERE/'代理十七列と六分境界の独立算術接続.json',dict(passed=True,
        source_sha256=core.sha(Path(__file__).read_bytes()),accounting_source_sha256=CORE_SHA,
        checks=dict(core.CHECKS),actual_result_reads=0,financial_replay=0,original_market_reads=0))
    print('十七列代理と六分境界の純人工算術は一致。実結果読取0。',flush=True)


def main(result: Path, expected_sha: str, output: Path) -> None:
    """
    機能: 根の完成通知後だけ結果と新四十NPZを各一読保全して八十会計を照合する。
    引数: result(Path)は完成JSON、expected_sha(str)は根指定SHA、output(Path)は未使用所有先。
    返り値: None。元市場・旧NPZ・売買エンジンの実行・registry変更をしない。
    """
    core.check(not output.exists(),'122監査所有先未使用')
    core.check(core.sha(Path(core.__file__).read_bytes()) == CORE_SHA,'122既独立算術source不変')
    raw = result.read_bytes()
    READS['完成結果'] += 1
    core.check(core.sha(raw) == expected_sha,'122根指定完成SHA')
    owned = output/'owned'
    owned.mkdir(parents=True)
    (owned/'完成結果.json').write_bytes(raw)
    data = json.loads(raw)
    core.check(data['passed'] and len(data['specs']) == 2 and len(data['runs']) == 80
        and len(data['cache']) == len(data['sessions']) == 40,'122固定二条件八十会計四十cache')
    core.check(data['financial_accounts'] == 80 and data['reused_baseline_accounts'] == 40
        and data['original_market_reads'] == data['API'] == data['実注文'] == 0,'122金融と引用の由来')
    core.check(tuple(data['order_columns']) == core.ORDER_COLUMNS and tuple(data['lot_columns']) == core.LOT_COLUMNS
        and tuple(data['curve_columns']) == core.CURVE_COLUMNS and tuple(data['proxy_columns']) == PROXY_COLUMNS,'122通常列と代理列契約')
    sources = {path:core.sha((ROOT/path).read_bytes()) for path in data['sources']}
    core.check(sources == data['sources'],'122正式源開始不変')
    fixed = json.loads((WORK/'固定計画.json').read_text(encoding='utf-8'))
    proposal = json.loads((WORK/'試行計画.json').read_text(encoding='utf-8'))
    registration = json.loads((WORK/'正式登録の全出力.json').read_text(encoding='utf-8'))
    check = json.loads((WORK/'事前照合の全出力.json').read_text(encoding='utf-8'))
    actual = json.loads(registration['stdout'])
    core.check(registration['終了コード'] == check['終了コード'] == 0 and json.loads(check['stdout'])['提案完全'] is True
        and actual['id'] == proposal['id'] and actual['spec'] == proposal['spec'],'122登録実体と完全提案')
    core.check(sources == fixed['sources'] == proposal['spec']['implementation'],'122全源の同じ拘束')
    raw = (ROOT/fixed['input_manifest']['path']).read_bytes()
    core.check(core.sha(raw) == fixed['input_manifest']['sha256'],'122coverage入力目録SHA')
    meta = json.loads(raw)
    planned = {item['session']:item for item in meta['inputs']}
    refs = {ref['session']:ref for ref in data['cache']}
    core.check(len(planned) == len(refs) == 40 and set(planned) == set(refs) == set(data['sessions']),'122全四十場一意')
    core.check(all((refs[session]['input_path'],refs[session]['input_sha256']) ==
        (item['path'],item['sha256']) for session,item in planned.items()),'122保存coverage入力との全参照一致')
    core.check(data['baseline'] == fixed['baseline'],'122基準四十行は登録前固定と同値')
    baseline_raw = (ROOT/'work/stability121_20261017/audit/result/owned/完成結果.json').read_bytes()
    READS['既所有基準結果'] += 1
    core.check(core.sha(baseline_raw) == BASELINE_SHA == data['baseline']['sha256'],'122既所有121基準SHA')
    baseline = [row for row in json.loads(baseline_raw)['runs'] if row['method'] == 'G3_T5_RESET']
    core.check(len(baseline) == 40 and baseline == data['baseline']['rows'],'122基準四十会計の保存引用一致')
    artificial = (ROOT/fixed['artificial_audit']['path']).read_bytes()
    core.check(core.sha(artificial) == fixed['artificial_audit']['sha256'] and json.loads(artificial)['passed'],
        '122金融前独立人工の固定')
    runtime = json.loads((WORK/'実行プロセスの人工確認.json').read_text(encoding='utf-8'))
    core.check(runtime['passed'] and runtime['missing_window_rejected'] and len(runtime['cases']) == 2
        and all(case['entries'] > 0 for case in runtime['cases']),'122本番プロセスの非空人工と欠窓拒否')
    core.check(runtime['engine_sha256'] == sources['work/stability122_20261017/engine122.py']
        and runtime['base_engine_sha256'] == sources['work/stability121_20261017/engine121.py'],'122本番人工と金融source一致')
    core.check(data['specs'] == fixed['specs'] and [spec['kind'] for spec in data['specs']] == ['EARLY','CLOSE_PROXY'],
        '122二終了方式の固定')
    loader = importlib.util.spec_from_file_location('audit122_contract',PRIOR/'catalog120.py')
    catalog = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(catalog)
    rows = {(row['session'],row['method']):row for row in data['runs']}
    core.check(len(rows) == 80 and all(row['symbol'] == 'TOPIX' for row in data['runs']),'122八十口座はTOPIXだけ')
    reports = []
    for number,ref in enumerate(data['cache']):
        session = ref['session']
        path = (ROOT/ref['path']).resolve()
        core.check(path.is_relative_to((WORK/'measurement').resolve()),'122新measurementだけ一読')
        raw = path.read_bytes()
        READS['新小cache'] += 1
        core.check(core.sha(raw) == ref['sha256'],'122新小cache同bytes')
        (owned/(session+'.npz')).write_bytes(raw)
        with np.load(BytesIO(raw),allow_pickle=False) as stored:
            arrays = {name:stored[name].copy() for name in stored.files}
        expected_keys = {f'{i}__{key}' for i in (0,1) for key in ('orders','lots','curves','proxy_lots')}
        expected_keys |= {'quotes__'+key for key in ('row','time','last','bid','ask')}
        core.check(set(arrays) == expected_keys,'122政策別通常代理台帳の保存集合')
        quotes = {key:arrays['quotes__'+key] for key in ('row','time','last','bid','ask')}
        setting = catalog.settings('TOPIX',session)
        reference_entries = None
        for index,spec in enumerate(data['specs']):
            o,l,c,p = (arrays[f'{index}__{key}'] for key in ('orders','lots','curves','proxy_lots'))
            for value,columns in ((o,18),(l,19),(c,8),(p,17)):
                core.check(value.ndim == 2 and value.shape[1] == columns,'122政策番号なしの各台帳列数')
            entries = o[o[:,1] == 1]
            if reference_entries is None:
                reference_entries = entries.copy()
            else:
                core.check(np.array_equal(reference_entries,entries),'122全新規の方向時刻価格UIDが両条件同値')
            answer = audit_account(quotes,o,l,c,p,rows[session,spec['id']],setting,spec['kind'],planned[session]['terminal_proxy'])
            reports.append(dict(session=session,method=spec['id'],**answer))
        print(f'{number+1}/40 通常返済と別代理終端の会計一致',flush=True)
    core.check(sources == {path:core.sha((ROOT/path).read_bytes()) for path in sources},'122正式源終端不変')
    unclosed = [row for row in reports if row['reported_unclosed']]
    proof = dict(passed=not unclosed,result_sha256=expected_sha,
        source_sha256=core.sha(Path(__file__).read_bytes()),accounting_source_sha256=CORE_SHA,sources=sources,
        checks=dict(core.CHECKS),reads=dict(READS),saved_accounts=len(reports),unclosed_accounts=unclosed,
        normal_accounts=40,proxy_assumption_accounts=40,reused_baseline_accounts=40,reconstructed=reports,
        original_market_reads=0,old_npz_reads=0,financial_replay=0,registry_changes=0,
        留保='代理40会計は実約定ではなく許可された直前六分BBOの終端価格仮定。通常曲線に残る在庫・含損を消さず、別終端事象のゼロ在庫を確認。同じ既知40場の開発比較。')
    target = output/'八十通常及び代理終端会計の独立監査.json'
    core.save(target,proof)
    projection = dict(baseline=metrics(baseline),methods={spec['id']:metrics([
        row for row in data['runs'] if row['method'] == spec['id']]) for spec in data['specs']},
        september24={spec['id']:rows['2026-09-24_Day',spec['id']] for spec in data['specs']},financial_replay=0)
    core.save(output/'二終端の全四十場と九月二十四日の独立集計.json',projection)
    print(json.dumps(dict(passed=not unclosed,accounts=len(reports),sha256=core.sha(target.read_bytes()),
        reads=dict(READS),projection=projection),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pure',action='store_true')
    parser.add_argument('--result',type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if args.pure:
        pure()
    else:
        assert args.result and args.sha256 and args.output
        main(args.result,args.sha256,args.output)
