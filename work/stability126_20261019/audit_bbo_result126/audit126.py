"""次正常原行BBOの完成会計を、実注文から独立に復元する。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
TASK=HERE.parent
BBO=TASK/'engine/bbo_next'
READS=[]
SEEN=set()


def read_json(path: Path) -> dict:
    """
    機能: 固定計画又は完成会計の小JSONを読む。
    引数: path(Path)は対象位置。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def read_once(item: dict, kind: str) -> bytes:
    """
    機能: 保存派生素材を一回読み、同bytesのSHAを独立照合する。
    引数: item(dict)はpath/sha256、kind(str)は監査入力区分。
    返り値: bytesは照合済み保存内容。原本へのアクセスは拒否する。
    """
    path=(ROOT/item['path']).resolve();name=path.relative_to(ROOT).as_posix()
    assert name.startswith('work/') and name not in SEEN,name
    raw=path.read_bytes();actual=hashlib.sha256(raw).hexdigest()
    log=dict(path=name,kind=kind,bytes=len(raw),sha256=actual,expected_sha256=item['sha256'],matches=actual==item['sha256'])
    READS.append(log);SEEN.add(name)
    with (HERE/'保存入力の独立一読履歴.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(log,ensure_ascii=False)+'\n')
    assert actual==item['sha256'],name
    return raw


def equal(actual: object, expected: object, name: str) -> None:
    """
    機能: 独立復元値と被監査値を厳しく比較する。
    引数: actual/expected(object)は配列又は値、name(str)は検査項目。
    返り値: None。
    """
    np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-7,err_msg=name)


