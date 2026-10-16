"""公表取引更新代理の確認をR/C/両方の入口へ分けた36比較を固定する。"""

from copy import deepcopy

import catalog


TRIAL_ID='106_取引更新代理の入口範囲R_C_BOTH36対照'


def configs() -> list[dict]:
    """
    機能: 元AUTO_ER40の4条件へ、代理時計10/30/60秒と適用範囲3種類の36条件を返す。
    引数: なし。
    返り値: list[dict]は元数学を保持した設定。各指定以外の入口・待機・保有出口は変更しない。
    """
    originals={c['id']:c for c in catalog.catalog()}
    result=[]
    for scope in ('R','C','BOTH'):
        for window in (10,30,60):
            for margin in (1,2):
                for mode in ('MARKET','LIMIT'):
                    baseline=f'AUTO_ER40_M{margin}_{mode}'
                    value=deepcopy(originals[baseline])
                    value.update(id=f'TRADE_GATE_{scope}_W{window}_M{margin}_{mode}',baseline_id=baseline,gate_scope=scope,
                        trade_window_seconds=window,minimum_direction_votes=2,minimum_direction_balance=.25)
                    result.append(value)
    assert len(result)==36
    return result
