"""完成SHAの根指定後だけ、新七場会計と最大八つの所有入力・台帳を読んで損失を記述する。"""

import argparse
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[2]
VALUE={'TOPIX':1000.,'NK225':10.}
FEES={'TOPIX':(209,5),'NK225':(11,1)}
PLAN='完成後の新七場損失と勝ち対照を読む計画.json'


def clean(value: object) -> object:
    """
    機能: NumPy型を有限JSONへ変換し、未保存をnullで保持する。
    引数: value(object)は診断値。
    返り値: objectはJSON互換。未知を零や利益へ補完しない。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 未保存の診断資料だけを所有領域へ書く。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。金融成果や旧sourceを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def stamp(account: dict, row: int) -> dict:
    """
    機能: 保存normal行の元seq・価格時計・Last/BBOを明示する。
    引数: account(dict)、row(int)は同一入力と行。
    返り値: dictは観測点。価格時計を受信時刻と呼ばない。
    """
    r,q=account['record'],account['quotes'];time=float(r['time_s'][row])
    return dict(row=row,raw_seq=int(r['seq'][row]),price_time_s=time,
        価格時計=datetime.fromtimestamp(time,ZoneInfo('Asia/Tokyo')).isoformat(),
        last=float(r['price'][row]),bid=float(q['bid'][row]),ask=float(q['ask'][row]),quote_valid=bool(q['quote_valid'][row]))


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 実注文単位のfloor料を整数有理数から求める。
    引数: quantity(int)、symbol(str)は枚数と商品。
    返り値: intは片道手数料。
    """
    num,den=FEES[symbol];return quantity*num//den


def local_path(account: dict, ledger: dict, parent: dict) -> dict:
    """
    機能: 一親の実注文だけから清算可能損益と保有中最大順逆行を再構成する。
    引数: account/ledger/parent(dict)は同口座入力・実台帳・完結親。
    返り値: dictは部分実現/実料/残UID料込みの親局所経路。別出口利益は計算しない。
    """
    symbol=account['symbol'];orders=ledger['orders'];uids=ledger['order_uids']
    targets=ledger['exit_target_uids'];cid=int(parent['親']);indexes=np.flatnonzero(orders[:,2]==cid)
    assert len(indexes)>0
    first=int(parent['新規行']);last=int(parent['最終返済行']);cash=0.;paid=0;states={};cursor=0
    path=[];holding=[];used_quote=[];prior=-1;q=account['quotes']
    valid=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])
    earlier=np.flatnonzero(valid[:first+1]);assert len(earlier);prior=int(earlier[-1])
    for row in range(first,last+1):
        if valid[row]:prior=row
        while cursor<len(indexes) and int(orders[indexes[cursor],0])==row:
            index=int(indexes[cursor]);order=orders[index];d,quantity=int(order[3]),int(order[4])
            price=float(order[5]);cost=fee(quantity,symbol)
            assert ledger['order_fees'][index]==cost and valid[row] and price==q['ask' if d>0 else 'bid'][row]
            cash-=d*quantity*price*VALUE[symbol];paid+=cost
            if int(order[7]):
                uid=int(uids[index]);assert uid>=0 and uid not in states
                states[uid]=dict(side=d,remaining=quantity)
            else:
                assert int(uids[index])==-1;remaining=quantity;target=int(targets[index])
                for uid,state in states.items():
                    if target>=0 and target!=uid:continue
                    if state['side']!=-d or state['remaining']==0:continue
                    amount=min(remaining,state['remaining']);state['remaining']-=amount;remaining-=amount
                    if remaining==0:break
                assert remaining==0
            cursor+=1
        quantity=sum(s['remaining'] for s in states.values());reserve=sum(fee(s['remaining'],symbol) for s in states.values() if s['remaining'])
        mark=sum(s['side']*s['remaining']*float(q['bid' if s['side']>0 else 'ask'][prior])*VALUE[symbol] for s in states.values())
        path.append(cash+mark-paid-reserve);holding.append(quantity>0);used_quote.append(prior)
    path=np.asarray(path);holding=np.asarray(holding,bool)
    assert cursor==len(indexes) and sum(v['remaining'] for v in states.values())==0
    assert np.isclose(path[-1],parent['収支'],atol=1e-5,rtol=1e-12) and paid==parent['費用']
    selected=np.flatnonzero(holding);assert len(selected)>0
    peak=int(selected[np.argmax(path[selected])]);trough=int(selected[np.argmin(path[selected])])
    return dict(holding_peak=float(path[peak]),holding_trough=float(path[trough]),
        peak=stamp(account,first+peak),trough=stamp(account,first+trough),
        final_net=float(path[-1]),fees=paid,ever_positive_while_holding=bool(np.any(path[selected]>0)),
        peak_minus_final=float(path[peak]-path[-1]),definition='親局所清算可能損益。部分実現・全支払料・残UID別返済料込み。保有中極値は最終flat行を除く。救済可能利益ではない。')


