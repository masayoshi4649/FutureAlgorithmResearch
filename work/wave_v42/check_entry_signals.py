"""原本観測入口の接続を、人工・旧入口再現・全公開根拠で検査する。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket

import numpy as np

import design
import entry_signals as entry


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent/'wave_v40'
CHECKS = []


def sha(path: Path) -> str:
    """機能: 元資料を変更せず指紋を求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8*1024*1024):
            value.update(block)
    return value.hexdigest()


def write(name: str, value: dict) -> None:
    """機能: 今回領域だけへ有限JSONを保存する。

    引数: name(str)、value(dict)。返り値: なし(None)。
    """
    path = HERE/name
    assert path.resolve().is_relative_to(HERE)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def references(extra: tuple[Path, ...] = ()) -> dict:
    """機能: 今回検査が実際に利用する実体の指紋を列挙する。

    引数: extra(tuple[Path,...])。返り値: ルート相対参照(dict[str,str])。
    """
    paths = (HERE/'design.py', HERE/'entry_signals.py', Path(__file__),
             HERE/'比較計画.md', OLD/'entry_signals.py', OLD/'band_events.py')+extra
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}


def check(name: str, condition: bool) -> None:
    """機能: 条件が成立しない場合に検査を停止する。

    引数: name(str)、condition(bool)。返り値: なし(None)。
    """
    assert condition, name
    CHECKS.append(name)


def rejects(function: object) -> bool:
    """機能: 不正な公開根拠が明示的に拒否されるかを調べる。

    引数: function(callable)。返り値: 拒否したか(bool)。
    """
    try:
        function()
    except (ValueError, AssertionError, TypeError):
        return True
    return False


def point(index: int) -> dict:
    """機能: 人工公開と原本行の一貫した参照を作る。

    引数: index(int)。返り値: 公開参照(dict)。
    """
    return dict(event_index=index, ready_index=index, seq=index*10, time_s=float(index*10))


def fixture(u1: float | None = 1., u2: float | None = .5, weak: bool = True) -> tuple:
    """機能: 数量品質と価格弱化を独立に変更できる二試行人工帯を作る。

    引数: u1/u2(float|None)、weak(bool)。返り値: 入力・帯・新パネル・相手特徴(tuple)。
    """
    ready = dict(seq=np.arange(30, dtype=np.int64)*10, time_s=np.arange(30, dtype=float)*10)
    known = u1 is not None and u2 is not None
    feature = dict(two_trials_complete=True, price_comparable=True, quantity_comparable=known,
        u1=u1, u2=u2, b1=1., b2=.5 if weak else 1., price_weakens=weak,
        quantity_weakens=bool(u2<u1) if known else None,
        quantity_change=u2-u1 if known else None, pushback_change=-.5 if weak else 0.)
    trials = [dict(number=1, start=point(2), end=point(5), complete=True),
              dict(number=2, start=point(7), end=point(10), complete=True)]
    band = dict(band_id=1, direction=1, price=102., atr=10., tick=1., status='breakout',
        created=point(1), terminal=point(12), trials=trials, features=feature)
    observations = []
    for trial, ratio in zip(trials, (u1, u2)):
        publication = dict(release_seq=trial['end']['seq'], release_time_s=trial['end']['time_s'],
            ready_index=trial['end']['ready_index'], material_first_seq=trial['start']['seq'],
            material_last_seq=trial['end']['seq'], raw_row_count=31, decrease=2. if ratio is not None else 0.,
            increase_after_decrease=2.*ratio if ratio is not None else 0., first_decrease_seq=trial['start']['seq']+1,
            raw_quantity_known=True, old_quantity_known_so_far=True, raw_unknown_reason_counts={},
            missing_time_count=0, complete_available=True, u_strict=ratio, u_local=ratio,
            strict_none_reasons=[] if ratio is not None else ['可視減少0'],
            local_none_reasons=[] if ratio is not None else ['可視減少0'])
        observations.append(dict(number=trial['number'], start=trial['start'], end=trial['end'],
            complete_available=True, ratio_available_seq=trial['end']['seq'], u_strict=ratio, u_local=ratio,
            raw_row_count=31, public_sample_count=4, publications=[publication]))
    augmented = {name: deepcopy(band[name]) for name in ('band_id','direction','price','atr','tick','created','terminal')}
    augmented.update(trials=observations, features_strict=dict(feature, available_seq=100),
        features_local=dict(feature, available_seq=100))
    peer = dict(time_s=np.array([60.]), score=np.array([.25]), left=np.array([0]), seq=np.array([60]))
    return {('人工', 'TOPIX'): ready}, band, augmented, peer


