"""当行予定数量と絶対利益停止を、独立した実注文接頭で人工検査する。"""

from pathlib import Path
import json
import sys

import numpy as np

import risk_sizing_engine_check as core
from risk_sizing_oracle import VALUE, LOSS, fee, CAP
from range_engine_check import digest

import interface
import catalog


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_risk_sizing'


def account(a: dict, unknown: bool=False) -> dict:
    """
    機能: 独立した人工をinterface用の保存形式へ接続する。
    引数: a(dict)は人工、unknown(bool)は当時方向票の未知例。
    返り値: dictは人工口座。原紙上計算又は正式cacheを読まない。
    """
    bases={}
    for order in a['feed']:
        if order[7]:
            bases[int(order[0])]=dict(known=not unknown,reason=16 if unknown else 0,
                direction_votes=None if unknown else 2,balance=None if unknown else 1.)
    return dict(symbol=a['symbol'],record=dict(time_s=a['times'],price=a['prices'],tick=a['tick'],limit=a['end']),
        quotes=dict(time_s=a['times'],seq=np.arange(len(a['times']),dtype=np.int64),bid=a['bid'],ask=a['ask'],quote_valid=a['qok']),
        feed=a['feed'],quiet=a['quiet'],quiet_force=a['quiet_force'],trade_features={'60':bases},paper_SHA256='人工')


def expected_stop(a: dict, orders: np.ndarray, uids: np.ndarray, goal: float) -> dict:
    """
    機能: 実注文接頭だけから停止判断と次正常気配のUID返済を独立求める。
    引数: a(dict)、orders/uids(ndarray)、goal(float)は人工気配・実注文・絶対円目標。
    返り値: dictは期待prefix・実料金・停止種別。実装dailyと将来親収支を使わない。
    """
    symbol=a['symbol']; cash=0.; paid=0; held={}; cursor=0; decision=-1; kind=''; liquidation=0.
    for row in range(len(a['times'])):
        while cursor<len(orders) and int(orders[cursor,0])==row:
            o=orders[cursor]; side,q,new=map(int,(o[3],o[4],o[7])); cash-=side*q*o[5]; paid+=fee(q,symbol)
            if new:
                held[int(uids[cursor])]=dict(cid=int(o[2]),side=side,quantity=q)
            else:
                need=q
                for state in held.values():
                    if state['cid']==o[2] and state['side']==-side:
                        amount=min(need,state['quantity']); need-=amount; state['quantity']-=amount
                assert need==0
            cursor+=1
        good=bool(a['qok'][row] and 0<a['bid'][row]<a['ask'][row])
        if not good: continue
        marked=cash
        for state in held.values(): marked+=state['side']*state['quantity']*(a['bid'][row] if state['side']==1 else a['ask'][row])
        liquidation=marked*VALUE[symbol]-paid-sum(fee(s['quantity'],symbol) for s in held.values() if s['quantity'])
        if liquidation>=goal or liquidation<=-LOSS[symbol]:
            decision=row; kind='利益目標' if liquidation>=goal else '損失予算'; break
    if decision<0:
        return dict(発動=False,orders=orders.copy(),uids=uids.copy(),targets=np.full(len(uids),-1,np.int64))
    output=orders[:cursor].tolist(); output_uids=uids[:cursor].tolist(); targets=[-1]*cursor
    remaining=[(uid,s) for uid,s in held.items() if s['quantity']]
    fill=decision
    if remaining:
        candidates=[r for r in range(decision+1,len(a['times'])) if a['qok'][r] and 0<a['bid'][r]<a['ask'][r]]
        assert candidates; fill=candidates[0]
        for uid,state in remaining:
            side=-state['side']; price=a['ask'][fill] if side==1 else a['bid'][fill]
            output.append([fill,decision,state['cid'],side,state['quantity'],price,94 if kind=='利益目標' else 95,0])
            output_uids.append(-1); targets.append(uid)
    return dict(発動=True,判断行=decision,返済行=fill,種別=kind,判断時清算=liquidation,
        orders=np.asarray(output,float),uids=np.asarray(output_uids,np.int64),targets=np.asarray(targets,np.int64))


