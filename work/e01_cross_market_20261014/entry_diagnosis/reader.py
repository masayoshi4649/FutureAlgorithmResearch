"""実注文に対応する公開票だけを射影し、保存曲線の事後逆行を分母付きで診断する。"""

import argparse
from collections import Counter
from datetime import datetime,timezone,timedelta
import gzip
import hashlib
import pickle
import traceback
import numpy as np

import common


def expand(value: object, count: int) -> np.ndarray:
    """
    機能: 保存normal曲線を同値plateauから復元し、未来補完を行わない。
    引数: value(object)、count(int) は保存配列又は三項目plateauとnormal長。
    返り値: ndarray は保存値の全normal列。型・先頭・長さの不正を拒否する。
    """
    if isinstance(value,dict):
        assert set(value)=={'rows','values','length'} and value['length']==count
        rows,points=value['rows'],value['values']
        assert rows.ndim==1 and np.issubdtype(rows.dtype,np.integer) and len(rows)>0 and rows[0]==0
        assert np.all(rows[1:]>rows[:-1]) and rows[-1]<count and len(points)==len(rows)
        result=points[np.searchsorted(rows,np.arange(count),side='right')-1]
    else:result=value
    assert isinstance(result,np.ndarray) and len(result)==count
    return result


def project(ledger: dict, item: dict) -> list[dict]:
    """
    機能: 完結実親の公開票・受理q・実fill・実利益と保有中の事後清算逆行を射影する。
    引数: ledger/item(dict) は一読した新実台帳と固定対象。
    返り値: list[dict] は実親ごとの小資料。場停止後GU親は対象へ含めない。
    """
    symbol=item['symbol'];assert ledger['key']==(item['session'],symbol) and ledger['case']['id']==item['case_id']
    orders=ledger['orders'];fees=ledger['order_fees'];parents=ledger['parent']
    assert len(parents)==item['small_row']['親数'] and ledger['summary']==item['small_row']
    count=ledger['equity_yen']['length'] if isinstance(ledger['equity_yen'],dict) else len(ledger['equity_yen'])
    eq=expand(ledger['equity_yen'],count);liquid=expand(ledger['liquidation_yen'],count)
    long=expand(ledger['long_qty'],count);short=expand(ledger['short_qty'],count)
    events=ledger['sizing_events'];gate=ledger['entry_diagnostics'];rows=[]
    for parent in parents:
        cid=int(parent['親']);own_orders=orders[orders[:,2]==cid];new=own_orders[own_orders[:,7]==1]
        assert len(new)==1,'一親の実新規は一件という今回の契約'
        first=new[0];fill=int(first[0]);publication=int(first[1]);quantity=int(first[4]);side=int(first[3]);last=int(parent['最終返済行'])
        assert publication<fill<=last<count and side==parent['方向'] and quantity==parent['枚数']
        value=gate[publication];assert value['paper_parent']==cid and value['side']==side and value['accepted']
        vote=value['vote'];assert vote['known'] and vote['direction_votes']>=2 and vote['balance']>=value['threshold']
        selected=events[(events[:,0]==publication)&(events[:,1]==cid)]
        assert len(selected)==1;event=selected[0]
        assert event[14]==event[15]==1 and int(event[4])==quantity
        previous=[p for p in parents if p['親']!=cid and p['新規行']<fill and p['最終返済行']<=fill]
        prior=sum(p['収支'] for p in previous)
        # 別親が同じ保有区間に入っていないことを確認して場曲線から前親netだけ引く。
        assert not any(p['親']!=cid and p['新規行']<=last and p['最終返済行']>fill for p in parents)
        local_liquid=liquid[fill:last+1]-prior;local_equity=eq[fill:last+1]-prior
        own_fee=np.zeros(count)
        for order,cost in zip(orders,fees):
            if int(order[2])==cid:own_fee[int(order[0])]+=int(cost)
        paid=np.cumsum(own_fee);gross=local_equity+paid[fill:last+1]
        assert np.isclose(local_liquid[-1],parent['収支'],atol=1e-5,rtol=1e-12)
        assert np.isclose(gross[-1],parent['粗損益'],atol=1e-5,rtol=1e-12)
        minimum=int(np.argmin(local_liquid))+fill;gross_minimum=int(np.argmin(gross))+fill
        held=(long[fill:last+1]+short[fill:last+1])>0
        stamp=float(vote['candidate_price_time_s']);assert np.isfinite(stamp)
        goal=ledger['goal_anchor'];boundary=ledger['exit_boundary']
        rows.append(dict(case_id=item['case_id'],session=item['session'],symbol=symbol,paper_parent=cid,side=side,
            actual_net_yen=float(parent['収支']),gross_yen=float(parent['粗損益']),actual_fees_yen=int(parent['費用']),
            publication=dict(normal_row=publication,raw_seq=int(vote['candidate_raw_seq']),price_time_s=stamp,
                価格代理時計JST=datetime.fromtimestamp(stamp,timezone(timedelta(hours=9))).isoformat(),
                known=bool(vote['known']),unknown_reason=int(vote['reason']),direction_votes=int(vote['direction_votes']),
                up_votes=vote['up_votes'],down_votes=vote['down_votes'],balance=float(vote['balance']),threshold=float(value['threshold']),
                published_ATR=float(event[5]),published_spread=float(event[6]),selected_quantity=int(event[4]),
                bid=None,ask=None,気配根拠='公開両BBO列は台帳未保存。spreadを両値へ変換しない。'),
            session_first_accept=dict(quantity=goal['数量'],normal_row=goal['受理行'],paper_parent=goal['紙上親'],
                raw_seq=goal['受理原seq'],price_time_s=goal['受理価格時計']),
            actual_fill=dict(normal_row=fill,quantity=quantity,price=float(first[5]),quote_side='ask' if side>0 else 'bid',
                raw_seq=None,price_time_s=None,bid=None,ask=None,保存範囲='fill行と約定片側価格だけ。実fill時計/原seq/両BBO列は未保存。'),
            close=dict(normal_row=last,orders=[dict(normal_row=int(o[0]),decision_row=int(o[1]),quantity=int(o[4]),price=float(o[5]),reason=int(o[6]))
                for o in own_orders if o[7]==0]),
            risk=dict(target_yen=boundary['target_yen'],hard_loss_yen=boundary['hard_loss_yen'],
                quantity_selection_budget_yen=boundary['quantity_selection_budget_yen'],
                worst_fee_liquidation_yen=float(local_liquid.min()),worst_fee_liquidation_row=minimum,
                fee_liquidation_MAE_yen=max(0.,-float(local_liquid.min())),
                gross_mark_MAE_yen=max(0.,-float(gross.min())),gross_mark_MAE_row=gross_minimum,
                maximum_fee_liquidation_yen=float(local_liquid.max()),
                negative_fee_liquidation_rows=int(np.count_nonzero(local_liquid<0)),observed_normal_rows=len(local_liquid),
                held_rows=int(np.count_nonzero(held)),prior_completed_parent_net_yen=float(prior),
                定義='実fillから最後返済までの場清算から前親確定netを引いた親局所曲線。粗時価は親の当時累積支払料を戻す。事後極値で新出口を最適化しない。')))
    return rows


