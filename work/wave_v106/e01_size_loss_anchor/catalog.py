"""公開時数量予算を保ち、初回受理数量へ利益と損失の停止線を対応させる四対照。"""

QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
BUDGET={'TOPIX':5000.,'NK225':2000.}
TRIAL_ID='106_E01予定数量の初回受理損失アンカーP1P2四対照'


def configs() -> list[dict]:
    """
    機能: 母条件二つと利益目標二つを、結果を見る前の四条件へ列挙する。
    引数: なし。
    返り値: list[dict] は数量選択予算不変、損失停止線だけを比例させる四対照。
    """
    return [dict(id='E01_LOSS_ANCHOR_W60_'+mode+'_D0_P'+str(profit)+'_L2_A1',mode=mode,window_seconds=60,
        execution='D0',offset_atr=0.,profit_ticks=profit,loss_ticks=2,risk_atr_multiple=1.,
        quantity=QUANTITY,cap=CAP,profit_goal_yen={s:profit*BUDGET[s]/2 for s in QUANTITY},
        quantity_selection_budget_yen=BUDGET,loss_stop_base_yen=BUDGET,
        goal_anchor='最初の受理新規q。約定無しでも固定保持。',loss_anchor='停止線だけL2×最初受理q/full。数量選択予算は不変。',
        baseline_id='E01_ANCHOR_W60_'+mode+'_D0_P'+str(profit)+'_L2_A1')
        for mode in ('CONFIRM','VETO') for profit in (1,2)]