def synthetic() -> dict:
    """機能: 20基本判定、260接続、None・等号・公開境界を人工だけで攻撃する。

    引数: なし。返り値: 人工検査結果(dict)。実相場の売買は呼ばない。
    """
    CHECKS.clear()
    specs = design.catalog()+design.supplementary()
    selected = {spec['id']: spec for spec in specs}
    check('260一意と68主192補助', len(specs)==len(selected)==260 and len(design.catalog())==68)
    check('旧4対照ID', design.LEGACY_EQUIVALENTS=={'F00':'B00','F05':'B02','F18':'B01','F19':'B03'})
    check('乱数seed全数', all([selected[f'{identifier}_R{s:02d}']['seed'] for s in range(64)]==list(range(64))
        for identifier in ('F01','F02','F03')))
    key = ('人工', 'TOPIX')
    inputs, band, panel, peer = fixture()
    snapshot = json.dumps([band, panel], sort_keys=True)
    for spec in specs:
        pulse, meta = entry.make(spec, key, inputs, [band], peer, [panel])
        expected = spec['mode']!='strengthen'
        check(spec['id']+'人工候補', np.count_nonzero(pulse)==int(expected))
        if expected:
            sign = -1 if spec['invert'] else 1
            if spec['seed'] is not None:
                sign *= entry.direction_bit(spec['seed'], key, band['terminal']['seq'])
            check(spec['id']+'符号と一行', pulse[12]==sign and np.count_nonzero(pulse[:12])==0)
        json.dumps(meta, allow_nan=False)
    check('入力非破壊', snapshot==json.dumps([band,panel],sort_keys=True))
    for u1,u2 in ((None,.5),(1.,None),(None,None)):
        data, value, extra, other = fixture(u1,u2)
        for identifier in ('F01','F02','F03','F04','F06','F07','F08','F11','F12','F13','F14','F17'):
            pulse,_=entry.make(selected[identifier],key,data,[value],other,[extra])
            check(f'{identifier}不明{u1}/{u2}', not np.any(pulse))
        for identifier in ('F05','F19'):
            pulse,_=entry.make(selected[identifier],key,data,[value],other,[extra])
            check(identifier+'数量不明でも価格対照', pulse[12]==1)
    data,value,extra,other=fixture(.5,.5)
    for identifier in ('F01','F02','F08','F09','F11','F14','F15','F17'):
        pulse,_=entry.make(selected[identifier],key,data,[value],other,[extra])
        check(identifier+'数量同値は変化なし', not np.any(pulse))
    for identifier in ('F03','F04','F06','F07','F12','F13'):
        pulse,_=entry.make(selected[identifier],key,data,[value],other,[extra])
        check(identifier+'数量同値を順序なし対照は保持', pulse[12]==1)
    data,value,extra,other=fixture(1.,.5,False)
    for identifier in ('F01','F02','F03','F04','F06','F07','F08','F12','F13','F14'):
        check(identifier+'価格同値を弱化にしない', not np.any(entry.make(selected[identifier],key,data,[value],other,[extra])[0]))
    for identifier in ('F11','F17','F19'):
        check(identifier+'価格弱化を使わない対照', entry.make(selected[identifier],key,data,[value],other,[extra])[0][12]==1)
    data,value,extra,other=fixture()
    value['status']='early_breakout';value['trials'][1]['complete']=False
    for field in ('two_trials_complete','price_comparable','quantity_comparable'):
        value['features'][field]=False
    value['features'].update(u1=None,u2=None)
    for source in ('strict','local'):
        extra['features_'+source]=dict(value['features'],available_seq=None)
    for spec in specs:
        check(spec['id']+'二試行未完を後知恵採用しない',not np.any(entry.make(spec,key,data,[value],other,[extra])[0]))
    # ----------------------------------------
    # 旧品質維持とP局所品質は欠測判定そのものが異なるため別条件に残す。
    data,value,extra,other=fixture()
    extra['features_strict'].update(quantity_comparable=False,u1=None,u2=None)
    for trial in extra['trials']:
        trial['u_strict']=None
        trial['publications'][-1].update(u_strict=None,old_quantity_known_so_far=False)
    check('旧品質不明はF01不可', not np.any(entry.make(selected['F01'],key,data,[value],other,[extra])[0]))
    check('局所品質可はF02可能', entry.make(selected['F02'],key,data,[value],other,[extra])[0][12]==1)
    data,value,extra,other=fixture()
    bad=deepcopy(extra);bad['trials'][0]['publications'][-1]['decrease']=0.
    check('減少0に正の比率を偽装できない', rejects(lambda:entry.make(selected['F01'],key,data,[value],other,[bad])))
    bad=deepcopy(extra);bad['features_strict']['available_seq']=121
    check('未公開の特徴を拒否', rejects(lambda:entry.make(selected['F01'],key,data,[value],other,[bad])))
    bad=deepcopy(extra);bad['terminal']['seq']+=1
    check('別帯時刻パネルを拒否', rejects(lambda:entry.make(selected['F01'],key,data,[value],other,[bad])))
    bad=deepcopy(extra);bad['features_strict']['b1']+=1
    check('価格特徴変更を拒否', rejects(lambda:entry.make(selected['F01'],key,data,[value],other,[bad])))
    check('パネル欠落を拒否', rejects(lambda:entry.make(selected['F01'],key,data,[value],other,[])))
    check('パネル重複を拒否', rejects(lambda:entry.make(selected['F01'],key,data,[value],other,[extra,extra])))
    check('未知modeを拒否', rejects(lambda:entry.eligible(value,'unknown')))
    for now,expected in ((119.999,False),(120.,True),(240.,True),(240.001,False)):
        check(f'peer公開60秒と鮮度120秒境界{now}',entry.peer_at(other,now,1)[0]==expected)
    check('peer反対方向を拒否',not entry.peer_at(other,120.,-1)[0])
    invalid=dict(time_s=np.array([60.,61.]),score=np.array([.25,np.nan]),left=np.array([0,-1]),seq=np.array([60,61]))
    check('最新相手不明を飛ばさない',not entry.peer_at(invalid,121.,1)[0])
    for spec in specs:
        mirror=deepcopy(value);mirror['direction']=-1;mirror['price']=1000.-value['price']
        mirrored=deepcopy(extra);mirrored['direction']=-1;mirrored['price']=mirror['price']
        negative=dict(other,score=-other['score'])
        original=entry.make(spec,key,data,[value],other,[extra])[0]
        changed=entry.make(spec,key,data,[mirror],negative,[mirrored])[0]
        check(spec['id']+'買売反射',np.array_equal(changed,-original))
    check('8近傍だけが帯母集団を変更',len({entry.cache_key(spec) for spec in specs})==9)
    refs=references()
    result=dict(全合格=True,人工検査数=len(CHECKS),検査=CHECKS.copy(),全260接続=True,
        旧実入口再現未実施=True,新パネル全入力未実施=True,新売買計算=False,API取得数=0,
        参照SHA256=refs,出力SHA256={})
    write('check_entry_signals_synthetic.json',result)
    return result


