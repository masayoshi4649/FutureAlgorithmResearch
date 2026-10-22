"""追加ナイトの売買を暗色5分足で表示し、既存方式の14場損益を別会計へ接続する。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00041_入口途中出口の分解検証'
sys.path.insert(0,str(HERE))
import replay_parts as replay

loader=importlib.util.spec_from_file_location('v47_chart_cash',HERE.parent/'wave_v45/chart_report.py')
chart=importlib.util.module_from_spec(loader);loader.loader.exec_module(chart)
METHODS={'A0__V000':'数量調整なし A0','G000_F25_N1__V000':'順行待ちなし・25%減量 C01',
 'G150_F25_N1__V000':'1.5ATR順行後・25%減量','G150_F50_N1__V000':'1.5ATR順行後・50%減量',
 'G000_F50_N1__V000':'順行待ちなし・50%減量'}


def tracking_points(ready: dict, curve: np.ndarray, orders: np.ndarray) -> list[int]:
    """機能: 注文行・毎分の高低・最大下落の両端を残して時価線を軽量化する。

    引数: ready(dict)、curve(np.ndarray)、orders(np.ndarray)。返り値: 表示行(list[int])。
    """
    times=ready['time_s'];equity=curve[:,0]
    buckets=np.floor((times-ready['start'])/60)
    boundaries=np.r_[0,np.flatnonzero(np.diff(buckets))+1,len(times)]
    selected={0,len(times)-1,*[int(o[0]) for o in orders]}
    for left,right in zip(boundaries[:-1],boundaries[1:]):
        if right<=left:continue
        selected.update((int(left),int(right-1),int(left+np.argmax(equity[left:right])),int(left+np.argmin(equity[left:right]))))
    full_drawdown=np.maximum.accumulate(equity)-equity
    trough=int(np.argmax(full_drawdown));peak=int(np.argmax(equity[:trough+1]))
    selected.update((trough,peak));result=sorted(selected);displayed=equity[result]
    assert abs(float(np.max(np.maximum.accumulate(displayed)-displayed))-float(np.max(full_drawdown)))<1e-8
    assert displayed.min()==equity.min() and displayed.max()==equity.max()
    return result


def main() -> None:
    """機能: 全台帳から図と累積損益を再構成して保存する。

    引数: なし。返り値: なし(None)。既存方式の事後変更や新規注文はしない。
    """
    assert replay.previous.read(HERE/'new_audits.json')['全合格']
    assert replay.previous.read(HERE/'new_signal_audit.json')['全合格']
    inputs=pickle.loads((HERE/'inputs.pkl').read_bytes())
    new_rows=replay.previous.read(HERE/'new_sessions.json')
    new_ledgers=replay.previous.read(HERE/'new_ledgers.json.gz')
    charts=[];combined=[];checks=[]
    periods={'全14セッション':sorted({k[0] for k in inputs}),
        '第1週 9月21〜25日':sorted({k[0] for k in inputs if k[0][:10]<='2026-09-25'}),
        '第2週 9月28〜29日':sorted({k[0] for k in inputs if k[0][:10]>='2026-09-28'})}
    for identifier,label in METHODS.items():
        rows=replay.previous.read(HERE.parent/'wave_v45/sessions'/(identifier+'.json.gz'))
        rows += [r for r in new_rows if r['id']==identifier]
        ledgers=replay.previous.read(HERE.parent/'wave_v45/ledgers'/(identifier+'.json.gz'))
        ledgers += [r for r in new_ledgers if r['id']==identifier]
        assert len(rows)==len(ledgers)==28
        series={}
        for ledger in ledgers:
            key=ledger['session'],ledger['symbol'];ready=inputs[key]
            curve,totals=chart.reconstruct(ready,ledger)
            row=next(r for r in rows if (r['session'],r['symbol'])==key)
            for k,v in totals.items(): assert abs(row[k]-v)<1e-6,(identifier,key,k)
            series[key]=curve[:,0]
            checks.append(dict(id=identifier,session=key[0],symbol=key[1],全行会計指紋一致=True))
            if key[0]!=replay.NEW_SESSION:continue
            orders=np.asarray(ledger['orders'],float)
            times=ready['time_s'];factor=ledger['config']['point_value']
            selected=tracking_points(ready,curve,orders)
            tracking=[[float(times[i]),float(curve[i,0]*factor),float(curve[i,2]),float(curve[i,3])] for i in selected]
            rendered_orders=[[float(times[int(o[0])]),*o.tolist()] for o in orders]
            charts.append(dict(id=identifier,symbol=key[1],name=label,candles=chart.candles(
                ROOT/'candle_5min'/key[1]/(key[0]+'.csv'),ready),orders=rendered_orders,tracking=tracking,
                totals=totals,start=ready['start'],end=float(times[-1]),cap=ledger['config']['audit_cap']))
        summary={period:{symbol:replay.previous.audit.statistics.period(rows,series,names,symbol,
            replay.previous.old.base.research.MULT[symbol]) for symbol in ('TOPIX','NK225')}
            for period,names in periods.items()}
        combined.append(dict(id=identifier,name=label,sessions=rows,periods=summary))
    replay.save(HERE/'combined_baselines.json',combined)
    replay.save(HERE/'chart_payload.json',charts)
    replay.save(HERE/'combined_baselines_audit.json',dict(全合格=True,方式数=5,全行会計数=len(checks),
        新ナイト図数=len(charts),結果=checks,時価差分の境界='21時直前の最終原本行。建玉をリセットしない。'))
    OUT.mkdir(parents=True,exist_ok=True)
    template=(HERE/'new_chart_template.html').read_text(encoding='utf-8')
    payload=json.dumps(charts,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</',r'<\/')
    (OUT/'追加ナイトの５分足と売買.html').write_text(template.replace('@@PAYLOAD@@',payload),encoding='utf-8')
    print('5方式×14場×2銘柄=140入力の別会計一致。追加ナイト10図を保存。',flush=True)


if __name__=='__main__':main()
