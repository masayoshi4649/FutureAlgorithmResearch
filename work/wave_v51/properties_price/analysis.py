"""過去だけの状態分類と未来の価格経路を分離して記述する。売買は生成しない。"""
from __future__ import annotations
import csv
from datetime import datetime,timezone,timedelta
import importlib.util
import json
import hashlib
from pathlib import Path
import socket
import sys
from collections import Counter
import numpy as np
import pandas as pd
from design import HERE,freeze

ROOT=HERE.parents[2]
STATES=['両市場逆方向','同方向高効率','自市場低効率','自市場高効率','中間']
JST=timezone(timedelta(hours=9))


def save(name: str,value: object) -> None:
    """機能: 今回の記述分析領域へ有限JSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')


def deny(*args,**kwargs) -> None:
    """機能: 保存資料による性質分析中のネットワーク接続を拒否する。

    引数: 任意の引数。返り値: なし(None)、常に例外。
    """
    raise RuntimeError('性質の記述には保存済みデータだけを使用します')


def load() -> dict:
    """機能: 既存23場の公開済み価格・ATR入力を読む。

    引数: なし。返り値: 入力(dict)。
    """
    spec=importlib.util.spec_from_file_location('価格性質_保存入力参照',HERE.parent/'overlay/research.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    inputs,_=module.load();return inputs


def reversals(values: np.ndarray) -> float:
    """機能: ゼロ変化を除いた直近1分変化の符号転換回数を数える。

    引数: values(ndarray)。返り値: 反転回数(float)。
    """
    signs=np.sign(values);signs=signs[signs!=0]
    return float(np.count_nonzero(signs[1:]!=signs[:-1]))


def bar_model(key: tuple,table: pd.DataFrame|None=None) -> dict:
    """機能: 公開済み確定足だけで、連続30分の価格過程を計算する。

    引数: key(tuple)、table(DataFrame|None)。返り値: 公開時刻・指標(dict)。
    """
    if table is None:table=pd.read_csv(ROOT/'candle_1min'/key[1]/(key[0]+'.csv'))
    table=table.loc[table.closed.astype(str).str.lower().eq('true')].reset_index(drop=True)
    t=pd.to_datetime(table.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
    close=table.close.astype(float);delta=close.diff()
    distance=delta.abs().rolling(30,min_periods=30).sum()
    pure=close.diff(30);er=pure.abs()/distance.replace(0,np.nan)
    er=er.mask(distance==0,0.)
    continuous=pd.Series(t).diff(30).eq(1800).to_numpy()
    return dict(t=t,close=close.to_numpy(),delta30=pure.to_numpy(),delta5=close.diff(5).to_numpy(),
                er=er.to_numpy(),ema=close.ewm(span=30,adjust=False,min_periods=30).mean().to_numpy(),
                flips=delta.rolling(30,min_periods=30).apply(reversals,raw=True).to_numpy(),valid=continuous)


def current_state(key: tuple,now: float,inputs: dict,models: dict) -> tuple:
    """機能: 指定観測時刻までに公開された値だけで固定五状態を判定する。

    引数: key(tuple)、now(float)、inputs/models(dict)。返り値: 状態辞書又は除外理由(tuple)。
    """
    peer=(key[0],'TOPIX' if key[1]=='NK225' else 'NK225');found=[]
    for k in (key,peer):
        ready=inputs[k];m=models[k]
        tick=int(np.searchsorted(ready['time_s'],now,side='left')-1)
        bar=int(np.searchsorted(m['t'],now,side='right')-1)
        if tick<0 or bar<0:return None,'過去不足'
        if now-ready['time_s'][tick]>60:return None,'価格古い'
        if now-m['t'][bar]>60:return None,'公開足古い'
        if bar<30:return None,'開始後の足数不足'
        if not m['valid'][bar]:return None,'連続30分不足'
        atr=float(ready['atr'][tick]);price=float(ready['last'][tick])
        if not np.isfinite(atr) or atr<=0 or not np.isfinite(price) or price<=0:return None,'価格ATR不足'
        er=float(m['er'][bar]);ret=float(m['delta30'][bar]/atr)
        if not np.isfinite(er):return None,'効率比不足'
        side=1 if ret>.5 else -1 if ret<-.5 else 0
        found.append(dict(price=price,atr=atr,er=er,ret=ret,side=side,ema=float(m['ema'][bar]),
                          deviation=(price-float(m['ema'][bar]))/atr,flips=int(m['flips'][bar]),
                          ret5=float(m['delta5'][bar]/atr),seq=int(ready['seq'][tick]),bar_public=float(m['t'][bar])))
    own,other=found
    if own['side']*other['side']==-1:state='両市場逆方向'
    elif own['side']==other['side'] and own['side']!=0 and min(own['er'],other['er'])>=.3:state='同方向高効率'
    elif own['er']<=.2:state='自市場低効率'
    elif own['er']>=.3:state='自市場高効率'
    else:state='中間'
    result=dict(session=key[0],symbol=key[1],part='Day' if key[0].endswith('Day') else 'Night',time_s=now,
                time=datetime.fromtimestamp(now,JST).isoformat(),state=state,
                reference_seq=own['seq'],price=own['price'],atr=own['atr'],er=own['er'],peer_er=other['er'],
                ret30_atr=own['ret'],peer_ret30_atr=other['ret'],direction=own['side'],peer_direction=other['side'],
                direction_changes=own['flips'],ema_deviation_atr=own['deviation'],ret5_atr=own['ret5'],
                public_time=own['bar_public'],peer_public_time=other['bar_public'],
                nonoverlap_60=int((now-inputs[key]['start'])%3600==0))
    return result,''


def future_labels(observation: dict,ready: dict,horizon: int) -> list[dict]:
    """機能: 現在状態を変更せず、将来経路だけから二つの評価方向の結果を記述する。

    引数: observation/ready(dict)、horizon(int:分)。返り値: 未来ラベル(list[dict])。
    """
    now=observation['time_s'];end=now+horizon*60
    if end>ready['limit']:return []
    left=int(np.searchsorted(ready['time_s'],now,side='left'));right=int(np.searchsorted(ready['time_s'],end,side='left'))
    if right<=left or end-ready['time_s'][right-1]>60:return []
    path=ready['last'][left:right];path=path[np.isfinite(path)&(path>0)]
    if len(path)==0:return []
    move=(path-observation['price'])/observation['atr'];result=[]
    directions=[('過去30分方向',int(np.sign(observation['ret30_atr']))),('平均線回帰方向',-int(np.sign(observation['ema_deviation_atr'])))]
    for hypothesis,direction in directions:
        if direction==0:continue
        progress=move*direction;up=np.flatnonzero(progress>=1.5);down=np.flatnonzero(progress<=-.75)
        first_up=int(up[0]) if len(up) else len(progress);first_down=int(down[0]) if len(down) else len(progress)
        touch='順行先着' if first_up<first_down else '逆行先着' if first_down<first_up else '未到達'
        finish=float(progress[-1]);record=dict(observation,horizon=horizon,hypothesis=hypothesis,evaluation_direction=direction,
            terminal_atr=finish,continue_direction=int(finish>0),reverse_direction=int(finish<0),flat=int(finish==0),
            mfe_atr=max(0.,float(np.max(progress))),mae_atr=max(0.,float(-np.min(progress))),
            barrier=touch,hit_win=int(touch=='順行先着'),hit_loss=int(touch=='逆行先着'),untouched=int(touch=='未到達'))
        result.append(record)
    return result


def describe(frame: pd.DataFrame) -> dict:
    """機能: 観測点比率とセッション均等分布を併記する。

    引数: frame(DataFrame)。返り値: 集計(dict)。
    """
    n=len(frame)
    if not n:return dict(n=0,sessions=0)
    metrics=['continue_direction','reverse_direction','flat','mfe_atr','mae_atr','hit_win','hit_loss','untouched','terminal_atr','direction_changes','ema_deviation_atr']
    output=dict(n=n,sessions=int(frame.session.nunique()))
    for metric in metrics:output[metric]=float(frame[metric].mean())
    output['mfe_median']=float(frame.mfe_atr.median());output['mae_median']=float(frame.mae_atr.median())
    output['hit_win_if_hit']=float(frame.hit_win.sum()/(frame.hit_win.sum()+frame.hit_loss.sum())) if frame.hit_win.sum()+frame.hit_loss.sum() else None
    grouped=frame.groupby('session')[['continue_direction','hit_win','mfe_atr','mae_atr']].mean()
    output['session_distribution']={metric:dict(mean=float(grouped[metric].mean()),median=float(grouped[metric].median()),
        q25=float(grouped[metric].quantile(.25)),q75=float(grouped[metric].quantile(.75)),min=float(grouped[metric].min()),max=float(grouped[metric].max())) for metric in grouped.columns}
    return output


def causal_audit(inputs: dict,models: dict,observations: list[dict]) -> dict:
    """機能: 未来の足を改変・切断しても現在分類が完全一致することを検査する。

    引数: inputs/models(dict)、observations(list[dict])。返り値: 検査結果(dict)。
    """
    checks=[]
    for session in ('2026-09-21_Day','2026-10-05_Night','2026-10-06_Day'):
        own_rows=[o for o in observations if o['session']==session and o['symbol']=='TOPIX']
        if not own_rows:continue
        for sample in (own_rows[len(own_rows)//3],own_rows[2*len(own_rows)//3]):
            now=sample['time_s'];changed={};prefix={}
            for symbol in ('TOPIX','NK225'):
                key=session,symbol;table=pd.read_csv(ROOT/'candle_1min'/symbol/(session+'.csv'))
                published=pd.to_datetime(table.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
                altered=table.copy();altered.loc[published>now,'close']+=10000
                changed[key]=bar_model(key,altered);prefix[key]=bar_model(key,table.loc[published<=now].copy())
            for symbol in ('TOPIX','NK225'):
                key=session,symbol
                original=current_state(key,now,inputs,models)
                assert original==current_state(key,now,inputs,changed)
                assert original==current_state(key,now,inputs,prefix)
                checks.append(dict(session=session,symbol=symbol,time_s=now,現在分類完全一致=True))
    return dict(全合格=True,検査=checks,将来使用箇所='future_labelsと遷移先ラベルのみ',ATR='過去確定公開キャッシュの既存監査を継承')


def main() -> None:
    """機能: 固定状態・将来経路・状態遷移を記述し、条件は最適化しない。

    引数: なし。返り値: なし(None)。
    """
    freeze();socket.socket.connect=deny;socket.create_connection=deny
    transition_design=dict(追加目的='現在の状態分類が将来も維持されるかを検証する',評価分=[15,30],
                           閾値変更=False,将来状態を現在分類に使用=False,補足='15分先の30分窓は現在窓と15分重複するので、持続だけを独立な予測力としない。')
    path=HERE/'状態遷移の追加固定.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf8'))==transition_design
    else:save('状態遷移の追加固定.json',transition_design)
    inputs=load();models={k:bar_model(k) for k in inputs};names=sorted({k[0] for k in inputs})
    observations=[];labels=[];exclusions=Counter();transitions=[];excluded=[]
    for key,ready in sorted(inputs.items()):
        for now in np.arange(ready['start']+300,ready['limit']+1,300):
            current,reason=current_state(key,float(now),inputs,models)
            if current is None:
                exclusions[reason]+=1
                excluded.append(dict(session=key[0],symbol=key[1],time_s=float(now),reason=reason))
                continue
            observations.append(current)
            for horizon in (15,30,60):labels.extend(future_labels(current,ready,horizon))
            for ahead in (15,30):
                future=now+ahead*60
                if future>ready['limit']:continue
                other,_=current_state(key,float(future),inputs,models)
                if other is not None:transitions.append(dict(session=key[0],symbol=key[1],part=current['part'],time_s=float(now),
                    current=current['state'],future=other['state'],ahead=ahead,nonoverlap_60=current['nonoverlap_60'],
                    current_direction=current['direction'],future_direction=other['direction']))
    data=pd.DataFrame(labels);obs=pd.DataFrame(observations);trans=pd.DataFrame(transitions)
    data.to_csv(HERE/'観測点と将来経路.csv',index=False,encoding='utf-8-sig')
    obs.to_csv(HERE/'現在状態.csv',index=False,encoding='utf-8-sig')
    trans.to_csv(HERE/'状態遷移観測.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(excluded).to_csv(HERE/'除外観測点.csv',index=False,encoding='utf-8-sig')
    periods={'全23':names,'先頭10':names[:10],'次9':names[10:19],'既知4':names[19:]};summaries=[];transition_summary=[]
    for period,selected in periods.items():
        for sampling in ('5分全観測','60分非重複'):
            chosen=data.loc[data.session.isin(selected)]
            tc=trans.loc[trans.session.isin(selected)]
            if sampling=='60分非重複':chosen=chosen.loc[chosen.nonoverlap_60==1];tc=tc.loc[tc.nonoverlap_60==1]
            for part in ('全体','Day','Night'):
                pf=chosen if part=='全体' else chosen.loc[chosen.part==part]
                tf=tc if part=='全体' else tc.loc[tc.part==part]
                for symbol in ('TOPIX','NK225'):
                    sf=pf.loc[pf.symbol==symbol];st=tf.loc[tf.symbol==symbol]
                    for state in ['全状態']+STATES:
                        gf=sf if state=='全状態' else sf.loc[sf.state==state]
                        for hypothesis in ('過去30分方向','平均線回帰方向'):
                            for horizon in (15,30,60):
                                target=gf.loc[(gf.hypothesis==hypothesis)&(gf.horizon==horizon)]
                                summaries.append(dict(period=period,sampling=sampling,part=part,symbol=symbol,state=state,hypothesis=hypothesis,horizon=horizon,**describe(target)))
                    for ahead in (15,30):
                        baseline=st.loc[st.ahead==ahead]
                        baseline_rates={s:float((baseline.future==s).mean()) if len(baseline) else None for s in STATES}
                        for state in STATES:
                            target=st.loc[(st.current==state)&(st.ahead==ahead)];n=len(target)
                            transition_summary.append(dict(period=period,sampling=sampling,part=part,symbol=symbol,ahead=ahead,state=state,n=n,
                                sessions=int(target.session.nunique()),same_rate=float((target.future==state).mean()) if n else None,
                                rates={s:float((target.future==s).mean()) if n else None for s in STATES},
                                baseline_n=len(baseline),baseline_rates=baseline_rates,
                                same_rate_minus_baseline=float((target.future==state).mean())-baseline_rates[state] if n else None,
                                future_same_initial_direction=float((target.future_direction==target.current_direction).mean()) if n else None))
    save('状態別集計.json',summaries);save('状態遷移集計.json',transition_summary)
    coverage=[]
    ef=pd.DataFrame(excluded)
    for key,ready in sorted(inputs.items()):
        kept=obs.loc[(obs.session==key[0])&(obs.symbol==key[1])]
        lost=ef.loc[(ef.session==key[0])&(ef.symbol==key[1])]
        coverage.append(dict(session=key[0],symbol=key[1],採用数=len(kept),除外数=len(lost),
                             除外理由={str(k):int(v) for k,v in lost.reason.value_counts().items()}))
    save('観測被覆.json',coverage)
    flat=[{k:v for k,v in row.items() if k!='session_distribution'} for row in summaries]
    pd.DataFrame(flat).to_csv(HERE/'状態別集計.csv',index=False,encoding='utf-8-sig')
    session_table=data.groupby(['session','symbol','state','hypothesis','horizon']).agg(n=('hit_win','size'),
        continue_rate=('continue_direction','mean'),reverse_rate=('reverse_direction','mean'),win_touch_rate=('hit_win','mean'),
        loss_touch_rate=('hit_loss','mean'),untouched_rate=('untouched','mean'),mfe_mean=('mfe_atr','mean'),mae_mean=('mae_atr','mean')).reset_index()
    session_table.to_csv(HERE/'セッション別性質.csv',index=False,encoding='utf-8-sig')
    audit=causal_audit(inputs,models,observations);save('因果監査.json',audit)
    save('完了.json',dict(全合格=True,売買戦略探索=False,閾値最適化=False,対象=names,現在状態数=len(obs),将来ラベル数=len(data),
        状態遷移数=len(trans),除外理由=dict(exclusions),非重複観測数=int(obs.nonoverlap_60.sum()),API取得数=0,
        実装SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},真正未見=False))
    print('価格過程の記述分析完了: '+str(len(obs))+'現在状態 / '+str(len(data))+'将来ラベル',flush=True)


if __name__=='__main__':main()
