"""十二保護再参加条件を独立実注文会計と公開/影/実親の系譜へ結ぶ。"""

import numpy as np
import catalog
import core
import daily
import entry_gate


REASONS={90:'新規FAK約定',92:'予定静観',93:'場内期限',98:'一回FAK価格不成立',
    140:'親純利益目標',141:'親純損失停止',142:'親純益保護',151:'paper退出又は方向撤回',
    152:'両市場の反対価格票',161:'場純損失停止',162:'場純利益停止'}


def play(account: dict, features: dict, config: dict, session: str,
         finish: bool=True, python: bool=False, initial_capacity: int=32) -> dict:
    """
    機能: 一保存口座と同場の因果価格票から、全後続の保護/新しい再参加を運転する。
    引数: account/features/config(dict)、session(str)、finish/python(bool)、initial_capacity(int)。
    返り値: dict は独立会計と九出力。未完成接頭を全場損益又は目標達成としない。
    """
    s=account['symbol'];r,q=account['record'],account['quotes'];f=features;num,den=catalog.FEE_RATIO[s]
    assert config['quantity'][s]==config['cap'][s]==catalog.CAP[s]
    execution=dict(q,quote_valid=q['quote_valid']&np.isfinite(r['time_s']))
    gate=entry_gate.build(account,features,config)
    fn=core.simulate.py_func if python else core.simulate
    values=fn(r['time_s'],r['price'],q['bid'],q['ask'],execution['quote_valid'],account['feed'],account['quiet'],account['quiet_force'],
        f['own']['normal'],f['own']['known'],f['own']['count'],f['own']['balance'],f['peer_known'],f['peer_count'],f['peer_balance'],
        r['start'],r['limit'],catalog.CAP[s],r['tick'],catalog.VALUE[s],num,den,
        ('ORIGIN','PULL','BREAK','ADAPTIVE').index(config['reentry_id']),('TARGET','TIGHT_TRAIL','WIDE_TRAIL').index(config['exit_id']),
        config['parent_stop_fraction'],config['parent_target_fraction'],config['arm_fraction'],config['draw_fraction'],config['floor_fraction'],
        config['session_stop_fraction'],config['session_profit_fraction'],config['pull_fraction'],config['recover_fraction'],
        config['break_fraction'],initial_capacity,config['enable_opposed_price_exit'],gate['allowed'])
    if finish:assert len(r['time_s'])>0 and r['time_s'][-1]>=r['limit']
    result=daily.reconstruct((session,s),values[0],values[1],execution,finish=finish)
    for field,column in (('equity_yen',0),('liquidation_yen',1),('long_qty',4),('short_qty',5),('cumulative_fees',6),('reserved_exit_fees',7)):
        np.testing.assert_allclose(result[field],values[2][:,column],atol=1e-5,rtol=1e-12,err_msg=field)
    opened=result['orders'][result['orders'][:,7]==1];assert np.all(opened[:,4]==catalog.CAP[s])
    assert len(values[6])==len(opened)
    completed={u['親'] for u in result['uid_accounts'] if u['残枚数']==0}
    if finish:assert len(completed)==len(result['parent'])==len(opened)
    result.update(case=config,economic_curve=values[2],publication_events=values[3],exit_judgments=values[4],execution_events=values[5],
        actual_origins=values[6],geometry_trace=values[7],buffer_capacity=int(values[8]),actual_completed_parent_ids=sorted(completed),
        source_scope='新実CID/UIDごとに完結。paper CID/部分数量は別状態。全退出/方向撤回だけ実全量予約。',
        entry_gate_diagnostics=gate['diagnostics'],
        完成範囲='全場' if finish else '未完成接頭。未完実親を目標達成の分母へ代用しない。')
    return result


