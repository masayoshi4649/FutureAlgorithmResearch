"""60代理秒のE01二入口へ、小利益/損失予算18を結果前に固定する。"""


TRIAL_ID='106_E01取引更新60秒二入口の小利益損失予算18対照'
QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}


def configs() -> list[dict]:
    """
    機能: 完成CONFIRM/VETO D0 GUの実注文接頭に対する18場内停止政策を返す。
    引数: なし。
    返り値: list[dict]は利益1/2/4・損失2/4/8の固定設定。P1L8の2条件は保存再利用する。
    """
    return [dict(id=f'E01_BUDGET_W60_{mode}_D0_P{p}_L{loss}',mode=mode,window_seconds=60,execution='D0',
        profit_ticks=p,loss_ticks=loss,quantity=QUANTITY,cap=CAP,
        GU_id=f'E01_TRADE_W60_{mode}_D0_GU',baseline_id=f'E01_TRADE_W60_{mode}_D0_P1L8',
        saved_alias=(p==1 and loss==8)) for mode in ('CONFIRM','VETO') for p in (1,2,4) for loss in (2,4,8)]