def audit_account(ready: dict, quotes: dict, market: np.ndarray, paper: dict,
                  result: dict, config: dict) -> dict:
    """
    機能: 実注文だけからFIFO・現金・在庫・全行気配清算・全統計と親組を再構築する。
    引数: ready/quotes/paper/result/config(dict)、market(ndarray)は保存入力と被監査完成値。
    返り値: dictは独立計算した場会計。実売買と影を再運転しない。
    """
    n=len(ready['seq']);symbol=ready['symbol'];quantity=5 if symbol=='TOPIX' else 10
    cap=quantity*2;multiplier=1000. if symbol=='TOPIX' else 10.
    orders,trades,cycles,curve,stats=(np.asarray(result[k]) for k in ('orders','trades','cycles','curve','stats'))
    uids=np.asarray(result['order_uids']);events=np.asarray(result['execution_events']);states=np.asarray(result['execution_states'])
    assert orders.shape[1]==8 and trades.shape[1]==11 and cycles.shape[1]==10 and curve.shape==(n,8) and states.shape==(n,14)
    assert len(uids)==len(orders) and all(np.isfinite(v).all() for v in result.values())
    np.testing.assert_array_equal(ready['seq'],quotes['seq']);np.testing.assert_array_equal(ready['time_s'],quotes['time_s'])
    bid,ask=np.asarray(quotes['bid']),np.asarray(quotes['ask'])
    good=np.asarray(quotes['quote_valid'],bool)&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
    markrow=np.maximum.accumulate(np.where(good,np.arange(n),-1))
    valid_rows=np.flatnonzero(good)
    cash_change=np.zeros(n);long_change=np.zeros(n);short_change=np.zeros(n);realized_change=np.zeros(n)
    lots=[];uid_seen=set();expected_trades=[];parents={};parent_orders={}
    original_orders=np.asarray(paper['orders']);original_cycles=np.asarray(paper['cycles'])
    paper_atr={int(c[0]):float(c[5]) for c in original_cycles}
    assert len(paper_atr)==len(original_cycles) and not np.any(original_orders[:,6]==32.)
    assert not len(orders) or np.all(np.diff(orders[:,0])>=0)
    for index,order in enumerate(orders):
        row,source,cid,side,qty=map(int,order[:5]);price=float(order[5]);new=int(order[7]);reason=int(order[6])
        assert 0<=source<row<n and good[row] and side in (-1,1) and qty>0 and new in (0,1)
        assert np.array_equal(order[:5],np.array([row,source,cid,side,qty]))
        assert price==(ask[row] if side>0 else bid[row])
        cash_change[row]-=side*qty*price
        parent_orders.setdefault(cid,[]).append(index)
        if new:
            assert qty==quantity and cid not in parents
            publication=original_orders[(original_orders[:,0]==source)&(original_orders[:,2]==cid)&(original_orders[:,7]==1)]
            assert len(publication)==1 and publication[0,3]==side and publication[0,4]==qty
            assert valid_rows[np.searchsorted(valid_rows,source,side='right')]==row
            uid=int(uids[index]);assert uid>=0 and uid not in uid_seen;uid_seen.add(uid)
            lots.append(dict(uid=uid,cid=cid,side=side,qty=qty,price=price,row=row))
            parents[cid]=dict(entry_row=row,exit_row=-1,qty=qty,side=side,price=price,atr=paper_atr[cid],risk=qty*paper_atr[cid],pnl=0.,reason=-1)
            (long_change if side>0 else short_change)[row]+=qty
        else:
            assert uids[index]==-1 and cid in parents
            if reason not in (32,70,73,93):
                publication=original_orders[(original_orders[:,0]==source)&(original_orders[:,2]==cid)&(original_orders[:,7]==0)&(original_orders[:,6]==reason)]
                assert len(publication)>0 and publication[:,4].sum()>=qty
            left=qty
            for lot in lots:
                if left==0:break
                if lot['qty']==0 or lot['cid']!=cid or lot['side']!=-side:continue
                take=min(left,lot['qty']);gain=lot['side']*take*(price-lot['price'])
                expected_trades.append([cid,lot['uid'],lot['side'],take,lot['price'],price,lot['row'],row,0,reason,gain])
                realized_change[row]+=gain;parents[cid]['pnl']+=gain
                lot['qty']-=take;left-=take
            assert left==0
            parents[cid]['exit_row']=row;parents[cid]['reason']=reason
            (long_change if side<0 else short_change)[row]-=qty
    equal(trades,np.array(expected_trades,float).reshape((-1,11)),'注文からの独立FIFO')
    cash=np.cumsum(cash_change);longqty=np.cumsum(long_change);shortqty=np.cumsum(short_change)
    realized=np.cumsum(realized_change)
    assert np.all((longqty>=0)&(longqty<=cap)&(shortqty>=0)&(shortqty<=cap))
    assert not np.any((longqty>0)&(shortqty>0))
    held=(longqty+shortqty)>0;assert np.all(markrow[held]>=0)
    liquidation=np.zeros(n);long_rows=longqty>0;short_rows=shortqty>0
    liquidation[long_rows]=longqty[long_rows]*bid[markrow[long_rows]]
    liquidation[short_rows]=-shortqty[short_rows]*ask[markrow[short_rows]]
    equity=cash+liquidation;peak=np.maximum.accumulate(np.maximum(equity,0.));drawdown=np.maximum.accumulate(peak-equity)
    expected_curve=np.column_stack([equity,realized,longqty,shortqty,drawdown,cash,longqty-shortqty])
    equal(curve[:,:7],expected_curve,'全行の現金・在庫・最新有効BBO清算')
    equal(states[:,3],longqty,'状態の買枚数');equal(states[:,4],shortqty,'状態の売枚数')
    equal(states[:,9],markrow,'無効気配行のmark carry元行');equal(curve[:,7],states[:,2],'実親ID曲線')
    expected_stats=[realized[-1],drawdown.max(initial=0),longqty.max(initial=0),shortqty.max(initial=0),
                    (longqty+shortqty).max(initial=0),np.abs(longqty-shortqty).max(initial=0),0.,
                    min(0.,equity.min(initial=0)),max(0.,equity.max(initial=0)),longqty[-1]+shortqty[-1],0.]
    equal(stats,expected_stats,'全十一統計')
    assert not longqty[-1] and not shortqty[-1] and all(lot['qty']==0 for lot in lots),'未返済を完成結果にしない'
    expected_cycles=[]
    for cid,parent in sorted(parents.items()):
        assert parent['exit_row']>=parent['entry_row']
        expected_cycles.append([cid,parent['entry_row'],parent['exit_row'],parent['pnl'],parent['risk'],
                                parent['atr'],parent['qty'],parent['qty'],parent['side'],parent['reason']])
    equal(cycles,np.array(expected_cycles,float).reshape((-1,10)),'原通知固定ATRと実約定親組')
    equal(cycles[:,3].sum(),trades[:,10].sum(),'親と脚の合計');equal(realized[-1],cash[-1],'全返済の現金')
    # ----------------------------------------
    # 予約時の実組評価と場終了閾値を、保存市場と独立会計へ照合する。
    for event in events[events[:,1]==9.]:
        row,cid=int(event[0]),int(event[2]);parent=parents[cid]
        subset=orders[np.array(parent_orders[cid])];applied=subset[subset[:,0]<=row]
        amount=float((applied[:,3]*applied[:,4]).sum());qty=abs(amount)
        done=trades[(trades[:,0]==cid)&(trades[:,7]<=row),10].sum()
        mark=bid[row] if parent['side']>0 else ask[row]
        campaign=done+parent['side']*qty*(mark-parent['price'])
        equal(event[5],campaign,'予約時の実組清算');equal(event[6],parent['risk'],'予約の固定初回risk')
        assert good[row] and event[3]==row
        if event[13]==32.:
            assert campaign<=-parent['risk']+1e-7
            equal(event[7],-parent['risk'],'未設定利益床を予算境界に混ぜない')
        else:
            assert event[13]==70. and config['protect_start_atr']>0 and campaign<=event[7]+1e-7
    stops=events[events[:,1]==10.]
    if config['session_loss_r']>0 and parents:
        initial=min(parents.values(),key=lambda p:p['entry_row']);risk=initial['risk']
        eligible=np.flatnonzero(good&(np.arange(n)>=initial['entry_row'])&(equity<=-config['session_loss_r']*risk+1e-8))
        assert len(stops)==int(len(eligible)>0)
        if len(stops):
            assert stops[0,0]==eligible[0];equal(stops[0,5],equity[eligible[0]],'場停止の清算損益')
            equal(stops[0,6],risk,'場停止の最初の実risk')
    else:assert len(stops)==0
    loss_events=events[events[:,1]==11.]
    assert len(loss_events)==(sum(p['pnl']<0 for p in parents.values()) if config['rearm_progress_atr']>0 else 0)
    for e in loss_events:
        p=parents[int(e[2])];assert p['pnl']<0 and e[0]==p['exit_row'];equal(e[5],p['pnl'],'損失後停止は実親PL')
    # ----------------------------------------
    gains=trades[:,10]*multiplier;parent_net=cycles[:,3]*multiplier
    entry=orders[:,7]==1;wins=gains>0;losses=gains<0
    return dict(profit=float(gains[wins].sum()),loss=float(-gains[losses].sum()),net=float(gains.sum()),fees=0,
        entry_orders=int(entry.sum()),entry_quantity=int(orders[entry,4].sum()),closed_quantity=int(trades[:,3].sum()),
        winning_quantity=int(trades[wins,3].sum()),losing_quantity=int(trades[losses,3].sum()),flat_lots=int(trades[gains==0,3].sum()),
        groups=len(cycles),parent_profit=float(parent_net[parent_net>0].sum()),parent_loss=float(-parent_net[parent_net<0].sum()),
        parent_wins=int((parent_net>0).sum()),parent_losses=int((parent_net<0).sum()),unclosed=0,
        max_long=float(stats[2]),max_short=float(stats[3]),
        long_net=float(gains[trades[:,2]==1].sum()),short_net=float(gains[trades[:,2]==-1].sum()),
        order_count=len(orders),trade_count=len(trades),curve_rows=n,policy_events=len(events))


