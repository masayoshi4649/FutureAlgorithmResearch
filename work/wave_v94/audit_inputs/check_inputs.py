"""新価格素材を原本及び独立した厳密過去窓から照合し、売買・損益を実行しない。"""

from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
WINDOWS = (30,60,180,300,600)
RANGES = (60,180)
COUNTS = Counter()


def module(name: str,path: Path) -> object:
    """
    機能: 比較対象だけを局所名で読み、独立期待値へ対象関数を使用しない。
    引数: name(str)、path(Path)。
    返り値: object、読み込んだモジュール。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    sys.modules[name]=result
    spec.loader.exec_module(result)
    return result


def digest(path: Path) -> str:
    """
    機能: 不変資料を一定メモリーでSHA256照合する。
    引数: path(Path)。
    返り値: str、SHA256。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def load(path: Path) -> object:
    """
    機能: 保存素材を読取り専用として取得する。
    引数: path(Path)。
    返り値: object、JSON又はpickle内容。
    """
    if path.suffix=='.pkl':
        with path.open('rb') as stream:return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def equal(actual: object,expected: object,name: str) -> None:
    """
    機能: 数値・旗・構造を欠測位置込みで照合する。
    引数: actual/expected(object)、name(str)。
    返り値: None、不一致なら停止する。
    """
    if isinstance(expected,dict):
        assert isinstance(actual,dict) and set(actual)==set(expected),(name,set(actual)^set(expected))
        for key,value in expected.items():equal(actual[key],value,name+'/'+str(key))
    elif isinstance(expected,np.ndarray):
        assert actual.shape==expected.shape,(name,actual.shape,expected.shape)
        if expected.dtype.kind in 'fc':np.testing.assert_allclose(actual,expected,rtol=1e-11,atol=1e-8,equal_nan=True,err_msg=name)
        else:np.testing.assert_array_equal(actual,expected,err_msg=name)
        COUNTS['比較配列']+=1
        COUNTS['比較セル']+=expected.size
    else:assert actual==expected,(name,actual,expected)


def clock(value: object) -> float:
    """
    機能: 原本のtimezone付き時計だけを独立に読み、欠測を補完しない。
    引数: value(object)。
    返り値: float、代理epoch秒又はNaN。
    """
    if not isinstance(value,str):return math.nan
    try:
        stamp=datetime.fromisoformat(value)
        if stamp.tzinfo is None:return math.nan
        result=stamp.timestamp()
        return result if math.isfinite(result) else math.nan
    except (ValueError,TypeError,OverflowError,OSError):return math.nan


def positive(value: object) -> float:
    """
    機能: 正常LP又は数量を独立に分類する。
    引数: value(object)。
    返り値: float、有限正値又はNaN。
    """
    if isinstance(value,bool):return math.nan
    try:result=float(value)
    except (TypeError,ValueError,OverflowError):return math.nan
    return result if math.isfinite(result) and result>0 else math.nan


def source(targets: np.ndarray,times: np.ndarray,valid: np.ndarray,reset: np.ndarray) -> tuple:
    """
    機能: 一意な時計の先頭行を独立索引化し、最新厳密過去だけを選ぶ。
    引数: targets/times(ndarray)、valid/reset(ndarray[bool])。
    返り値: tuple、index(int32配列)とage(float32配列)。救済や前方補完なし。
    """
    clocks,first=np.unique(times,return_index=True)
    group=np.searchsorted(clocks,targets,side='left')-1
    index=np.full(len(targets),-1,np.int32)
    age=np.full(len(targets),np.nan,np.float32)
    if not len(times):return index,age
    safe=np.maximum(group,0);row=first[safe]
    elapsed=targets-times[row]
    accepted=(group>=0)&valid[row]&~reset[row]&(elapsed>0)&(elapsed<=30.)
    index[accepted]=row[accepted]
    age[accepted]=elapsed[accepted]
    return index,age


