"""旧A0の準備時計へ同期した、数量4方式×出口3方式の統合窓口。"""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import numpy as np

import exit_partial_integrated as engine

HERE=Path(__file__).resolve().parent
_paths=list(sys.path)
_spec=importlib.util.spec_from_file_location('exit_v44_reference',HERE.parent/'wave_v44/runner.py')
reference=importlib.util.module_from_spec(_spec);sys.modules[_spec.name]=reference;_spec.loader.exec_module(reference)
sys.path[:]=_paths
assert Path(engine.__file__).resolve()==HERE/'exit_partial_integrated.py'
assert Path(reference.engine.__file__).resolve()==HERE.parent/'wave_v41/engine_partial_restore_corrected.py'
FIELDS=reference.FIELDS
STORED=reference.STORED
INPUTS={}


def catalog() -> list[dict]:
    """機能: 元3方式と復元なしの4方式に、固定した3出口を対応させる。

    引数: なし。返り値: 統合12条件(list[dict])。結果で条件を差し替えない。
    """
    fixed=reference.read(HERE.parent/'wave_v44/探索条件の固定.json')
    originals={r['id']:r for r in fixed['conditions']}
    names=[('A0','A0__V000'),('C01','G000_F25_N1__V000'),
           ('F50','G150_F50_N1__V000'),('F50_NONE','G150_F50_N1__V000')]
    out=[]
    for quantity_id,source in names:
        for exit_id,width in [('E00',1.),('E10',1.5),('E11',.75)]:
            row=deepcopy(originals[source]);row.update(id=quantity_id+'__'+exit_id,
                quantity_id=quantity_id,exit_id=exit_id,reference_id=source if quantity_id!='F50_NONE' else None,
                primary=quantity_id=='F50' and exit_id=='E10',role='統合比較',
                tighten_atr=0. if exit_id=='E00' else 3.,tight_width=width)
            if quantity_id=='F50_NONE':
                row['policy'].update(id='B00_NONE_F50',restore_mode='none')
            out.append(row)
    return out


def initialize() -> None:
    """機能: 旧26入力だけを旧検証済み窓口から読む。

    引数: なし。返り値: なし。v47の新ナイト入力を読まない。
    """
    global INPUTS
    reference.initialize();INPUTS=reference.INPUTS
    assert len(INPUTS)==26 and all(s<='2026-09-29_Day' for s,_ in INPUTS)


def columns_for(spec: dict, key: tuple) -> tuple:
    """機能: 入口と途中判断の元10列を変更せず取得する。

    引数: spec(dict)、key(tuple)。返り値: 旧10配列(tuple)。
    """
    return reference.columns_for(spec,key)


def quality_for(spec: dict, key: tuple) -> np.ndarray:
    """機能: 元B00公開品質を悪化判定用に得る。

    引数: spec(dict)、key(tuple)。返り値: 品質列(ndarray[bool])。
    """
    return reference.quality_for(spec,key)


def config_for(spec: dict, ready: dict) -> dict:
    """機能: 元設定を複写し、統合出口の短縮2値だけを設定する。

    引数: spec/ready(dict)。返り値: 実使用設定(dict)。
    """
    config=reference.old.base.managers.make_config(reference.old.FIXED['manager'],ready['symbol'],ready)
    return dict(config,tighten_atr=spec['tighten_atr'],tight_width=spec['tight_width'])


def play(spec: dict, ready: dict, columns: tuple, config: dict, *, gate_valid: np.ndarray) -> tuple:
    """機能: 基準影の新規時計・減量許可を保ち、短縮出口影と数量注文器を接続する。

    引数: spec/ready/config(dict)、columns(tuple)、gate_valid(ndarray[bool])。
    返り値: 実結果・実使用10列・到達証拠(tuple)。切断時は影も再生成する。
    """
    assert spec['observed_fill'] is False and spec['min_delay_seconds']==0
    assert config['tighten_atr']==spec['tighten_atr'] and config['tight_width']==spec['tight_width']
    shadow=engine.make_shadow(ready,columns[0],config,False,0.)
    scheduler=shadow['scheduler']
    bad,source,evidence=reference.gate.gate_bad(ready,scheduler,columns[1],columns[2],
        spec['gate_threshold_atr'],mode=spec['gate_mode'],valid=gate_valid)
    effective=(columns[0],bad,source,*columns[3:])
    result=reference.reference.play(engine,spec,ready,effective,config,shadow)
    assert result['shadow'] is shadow
    return result,effective,evidence


