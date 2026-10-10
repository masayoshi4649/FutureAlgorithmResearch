"""各脚の保有区間から全原本行の時価評価と03:01以降の差分を独立に監査する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from audit_results import close,digest

WORK=Path(__file__).resolve().parent
BOUNDARY=pd.Timestamp('2026-09-25T03:01:00+09:00').timestamp()
MULTIPLIERS={'NK225':1000.,'TOPIX':10000.}


def account(prices: np.ndarray, raw: np.ndarray) -> tuple:
    """機能: 各脚の生存期間を直接足し合わせ、円換算前の全行評価を計算する。

    引数: prices/raw (ndarray)。返り値: 評価、確定、総枚数、最大下落 (tuple)。
    実行器の現金差分会計・集計関数は使用しない。
    """
    prices=pd.Series(prices).ffill().fillna(0.).to_numpy()
    equity=np.zeros(len(prices));closed=np.zeros(len(prices));gross=np.zeros(len(prices))
    for leg in raw:
        start,end,side=int(leg[5]),int(leg[6]),int(leg[2])
        stop=end if leg[14] else len(prices)
        equity[start:stop]+=side*(prices[start:stop]-leg[8]);gross[start:stop]+=1
        if leg[14]:
            pnl=side*(leg[9]-leg[8])
            equity[end:]+=pnl;closed[end:]+=pnl
    drawdown=np.maximum.accumulate(np.r_[0.,equity])[1:]-equity
    return equity,closed,gross,float(drawdown.max())


def main() -> None:
    """機能: 保存済み明細と価格を読み、全行評価・境界・全返済を照合する。

    引数: --prefix/--extra (str)、--holdout (bool)。返り値: なし (None)。
    最終保留の入力は固定記録がある場合にしか読み込まない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--prefix',required=True);parser.add_argument('--extra',required=True)
    parser.add_argument('--holdout',action='store_true')
    args=parser.parse_args()
    with (WORK/'入力_development.pkl').open('rb') as stream: ready=pickle.load(stream)
    if args.holdout:
        assert (WORK/'最終保留_凍結記録.json').exists(),'最終保留の固定前です'
        with (WORK/'入力_holdout.pkl').open('rb') as stream: ready.update(pickle.load(stream))
    with (WORK/f'{args.prefix}_数値.pkl').open('rb') as stream: blocks=pickle.load(stream)
    frame=pd.read_csv(WORK/f'{args.prefix}_セッション集計.csv')
    extra=pd.read_csv(WORK/f'{args.extra}_セッション集計.csv')
    curves=json.loads((WORK/f'{args.prefix}_資産曲線.json').read_text(encoding='utf-8'))
    checks=[]
    periods={}
    for (method,session,symbol),raw in blocks.items():
        tape=ready[(session,symbol)];multiplier=MULTIPLIERS[symbol]
        row=frame.loc[(frame['方式']==method)&(frame['セッション']==session)&(frame['銘柄']==symbol)].iloc[0]
        equity,closed,gross,dd=account(tape['last'],raw)
        close(row['net_yen'],equity[-1]*multiplier,method+' 全評価')
        close(row['closed_net_yen'],closed[-1]*multiplier,method+' 確定')
        close(row['open_yen'],(equity[-1]-closed[-1])*multiplier,method+' 含み')
        close(row['max_drawdown_yen'],dd*multiplier,method+' 全行DD')
        if '最小評価損益円' in row:
            close(row['最小評価損益円'],min(0.,equity.min()*multiplier),method+' 全行最小評価')
            close(row['最大評価損益円'],max(0.,equity.max()*multiplier),method+' 全行最大評価')
        state=periods.setdefault((method,symbol),dict(cash=0.,peak=0.,dd=0.,sessions=[]))
        global_values=equity*multiplier+state['cash']
        global_peaks=np.maximum.accumulate(np.r_[state['peak'],global_values])[1:]
        state['dd']=max(state['dd'],float((global_peaks-global_values).max()))
        state['peak']=float(global_peaks[-1]);state['cash']=float(global_values[-1]);state['sessions'].append(session)
        assert not len(raw) or np.all(raw[:,14]==1),(method,session,'完全sessionに未返済')
        assert gross[-1]==0,(method,session,'場またぎ')
        curve=np.asarray(curves[f'{method}|{session}|{symbol}'])
        curve_checks=0
        for point in curve:
            position=int(np.searchsorted(tape['seq'],point[1],side='left'))
            assert position<len(tape['seq']) and tape['seq'][position]==point[1],(method,'図の原本番号')
            close(point[2],equity[position]*multiplier,method+' 図全評価')
            close(point[5],closed[position]*multiplier,method+' 図確定')
            close(point[4],gross[position],method+' 図枚数')
            curve_checks+=3
        boundary_result=None
        if session=='2026-09-24_Night':
            before=int(np.searchsorted(tape['time_s'],BOUNDARY,side='left'))-1
            base=equity[before]*multiplier
            suffix=equity[before+1:]*multiplier-base
            suffix_dd=np.maximum.accumulate(np.r_[0.,suffix])[1:]-suffix
            er=extra.loc[(extra['方式']==method)&(extra['セッション']==session)&(extra['銘柄']==symbol)].iloc[0]
            close(er['baseline_equity_yen'],base,method+' 境界評価')
            close(er['net_yen'],suffix[-1],method+' 境界後増分')
            close(er['max_drawdown_yen'],float(suffix_dd.max()),method+' 境界後DD')
            if '最小評価損益円' in er:
                close(er['最小評価損益円'],min(0.,suffix.min()),method+' 境界後最小評価')
                close(er['最大評価損益円'],max(0.,suffix.max()),method+' 境界後最大評価')
            boundary_result=dict(前回時価評価円=base,追加収支円=float(suffix[-1]),追加最大下落円=float(suffix_dd.max()))
        checks.append(dict(方式=method,銘柄=symbol,セッション=session,原本行数=len(tape['last']),
            脚数=len(raw),図の数値検査数=curve_checks,全返済=True,追加境界=boundary_result))
    weekly_path=WORK/'週合計指標.json'
    if args.holdout and weekly_path.exists():
        weekly=json.loads(weekly_path.read_text(encoding='utf-8'))
        for row in weekly:
            key=(row['method'],row['symbol'])
            if key not in periods: continue
            close(row['指標']['全10区間']['期間全体の最大下落円'],periods[key]['dd'],str(key)+' 週全体全行DD')
    output=dict(接頭辞=args.prefix,検査セル数=len(checks),全原本行数=sum(c['原本行数'] for c in checks),
        全脚数=sum(c['脚数'] for c in checks),図検査数=sum(c['図の数値検査数'] for c in checks),
        境界検査数=sum(c['追加境界'] is not None for c in checks),セル=checks,
        期間全体={m+'|'+s:p for (m,s),p in periods.items()},
        入力ハッシュ={name:digest(WORK/name) for name in [f'{args.prefix}_数値.pkl',f'{args.prefix}_セッション集計.csv',f'{args.extra}_セッション集計.csv']})
    (WORK/f'{args.prefix}_全原本時価の独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k not in ['セル','入力ハッシュ','期間全体']},ensure_ascii=False))


if __name__=='__main__':
    main()