def bounds(prices: np.ndarray,left: np.ndarray,right: np.ndarray) -> tuple:
    """
    機能: 独立疎表で過去半開区間の高安を求め、現在価格を排除する。
    引数: prices(ndarray)、left/right(ndarray[int])。
    返り値: tuple、高値と安値のfloat配列。対象実装のdequeを使わない。
    """
    high=np.full(len(left),np.nan);low=high.copy()
    if not len(prices):return high,low
    maxima=[prices.copy()];minima=[prices.copy()];width=1
    while width*2<=len(prices):
        maxima.append(np.maximum(maxima[-1][:-width],maxima[-1][width:]))
        minima.append(np.minimum(minima[-1][:-width],minima[-1][width:]))
        width*=2
    lengths=right-left
    for level in range(len(maxima)):
        use=(lengths>=(1<<level))&(lengths<(1<<(level+1)))
        stop=right[use]-(1<<level)
        high[use]=np.maximum(maxima[level][left[use]],maxima[level][stop])
        low[use]=np.minimum(minima[level][left[use]],minima[level][stop])
    return high,low


def oracle(grid: np.ndarray,record: dict,lane: str,old: dict=None) -> dict:
    """
    機能: 原本に照合済みの価格・断裂から全格子の厳密過去窓を独立再構成する。
    引数: grid(ndarray)、record(dict)、lane(str:I1/I2/I3)、old(dict|None)。
    返り値: dict、価格素材の期待値。旧Q/F・執行時計・損益を生成しない。
    """
    times=record['time_s'];seq=record['seq'];prices=record['values']
    quality=record.get('endpoint_valid',record['valid']);path_valid=record['valid'];reset=record['reset'];size=len(grid)
    if lane=='I2':now=old['current']['index'].copy();age=old['current']['age'].copy()
    else:now,age=source(grid-1.,times,quality,reset)
    safe_now=np.maximum(now,0)
    raw_seq=seq[safe_now].copy();raw_seq[now<0]=-1
    src_time=times[safe_now].copy();src_time[now<0]=np.nan
    value=prices[safe_now].copy();value[now<0]=np.nan
    current=dict(index=now,raw_seq=raw_seq,time_s=src_time,age=age,actual_age=age+1,valid=now>=0)
    if lane=='I1':
        current['mid']=value
        for field in ('bid','ask','last'):
            current[field]=record[field][safe_now].copy();current[field][now<0]=np.nan
        current['last_valid']=current['valid']&np.isfinite(current['last'])&(current['last']>0)
        current['spread_ticks']=(current['ask']-current['bid'])/record['tick']
    else:current.update(value=value,last=value.copy())
    unique,first=np.unique(times,return_index=True)
    first_values=prices[first]
    changes=np.abs(np.diff(first_values));changes[~np.isfinite(changes)]=0
    cumulative=np.r_[0.,np.cumsum(changes)]
    broken=np.r_[0,np.cumsum(~path_valid|reset)]
    now_pos=np.searchsorted(first,safe_now)
    result=dict(current=current,windows={},ranges={})
    if lane=='I1':result['price_quality']=record['price_quality']
    elif lane=='I2':result['source_kind']='旧源行と旧資格を保ったLastPrice対照'
    else:result['source_kind']='原本CurrentPriceのみ'
    for seconds in WINDOWS:
        if lane=='I2':old_index=old['windows'][seconds]['old'].copy();old_age=old['windows'][seconds]['old_age'].copy()
        else:old_index,old_age=source(grid-1.-seconds,times,quality,reset)
        safe_old=np.maximum(old_index,0);old_pos=np.searchsorted(first,safe_old)
        available=(now>=0)&(old_index>=0)
        same=available&(now==old_index)
        crossed=available&((broken[safe_now+1]-broken[safe_old+1])>0)
        usable=available&(old_index<now)&~crossed
        if lane=='I2':
            same=old['windows'][seconds]['same_row'].copy()
            crossed=old['windows'][seconds]['reset_or_invalid_cross'].copy()
            usable=old['windows'][seconds]['source_valid'].copy()
        displacement=prices[safe_now]-prices[safe_old]
        variation=cumulative[now_pos]-cumulative[old_pos]
        efficiency=np.full(size,np.nan);good=usable&(variation>0)
        efficiency[good]=np.abs(displacement[good])/variation[good]
        values=dict(old=old_index,now=now.copy(),old_age=old_age,source_valid=usable,same_row=same,
                    reset_or_invalid_cross=crossed,zero_variation=usable&(variation<=0),
                    unique_observations=(now_pos-old_pos+1).astype(np.int32),
                    actual_seconds=times[safe_now]-times[safe_old],ret_bp=displacement/prices[safe_old]*10000.,
                    displacement=displacement,total_variation=variation,efficiency=efficiency)
        if lane=='I1':
            values.update(bid_change_ticks=(record['bid'][safe_now]-record['bid'][safe_old])/record['tick'],
                          ask_change_ticks=(record['ask'][safe_now]-record['ask'][safe_old])/record['tick'])
        else:
            old_seq=seq[safe_old].copy();old_seq[old_index<0]=-1
            values.update(old_seq=old_seq,now_seq=raw_seq.copy())
        for field in ('actual_seconds','ret_bp','displacement','total_variation','bid_change_ticks','ask_change_ticks'):
            if field in values:values[field][~usable]=np.nan
        values['unique_observations'][~usable]=0
        if lane=='I2':values['unique_observations']=old['windows'][seconds]['unique_observations'].copy()
        result['windows'][seconds]=values
        if seconds not in RANGES:continue
        high,low=bounds(first_values,old_pos,now_pos)
        observations=(now_pos-old_pos).astype(np.int32)
        range_ok=usable&(observations>=2)&np.isfinite(high)&np.isfinite(low)
        if lane=='I2':range_ok&=old['ranges'][seconds]['source_valid']
        width=high-low;position=np.full(size,np.nan)
        position_ok=range_ok&(width>0)
        position[position_ok]=(prices[safe_now][position_ok]-low[position_ok])/width[position_ok]
        values=dict(old=old_index.copy(),now=now.copy(),source_valid=range_ok,position_valid=position_ok,
                    unique_observations=observations,high=high,low=low,width=width,position=position,
                    first_time=times[safe_old],last_time=times[first[np.maximum(now_pos-1,0)]])
        suffix='ticks' if lane=='I1' else 'points'
        divisor=record['tick'] if lane=='I1' else 1.
        values['high_distance_'+suffix]=(prices[safe_now]-high)/divisor
        values['low_distance_'+suffix]=(prices[safe_now]-low)/divisor
        for field in ('high','low','width','high_distance_'+suffix,'low_distance_'+suffix,'first_time','last_time'):
            values[field][~range_ok]=np.nan
        values['unique_observations'][~range_ok]=0
        result['ranges'][seconds]=values
    return result


