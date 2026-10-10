"""追加５秒足の閉じた価格区間、必要全観測、急傾斜初発を別式で確認する。"""

import hashlib
import importlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

from independent_signals_check import check_frame


HERE=Path(__file__).resolve().parent
WORK=HERE.parent/'round2'
ROOT=HERE.parents[2]


def independent_frame(account,quote):
    """機能: 完全５秒グリッドを原板区間から作り、12/24差分の特徴を手計算する。

    引数: account/quote(dict)。返り値: 公開原板行に対応する特徴表(pd.DataFrame)。
    """
    t,seq,mid=account['time_s'],account['seq'],quote['mid'];bucket=np.floor(t/5).astype(np.int64)
    starts=np.r_[0,np.flatnonzero(bucket[1:]!=bucket[:-1])+1]
    first=int(np.floor(account['start']/5));size=int(bucket[-1])-first
    fields={n:np.full(size,np.nan) for n in ('open','high','low','close','source_last_seq','source_last_time')};observed=np.zeros(size,dtype=bool)
    for n in range(len(starts)-1):
        a,b=int(starts[n]),int(starts[n+1]);j=int(bucket[a]-first)
        if j<0 or j>=size:continue
        p=mid[a:b];observed[j]=True
        for name,value in (('open',p[0]),('high',p.max()),('low',p.min()),('close',p[-1]),('source_last_seq',seq[b-1]),('source_last_time',t[b-1])):fields[name][j]=value
    for j in range(size):
        if not observed[j] and j>0:
            for name in ('close','source_last_seq','source_last_time'):fields[name][j]=fields[name][j-1]
        if not observed[j]:
            for name in ('open','high','low'):fields[name][j]=fields['close'][j]
    fields['observed']=observed;close=fields['close']
    for window,count in ((60,12),(120,24)):
        slope=np.full(size,np.nan);er=np.full(size,np.nan);previous=np.full(size,np.nan);high=np.full(size,np.nan);low=np.full(size,np.nan)
        valid=np.zeros(size,dtype=bool);accel=np.zeros(size,dtype=bool);fraction=np.full(size,np.nan);accel_fraction=np.full(size,np.nan)
        for j in range(size):
            if j>=count:
                segment=close[j-count:j+1]
                if np.isfinite(segment).all():
                    slope[j]=100*np.log1p((close[j]-close[j-count])/close[j-count])/(window/60)
                    travel=float(np.abs(segment[1:]-segment[:-1]).sum());er[j]=abs(close[j]-close[j-count])/travel if travel else 0.
                h=fields['high'][j-count:j];l=fields['low'][j-count:j]
                if np.isfinite(h).all():high[j]=h.max()
                if np.isfinite(l).all():low[j]=l.min()
                fraction[j]=observed[j-count:j+1].sum()/(count+1);valid[j]=observed[j-count:j+1].all()
                previous[j]=slope[j-count]
            if j>=2*count:
                accel_fraction[j]=observed[j-2*count:j+1].sum()/(2*count+1);accel[j]=observed[j-2*count:j+1].all()
        for name,value in ((f'slope_{window}',slope),(f'er_{window}',er),(f'previous_slope_{window}',previous),
            (f'prior_high_{window}',high),(f'prior_low_{window}',low),(f'window_observed_{window}',valid),(f'accel_observed_{window}',accel),
            (f'window_observed_fraction_{window}',fraction),(f'accel_observed_fraction_{window}',accel_fraction)):
            fields[name]=value
    published=starts[1:];source=bucket[published]-1;position=source-first
    frame=pd.DataFrame({name:value[position] for name,value in fields.items()})
    frame['source_bucket']=source;frame['bar_start']=source*5;frame['bar_end']=(source+1)*5
    frame['i']=published;frame['seq']=seq[published];frame['time_s']=t[published]
    for name in ('mid','bid','ask'):frame[name]=quote[name][published]
    frame['spread']=frame['ask']-frame['bid'];frame['tick']=float(account['tick'])
    frame['bar_age']=frame['time_s']-frame['source_last_time'];frame['publication_delay']=frame['time_s']-frame['bar_end']
    frame['quality']=frame['observed'] & frame['bar_age'].ge(0) & frame['bar_age'].le(5) & frame['publication_delay'].ge(0) & frame['publication_delay'].le(5) & frame['spread'].le(frame['mid']*.0002)
    return frame


