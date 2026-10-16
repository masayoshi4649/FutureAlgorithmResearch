"""公開時二入口を固定し、保有中の逆票と4呼値損失だけを追加する6対照。"""

TRIAL_ID='106_E01保有中の逆票と4呼値損失の同時退出6対照'
QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}


def configs() -> list[dict]:
    """
    機能: W60公開時CONFIRM/VETOの同GUに対し、途中W10/30/60の固定6条件を返す。
    引数: なし。
    返り値: list[dict]は結果を見て選ばない条件。逆票だけの退出は含めない。
    """
    return [dict(id=f'E01_EXIT_{mode}_W{w}_P1_H8_V4',mode=mode,window_seconds=w,
        entry_window_seconds=60,execution='D0',profit_ticks=1,loss_ticks=8,early_loss_ticks=4,
        quantity=QUANTITY,cap=CAP,GU_id=f'E01_TRADE_W60_{mode}_D0_GU',
        baseline8_id=f'E01_TRADE_W60_{mode}_D0_P1L8',baseline4_id=f'E01_BUDGET_W60_{mode}_D0_P1_L4')
        for mode in ('CONFIRM','VETO') for w in (10,30,60)]