def scan(key: tuple,execution: dict,expected_lp: dict,diagnosis: dict) -> tuple:
    """
    機能: 全原行を独立読取し、LP系列・識別・価格時計・旧執行気配を全件照合する。
    引数: key(tuple)、execution/expected_lp/diagnosis(dict)。
    返り値: tuple、独立LP、独立中値素材、診断dict。元素材を書き換えない。
    """
    path=ROOT/'book'/key[1]/(key[0]+'.jsonl')
    sequence=[];times=[];prices=[];reasons=[];missing=[]
    previous_clock=-math.inf;previous_saved=None;pending=0;pointer=0
    bqty=np.full(len(execution['seq']),np.nan);aqty=bqty.copy()
    count=outside=invalid=0;identity=None;hasher=hashlib.sha256()
    with path.open('rb') as stream:
        for seq,line in enumerate(stream):
            hasher.update(line);count+=1
            raw=json.loads(line);assert isinstance(raw,dict),(key,seq)
            actual_id={field:raw.get(field) for field in ('Symbol','SymbolName','Exchange')}
            assert all(value is not None for value in actual_id.values()),(key,seq,actual_id)
            if identity is None:identity=actual_id
            assert actual_id==identity==diagnosis['識別'],(key,seq,'識別')
            stamp=clock(raw.get('CurrentPriceTime'));last=positive(raw.get('CurrentPrice'))
            if pointer<len(bqty) and seq==execution['seq'][pointer]:
                assert stamp==execution['time_s'][pointer] and last==execution['price'][pointer],(key,seq,'時計又はLP')
                bid=raw.get('Buy1') or {};ask=raw.get('Sell1') or {}
                assert bid.get('Price')==execution['bid'][pointer] and ask.get('Price')==execution['ask'][pointer],(key,seq,'最良価格')
                bqty[pointer]=positive(bid.get('Qty'));aqty[pointer]=positive(ask.get('Qty'))
                assert math.isfinite(bqty[pointer]) and math.isfinite(aqty[pointer]),(key,seq,'数量')
                pointer+=1
            if not math.isfinite(stamp):missing.append(seq);pending|=4;continue
            assert stamp>=previous_clock,(key,seq,'逆行')
            previous_clock=stamp
            if not execution['start']<=stamp<execution['end']:outside+=1;pending|=8;continue
            reason=pending
            if previous_saved is None:reason|=1
            elif seq-previous_saved!=1:reason|=2
            sequence.append(seq);times.append(stamp);prices.append(last);reasons.append(reason)
            previous_saved=seq;pending=0;invalid+=not math.isfinite(last)
    assert pointer==len(execution['seq'])
    reset_reason=np.asarray(reasons,np.uint8)
    lp=dict(seq=np.asarray(sequence,np.int64),time_s=np.asarray(times,float),last=np.asarray(prices,float),
            valid=np.isfinite(prices)&(np.asarray(prices)>0),reset=reset_reason!=0,reset_reason=reset_reason,
            source_kind='原本CurrentPriceのみ',start=execution['start'],end=execution['end'],
            diagnostic=dict(読取原本行=count,保存時計行=len(sequence),時計欠測=len(missing),場外=outside,
                            価格不正=invalid,板参照=0,損益計算=0))
    equal(expected_lp,lp,'原LP/'+str(key))
    assert hasher.hexdigest()==diagnosis['原本SHA256'] and count==diagnosis['原本行数']
    bid=execution['bid'];ask=execution['ask'];tick=execution['tick'];seq=execution['seq']
    valid=(np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)&(ask-bid<=2*tick+1e-9)
           &np.isfinite(bqty)&np.isfinite(aqty)&(bqty>0)&(aqty>0))
    reason=np.zeros(len(seq),np.uint8);reason[0]=1;reason[1:]=np.where(np.diff(seq)!=1,2,0)
    mid=(bid+ask)/2.;mid[~valid]=np.nan
    qualities=dict(valid=valid,reset=reason!=0,reset_reason=reason,mid=mid,
                   first=np.r_[True,np.zeros(len(seq)-1,bool)],sequence_gap=(reason&2)!=0,
                   clock_reverse=np.zeros(len(seq),bool),best_price_or_quantity_invalid=~valid)
    mid_record=dict(seq=seq,time_s=execution['time_s'],values=mid,valid=valid,reset=reason!=0,
                    reset_reason=reason,bid=bid,ask=ask,last=execution['price'],tick=tick,
                    bid_qty=bqty,ask_qty=aqty,price_quality=qualities)
    lp_record=dict(seq=lp['seq'],time_s=lp['time_s'],values=lp['last'],valid=lp['valid'],reset=lp['reset'])
    missing=np.asarray(missing,np.int64)
    result=dict(場=key[0],商品=key[1],原本行数=count,LP保存行=len(sequence),旧執行行数=pointer,
                原本SHA256=hasher.hexdigest(),原本識別=identity,
                時計欠測前初回=int((missing<sequence[0]).sum()),
                時計欠測保存区間内=int(((missing>=sequence[0])&(missing<=sequence[-1])).sum()),
                時計欠測後最終=int((missing>sequence[-1]).sum()),
                原本全行と旧執行列一致=True,LP有効旗及び欠測切断一致=True)
    COUNTS['原本行']+=count;COUNTS['旧執行行']+=pointer;COUNTS['LP保存行']+=len(sequence)
    return lp_record,mid_record,result


