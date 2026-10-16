"""公開時数量を保ち、最初の受理数量だけへ円利益目標を対応させる四対照。"""

QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
BUDGET={'TOPIX':5000.,'NK225':2000.}
TRIAL_ID='106_E01予定リスク数量の初回受理目標アンカーP1P2四対照'


def configs() -> list[dict]:
    """
    機能: 母条件二つと利益目標二つを、結果を見る前の四条件へ列挙する。
    引数: なし。
    返り値: list[dict] は数量計算・損失L2不変の利確目標対照。
    """
    return [dict(id='E01_ANCHOR_W60_'+mode+'_D0_P'+str(profit)+'_L2_A1',mode=mode,window_seconds=60,
        execution='D0',offset_atr=0.,profit_ticks=profit,loss_ticks=2,risk_atr_multiple=1.,
        quantity=QUANTITY,cap=CAP,profit_goal_yen={s:profit*BUDGET[s]/2 for s in QUANTITY},loss_budget_yen=BUDGET,
        goal_anchor='最初の受理新規q。約定無しでも固定保持。',
        baseline_id='E01_SIZE_W60_'+mode+'_D0_P'+str(profit)+'_L2_A1')
        for mode in ('CONFIRM','VETO') for profit in (1,2)]
