"""急傾斜入口の閉じた分足・数値特徴・初発状態を別実装で確認する。"""

import hashlib
import importlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]


def independent_frame(account,quote):
    """機能: 完全分グリッド上の価格区間を手集計して数値特徴を計算する。

    引数: account/quote(dict)。返り値: 元実装と同じ公開行の特徴表(pd.DataFrame)。
    """
    times,seq,mid=account['time_s'],account['seq'],quote['mid']
    buckets=np.floor(times/60).astype(np.int64)
    starts=np.r_[0,np.flatnonzero(buckets[1:]!=buckets[:-1])+1]
    first=int(np.floor(account['start']/60));last=int(buckets[-1]);size=last-first
    fields={name:np.full(size,np.nan) for name in ('open','high','low','close','source_last_seq','source_last_time')}
    observed=np.zeros(size,dtype=bool)
    for position in range(len(starts)-1):
        a,b=int(starts[position]),int(starts[position+1]);j=int(buckets[a]-first)
        if j<0 or j>=size:
            continue
        prices=mid[a:b];observed[j]=True
        for name,value in (('open',prices[0]),('high',prices.max()),('low',prices.min()),('close',prices[-1]),('source_last_seq',seq[b-1]),('source_last_time',times[b-1])):
            fields[name][j]=value
    for j in range(size):
        if not observed[j] and j>0:
            for name in ('close','source_last_seq','source_last_time'):
                fields[name][j]=fields[name][j-1]
        if not observed[j]:
            for name in ('open','high','low'):
                fields[name][j]=fields['close'][j]
    fields['observed']=observed
    close=fields['close']
    for window in (2,3,5,10):
        slope=np.full(size,np.nan);er=np.full(size,np.nan)
        previous=np.full(size,np.nan);high=np.full(size,np.nan);low=np.full(size,np.nan)
        valid=np.zeros(size,dtype=bool);accel=np.zeros(size,dtype=bool)
        for j in range(size):
            if j>=window:
                segment=close[j-window:j+1]
                if np.isfinite(segment).all():
                    slope[j]=100*np.log1p((close[j]-close[j-window])/close[j-window])/window
                    travel=float(np.abs(segment[1:]-segment[:-1]).sum())
                    er[j]=abs(close[j]-close[j-window])/travel if travel else 0.
                high_segment=fields['high'][j-window:j]
                low_segment=fields['low'][j-window:j]
                if np.isfinite(high_segment).all():
                    high[j]=high_segment.max()
                if np.isfinite(low_segment).all():
                    low[j]=low_segment.min()
                valid[j]=observed[j-window:j+1].all()
            if j>=2*window:
                accel[j]=observed[j-2*window:j+1].all()
            if j>=window:
                previous[j]=slope[j-window]
        for name,value in ((f'slope_{window}',slope),(f'er_{window}',er),(f'previous_slope_{window}',previous),
            (f'prior_high_{window}',high),(f'prior_low_{window}',low),(f'window_observed_{window}',valid),(f'accel_observed_{window}',accel)):
            fields[name]=value
    published=starts[1:];source=buckets[published]-1;positions=source-first
    frame=pd.DataFrame({name:value[positions] for name,value in fields.items()})
    frame['source_bucket']=source;frame['bar_start']=source*60;frame['bar_end']=(source+1)*60
    frame['i']=published;frame['seq']=seq[published];frame['time_s']=times[published]
    for name in ('mid','bid','ask'):
        frame[name]=quote[name][published]
    frame['spread']=frame['ask']-frame['bid'];frame['tick']=float(account['tick'])
    frame['bar_age']=frame['time_s']-frame['source_last_time'];frame['publication_delay']=frame['time_s']-frame['bar_end']
    frame['quality']=frame['observed'] & frame['bar_age'].ge(0) & frame['bar_age'].le(60) & frame['publication_delay'].ge(0) & frame['publication_delay'].le(60) & frame['spread'].le(frame['mid']*.0002)
    return frame


