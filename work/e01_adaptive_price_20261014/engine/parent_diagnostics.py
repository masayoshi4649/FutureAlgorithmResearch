"""一次入力と実政策だけから、公開許容・実注文・事後清算の小射影を保存する。"""

import numpy as np
import daily


def project(account: dict, output: dict) -> list[dict]:
    """
    機能: 全完結実親の公開票・許容価格と入口/返済及び事後最悪清算を小資料へ射影する。
    引数: account/output(dict) は同一次読取口座と実政策の完全出力。
    返り値: list[dict] は実親だけの事後診断。未来極値を入口/出口の規則に使用しない。
    """
    record=account['record'];quotes=account['quotes'];orders=output['orders'];parents=output['parent']
    normal=daily.normal_mask(quotes);result=[]
    for parent in parents:
        cid=int(parent['親']);selected=orders[orders[:,2]==cid]
        new=selected[selected[:,7]==1];repays=selected[selected[:,7]==0]
        assert len(new)==1 and len(repays)>0
        first=new[0];row,publication=int(first[0]),int(first[1]);last=int(parent['最終返済行'])
        assert row==int(parent['新規行']) and int(repays[-1,0])==last
        vote=account['trade_features']['60'][publication]
        size=output['sizing_events'][(output['sizing_events'][:,0]==publication)&(output['sizing_events'][:,1]==cid)]
        fak=output['fak_events'][(output['fak_events'][:,1]==1)&(output['fak_events'][:,3]==publication)&(output['fak_events'][:,2]==cid)]
        assert len(size)==len(fak)==1 and fak[0,15]==1
        other=[p for p in parents if int(p['親'])!=cid and int(p['新規行'])<=last and int(p['最終返済行'])>=row]
        indices=np.flatnonzero(normal[row:last+1])+row
        assert len(indices)>0
        prior=sum(p['収支'] for p in parents if int(p['最終返済行'])<row)
        curve=output['liquidation_yen'][indices]
        local=curve-prior if not other else None
        def order_data(order: np.ndarray) -> dict:
            """
            機能: 実注文の判断/約定の原seqと価格代理時計を、その行の資料へ結ぶ。
            引数: order(ndarray[float,8]) は実新規又は返済。
            返り値: dict は観測実価格・枚数・料。物理受信時計へ補完しない。
            """
            fill,source=int(order[0]),int(order[1])
            return dict(row=fill,source_row=source,raw_seq=int(record['seq'][fill]),source_raw_seq=int(record['seq'][source]),
                price_time_s=float(record['time_s'][fill]),source_price_time_s=float(record['time_s'][source]),
                side=int(order[3]),quantity=int(order[4]),price=float(order[5]),fee_yen=daily.fee(int(order[4]),account['symbol']),
                reason=int(order[6]),bid=float(quotes['bid'][fill]),ask=float(quotes['ask'][fill]))
        anchor=output['goal_anchor']
        result.append(dict(parent=cid,side=int(parent['方向']),net_yen=float(parent['収支']),fee_yen=int(parent['費用']),
            entry=order_data(first),exits=[order_data(o) for o in repays],publication_row=publication,
            publication_raw_seq=int(record['seq'][publication]),publication_price_time_s=float(record['time_s'][publication]),
            published_balance=vote['balance'],published_direction_votes=int(vote['direction_votes']),published_known=bool(vote['known']),
            published_adverse_ticks=int(fak[0,9]),published_price_cap=float(fak[0,6]),published_atr=float(size[0,5]),
            published_spread=float(size[0,6]),publication_bid=float(quotes['bid'][publication]),publication_ask=float(quotes['ask'][publication]),
            initial_anchor_quantity=anchor['数量'],actual_entry_quantity=int(first[4]),
            observed_normal_rows=len(indices),prior_completed_net_yen=float(prior),overlapping_parent_ids=[int(p['親']) for p in other],
            worst_fee_liquidation_yen=float(np.min(curve)),
            parent_worst_fee_liquidation_yen=None if local is None else float(np.min(local)),
            parent_observed_mae_yen=None if local is None else float(max(0.,-np.min(local))),
            definition='正常観測行の費用後同時全玉清算。親期間が他親と重なる場合は局所MAE未定義。非重複だけ前完結親netを差し引く。',
            hindsight_only=True,clock_definition='CurrentPriceTimeの価格代理時計。受信又は発注応答時計ではない。'))
    assert len(result)==len(parents)
    return result
