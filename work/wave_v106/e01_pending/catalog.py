"""待機指値の逆方向取消を六条件、出口二種類へ固定する。"""


TRIAL_ID='106_E01待機指値の逆方向永久取消と小利益停止12対照'
CONFIGS=[dict(id=f'E01_PENDING_{mode}{window}_{exit_id}',mode=mode,window_seconds=window,
    cancel_mode=1 if mode=='N' else 2,exit=exit_id,offset_atr=.2,
    profit_ticks=1 if exit_id=='P1L8' else 0,loss_ticks=8 if exit_id=='P1L8' else 0,
    初回={'TOPIX':5,'NK225':10},上限={'TOPIX':10,'NK225':20})
    for mode in ('N','P') for window in (10,30,60) for exit_id in ('GU','P1L8')]