def load_known() -> tuple[dict,dict,dict,dict]:
    """機能: 既知入力と旧公開・旧帯を読むだけで売買は再生しない。

    引数: なし。返り値: 原本入力・公開・帯・相手(dictのtuple)。
    """
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    depth=pickle.loads((OLD/'released_depth.pkl').read_bytes())
    bands=pickle.loads((OLD/'band_cache.pkl').read_bytes())
    peers={key:entry.peer_prices(events) for key,events in depth.items()}
    assert len(inputs)==len(depth)==26 and len(bands)==10
    return inputs,depth,bands,peers


def legacy_check() -> dict:
    """機能: F00/F05/F18/F19の全26入口を旧4方式の生成列に厳密照合する。

    引数: なし。返り値: 104入力の旧再現証跡(dict)。損益資料は読まない。
    """
    extras=(HERE.parent/'wave_v23/inputs.pkl',OLD/'released_depth.pkl',OLD/'band_cache.pkl',OLD/'design.py')
    before=references(extras)
    inputs,depth,bands,peers=load_known()
    specs={row['id']:row for row in design.catalog()}
    records=[]
    for new_id,old_id in design.LEGACY_EQUIVALENTS.items():
        spec=specs[new_id]
        for key in sorted(inputs):
            peer=peers[(key[0],'TOPIX' if key[1]=='NK225' else 'NK225')]
            group=bands[entry.cache_key(spec)][key]
            actual,meta=entry.make(spec,key,inputs,group,peer)
            old_spec=dict(spec,id=old_id)
            expected,old_meta=entry.legacy_entry.make(old_spec,key,inputs,group,peer)
            assert np.array_equal(actual,expected),(new_id,key)
            assert [row['band_id'] for row in meta['候補']]==[row['band_id'] for row in old_meta['候補']]
            records.append(dict(id=new_id,旧id=old_id,session=key[0],symbol=key[1],原本行数=len(actual),
                全入口完全一致=True,候補数=int(np.count_nonzero(actual)),入口SHA256=hashlib.sha256(actual.tobytes()).hexdigest()))
    assert len(records)==104 and before==references(extras)
    result=dict(全合格=True,旧4方式26入力完全再現=True,比較入力数=104,結果=records,
        新パネル全入力未実施=True,新売買計算=False,API取得数=0,参照SHA256=before,出力SHA256={})
    write('check_entry_signals_legacy.json',result)
    return result