def clip_record(record: dict,cut: int) -> dict:
    """
    機能: 特定価格系列の先頭だけを独立切断し、名前空間を保つ。
    引数: record(dict)、cut(int)。
    返り値: dict、対象系列の配列だけ切断した素材。
    """
    n=len(record['seq'])
    return {key:value[:cut].copy() if isinstance(value,np.ndarray) and len(value)==n else value for key,value in record.items()}


def grid_clip(value: object,length: int,full_size: int) -> object:
    """
    機能: 保存出力の格子列だけを接頭区間へ切断する。
    引数: value(object)、length/full_size(int)。
    返り値: object、入力生行品質を除く格子出力。
    """
    if isinstance(value,dict):return {k:grid_clip(v,length,full_size) for k,v in value.items() if k!='price_quality'}
    if isinstance(value,np.ndarray) and len(value)==full_size:return value[:length]
    return value


def causal(key: tuple,grid: np.ndarray,mid: dict,lp: dict,lp_original: dict,lanes: dict,old: dict,core: object,last: object,generator: object) -> None:
    """
    機能: 各実セッションの複数接頭と自己・相手候補の未来価格変形を確認する。
    引数: key(tuple)、grid(ndarray)、mid/lp/lp_original/lanes/old(dict)、core/last/generator(object)。
    返り値: None、全格子接頭及び独立期待値を照合する。売買は実行しない。
    """
    for fraction in (.2,.5,.8):
        length=max(1,int(len(grid)*fraction));past=grid[:length];threshold=float(past[-1])
        cut_mid=int(np.searchsorted(mid['time_s'],threshold,side='left'))
        cut_lp=int(np.searchsorted(lp['time_s'],threshold,side='left'))
        assert cut_mid>0 and cut_lp>0
        small_mid=clip_record(mid,cut_mid);small_lp=clip_record(lp_original,cut_lp)
        ready=dict(seq=small_mid['seq'],time_s=small_mid['time_s'],tick=small_mid['tick'],last=small_mid['last'])
        book={k:small_mid[k] for k in ('bid','ask','last','bid_qty','ask_qty')}
        short_mid=core.price_features(past,1,ready,book)
        short_lp=last.last_price_features(past,1,small_lp)
        expected_mid=grid_clip(lanes['I1'],length,len(grid));expected_lp=grid_clip(lanes['I3'],length,len(grid))
        equal(grid_clip(short_mid,length,length),expected_mid,'実接頭I1/'+str(key))
        equal(short_lp,expected_lp,'実接頭I3/'+str(key))
        raw_ready=dict(seq=mid['seq'],time_s=mid['time_s'],tick=mid['tick'],last=mid['last'])
        future_book={k:mid[k].copy() for k in ('bid','ask','last','bid_qty','ask_qty')}
        for k in ('bid','ask','last'):future_book[k][cut_mid:]*=1.013
        future_book['bid_qty'][cut_mid:]*=7;future_book['ask_qty'][cut_mid:]*=.2
        changed_mid=core.price_features(past,1,raw_ready,future_book)
        future_lp={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in lp_original.items()}
        future_lp['last'][cut_lp:]*=.983
        changed_lp=last.last_price_features(past,1,future_lp)
        equal(grid_clip(changed_mid,length,length),expected_mid,'実未来価格変形I1/'+str(key))
        equal(changed_lp,expected_lp,'実未来価格変形I3/'+str(key))
        COUNTS['実接頭価格系列']+=2;COUNTS['実未来変形価格系列']+=2


