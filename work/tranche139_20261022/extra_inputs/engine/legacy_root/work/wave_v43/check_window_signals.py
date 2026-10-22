"""固定窓合議を売買損益なしで生成し、旧入口・公開順・未来独立性を検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import pickle
import socket
import urllib.request

import numpy as np
import pandas as pd

import window_signals as signals


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SYMBOLS=('TOPIX','NK225')


def sha(path: Path) -> str:
    """機能: 入出力と原本の不変性を内容指紋で確認する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8388608):value.update(block)
    return value.hexdigest()


def save(path: Path, value: dict) -> None:
    """機能: 有限な日本語の監査証跡を保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存入力の監査からの通信を拒否する。

    引数: 任意 (object)。返り値: なし (None)、例外。
    """
    raise AssertionError('この監査で新しいデータは取得しません')


def synthetic() -> dict:
    """機能: 27票組合せ・対称性・部分集合・母数維持と同秒順序を検査する。

    引数: なし。返り値: 人工検査の全結果 (dict)。
    """
    votes=np.asarray(list(itertools.product((-1,0,1),repeat=3)),np.int8)
    expected={}
    for mode in ('M2','V2','U3'):
        rows=[]
        for row in votes.tolist():
            output=0
            for side in (-1,1):
                count=row.count(side)
                if mode=='M2' and count>=2:output=side
                if mode=='V2' and count>=2 and -side not in row:output=side
                if mode=='U3' and count==3:output=side
            rows.append(output)
        expected[mode]=np.asarray(rows,np.int8)
        np.testing.assert_array_equal(signals.combine(votes,mode),expected[mode])
        np.testing.assert_array_equal(signals.combine(-votes,mode),-expected[mode])
        for permutation in itertools.permutations(range(3)):
            np.testing.assert_array_equal(signals.combine(votes[:,permutation],mode),expected[mode])
    np.testing.assert_array_equal(expected['M2'],np.median(votes,axis=1).astype(np.int8))
    for left,right in (('U3','V2'),('V2','M2')):
        active=expected[left]!=0
        np.testing.assert_array_equal(expected[left][active],expected[right][active])
    assert signals.combine(np.array([[1,0,0],[-1,0,0]],np.int8),'M2').tolist()==[0,0]
    assert signals.combine(np.array([[1,1,-1],[-1,-1,1]],np.int8),'M2').tolist()==[1,-1]
    assert signals.combine(np.array([[1,1,-1],[-1,-1,1]],np.int8),'V2').tolist()==[0,0]
    rejected=0
    for values,mode in ((np.zeros((2,2)),'M2'),(np.array([[1,1,np.nan]]),'M2'),
                        (np.array([[1,1,2]]),'M2'),(votes,'中央値')):
        try:signals.combine(values,mode)
        except ValueError:rejected+=1
    assert rejected==4
    # ----------------------------------------
    # 同じ時計時刻の後続seqで初めて公開される入口を前行へ広げない。
    raw_seq=np.array([10,11,12],np.int64);raw_time=np.array([100.,100.,101.])
    actual,_,_=signals.HIERARCHY._entry_filter(raw_seq,raw_time,np.ones(3,np.int8),
        np.array([11],np.int64),np.array([100.]),np.ones(1,np.int8),np.array([.1]),np.ones(1),1,1.)
    np.testing.assert_array_equal(actual,[0,1,1])
    member_matrix=np.column_stack([actual,actual,actual])
    for mode in ('M2','V2','U3'):
        np.testing.assert_array_equal(signals.combine(member_matrix,mode),[0,1,1])
    models={('人工','TOPIX'):dict(time_s=np.array([0.]),direction=np.array([1])),
            ('人工','NK225'):dict(time_s=np.array([10.]),direction=np.array([1]))}
    params=signals.BASE['params']
    np.testing.assert_array_equal(signals.HIERARCHY._allowed(('人工','TOPIX'),np.array([69.999,70.]),models,params),[0,1])
    rounding={scale:[signals.HIERARCHY._size(v*scale) for v in (15,60,3,30)] for scale in signals.SCALES}
    assert list(rounding.values())==[[10,38,2,19],[12,48,2,24],[14,58,3,29],[15,60,3,30],[18,72,4,36],[22,86,4,43]]
    return dict(全合格=True,全27組合せの3方式一致=True,中央値M2同一=True,反射対称=True,
        全6票順不変=True,中立を母数3へ残す=True,部分集合は方向だけ=True,不正入力4拒否=True,
        同時刻後続seqの先行なし=True,相手60秒の境界一致=True,丸め窓={str(k):v for k,v in rounding.items()})


