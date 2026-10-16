"""観測が十分な逆票見送りをW60成行の二出口へ固定する。"""

TRIAL_ID='106_E01既知二票以上の逆票見送り二出口対照'
QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}


def configs() -> list[dict]:
    """
    機能: 結果前のKNOWN_VETO・60価格代理秒・成行・GU/P1L8を返す。
    引数: なし。
    返り値: list[dict]は二条件。既知データ損益から窓や閾値を追加しない。
    """
    return [dict(id=f'E01_TRADE_W60_KNOWN_VETO_D0_{exit_id}',window_seconds=60,mode='KNOWN_VETO',
        exit=exit_id,execution='D0',quantity=QUANTITY,cap=CAP,offset_atr=0.,
        baseline_id=f'E01_TRADE_W60_VETO_D0_{exit_id}') for exit_id in ('GU','P1L8')]
