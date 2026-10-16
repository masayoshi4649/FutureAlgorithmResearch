"""十四規模条件を独立実注文/親会計と当時清算へ結ぶ。"""

import numpy as np
import common
import catalog
import core
import daily
import entry_policy


def play(account: dict, config: dict, session: str, finish: bool=True, python: bool=False) -> dict:
    """
    機能: 同紙上全候補から実親を別状態で再生し、当時会計と容量/利益診断を返す。
    引数: account/config(dict)、session(str)、finish/python(bool) は口座・固定条件・場・完結範囲・実装選択。
    返り値: dict は実注文/完結親/玉/清算と公開/判断系譜。未完成接頭を場完成損益と呼ばない。
    """
    symbol=account['symbol'];record=account['record'];quotes=account['quotes']
    gate_id,strong=config['entry_parameters'][symbol]
    gate=entry_policy.mask(account,gate_id);allow=entry_policy.allowances(account,strong)
    num,den=catalog.FEE_RATIO[symbol];requested=config['quantity'][symbol]
    assert requested==(catalog.HALF[symbol] if config['quantity_mode']=='HALF' else catalog.CAP[symbol])
    fn=core.simulate.py_func if python else core.simulate
    values=fn(record['time_s'],record['price'],quotes['bid'],quotes['ask'],quotes['quote_valid'],account['feed'],
        account['quiet'],account['quiet_force'],record['start'],record['limit'],catalog.CAP[symbol],record['tick'],catalog.VALUE[symbol],
        num,den,gate['accepted'],allow,requested,int(config['quantity_mode']=='RISK'),
        ('GU','TARGET','TRAIL','PARTIAL').index(config['exit_id']),config['quantity_budget_fraction'],config['parent_stop_fraction'],
        config['parent_target_fraction'],config['arm_fraction'],config['draw_fraction'],config['floor_fraction'],
        config['partial_arm_fraction'],config['partial_fraction'],config['session_stop_fraction'])
    if finish:assert len(record['time_s'])>0 and record['time_s'][-1]>=record['limit']
    result=daily.reconstruct((session,symbol),values[0],values[1],quotes,finish=finish)
    curve=values[2]
    for field,index in (('equity_yen',0),('liquidation_yen',1),('long_qty',4),('short_qty',5),('cumulative_fees',6),('reserved_exit_fees',7)):
        np.testing.assert_allclose(result[field],curve[:,index],atol=1e-5,rtol=1e-12,err_msg=field)
    new=result['orders'][result['orders'][:,7]==1]
    if config['quantity_mode']!='RISK':assert np.all(new[:,4]==requested)
    assert len(values[6])==len(new) and len(result['parent'])==len(new)
    completed={u['親'] for u in result['uid_accounts'] if u['残枚数']==0}
    if finish:assert len(completed)==len(result['parent'])
    result.update(case=config,gate_accepted=gate['accepted'],gate_reasons=gate['reasons'],entry_diagnostics=gate['diagnostics'],
        economic_curve=curve,publication_events=values[3],exit_judgments=values[4],execution_events=values[5],actual_origins=values[6],
        pure_parent_complete_ids=sorted(completed),完成範囲='全場' if finish else '未完成接頭',
        source_scope='元paper5/10は候補生成/未約定取消に保持。native実親完結は実UID残0だけで判定しpaper未返済を条件にしない。',
        quantity_semantics='requested実枚数と容量はpaper数量と別。初fill名目額から親線を固定。親利益返済後も次候補を続行。')
    return result