def peer_oracle(events: dict, now: float, direction: int) -> bool:
    """機能: 相手の現在公開・過去5分価格品質を直接調べ、旧関数なしで確認する。

    引数: events(dict)、now(float)、direction(int)。返り値: 相手確認(bool)。
    """
    eligible_rows=np.flatnonzero(events['time_s']<=now-60.)
    if not len(eligible_rows):return False
    i=int(eligible_rows[-1]);age=now-events['time_s'][i]-60.
    if not 0<=age<=120.:return False
    times=events['time_s'];earlier=np.flatnonzero(times[:i+1]<=times[i]-300.)
    if not len(earlier):return False
    left=int(earlier[-1])
    if times[i]-300.-times[left]>60.:return False
    for row in range(left,i+1):
        bid,ask=events['bid_prices'][row,0],events['ask_prices'][row,0]
        atr=events['atr'][row];gap=events['previous_release_gap'][row];delay=events['block_delay_seconds'][row]
        if not (events['price_valid'][row] and np.isfinite([bid,ask,atr,gap,delay]).all()
            and bid>0 and ask>bid and atr>0 and 0<gap<=60. and 0<delay<=60.):return False
    first=(events['bid_prices'][left,0]+events['ask_prices'][left,0])/2.
    last=(events['bid_prices'][i,0]+events['ask_prices'][i,0])/2.
    return bool(direction*(last-first)/events['atr'][i]>=.25)