def deny(*args: object,**kwargs: object) -> None:
    """
    機能: 監査からのネットワーク接続を拒絶する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None、常に停止する。
    """
    raise RuntimeError('保存原本だけの監査です')


def spread_conflict(grid: np.ndarray,mid: dict,actual: dict,key: tuple) -> dict:
    """
    機能: 初版が正常な途中広気配を価格断裂へ転用した交絡を独立に数値化する。
    引数: grid(ndarray)、mid/actual(dict)、key(tuple)。
    返り値: dict、旧端点上限と途中経路資格を区別した不一致数及び具体例。
    """
    semantic={**mid}
    semantic['valid']=(np.isfinite(mid['bid'])&np.isfinite(mid['ask'])&(mid['bid']>0)&(mid['ask']>mid['bid'])
                       &np.isfinite(mid['bid_qty'])&np.isfinite(mid['ask_qty'])&(mid['bid_qty']>0)&(mid['ask_qty']>0))
    semantic['endpoint_valid']=mid['valid']
    semantic['values']=(mid['bid']+mid['ask'])/2.
    semantic['values'][~semantic['valid']]=np.nan
    expected=oracle(grid,semantic,'I1')
    difference={}
    examples=[]
    wide=semantic['valid']&~semantic['endpoint_valid']
    for seconds in WINDOWS:
        old=actual['windows'][seconds]['source_valid'];new=expected['windows'][seconds]['source_valid']
        affected=np.flatnonzero(new&~old)
        difference[str(seconds)]=len(affected)
        if not len(affected) or len(examples)>=3:continue
        row=int(affected[0]);left=int(expected['windows'][seconds]['old'][row]);right=int(expected['windows'][seconds]['now'][row])
        inter=np.flatnonzero(wide[left+1:right+1])+left+1
        examples.append(dict(窓秒=seconds,判断格子=float(grid[row]),旧端点原seq=int(mid['seq'][left]),
                             現在端点原seq=int(mid['seq'][right]),途中正常広気配数=len(inter),
                             広気配原seq=[int(mid['seq'][i]) for i in inter[:4]],
                             旧端点幅=float((mid['ask'][left]-mid['bid'][left])/mid['tick']),
                             現在端点幅=float((mid['ask'][right]-mid['bid'][right])/mid['tick']),
                             中途幅=[float((mid['ask'][i]-mid['bid'][i])/mid['tick']) for i in inter[:4]],
                             初版断裂=True,旧端点上限を維持した経路資格では断裂しない=True))
        assert len(inter)>0,(key,seconds,row)
    COUNTS['初版広気配交絡の窓格子']+=sum(difference.values())
    return dict(正常途中広気配の原行=int(wide.sum()),交絡で不明にした窓格子=difference,具体例=examples)


