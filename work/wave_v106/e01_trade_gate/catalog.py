"""結果前に固定したE01新規公開確認と二執行の24対照。"""

TRIAL_ID='106_E01公開時の取引更新代理と二執行24対照'
QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}


def configs() -> list[dict]:
    """
    機能: 時間窓・確認又は逆向き拒否・二執行・不変出口の全24条件を返す。
    引数: なし。
    返り値: list[dict]は結果による選択をしない固定条件。
    """
    return [dict(id=f'E01_TRADE_W{w}_{mode}_{execution}_{exit_id}',window_seconds=w,mode=mode,exit=exit_id,
                 execution=execution,quantity=QUANTITY,cap=CAP,offset_atr=0. if execution=='D0' else .2)
            for w in (10,30,60) for mode in ('CONFIRM','VETO')
            for execution in ('D0','D20') for exit_id in ('GU','P1L8')]
