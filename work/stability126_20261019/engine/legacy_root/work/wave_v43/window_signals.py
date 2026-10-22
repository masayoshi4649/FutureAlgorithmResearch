"""H019の完全入口を固定した時間窓で生成し、同一原本行の3票を合成する。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent/'wave_v27'
sys.path.insert(0, str(OLD))
import hierarchy_signals as HIERARCHY
assert Path(HIERARCHY.__file__).resolve() == (OLD/'hierarchy_signals.py').resolve()
BASE = next(row for row in HIERARCHY.catalog() if row['id']=='H019')
assert BASE['params'] == dict(main_kind='ema15_60',time_multiplier=1,entry_kind='short_price',
    peer_confirm=True,clock_multiplier=1.,peer_multiplier=1.,confirmation_multiplier=1.)
SCALES = (.64,.8,.96,1.,1.2,1.44)
_MEMBERS: dict = {}


def catalog() -> list[dict]:
    """機能: 単一3本と、3合議方式×3中心の固定12入口を返す。

    引数: なし。返り値: id/mode/center/scalesの仕様 (list[dict])。
    """
    result=[dict(id=f'S{round(c*100):03d}',mode='single',center=c,scales=[c]) for c in (.8,1.,1.2)]
    for mode in ('M2','V2','U3'):
        for center in (.8,1.,1.2):
            result.append(dict(id=f'{mode}_{round(center*100):03d}',mode=mode,center=center,
                scales=[round(center*multiplier,2) for multiplier in (.8,1.,1.2)]))
    return result


def signal_catalog() -> list[dict]:
    """機能: catalogと同じ12入口を別の明示名で返す。

    引数: なし。返り値: 固定仕様 (list[dict])。
    """
    return catalog()


def clear_cache() -> None:
    """機能: 旧確定足・公開板と新メンバーのキャッシュを破棄する。

    引数: なし。返り値: なし (None)。入力改変監査の前後にも呼ぶ。
    """
    _MEMBERS.clear()
    HIERARCHY.clear_cache()


def set_root(path: Path | str) -> None:
    """機能: 因果検査用の複写1分足の根を設定する。

    引数: path (Path|str)。返り値: なし (None)。既知原本自体は編集しない。
    """
    clear_cache()
    HIERARCHY.set_root(path)


def member_spec(clock: float) -> dict:
    """機能: H019の時計だけを、固定6倍率の一つへ変更する。

    引数: clock (float)。返り値: 旧関数へ渡す完全入口仕様 (dict)。
    相手遅延・価格閾値・足公開遅延・20分待ち・保持期限は変更しない。
    """
    if clock not in SCALES:
        raise ValueError('固定6倍率にない時計です')
    spec=deepcopy(BASE)
    spec['id']=f'H019_C{round(clock*100):03d}'
    spec['params']['clock_multiplier']=clock
    return spec


def member_directions(clock: float, inputs: dict, features: dict) -> dict:
    """機能: 旧H019の全段階を、その窓内で完結して原本行へ展開する。

    引数: clock (float)、inputs (dict[tuple,dict])、features (dict[tuple,DataFrame])。
    返り値: 原本行の完全入口 (dict[tuple,ndarray[int8]])。返された列は変更しない。
    旧buildは旧カタログと±20%だけを許すため、固定6倍率の検証後に同じ内部関数を呼ぶ。
    旧コード・catalog・関数を一時変更せず、EMAだけでなく短期入口まで旧順序で計算する。
    """
    spec=member_spec(clock);params=spec['params']
    if not inputs or not set(inputs)<=set(features):
        raise ValueError('入力又は対応する公開特徴が不足しています')
    for session,symbol in inputs:
        other='NK225' if symbol=='TOPIX' else 'TOPIX'
        if symbol not in ('TOPIX','NK225') or (session,other) not in inputs:
            raise ValueError('各セッション両市場の入力が必要です')
    fingerprint=(str(HIERARCHY.ROOT),clock,tuple((key,id(ready),id(ready['atr']),id(features[key]),
        len(ready['seq']),int(ready['seq'][-1]),float(ready['time_s'][-1])) for key,ready in sorted(inputs.items())))
    if fingerprint in _MEMBERS:
        return _MEMBERS[fingerprint]['output']
    main=HIERARCHY.main_directions(spec,inputs)
    models={key:HIERARCHY._main_model(ready,params) for key,ready in inputs.items()}
    output={}
    for key,ready in inputs.items():
        short=HIERARCHY._short_model(ready,features[key],params)
        event_main=HIERARCHY._allowed(key,short['time_s'],models,params)
        event_main[short['time_s']<ready['start']+1200]=0
        direction,_,_=HIERARCHY._entry_filter(ready['seq'],ready['time_s'],main[key],short['seq'],
            short['time_s'],event_main,short['short'],short['ofi'],1,params['confirmation_multiplier'])
        assert direction.dtype==np.int8 and direction.shape==ready['seq'].shape
        assert np.isin(direction,[-1,0,1]).all()
        output[key]=direction
    _MEMBERS[fingerprint]=dict(output=output,inputs_ref=inputs,features_ref=features)
    return output


def combine(votes: np.ndarray, mode: str) -> np.ndarray:
    """機能: 同じ原本行の固定3票を多数決・反対拒否・全一致で合成する。

    引数: votes (ndarray[n,3]、-1/0/+1)、mode (str:M2/V2/U3)。
    返り値: 同じn行の入口 (ndarray[int8])。中立を除いて母数を縮めず、追加保持もしない。
    """
    votes=np.asarray(votes)
    if votes.ndim!=2 or votes.shape[1]!=3 or not np.isin(votes,[-1,0,1]).all():
        raise ValueError('3票の方向は-1/0/+1に限ります')
    positive=(votes==1).sum(axis=1);negative=(votes==-1).sum(axis=1)
    if mode=='M2':
        buy,sell=positive>=2,negative>=2
    elif mode=='V2':
        buy,sell=(positive>=2)&(negative==0),(negative>=2)&(positive==0)
    elif mode=='U3':
        buy,sell=positive==3,negative==3
    else:
        raise ValueError('未定義の合議方式です')
    output=np.zeros(len(votes),np.int8)
    output[buy]=1;output[sell]=-1
    return output


def build(spec: dict, inputs: dict, features: dict) -> dict:
    """機能: 12固定入口の一つを、同時刻ではなく同一原本行で合成する。

    引数: spec (dict)、inputs/features (dict)。返り値: 方向配列 (dict[tuple,ndarray[int8]])。
    個々の入力欠測・未成熟による中立票を残す。未来の票や損益による重み選択はない。
    """
    expected={row['id']:row for row in catalog()}.get(spec.get('id'))
    if spec!=expected:
        raise ValueError('固定した12入口と仕様が一致しません')
    members=[member_directions(scale,inputs,features) for scale in spec['scales']]
    if spec['mode']=='single':
        return members[0]
    return {key:combine(np.column_stack([member[key] for member in members]),spec['mode']) for key in inputs}
