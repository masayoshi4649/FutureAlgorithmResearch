"""全normal独立の三入口と三Native退出を、同じ容量・時計・構造で比較する。"""

TRIAL_ID='113_E01に依存しない現在確認とquote再進行の九対照'
CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
ENTRIES=('CURRENT_VOL_SEL','CURRENT_VOL_PRICE','CURRENT_VOL_PRICE_RESPONSE')
EXITS=('TARGET','TIGHT_TRAIL','WIDE_TRAIL')


def configs() -> list[dict]:
    """
    機能: 根裁定の三入口×三Native退出をJSON同値の構造へする。
    引数: なし。
    返り値: list[dict] は九つの未金融条件。旧111参考は新条件へ混ぜない。
    """
    result=[]
    for entry in ENTRIES:
        for exit_id in EXITS:
            arm,draw,floor=(.00075,.00025,.0005) if exit_id=='TIGHT_TRAIL' else (.00125,.000375,.00075)
            result.append(dict(id='E01_CURRENT_'+entry.removeprefix('CURRENT_')+'_'+exit_id,entry_id=entry,exit_id=exit_id,
                entry_domain='paper/PUBに依存しない全normalの構造event',quantity=dict(CAP),cap=dict(CAP),window_seconds=60,min_votes=2,
                volume_balance_threshold={'TOPIX':.5,'NK225':.25},price_min_votes_each=2,price_balance_threshold_each=.25,
                peer_max_price_age_seconds=60,bar_seconds=300,empty_previous_bar='L未知、carry無し',
                base_progress_ticks=1,response_progress_ticks=2,probe_max_adverse_ticks=1,support_margin_ticks=1,
                structural_stop_inclusive=True,breakout_strict=True,strong_price_min2=True,strong_price_balance=.75,
                parent_stop_fraction=.00075,parent_target_fraction=.00125,arm_fraction=arm,draw_fraction=draw,floor_fraction=floor,
                session_stop_fraction=.0025,session_profit_fraction=.00375,public_cost_stop_ratio=.5,
                new_start_offset_seconds=300,new_end_offset_seconds=300,holding_time_stop='不使用',paper_withdrawal_exit='不使用',
                holding_support_update='全3入口共通。新反対更新＋両気配逆側1T超無し＋後2T再進行で有利方向だけ更新。',
                target_session_mean_net_yen={'TOPIX':100000,'NK225':'円額目標の対象外（未指定）'}))
    assert len(result)==9
    return result
