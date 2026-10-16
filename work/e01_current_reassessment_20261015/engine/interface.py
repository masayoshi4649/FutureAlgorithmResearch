"""共通構造sourceを一回準備し、九Native運転を実UID会計と保存原始型へ結ぶ。"""

import numpy as np
import bars
import catalog
import core
import daily
import flows
import input_contract
import price_features
import signals

REASONS={90:'公開価格限界内の一回FAK約定',92:'予定静観',93:'場内期限',94:'実保有又は予約busy',96:'現在価格又は支持L不明',
    98:'一回FAK価格不成立',140:'親純利益目標',141:'親純損失停止',142:'親純益保護',143:'確定支持線の両気配喪失',153:'共通新規期間外',154:'公開気配差と料の余裕不足',
    161:'場純損失停止',162:'場純利益停止'}


def prepare(gate_packet: dict,exit_packet: dict,python: bool=False,initial_capacity: int=32) -> dict:
    """
    機能: 二cacheを厳密joinし、現在票/閉足/共通構造eventを一場一回生成する。
    引数: gate_packet/exit_packet(dict)、python(bool)、initial_capacity(int) は保存入力と実装検算条件。
    返り値: dict[symbol,dict] は九条件で共有するfeatures。実注文や紙上方向を生成しない。
    """
    checks=input_contract.strict_join(gate_packet,exit_packet);prices=price_features.pair(gate_packet);output={}
    fn=signals.generate.py_func if python else signals.generate
    for symbol in ('TOPIX','NK225'):
        a=gate_packet['accounts'][symbol];r,q=a['record'],a['quotes'];p=prices[symbol];v=exit_packet['accounts'][symbol]['votes']['60']
        level=bars.closed(a,p['own']['normal']);f=flows.measure(v,p,symbol)
        candidates,breakpoints,consumed,retired=fn(q['bid'],q['ask'],p['own']['normal'],level['high'],level['low'],level['bucket_id'],level['confirmed_row'],
            f['volume_known'],f['price_known'],f['volume_gate'],f['price_gate'],f['interval_known'],f['new_up_lower'],f['new_down_lower'],r['tick'],initial_capacity)
        output[symbol]=dict(price=p,volume=v,bar=level,flow=f,candidates=candidates,breakpoints=breakpoints,consumed=consumed,retired=retired,input_checks=checks,
            definition='paper/PUBは入力同源照合だけ。候補は最新の確定5分Lと全normalの現在根拠。各L/side episode/入口種類で一回。')
    return output


