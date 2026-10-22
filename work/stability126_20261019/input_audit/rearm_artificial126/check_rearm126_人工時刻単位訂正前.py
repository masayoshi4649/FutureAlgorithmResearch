"""既知G/GUの再接続を、非空の合成売買と公開時刻の独立計算で確かめる。"""

import ast
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
TASK=HERE.parents[1]
ENGINE=TASK/'engine'
REARM=TASK/'rearm126'
sys.dont_write_bytecode=True
sys.path[:0]=[str(ENGINE),str(REARM)]
import legacy126 as legacy
import adapter126 as adapter

CHECKS=[]
ALLOWED_JSON={ENGINE/'legacy_root'/p for p in legacy.SMALL_FIXED}
OPENED=[]


def boundary(event: str, args: tuple) -> None:
    """
    機能: 独立人工による実市場・保存金融本文の読取を実open境界で拒否する。
    引数: event(str)、args(tuple)はPython監査イベント。
    返り値: None。源・小FIXED・所有JIT以外の市場入出力は禁止する。
    """
    if event!='open' or not isinstance(args[0],(str,bytes,os.PathLike)):return
    path=Path(os.fsdecode(args[0])).resolve()
    if not path.is_relative_to(ROOT):return
    mode=str(args[1] or '');flags=int(args[2] or 0)
    if any(v in mode for v in ('w','a','x','+')) or flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT):
        assert path.is_relative_to(HERE),('人工所有域外の書込',str(path));return
    if path.suffix in ('.py','.pyc','.nbi','.nbc','.pyd','.dll'):return
    assert path in ALLOWED_JSON,('実市場又は金融本文の読取拒否',str(path))
    OPENED.append(path.relative_to(ROOT).as_posix())


def check(name: str, condition: bool) -> None:
    """
    機能: 独立期待値との一致を記録する。
    引数: name(str)、condition(bool)は検査項目と成否。
    返り値: None。
    """
    assert condition,name;CHECKS.append(name)


def same(name: str, left: object, right: object) -> None:
    """
    機能: NaNを含む配列の厳密な同値を記録する。
    引数: name(str)、left/right(object)は比較値。
    返り値: None。
    """
    np.testing.assert_array_equal(left,right,err_msg=name);check(name,True)