def last_decomposition(account: dict, ledger: dict, cid: int) -> dict:
    """
    機能: 同じ実入退出行のLast変化と実BBO価格差・費用を符号付きで分解する。
    引数: account/ledger(dict)、cid(int)は口座と親。
    返り値: dictは記述恒等式。Lastで約定可能だった別戦略成績ではない。
    """
    result=[];m=VALUE[account['symbol']]
    for leg in ledger['actual_legs']:
        if int(leg['親'])!=cid:continue
        d,q=int(leg['方向']),int(leg['枚数']);a,b=int(leg['新規行']),int(leg['返済行'])
        before=float(account['record']['price'][a]);after=float(account['record']['price'][b])
        gross_last=d*(after-before)*q*m
        entry_adverse=d*(float(leg['新規価格'])-before)*q*m
        exit_adverse=d*(after-float(leg['返済価格']))*q*m
        assert np.isclose(gross_last-entry_adverse-exit_adverse,leg['粗損益'],atol=1e-5,rtol=1e-12)
        fees=float(leg['新規料金配分'])+float(leg['返済料金配分'])
        assert np.isclose(leg['粗損益']-fees,leg['収支'],atol=1e-5,rtol=1e-12)
        result.append(dict(gross_last=gross_last,entry_adverse=entry_adverse,exit_adverse=exit_adverse,
                           actual_gross=float(leg['粗損益']),fees=fees,net=float(leg['収支'])))
    assert result
    return dict(legs=result,totals={k:sum(v[k] for v in result) for k in result[0]},
        留保='同タイミングの記述。Lastの実約定可能性や新しい退出規則の損益ではない。')


def load_cache(meta: dict, kind: str, key: str, logs: list) -> dict:
    """
    機能: 指定所有cacheを一度読み、parse前に同bytes保全する。
    引数: meta(dict)、kind/key(str)、logs(list)は固定SHA・種類・口座・履歴。
    返り値: dictは保存入力又は台帳。元市場・stage原本は開かない。
    """
    path=(ROOT/meta['path']).resolve();assert path.is_relative_to(BASE) and path.suffix=='.gz'
    payload=path.read_bytes();assert len(payload)==meta['bytes'] and hashlib.sha256(payload).hexdigest()==meta['SHA256']
    copy=HERE/'owned'/kind/(key.replace('|','_')+'.pkl.gz');copy.parent.mkdir(parents=True,exist_ok=True)
    assert not copy.exists();copy.write_bytes(payload)
    logs.append(dict(meta,kind=kind,key=key,reads=1,owned_copy=copy.relative_to(ROOT).as_posix()))
    return pickle.loads(gzip.decompress(payload))