def finite(value: object) -> object:
    """
    機能: 保存診断だけをJSON型へ写し、NaN又は欠測をNoneで残す。
    引数: value(object) は一次出力の保存対象。
    返り値: object は未補完の構造。利益/目標の零を捏造しない。
    """
    if isinstance(value,np.ndarray):return finite(value.tolist())
    if isinstance(value,np.generic):return finite(value.item())
    if isinstance(value,float):return value if np.isfinite(value) else None
    if isinstance(value,dict):return {k:finite(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [finite(v) for v in value]
    return value


def parent_diagnostics(account: dict, features: dict, output: dict) -> list[dict]:
    """
    機能: 実完結親の二市場新価格票・公開cap・paper根拠・保護線と事後極値を小保存する。
    引数: account/features/output(dict) は一次入力/価格票と実出力。
    返り値: list[dict] は完結実親だけ。実非保有期間又は未保存深板を推定しない。
    """
    r,q=account['record'],account['quotes'];s=account['symbol'];orders=output['orders'];curve=output['economic_curve'];cfg=output['case']
    good=daily.normal_mask(q)&np.isfinite(r['time_s']);result=[]
    for p in output['parent']:
        cid=int(p['親'])
        if cid not in output['actual_completed_parent_ids']:continue
        new=orders[(orders[:,2]==cid)&(orders[:,7]==1)];exits=orders[(orders[:,2]==cid)&(orders[:,7]==0)]
        origin=output['actual_origins'][output['actual_origins'][:,0]==cid];assert len(new)==len(origin)==1 and len(exits)==1
        origin=origin[0];entry=new[0];first,last=int(entry[0]),int(exits[-1,0]);pub=int(entry[1]);notional=float(origin[7])
        rows=np.flatnonzero(good[first:last+1])+first;local=curve[rows,2];assert len(rows)>0 and np.all(curve[rows,8]==cid)
        published=output['publication_events'][(output['publication_events'][:,1]==cid)&(output['publication_events'][:,12]==1)]
        assert len(published)==1;published=published[0]
        def point(row: int) -> dict:
            """
            機能: 当該実親の保存原seq/代理時計/BBO/局所清算を未補完で整理する。
            引数: row(int) は一次normal列位置。
            返り値: dict は観測点。受信/注文応答時刻を代用しない。
            """
            same=int(curve[row,8])==cid
            return finite(dict(normal_row=row,raw_seq=int(r['seq'][row]),raw_index=int(account['mapping'][row]),
                price_time_s=float(r['time_s'][row]),Last=float(r['price'][row]),bid=float(q['bid'][row]),ask=float(q['ask'][row]),
                normal=bool(good[row]),parent_liquidation_yen=float(curve[row,2]) if same else None,
                parent_peak_yen=float(curve[row,3]) if same else None,paper_parent=int(curve[row,11]),paper_direction=int(curve[row,12]),
                paper_remaining_quantity=int(curve[row,13]),
                own_count=int(features['own']['count'][row]),own_balance=float(features['own']['balance'][row]),
                peer_known=bool(features['peer_known'][row]),peer_count=int(features['peer_count'][row]),
                peer_balance=float(features['peer_balance'][row]),peer_row=int(features['peer_row'][row]),
                peer_raw_seq=int(features['peer_raw_seq'][row]),peer_price_age_seconds=float(features['peer_price_age_seconds'][row])))
        def event(order: np.ndarray) -> dict:
            """
            機能: 実注文の判断/約定と各注文料を系譜へ結ぶ。
            引数: order(ndarray[float,8]) は実新規又は返済。
            返り値: dict は未補完の実観測。paper数量と実qを混ぜない。
            """
            row,source=int(order[0]),int(order[1]);reason=int(order[6]);same=int(curve[source,8])==cid
            protective=max(notional*cfg['floor_fraction'],curve[source,3]-notional*cfg['draw_fraction']) if same else np.nan
            return finite(dict(row=row,source_row=source,price=float(order[5]),quantity=int(order[4]),fee_yen=daily.fee(int(order[4]),s),
                reason=reason,reason_label=REASONS.get(reason,'保存理由'+str(reason)),判断=point(source),約定=point(row),
                親純損失線=notional*cfg['parent_stop_fraction'] if same else None,
                親純利益線=notional*cfg['parent_target_fraction'] if same and cfg['exit_id']=='TARGET' else None,
                発動後保護線=protective if same and cfg['exit_id']!='TARGET' and curve[source,3]>=notional*cfg['arm_fraction'] else None))
        minimum,maximum=int(rows[np.argmin(local)]),int(rows[np.argmax(local)])
        direction=int(p['方向']);clear=q['bid' if direction>0 else 'ask'][rows];movement=direction*(clear-entry[5])
        result.append(finite(dict(parent=cid,paper_parent=int(origin[1]),side=direction,entry=event(entry),exits=[event(e) for e in exits],
            entry_quantity=int(entry[4]),maximum_held_quantity=int(np.max(curve[rows,4]+curve[rows,5])),capacity=catalog.CAP[s],
            net_yen=float(p['収支']),fees_yen=int(p['費用']),notional_yen=notional,parent_stop_yen=notional*cfg['parent_stop_fraction'],
            target_yen=notional*cfg['parent_target_fraction'] if cfg['exit_id']=='TARGET' else None,
            arm_yen=notional*cfg['arm_fraction'] if cfg['exit_id']!='TARGET' else None,
            published_price_cap=float(published[10]),published_adverse_ticks=int(published[11]),
            published_paper_price=float(published[6]),published_paper_atr=float(published[7]),published_spread=float(published[8]),
            publication_kind=int(published[4]),published_entry_information=output['entry_gate_diagnostics'][pub],
            published_own_count=int(published[14]),published_own_balance=float(published[15]),
            published_peer_count=int(published[16]),published_peer_balance=float(published[17]),
            worst_parent_liquidation_yen=float(local.min()),best_parent_liquidation_yen=float(local.max()),
            parent_mae_yen=max(0.,float(-local.min())),parent_mfe_yen=float(local.max()),
            first_parent_liquidation_argmin=point(minimum),first_parent_liquidation_argmax=point(maximum),
            liquidation_side_mfe_price=float(movement.max()),liquidation_side_mae_price=float(movement.min()),
            holding_price_proxy_seconds=float(r['time_s'][last]-r['time_s'][first]),hindsight_only=True,
            definition='一実CID/UIDの全量保有区間だけ。前親netを除く局所清算、全実料/残全量返済料。事後極値を別出口利益へ換算しない。',
            clock_definition='CurrentPriceTime代理。二市場はstrict価格時計模型で、物理受信先後は未測。')))
    return result