def finite(value: object) -> object:
    """
    機能: 保存診断をJSON原始型へ写し、非有限の観測欠測をNoneで残す。
    引数: value(object) は一次出力の診断。
    返り値: object は保存構造。採否計算へ補完値を戻さない。
    """
    if isinstance(value,np.ndarray):return finite(value.tolist())
    if isinstance(value,np.generic):return finite(value.item())
    if isinstance(value,float):return value if np.isfinite(value) else None
    if isinstance(value,dict):return {k:finite(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [finite(v) for v in value]
    return value


def play(account: dict,features: dict,config: dict,session: str,finish: bool=True,python: bool=False,initial_capacity: int=32) -> dict:
    """
    機能: 一入口種類の現在構造eventをNative全量運転し、独立実注文会計へ照合する。
    引数: account/features/config(dict)、session(str)、finish/python(bool)、initial_capacity(int)。
    返り値: dict は注文/UID/返済対象/完結親/実脚/全行会計とPUB/支持/判断。未完成接頭は全場と呼ばない。
    """
    symbol=account['symbol'];r,q=account['record'],account['quotes'];f=features['flow'];p=features['price'];num,den=catalog.FEE_RATIO[symbol]
    assert config['quantity'][symbol]==config['cap'][symbol]==catalog.CAP[symbol]
    candidates=features['candidates'];candidates=candidates[candidates[:,1]==catalog.ENTRIES.index(config['entry_id'])]
    assert len({int(row) for row in candidates[:,0]})==len(candidates),'同種類/当行の買売候補重複'
    execution=dict(q,quote_valid=q['quote_valid']&np.isfinite(r['time_s']))
    fn=core.simulate.py_func if python else core.simulate
    values=fn(r['time_s'],r['price'],q['bid'],q['ask'],execution['quote_valid'],account['quiet'],account['quiet_force'],p['own']['normal'],
        f['volume_known'],f['price_known'],f['volume_gate'],f['price_gate'],f['interval_known'],f['new_up_lower'],f['new_down_lower'],f['strong'],candidates,
        r['start'],r['limit'],catalog.CAP[symbol],r['tick'],catalog.VALUE[symbol],num,den,catalog.EXITS.index(config['exit_id']),
        config['parent_stop_fraction'],config['parent_target_fraction'],config['arm_fraction'],config['draw_fraction'],config['floor_fraction'],
        config['session_stop_fraction'],config['session_profit_fraction'],config['public_cost_stop_ratio'],initial_capacity)
    if finish:assert r['time_s'][-1]>=r['limit']
    result=daily.reconstruct((session,symbol),values[0],values[1],execution,finish=finish)
    for field,column in (('equity_yen',0),('liquidation_yen',1),('long_qty',4),('short_qty',5),('cumulative_fees',6),('reserved_exit_fees',7)):
        np.testing.assert_allclose(result[field],values[2][:,column],atol=1e-5,rtol=1e-12,err_msg=field)
    opened=result['orders'][result['orders'][:,7]==1];assert np.all(opened[:,4]==catalog.CAP[symbol])
    completed=sorted({u['親'] for u in result['uid_accounts'] if u['残枚数']==0})
    if finish:assert len(completed)==len(result['parent'])==len(opened)
    assert not np.any(np.isin(result['orders'][:,6],np.asarray([151,152])))
    result.update(case=config,uids=result['order_uids'],targets=result['exit_target_uids'],economic_curve=values[2],publication_events=values[3],
        exit_judgments=values[4],execution_events=values[5],actual_origins=values[6],support_events=values[7],buffer_capacity=int(values[8]),
        actual_completed_parent_ids=completed,source_scope='実CID/UIDのみ。paper/元ATR/旧PUB/未知補完に依存しない。',
        finish=finish,完成範囲='全場' if finish else '未完成接頭。次normal未観測の予約は保持。')
    result['parent_diagnostics']=parent_diagnostics(account,features,result)
    return result


def parent_diagnostics(account: dict,features: dict,output: dict) -> list[dict]:
    """
    機能: 完結実親の支持/現在票/実注文と実保有normal内の事後極値を一次入力から保存する。
    引数: account/features/output(dict) は一次保存入力/現在features/実出力。
    返り値: list[dict] はJSON原始型の小射影。非保有の潜在波や心理を捏造しない。
    """
    r,q=account['record'],account['quotes'];curve=output['economic_curve'];orders=output['orders'];v=features['volume'];p=features['price'];s=account['symbol'];result=[]
    good=daily.normal_mask(q)&np.isfinite(r['time_s'])
    for parent in output['parent']:
        cid=int(parent['親'])
        if cid not in output['actual_completed_parent_ids']:continue
        entry=orders[(orders[:,2]==cid)&(orders[:,7]==1)];exits=orders[(orders[:,2]==cid)&(orders[:,7]==0)]
        origins=output['actual_origins'][output['actual_origins'][:,0]==cid];assert len(entry)==len(exits)==len(origins)==1
        entry,exit,origin=entry[0],exits[0],origins[0];first,last=int(entry[0]),int(exit[0]);side=int(entry[3]);pub=int(entry[1])
        rows=np.flatnonzero(good[first:last+1])+first;local=curve[rows,2];assert len(rows) and np.all(curve[rows,8]==cid)
        def point(row: int) -> dict:
            """
            機能: 同観測行の原seq/価格時計/BBO/局所清算/現在票を未補完で整理する。
            引数: row(int) はnormal列位置。
            返り値: dict は観測点。未知の票をdebug零へ替えない。
            """
            known=bool(v['known'][row]);same=int(curve[row,8])==cid
            return finite(dict(normal_row=int(row),raw_row=int(account['mapping'][row]),raw_seq=int(r['seq'][row]),price_time_s=float(r['time_s'][row]),
                Last=float(r['price'][row]),bid=float(q['bid'][row]),ask=float(q['ask'][row]),normal=bool(good[row]),
                parent_liquidation_yen=float(curve[row,2]) if same else None,support_line=float(curve[row,11]) if same else None,
                volume_known=known,volume_reason=int(v['reason'][row]),volume_up=int(v['up_votes'][row]) if known else None,
                volume_down=int(v['down_votes'][row]) if known else None,volume_signed_balance=side*float(v['balance'][row]) if known else None,
                own_price_known=bool(p['own']['known'][row]),own_price_count=int(p['own']['count'][row]) if p['own']['known'][row] else None,
                own_price_balance=side*float(p['own']['balance'][row]) if p['own']['known'][row] else None,
                peer_price_known=bool(p['peer_known'][row]),peer_price_count=int(p['peer_count'][row]) if p['peer_known'][row] else None,
                peer_price_balance=side*float(p['peer_balance'][row]) if p['peer_known'][row] else None,
                peer_row=int(p['peer_row'][row]),peer_raw_seq=int(p['peer_raw_seq'][row]),peer_price_age_seconds=float(p['peer_price_age_seconds'][row])))
        def event(order: np.ndarray) -> dict:
            """
            機能: 判断/実約定の価格代理時計と全量の個別floor料金を結ぶ。
            引数: order(ndarray[float,8]) は実新規又は全量返済。
            返り値: dict は注文と二つの観測。受信/注文応答時刻と呼ばない。
            """
            source,row=int(order[1]),int(order[0]);reason=int(order[6])
            return dict(source_row=source,row=row,quantity=int(order[4]),price=float(order[5]),fee_yen=daily.fee(int(order[4]),s),
                reason=reason,reason_label=REASONS.get(reason,'保存理由'+str(reason)),判断=point(source),約定=point(row))
        publication=output['publication_events'][(output['publication_events'][:,1]==cid)&(output['publication_events'][:,12]==1)];assert len(publication)==1
        z=publication[0];updates=output['support_events'][output['support_events'][:,1]==cid]
        assert not len(updates) or np.all(updates[:,5]>first)
        maximum,minimum=int(rows[np.argmax(local)]),int(rows[np.argmin(local)])
        result.append(finite(dict(parent=cid,side=side,entry=event(entry),exits=[event(exit)],entry_quantity=int(entry[4]),capacity=catalog.CAP[s],
            structure_event=int(origin[1]),structure_level=float(origin[9]),initial_support_line=float(origin[10]),support_width=float(origin[11]),
            entry_response_proof_row=int(origin[15]),published_price_cap=float(origin[12]),published_adverse_ticks=int(origin[13]),
            notional_yen=float(origin[7]),net_yen=float(parent['収支']),fees_yen=int(parent['費用']),parent_stop_yen=float(origin[7])*output['case']['parent_stop_fraction'],
            target_yen=float(origin[7])*output['case']['parent_target_fraction'] if output['case']['exit_id']=='TARGET' else None,
            publication=point(pub),structure_break_row=int(z[14]),structure_response_row=int(z[15]),level_confirmed_row=int(z[18]),
            best_parent_liquidation_yen=float(local.max()),worst_parent_liquidation_yen=float(local.min()),parent_mae_yen=max(0.,float(-local.min())),
            parent_mfe_yen=float(local.max()),first_parent_liquidation_argmax=point(maximum),first_parent_liquidation_argmin=point(minimum),
            holding_price_proxy_seconds=float(r['time_s'][last]-r['time_s'][first]),support_events=updates,
            hindsight_only=True,clock_definition='CurrentPriceTime模型。実受信/真の攻撃注文時刻は未保存。',
            definition='一実CID/UIDの全量保有区間だけ。前親netを除く清算・個別実料。事後極値を別退出救済PLへ換算しない。')))
    return result