def oracle(spec: dict, key: tuple, ready: dict, bands: list, panel: list, other: dict) -> np.ndarray:
    """機能: モードごとの式を直接列挙し、入口関数を呼ばず符号列を作る。

    引数: spec/ready/other(dict)、key(tuple)、bands/panel(list)。返り値: 独立期待(ndarray)。
    """
    output=np.zeros(len(ready['seq']),np.int8)
    extra={row['band_id']:row for row in panel}
    for band in bands:
        if band['status']!='breakout':continue
        f=band['features'] if spec['feature_source']=='old' else extra[band['band_id']]['features_'+spec['feature_source']]
        if not (f['two_trials_complete'] and f['price_comparable']):continue
        price=f['b2']<f['b1']
        assert bool(price)==f['price_weakens']
        mode=spec['mode'];known=f['u1'] is not None and f['u2'] is not None
        assert known==f['quantity_comparable']
        allowed=False
        if mode=='all':allowed=True
        elif mode=='price':allowed=price
        elif known:
            u1,u2=f['u1'],f['u2']
            allowed={'weaken':price and u2<u1,'price_matched':price,'quantity':u2<u1,
                'last':price and u2<1.,'mean':price and u1+u2<2.,'strengthen':price and u2>u1}[mode]
        if not allowed:continue
        terminal=band['terminal'];direction=int(band['direction'])
        if spec['peer'] and not peer_oracle(other,terminal['time_s'],direction):continue
        if spec['invert']:direction=-direction
        if spec['seed'] is not None:
            value=hashlib.sha256(f"v42|{spec['seed']}|{key[0]}|{key[1]}|{terminal['seq']}".encode('utf-8')).digest()[0]
            direction*=1 if value%2 else -1
        row=int(terminal['ready_index'])
        assert output[row]==0 and ready['seq'][row]==terminal['seq']
        output[row]=direction
    return output


def reflected(bands: list, panel: list) -> tuple[list,list]:
    """機能: 固定帯と同側数量観測を上下反射し、時刻・比率をそのまま保持する。

    引数: bands/panel(list[dict])。返り値: 反射帯と反射パネル(tuple[list,list])。
    原本からの反射再集計は別のパネル監査が担当する。
    """
    anchor=4.*max([band['price'] for band in bands]+[1.])
    old,new=deepcopy(bands),deepcopy(panel)
    for group in (old,new):
        for band in group:
            band['direction']=-band['direction'];band['price']=anchor-band['price']
    return old,new


def changed_future(panel: list, seq: int) -> list:
    """機能: 切断後に終了した試行の比率だけを変更し、過去公開を保つ。

    引数: panel(list[dict])、seq(int)。返り値: 未来特徴を変えたパネル(list[dict])。
    帯の条件付き母集団は不変。原本からの再集計因果とは別の入口接続検査である。
    """
    result=deepcopy(panel)
    for band in result:
        if not band['features_strict']['two_trials_complete']:continue
        for trial in band['trials']:
            if trial['ratio_available_seq']<=seq:continue
            for source in ('strict','local'):
                if trial['u_'+source] is not None:
                    trial['u_'+source]+=7.5
                    trial['publications'][-1]['u_'+source]=trial['u_'+source]
        for source in ('strict','local'):
            f=band['features_'+source]
            u1,u2=[trial['u_'+source] for trial in band['trials']]
            f.update(u1=u1,u2=u2,quantity_change=u2-u1 if u1 is not None and u2 is not None else None,
                quantity_weakens=bool(u2<u1) if u1 is not None and u2 is not None else None)
    return result