def load_papers(fixed: dict, baseline: dict) -> dict:
    """
    機能: 元Last通知23個の保存cacheを各一監査読取して初期ATRを拘束する。
    引数: fixed/baseline(dict)は別登録BBOの固定と旧30保存会計。
    返り値: dict[tuple,dict]は82紙上口座の注文・初期ATR保存値。
    """
    papers={};items=fixed['paper_caches']
    with np.load(BytesIO(read_once(items[0],'旧30原版通知cache')),allow_pickle=False) as arrays:
        for row in baseline['rows']:
            key=row['session'],row['symbol'];prefix=row['symbol']+'_'+row['session']
            papers[key]={name:arrays[prefix+'__'+name] for name in ('orders','cycles')}
    for item in items[1:]:
        key=item['session'],item['symbol'];assert key not in papers
        with np.load(BytesIO(read_once(item,'新11原版通知cache')),allow_pickle=False) as arrays:
            papers[key]={name:arrays['E01__'+name] for name in ('orders','cycles')}
    assert len(papers)==82 and len(items)==23
    return papers


def execute() -> None:
    """
    機能: 完成BBO1312口座を保存注文から独立監査し、累計まで確認する。
    引数: なし。
    返り値: None。金融再生・原市場・現在APIを使わない。
    """
    assert not (HERE/'独立監査開始.json').exists()
    completed_path=BBO/'全十六条件の次原行BBO会計.json';raw=completed_path.read_bytes();completed=json.loads(raw)
    assert completed['passed'] and len(completed['rows'])==1312
    fixed=read_json(BBO/'固定計画.json');baseline=read_json(ROOT/fixed['baseline']['path'])
    manifest=read_json(ROOT/fixed['input']['path'])
    save=lambda path,value:path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save(HERE/'独立監査開始.json',dict(start=time.time(),result_sha256=hashlib.sha256(raw).hexdigest(),
        original_market_reads=0,financial_replays=0,expected_packet_reads=41,expected_result_cache_reads=82,expected_paper_cache_reads=23))
    papers=load_papers(fixed,baseline)
    result_refs={(v['session'],v['symbol']):v for v in completed['cache']}
    rows={(v['method'],v['session'],v['symbol']):v for v in completed['rows']};assert len(rows)==1312
    independent=[]
    for item in manifest['packets']:
        packet=pickle.loads(read_once(item,'元入力と参考気配packet'));scene=packet['session']
        assert scene==item['session']
        for symbol in ('TOPIX','NK225'):
            key=scene,symbol;reference=result_refs[key]
            with np.load(BytesIO(read_once(reference,'BBO新金融会計cache')),allow_pickle=False) as arrays:
                for config in completed['specs']:
                    method=config['id']
                    result={name:arrays[method+'__'+name] for name in ('orders','trades','cycles','curve','stats','order_uids','execution_events','execution_states')}
                    row=audit_account(packet['inputs'][key],packet['quotes'][key],packet['markets'][key],papers[key],result,config)
                    stored=rows[method,scene,symbol]
                    for name,value in row.items():
                        if name in stored:equal(stored[name],value,method+'/'+scene+'/'+symbol+'/'+name)
                    independent.append(dict(method=method,session=scene,symbol=symbol,**row))
            print(scene+' '+symbol+' 十六会計の注文FIFOと全行BBO清算を独立確認',flush=True)
    assert len(independent)==1312 and len(READS)==146 and len(SEEN)==146
    totals=[]
    for method in [v['id'] for v in completed['specs']]:
        for symbol in ('TOPIX','NK225'):
            part=[v for v in independent if v['method']==method and v['symbol']==symbol]
            stored=[v for v in completed['rows'] if v['method']==method and v['symbol']==symbol]
            total={name:float(sum(v[name] for v in part)) for name in ('profit','loss','net','entry_orders','entry_quantity','closed_quantity','long_net','short_net')}
            for name,value in total.items():equal(sum(v[name] for v in stored),value,'全場累計/'+method+'/'+symbol+'/'+name)
            totals.append(dict(method=method,symbol=symbol,**total,green=sum(v['net']>0 for v in part),red=sum(v['net']<0 for v in part),no_trade=sum(v['entry_orders']==0 for v in part)))
    proof=dict(passed=True,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        result=dict(path=completed_path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(raw).hexdigest()),
        accounts=independent,totals=totals,read_log=READS,packet_reads=41,result_cache_reads=82,paper_cache_reads=23,
        financial_accounts_checked=1312,original_market_reads=0,financial_replays=0,API=0,real_orders=0,
        scope='注文からFIFO玉・原通知ATR・全行cash/BBO時価・11統計・親組・場集計・累計を別実装で復元。原版Last又はBBOの再金融なし。')
    save(HERE/'全千三百十二BBO会計と全行清算の独立監査.json',proof)
    print('全1312BBO会計の独立監査完了、金融0・原本0',flush=True)


if __name__=='__main__':
    try:execute()
    except Exception as error:
        path=HERE/('独立監査停止_'+str(time.time_ns())+'.json')
        path.write_text(json.dumps(dict(passed=False,error=repr(error),read_log=READS,original_market_reads=0,
            financial_replays=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
