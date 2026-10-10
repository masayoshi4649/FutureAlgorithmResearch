"""EMAだけ履歴継続する12入口を、旧初期化12入口と因果性で照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np
import pandas as pd

import warm_component_signals as signals


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE.parent/'wave_v43'))
from check_window_signals import slice_inputs,transformed


def sha(path: Path) -> str:
    """機能: 旧入力・新旧実装と保存列の内容指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8388608):
            h.update(block)
    return h.hexdigest()


def save(path: Path,value: dict) -> None:
    """機能: 非有限値を拒否して日本語の検査記録を保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


def deny(*args: object,**kwargs: object) -> None:
    """機能: 新データ取得を明示的に拒否する。

    引数: 任意 (object)。返り値: なし (None)、例外。
    """
    raise AssertionError('新しいデータを取得しません')


def copied_root(keys: list,label: str,cutoff: float | None,pivots: dict | None) -> Path:
    """機能: 旧全26足を新作業へ複写し、将来だけ変更又は全履歴を反射する。

    引数: keys (list[tuple])、label (str)、cutoff (float|None)、pivots (dict[str,float]|None)。
    返り値: 複写足の参照根 (Path)。前場も後続場も同じ絶対公開時刻で分類する。
    """
    output=(HERE/'warm_audit_candles'/label).resolve()
    assert output.is_relative_to((HERE/'warm_audit_candles').resolve())
    for session,symbol in keys:
        assert session in signals.SESSIONS and session!='2026-09-29_Night'
        frame=pd.read_csv(ROOT/'candle_1min'/symbol/(session+'.csv'))
        if cutoff is not None:
            release=pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
            future=release>=cutoff
            for column in ('open','high','low','close','volume'):
                frame[column]=frame[column].astype(float)
                frame.loc[future,column]=frame.loc[future,column]*1.7+7000
            frame.loc[future,'closed']=True
            if 'volume_complete' in frame:
                frame.loc[future,'volume_complete']=True
        if pivots is not None:
            pivot=pivots[symbol]
            high,low=frame.high.copy(),frame.low.copy()
            for column in ('open','close'):
                frame[column]=2*pivot-frame[column]
            frame['high'],frame['low']=2*pivot-low,2*pivot-high
        target=output/'candle_1min'/symbol/(session+'.csv')
        target.parent.mkdir(parents=True,exist_ok=True)
        frame.to_csv(target,index=False,encoding='utf-8')
    return output


def calculate(inputs: dict,features: dict,root: Path) -> dict:
    """機能: 同じ参照根で暖機12入口を計算し、キャッシュを持ち越さない。

    引数: inputs/features (dict)、root (Path)。返り値: ID別方向列 (dict)。
    """
    signals.set_root(root)
    return {spec['id']:signals.build(spec,inputs,features) for spec in signals.catalog()}


def manual_main(ready: dict,scale: float) -> np.ndarray:
    """機能: pandasや主方向関数を呼ばず終値の逐次EMAから方向を照合する。

    引数: ready (dict)、scale (float)。返り値: 当場の公開足方向 (ndarray[int8])。
    """
    hierarchy=signals.RESET.HIERARCHY
    bars=hierarchy.LEGACY._bars(ready)
    past=signals.past_closes(ready)
    prices=np.r_[past,np.asarray(bars['close'],float)]
    fast,slow,slope_n=[max(1,int(np.floor(value*scale+.5))) for value in (15,60,3)]
    short=np.full(len(prices),np.nan)
    long=np.full(len(prices),np.nan)
    for span,values in ((fast,short),(slow,long)):
        mean=0.
        alpha=2./(span+1)
        for index,price in enumerate(prices):
            mean=price if index==0 else (1.-alpha)*mean+alpha*price
            if index+1>=span:
                values[index]=mean
    output=np.zeros(len(bars['atr']),np.int8)
    direction=0
    for row,atr in enumerate(bars['atr']):
        index=len(past)+row
        if not np.isfinite(atr) or atr<=0 or not np.isfinite(long[index]):
            direction=0
            continue
        gap=(short[index]-long[index])/atr
        slope=(long[index]-long[index-slope_n])/atr if index>=slope_n else np.nan
        if direction*gap<0:
            direction=0
        if gap>.15 and slope>.02:
            direction=1
        elif gap<-.15 and slope<-.02:
            direction=-1
        output[row]=direction
    return output


def main() -> None:
    """機能: 12暖機入口の旧対応・全履歴因果・独立EMAを損益なしで固定する。

    引数: なし。返り値: なし (None)。保存12入口は旧13セッションのみを含む。
    """
    socket.create_connection=deny
    socket.socket.connect=deny
    urllib.request.urlopen=deny
    protocol=dict(条件=signals.catalog(),対象セッション=list(signals.SESSIONS),
        履歴='当場より前の保存済み場のclosed=trueかつ時刻+120秒が当場開始より前の終値を全連結。最初の9/21デイは履歴なし。',
        継続='EMA短長と傾き計算だけ。場間の時間空白で減衰させず、次の確定足を次の1本と数える。',
        初期化='主方向保持状態、当場ATR、当場開始20分待機、相手60秒、短期30秒、短期TTL120秒は従来通り。',
        取引='入口列の検査だけ。建玉の持越しを許す変更ではなく、売買損益は計算しない。',
        検査='旧初期化12仕様の保存列一致、初日暖機なし一致、全26入力で途中切断・全後続足の未来改変・全履歴反射・同秒seq途中切断。',
        新ナイト読取=False,新売買損益読取=False,API取得数=0)
    references=[Path(__file__),HERE/'warm_component_signals.py',HERE/'component_signals.py',
        HERE/'component_signals_fixed.json',HERE.parent/'wave_v27/hierarchy_signals.py',
        HERE.parent/'wave_v27/hierarchy_design_fixed.json',HERE.parent/'wave_v23/signals.py',
        HERE.parent/'wave_v23/inputs.pkl',HERE.parent/'wave_v23/features_depth.pkl',
        HERE.parent/'wave_v43/check_window_signals.py']
    references += [HERE/'component_entries'/(spec['reset']['id']+'.npz') for spec in signals.catalog()]
    before={path.relative_to(ROOT).as_posix():sha(path) for path in references}
    protocol['参照SHA256']=before
    protocol_path=HERE/'warm_signal_protocol.json'
    if protocol_path.exists():
        assert json.loads(protocol_path.read_text(encoding='utf-8'))==protocol
    else:
        save(protocol_path,protocol)
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    features=pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    assert len(inputs)==26 and {key[0] for key in inputs}==set(signals.SESSIONS)
    for key in inputs:
        path=ROOT/'candle_1min'/key[1]/(key[0]+'.csv')
        before[path.relative_to(ROOT).as_posix()]=sha(path)
    baseline=calculate(inputs,features,ROOT)
    equality=[]
    history_info=[]
    reset_directions={}
    for spec in signals.catalog():
        reset=signals.RESET.build(spec['reset'],inputs,features)
        reset_directions[spec['id']]=reset
        with np.load(HERE/'component_entries'/(spec['reset']['id']+'.npz')) as archive:
            for key in inputs:
                np.testing.assert_array_equal(reset[key],archive['|'.join(key)])
                first=key[0]==signals.SESSIONS[0]
                if first:
                    np.testing.assert_array_equal(baseline[spec['id']][key],reset[key])
                equality.append(dict(id=spec['id'],session=key[0],symbol=key[1],旧初期化一致=True,初場暖機なし一致=first))
    assert len(equality)==312 and sum(value['初場暖機なし一致'] for value in equality)==24
    for key,ready in inputs.items():
        for scale in signals.RESET.SCALES:
            params=signals.RESET.legacy_spec(signals.RESET.specification(main_scale=scale))['params']
            model=signals.main_model(ready,params)
            np.testing.assert_array_equal(model['direction'],manual_main(ready,scale))
            history_info.append(dict(session=key[0],symbol=key[1],主窓=scale,過去足数=model['past_count'],逐次EMA独立一致=True))
    print('旧初期化312入力・初場24入力・独立逐次EMA78入力が一致',flush=True)
    rows=[]
    for session in signals.SESSIONS:
        keys=[(session,symbol) for symbol in ('TOPIX','NK225')]
        own={key:inputs[key] for key in keys}
        frames={key:features[key] for key in keys}
        start=max(value['start'] for value in own.values())
        end=min(value['time_s'][-1] for value in own.values())
        cut=start+(end-start)*.37
        counts={key:int(np.searchsorted(value['time_s'],cut,side='left')) for key,value in own.items()}
        truncated,tf=slice_inputs(own,frames,counts)
        partial=calculate(truncated,tf,ROOT)
        future_cut=start+(end-start)*.73
        changed,cf,_=transformed(own,frames,future_cut)
        future=calculate(changed,cf,copied_root(list(inputs),'future_'+session,future_cut,None))
        mirrored,mf,pivots=transformed(own,frames,None)
        symbol_pivots={key[1]:value for key,value in pivots.items()}
        reflected=calculate(mirrored,mf,copied_root(list(inputs),'reflection_'+session,None,symbol_pivots))
        for spec in signals.catalog():
            for key in keys:
                identifier=spec['id']
                original=baseline[identifier][key]
                future_size=int(np.searchsorted(own[key]['time_s'],future_cut,side='left'))
                np.testing.assert_array_equal(partial[identifier][key],original[:counts[key]])
                np.testing.assert_array_equal(future[identifier][key][:future_size],original[:future_size])
                np.testing.assert_array_equal(reflected[identifier][key],-original)
                rows.append(dict(id=identifier,session=key[0],symbol=key[1],prefix一致=True,
                    未来の当場後続場変更一致=True,過去当場の全履歴反射一致=True))
        for key in keys:
            times=own[key]['time_s']
            candidates=np.flatnonzero(times[1:]==times[:-1])+1
            candidates=candidates[(candidates>1)&(candidates<len(times)-1)]
            assert len(candidates)
            count=int(candidates[np.argmin(np.abs(candidates-int(len(times)*.73)))])
            keep={other:len(own[other]['seq']) for other in keys}
            keep[key]=count
            truncated,tf=slice_inputs(own,frames,keep)
            tied=calculate(truncated,tf,ROOT)
            for spec in signals.catalog():
                identifier=spec['id']
                np.testing.assert_array_equal(tied[identifier][key],baseline[identifier][key][:count])
                row=next(value for value in rows if value['id']==identifier and (value['session'],value['symbol'])==key)
                row.update(同秒切断一致=True,切断行=count)
        print(session+'：暖機12仕様のprefix・未来全足・全履歴反射・同秒seq一致',flush=True)
    assert len(rows)==312 and all(row.get('同秒切断一致') for row in rows)
    signals.set_root(ROOT)
    outputs={}
    comparisons=[]
    (HERE/'warm_entries').mkdir(exist_ok=True)
    for spec in signals.catalog():
        identifier=spec['id']
        path=HERE/'warm_entries'/(identifier+'.npz')
        np.savez_compressed(path,**{'|'.join(key):value for key,value in sorted(baseline[identifier].items())})
        outputs[path.relative_to(ROOT).as_posix()]=sha(path)
        for key,ready in sorted(inputs.items()):
            new=baseline[identifier][key]
            old=reset_directions[identifier][key]
            duration=np.maximum(0.,np.diff(ready['time_s'],append=ready['time_s'][-1]))
            earliest_new=np.flatnonzero(new)
            earliest_old=np.flatnonzero(old)
            first_hour=ready['time_s']<ready['start']+3600
            comparisons.append(dict(id=identifier,reset_id=spec['reset']['id'],session=key[0],symbol=key[1],
                異なる方向行数=int((new!=old).sum()),異なる方向秒=float(duration[new!=old].sum()),
                暖機の最初の方向開始秒=float(ready['time_s'][earliest_new[0]]-ready['start']) if len(earliest_new) else None,
                初期化の最初の方向開始秒=float(ready['time_s'][earliest_old[0]]-ready['start']) if len(earliest_old) else None,
                最初一時間の暖機非中立秒=float(duration[first_hour&(new!=0)].sum()),
                最初一時間の初期化非中立秒=float(duration[first_hour&(old!=0)].sum())))
    for path,digest in before.items():
        assert sha(ROOT/path)==digest,path
    save(HERE/'warm_signal_comparison.json',dict(売買損益ではない=True,全312対応=True,結果=comparisons))
    audit=dict(全合格=True,仕様数=12,入力数=26,方向セル数=312,旧初期化一致数=312,
        初場暖機なし一致数=24,逐次EMA独立一致数=78,prefix数=312,未来全足変更数=312,
        全履歴反射数=312,同秒切断数=312,旧一致=equality,履歴=history_info,検査=rows,
        参照SHA256=before,入口保存列SHA256=outputs,原本旧実装不変=True,
        売買再生=False,新ナイト読取=False,新売買損益読取=False,API取得数=0)
    save(HERE/'warm_signal_audit.json',audit)
    save(HERE/'warm_signals_fixed.json',dict(全合格=True,条件=signals.catalog(),規則=protocol,
        参照SHA256=before,入口保存列SHA256=outputs,
        監査SHA256=sha(HERE/'warm_signal_audit.json'),方向比較SHA256=sha(HERE/'warm_signal_comparison.json'),
        新損益未読=True,新ナイト未読=True))
    print('暖機12仕様：旧初期化312・初場24・独立EMA78・因果312×4が全一致',flush=True)


if __name__=='__main__':
    main()
