"""180条件を保存済み一週間に適用し、金額・枚数・全玉評価を別々に集計する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

import catalog
import engine
import signals

OUT=Path(__file__).resolve().parent
SESSIONS=[f'2026-09-{day:02d}_{part}' for day in range(21,26) for part in ['Day','Night']]
MULT={'NK225':1000.,'TOPIX':10000.}


def clean(value: object) -> object:
    """機能: NumPy値と無限値をJSONの有限値・欠損へ変換する。

    引数: value (object)。返り値: JSON互換値 (object)。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,(np.integer,)):return int(value)
    if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
    return value


def save(name: str,value: object) -> None:
    """機能: 今回専用ディレクトリへ日本語JSONを保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    (OUT/name).write_text(json.dumps(clean(value),ensure_ascii=False,indent=2),encoding='utf-8')


def quotient(a: float,b: float) -> float | None:
    """機能: 損失なしを無限の優秀さへ置換せず比率を返す。

    引数: a/b (float)。返り値: 比率またはNone (float|None)。
    """
    return float(a/b) if b>1e-8 else None


def summarize(result: dict,config: dict,symbol: str,session: str) -> dict:
    """機能: 全返済脚の金額・枚数と、組合算損益を分けて集計する。

    引数: result/config (dict)、symbol/session (str)。返り値: 一区間の指標 (dict)。
    """
    trades,cycles,stats=result['trades'],result['cycles'],result['stats']
    value=trades[:,10]*MULT[symbol];qty=trades[:,3]
    win=value>1e-6;loss=value< -1e-6;flat=~(win|loss)
    gp=value[win].sum();gl=-value[loss].sum();wq=qty[win].sum();lq=qty[loss].sum()
    cv=cycles[:,3]*MULT[symbol];cw=cv>1e-6;cl=cv< -1e-6
    assert stats[9]==0,'セッション末尾に未返済玉があります'
    np.testing.assert_allclose(value.sum(),stats[0]*MULT[symbol],atol=.01)
    np.testing.assert_allclose(cv.sum(),value.sum(),atol=.01)
    assert stats[2]<=100 and stats[3]<=100 and stats[6]<1e-5
    return dict(method_id=config['id'],symbol=symbol,session=session,
                gross_profit_yen=gp,gross_loss_yen=gl,net_yen=value.sum(),
                profit_units=int(wq),loss_units=int(lq),zero_units=int(qty[flat].sum()),unit_balance=int(wq-lq),
                money_ratio=quotient(gp,gl),unit_ratio=quotient(wq,lq),
                avg_profit_per_unit=quotient(gp,wq),avg_loss_per_unit=quotient(gl,lq),
                unit_payoff=quotient(gp/wq,gl/lq) if wq and lq else None,
                cycle_profit_yen=cv[cw].sum(),cycle_loss_yen=-cv[cl].sum(),
                cycle_wins=int(cw.sum()),cycle_losses=int(cl.sum()),cycles=len(cycles),
                net_r=float(np.sum(cycles[:,3]/cycles[:,4])) if len(cycles) else 0.,
                drawdown_yen=stats[1]*MULT[symbol],min_equity_yen=stats[7]*MULT[symbol],
                max_equity_yen=stats[8]*MULT[symbol],max_long=int(stats[2]),max_short=int(stats[3]),
                max_gross=int(stats[4]),max_net=int(stats[5]),reversals=int(stats[10]),
                closed_units=int(qty.sum()),order_count=len(result['orders']),cash_error=stats[6],
                cover_profit_yen=value[(trades[:,8]==1)&win].sum(),
                cover_loss_yen=-value[(trades[:,8]==1)&loss].sum())


def aggregate(rows: list[dict]) -> dict:
    """機能: 任意の連続区間を合算し、週を通した時価最大下落を求める。

    引数: rows (list[dict])。返り値: 期間指標 (dict)。
    """
    fields=['gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units',
            'unit_balance','cycle_profit_yen','cycle_loss_yen','cycle_wins','cycle_losses','cycles',
            'net_r','closed_units','order_count','reversals','cover_profit_yen','cover_loss_yen']
    out={key:sum(r[key] for r in rows) for key in fields}
    out.update(method_id=rows[0]['method_id'],symbol=rows[0]['symbol'],session_count=len(rows),
               positive_sessions=sum(r['net_yen']>0 for r in rows),active_sessions=sum(r['cycles']>0 for r in rows))
    gp,gl,wq,lq=[out[k] for k in ['gross_profit_yen','gross_loss_yen','profit_units','loss_units']]
    out.update(money_ratio=quotient(gp,gl),unit_ratio=quotient(wq,lq),
               avg_profit_per_unit=quotient(gp,wq),avg_loss_per_unit=quotient(gl,lq),
               unit_payoff=quotient(gp/wq,gl/lq) if wq and lq else None)
    cgp,cgl,cw,cl=[out[k] for k in ['cycle_profit_yen','cycle_loss_yen','cycle_wins','cycle_losses']]
    out.update(cycle_pf=quotient(cgp,cgl),cycle_payoff=quotient(cgp/cw,cgl/cl) if cw and cl else None)
    net=0.;peak=0.;dd=0.
    for row in rows:
        dd=max(dd,row['drawdown_yen'],peak-net-row['min_equity_yen'])
        peak=max(peak,net+row['max_equity_yen']);net+=row['net_yen']
    out['drawdown_yen']=dd
    for k in ['max_long','max_short','max_gross','max_net']:
        out[k]=max(row[k] for row in rows)
    return out


def choose(candidates: list[list[dict]]) -> tuple[dict,bool]:
    """機能: 過去の組損益だけで候補を選ぶ。利益脚だけの比率で順位付けしない。

    引数: candidates (list[list[dict]])。返り値: 採用期間指標と資格 (tuple[dict,bool])。
    """
    ranked=[]
    for rows in candidates:
        a=aggregate(rows);pf=a['cycle_pf'] or 0.;pay=a['cycle_payoff'] or 0.
        eligible=a['cycles']>=6 and a['cycle_wins']>=2 and a['cycle_losses']>=2 and pf>1 and pay>1
        eligible=eligible and a['active_sessions']>=min(3,len(rows)) and a['positive_sessions']>len(rows)/2
        eligible=eligible and a['net_r']-max(r['net_r'] for r in rows)>0
        robust=[]
        for j in range(len(rows)):
            b=aggregate(rows[:j]+rows[j+1:]);robust.append(min(b['cycle_pf'] or 0.,b['cycle_payoff'] or 0.,5.))
        ranked.append((eligible,min(robust),pf,pay,a['method_id'],a))
    ranked.sort(key=lambda x:(-int(x[0]),-x[1],-x[2],-x[3],x[4]))
    return ranked[0][-1],ranked[0][0]


def main() -> None:
    """機能: 条件と入力ハッシュを固定し、保存データだけで全比較・時間順選択を行う。

    引数: なし。返り値: なし (None)。取引発注・現在API取得なし。
    """
    configs=catalog.configs();inputs=signals.load_inputs()
    states=pickle.loads((OUT/'主方向状態.pkl').read_bytes())
    hashes={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest()
            for name in ['engine.py','catalog.py','signals.py','主方向状態.pkl','research.py']}
    save('探索前の固定記録.json',dict(条件数=len(configs),全データ既読=True,現在API取得回数=0,
         買い上限=100,売り上限=100,総上限=200,初期数量=10,ハッシュ=hashes))
    save('全条件一覧.json',configs)
    rows=[];blocks={};started=time.time()
    for j,cfg in enumerate(configs):
        for session in SESSIONS:
            for symbol in ['NK225','TOPIX']:
                key=(session,symbol);direction=np.ascontiguousarray(states[key][cfg['signal']]*cfg['sign'],dtype=np.int8)
                result=engine.run(inputs[key],direction,cfg)
                row=summarize(result,cfg,symbol,session);rows.append(row)
                blocks[(cfg['id'],session,symbol)]=dict(trades=result['trades'],cycles=result['cycles'])
        if (j+1)%10==0:print(f'{j+1}/{len(configs)}条件完了、{time.time()-started:.1f}秒',flush=True)
    save('セッション集計.json',rows);pd.DataFrame(rows).to_csv(OUT/'セッション集計.csv',index=False,encoding='utf-8-sig')
    with (OUT/'全返済と組.pkl').open('wb') as stream:pickle.dump(blocks,stream,pickle.HIGHEST_PROTOCOL)
    grouped={(c['id'],symbol):[r for r in rows if r['method_id']==c['id'] and r['symbol']==symbol]
             for c in configs for symbol in ['NK225','TOPIX']}
    weekly=[aggregate(v) for v in grouped.values()];save('週合計.json',weekly)
    pd.DataFrame(weekly).to_csv(OUT/'週合計.csv',index=False,encoding='utf-8-sig')
    walk=[];default={}
    for count in range(3,10):
        for symbol in ['NK225','TOPIX']:
            selected,eligible=choose([grouped[(c['id'],symbol)][:count] for c in configs])
            chosen=selected['method_id'];future=grouped[(chosen,symbol)][count]
            manager=next(c for c in configs if c['id']==chosen)
            baseline=f'{manager["signal"]}_{"順" if manager["sign"]==1 else "逆"}_A00'
            control=grouped[(baseline,symbol)][count]
            walk.append(dict(symbol=symbol,train_sessions=count,chosen=chosen,eligible=eligible,
                             next_session=SESSIONS[count],result=future,baseline=control))
            if count==9:default[symbol]=chosen
    save('時間順比較.json',walk)
    save('表示設定.json',dict(default=default,全データ既読=True,条件数=len(configs),
         配置='00012_状態切替と柔軟な建玉管理',枚数='片方向100仮想単位、返済累計枚数と同時保有枚数を区別',
         金額='元データのラージ価格倍率による参考円。換算係数で数量単位の額だけを変更可能。',
         注文順序='前行の注文から、観測区間で先に到達する一件を約定。再設定は次行から有効。'))
    save('探索完了記録.json',dict(条件数=len(configs),セッションセル数=len(rows),
         経過秒=time.time()-started,最大買い=max(r['max_long'] for r in rows),最大売り=max(r['max_short'] for r in rows),
         最大現金勘定誤差=max(r['cash_error'] for r in rows),全セル返済=True,現在API取得回数=0,
         入力コード不変=all(hashlib.sha256((OUT/k).read_bytes()).hexdigest()==v for k,v in hashes.items())))
    print(json.dumps(dict(表示候補=default,条件数=len(configs),セル数=len(rows)),ensure_ascii=False))


if __name__=='__main__':main()
