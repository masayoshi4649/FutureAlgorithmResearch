"""主入口と価格・素OFI・方向乱数を、結果に合わせず比較する。"""

import numpy as np
import trade_statistics as stats


def assess(index: dict) -> dict:
    """機能: 基礎成績、情報成分、実行感度、相手確認を別に判定する。

    引数: index (dict[str, dict])。返り値: 既知データに対する経済判定 (dict)。
    """
    symbols=('TOPIX','NK225')
    for identifier,summary in index.items():
        if any(not np.isfinite(summary['symbols'][symbol][field])
               for symbol in symbols for field in ('net_r','net_yen')):
            raise ValueError('非有限の比較収支を評価しません: '+identifier)
    cells={s:stats.basic(index['I00']['symbols'][s]) for s in symbols}
    component={}
    for symbol in symbols:
        value=index['I00']['symbols'][symbol]
        values=[index[f'I00_R{seed:02d}']['symbols'][symbol] for seed in range(64)]
        median=float(np.median([r['net_r'] for r in values]))
        comparisons={identifier:value['net_r']>index[identifier]['symbols'][symbol]['net_r']
            for identifier in ('I01','I03','I19','I04')}
        comparisons['乱数中央値']=value['net_r']>median
        component[symbol]=dict(合格=all(comparisons.values()),比較=comparisons,
            乱数合計R中央値=median,主以上合計Rの乱数数=sum(r['net_r']>=value['net_r'] for r in values),
            主以上円収支の乱数数=sum(r['net_yen']>=value['net_yen'] for r in values))
    execution={identifier:{s:stats.basic(index[identifier]['symbols'][s]) for s in symbols}
        for identifier in ('I00_D01','I00_D05','I00_D15','I00_OBS')}
    peer={}
    for identifier in ('I05','I06'):
        peer[identifier]={}
        for symbol in symbols:
            value=index[identifier]['symbols'][symbol]
            distribution=[index[f'{identifier}_R{seed:02d}']['symbols'][symbol]['net_r'] for seed in range(64)]
            peer[identifier][symbol]=dict(基礎=stats.basic(value),
                確認なし合計R超過=value['net_r']>index['I00']['symbols'][symbol]['net_r'],
                同機会乱数中央値超過=value['net_r']>float(np.median(distribution)))
    base_pass=all(v['合格'] for v in cells.values())
    added=all(v['合格'] for v in component.values())
    robust=all(v['合格'] for each in execution.values() for v in each.values())
    return dict(主仮説='I00',基礎候補=base_pass,板の比較付加価値=added,実行感度=robust,
        既知経済目安合格=base_pass and added and robust,基礎=cells,成分対照=component,
        実行感度詳細=execution,相手確認=peer,未知での有効性確認=False,全体目標達成=False,
        解釈='素OFI・共通価格・独立価格・逆・乱数との既知比較。市場に対する因果効果や正式有意確率ではない。')