def parent_diagnostics(account: dict, output: dict) -> list[dict]:
    """
    機能: 同一次入力から完結実親の票/容量/費用/実価格と局所清算の事後MFE/MAEを小保存する。
    引数: account/output(dict) は一次口座と実政策台帳。
    返り値: list[dict] は完結親だけの診断。未来極値を入口又は返済規則へ使用しない。
    """
    record=account['record'];quotes=account['quotes'];symbol=account['symbol'];normal=daily.normal_mask(quotes)
    orders=output['orders'];curve=output['economic_curve'];origins=output['actual_origins'];result=[]
    for parent in output['parent']:
        cid=int(parent['親'])
        if cid not in output['pure_parent_complete_ids']:continue
        entries=orders[(orders[:,2]==cid)&(orders[:,7]==1)];exits=orders[(orders[:,2]==cid)&(orders[:,7]==0)]
        assert len(entries)==1 and len(exits)>0;entry=entries[0];first,last=int(entry[0]),int(exits[-1,0])
        origin=origins[origins[:,0]==cid];assert len(origin)==1;origin=origin[0]
        indices=np.flatnonzero(normal[first:last+1])+first
        assert len(indices)>0 and np.all(curve[indices,8]==cid)
        pub=int(entry[1]);vote=account['trade_features']['60'][pub];direction=int(parent['方向'])
        liquidation=curve[indices,2];clears=quotes['bid' if direction>0 else 'ask'][indices]
        movement=direction*(clears-entry[5])
        def event(order: np.ndarray) -> dict:
            """
            機能: 実判断/約定行へ原seqと価格代理時計及び注文別料を付ける。
            引数: order(ndarray[float,8]) は実新規又は返済。
            返り値: dict は実BBO価格/q/料。受信又は応答時刻を推定しない。
            """
            row,source=int(order[0]),int(order[1])
            peak=float(curve[source,3]);notional=float(origin[6]);cfg=output['case']
            same_parent=int(curve[source,8])==cid
            def finite(value: float) -> float|None:
                """
                機能: 診断値の非有限だけを未定義へ写し、零や未来値を補わない。
                引数: value(float) は保存された診断値。
                返り値: float|None は有限値又は未知。
                """
                return float(value) if np.isfinite(value) else None
            return dict(row=row,source_row=source,raw_seq=int(record['seq'][row]),source_raw_seq=int(record['seq'][source]),
                price_time_s=float(record['time_s'][row]),source_price_time_s=float(record['time_s'][source]),
                price=float(order[5]),quantity=int(order[4]),fee_yen=daily.fee(int(order[4]),symbol),reason=int(order[6]),
                bid=float(quotes['bid'][row]),ask=float(quotes['ask'][row]),
                source_normal=bool(normal[source]),source_bid=finite(quotes['bid'][source]),source_ask=finite(quotes['ask'][source]),
                source_parent_liquidation_yen=finite(curve[source,2]) if same_parent else None,
                source_parent_peak_yen=finite(peak) if same_parent else None,
                source_notional_yen=notional if same_parent else None,
                source_parent_stop_yen=notional*cfg['parent_stop_fraction'] if same_parent else None,
                source_target_yen=notional*cfg['parent_target_fraction'] if same_parent and cfg['exit_id']=='TARGET' else None,
                source_trail_line_yen=max(notional*cfg['floor_fraction'],peak-notional*cfg['draw_fraction'])
                    if same_parent and cfg['exit_id'] in ('TRAIL','PARTIAL') and np.isfinite(peak) and peak>=notional*cfg['arm_fraction'] else None,
                source_scene_stop_yen=finite(curve[source,9]),
                source_liquidation_definition='非normal時の局所清算は当行実注文と直前正常markを保持。新しい有効BBOや未来quoteを補った値ではない。')
        q=int(entry[4]);notional=float(origin[6]);paper=account['feed'][(account['feed'][:,2]==cid)&(account['feed'][:,7]==0)]
        def point(position: int) -> dict:
            """
            機能: 実保有normal内の最初の極値行を原seq/代理時計/BBO/局所清算へ結ぶ。
            引数: position(int) は当該親の正常観測位置。
            返り値: dict は事後専用の原行診断。返済ルールへ極値を渡さない。
            """
            row=int(indices[position])
            return dict(row=row,raw_seq=int(record['seq'][row]),price_time_s=float(record['time_s'][row]),
                bid=float(quotes['bid'][row]),ask=float(quotes['ask'][row]),parent_liquidation_yen=float(curve[row,2]),
                holding_quantity=int(curve[row,4]+curve[row,5]),hindsight_only=True)
        result.append(dict(parent=cid,side=direction,entry=event(entry),exits=[event(e) for e in exits],
            entry_quantity=q,maximum_held_quantity=int(np.max(curve[indices,4]+curve[indices,5])),capacity=catalog.CAP[symbol],
            capacity_initial_ratio=q/catalog.CAP[symbol],net_yen=float(parent['収支']),fees_yen=int(parent['費用']),notional_yen=notional,
            parent_stop_yen=notional*output['case']['parent_stop_fraction'],target_yen=notional*output['case']['parent_target_fraction'],
            published_atr=float(origin[8]),published_balance=vote['balance'],published_direction_votes=vote['direction_votes'],
            published_adverse_ticks=int(origin[10]),published_price_cap=float(origin[9]),
            publication_raw_seq=int(record['seq'][pub]),publication_price_time_s=float(record['time_s'][pub]),
            holding_price_proxy_seconds=float(record['time_s'][last]-record['time_s'][first]),
            parent_mae_yen=float(max(0.,-liquidation.min())),parent_mfe_yen=float(liquidation.max()),
            worst_parent_liquidation_yen=float(liquidation.min()),best_parent_liquidation_yen=float(liquidation.max()),
            first_parent_liquidation_argmin=point(int(np.argmin(liquidation))),
            first_parent_liquidation_argmax=point(int(np.argmax(liquidation))),
            liquidation_side_mfe_price=float(movement.max()),liquidation_side_mae_price=float(movement.min()),
            paper_exit_rows=[int(o[0]) for o in paper],paper_exit_prices=[float(o[5]) for o in paper],
            actual_completed_before_paper_exit=bool(len(paper)>0 and last<int(paper[-1,0])),
            definition='初実fill名目N固定。実親局所清算は前親netを除き部分実現・支払料・残UID返済料を含む。価格極値は当該実保有期間だけ。',
            hindsight_only=True,clock_definition='CurrentPriceTimeの価格代理時計。実受信/注文応答時計ではない。'))
    return result