def main() -> None:
    """
    機能: 新62価格素材の独立検算証跡を新監査フォルダへ保存する。
    引数: なし。
    返り値: None、JSON一つ。正式損益・元素材・凍結資料を変更しない。
    """
    socket.socket.connect=deny;socket.create_connection=deny
    metadata=load(WORK/'prepared/metadata.json')
    sources={**metadata['旧入力SHA256'],**metadata['新コードSHA256'],**metadata['新入力SHA256']}
    sources[str((WORK/'prepared/metadata.json').relative_to(ROOT))]=digest(WORK/'prepared/metadata.json')
    for relative,expected in sources.items():assert digest(ROOT/relative)==expected,relative
    material=module('監査専用旧93素材',ROOT/'work/wave_v93/data.py').load_inputs()
    lanes=load(WORK/'prepared/price_lanes.pkl');raw_lp=load(WORK/'prepared/raw_last_records.pkl')
    core=module('監査対象価格部品94',WORK/'inputs/core.py')
    last=module('監査対象LP部品94',WORK/'inputs/last_price.py')
    generator=module('監査対象価格準備94',WORK/'prepare_inputs.py')
    diagnoses={(v['場'],v['商品']):v for v in metadata['素材取得診断']}
    assert len(material['prices'])==len(raw_lp)==len(diagnoses)==62
    rows=[]
    for key,execution in sorted(material['prices'].items()):
        lp,mid,review=scan(key,execution,raw_lp[key],diagnoses[key])
        grid=material['grids'][key[0]]['grid'];old=material['grids'][key[0]]['markets'][key[1]]
        assert (np.diff(execution['time_s'])>=0).all() and (np.diff(lp['time_s'])>=0).all()
        old_record=dict(seq=execution['seq'],time_s=execution['time_s'],values=execution['price'],
                        valid=execution['price_valid'],reset=material['features'][key]['reset'])
        actual_lanes={kind:lanes[kind][key[0]]['markets'][key[1]] for kind in ('I1','I2','I3')}
        for kind,record in (('I1',mid),('I2',old_record),('I3',lp)):
            np.testing.assert_array_equal(lanes[kind][key[0]]['grid'],grid)
            expected=oracle(grid,record,kind,old)
            equal(actual_lanes[kind],expected,str(key)+'/'+kind)
            valid=expected['current']['valid']
            assert (expected['current']['time_s'][valid]<grid[valid]-1.).all()
            COUNTS['全格子価格系列']+=1
            COUNTS['価格現在格子']+=len(grid)
            COUNTS['価格窓格子']+=len(grid)*len(WINDOWS)
            COUNTS['価格高安格子']+=len(grid)*len(RANGES)
        causal(key,grid,mid,lp,raw_lp[key],actual_lanes,old,core,last,generator)
        review['初版I1の広気配交絡']=spread_conflict(grid,mid,actual_lanes['I1'],key)
        review.update(全3価格系全格子独立期待値一致=True,複数実接頭と未来価格変形一致=True,
                      中値index名前空間='旧執行retained板系列',LPindex名前空間='全原本LP系列',
                      旧Q及びflow='素材SHAを前後照合し、価格素材へ上書きしない')
        rows.append(review)
        print(f'{key[0]} {key[1]} 独立原本{review["原本行数"]:,}・I1/I2/I3全格子・実接頭3点合格',flush=True)
    for relative,expected in sources.items():assert digest(ROOT/relative)==expected,('監査途中変更',relative)
    result=dict(全検査合格=False,保存素材の数値及び未来検査合格=True,
                理論不合格='初版I1は端点の2呼値上限を途中経路へ広げる追加交絡。修正版は別領域で監査が必要。',
                全31既知=True,新未見場数=0,口座数=62,価格系列数=186,
                独立検算=dict(COUNTS),場別検算=rows,
                価格源と旧BBO源の名前空間分離=True,旧素材及びQFlow変更=0,
                素材窓期待値に対象実装を使用=0,現在API取得=0,実注文=0,売買実行=0,新損益計算=0,
                限界=['CurrentPriceTimeは約定代理時計で真の受信時計ではない。',
                      '入力可用性や未来不変だけで方向予測又は収益の有効性を認定しない。',
                      '保存原行seq連続は配信の全イベント取得を保証しない。'],
                SHA256={**sources,str(Path(__file__).relative_to(ROOT)):digest(Path(__file__))})
    output=HERE/'初版全62原本と3価格系の独立検算及び広気配交絡の不合格.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('初版全62原本・186価格系の数値検算完了。I1理論交絡は不合格、売買・損益0。',flush=True)


if __name__=='__main__':main()
