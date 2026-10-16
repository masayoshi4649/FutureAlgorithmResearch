"""低い純益保護と二市場価格票からの新しい再参加を十二条件へ分ける。"""

CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
TRIAL_ID='109_E01反対価格票退出だけを外した四再参加三保護の十二対照'


def configs() -> list[dict]:
    """
    機能: 四再参加×三純益保護を結果前の共通ルールへ固定する。
    引数: なし。
    返り値: list[dict] は十二条件。商品別円床未指定を零で補完しない。
    """
    result=[]
    for mode in ('ORIGIN','PULL','BREAK','ADAPTIVE'):
        for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
            arm,draw,floor=(.00075,.00025,.0005) if exit_id=='TIGHT_TRAIL' else (.00125,.000375,.00075)
            result.append(dict(id='E01_NO_PRICE_EXIT_'+mode+'_'+exit_id,paired_on_id='E01_PROTECT_'+mode+'_'+exit_id,
                enable_opposed_price_exit=False,reentry_id=mode,exit_id=exit_id,
                quantity=CAP,cap=CAP,window_seconds=60,min_votes=2,balance_threshold=.25,strong_balance_threshold=.75,
                peer_max_price_age_seconds=60,parent_stop_fraction=.00075,parent_target_fraction=.00125,
                arm_fraction=arm,draw_fraction=draw,floor_fraction=floor,
                pull_fraction=.00025,recover_fraction=.000125,break_fraction=.00025,
                public_spread_cost_parent_stop_ratio=.5,session_stop_fraction=.0025,session_profit_fraction=.00375,
                target_session_mean_net_yen={'TOPIX':100000,'NK225':'円額目標の対象外（未指定）'},
                paper_partial_exit='実枚数へ写さない。全影退出/方向撤回だけ尊重する。'))
    assert len(result)==12 and len({c['id'] for c in result})==12
    return result
