"""通常A0の新規準備だけを時計にし、短縮出口を同じ初回へ同期する。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
_saved_path=list(sys.path)
sys.path.insert(0,str(HERE.parent/'wave_v38'))
import engine_shadow_plan as original
sys.path[:]=_saved_path
assert Path(original.__file__).resolve()==HERE.parent/'wave_v38/engine_shadow_plan.py'

PARAMS=original.PARAMS
ATR_COLUMNS=original.ATR_COLUMNS
PLAN_COLUMNS=original.PLAN_COLUMNS
REASONS=original.REASONS
inventory=original.inventory
FIELDS=('trades','cycles','curve','orders','stats','atr_curve','prepare_events','entry_preparations','plans','execution_plans')


def dependency_sha256() -> str:
    """機能: 無変更で呼ぶ旧影実装をキャッシュ指紋へ含める。

    引数: なし。返り値: SHA256(str)。
    """
    return hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest()


def run(ready: dict, state: np.ndarray, config: dict, detail: bool=False,
        context: np.ndarray | None=None, width_mode: int=0, observed_fill: bool=False,
        trail_atr: np.ndarray | None=None, prepare_allow: np.ndarray | None=None,
        min_delay_seconds: float=0.) -> dict:
    """機能: 因果的A0の新設行だけ新規を許し、既存短縮機構で出口影を運転する。

    引数: ready/config(dict)、state/context(ndarray)、詳細・約定(bool)、他は旧署名互換。
    返り値: 旧10配列、通常A0 scheduler、新設許可列(dict)。終了解放行の事後コピーはしない。
    """
    if width_mode!=0 or trail_atr is not None or prepare_allow is not None or min_delay_seconds!=0:
        raise ValueError('今回の同期統合は固定A0・伝達0秒・内部準備許可に限定します')
    selected=(float(config['tighten_atr']),float(config['tight_width']))
    if selected not in ((0.,1.),(3.,1.5),(3.,.75)):
        raise ValueError('統合出口はE00/E10/E11だけです')
    baseline=dict(config,tighten_atr=0.,tight_width=1.)
    scheduler=original.run(ready,state,baseline,detail=True,context=context,width_mode=0,
                           observed_fill=observed_fill,min_delay_seconds=0.)
    allow=np.zeros(len(state),np.bool_)
    rows=scheduler['prepare_events'][:,1].astype(np.int64)
    allow[rows]=True
    if selected==(0.,1.):
        result={k:scheduler[k] for k in FIELDS}
    else:
        par=np.array([config[k] for k in PARAMS],float)
        values=original.simulate(ready['time_s'],ready['last'],ready['atr'],ready['atr'],state,
            state if context is None else context,ready['tick'],ready['start'],ready['limit'],ready['us_open'],
            par,True,int(config['audit_cap']),0,bool(observed_fill),allow,0.,float(ready.get('session_close',ready['limit']+600.)))
        result=dict(zip(FIELDS,values))
    # ----------------------------------------
    # 新規準備・初回約定は旧A0と同じ。短縮出口は準備済注文への後発参加を作らない。
    for name in ('prepare_events','entry_preparations'):
        np.testing.assert_array_equal(result[name],scheduler[name])
    a=result['orders'];b=scheduler['orders']
    np.testing.assert_array_equal(a[a[:,7]==1],b[b[:,7]==1])
    # 途中切断では短縮側だけ完済済みの場合がある。旧影完済組だけを対応させる。
    actual={int(c[0]):c for c in result['cycles']}
    for c in scheduler['cycles']:
        assert int(c[0]) in actual,'旧影完済後も短縮影が未返済'
        own=actual[int(c[0])]
        np.testing.assert_array_equal(own[[0,1,4,5,8]],c[[0,1,4,5,8]])
        assert own[2]<=c[2],'短縮影が旧影より後に返済'
    result['scheduler']=scheduler
    result['schedule_prepare_allow']=allow
    return result
