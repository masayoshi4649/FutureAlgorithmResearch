"""目標利益と損失予算による場内停止を、同一経路の最初の到達までだけ再生する。"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import pickle
import sys

import numpy as np

import common
import evaluation
import research


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX','NK225')
BASES = ('C_OWN_B4','C_N30_B4','U_P10_B4')
ACCOUNTING = common.module('106場内停止の不変会計',ROOT/'work/wave_v102/accounting.py')


def configs() -> list[dict]:
    """
    機能: 場中の小利益をその場の実収支にする36対照を定義する。
    引数: なし。
    返り値: list[dict]は目標3幅、損失予算3幅と無制限の直積。
    """
    result = []
    original = {value['id']:value for value in research.catalog.catalog()}
    for base in BASES:
        for goal in (.5,1.,2.):
            for loss in (.5,1.,2.,None):
                ident = base+'_DAY_P'+str(int(goal*10))+'_L'+('FREE' if loss is None else str(int(loss*10)))
                value = dict(deepcopy(original[base]), id=ident, base_id=base,
                    daily_profit_multiple=goal, daily_loss_multiple=loss,
                    name='場内利益目標と停止',
                    explanation='口座の清算時価が目標利益又は損失枠に達したら次の正常気配で全返済し、その場の新規を終了する。')
                result.append(value)
    assert len(result) == 36
    return result


def simulate(record: dict, ledger: dict, goal: float, loss: float | None) -> dict:
    """
    機能: 元の運転に場全体の利益目標・損失枠を追加する。
    引数: record(dict)は正常原行入力、ledger(dict)は基準運転、goal(float)/loss(float|None)は円額。
    返り値: dictは新注文・完了取引・全行時価と停止判断。当時の最初の到達以後の基準売買は使用しない。
    """
    n = ledger['row_count']
    assert n == len(record['seq']) and goal > 0 and (loss is None or loss > 0)
    old_curve = np.empty(n,np.float64)
    change_rows = ledger['equity_change_rows']
    next_rows = np.r_[change_rows[1:],n]
    for begin,end,value in zip(change_rows,next_rows,ledger['equity_change_values'],strict=True):
        old_curve[int(begin):int(end)] = value
    valid = (record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
             & (record['ask'] > record['bid']) & (record['bid'] > 0))
    hits = valid & ((old_curve >= goal) | ((old_curve <= -loss) if loss is not None else False))
    eligible = np.flatnonzero(hits)
    if not len(eligible):
        return dict(orders=ledger['orders'].copy(),trades=ledger['trades'].copy(),curve=old_curve,
            stopped=False,stop_reason='未到達',decision_row=None,fill_row=None,goal=goal,loss=loss)
    decision = int(eligible[0])
    orders = ledger['orders'][ledger['orders'][:,0] <= decision].copy()
    trades = ledger['trades'][ledger['trades'][:,3] <= decision].copy()
    entries = orders[orders[:,7] == 1]
    exits = orders[orders[:,7] == 0]
    open_parents = set(entries[:,2])-set(exits[:,2])
    assert len(open_parents) <= 1
    fill = decision
    if open_parents:
        future = np.flatnonzero(valid & (np.arange(n) > decision))
        assert len(future), '停止判断後の約定可能な観測がありません'
        fill = int(future[0])
        parent = open_parents.pop()
        entry = entries[entries[:,2] == parent][0]
        side,quantity = int(entry[4]),int(entry[5])
        price = float(record['bid'][fill] if side == 1 else record['ask'][fill])
        multiplier = 1000. if record['symbol'] == 'TOPIX' else 10.
        fee = float(entry[9])
        exit_order = entry.copy()
        exit_order[[0,1,4,6,7,8,10,11,14,16]] = [fill,decision,-side,price,0,90,
            float(record['time_s'][decision]),float(record['time_s'][fill]),90,orders[:,16].max()+1]
        assert exit_order[9] == fee and fill > decision
        orders = np.vstack((orders,exit_order))
        original = ledger['trades'][ledger['trades'][:,0] == parent][0].copy()
        gross = side*quantity*(price-entry[6])*multiplier
        original[[3,7,9,10,11,13]] = [fill,price,fee,gross,gross-2*fee,90]
        trades = np.vstack((trades,original))
    net = float(trades[:,11].sum())
    curve = old_curve.copy()
    curve[fill:] = net
    reason = '利益目標' if old_curve[decision] >= goal else '損失予算'
    return dict(orders=orders,trades=trades,curve=curve,stopped=True,stop_reason=reason,
        decision_row=decision,decision_seq=int(record['seq'][decision]),
        decision_time=float(record['time_s'][decision]),decision_equity=float(old_curve[decision]),
        fill_row=fill,fill_time=float(record['time_s'][fill]),goal=goal,loss=loss,
        note='基準と同じ運転を最初の当時閾値到達まで続け、保有時は次正常気配で全返済。以後は新規なし。')


def account(session: str, record: dict, result: dict, budget: float) -> dict:
    """
    機能: 停止後の全注文と時価を独立計算する。
    引数: session(str)、record/result(dict)、budget(float)は場名、入力、新出力と基準幅の円額。
    返り値: dictは手数料後の場会計。利益目標・損失枠は約定保証ではない。
    """
    orders,trades = result['orders'],result['trades']
    n = len(record['seq'])
    multiplier,fee_unit,cap = (1000.,41.8,10) if record['symbol']=='TOPIX' else (10.,11.,20)
    cash_changes,held_changes = np.zeros(n),np.zeros(n)
    valid = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask']) & (record['ask']>record['bid'])
    for order in orders:
        row,direction,quantity = int(order[0]),int(order[4]),int(order[5])
        assert order[9] == np.floor(quantity*fee_unit+1e-8)
        assert row > int(order[1]) and valid[row]
        assert order[6] == (record['ask'][row] if direction == 1 else record['bid'][row])
        cash_changes[row] += -direction*quantity*order[6]*multiplier-order[9]
        held_changes[row] += direction*quantity
    cash,held = np.cumsum(cash_changes),np.cumsum(held_changes)
    assert np.max(np.abs(held),initial=0) <= cap and held[-1] == 0
    latest = np.maximum.accumulate(np.where(valid,np.arange(n),-1))
    positive,negative = held > 0,held < 0
    assert np.all(latest[positive|negative] >= 0)
    curve = cash.copy()
    curve[positive] += held[positive]*record['bid'][latest[positive]]*multiplier
    curve[negative] += held[negative]*record['ask'][latest[negative]]*multiplier
    curve -= np.floor(np.abs(held)*fee_unit+1e-8)
    np.testing.assert_allclose(curve,result['curve'],atol=1e-4,rtol=0)
    totals = ACCOUNTING.trade_totals(trades)
    assert abs(totals['net']-cash[-1]) < 1e-4 and totals['fees']==orders[:,9].sum()
    return dict(session=session,symbol=record['symbol'],**totals,**ACCOUNTING.path_totals(curve),
        budget_unit=budget,goal=result['goal'],loss_limit=result['loss'],stopped=result['stopped'],
        stop_reason=result['stop_reason'],decision_time=result.get('decision_time'),
        独立全行会計検算=True, directions={name:ACCOUNTING.trade_totals(trades[trades[:,4]==side])
                                    for side,name in ((1,'買い'),(-1,'売り'))})


def freeze() -> None:
    """
    機能: 場中利益を確定する仮説と36条件を第二再生前に登録可能な形へ固定する。
    引数: なし。
    返り値: None。第一51条件の金融証跡を上書きしない。
    """
    first = common.read(HERE/'finance/results.json')
    plan = deepcopy(common.read(HERE/'試行計画.json'))
    plan.update(id='106_第二段階_場中利益と損失予算の36対照',name='場中の小利益を確定して新規を止める対照',
        purpose='新仮説',question='目標利益又は損失枠で場内全返済し休止すると、取った利益を再参加で失う赤字場を減らせるか。',
        change='同じ3入口のB4を最初の当時清算時価閾値まで運転。以後は次正常気配で全返済して新規を止める。',
        repeat_reason='第一51条件では入口選別は活動不足、厳格損失帯は回復利益を失った。場の利益保全と反復損失制限を別の執行部品として比較する。',
        compares_to=['106_往復帯と初期リスク及び再参加の全33対照'])
    plan['spec']['entry'] = dict(saved_first_phase=BASES,rule='元と同じ入口を維持する')
    plan['spec']['management'] = dict(candidates=[dict(id=c['id'],base=c['base_id'],profit=c['daily_profit_multiple'],
        loss='停止上限なし' if c['daily_loss_multiple'] is None else c['daily_loss_multiple']) for c in configs()],
        rule='当時の場内清算時価が利益目標以上又は損失枠以下なら全返済を判断しその場は新規しない',
        unit='始値の0.1%を呼値へ切り上げた幅×実数量×商品倍率',
        loss_observation='確定損益・含み損益・新規と返済の手数料を含む')
    plan['spec']['exit'] = dict(before_trigger='元B4の支持損切りと広い利益追尾',
        on_trigger='最初の当時閾値到達判断後の次正常気配で全返済。指値線での架空約定はしない')
    plan['spec']['implementation'] = dict(plan['spec']['implementation'],**{str(Path(__file__).relative_to(ROOT)):common.digest(Path(__file__))})
    plan['evidence'] += [dict(path='work/wave_v106/finance/results.json',sha256=common.digest(HERE/'finance/results.json'))]
    research.write(HERE/'第二段階の試行計画.json',plan)
    research.write(HERE/'第二段階の事前固定.json',dict(configs=configs(),sessions=first['sessions'],
        source=common.digest(Path(__file__)),first_result=common.digest(HERE/'finance/results.json'),
        timestamp=datetime.now(timezone.utc).isoformat(),金融再生=0,未知セッション=0))


def run() -> None:
    """
    機能: 全33場の同じ保存経路へ36場内停止条件を適用する。
    引数: なし。
    返り値: None。複数の閾値で将来価格を選び直さず、各条件の最初の到達で判断する。
    """
    fixed = common.read(HERE/'第二段階の事前固定.json')
    assert fixed['source']==common.digest(Path(__file__))
    trials = common.read(ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    assert any(item['id']=='106_第二段階_場中利益と損失予算の36対照' for item in trials)
    first = common.read(HERE/'finance/results.json')
    loader = research.load_module('106場内制御の固定入力',HERE/'input/data.py')
    cases = {c['id']:dict(rows=[],ledgers={}) for c in fixed['configs']}
    for session in fixed['sessions']:
        packet = loader.load_session(session)
        for symbol in SYMBOLS:
            record = packet['prepared'][symbol]['record']
            for base in BASES:
                path = ROOT/first['cases'][base]['ledgers'][session][symbol]['path']
                assert common.digest(path)==first['cases'][base]['ledgers'][session][symbol]['SHA256']
                with gzip.open(path,'rb') as stream:
                    ledger = pickle.load(stream)
                budget = next(r['budget_unit'] for r in first['cases'][base]['rows'] if r['session']==session and r['symbol']==symbol)
                for config in (c for c in fixed['configs'] if c['base_id']==base):
                    goal = budget*config['daily_profit_multiple']
                    loss = None if config['daily_loss_multiple'] is None else budget*config['daily_loss_multiple']
                    output = simulate(record,ledger,goal,loss)
                    row = account(session,record,output,budget)
                    cases[config['id']]['rows'].append(row)
                    stored = HERE/'finance/session_control'/config['id']/(session+'_'+symbol+'.pkl.gz')
                    stored.parent.mkdir(parents=True,exist_ok=True)
                    assert not stored.exists()
                    output['curve'] = dict(rows=np.flatnonzero(np.r_[True,np.diff(output['curve'])!=0]),
                        values=output['curve'][np.flatnonzero(np.r_[True,np.diff(output['curve'])!=0])],row_count=len(record['seq']))
                    with gzip.open(stored,'wb',compresslevel=2) as stream:
                        pickle.dump(output,stream,protocol=5)
                    cases[config['id']]['ledgers'][session+'|'+symbol] = dict(path=str(stored.relative_to(ROOT)),SHA256=common.digest(stored))
        print(session+'：利益目標・損失枠の36条件、当時判断・次正常気配・全行会計を確認',flush=True)
    result = dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],cases=cases,
        account_count=36*33*2,unknown_sessions=0,current_API_reads=0,actual_orders=0)
    research.write(HERE/'finance/session_control_results.json',result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='場中利益と損失予算の第二段階')
    parser.add_argument('action',choices=('freeze','run'))
    arguments=parser.parse_args()
    freeze() if arguments.action=='freeze' else run()