def slice_inputs(inputs: dict, features: dict, counts: dict) -> tuple[dict,dict]:
    """機能: 原本行と既公開特徴の双方を短縮し、未来列を実際に取り除く。

    引数: inputs/features/counts (dict)。返り値: 短縮入力と特徴 (tuple[dict,dict])。
    """
    out,frames={},{}
    for key,ready in inputs.items():
        count=counts[key];total=len(ready['seq']);assert 0<count<=total
        out[key]={name:value[:count].copy() if isinstance(value,np.ndarray) and value.ndim and len(value)==total else value
            for name,value in ready.items()}
        frames[key]=features[key].loc[(features[key].seq<=out[key]['seq'][-1]) & (features[key].time_s<=out[key]['time_s'][-1])].copy()
    return out,frames


def transformed(inputs: dict, features: dict, cutoff: float | None) -> tuple[dict,dict,dict]:
    """機能: cutoff以後を改変、又は全価格と売買側を反射する新しい入力を作る。

    引数: inputs/features (dict)、cutoff (float|None)。Noneは上下反射。
    返り値: 原本入力・公開特徴・市場別反射軸 (tuple[dict,dict,dict])。
    """
    out,frames,pivots={},{},{}
    for key,ready in inputs.items():
        value=dict(ready);frame=features[key].copy();pivot=float(ready['last'][0]);pivots[key]=pivot
        if cutoff is not None:
            future=ready['time_s']>=cutoff
            for column in ('last','atr'):
                value[column]=ready[column].copy();value[column][future]=ready[column][future]*1.7+700
            mask=frame.time_s>=cutoff
            for column in frame.select_dtypes(include='number').columns:
                if 'seq' in column or 'time' in column:continue
                frame[column]=frame[column].astype(float)
                frame.loc[mask,column]=frame.loc[mask,column]*1.7+700
        else:
            value['last']=2*pivot-ready['last']
            for bid,ask in (('bid','ask'),('source_bid_last','source_ask_last')):
                frame[bid],frame[ask]=2*pivot-features[key][ask],2*pivot-features[key][bid]
            for column in ('mid','source_mid_last'):frame[column]=2*pivot-features[key][column]
            for column in ('imb1','imb5','imb10','micro_bias','ofi_signed','quote_move_ticks','dflow_near','dflow_far','pressure_near','pressure_far'):
                if column in frame:frame[column]=-features[key][column]
            for first,second in (('bid_qty','ask_qty'),('quote_up','quote_down'),('added_bid','added_ask'),
                                ('removed_bid','removed_ask'),('trade_pos','trade_neg'),('refill_bid','refill_ask')):
                if first in frame:frame[first],frame[second]=features[key][second].copy(),features[key][first].copy()
        out[key]=value;frames[key]=frame
    return out,frames,pivots


