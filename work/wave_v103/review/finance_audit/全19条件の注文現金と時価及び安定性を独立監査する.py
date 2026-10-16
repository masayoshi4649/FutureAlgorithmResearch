"""正式再生を繰り返さず、全数注文から現金と時価を復元して結果を独立監査する。"""

import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR
import gzip
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import pickle
import sys
import traceback

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
WAVE = HERE.parents[1]
COUNTS = Counter()


def sha(path: Path) -> str:
    """
    機能: 小資料の内容指紋を取る。
    引数: path(Path)はsource又はJSON。
    返り値: strはSHA256。生原本とNPZを開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 結果又は事前固定のJSONだけを読む。
    引数: path(Path)は資料。
    返り値: dictは内容。金融再生は実行しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def equal(actual: object, expected: object, context: object) -> None:
    """
    機能: 数値とNoneを別に扱い、独立期待値と照合する。
    引数: actual/expected(object)、context(object)は値と診断情報。
    返り値: None。不一致は停止し、監査件数を数える。
    """
    if expected is None:
        assert actual is None, context
    elif isinstance(expected, (float, int, np.number)) and not isinstance(expected, bool):
        assert actual is not None and math.isclose(float(actual), float(expected), abs_tol=1e-4, rel_tol=1e-11), (context, actual, expected)
    else:
        assert actual == expected, (context, actual, expected)
    COUNTS['独立値照合'] += 1


def charge(quantity: int, symbol: str) -> int:
    """
    機能: 注文の片道料金を十進数で切り捨てる。
    引数: quantity(int)、symbol(str)は実枚数と商品。
    返り値: intは税込料金。エンジン又はaccountingのfee関数を呼ばない。
    """
    return int((Decimal(quantity) * Decimal('41.8' if symbol == 'TOPIX' else '11')).to_integral_value(rounding=ROUND_FLOOR))


# ----------------------------------------

def totals(parents: list[dict]) -> dict:
    """
    機能: 完結親を相殺前に集計して平均勝負額を計算する。
    引数: parents(list[dict])は注文現金から復元した親。
    返り値: dictは商品内G/L及び枚数。未取引は勝ちに数えない。
    """
    wins = [parent for parent in parents if parent['net'] > 1e-5]
    losses = [parent for parent in parents if parent['net'] < -1e-5]
    flat = [parent for parent in parents if abs(parent['net']) <= 1e-5]
    profit, loss = sum(parent['net'] for parent in wins), -sum(parent['net'] for parent in losses)
    average_win = profit / len(wins) if wins else None
    average_loss = loss / len(losses) if losses else None
    return dict(profit=profit, loss=loss, net=profit-loss, gross=sum(parent['gross'] for parent in parents),
        fees=sum(parent['fees'] for parent in parents), campaigns=len(parents), winning_campaigns=len(wins),
        losing_campaigns=len(losses), flat_campaigns=len(flat), winning_lots=sum(parent['quantity'] for parent in wins),
        losing_lots=sum(parent['quantity'] for parent in losses), flat_lots=sum(parent['quantity'] for parent in flat),
        lots=sum(parent['quantity'] for parent in parents), profit_share=profit/(profit+loss) if profit+loss else None,
        average_win=average_win, average_loss=average_loss,
        payoff=average_win/average_loss if average_win is not None and average_loss is not None else None)


def sum_rows(rows: list[dict]) -> dict:
    """
    機能: 同商品の相殺前親別利益・損失を合計し、比率を再計算する。
    引数: rows(list[dict])は独立会計行。
    返り値: dictは期間集計。研究側aggregateを呼ばない。
    """
    fields = ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'winning_campaigns', 'losing_campaigns',
              'flat_campaigns', 'winning_lots', 'losing_lots', 'flat_lots', 'lots')
    result = {field: sum(row[field] for row in rows) for field in fields}
    nw, nl = result['winning_campaigns'], result['losing_campaigns']
    result.update(profit_share=result['profit']/(result['profit']+result['loss']) if result['profit']+result['loss'] else None,
        average_win=result['profit']/nw if nw else None, average_loss=result['loss']/nl if nl else None,
        payoff=(result['profit']/nw)/(result['loss']/nl) if nw and nl else None)
    return result


def lineage_check(packet: dict, raw: dict, history: dict, side: int) -> None:
    """
    機能: 保存lineageを当時以前のeventと原行から独立復元する。
    引数: packet/raw/history(dict)、side(int)は状態、源原行、由来、参加方向。
    返り値: None。未来段階、異なるepisode及びraw対応不一致を拒否する。
    """
    row, anchor = history['row'], history['anchor_raw_seq']
    candidates = np.flatnonzero((packet['event_anchor_raw_seq'] == anchor)
        & (packet['events'][:, 2] == side) & (packet['events'][:, 0] <= row))
    assert len(candidates)
    event = packet['events'][candidates[-1]]
    equal(history['last_event_index'], int(candidates[-1]), 'lineage最後event')
    equal(history['raw_seq'], int(raw['raw_seq'][row]), 'lineage原seq')
    equal(history['price_time_s'], float(raw['price_time_s'][row]), 'lineage価格代理時計')
    for offset, name in enumerate(('anchor','prepared','recovery','moved','ready','first_price_move'), 6):
        index = int(event[offset])
        expected = None if index < 0 else dict(row=index, raw_seq=int(raw['raw_seq'][index]),
                                               price_time_s=float(raw['price_time_s'][index]))
        assert index <= row and history['stages'][name] == expected
        COUNTS['当時段階lineage'] += 1


def audit_ledger(ledger: dict, account: dict, peer: dict, config: dict, symbol: str) -> dict:
    """
    機能: 一新口座を注文だけから現金・親・玉・全時価・保有へ復元する。
    引数: ledger/account/peer/config(dict)、symbol(str)は保存台帳、活動、相手、条件、商品。
    返り値: dictは独立会計行。新金融再生、raw及びNPZ読取は0。
    """
    record, source = account['normal_record'], account['source']
    n, multiplier = len(record['time_s']), 1000 if symbol == 'TOPIX' else 10
    orders, trades = ledger['orders'], ledger['trades']
    oc = {name:index for index,name in enumerate(ledger['order_columns'])}
    tc = {name:index for index,name in enumerate(ledger['trade_columns'])}
    gc = {name:index for index,name in enumerate(ledger['growth_cohort_columns'])}
    assert orders.shape[1] == 17 and trades.shape[1] == 16
    assert np.isfinite(orders).all() and np.isfinite(trades).all()
    assert np.all(np.diff(orders[:,oc['row']]) >= 0)
    bid, ask = record['bid'], record['ask']
    assert np.isfinite(bid).all() and np.isfinite(ask).all() and np.all((bid>0)&(ask>bid))
    cash_delta, position_delta = np.zeros((n,2)), np.zeros((n,2))
    live, parents, uid = {}, [], set()
    diags = {int(row['order_uid']):row for row in ledger['raw_entry_diagnostics']}
    for order in orders:
        get = lambda name: order[oc[name]]
        row, decision, parent, src, side, quantity, new, reason = [int(get(name)) for name in
            ('row','decision_row','parent_id','source','action_side','quantity','is_entry','reason')]
        ident, price, fee = int(get('uid')), float(get('price')), float(get('fee'))
        assert 0 <= row < n and 0 <= decision <= row and src in (0,1) and side in (-1,1)
        assert quantity > 0 and get('quantity') == quantity and new in (0,1) and ident not in uid
        uid.add(ident)
        equal(fee, charge(quantity,symbol), ('fee',config['id'],symbol,row))
        equal(price, record['ask' if side==1 else 'bid'][row], '約定時BBO')
        equal(get('fill_time'), record['time_s'][row], '約定価格時計')
        if config['kind']=='portfolio':
            assert parent % 2 == src and ident % 2 == src
        key = src,parent
        if new:
            assert key not in live and key not in {(p['source'],p['parent_id']) for p in parents}
            assert decision < row and row == decision+1 and get('method') == 0
            equal(quantity,config['allocations'][symbol][src] if config['kind']=='portfolio' else config['quantity'][symbol],'実設定枚数')
            assert record['start']+300 <= record['time_s'][decision] < record['limit']-300
            case_id = ('C1' if src==0 else 'R1') if config['kind']=='portfolio' else config['id']
            pulse = account['pulses'][case_id]
            equal(int(pulse['normal_event'][decision]), side, '判断同normal行pulse')
            raw_row = int(source['execution_to_raw_index'][decision])
            assert source['qualified'][raw_row]
            decision_records = [value for value in pulse['normal_decisions'] if value['normal_row']==decision]
            assert len(decision_records)==1 and decision_records[0]['row']==raw_row
            diag = diags[ident]
            equal(diag['decision_normal_row'], decision, 'diagnostic normal判断')
            equal(diag['decision_raw_row'], raw_row, 'diagnostic raw判断')
            equal(diag['fill_raw_row'], int(source['execution_to_raw_index'][row]), 'diagnostic raw約定')
            assert diag['episode']['lineage'] == decision_records[0]['lineage']
            for history in decision_records[0]['lineage']:
                family = history['episode'][0]
                packet_id = family+'1' if case_id=='U_C1R1' else account['case_to_packet'][case_id]
                lineage_check(account['packets'][packet_id], source, history['own'], side)
                assert account['packets'][packet_id]['ready'][raw_row,0 if side==1 else 1]
                ph = history['peer']
                if ph is not None:
                    lineage_check(peer['packets'][packet_id],peer['source'],ph,side)
                    assert 0 < history['own']['price_time_s']-ph['price_time_s'] <=15
                    first = np.flatnonzero(peer['source']['price_time_s']==ph['price_time_s'])[0]
                    assert ph['row']==first
                    assert peer['packets'][packet_id]['ready'][ph['row'],0 if side==1 else 1]
            live[key]=dict(parent_id=parent,source=src,side=side,quantity=quantity,price=price,fee=fee,row=row,decision=decision)
            COUNTS['全実新規のpulse_BBO_lineage']=COUNTS['全実新規のpulse_BBO_lineage']+1
        else:
            assert key in live
            entry=live.pop(key)
            assert side==-entry['side'] and quantity==entry['quantity']
            gross=float(Decimal(entry['side']*quantity*multiplier)*(Decimal(str(price))-Decimal(str(entry['price']))))
            net=gross-entry['fee']-fee
            parent_result=dict(parent_id=parent,source=src,side=entry['side'],quantity=quantity,
                gross=gross,fees=entry['fee']+fee,net=net,entry_row=entry['row'],exit_row=row)
            matched=trades[(trades[:,tc['parent_id']]==parent)&(trades[:,tc['source']]==src)]
            assert len(matched)==1
            for name,value in dict(entry_row=entry['row'],exit_row=row,side=entry['side'],quantity=quantity,
                entry_price=entry['price'],exit_price=price,entry_fee=entry['fee'],exit_fee=fee,gross=gross,net=net).items():
                equal(matched[0,tc[name]],value,('親',name))
            cohort=ledger['growth_cohorts'][ledger['growth_cohorts'][:,gc['parent_id']]==parent]
            assert len(cohort)==1
            for name,value in dict(side=entry['side'],quantity=quantity,entry_row=entry['row'],exit_row=row,
                entry_price=entry['price'],exit_price=price,entry_fee=entry['fee'],exit_fee_share=fee,gross=gross,net=net,
                order_uid=next(int(o[oc['uid']]) for o in orders if int(o[oc['parent_id']])==parent and int(o[oc['is_entry']])==1)).items():
                equal(cohort[0,gc[name]],value,('玉',name))
            if config['kind']=='portfolio':
                assert int(cohort[0,gc['cohort_id']]) %2==src
            parents.append(parent_result)
        cash_delta[row,src]-=side*quantity*price*multiplier+fee
        position_delta[row,src]+=side*quantity
        COUNTS['実注文']+=1
    assert not live and len(parents)==len(trades)==len(ledger['growth_cohorts'])
    positions=np.cumsum(position_delta,axis=0)
    cash=np.cumsum(cash_delta,axis=0)
    liquidation=np.where(positions>=0,bid[:,None],ask[:,None])
    absolute=np.abs(positions).astype(np.int64)
    np.testing.assert_array_equal(absolute,np.abs(positions))
    remaining_fee=absolute*209//5 if symbol=='TOPIX' else absolute*11
    expected_sources=cash+positions*liquidation*multiplier-remaining_fee
    expected_curve=expected_sources.sum(axis=1)
    np.testing.assert_allclose(ledger['source_curve'],expected_sources,atol=1e-4,rtol=0)
    np.testing.assert_allclose(ledger['curve'],expected_curve,atol=1e-4,rtol=0)
    trace=ledger['target_trace']
    assert trace.shape==(n,6) and np.isfinite(trace).all() and np.all(trace>=0)
    np.testing.assert_array_equal(trace[:,0],np.maximum(positions,0).sum(axis=1))
    np.testing.assert_array_equal(trace[:,1],np.maximum(-positions,0).sum(axis=1))
    np.testing.assert_array_equal(trace[:,2]+trace[:,3]-trace[:,0]-trace[:,1],trace[:,4])
    assert np.all(trace[:,2]>=trace[:,0]) and np.all(trace[:,3]>=trace[:,1])
    assert np.all(trace[:,5]<=trace[:,0]+trace[:,1]) and not trace[-1].any()
    cap=(10 if symbol=='TOPIX' else 20) if config['kind']=='portfolio' else 1
    assert np.all(trace[:,:4]<=cap)
    result=totals(parents)
    equity=np.r_[0.,expected_curve]
    result.update(equity_peak=float(equity.max()),equity_trough=float(equity.min()),
        equity_drawdown=float((np.maximum.accumulate(equity)-equity).max()),
        order_count=len(orders),entry_order_count=len(parents),adding_order_count=0)
    result['sources']={name:totals([p for p in parents if p['source']==src]) for src,name in enumerate(('J2','O06'))}
    result['directions']={name:totals([p for p in parents if p['side']==side]) for side,name in ((1,'買い'),(-1,'売り'))}
    COUNTS['全時価とtrace行']+=n
    COUNTS['新口座']+=1
    return result


# ----------------------------------------

def aggregate_check(actual: dict, rows: list[dict], context: object) -> None:
    """
    機能: 会計期間を再集計し、活動と最大経路損失を別に検証する。
    引数: actual(dict)、rows(list[dict])、context(object)は掲載集計、独立行、診断情報。
    返り値: None。親G/Lの相殺、未活動を勝ちとする不一致を拒否する。
    """
    for name,value in sum_rows(rows).items():
        equal(actual[name],value,(context,name))
    active=[row for row in rows if row['campaigns']>0]
    expected=dict(active_sessions=len(active),no_trade_sessions=len(rows)-len(active),
        positive_sessions=sum(row['net']>1e-5 for row in active),losing_sessions=sum(row['net']<-1e-5 for row in active),
        session_count=len(rows),positive_session_rate=sum(row['net']>1e-5 for row in active)/len(active) if active else None,
        all_sessions_profitable=all(row['net']>1e-5 for row in rows),worst_session=min((row['net'] for row in rows),default=0))
    cash,peak,draw=0.,0.,0.
    for row in rows:
        draw=max(draw,row['equity_drawdown'],peak-cash-row['equity_trough'])
        peak=max(peak,cash+row['equity_peak'])
        cash+=row['net']
    expected['equity_drawdown']=draw
    for name,value in expected.items():
        equal(actual[name],value,(context,name))
    for family in ('sources','directions'):
        for name in actual[family]:
            for field,value in sum_rows([row[family][name] for row in rows]).items():
                equal(actual[family][name][field],value,(context,family,name,field))


def stable_check(actual: dict, rows: list[dict], config: dict, refs: dict, symbol: str) -> None:
    """
    機能: 設定合計枚数の下方尺度と活動場赤字率を独立算数で照合する。
    引数: actual(dict)、rows(list[dict])、config/refs(dict)、symbol(str)は掲載値、独立行、条件、保存始値、商品。
    返り値: None。無取引を低損失の成功へ変えない。
    """
    quantity=sum(config['allocations'][symbol]) if config['kind']=='portfolio' else config['quantity'][symbol]
    multiplier=1000 if symbol=='TOPIX' else 10
    active=[row for row in rows if row['campaigns']>0]
    losses=[row for row in active if row['net']<-1e-5]
    units={row['session']:float(Decimal(str(refs[row['session']+'|'+symbol]['ref_open']['value']))*quantity*multiplier*Decimal('.001')) for row in rows}
    negatives=[min(row['net']/units[row['session']],0)**2 for row in active]
    best=max(rows,key=lambda row:row['net']) if rows else None
    expected=dict(session_count=len(rows),active_sessions=len(active),no_trade_sessions=len(rows)-len(active),
        positive_sessions=sum(row['net']>1e-5 for row in active),losing_sessions=len(losses),
        flat_active_sessions=sum(abs(row['net'])<=1e-5 for row in active),
        losing_active_rate=len(losses)/len(active) if active else None,
        downside_rms_units=math.sqrt(sum(negatives)/len(active)) if active else None,
        worst_session_loss_yen=max((-row['net'] for row in losses),default=0),
        worst_session_loss_units=max((-row['net']/units[row['session']] for row in losses),default=0),
        mean_losing_session_yen=sum(-row['net'] for row in losses)/len(losses) if losses else None,
        configured_quantity=quantity,activity_adequate=len(active)>=16 and sum(row['campaigns'] for row in active)>=20,
        best_session=best['session'] if best else None,
        without_best_session_net=sum(row['net'] for row in rows if best is None or row['session']!=best['session']))
    for name,value in expected.items():
        equal(actual[name],value,('安定性',config['id'],symbol,name))


def main() -> None:
    """
    機能: 完了manifest出現後だけ全19×64を一回監査し、独立証跡を保存する。
    引数: CLI --root-results-complete(bool)は明示起動条件。
    返り値: None。再生又はcounterfactualは生成しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--root-results-complete',action='store_true',required=True)
    parser.parse_args()
    destination=HERE/'全19条件と全32セッションの独立金融監査.json'
    assert not destination.exists()
    final_path=WAVE/'金融全32の結果.json'
    assert final_path.exists(),'正式完了manifest前に金融を読みません'
    final,fixed=read(final_path),read(WAVE/'金融事前固定.json')
    assert final['全合格'] and fixed['全合格'] and final['sessions']==fixed['sessions']
    assert len(fixed['catalog'])==19 and len(fixed['sessions'])==32
    assert final['source_SHA256']==fixed['source_SHA256']
    for name,wanted in fixed['source_SHA256'].items():
        assert sha(ROOT/name)==wanted,name
    docs={config['id']:read(ROOT/final['results'][config['id']]['path']) for config in fixed['catalog']}
    for ident,item in final['results'].items():
        assert sha(ROOT/item['path'])==item['SHA256'],ident
    refs={}
    for path in (ROOT/'work/wave_v91/inputs/metadata.json',ROOT/'work/wave_v102/holdout_input/metadata.json'):
        refs.update(read(path)['references'])
    spec=importlib.util.spec_from_file_location('独立金融監査の一場活動読取',WAVE/'activity/data.py')
    activity=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=activity
    spec.loader.exec_module(activity)
    computed={config['id']:[] for config in fixed['catalog']}
    hashes={}
    old={}
    for part in ('front','back','holdout_results'):
        path=ROOT/'work/wave_v102'/part/'results/G0_Q1_X1.json'
        old.update({(row['session'],row['symbol']):row for row in read(path)['rows']})
    assert len(old)==64
    for session in fixed['sessions']:
        cache=activity.load_session(session,verify=True)
        COUNTS['activity一場読取']+=1
        for config in fixed['catalog']:
            ident=config['id']
            for symbol in ('TOPIX','NK225'):
                listed=[row for row in docs[ident]['rows'] if row['session']==session and row['symbol']==symbol]
                assert len(listed)==1
                listed=listed[0]
                if config['kind']=='previous':
                    assert listed==old[session,symbol]
                    independent=dict(listed)
                    COUNTS['旧対照委譲口座']+=1
                else:
                    item=docs[ident]['ledgers'][session+'|'+symbol]
                    path=ROOT/item['path']
                    assert path.resolve().is_relative_to((WAVE/'finance/ledger').resolve())
                    data=path.read_bytes()
                    fingerprint=hashlib.sha256(data).hexdigest()
                    assert fingerprint==item['SHA256']
                    hashes[str(path.relative_to(ROOT))]=fingerprint
                    ledger=pickle.loads(gzip.decompress(data))
                    other='NK225' if symbol=='TOPIX' else 'TOPIX'
                    independent=audit_ledger(ledger,cache['accounts'][symbol],cache['accounts'][other],config,symbol)
                    for name in ('profit','loss','net','gross','fees','campaigns','winning_campaigns','losing_campaigns',
                        'flat_campaigns','winning_lots','losing_lots','flat_lots','lots','profit_share','average_win',
                        'average_loss','payoff','equity_peak','equity_trough','equity_drawdown','order_count','entry_order_count','adding_order_count'):
                        equal(listed[name],independent[name],('口座',ident,session,symbol,name))
                    for family in ('sources','directions'):
                        for name,value in independent[family].items():
                            for field,number in value.items():
                                equal(listed[family][name][field],number,('口座',family,name,field))
                    independent.update(session=session,symbol=symbol)
                computed[ident].append(independent)
        print(session+' 全19×2の独立現金・時価・判断監査完了',flush=True)
        del cache
    conclusions={}
    for config in fixed['catalog']:
        ident=config['id']
        for label,sessions in (('前16',fixed['sessions'][:16]),('後16',fixed['sessions'][16:]),('全32',fixed['sessions'])):
            for symbol in ('TOPIX','NK225'):
                rows=[row for session in sessions for row in computed[ident] if row['session']==session and row['symbol']==symbol]
                aggregate_check(docs[ident]['periods'][label][symbol],rows,(ident,label,symbol))
                stable_check(docs[ident]['stability'][label][symbol],rows,config,refs,symbol)
        conclusions[ident]={}
        for symbol in ('TOPIX','NK225'):
            value=docs[ident]['periods']['全32'][symbol]
            state=docs[ident]['stability']['全32'][symbol]
            payoff_good=value['payoff'] is not None and value['payoff']>1
            if value['profit']>0 and value['loss']==0:
                payoff_good=True
            conclusions[ident][symbol]=dict(net=value['net'],profit=value['profit'],loss=value['loss'],
                profit_share=value['profit_share'],payoff=value['payoff'],active_sessions=state['active_sessions'],
                losing_sessions=state['losing_sessions'],no_trade_sessions=state['no_trade_sessions'],
                losing_active_rate=state['losing_active_rate'],worst_session_loss_yen=state['worst_session_loss_yen'],
                downside_rms_units=state['downside_rms_units'],activity_adequate=state['activity_adequate'],
                without_best_session_net=state['without_best_session_net'],
                合計黒字と活動と損小利大=bool(state['activity_adequate'] and value['net']>0 and payoff_good),
                金額利益8割=bool(value['profit_share'] is not None and value['profit_share']>=.8),
                全セッション黒字=value['all_sessions_profitable'])
    assert COUNTS['新口座']==1152 and COUNTS['旧対照委譲口座']==64 and COUNTS['activity一場読取']==32
    for name,wanted in fixed['source_SHA256'].items():
        assert sha(ROOT/name)==wanted,name
    assembly=HERE.parent/'金融one_session組立と実枚数及び安定性の独立人工.json'
    assert read(assembly)['全合格']
    result=dict(全合格=True,scope='全新1152台帳を独立現金/Decimal料金/親玉/全時価/予約上限/実新規lineageで監査。旧64は既監査会計へ委譲。activityは一場一読取。再生・raw・NPZ・APIなし。',
        検査件数=dict(COUNTS),独立結果=conclusions,
        両商品で活動と黒字と損小利大=[ident for ident,items in conclusions.items() if all(value['合計黒字と活動と損小利大'] for value in items.values())],
        両商品で金額利益8割=[ident for ident,items in conclusions.items() if all(value['金額利益8割'] for value in items.values())],
        全1152新台帳SHA256=hashes,
        資料SHA256={str(path.relative_to(ROOT)):sha(path) for path in (Path(__file__),final_path,WAVE/'金融事前固定.json',assembly)},
        事前固定sourceSHA256=fixed['source_SHA256'],全32既知=True,未知確認場数=0,
        正式金融再実行=0,counterfactual生成=0,生原本読取=0,NPZ読取=0,API取得=0,実注文=0,
        限界='同じ既知32場内の検証。厳密過去の価格代理時計は真の受信先後を証明しない。無取引と活動不足を成功に含めない。')
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査件数=dict(COUNTS),SHA256=sha(destination)),ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        index=1
        while (HERE/f'独立監査False_{index:05d}.json').exists():
            index+=1
        (HERE/f'独立監査False_{index:05d}.json').write_text(json.dumps(dict(全合格=False,例外=str(error),
            診断=traceback.format_exc(),完了検査件数=dict(COUNTS),sourceSHA256=sha(Path(__file__)),
            正式金融再実行=0,生原本読取=0,NPZ読取=0,API取得=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
