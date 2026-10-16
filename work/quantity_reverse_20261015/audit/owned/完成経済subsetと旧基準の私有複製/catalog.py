"""公表活動と数量の三入口を、同じ実全量と四出口で対照する。"""

CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(418,10),'NK225':(11,1)}
ENTRIES=('A_ALL_TYPE0','B_NEVER_BELOW','C_SAME_SIDE_DEPTH')
EXITS=('E1_TP2_SL2','E2_TP4_SL2','E3_ARM3_TRAIL1','E4_HALF2_TRAIL1')
TRIAL_ID='116_同じ板入口の買売方向を反転する十二対照'


def configs() -> list[dict]:
    """
    機能: 三入口と四出口だけの結果前固定候補を返す。
    引数: なし。
    返り値: list[dict] は十二条件。先着率を利益又は約定率として扱わない。
    """
    return [dict(id='QREVERSE_'+entry+'_'+exit_id,entry_id=entry,exit_id=exit_id,
        entry_mode=i,exit_mode=j,direction_multiplier=-1,quantity=dict(CAP),cap=dict(CAP),
        entry_execution='公開直後のraw seq+1だけmarket。データ資格不達なら取消し、後正常行へ繰越さない。',
        public_spread_limit_ticks=2.,public_spread_strict=True,arrival_spread_cancel=False,
        parent_stop_ticks=2.,session_loss_fraction=.00125,session_profit_fraction=.00375,
        target_session_mean_net_yen={'TOPIX':100000,'NK225':'円額床の対象外（未指定）'},
        主候補=bool(i==2 and j==3),model='CurrentPriceTime模型。真の受信順/注文応答時計は未保存。')
        for i,entry in enumerate(ENTRIES) for j,exit_id in enumerate(EXITS)]
