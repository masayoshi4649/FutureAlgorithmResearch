"""原新規の四入口三退出を、商品別の唯一金融と保存再利用へ分ける。"""

CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
TRIAL_ID='111_E01少ない価格票で追随せず入口を残す十二比較'


def configs() -> list[dict]:
    """
    機能: 原新規だけの四入口×三退出を固定し、PRICE三条件の再金融をしない。
    引数: なし。
    返り値: list[dict] は十二条件。商品別円床未指定を零で補完しない。
    """
    result=[]
    for entry_id in ('PRICE_BOTH','VOL_SELECTED','VOL25','VOL25_PRICE_BOTH'):
        for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
            arm,draw,floor=(.00075,.00025,.0005) if exit_id=='TIGHT_TRAIL' else (.00125,.000375,.00075)
            cid='E01_EVID_'+entry_id+'_'+exit_id
            result.append(dict(id=cid,entry_id=entry_id,
                paired_previous_id='E01_INFO_'+entry_id+'_'+exit_id,actual_financial=entry_id in ('VOL_SELECTED','VOL25'),
                actual_financial_by_symbol={'TOPIX':entry_id in ('VOL_SELECTED','VOL25'),'NK225':entry_id=='VOL_SELECTED'},
                execution_kind_by_symbol={s:'旧110経済同値保存' if entry_id in ('PRICE_BOTH','VOL25_PRICE_BOTH') else '内部同値保存再利用' if s=='NK225' and entry_id=='VOL25' else '新金融' for s in CAP},
                economic_source_id_by_symbol={s:'E01_INFO_'+entry_id+'_'+exit_id if entry_id in ('PRICE_BOTH','VOL25_PRICE_BOTH') else 'E01_EVID_VOL_SELECTED_'+exit_id if s=='NK225' and entry_id=='VOL25' else cid for s in CAP},
                require_strong_price_min2=True,
                volume_balance_threshold={'TOPIX':.5 if entry_id=='VOL_SELECTED' else .25,'NK225':.25},
                enable_opposed_price_exit=False,reentry_id='ORIGIN',exit_id=exit_id,
                quantity=CAP,cap=CAP,window_seconds=60,min_votes=2,balance_threshold=.25,strong_balance_threshold=.75,
                peer_max_price_age_seconds=60,parent_stop_fraction=.00075,parent_target_fraction=.00125,
                arm_fraction=arm,draw_fraction=draw,floor_fraction=floor,
                pull_fraction=.00025,recover_fraction=.000125,break_fraction=.00025,
                public_spread_cost_parent_stop_ratio=.5,session_stop_fraction=.0025,session_profit_fraction=.00375,
                target_session_mean_net_yen={'TOPIX':100000,'NK225':'円額目標の対象外（未指定）'},
                paper_partial_exit='実枚数へ写さない。全影退出/方向撤回だけ尊重する。'))
    assert len(result)==12 and len({c['id'] for c in result})==12
    return result