def check(a: dict, config: dict, unknown: bool=False) -> tuple:
    """
    機能: interface数量とP1/P2停止を独立接頭期待値へ照合する。
    引数: a/config(dict)、unknown(bool)は人工と固定条件・票未知の有無。
    返り値: tuple[dict,dict]は実出力と期待停止。金融成績を測定しない。
    """
    acc=account(a,unknown); values=interface.execute(acc,config,python=True)
    result=interface.account_output('人工',acc,config,values)
    expected=expected_stop(a,values[0],values[5],config['profit_goal_yen'][a['symbol']])
    np.testing.assert_array_equal(result['orders'],expected['orders'])
    np.testing.assert_array_equal(result['order_uids'],expected['uids'])
    np.testing.assert_array_equal(result['exit_target_uids'],expected['targets'])
    assert result['control']['発動']==expected['発動']
    if expected['発動']:
        assert result['control']['判断行']==expected['判断行'] and result['control']['返済行']==expected['返済行'] and result['control']['種別']==expected['種別']
    totals=result['actual_leg_totals']; legs=result['actual_legs']
    gain=sum(max(0.,p['収支']) for p in legs); loss=sum(max(0.,-p['収支']) for p in legs)
    assert totals['profit']==gain and totals['loss']==loss and totals['net']==gain-loss
    assert totals['profit_share']==(gain/(gain+loss) if gain+loss else None)
    assert totals['actual_legs']==len(legs) and totals['winning_legs']==sum(p['収支']>0 for p in legs) and totals['losing_legs']==sum(p['収支']<0 for p in legs)
    fees=sum(fee(int(o[4]),a['symbol']) for o in expected['orders'])
    assert result['summary']['費用']==fees
    assert result['long_qty'][-1]==result['short_qty'][-1]==0
    assert '共有GU全feedの診断' in result['source_scope'] and '主評価の完結親とは別' in totals['定義']
    return result,expected


def main() -> None:
    """
    機能: 両母と両目標の当時停止、未知門、ゼロ量及び過損失反例を人工で固定する。
    引数: なし。source完成通知後の人工だけで、大型入力は使わない。
    返り値: Noneは別証跡。平均黒字補填又は安定性達成を意味しない。
    """
    target=HERE/'risk_sizing_P1P2停止と母採否及び次気配超過の独立人工.json'; assert not target.exists()
    scope=[SOURCE/n for n in ('engine.py','order_kernel.py','catalog.py','interface.py','daily.py','policy.py')]
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in scope}; rows=[]; cases=0
    for config in catalog.configs():
        for symbol in CAP:
            for side in (1,-1):
                a=core.fixture(symbol,side)
                result,expected=check(a,config); cases+=1
                assert not expected['発動']
                # ----------------------------------------
                # 当行少額順行P1、次行追加順行P2。影の返済予約があっても全残を一度だけ閉じる。
                rise=core.clone(a)
                first=1.5 if symbol=='TOPIX' else 50.; second=2.5 if symbol=='TOPIX' else 80.
                move=np.zeros(len(a['times'])); move[3]=side*first; move[4:]=side*second
                rise['bid']+=move; rise['ask']+=move; rise['prices']+=move
                positive,stop=check(rise,config); cases+=1
                assert stop['発動'] and stop['種別']=='利益目標'
                assert stop['判断行']==(3 if config['profit_ticks']==1 else 4)
                rows.append(dict(id=config['id'],商品=symbol,方向=side,種類='段階的利益停止',判断=stop['判断行'],返済=stop['返済行'],収支=positive['summary']['収支']))
                # 損失判断時は既予約の半返済があり、次正常気配までさらに悪化する。
                fall=core.clone(a); fall['qok'][4:6]=False
                loss1=2.5 if symbol=='TOPIX' else 110.; loss2=3.5 if symbol=='TOPIX' else 160.
                decline=np.zeros(len(a['times'])); decline[3]=side*(-loss1); decline[4:]=side*(-loss2)
                fall['bid']+=decline; fall['ask']+=decline; fall['prices']+=decline
                negative,stop=check(fall,config); cases+=1
                assert stop['判断行']==3 and stop['返済行']==6 and stop['種別']=='損失予算'
                assert negative['summary']['収支'] < -LOSS[symbol]
                rows.append(dict(id=config['id'],商品=symbol,方向=side,種類='次正常気配までの損失枠超過',判断=3,返済=6,損失枠=LOSS[symbol],実収支=negative['summary']['収支']))
                # 票未知をVETOは元通り許可しCONFIRMは拒否する。q可用性と実採用を混同しない。
                unknown,_=check(a,config,unknown=True); cases+=1
                assert (len(unknown['orders'])>0)==(config['mode']=='VETO')
                # 全公開q0でも元影を最後まで進め、勝ち又は金額比100%に補完しない。
                noquantity=core.clone(a); noquantity['feed'][noquantity['feed'][:,7]==1,9]=10000.
                empty,_=check(noquantity,config); cases+=1
                assert len(empty['orders'])==0 and empty['summary']['費用']==0 and empty['summary']['利益割合'] is None
                assert empty['actual_leg_totals']['profit_share'] is None
    assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in scope}
    proof=dict(全合格=True,source_SHA256=sources,独立source_SHA256=digest(Path(__file__)),人工条件数=cases,観測=rows,
        範囲='interface母採否・P1/P2とL2・実注文接頭・元UID・玉別金額参考を人工で確認。GU suffixを実政策に合算しない。',
        反証='当行清算が損失枠を通過してから次正常気配で返済するため、L2は最大赤字の保証ではない。',
        原入力=0,原板=0,NPZ=0,API=0,金融=0,旧source及び旧JIT変更=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,条件数=cases,SHA256=digest(target)),ensure_ascii=False))


if __name__=='__main__': main()