def candle_copy(keys: list, label: str, cutoff: float | None, pivots: dict | None) -> Path:
    """機能: 原本を変更せず、未来足変更又は全足反射の作業用複写を作る。

    引数: keys (list[tuple])、label (str)、cutoff (float|None)、pivots (dict|None)。
    返り値: 監査複写の参照根 (Path)。足の始点+120秒を公開時刻とする。
    """
    output=(HERE/'audit_candles'/label).resolve()
    assert output.is_relative_to((HERE/'audit_candles').resolve())
    for key in keys:
        frame=pd.read_csv(ROOT/'candle_1min'/key[1]/(key[0]+'.csv'))
        if cutoff is not None:
            release=pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
            mask=release>=cutoff
            for column in ('open','high','low','close','volume'):
                frame[column]=frame[column].astype(float);frame.loc[mask,column]=frame.loc[mask,column]*1.7+7000
            frame.loc[mask,'closed']=True
            if 'volume_complete' in frame:frame.loc[mask,'volume_complete']=True
        if pivots is not None:
            pivot=pivots[key];high=frame.high.copy();low=frame.low.copy()
            for column in ('open','close'):frame[column]=2*pivot-frame[column]
            frame['high'],frame['low']=2*pivot-low,2*pivot-high
        target=output/'candle_1min'/key[1]/(key[0]+'.csv')
        target.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(target,index=False,encoding='utf-8')
    return output


def calculate(inputs: dict, features: dict, root: Path) -> dict:
    """機能: キャッシュを捨て、指定原本・板・足から全12入口を再計算する。

    引数: inputs/features (dict)、root (Path)。返り値: ID別の全方向 (dict)。
    """
    signals.set_root(root)
    return {spec['id']:signals.build(spec,inputs,features) for spec in signals.catalog()}