def full_check() -> dict:
    """機能: 全260×26を独立判定し、公開投影と未来比率・反射を入口へ接続する。

    引数: なし。返り値: 正式な入口検査証跡(dict)。新しい売買収支は計算しない。
    """
    synthetic_result=synthetic();legacy_result=legacy_check()
    panel_proof=json.loads((HERE/'trial_observation_audit.json').read_text(encoding='utf-8'))
    assert panel_proof['全合格'] and panel_proof['全セル数']==260
    assert panel_proof['prefix数']==panel_proof['future数']==520 and panel_proof['reflection数']==260
    source={}
    for group in ('参照SHA256','出力SHA256','原本SHA256'):
        for relative,value in panel_proof[group].items():
            assert sha(ROOT/relative)==value,relative
            source[relative]=value
    extras=(HERE.parent/'wave_v23/inputs.pkl',OLD/'released_depth.pkl',OLD/'band_cache.pkl',
        HERE/'trial_panel.pkl',HERE/'trial_observation_audit.json',
        HERE/'check_entry_signals_synthetic.json',HERE/'check_entry_signals_legacy.json')
    source.update(references(extras))
    inputs,depth,bands,peers=load_known()
    panels=pickle.loads((HERE/'trial_panel.pkl').read_bytes())
    assert set(panels)==set(bands)
    specs=design.catalog()+design.supplementary();records=[]
    counters=Counter();transform_cache={};sets={}
    for number,spec in enumerate(specs):
        canonical=entry.cache_key(spec)
        assert canonical in panels
        for key,ready in sorted(inputs.items()):
            group=bands[canonical][key];panel=panels[canonical][key]
            other_key=(key[0],'TOPIX' if key[1]=='NK225' else 'NK225')
            other=peers[other_key]
            pulse,meta=entry.make(spec,key,inputs,group,other,panel)
            expected=oracle(spec,key,ready,group,panel,depth[other_key])
            assert np.array_equal(pulse,expected),(spec['id'],key,'独立条件式')
            counters['全入口列独立一致']+=1
            if spec['id'] in ('F01','F02','F03','F04','F05','F19'):
                sets[(spec['id'],canonical,key)]=set(np.flatnonzero(pulse).tolist())
            projection=future=mirror=False
            if spec['role'] not in ('random','execution'):
                # ----------------------------------------
                # 将来の未確定帯を使わず、切断までに終端が公開された帯だけで再生成する。
                for fraction in (.37,.73):
                    cut=max(1,int(len(pulse)*fraction));cut_seq=int(ready['seq'][cut-1])
                    past=[row for row in group if row['terminal'] is not None and row['terminal']['seq']<=cut_seq]
                    ids={row['band_id'] for row in past}
                    partial=[row for row in panel if row['band_id'] in ids]
                    past_ready={name:(value[:cut].copy() if isinstance(value,np.ndarray) and value.ndim and len(value)==len(pulse) else value)
                        for name,value in ready.items()}
                    past_peer={name:value[other['time_s']<=ready['time_s'][cut-1]-60.].copy() for name,value in other.items()}
                    actual,_=entry.make(spec,key,{key:past_ready},past,past_peer,partial)
                    assert np.array_equal(actual,pulse[:cut]),(spec['id'],key,'公開投影',fraction)
                    counters['既確定候補の公開投影']+=1
                    cache=(canonical,key,'future',fraction)
                    if cache not in transform_cache:transform_cache[cache]=changed_future(panel,cut_seq)
                    modified,_=entry.make(spec,key,inputs,group,other,transform_cache[cache])
                    assert np.array_equal(modified[:cut],pulse[:cut]),(spec['id'],key,'未来比率',fraction)
                    counters['未来側確定比率変更']+=1
                cache=(canonical,key,'mirror')
                if cache not in transform_cache:transform_cache[cache]=reflected(group,panel)
                reflected_bands,reflected_panel=transform_cache[cache]
                negative=dict(other,score=-other['score'])
                inverse,_=entry.make(spec,key,inputs,reflected_bands,negative,reflected_panel)
                assert np.array_equal(inverse,-pulse),(spec['id'],key,'反射')
                counters['固定帯と公開比率の上下反射']+=1
                projection=future=mirror=True
            if spec['seed'] is not None:
                original=dict(spec,seed=None)
                baseline,_=entry.make(original,key,inputs,group,other,panel)
                assert np.array_equal(pulse!=0,baseline!=0),(spec['id'],key,'乱数の候補時刻')
                counters['乱数同候補時刻']+=1
            records.append(dict(id=spec['id'],session=key[0],symbol=key[1],全入口列独立一致=True,
                母集団キー=canonical,数量観測=spec['feature_source'],原本行数=len(pulse),
                候補数=int(np.count_nonzero(pulse)),入口SHA256=hashlib.sha256(pulse.tobytes()).hexdigest(),
                段階件数=meta['段階件数'],公開投影検査=projection,未来比率検査=future,反射検査=mirror))
        if (number+1)%20==0:print(f'入口接続 {number+1}/260',flush=True)
    assert len(records)==6760 and len({(r['id'],r['session'],r['symbol']) for r in records})==6760
    # 数量情報を外す対照は同じ比較可能機会を保持する。方向行の包含であり収益の優劣ではない。
    for key in inputs:
        for canonical in {entry.cache_key(spec) for spec in specs}:
            for main,control in (('F01','F03'),('F02','F04')):
                main_id=next((spec['id'] for spec in specs if (spec['id']==main or spec.get('parent')==main)
                    and spec['role'] not in ('execution','random') and entry.cache_key(spec)==canonical),None)
                control_id=next((spec['id'] for spec in specs if (spec['id']==control or spec.get('parent')==control)
                    and spec['role'] not in ('execution','random') and entry.cache_key(spec)==canonical),None)
                if main_id is None:continue
                a=next(r for r in records if r['id']==main_id and (r['session'],r['symbol'])==key)
                b=next(r for r in records if r['id']==control_id and (r['session'],r['symbol'])==key)
                assert a['段階件数']['板比較可能']==b['段階件数']['板比較可能']
                assert a['段階件数']['完了後突破の板比較可能']==b['段階件数']['完了後突破の板比較可能']
                counters['同品質対照の比較可能母集団一致']+=1
        canonical=entry.cache_key(specs[0])
        assert sets[('F01',canonical,key)]<=sets[('F03',canonical,key)]
        assert sets[('F02',canonical,key)]<=sets[('F04',canonical,key)]
        assert sets[('F03',canonical,key)]<=sets[('F05',canonical,key)]<=sets[('F19',canonical,key)]
        assert sets[('F04',canonical,key)]<=sets[('F05',canonical,key)]
    for relative,value in source.items():assert sha(ROOT/relative)==value,relative
    payload=json.dumps(records,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    path=HERE/'check_entry_signals_details.json.gz';path.write_bytes(gzip.compress(payload,mtime=0))
    result=dict(全合格=True,条件数=260,入力数=26,全比較入力数=6760,人工検査数=synthetic_result['人工検査数'],
        旧4方式26入力完全再現=True,旧入口再現数=legacy_result['比較入力数'],検査数=dict(counters),
        原本からパネルの別監査=dict(全セル数=260,prefix数=520,future数=520,reflection数=260,
            資料='work/wave_v42/trial_observation_audit.json'),
        因果検査の区別='原本差分の再集計は別監査。こちらは既確定帯の公開投影・未来に確定する比率の変更・固定帯と比率の反射を検査。',
        全270等の誤表示なし=True,新売買計算=False,API取得数=0,現在保存物使用=False,
        参照SHA256=source,出力SHA256={path.relative_to(ROOT).as_posix():sha(path)})
    write('check_entry_signals.json',result)
    return result


def main() -> None:
    """機能: 人工・旧再現を別証跡にし、全パネル確認前の正式合格を出さない。

    引数: CLI --synthetic-only/--legacy-only。返り値: なし(None)。
    """
    def denied(*args: object, **kwargs: object) -> None:
        """機能: 保存入力検査からの通信を拒否する。

        引数: 任意args/kwargs(object)。返り値: なし(None)、常に例外。
        """
        raise RuntimeError('新しい通信は使いません')
    socket.socket=denied;socket.create_connection=denied
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--synthetic-only',action='store_true')
    group.add_argument('--legacy-only',action='store_true')
    args=parser.parse_args()
    if args.synthetic_only:
        result=synthetic()
    elif args.legacy_only:
        result=legacy_check()
    else:
        result=full_check()
    print(json.dumps({key:value for key,value in result.items() if key not in ('検査','結果','参照SHA256')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
