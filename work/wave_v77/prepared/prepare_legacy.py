"""従来J1の29場候補を完全保持し、追加ナイトだけ同一入口式で準備する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys
import types

import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'work/wave_v75'
INPUT=HERE.parent/'inputs'
SIGNAL_ID='J1_W300_L0'
EXTRA='2026-10-09_Night'
DELAYS=(1,5,15)


def module(name: str,path: Path) -> object:
    """機能: 旧入口と同期実装を旧ファイル変更なしで読み込む。

    引数: name(str)、path(Path)。返り値: 読込モジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def load(path: Path) -> object:
    """機能: 指定した保存入力・入口だけを読み取る。

    引数: path(Path)。返り値: 保存内容(object)。売買結果は参照しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 旧資料と新入口の内容指紋を一定メモリーで計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def deny(*args: object,**kwargs: object) -> None:
    """機能: 入口準備からのネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)。接続呼出しは例外で停止する。
    """
    raise RuntimeError('従来入口の準備中の通信は禁止')


def equal(left: object,right: object) -> int:
    """機能: 入口候補と状態配列を欠損込みで厳密に照合する。

    引数: left/right(dict又はndarray)。返り値: 一致した配列数(int)。
    """
    if isinstance(left,dict):
        assert left.keys()==right.keys()
        return sum(equal(left[k],right[k]) for k in left)
    np.testing.assert_array_equal(left,right)
    return 1


def clipped(value: dict,cut: int) -> dict:
    """機能: 未来側を除いた追加入力を作る。

    引数: value(dict)、cut(int)。返り値: 過去だけの入力(dict)。
    """
    return {k:v[:cut] if isinstance(v,np.ndarray) and v.ndim else v for k,v in value.items()}


def build_extra(legacy: object,grid: np.ndarray,ready: dict,book: dict,delay: int) -> dict:
    """機能: 旧75の同じ関数でJ1_W300_L0の追加2口座候補を作る。

    引数: legacy(object)、grid(float配列)、ready/book(dict)、delay(int)。
    返り値: 旧J1と同じ候補・状態・源泉行の辞書(dict)。損益は計算しない。
    """
    stats={s:legacy.features(grid,delay,300,30,ready[(EXTRA,s)],book[(EXTRA,s)]) for s in legacy.SYMBOLS}
    out={}
    for s in legacy.SYMBOLS:
        p='NK225' if s=='TOPIX' else 'TOPIX';key=(EXTRA,s)
        states,valid=legacy.conditions(stats[s],stats[p],300,0,True)
        pulse=legacy.event_pulses(grid,states[0],valid)
        candidates=legacy.map_pulses(grid,pulse,stats[s],stats[p],ready[key],book[key])
        out[key]=dict(candidates=candidates,states=states[0],valid=valid,pulse=pulse,
            own_source=stats[s]['now'],peer_source=stats[p]['now'])
        for row in candidates:
            g,decision,side,own,peer=map(int,row)
            assert side in (-1,1) and own>=0 and peer>=0
            assert ready[key]['time_s'][own]<grid[g]-delay
            assert ready[(EXTRA,p)]['time_s'][peer]<grid[g]-delay
            assert own==np.searchsorted(ready[key]['time_s'],ready[key]['time_s'][own],side='left')
            assert peer==np.searchsorted(ready[(EXTRA,p)]['time_s'],ready[(EXTRA,p)]['time_s'][peer],side='left')
            assert ready[key]['time_s'][decision]>=grid[g]
    return out


def prefix_check(legacy: object,grid: np.ndarray,ready: dict,book: dict,delay: int,base: dict) -> dict:
    """機能: 追加両市場を同時点で切断し、過去入口状態と注文候補の不変性を確かめる。

    引数: legacy(object)、grid(ndarray)、ready/book/base(dict)、delay(int)。返り値: 検査記録(dict)。
    注文判断が切断後になる候補は比較対象から除く。末尾だから入口を過去へ補完しない。
    """
    cutoff=ready[(EXTRA,'TOPIX')]['start']+6*3600.
    cuts={key:int(np.searchsorted(r['time_s'],cutoff,side='left')) for key,r in ready.items()}
    rs={key:clipped(r,cuts[key]) for key,r in ready.items()};bs={key:clipped(b,cuts[key]) for key,b in book.items()}
    prefix_grid=grid[grid<cutoff];short=build_extra(legacy,prefix_grid,rs,bs,delay);rows=[]
    for key,r in short.items():
        length=len(prefix_grid)
        for name in ('states','valid','pulse','own_source','peer_source'):
            np.testing.assert_array_equal(base[key][name][:length],r[name])
        old=base[key]['candidates'];expected=old[(old[:,0]<length)&(old[:,1]<cuts[key])]
        np.testing.assert_array_equal(expected,r['candidates'])
        rows.append(dict(session=key[0],symbol=key[1],cut_i=cuts[key],過去状態一致=True,過去候補一致=True,候補数=len(expected)))
    return dict(delay=delay,cutoff=cutoff,rows=rows,限定='最終約定代理時計上の前方参照検査であり共通受信時計の証明ではない。')


def main() -> None:
    """機能: 既往58候補を保持し、追加2口座だけ同一式で作り三遅延へ保存する。

    引数: なし。返り値: なし(None)。API・実注文・全期間と追加場の損益再生は0。
    """
    socket.socket.connect=deny;socket.create_connection=deny
    assert not any((HERE/f'legacy_delay{d}.pkl').exists() for d in DELAYS),'完成入口は上書きしない'
    pkg=types.ModuleType('inputs');pkg.__path__=[str(OLD/'inputs')];sys.modules['inputs']=pkg
    oldcore=module('inputs.core',OLD/'inputs/core.py')
    legacy=module('旧共同方向J1入口77',OLD/'signals.py')
    ready=load(INPUT/'extra_inputs.pkl');book=load(INPUT/'extra_features.pkl');meta=load(INPUT/'metadata.json')
    assert len(ready)==len(book)==2 and meta['unseen_session']==EXTRA
    grid=oldcore.session_sync(ready,book,EXTRA,delays=DELAYS,step=15.,max_age=30.)['grid']
    checks=[];hashes={}
    for delay in DELAYS:
        source=OLD/'prepared'/f'signals_delay{delay}.pkl';old=load(source)[SIGNAL_ID]
        assert len(old)==58 and {k[0] for k in old}==set(meta['existing29'])
        extra=build_extra(legacy,grid,ready,book,delay)
        prefix=prefix_check(legacy,grid,ready,book,delay,extra)
        output=dict(old);assert not set(output)&set(extra);output.update(extra)
        assert len(output)==60
        old_checks=equal({k:output[k] for k in old},old)
        for key in ready:
            ref=meta['references']['|'.join(key)]['ref_open']
            assert ref['known_from_i']==0 and ref['value']>0
        path=HERE/f'legacy_delay{delay}.pkl';path.write_bytes(pickle.dumps(output,protocol=5))
        roundtrip=load(path);equal(roundtrip,output)
        checks.append(dict(delay=delay,既往29場候補状態の全配列一致=True,既往照合配列数=old_checks,
            prefix=prefix,追加候補数={s:len(extra[(EXTRA,s)]['candidates']) for s in legacy.SYMBOLS},
            ref_open全口座利用可能=True))
        hashes[str(source.relative_to(ROOT))]=digest(source);hashes[str(path.relative_to(ROOT))]=digest(path)
        print(f'旧29候補完全保持・追加Night入口生成、遅延{delay}秒',flush=True)
    for path in (Path(__file__),OLD/'signals.py',OLD/'inputs/core.py',INPUT/'extra_inputs.pkl',INPUT/'extra_features.pkl',INPUT/'metadata.json'):
        hashes[str(path.relative_to(ROOT))]=digest(path)
    (HERE/'legacy_入口継承と追加Nightの因果照合.json').write_text(json.dumps(dict(合格=True,
        signal_id=SIGNAL_ID,既往29場再生成なし=True,追加場=EXTRA,場数=30,口座数=60,checks=checks,
        grid='旧75同様にstart+300以上limit−300未満の15秒格子',
        入口='旧75のfeatures/conditions/event_pulses/map_pulsesを直接呼ぶ。300秒同方向0.03%以上＋自15秒両気配1呼値＋相手15秒非逆行。',
        保存形='legacy[key]辞書。candidates/state/valid/pulse/own_source/peer_sourceは旧J1と同じ。',
        API取得=0,実注文=0,損益再生=0,SHA256=hashes),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


if __name__=='__main__':
    main()