def state_candidates(frame,config):
    """機能: 各公開行で全条件符号stateを逐次更新し、切替初発を抽出する。

    引数: frame(pd.DataFrame)、config(dict)。返り値: 候補配列と発火表(tuple)。
    """
    window,family,speed=config['window'],config['family'],config['speed']
    slopes=frame[f'slope_{window}'].to_numpy();er=frame[f'er_{window}'].to_numpy();previous=frame[f'previous_slope_{window}'].to_numpy()
    last_state=0;chosen=[];sides=[]
    for j in range(len(frame)):
        row=frame.iloc[j];slope=slopes[j]
        direction=int(slope>0)-int(slope<0) if np.isfinite(slope) else 0
        valid=bool(row['quality'] and row[f'window_observed_{window}'] and abs(slope)>=speed)
        if family!='SPEED':
            valid=valid and er[j]>=.7
        if family in ('ACCEL','BREAK'):
            valid=valid and bool(row[f'accel_observed_{window}']) and direction*previous[j]<=abs(slope)/2
        breakthrough=(direction==1 and row['close']>=row[f'prior_high_{window}']+row['tick']) or (direction==-1 and row['close']<=row[f'prior_low_{window}']-row['tick'])
        if family=='BREAK':
            valid=valid and breakthrough
        state=direction if valid else 0
        if state and state!=last_state:
            chosen.append(j);sides.append(state)
        last_state=state
    result=np.zeros((len(chosen),3));result[:,0]=frame['i'].to_numpy()[chosen];result[:,1]=sides
    return result,chosen


def check_frame(actual,expected):
    """機能: 特徴の全列を別式と数値許容差付きで比較する。

    引数: actual/expected(pd.DataFrame)。返り値: なし(None)。不一致なら例外。
    """
    assert set(actual.columns)==set(expected.columns)
    for name in actual.columns:
        a,b=actual[name].to_numpy(),expected[name].to_numpy()
        if a.dtype==bool or np.issubdtype(a.dtype,np.integer):
            np.testing.assert_array_equal(a,b,err_msg=name)
        else:
            np.testing.assert_allclose(a,b,rtol=1e-12,atol=1e-12,equal_nan=True,err_msg=name)


