"""R新規だけに公表取引更新代理の確認を加える12比較を固定する。"""

from copy import deepcopy

import catalog


TRIAL_ID='106_R取引更新代理の自己方向確認12対照'


def configs() -> list[dict]:
    """
    機能: 元AUTO_ER40の4条件へ、代理時計10/30/60秒確認を加えた12条件を返す。
    引数: なし。
    返り値: list[dict]は元数学を保持した設定。C・待機・保有出口は変更しない。
    """
    originals={c['id']:c for c in catalog.catalog()}
    result=[]
    for window in (10,30,60):
        for margin in (1,2):
            for mode in ('MARKET','LIMIT'):
                baseline=f'AUTO_ER40_M{margin}_{mode}'
                value=deepcopy(originals[baseline])
                value.update(id=f'R_TRADE_GATE_W{window}_M{margin}_{mode}',baseline_id=baseline,
                    trade_window_seconds=window,minimum_direction_votes=2,minimum_direction_balance=.25)
                result.append(value)
    assert len(result)==12
    return result