def run() -> None:
    """
    機能: 根が固定対象をレビューした後だけ、十六新台帳を各一読して診断する。
    引数: なし。
    返り値: None。読取数とsource一致を記録し、不具合ではFalseを保持して停止する。
    """
    plan,plan_sha=common.read_json(common.HERE/'読取計画.json');assert plan['source_SHA256']==common.sources()
    assert not any((common.HERE/n).exists() for n in ('読取開始.json','読取False.json','実公開票と事後逆行の追加射影.json'))
    source=common.sources();counts=Counter();projections=[]
    common.write('読取開始.json',dict(正式一回=True,source_SHA256=source,計画SHA256=plan_sha,予定台帳一読=len(plan['targets']),金融=0,入力=0,API=0))
    try:
        for item in plan['targets']:
            path=common.ROOT/item['path'];assert path.resolve().is_relative_to(common.ROOT/'work/e01_cross_market_20261014/engine/finance/ledgers')
            assert counts[item['path']]==0;counts[item['path']]+=1;saved=path.read_bytes()
            assert hashlib.sha256(saved).hexdigest()==item['SHA256'];ledger=pickle.loads(gzip.decompress(saved))
            projections.extend(project(ledger,item));del ledger,saved
        assert len(counts)==len(plan['targets'])==16 and all(n==1 for n in counts.values())
        assert common.sources()==source
        grouped={}
        for case,symbol in (('E01_CROSS_B03','TOPIX'),('E01_CROSS_B03','NK225'),('E01_CROSS_B01','TOPIX')):
            own=[r for r in projections if r['case_id']==case and r['symbol']==symbol]
            grouped[case+'|'+symbol]=dict(実親数=len(own),黒字親=sum(r['actual_net_yen']>0 for r in own),
                赤字親=sum(r['actual_net_yen']<0 for r in own),direction_vote_counts=dict(Counter(str(r['publication']['direction_votes']) for r in own)),
                balances=dict(Counter(str(r['publication']['balance']) for r in own)),
                初受理qと実fillq差数=sum(r['session_first_accept']['quantity']!=r['actual_fill']['quantity'] for r in own),
                総net=sum(r['actual_net_yen'] for r in own),分母='指定活動場又は指定赤字場にある完結実親。場停止後の影GU親は含めない。')
        common.write('実公開票と事後逆行の追加射影.json',dict(全合格=True,source_SHA256=source,開始終端source一致=True,
            計画SHA256=plan_sha,保存結果SHA256=plan['result_SHA256'],台帳一読=dict(counts),台帳数=16,
            parent_projections=projections,summary=grouped,
            limitations=plan['limitations'],金融再生=0,入力読取=0,原板=0,NPZ=0,API=0))
        print('追加公開票と事後逆行の射影完了 '+str(len(projections))+'実親、十六台帳一読',flush=True)
    except BaseException:
        common.write('読取False.json',dict(全合格=False,原因=traceback.format_exc(),読取計数=dict(counts),
            source開始SHA256=source,計画SHA256=plan_sha,自動再開始=False,金融=0,入力=0,API=0));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root-review-complete',action='store_true')
    args=parser.parse_args();assert args.root_review_complete;run()
