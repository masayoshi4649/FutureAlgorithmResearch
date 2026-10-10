"""価格距離と物理時間の平均を、同じ原本順で計算する未採択の純粋モジュール。"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

TAU15 = -60. / math.log1p(-2. / 16.)


@dataclass(frozen=True)
class Config:
    """機能: 校正しない暫定パラメータを保持する。

    引数: 各項目は価格距離又は秒(float)。返り値: 不変設定(Config)。
    数値は売買条件として未固定であり、今回の人工検査用の設計案である。
    """

    fast_distance: float = 1.
    slow_distance: float = 4.
    tau_unit: float = TAU15
    slope_distance: float = .4
    slope_seconds: float = .4 * TAU15
    warmup_seconds: float = 1200.
    warmup_distance: float = 4.
    maximum_gap_seconds: float = 60.
    maximum_slope_age_seconds: float = 1800.
    entry_gap_atr: float = .15
    entry_slope_atr: float = .02


def candidate(scale: float = 1.) -> Config:
    """機能: 暫定の四つの距離幅を機械的に対応する設定へ変換する。

    引数: scale(float) は.5/1/2/4。返り値: 設定(Config)。データは参照しない。
    """
    if scale not in (.5,1.,2.,4.):
        raise ValueError('候補距離倍率が定義外です')
    return Config(fast_distance=scale,slow_distance=4*scale,slope_distance=.4*scale,
                  slope_seconds=.4*scale*TAU15,warmup_distance=4*scale)


def arrays(ready: dict) -> tuple:
    """機能: 単一セッションの原本列を、副作用なく検査して参照する。

    引数: ready(dict) はtime_s/seq/last/atr/tick/start。返り値: 四配列と呼値・開始秒(tuple)。
    同秒は認めるが時刻逆行・seq重複を拒否する。価格・ATR欠測は後段で扱う。
    """
    times=np.asarray(ready['time_s'],dtype=float)
    seq=np.asarray(ready['seq'])
    price=np.asarray(ready['last'],dtype=float)
    atr=np.asarray(ready['atr'],dtype=float)
    tick,start=float(ready['tick']),float(ready['start'])
    if any(a.ndim!=1 for a in (times,seq,price,atr)) or not (len(times)==len(seq)==len(price)==len(atr)):
        raise ValueError('入力配列の形状が不一致です')
    if not (np.isfinite(times).all() and np.all(np.diff(times)>=0)):
        raise ValueError('原本時刻は有限かつ非減少でなければなりません')
    if not np.issubdtype(seq.dtype,np.integer) or not (np.all(seq>=0) and np.all(np.diff(seq)>0)):
        raise ValueError('seqは重複のない非負整数でなければなりません')
    if not (math.isfinite(tick) and tick>0 and math.isfinite(start)):
        raise ValueError('呼値又は開始時刻が不正です')
    return times,seq,price,atr,tick,start


def price_ticks(price: np.ndarray, tick: float) -> np.ndarray:
    """機能: 有限正価格の呼値整合を検証し、整数座標へ変換する。

    引数: price(ndarray)、tick(float)。返り値: 呼値座標(ndarray[int64])。
    許す誤差は浮動小数の8ULPだけ。実質的な非整合価格を丸めて受け入れない。
    """
    output=np.zeros(len(price),dtype=np.int64)
    valid=np.isfinite(price)&(price>0)
    scaled=price[valid]/tick
    if np.any(scaled>2**52):raise ValueError('呼値座標が整数精度の範囲外です')
    integer=np.rint(scaled)
    restored=integer*tick
    tolerance=8*np.maximum(np.spacing(price[valid]),np.spacing(restored))
    if np.any(np.abs(price[valid]-restored)>tolerance):
        raise ValueError('価格が宣言呼値に整合しません。別仕様を先に定義してください')
    output[valid]=integer.astype(np.int64)
    return output


def model(ready: dict, config: Config = Config(), *, clock: str = 'distance',
          slope_clock: str = 'native', warmup_clock: str = 'distance') -> dict:
    """機能: 過去の価格距離又は物理時間で平均と暫定自己主方向を計算する。

    引数: ready(dict)、config(Config)、clock/slope_clock/warmup_clock(str)。
    返り値: 全行の特徴・方向・素材行を持つ辞書(dict[str,ndarray])。
    売買・相手確認・旧短期確認は実行しない。ATR欠測時は両時計を同様に再初期化する。
    """
    times,seq,price,atr,tick,start=arrays(ready)
    ticks=price_ticks(price,tick)
    if clock not in ('distance','physical') or slope_clock not in ('native','distance','physical'):
        raise ValueError('平均又は勾配の時計が未定義です')
    if warmup_clock not in ('distance','physical'):
        raise ValueError('暖機時計が未定義です')
    values=vars(config)
    if not all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) for v in values.values()):
        raise ValueError('設定は有限数値でなければなりません')
    if not (0<config.fast_distance<config.slow_distance and config.tau_unit>0 and
            config.slope_distance>0 and config.slope_seconds>0 and config.warmup_seconds>=0 and
            config.warmup_distance>=0 and config.maximum_gap_seconds>0 and
            config.maximum_slope_age_seconds>0 and config.entry_gap_atr>=0 and config.entry_slope_atr>=0):
        raise ValueError('設定の範囲が不正です')
    n=len(times)
    output={k:np.full(n,np.nan) for k in ('u','du','fast','slow','fast_offset','slow_offset','gap','slope','used_atr',
        'normalization_atr','seed_weight_slow','slope_actual_distance','slope_age_seconds')}
    output.update({k:np.full(n,-1,dtype=np.int64) for k in ('atr_source_row','slope_source_row','segment')})
    output.update(valid=np.zeros(n,bool),warm=np.zeros(n,bool),direction=np.zeros(n,np.int8))
    if slope_clock=='native':slope_clock='distance' if clock=='distance' else 'physical'
    previous_atr=np.nan;previous_atr_row=-1
    begin=-1;state=0;u=0.;fast=slow=np.nan;number=-1
    for i in range(n):
        # ----------------------------------------
        # 当行のATRは品質と方向の正規化だけに使う。距離は直前までの値に限定する。
        current_atr=atr[i]
        current_valid=math.isfinite(current_atr) and current_atr>0
        price_valid=math.isfinite(price[i]) and price[i]>0
        gap_ok=i==0 or times[i]-times[i-1]<=config.maximum_gap_seconds
        usable=price_valid and current_valid and math.isfinite(previous_atr) and previous_atr>0
        if not usable or not gap_ok:
            begin=-1;state=0
        if usable:
            denominator=max(previous_atr,2*tick)
            output['used_atr'][i]=denominator;output['atr_source_row'][i]=previous_atr_row
            output['normalization_atr'][i]=max(current_atr,2*tick)
            if begin<0:
                begin=i;number+=1;u=0.;fast=slow=0.;du=dt=0.
            else:
                du=abs(int(ticks[i])-int(ticks[i-1]))*tick/denominator;dt=times[i]-times[i-1]
                u+=du
                increment=du if clock=='distance' else dt/config.tau_unit
                offset=(int(ticks[i])-int(ticks[begin]))*tick
                fast+=-math.expm1(-increment/config.fast_distance)*(offset-fast)
                slow+=-math.expm1(-increment/config.slow_distance)*(offset-slow)
            output['u'][i]=u;output['du'][i]=du
            output['fast_offset'][i]=fast;output['slow_offset'][i]=slow
            output['fast'][i]=price[begin]+fast;output['slow'][i]=price[begin]+slow
            output['segment'][i]=number;output['valid'][i]=True
            output['gap'][i]=(fast-slow)/output['normalization_atr'][i]
            distance_or_time=u if clock=='distance' else (times[i]-times[begin])/config.tau_unit
            output['seed_weight_slow'][i]=math.exp(-distance_or_time/config.slow_distance)
            # ----------------------------------------
            # 探索範囲を当行までに限定し、同距離・同時刻でも後続原本を参照しない。
            coordinate=output['u'][begin:i+1] if slope_clock=='distance' else times[begin:i+1]
            target=(u-config.slope_distance) if slope_clock=='distance' else times[i]-config.slope_seconds
            j=begin+int(np.searchsorted(coordinate,target,side='right'))-1
            if j>=begin:
                age=times[i]-times[j]
                output['slope_source_row'][i]=j;output['slope_age_seconds'][i]=age
                output['slope_actual_distance'][i]=u-output['u'][j]
                if age<=config.maximum_slope_age_seconds:
                    output['slope'][i]=(slow-output['slow_offset'][j])/output['normalization_atr'][i]
            warm_clock=(u>=config.warmup_distance) if warmup_clock=='distance' else (
                times[i]-times[begin]>=config.slow_distance*config.tau_unit)
            warm=times[i]>=start+config.warmup_seconds and warm_clock and math.isfinite(output['slope'][i])
            output['warm'][i]=warm
            if not warm:state=0
            else:
                measure,slope=output['gap'][i],output['slope'][i]
                if state*measure<0:state=0
                if measure>config.entry_gap_atr and slope>config.entry_slope_atr:state=1
                elif measure<-config.entry_gap_atr and slope<-config.entry_slope_atr:state=-1
            output['direction'][i]=state
        # ----------------------------------------
        # 欠測ATRを未来値で埋めない。次行で使えるのはこの行までの有効値だけ。
        if current_valid:
            previous_atr=current_atr;previous_atr_row=i
        else:
            previous_atr=np.nan;previous_atr_row=-1
    return output


def compare(ready: dict, config: Config = Config(), *, slope_clock: str = 'native',
            warmup_clock: str = 'distance') -> dict:
    """機能: 同じ価格・ATR・品質と暖機案で二つの時計を並行計算する。

    引数: ready(dict)、config(Config)、slope_clock/warmup_clock(str)。返り値: 二方式辞書(dict)。
    nativeでは勾配時計も変わる。平均時計だけを調べる場合はphysicalを明示する。
    """
    return {kind:model(ready,config,clock=kind,slope_clock=slope_clock,warmup_clock=warmup_clock)
            for kind in ('distance','physical')}


def completed_groups(ready: dict, values: dict) -> dict:
    """機能: 同値時刻群の末尾状態を、次の異時刻を観測した行で初めて公開する。

    引数: ready(dict)、values(dict) はmodel出力。返り値: 公開イベント列(dict)。
    末尾群は未完のまま返さない。真の受信時刻を復元する関数ではない。
    """
    times,seq,_,_,_,_=arrays(ready)
    if len(values['direction'])!=len(times):raise ValueError('方向列長が不一致です')
    release=np.flatnonzero(np.r_[False,np.diff(times)>0]) if len(times) else np.empty(0,dtype=np.int64)
    source=release-1
    return dict(release_time=times[release].copy(),release_row=release.astype(np.int64),
        source_time=times[source].copy(),source_row=source.astype(np.int64),source_seq=seq[source].copy(),
        direction=np.asarray(values['direction'])[source].astype(np.int8),
        valid=np.asarray(values['valid'])[source].astype(bool))


def peer_asof(target_times: np.ndarray, events: dict, *, delay: float = 60.,
              freshness: float = 120.) -> dict:
    """機能: 追加遅延を経た相手公開を、物理時間の過去asofだけで参照する。

    引数: target_times(ndarray)、events(dict)、delay/freshness(float秒)。返り値: 方向と参照列(dict)。
    相手確認済み方向を循環入力しない。source_rowは相手のready行であり自己seqと比較しない。
    """
    targets=np.asarray(target_times,dtype=float);release=np.asarray(events['release_time'],dtype=float)
    if targets.ndim!=1 or not np.isfinite(targets).all() or np.any(np.diff(targets)<0):
        raise ValueError('自己時刻が不正です')
    if not (math.isfinite(delay) and delay>=0 and math.isfinite(freshness) and freshness>=0):
        raise ValueError('遅延又は鮮度が不正です')
    if not np.isfinite(release).all() or np.any(np.diff(release)<=0):raise ValueError('公開時刻が不正です')
    if not all(len(events[k])==len(release) for k in ('release_row','source_row','source_seq','direction','valid')):
        raise ValueError('相手公開列長が不一致です')
    index=np.searchsorted(release+delay,targets,side='right')-1
    result=dict(direction=np.zeros(len(targets),np.int8),event_index=index,
        source_row=np.full(len(targets),-1,np.int64),release_row=np.full(len(targets),-1,np.int64),
        effective_time=np.full(len(targets),np.nan),fresh=np.zeros(len(targets),bool))
    for i,j in enumerate(index):
        if j<0:continue
        effective=release[j]+delay
        result['source_row'][i]=events['source_row'][j];result['release_row'][i]=events['release_row'][j]
        result['effective_time'][i]=effective
        valid=bool(events['valid'][j]) and targets[i]-effective<=freshness
        result['fresh'][i]=valid
        if valid:result['direction'][i]=events['direction'][j]
    return result