def independent_candidates(frame,config):
    """機能: 条件全符号の初発をNumPy列演算で独立計算する。

    引数: frame(pd.DataFrame)、config(dict)。返り値: Nx3候補と選択行番号(tuple)。
    """
    w=config['window_seconds'];slope=frame[f'slope_{w}'].to_numpy();direction=np.sign(np.nan_to_num(slope,nan=0)).astype(np.int64)
    valid=frame['quality'].to_numpy() & frame[f'window_observed_{w}'].to_numpy() & (np.abs(slope)>=config['speed'])
    if config['family']!='SPEED':valid&=frame[f'er_{w}'].to_numpy()>=.7
    if config['family'] in ('ACCEL','BREAK'):
        valid&=frame[f'accel_observed_{w}'].to_numpy() & (direction*frame[f'previous_slope_{w}'].to_numpy()<=np.abs(slope)/2)
    if config['family']=='BREAK':
        close=frame['close'].to_numpy();tick=frame['tick'].to_numpy()
        valid&=((direction==1)&(close>=frame[f'prior_high_{w}'].to_numpy()+tick))|((direction==-1)&(close<=frame[f'prior_low_{w}'].to_numpy()-tick))
    state=np.where(valid,direction,0);previous=np.r_[0,state[:-1]]
    chosen=np.flatnonzero((state!=0)&(state!=previous));out=np.zeros((len(chosen),3));out[:,0]=frame['i'].to_numpy()[chosen];out[:,1]=state[chosen]
    return out,chosen