def initial_identity(result: dict) -> dict:
    """機能: 通常影・出口影・実口座の初回と完済順を因果的な結果で検査する。

    引数: result(dict)。返り値: 同一性証跡(dict)。途中切断では完済済み組だけ照合する。
    """
    shadow=result['shadow'];scheduler=shadow['scheduler']
    openings=[]
    for obj in (scheduler,shadow,result):
        oo=obj['orders'];openings.append(oo[(oo[:,7]==1)&(oo[:,6]==20)])
    for actual in openings[1:]:np.testing.assert_array_equal(actual,openings[0])
    for name in ('prepare_events','entry_preparations'):
        np.testing.assert_array_equal(result[name],scheduler[name])
    actual={int(c[0]):c for c in result['cycles']}
    middle={int(c[0]):c for c in shadow['cycles']}
    for c in scheduler['cycles']:
        cid=int(c[0]);assert cid in middle and cid in actual
        for d in (middle[cid],actual[cid]):np.testing.assert_array_equal(d[[0,1,4,5,8]],c[[0,1,4,5,8]])
        assert actual[cid][2]<=middle[cid][2]<=c[2]
    return dict(全初回同値=True,実退出が短縮影以前=True,短縮影が通常影以前=True,初回数=len(openings[0]))


def prefix_check(actual: tuple, changed: tuple, count: int) -> None:
    """機能: 実口座・短縮影・元影・許可源の確定済み過去を全列照合する。

    引数: actual/changed(tuple)、count(int)。返り値: なし。全場集計statsは対象外。
    """
    reference.gate_prefix(actual,changed,count)
    left,right=actual[0]['shadow']['scheduler'],changed[0]['shadow']['scheduler']
    for name in engine.shadow_engine.FIELDS:
        if name=='stats':continue
        a,b=left[name],right[name]
        if name in ('curve','atr_curve','plans','execution_plans'):
            a,b=a[:count],b[:count]
        else:
            column=reference.causal.EVENTS[name]
            a,b=a[a[:,column]<count],b[b[:,column]<count]
        reference.causal.exact(a,b,'通常影/'+name)
    reference.causal.exact(actual[0]['shadow']['schedule_prepare_allow'][:count],
        changed[0]['shadow']['schedule_prepare_allow'][:count],'同期許可列')


def causal_check(spec: dict, ready: dict, columns: tuple, config: dict,
                 actual: tuple, gate_valid: np.ndarray) -> dict:
    """機能: 切断・未来改変・売買反射の都度、元影から全入力を再計算する。

    引数: spec/ready/config(dict)、columns/actual(tuple)、gate_valid(ndarray[bool])。
    返り値: 全列の因果照合結果(dict)。完成済み同期許可を流用しない。
    """
    causal=reference.causal;n=len(ready['last']);cut=max(2,int(n*.37))
    short=play(spec,causal.clipped(ready,cut),tuple(v[:cut].copy() for v in columns),
        config,gate_valid=gate_valid[:cut].copy())
    prefix_check(actual,short,cut);del short
    repeated=np.flatnonzero(np.diff(ready['time_s'])==0)+1
    change=int(repeated[np.argmin(abs(repeated-int(n*.73)))]) if len(repeated) else int(n*.73)
    future=causal.clipped(ready,n)
    future['last'][change:]+=ready['tick']*(37+np.arange(n-change));future['atr'][change:]*=3
    altered=[v.copy() for v in columns]
    for index in (0,1,3,6):altered[index][change:]=np.where(altered[index][change:]==1,-1,1)
    for index in (2,4,7):altered[index][change:]=np.arange(change,n)
    for index in (5,8):altered[index][change:]=~altered[index][change:]
    altered[9][change:]=1-altered[9][change:]
    changed_valid=gate_valid.copy();changed_valid[change:]=~changed_valid[change:]
    changed=play(spec,future,tuple(altered),config,gate_valid=changed_valid)
    prefix_check(actual,changed,change);del changed
    # ----------------------------------------
    # 数量・公開源・価格距離は同じまま、全売買方向と価格だけを反転する。
    center=float(2*np.ceil(np.max(ready['last'])/ready['tick'])*ready['tick'])
    mirrored=dict(ready,last=center-ready['last'])
    mirror_columns=tuple(-v if i in (0,1,3,6) else v.copy() for i,v in enumerate(columns))
    mirror=play(spec,mirrored,mirror_columns,config,gate_valid=gate_valid.copy())
    causal.reflected_result(actual[0],mirror[0],center,True)
    for a,b in ((actual[0]['shadow'],mirror[0]['shadow']),
                (actual[0]['shadow']['scheduler'],mirror[0]['shadow']['scheduler'])):
        causal.reflected_result(a,b,center,False)
    causal.exact(actual[0]['shadow']['schedule_prepare_allow'],mirror[0]['shadow']['schedule_prepare_allow'],'反射同期許可')
    for i in range(10):causal.exact(-actual[1][i] if i in (0,1,3,6) else actual[1][i],mirror[1][i],'反射入力'+str(i))
    for name in actual[2]:
        if name=='mfe_atr':causal.close(actual[2][name],mirror[2][name],'反射順行距離')
        else:causal.exact(actual[2][name],mirror[2][name],'反射許可/'+name)
    return dict(先頭切断一致=True,未来変更一致=True,上下反射一致=True,
        切断行=cut,未来変更行=change,元影と短縮影と許可を再生成=True)
