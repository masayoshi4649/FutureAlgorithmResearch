"""中値の最大順行が広い気配差で膨らんでいないかを固定入口で点検する。"""

from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent


def stats(values):
    """機能: 気配幅と順行幅の分布をまとめる。

    引数: values(list[float])。返り値: 件数・中央値・四分位75・最大(dict)。
    """
    if not values:
        return dict(件数=0,中央値=None,四分位75=None,最大=None)
    return dict(件数=len(values),中央値=float(np.median(values)),四分位75=float(np.quantile(values,.75)),最大=float(np.max(values)))


def main():
    """機能: 全281入口の中値頂点spreadと、返済可能気配の0.10%到達感度を記録する。

    引数: なし。返り値: なし(None)。元入口・主採点・幅・損益は変更しない。
    """
    packet=json.loads((HERE/'最大順行と入口採点.json').read_text(encoding='utf-8'))
    ready=pickle.loads((HERE.parent/'wave_v60/inputs.pkl').read_bytes())
    quotes=pickle.loads((HERE.parent/'wave_v60/quotes.pkl').read_bytes())
    rows=[]
    for row in packet['rows']:
        key=(row['session'],row['symbol']);q=quotes[key];tick=ready[key]['tick']
        start,index,side=row['decision_mid'],row['decision_i'],row['side']
        width=float((Decimal(str(start))*Decimal('0.001')/Decimal(str(tick))).to_integral_value(rounding=ROUND_CEILING)*Decimal(str(tick)))
        liquidation=q['bid'] if side==1 else q['ask']
        entry_quote=float(q['ask'][index] if side==1 else q['bid'][index])
        future=liquidation[index+1:]
        max_liquidation=float(future.max() if side==1 else future.min())
        conservative_mfe=max(0.,side*(max_liquidation-start))
        executable_mfe=max(0.,side*(max_liquidation-entry_quote))
        peak=row['extent']['最大順行行']
        spread=float(q['ask'][peak]-q['bid'][peak]) if peak is not None else None
        conservative_at_mid_peak=max(0.,side*(float(liquidation[peak])-start)) if peak is not None else None
        rows.append(dict(method=row['method'],session=row['session'],symbol=row['symbol'],decision_seq=row['decision_seq'],side=side,
            幅0_10=width,中値最大順行=row['extent']['最大順行'],中値最大時のspread=spread,
            中値最大時のspread呼値=spread/tick if spread is not None else None,
            中値最大時の返済可能順行幅=conservative_at_mid_peak,
            判断中値から返済可能気配の最大順行=conservative_mfe,
            判断時新規可能気配から返済可能気配の最大順行=executable_mfe,
            中値で0_10到達=row['extent']['到達']['0.10']['順行到達'],
            判断中値から返済可能気配で0_10到達=conservative_mfe>=width,
            判断時新規可能気配から返済可能気配で0_10到達=executable_mfe>=width))
    summary=[]
    for method in packet['methods']:
        for symbol in ('TOPIX','NK225'):
            selected=[r for r in rows if r['method']==method['id'] and r['symbol']==symbol]
            peaks=[r for r in selected if r['中値最大時のspread'] is not None]
            summary.append(dict(候補=method['number'],銘柄=symbol,新規数=len(selected),
                頂点spread価格幅=stats([r['中値最大時のspread'] for r in peaks]),
                頂点spread呼値=stats([r['中値最大時のspread呼値'] for r in peaks]),
                頂点spread一呼値超=sum(r['中値最大時のspread呼値']>1 for r in peaks),
                頂点spread二呼値超=sum(r['中値最大時のspread呼値']>2 for r in peaks),
                頂点spread五呼値超=sum(r['中値最大時のspread呼値']>5 for r in peaks),
                中値最大順行=stats([r['中値最大順行'] for r in selected]),
                判断中値から返済可能気配の最大順行=stats([r['判断中値から返済可能気配の最大順行'] for r in selected]),
                判断時新規可能気配から返済可能気配の最大順行=stats([r['判断時新規可能気配から返済可能気配の最大順行'] for r in selected]),
                中値0_10到達=sum(r['中値で0_10到達'] for r in selected),
                判断中値から返済気配0_10到達=sum(r['判断中値から返済可能気配で0_10到達'] for r in selected),
                判断時新規気配から返済気配0_10到達=sum(r['判断時新規可能気配から返済可能気配で0_10到達'] for r in selected),
                中値到達が返済気配で未到達=sum(r['中値で0_10到達'] and not r['判断中値から返済可能気配で0_10到達'] for r in selected)))
    full=dict(新規数=281,主評価の変更=False,幅='元の判断中値×0.10%、ラージ呼値切上げの同じ幅を3種類の価格評価に固定',
        全体頂点spread呼値=stats([r['中値最大時のspread呼値'] for r in rows if r['中値最大時のspread呼値'] is not None]),
        全体一呼値超=sum(r['中値最大時のspread呼値']>1 for r in rows if r['中値最大時のspread呼値'] is not None),
        全体二呼値超=sum(r['中値最大時のspread呼値']>2 for r in rows if r['中値最大時のspread呼値'] is not None),
        全体五呼値超=sum(r['中値最大時のspread呼値']>5 for r in rows if r['中値最大時のspread呼値'] is not None),
        summary=summary,rows=rows,
        留意点=['買い判断の将来bid、売り判断の将来askを返済可能気配として測定。中値ピークとは別の行で最大になることもある。',
        '判断中値を起点とする感度と、判断時点の新規可能気配を起点とする売買気配差込みの感度を区別する。',
        '判断時点の新規可能気配は実際の次行約定価格ではない。いずれも手数料未控除、最高値の事後採点であり実取引損益ではない。',
        'ラージ気配の読み取りによる小型商品の価格感度であり、ミニ/マイクロが同じ気配で約定する保証はない。'])
    (HERE/'限界値の気配感度検査.json').write_text(json.dumps(full,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:full[k] for k in ('全体頂点spread呼値','全体一呼値超','全体二呼値超','全体五呼値超','summary')},ensure_ascii=False))


if __name__=='__main__':
    main()