def main():
    """機能: 全48入口を別式照合し、窓/欠測/公開境界prefixと閾値同値を検査する。

    引数: なし。返り値: なし(None)。入口特徴と条件を変更しない。
    """
    sys.dont_write_bytecode=True;sys.path.insert(0,str(WORK));signals=importlib.import_module('steep_signals')
    fixed=json.loads((WORK/'実行前固定.json').read_text(encoding='utf-8'))
    prepared=json.loads((WORK/'入力準備.json').read_text(encoding='utf-8'))
    for path,sha in fixed['SHA'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
    for name,sha in prepared['SHA'].items():
        assert hashlib.sha256((WORK/name).read_bytes()).hexdigest()==sha
    inputs=pickle.loads((ROOT/'work/wave_v60/inputs.pkl').read_bytes());quotes=pickle.loads((ROOT/'work/wave_v60/quotes.pkl').read_bytes())
    frames=pickle.loads((WORK/'公開特徴.pkl').read_bytes());candidates=pickle.loads((WORK/'入口候補.pkl').read_bytes());metadata=pickle.loads((WORK/'入口詳細.pkl').read_bytes())
    total_bars=total_candidates=prefix_count=future_count=0;account_results=[]
    prefix_configs=[c for c in fixed['入口'] if c['id'] in ('SPEED_H02_V020','ACCEL_H03_V020','BREAK_H03_V020','STRAIGHT_H05_V020','ACCEL_H10_V020')]
    for account_no,key in enumerate(sorted(inputs)):
        account,quote=inputs[key],quotes[key];full=frames[key]
        independent=independent_frame(account,quote);check_frame(full,independent)
        numeric_cols=sum(np.issubdtype(full[c].dtype,np.number) for c in full.columns)
        for config in fixed['入口']:
            expected,indexes=state_candidates(full,config)
            np.testing.assert_array_equal(candidates[key][config['id']],expected)
            saved=pd.DataFrame(metadata[key][config['id']])
            if len(saved):
                np.testing.assert_array_equal(saved['i'].to_numpy(),expected[:,0])
                np.testing.assert_array_equal(saved['side'].to_numpy(),expected[:,1])
                for name in ('seq','time_s','source_bucket','bar_end','source_last_seq','source_last_time','mid','bid','ask','spread','close','bar_age','publication_delay','tick'):
                    np.testing.assert_allclose(saved[name].to_numpy(),full.iloc[indexes][name].to_numpy(),rtol=0,atol=0,equal_nan=True)
                np.testing.assert_allclose(saved['slope'],full.iloc[indexes][f'slope_{config["window"]}'],rtol=0,atol=0,equal_nan=True)
                np.testing.assert_allclose(saved['er'],full.iloc[indexes][f'er_{config["window"]}'],rtol=0,atol=0,equal_nan=True)
                np.testing.assert_allclose(saved['previous_slope'],full.iloc[indexes][f'previous_slope_{config["window"]}'],rtol=0,atol=0,equal_nan=True)
            total_candidates+=len(expected)
        positions={0,len(full)//2,len(full)-1}
        for window in (2,3,5,10):
            valid=np.flatnonzero(full[f'window_observed_{window}'].to_numpy())
            if len(valid):positions.add(int(valid[0]))
        gaps=np.flatnonzero(full['source_bucket'].diff().fillna(1).to_numpy()!=1)
        if len(gaps):positions.add(int(gaps[0]))
        cut_sizes={1}
        for position in positions:
            i=int(full.iloc[position]['i']);cut_sizes.update((i,i+1))
        for size in sorted(cut_sizes):
            part=dict(account)
            for name in ('seq','time_s'):part[name]=account[name][:size]
            qpart={name:value[:size] for name,value in quote.items()}
            built=signals.build(part,qpart);expected=full[full['i']<size].reset_index(drop=True)
            pd.testing.assert_frame_equal(built,expected,check_exact=True);prefix_count+=1
            selected_configs=fixed['入口'] if account_no in (0,1,2,3) else prefix_configs
            for config in selected_configs:
                np.testing.assert_array_equal(signals.candidates(built,config),candidates[key][config['id']][candidates[key][config['id']][:,0]<size])
            changed={name:value.copy() for name,value in quote.items()}
            for name in ('bid','ask','mid'):changed[name][size:]+=997*account['tick']
            after=signals.build(account,changed);after=after[after['i']<size].reset_index(drop=True)
            pd.testing.assert_frame_equal(after,expected,check_exact=True);future_count+=1
        total_bars+=len(full)
        account_results.append(dict(session=key[0],symbol=key[1],公開足=len(full),数値列=numeric_cols,全48入口一致=True,prefix切断数=len(cut_sizes)))
    # ----------------------------------------
    # 抽象特徴で境界同値、連続条件、逆方向、欠測解除後のstateを確認する。
    synthetic=frames[next(iter(frames))].iloc[:6].copy().reset_index(drop=True)
    synthetic['quality']=True;synthetic['tick']=1.;synthetic['close']=100.;synthetic['i']=np.arange(6)
    synthetic['window_observed_3']=True;synthetic['accel_observed_3']=True
    synthetic['slope_3']=np.array([.019,.02,.02,0.,-.02,-.02]);synthetic['er_3']=.7
    synthetic['previous_slope_3']=np.array([.001,.01,.01,0.,-.01,-.01]);synthetic['prior_high_3']=99.;synthetic['prior_low_3']=101.
    boundary_checks=[]
    for family in ('SPEED','STRAIGHT','ACCEL','BREAK'):
        config=next(c for c in fixed['入口'] if c['window']==3 and c['speed']==.02 and c['family']==family)
        actual=signals.candidates(synthetic,config);expected=np.array([[1.,1.,0.],[4.,-1.,0.]])
        np.testing.assert_array_equal(actual,expected)
        boundary_checks.append(dict(系統=family,速度閾値同値=True,ER同値=True,加速同値=True,突破同値=True,連続再発火なし=True,逆方向初発=True))
    report=dict(結論='完全分グリッドの独立特徴計算、全48入口と詳細、公開境界prefix・未来改変・閾値同値が一致',
        口座数=len(inputs),公開足照合数=total_bars,入口候補照合数=total_candidates,入口口座群数=len(inputs)*48,
        prefix検査数=prefix_count,未来価格改変検査数=future_count,数値境界検査=boundary_checks,口座別=account_results,
        注意=['速度は100*logの毎分百分率、単純差分の百分率とは厳密には異なる。',
        'BREAKはACCELに突破を追加する包含関係。検知前の順行幅は事後MFEに加算しない。',
        '初発stateは速度・観測・ER・加速・突破など当該系統の全条件を結合後に更新。条件点滅で再発火し得る。',
        '新コードは足完全グリッドでN+1本/2N+1本観測を要求し、欠測の据置価格から急傾斜を発火させない。',
        '検知数は同一波の重複・入口定義間の重複を含み、独立した市場標本ではない。',
        '同じCurrentPriceTimeの原板更新をseq順に使う。実受信時計による未知試験ではない。'],
        実装SHA256=hashlib.sha256((WORK/'steep_signals.py').read_bytes()).hexdigest(),監査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'急傾斜入口の独立監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','口座数','公開足照合数','入口候補照合数','入口口座群数','prefix検査数','未来価格改変検査数')},ensure_ascii=False))


if __name__=='__main__':
    main()