def main() -> None:
    """機能: 全12×26の因果検査、既存3倍率一致、固定NPZを売買なしで作る。

    引数: なし。返り値: なし (None)。不一致なら固定完了を保存しない。
    """
    socket.create_connection=deny;socket.socket.connect=deny;urllib.request.urlopen=deny
    proof=synthetic();save(HERE/'signal_synthetic.json',proof)
    catalog=signals.catalog()
    protocol=dict(全入口数=12,構成倍率=list(signals.SCALES),条件=catalog,主='M2_100',
        数値条件='H019のclockだけを変更。floor(x+0.5)丸め、peer60秒/公開120秒/開始20分/入口保持120秒は固定。',
        合議='固定3票。M2は同方向2以上、V2はそれと反対0、U3は全3同方向。中立票を除かない。追加保持なし。',
        旧固定照合の迂回='旧buildは旧カタログと単一±20%のみ許可。新倍率は新固定集合で検査し旧内部関数を同じ順で呼ぶ。旧関数・仕様の一時置換はしない。',
        検査=dict(旧入口3倍率全26=78,共通時刻prefix全12全26=312,未来改変全12全26=312,反射全12全26=312,同時刻途中seq全12全26=312),
        切断='各セッション両市場を同じ時計37%で切断。未来変更は73%以後の価格ATR・公開板・足。別に各市場73%付近の同時刻群途中でseq切断。',
        新売買損益未実行=True,成績による閾値変更なし=True,現在API取得数=0)
    save(HERE/'signal_protocol.json',protocol)
    reference_paths=[HERE/'window_signals.py',Path(__file__),HERE/'signal_protocol.json',HERE/'signal_synthetic.json',
        ROOT/'work/wave_v27/hierarchy_signals.py',ROOT/'work/wave_v27/hierarchy_design_fixed.json',
        ROOT/'work/wave_v23/signals.py',ROOT/'work/wave_v23/inputs.pkl',ROOT/'work/wave_v23/features_depth.pkl']
    reference_paths += [ROOT/f'work/wave_v35/entries/H019__C{code}.npz' for code in ('080','100','120')]
    before={p.relative_to(ROOT).as_posix():sha(p) for p in reference_paths}
    raw_expected=json.loads((ROOT/'work/wave_v42/探索条件の固定.json').read_text(encoding='utf-8'))['原本78SHA256']
    assert len(raw_expected)==78
    for path,value in raw_expected.items():assert sha(ROOT/path)==value,path
    inputs=pickle.loads((ROOT/'work/wave_v23/inputs.pkl').read_bytes())
    features=pickle.loads((ROOT/'work/wave_v23/features_depth.pkl').read_bytes())
    assert len(inputs)==26
    baseline=calculate(inputs,features,ROOT)
    members={scale:signals.member_directions(scale,inputs,features) for scale in signals.SCALES}
    equality=[]
    for scale in (.8,1.,1.2):
        old=deepcopy(signals.BASE) if scale==1. else next(row for row in signals.HIERARCHY.neighbor_specs(signals.BASE)
            if row['diagnostic_category']=='clock' and row['params']['clock_multiplier']==scale)
        actual=signals.HIERARCHY.build(old,inputs,features)
        with np.load(ROOT/f'work/wave_v35/entries/H019__C{round(scale*100):03d}.npz') as archived:
            assert set(archived.files)=={'|'.join(key) for key in inputs}
            for key in sorted(inputs):
                np.testing.assert_array_equal(members[scale][key],actual[key])
                np.testing.assert_array_equal(members[scale][key],archived['|'.join(key)])
                equality.append(dict(clock=scale,session=key[0],symbol=key[1],全行=len(actual[key]),旧再生成完全一致=True,旧保存完全一致=True))
    rows=[];prefix_count=future_count=reflection_count=tie_count=0
    for session in sorted({key[0] for key in inputs}):
        keys=[(session,symbol) for symbol in SYMBOLS];own={key:inputs[key] for key in keys};frames={key:features[key] for key in keys}
        start=max(v['start'] for v in own.values());end=min(v['time_s'][-1] for v in own.values())
        cut=start+(end-start)*.37
        counts={key:int(np.searchsorted(ready['time_s'],cut,side='left')) for key,ready in own.items()}
        short_input,short_features=slice_inputs(own,frames,counts)
        partial=calculate(short_input,short_features,ROOT)
        future_cut=start+(end-start)*.73
        future_input,future_features,_=transformed(own,frames,future_cut)
        future_root=candle_copy(keys,'future_'+session,future_cut,None)
        future=calculate(future_input,future_features,future_root)
        mirror_input,mirror_features,pivots=transformed(own,frames,None)
        mirror_root=candle_copy(keys,'reflection_'+session,None,pivots)
        mirror=calculate(mirror_input,mirror_features,mirror_root)
        for spec in catalog:
            for key in keys:
                identifier=spec['id'];target=baseline[identifier][key]
                future_size=int(np.searchsorted(own[key]['time_s'],future_cut,side='left'))
                np.testing.assert_array_equal(partial[identifier][key],target[:counts[key]])
                np.testing.assert_array_equal(future[identifier][key][:future_size],target[:future_size])
                np.testing.assert_array_equal(mirror[identifier][key],-target)
                prefix_count+=1;future_count+=1;reflection_count+=1
                rows.append(dict(id=identifier,session=key[0],symbol=key[1],全行=len(target),prefix行=counts[key],future行=future_size,
                    prefix一致=True,未来価格ATR板足変更一致=True,上下反射一致=True))
        # ----------------------------------------
        # 相手を切らず、自市場の同じ時計群の途中だけを原本seqで切断する。
        for key in keys:
            ready=own[key];times=ready['time_s'];duplicates=np.flatnonzero(times[1:]==times[:-1])+1
            duplicates=duplicates[(duplicates>1)&(duplicates<len(times)-1)]
            assert len(duplicates)>0
            count=int(duplicates[np.argmin(np.abs(duplicates-int(len(times)*.73)))])
            assert times[count-1]==times[count]
            keep={other:len(own[other]['seq']) for other in keys};keep[key]=count
            tie_input,tie_features=slice_inputs(own,frames,keep)
            tied=calculate(tie_input,tie_features,ROOT)
            for spec in catalog:
                identifier=spec['id'];np.testing.assert_array_equal(tied[identifier][key],baseline[identifier][key][:count])
                row=next(r for r in rows if r['id']==identifier and (r['session'],r['symbol'])==key)
                row.update(同時刻切断一致=True,同時刻切断行=count,同時刻=float(times[count]),最終許可seq=int(ready['seq'][count-1]))
                tie_count+=1
        print(session+'：全12×両市場のprefix/未来/反射/同秒seqが一致',flush=True)
    assert (prefix_count,future_count,reflection_count,tie_count)==(312,312,312,312)
    signals.set_root(ROOT)
    # ----------------------------------------
    # 各構成票の実際の組合せも保存し、活動や相関を独立情報と呼ばない。
    participation=[]
    for spec in catalog:
        for key,ready in sorted(inputs.items()):
            matrix=np.column_stack([members[scale][key] for scale in spec['scales']])
            unique,counts=np.unique(matrix,axis=0,return_counts=True)
            state=baseline[spec['id']][key]
            durations=np.maximum(0.,np.diff(ready['time_s'],append=ready['time_s'][-1]))
            participation.append(dict(id=spec['id'],session=key[0],symbol=key[1],全行=len(state),
                同時刻0秒行数=int((durations==0).sum()),非中立行数=int((state!=0).sum()),
                買い秒=float(durations[state==1].sum()),売り秒=float(durations[state==-1].sum()),
                中立秒=float(durations[state==0].sum()),票組合せ=[dict(票=u.tolist(),行数=int(n)) for u,n in zip(unique,counts)]))
    save(HERE/'signal_participation.json',dict(全312=True,結果=participation,損益ではない=True))
    outputs={}
    for folder,values in (('entries',baseline),('members',{f'C{round(scale*100):03d}':value for scale,value in members.items()})):
        (HERE/folder).mkdir(exist_ok=True)
        for name,directions in values.items():
            path=HERE/folder/(name+'.npz')
            np.savez_compressed(path,**{'|'.join(key):direction for key,direction in sorted(directions.items())})
            with np.load(path) as archive:
                for key,value in directions.items():np.testing.assert_array_equal(archive['|'.join(key)],value)
            outputs[path.relative_to(ROOT).as_posix()]=sha(path)
    for path,value in before.items():assert sha(ROOT/path)==value,path
    for path,value in raw_expected.items():assert sha(ROOT/path)==value,path
    before['work/wave_v42/探索条件の固定.json']=sha(ROOT/'work/wave_v42/探索条件の固定.json')
    outputs['work/wave_v43/signal_participation.json']=sha(HERE/'signal_participation.json')
    audit=dict(全合格=True,全入口数=12,構成倍率数=6,全入力数=26,全方向セル数=312,旧3倍率完全一致数=len(equality),
        prefix数=prefix_count,future数=future_count,reflection数=reflection_count,同時刻切断数=tie_count,
        人工=proof,旧一致=equality,検査=rows,参照SHA256=before,出力SHA256=outputs,原本78SHA256=raw_expected,
        原本不変=True,旧実装不変=True,売買再生=False,新損益読取=False,現在API取得数=0,保存ライブ使用=False)
    save(HERE/'signal_audit.json',audit)
    fixed=dict(全合格=True,全入力監査合格=True,全入口数=12,全方向セル数=312,条件=catalog,規則=protocol,
        SHA256={**before,**outputs,'work/wave_v43/signal_audit.json':sha(HERE/'signal_audit.json')},
        参照資料SHA256={**before,'work/wave_v43/signal_audit.json':sha(HERE/'signal_audit.json')},
        入口保存列SHA256={path:value for path,value in outputs.items() if '/entries/' in path},
        構成窓保存列SHA256={path:value for path,value in outputs.items() if '/members/' in path},
        原本78SHA256=raw_expected,売買再生=False,新損益読取=False,現在API取得数=0)
    save(HERE/'signals_fixed.json',fixed)
    print(json.dumps(dict(全合格=True,入口12=True,全方向セル312=True,旧一致78=True,prefix=312,future=312,reflection=312,同秒=312),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
