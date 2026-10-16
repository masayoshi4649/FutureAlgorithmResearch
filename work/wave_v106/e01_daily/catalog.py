"""旧E01の小利益場内停止を、結果前に12条件へ固定する。"""


BASELINE = 'L_D20_BBO'
TRIAL_ID = '106_E01の小利益目標とUID別場内停止12対照'
CONFIGS = [dict(id=f'E01_DAILY_P{profit}_L{loss if loss is not None else "U"}',
    baseline=BASELINE, profit_ticks=profit, loss_ticks=loss,
    初回枚数={'TOPIX': 5, 'NK225': 10}, 片方向上限={'TOPIX': 10, 'NK225': 20})
    for profit in (1, 2, 4) for loss in (4, 8, 16, None)]