def main():
    """機能: 全24入口と全50口座の５秒足、prefix、欠測抑止と閾値同値を監査する。

    引数: なし。返り値: なし(None)。元192条件成果は変更しない。
    """
    sys.dont_write_bytecode=True;sys.path.insert(0,str(WORK));raw=importlib.import_module('raw_signals')
    fixed=json.loads((WORK/'実行前固定.json').read_text(encoding='utf-8'));prepared=json.loads((WORK/'入力準備.json').read_text(encoding='utf-8'))
    for path,sha in fixed['SHA'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    for name,sha in prepared['SHA'].items():assert hashlib.sha256((WORK/name).read_bytes()).hexdigest()==sha
    inputs=pickle.loads((ROOT/'work/wave_v60/inputs.pkl').read_bytes());quotes=pickle.loads((ROOT/'work/wave_v60/quotes.pkl').read_bytes())
    frames=pickle.loads((WORK/'公開特徴.pkl').read_bytes());candidates=pickle.loads((WORK/'入口候補.pkl').read_bytes());metadata=pickle.loads((WORK/'入口詳細.pkl').read_bytes())
    bars=total_candidates=prefix_checks=future_checks=0;reports=[]
    for account_no,key in enumerate(sorted(inputs)):
        account,q=inputs[key],quotes[key];full=frames[key];check_frame(full,independent_frame(account,q))
        for config in fixed['入口']:
            expected,selected=independent_candidates(full,config);np.testing.assert_array_equal(candidates[key][config['id']],expected)
            saved=pd.DataFrame(metadata[key][config['id']])
            if len(saved):
                np.testing.assert_array_equal(saved['side'].to_numpy(),expected[:,1]);np.testing.assert_array_equal(saved['i'].to_numpy(),expected[:,0])
                for name in ('seq','time_s','source_bucket','bar_end','source_last_seq','source_last_time','mid','bid','ask','spread','close','bar_age','publication_delay','tick'):
                    np.testing.assert_allclose(saved[name],full.iloc[selected][name],rtol=0,atol=0,equal_nan=True)
                for short,long in (('slope',f'slope_{config["window_seconds"]}'),('er',f'er_{config["window_seconds"]}'),('previous_slope',f'previous_slope_{config["window_seconds"]}')):
                    np.testing.assert_allclose(saved[short],full.iloc[selected][long],rtol=0,atol=0,equal_nan=True)
            total_candidates+=len(expected)
        positions={0,len(full)//2,len(full)-1}
        for w in (60,120):
            valid=np.flatnonzero(full[f'window_observed_{w}'].to_numpy())
            accel=np.flatnonzero(full[f'accel_observed_{w}'].to_numpy())
            if len(valid):positions.add(int(valid[0]))
            if len(accel):positions.add(int(accel[0]))
        gaps=np.flatnonzero(full['source_bucket'].diff().fillna(1).to_numpy()!=1)
        if len(gaps):positions.add(int(gaps[0]))
        lengths={1}
        for j in positions:
            i=int(full.iloc[j]['i']);lengths.update((i,i+1))
        for length in sorted(lengths):
            part=dict(account)
            for name in ('seq','time_s'):part[name]=account[name][:length]
            clipped={name:value[:length] for name,value in q.items()};expected=full[full['i']<length].reset_index(drop=True)
            frame=raw.build(part,clipped);pd.testing.assert_frame_equal(frame,expected,check_exact=True);prefix_checks+=1
            selected_configs=fixed['入口'] if account_no<4 else [c for c in fixed['入口'] if c['speed']==.05]
            for config in selected_configs:
                np.testing.assert_array_equal(raw.candidates(frame,config),candidates[key][config['id']][candidates[key][config['id']][:,0]<length])
            changed={name:value.copy() for name,value in q.items()}
            for name in ('bid','ask','mid'):changed[name][length:]+=997*account['tick']
            altered=raw.build(account,changed);pd.testing.assert_frame_equal(altered[altered['i']<length].reset_index(drop=True),expected,check_exact=True);future_checks+=1
        bars+=len(full);reports.append(dict(session=key[0],symbol=key[1],公開足=len(full),全24入口一致=True,prefix数=len(lengths)))
    # ----------------------------------------
    # １区間だけ欠測しても必要13/25・加速25/49区間全体が抑止されることを確認する。
    grid=np.arange(81);grid=grid[grid!=30];times=grid*5.+1.;mid=np.exp(grid*5/60*.001)*100000
    account=dict(start=0.,seq=np.arange(len(grid)),time_s=times,tick=1.)
    quote=dict(seq=account['seq'],time_s=times,mid=mid,bid=mid-.5,ask=mid+.5)
    gap_frame=raw.build(account,quote);check_frame(gap_frame,independent_frame(account,quote))
    gap_tests=[]
    for w,count in ((60,12),(120,24)):
        for name,length in ((f'window_observed_{w}',count+1),(f'accel_observed_{w}',2*count+1)):
            affected=(gap_frame['source_bucket']>=30)&(gap_frame['source_bucket']<30+length)
            assert not gap_frame.loc[affected,name].any()
            recovered=gap_frame[gap_frame['source_bucket']==30+length]
            assert len(recovered)==1 and bool(recovered.iloc[0][name])
            gap_tests.append(dict(指標=name,必要区間数=length,欠測影響全区間抑止=True,必要区間の観測復帰後解除=True))
    synthetic=frames[next(iter(frames))].iloc[:6].copy().reset_index(drop=True)
    synthetic['quality']=True;synthetic['tick']=1.;synthetic['close']=100.;synthetic['i']=np.arange(6)
    synthetic['window_observed_60']=True;synthetic['accel_observed_60']=True
    synthetic['slope_60']=[.049,.05,.05,0.,-.05,-.05];synthetic['er_60']=.7
    synthetic['previous_slope_60']=[.001,.025,.025,0.,-.025,-.025];synthetic['prior_high_60']=99.;synthetic['prior_low_60']=101.
    for family in ('SPEED','STRAIGHT','ACCEL','BREAK'):
        config=next(c for c in fixed['入口'] if c['window_seconds']==60 and c['speed']==.05 and c['family']==family)
        np.testing.assert_array_equal(raw.candidates(synthetic,config),np.array([[1.,1.,0.],[4.,-1.,0.]]))
    report=dict(結論='追加５秒足の全特徴・全24入口・公開境界prefix・未来改変・全必要観測抑止と数値境界が別式で一致',
        口座数=len(inputs),公開足照合数=bars,入口候補照合数=total_candidates,入口口座群数=24*len(inputs),prefix検査数=prefix_checks,未来価格改変検査数=future_checks,
        欠測合成検査=gap_tests,全4系統の閾値同値一致=True,口座別=reports,
        注意=['時計は最終約定時計で受信時計ではない。保存された時計と原板順の５秒区間としての因果性を検査した。',
        '60秒速度は13確定終値、120秒速度は25確定終値。加速は25/49観測区間が全て揃うことを要求する。',
        '加速・突破を含む各系統全条件の符号stateを更新する。フィルタ点滅で同じ波が再検知され得る。'],
        原実装SHA256=hashlib.sha256((WORK/'raw_signals.py').read_bytes()).hexdigest(),監査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'追加5秒足入口の独立監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','口座数','公開足照合数','入口候補照合数','入口口座群数','prefix検査数','未来価格改変検査数')},ensure_ascii=False))


if __name__=='__main__':main()
