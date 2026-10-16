"""新規公開の予定リスク数量と、絶対円P1/P2・L2の四条件を固定する。"""

QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
BUDGET={'TOPIX':5000.,'NK225':2000.}
TRIAL_ID='106_E01公開時の予定リスク数量と絶対円P1P2_L2四対照'


def configs() -> list[dict]:
    """
    機能: 二母条件と二絶対円利益目標を列挙する。
    引数: なし。
    返り値: list[dict] は新4条件。係数・数量・料金を損益で選ばない。
    """
    return [dict(id='E01_SIZE_W60_'+mode+'_D0_P'+str(profit)+'_L2_A1',mode=mode,window_seconds=60,
        execution='D0',offset_atr=0.,profit_ticks=profit,loss_ticks=2,risk_atr_multiple=1.,
        quantity=QUANTITY,cap=CAP,profit_goal_yen={s:profit*BUDGET[s]/2 for s in QUANTITY},loss_budget_yen=BUDGET,
        baseline_id='E01_BUDGET_W60_'+mode+'_D0_P'+str(profit)+'_L2',
        baseline8_id='E01_TRADE_W60_'+mode+'_D0_P1L8',GU_id='E01_TRADE_W60_'+mode+'_D0_GU')
        for mode in ('CONFIRM','VETO') for profit in (1,2)]