def execute(expected_sha: str) -> None:
    """
    機能: 根の完成SHA解除後だけ結果一読と最大八口座の必要cache診断を実施する。
    引数: expected_sha(str)は根が指定した完成結果SHA。
    返り値: None。金融再生・原市場追加読取・旧33台帳の読取は0。
    """
    assert len(expected_sha)==64 and not (HERE/'結果の同bytes保全.json').exists()
    path=BASE/'measurement/少額E01固定二設定の追加七場と全四十場.json'
    payload=path.read_bytes();assert hashlib.sha256(payload).hexdigest()==expected_sha
    copy=HERE/'結果の同bytes保全.json';copy.write_bytes(payload);result=json.loads(payload)
    assert result['全合格'] and result['raw_reads']==0 and result['new_actual_accounts']==14 and result['reused_accounting']==66
    own=[v for v in result['rows'] if v['origin']=='追加七場の新金融'];assert len(own)==14
    chosen=[]
    for symbol in VALUE:
        rows=[v for v in own if v['symbol']==symbol]
        chosen+=sorted((v for v in rows if v['net']<0),key=lambda v:(v['net'],v['session']))[:3]
        positive=sorted((v for v in rows if v['net']>0),key=lambda v:(-v['net'],v['session']))
        if positive:chosen.append(positive[0])
    assert len(chosen)<=8 and len({(v['session'],v['symbol']) for v in chosen})==len(chosen)
    selection=[dict(session=v['session'],symbol=v['symbol'],net=v['net'],cache=result['cache'][v['session']+'|'+v['symbol']]) for v in chosen]
    save(HERE/'完成SHAと詳細対象の事前固定.json',dict(全合格=True,result_SHA256=expected_sha,selection=selection,
        規則='商品ごと新7赤字上位3と黒字最大1。無黒字なら勝ち反証なし。最大8口座、入力/台帳各一読。',
        原市場追加読取=0,金融再生=0,旧33台帳読取=0))
    logs=[];details=[]
    for item in selection:
        scene,symbol=item['session'],item['symbol'];key=scene+'|'+symbol
        account=load_cache(item['cache']['input'],'input',key,logs)
        ledger=load_cache(item['cache']['ledger'],'ledger',key,logs)
        for parent in ledger['parent']:
            cid=int(parent['親']);order_indexes=np.flatnonzero((ledger['orders'][:,2]==cid)&(ledger['orders'][:,7]==1))
            assert len(order_indexes)>0;first=ledger['orders'][int(order_indexes[0])];publication=int(first[1])
            prior={}
            times=account['record']['time_s'];entry=int(parent['新規行']);side=int(parent['方向'])
            for seconds in (60,300):
                index=int(np.searchsorted(times,float(times[entry])-seconds,side='right')-1)
                prior[str(seconds)]=None if index<0 else dict(point=stamp(account,index),signed_last_change=side*(float(account['record']['price'][entry])-float(account['record']['price'][index])))
            gate=ledger['entry_diagnostics'].get(publication,{});vote=gate.get('vote')
            record=dict(session=scene,symbol=symbol,parent=parent,entry=stamp(account,entry),
                exit=stamp(account,int(parent['最終返済行'])),publication=stamp(account,publication),
                local=local_path(account,ledger,parent),last_bbo=last_decomposition(account,ledger,cid),
                previous_moves=prior,published_gate=gate,scene_control=ledger['control'],
                goal_anchor=ledger['goal_anchor'],exit_boundary=ledger['exit_boundary'],
                actual_legs=[v for v in ledger['actual_legs'] if int(v['親'])==cid],
                clock_qualification=result['input_clock_qualification'][key],
                資格効果='今回と不適格行を採用した反実仮想は比較しない。現在票と原seq上の資格関係だけ保存。')
            details.append(record)
    save(HERE/'新七場の損失と勝ち対照及び同時点価格費用の診断.json',dict(全合格=True,result_SHA256=expected_sha,
        new_rows=own,metrics=result['metrics'],selection=selection,details=details,read_log=logs,
        新金融=0,原市場追加読取=0,旧33台帳読取=0,
        留保=['事後の最大含み益を救済PL又は方向予測の成功へ足さない。',
              '旧33保存会計だけから、旧33に隠れた同じ損失尾があったとは確定しない。',
              '価格時計模型であり、板補充・主体・新規返済別数量を断定しない。',
              'Last分解は記述恒等式。Last約定又は別の新手法成績ではない。']))
    print('新七場の損失/勝ち対照の保存診断完了。原市場追加読取/新金融0。',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='根指定完成SHAの解除後だけ新七場の保存診断を行う')
    parser.add_argument('--root-result-sha',required=True)
    args=parser.parse_args();execute(args.root_result_sha)