def make_case(night: bool, side: int) -> tuple:
    """
    機能: 両数量・方向と足公開を確認できる非空の合成readyと足を構成する。
    引数: night(bool)はUS予定静観を含めるか、side(int)は上下方向。
    返り値: tuple[dict,dict]はpacketと銘柄別の合成1分足。実市場は参照しない。
    """
    start=datetime.fromisoformat('2026-10-19T21:00:00+09:00' if night else '2026-10-19T08:45:00+09:00').timestamp()
    pattern=np.array([100,99,100,102,106,104,104,104,104,104,104,104,104,104,104,100,99,100,102,106],float)
    n=480 if night else 240;time_s=start+np.arange(n)*30.
    price=np.tile(pattern,n//20)+np.arange(n)*.03
    if side<0:price=200.-price
    inputs={};features={};frames={}
    for symbol,scale,tick in (('TOPIX',1.,.5),('NK225',20.,10.)):
        key='人工',symbol;own=price*scale
        inputs[key]=dict(session='人工',symbol=symbol,seq=np.arange(n,dtype=np.int64)*3+7,
            time_s=time_s.copy(),last=own.copy(),atr=np.full(n,2.*scale),tick=tick,start=start,
            limit=time_s[-1]+30.,session_close=time_s[-1]+630.,
            us_open=datetime.fromisoformat('2026-10-19T22:30:00+09:00').timestamp() if night else np.inf)
        zero=np.zeros(n,np.int8);source=np.full(n,-1,np.int64);valid=np.zeros(n,bool)
        features[key]=dict(columns=(np.full(n,side,np.int8),zero,source,zero.copy(),source.copy(),valid),
            valid=valid.copy(),gate=np.zeros(n,bool),joint=dict(direction=zero.copy(),source=source.copy(),valid=valid.copy()),
            ema=(zero.copy(),source.copy(),source.copy(),valid.copy()))
        close=own[1::2]
        frames[symbol]=pd.DataFrame(dict(time=[datetime.fromtimestamp(start+j*60).astimezone().isoformat() for j in range(len(close))],
            open=close,high=close+.2*scale,low=close-.2*scale,close=close,
            volume=np.full(len(close),10.),closed=np.array([j!=5 for j in range(len(close))]),
            volume_complete=np.ones(len(close),bool)))
    signals=dict(entry={key:feature['columns'][0] for key,feature in features.items()},B00={},B01={})
    return dict(inputs=inputs,features=features,signals=signals),frames


def independent_ema(values: np.ndarray, span: int) -> np.ndarray:
    """
    機能: adjustFalse指数平滑を逐次式から独立計算する。
    引数: values(ndarray)、span(int)は合成終値と固定期間。
    返り値: ndarrayはminperiodsも反映したEMA。
    """
    output=np.full(len(values),np.nan);state=float(values[0]);alpha=2./(span+1.)
    for index,value in enumerate(values):
        state=float(value) if index==0 else (1.-alpha)*state+alpha*float(value)
        if index+1>=span:output[index]=state
    return output


def manual_gate(packet: dict, frames: dict) -> dict:
    """
    機能: 当時公開足と15/60EMA・3本傾きを外部逐次式で判定する。
    引数: packet/frames(dict)は合成入力。
    返り値: dict[tuple,ndarray]は自己120秒・相手追加60秒の独立gate。
    """
    models={}
    for key,ready in packet['inputs'].items():
        frame=frames[key[1]];release=pd.to_datetime(frame.time).astype('int64').to_numpy()/1e9+120.
        valid=frame.closed.to_numpy(bool)&(release<=ready['time_s'][-1])
        close=frame.close.to_numpy()[valid];times=release[valid]
        fast=independent_ema(close,15);slow=independent_ema(close,60)
        slope=np.full(len(close),np.nan);slope[3:]=slow[3:]-slow[:-3]
        atr=float(ready['atr'][0]);models[key]=dict(time=times,gap=(fast-slow)/atr,slow=slope/atr)
    output={}
    for key,ready in packet['inputs'].items():
        side=packet['features'][key]['columns'][0];allowed=np.ones(len(side),bool)
        for selected,delay in ((key,0.),((key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX'),60.)):
            model=models[selected];index=np.searchsorted(model['time']+delay,ready['time_s'],side='right')-1
            safe=np.maximum(index,0)
            allowed &= (index>=0)&(model['gap'][safe]*side>.15)&(model['slow'][safe]*side>.02)
        output[key]=allowed
    return output


def gate_with_frames(runtime: dict, packet: dict, frames: dict) -> dict:
    """
    機能: 原CSVの代わりに合成DataFrameだけを旧関数へ渡す。
    引数: runtime/packet/frames(dict)は所有旧源と合成素材。
    返り値: dictは被監査adapterが生成したgate。実CSV本文は開かない。
    """
    original=pd.read_csv
    def reader(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        """
        機能: 指定銘柄の合成足だけを返す。
        引数: path(object)、args/kwargs(object)はCSV要求。
        返り値: pd.DataFrameは合成足の独立コピー。
        """
        symbol=Path(path).parent.name;assert symbol in frames
        return frames[symbol].copy(deep=True)
    pd.read_csv=reader
    try:return adapter.make_gate(runtime,packet,HERE/'synthetic_consumer')
    finally:pd.read_csv=original


def fee_zero_reference(runtime: dict, config: dict, ready: dict, feature: dict) -> tuple:
    """
    機能: 旧play本文を変更せず費用だけを明示零にした独立比較元を運転する。
    引数: runtime/config/ready/feature(dict)は所有旧源と合成設定。
    返り値: tupleは旧playの返却値。費用代理は呼出後に復元する。
    """
    owner=runtime['old'].legacy;original=owner.control_parameters
    def zero(control: dict, symbol: str) -> np.ndarray:
        """
        機能: 元費用制御列の12番目だけを零にする。
        引数: control(dict)、symbol(str)は旧署名。
        返り値: ndarrayは他全項目を保持した設定。
        """
        value=original(control,symbol).copy();value[12]=0.;return value
    owner.control_parameters=zero
    try:return runtime['old'].play(config,ready,feature,observed=True)
    finally:owner.control_parameters=original


def execute() -> None:
    """
    機能: 非空G/GUの旧新全配列・公開時刻・未来不変・費用零を独立に確認する。
    引数: なし。
    返り値: None。原CSV及び保存市場・金融配列の本文を読まない。
    """
    numerical=[REARM/'adapter126.py',ENGINE/'legacy126.py',ENGINE/'policy126.py',
               ENGINE/'legacy_root/work/wave_v85/strategy.py',ENGINE/'legacy_root/work/wave_v49/gates/gate_replay.py',
               ENGINE/'legacy_root/work/wave_v23/signals.py',ENGINE/'legacy_root/work/wave_v85/time_filter.py']
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in numerical}
    sys.addaudithook(boundary);legacy.CACHE=str(HERE/'jit')
    records=[]
    with legacy.isolated(discover=False):
        runtime=legacy.runtime()
        for night in (False,True):
            for side in (1,-1):
                packet,frames=make_case(night,side)
                features=gate_with_frames(runtime,packet,frames)
                expected=manual_gate(packet,frames)
                for key in packet['inputs']:
                    same('逐次EMAと公開+120及び相手+60_'+str((night,side,key)),features[key]['gate'],expected[key])
                    check('gateが非空_'+str((night,side,key)),bool(features[key]['gate'].any()))
                    for a,b in zip(features[key]['columns'],packet['features'][key]['columns']):same('元十列を保持',a,b)
                    for config in adapter.catalog():
                        ready=packet['inputs'][key]
                        new,settings=adapter.play(runtime,config,ready,features[key])
                        old,old_settings=fee_zero_reference(runtime,config,ready,features[key])
                        check('設定が旧と同一',settings==old_settings)
                        check('非空売買と場内返済',len(new['orders'])>=2 and new['stats'][9]==0)
                        for field,value in new.items():
                            if isinstance(value,np.ndarray):same('旧zero_fee全配列_'+config['id']+'_'+field,value,old[field])
                        records.append(dict(night=night,side=side,symbol=key[1],method=config['id'],orders=len(new['orders']),net=float(new['stats'][0])))
                # ----------------------------------------
                # 未来足の毒値と真の観測尾切断が既知gateを変えない。
                cut=int(len(next(iter(packet['inputs'].values()))['last'])*.73)
                cutoff=next(iter(packet['inputs'].values()))['time_s'][cut]
                changed=deepcopy(frames)
                for frame in changed.values():
                    release=pd.to_datetime(frame.time).astype('int64').to_numpy()/1e9+120.
                    frame.loc[release>=cutoff,['close','high','low']]+=1000000.
                future=gate_with_frames(runtime,packet,changed)
                short=deepcopy(packet)
                for key,ready in short['inputs'].items():
                    for field in ('seq','time_s','last','atr'):ready[field]=ready[field][:cut]
                    feature=short['features'][key]
                    feature['columns']=tuple(v[:cut] for v in feature['columns']);feature['valid']=feature['valid'][:cut]
                    feature['gate']=feature['gate'][:cut]
                    feature['ema']=tuple(v[:cut] for v in feature['ema'])
                    feature['joint']={k:v[:cut] for k,v in feature['joint'].items()}
                prefix=gate_with_frames(runtime,short,frames)
                for key in packet['inputs']:
                    same('未公開足改変で既知gate不変',features[key]['gate'][:cut],future[key]['gate'][:cut])
                    same('真の尾切断でgate prefix不変',features[key]['gate'][:cut],prefix[key]['gate'])
        # ----------------------------------------
        # 極端な旧費用制御を注入しても新adapterは必ず判定費用を零にする。
        packet,frames=make_case(False,1);features=gate_with_frames(runtime,packet,frames)
        owner=runtime['old'].legacy;original=owner.control_parameters
        def expensive(control: dict, symbol: str) -> np.ndarray:
            """
            機能: 手数料零の無効化を反証するため、旧費用列だけを極端にする。
            引数: control(dict)、symbol(str)は旧署名。
            返り値: ndarrayは故意に高費用へした旧制御値。
            """
            result=original(control,symbol).copy();result[12]=1000000.;return result
        for key,ready in packet['inputs'].items():
            for config in adapter.catalog():
                correct,_=adapter.play(runtime,config,ready,features[key])
                owner.control_parameters=expensive
                try:
                    modified,_=adapter.play(runtime,config,ready,features[key])
                    native,_=runtime['old'].play(config,ready,features[key],observed=True)
                finally:owner.control_parameters=original
                for field in ('orders','trades','cycles','curve','stats'):
                    same('新adapterは判定費用も零_'+field,correct[field],modified[field])
                check('費用代理が実際に旧予算判定へ効く',not np.array_equal(native['orders'],correct['orders']))
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value for name,value in sources.items())
    proof=dict(passed=True,count=len(CHECKS),checks=CHECKS,nonempty_cases=records,sources=sources,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),small_fixed_reads=OPENED,
        original_market_reads=0,saved_market_reads=0,financial_replays=0,API=0,real_orders=0,
        comparison='旧play本文無変更・control_parameters費用列12だけ零の独立比較元。新adapterのAST一文追加と全ndarray一致。native高費用は別経路になることを反証。')
    target=HERE/'既知GとGUの非空旧新同値及び公開時計の独立純人工.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,count=len(CHECKS),nonempty_cases=len(records)),ensure_ascii=False))


if __name__=='__main__':
    try:execute()
    except Exception as error:
        target=HERE/('独立純人工停止_'+str(time.time_ns())+'.json')
        target.write_text(json.dumps(dict(passed=False,error=repr(error),checks=CHECKS,
            original_market_reads=0,saved_market_reads=0,financial_replays=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
