"""15秒最悪約定の悪化額を、発注時点の通過と直後の続伸・続落へ分解する。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REPORT = ROOT/'アルゴリズム調査/00046_E01の15秒最悪約定比較'
sys.path.insert(0,str(ROOT/'work/e01_worst15'))
import analyze as original


def group(rows: list[dict]) -> dict:
    """機能: 枚数と銘柄の価格尺度を補正した悪化量を集計する。

    引数: rows(list[dict])。返り値: 件数、金額、1枚当たり呼値、ATR比(dict)。
    """
    units = sum(r['quantity'] for r in rows)
    return dict(n=len(rows), units=units, adverse_yen=sum(r['adverse_yen'] for r in rows),
                adverse_rate=sum(r['adverse_yen']>0 for r in rows)/len(rows) if rows else None,
                per_unit_ticks=sum(r['adverse_ticks']*r['quantity'] for r in rows)/units if units else None,
                mean_order_atr=sum(r['adverse_atr'] for r in rows)/len(rows) if rows else None,
                immediate_yen=sum(r['immediate_yen'] for r in rows),
                following_yen=sum(r['following_yen'] for r in rows),
                median_range30_ticks=float(np.median([r['range30_ticks'] for r in rows])) if rows else None,
                mean_atr_ticks=float(np.mean([r['atr_ticks'] for r in rows])) if rows else None)


def category(row: dict, name: str) -> str:
    """機能: 過去30秒の動きとATRを、事前に定めた粗い区分へ分類する。

    引数: row(dict)、name(str)。返り値: 区分名(str)。
    """
    if name=='range30':
        return '4呼値以上' if row['range30_ticks']>=4 else '4呼値未満'
    if name=='momentum30':
        value=row['momentum30_side_ticks']
        return '参照不足' if value is None else ('発注方向へ2呼値以上' if value>=2 else ('反対へ2呼値以上' if value<=-2 else '2呼値未満'))
    if name=='updates30':
        return '価格変更10回以上' if row['price_changes30']>=10 else '価格変更10回未満'
    if name=='atr_half':
        return row['atr_half']
    raise ValueError(name)


def run() -> None:
    """機能: 現在の板取得を行わず、全469注文に直前特徴と悪化分解を付ける。

    引数: なし。返り値: なし(None)。特徴は判断行以前だけで計算する。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    data=original.read(REPORT/'計算結果.json')
    ready_all={}
    for path in original.INPUTS:
        with (ROOT/path).open('rb') as handle:
            ready_all.update(pickle.load(handle))
    rows=[]
    for account in data['sessions']:
        symbol,session=account['symbol'],account['session']
        ready=ready_all[session,symbol]
        times,prices=ready['time_s'],ready['last']
        tick=float(ready['tick'])
        factor=1000 if symbol=='TOPIX' else 10
        for order in account['orders']:
            d=order['decision_row']
            at=order['decision_time']
            side,q=order['side'],order['quantity']
            p=float(prices[d])
            atr=float(ready['atr'][d])
            assert np.isfinite(atr) and atr>0
            left=int(np.searchsorted(times,at-30,side='left'))
            past=prices[left:d+1]
            assert len(past)>0
            ref=int(np.searchsorted(times,at-30,side='right'))-1
            momentum=float(side*(p-prices[ref])/tick) if ref>=0 and at-30-times[ref]<=60 else None
            immediate=side*(p-order['ideal_price'])*q*factor
            following=side*(order['worst_price']-p)*q*factor
            assert following>=0
            assert abs(immediate+following-order['adverse_yen'])<1e-6
            item=dict(session=session,symbol=symbol,order=order['order'],reason=order['reason'],
                      side=side,quantity=q,is_entry=order['is_entry'],decision_jst=order['decision_jst'],
                      decision_row=d,price=p,ideal_price=order['ideal_price'],worst_price=order['worst_price'],
                      adverse_yen=order['adverse_yen'],adverse_ticks=order['adverse_yen']/(q*factor*tick),
                      immediate_yen=immediate,following_yen=following,atr=atr,atr_ticks=atr/tick,
                      adverse_atr=order['adverse_yen']/(q*factor*atr),
                      range30_ticks=float((np.max(past)-np.min(past))/tick),
                      momentum30_side_ticks=momentum,price_changes30=int(np.count_nonzero(np.diff(past))),
                      last_observation_gap=order['last_observation_gap'],
                      worst_elapsed=order['worst_time']-at,
                      source_to_fill_seconds=float(times[order['fill_row']]-times[order['source_row']]))
            curve={}
            for seconds in (0,1,3,5,10,15):
                right=int(np.searchsorted(times,at+seconds,side='right'))
                window=prices[d:right]
                w=float(np.max(window) if side>0 else np.min(window))
                curve[str(seconds)]=side*(w-order['ideal_price'])*q*factor
            assert curve['15']==item['adverse_yen']
            item['window_cost']=curve
            rows.append(item)
    summaries={}
    for symbol in ('TOPIX','NK225'):
        selected=[r for r in rows if r['symbol']==symbol]
        median=float(np.median([r['atr_ticks'] for r in selected]))
        for row in selected:
            row['atr_half']='ATR高い半分' if row['atr_ticks']>=median else 'ATR低い半分'
        groups={}
        for name in ('range30','momentum30','updates30','atr_half'):
            parts=defaultdict(list)
            for row in selected:
                parts[category(row,name)].append(row)
            groups[name]={label:group(part) for label,part in parts.items()}
        correlations={}
        frame=pd.DataFrame(selected)
        for col in ('atr_ticks','range30_ticks','momentum30_side_ticks','price_changes30'):
            ranked=frame[[col,'adverse_ticks']].dropna().rank(method='average')
            correlations[col]=float(ranked[col].corr(ranked['adverse_ticks']))
        within_reason={}
        for reason in sorted({r['reason'] for r in selected}):
            own=[r for r in selected if r['reason']==reason]
            within_reason[str(reason)]={label:group([r for r in own if category(r,'range30')==label]) for label in ('4呼値未満','4呼値以上')}
        session_pairs=[]
        for session in sorted({r['session'] for r in selected}):
            own=[r for r in selected if r['session']==session]
            low=[r for r in own if r['range30_ticks']<4]
            high=[r for r in own if r['range30_ticks']>=4]
            if len(low)>=2 and len(high)>=2:
                low_stats,high_stats=group(low),group(high)
                session_pairs.append(dict(session=session,low=low_stats,high=high_stats,
                                          high_worse=high_stats['per_unit_ticks']>low_stats['per_unit_ticks']))
        summary=group(selected)
        largest=max(selected,key=lambda r:r['adverse_yen'])
        robustness={}
        for label, subset in [('09/21〜09/25',[r for r in selected if r['session'][:10]<='2026-09-25']),
                              ('09/28〜10/02',[r for r in selected if r['session'][:10]>='2026-09-28']),
                              ('最大悪化1注文を除外',[r for r in selected if r is not largest])]:
            low=group([r for r in subset if r['range30_ticks']<4])
            high=group([r for r in subset if r['range30_ticks']>=4])
            robustness[label]=dict(low=low,high=high,ratio=high['per_unit_ticks']/low['per_unit_ticks'])
        summary.update(atr_split_ticks=median,groups=groups,correlations=correlations,
                       range_by_reason=within_reason,range_within_sessions=session_pairs,
                       range_robustness=robustness,
                       window_cost={str(s):sum(r['window_cost'][str(s)] for r in selected) for s in (0,1,3,5,10,15)},
                       top_following=sorted(selected,key=lambda r:r['following_yen'],reverse=True)[:10])
        assert summary['adverse_yen']==data['totals'][symbol]['adverse_yen']
        summaries[symbol]=summary
    result=dict(対象注文数=len(rows),現在セッション追加取得数=0,原本変更=False,
                条件='価格特徴は判断行以前の30秒。ATR高低の境界は全注文中央値による事後の記述区分。',
                分解='全悪化＝判断行の観測価格と理想価格の差＋判断後の同方向の最悪変動。0秒窓は同一秒の後続行を含む。',
                summary=summaries,orders=rows,
                source_sha256=hashlib.sha256((REPORT/'計算結果.json').read_bytes()).hexdigest())
    (HERE/'価格特徴分析.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({s:{k:v for k,v in r.items() if k not in ('top_following','range_by_reason','range_within_sessions')}
                      for s,r in summaries.items()},ensure_ascii=False,indent=2))


if __name__=='__main__':
    run()
