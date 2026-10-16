"""105の単一部品対照へ、既存候補と外部filterを同正常原行で接続する。"""

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys

import numba
import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(name: str, path: Path) -> object:
    """
    機能: 105所有sourceだけを固有名で接続し、JIT保存先も同所有域へ限定する。
    引数: name(str)は識別名、path(Path)は105engine source。
    返り値: objectは読取部品。旧104をimportせず旧cacheへ書かない。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    os.environ['NUMBA_CACHE_DIR']=str(HERE/'engine/jit')
    numba.config.CACHE_DIR=str(HERE/'engine/jit')
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,path)
        value=importlib.util.module_from_spec(spec)
        sys.modules[name]=value
        spec.loader.exec_module(value)
    os.environ['NUMBA_CACHE_DIR']=str(HERE/'engine/jit')
    numba.config.CACHE_DIR=str(HERE/'engine/jit')
    return sys.modules[name]


def connect(prepared_value: dict, normal_case: dict, config: dict, quantity: int=1,
            entry_filter: np.ndarray | None=None, filter_reason: np.ndarray | None=None) -> tuple[dict,dict]:
    """
    機能: 不変normal候補、実量、外部mask及び選択自己根拠を105へ結ぶ。
    引数: prepared_value/normal_case/config(dict)、quantity(int)、入口mask(np.ndarray | None)、拒否理由(np.ndarray | None)。
    返り値: tuple[dict,dict]はsignalと数量固定config。特徴再計算、将来正常行検索はしない。
    """
    record=prepared_value['record']
    n=len(record['seq'])
    assert isinstance(quantity,int) and not isinstance(quantity,bool)
    for name in ('event','support_price','entry_quality','entry_reset'):
        assert normal_case[name].shape==(n,),name
    assert normal_case['event'].dtype==np.int8 and np.isin(normal_case['event'],(-1,0,1)).all()
    assert normal_case['entry_quality'].dtype==normal_case['entry_reset'].dtype==np.bool_
    mapping=normal_case['execution_to_raw_index']
    assert mapping.shape==(n,) and np.issubdtype(mapping.dtype,np.integer)
    assert np.all(np.diff(mapping)>0)
    decisions=normal_case['decisions']
    assert len(decisions)==np.count_nonzero(normal_case['event'])
    assert {int(row['row']) for row in decisions}==set(np.flatnonzero(normal_case['event']))
    anchors=np.full(n,-1,np.int64)
    for row in decisions:
        current=int(row['row'])
        assert int(row['normal_row'])==current and int(row['raw_row'])==int(mapping[current])
        assert int(row['raw_seq'])==int(record['seq'][current])
        assert int(row['side'])==int(normal_case['event'][current])
        assert np.isfinite(normal_case['support_price'][current]) and normal_case['support_price'][current]>0
        assert float(row['support_price'])==float(normal_case['support_price'][current])
        roots=row.get('selected_support_roots',[])
        if config.get('reentry_band',False):
            assert roots,'損失帯解除には選択された当時自己根拠が必須です'
        if roots:
            for root in roots:
                anchor=root['anchor_raw_seq']
                assert isinstance(anchor,(int,np.integer)) and not isinstance(anchor,bool)
                assert 0<=int(anchor)<=int(record['seq'][current])
                assert float(root['support_price'])==float(row['support_price'])
            anchors[current]=min(int(root['anchor_raw_seq']) for root in roots)
    mask=np.ones(n,bool) if entry_filter is None else entry_filter
    reasons=np.zeros(n,np.int32) if filter_reason is None else filter_reason
    assert mask.shape==(n,) and mask.dtype==np.bool_
    assert reasons.shape==(n,) and np.issubdtype(reasons.dtype,np.integer)
    signal=dict(event=normal_case['event'],support_price=normal_case['support_price'],
        entry_quality=normal_case['entry_quality'],entry_reset=normal_case['entry_reset'],
        decisions=decisions,execution_to_raw_index=mapping,anchor_raw_seq=anchors,
        entry_filter=mask,filter_reason=reasons,
        reference_open=float(prepared_value['reference_open']),trend_width=float(prepared_value['signal']['trend_width']))
    settings=dict(deepcopy(config),quantity=quantity)
    return signal,settings


def play(prepared_value: dict, normal_case: dict, config: dict, quantity: int=1,
         finish: bool=True, python: bool=False, entry_filter: np.ndarray | None=None,
         filter_reason: np.ndarray | None=None) -> dict:
    """
    機能: 同じ原候補を、105の単一リスク部品と実数量料金で再生する。
    引数: prepared_value/normal_case/config(dict)、quantity(int)、finish/python(bool)、外部入口mask/理由(np.ndarray | None)。
    返り値: dictは104互換の経済台帳と105制御診断。金融全場を暗黙に開始しない。
    """
    signal,settings=connect(prepared_value,normal_case,config,quantity,entry_filter,filter_reason)
    engine=module('106純価格往復と旧C_B4の単一執行',HERE/'engine/core.py')
    signal['quiet']=normal_case.get('quiet',np.zeros(len(signal['event']),np.bool_))
    signal['quiet_start_s']=normal_case.get('quiet_start_s',np.full(len(signal['event']),np.nan,np.float64))
    signal['entry_families']=normal_case.get('entry_families',np.where(signal['event']!=0,1,0).astype(np.int8))
    signal['target_prices']=normal_case.get('target_prices',np.full(len(signal['event']),np.nan,np.float64))
    for name in ('entry_stop_prices','entry_limit_prices','entry_modes','range_pending_trend'):signal[name]=normal_case[name]
    output=engine.execute(prepared_value['record'],signal,settings,finish=finish,python=python)
    assign_sources(prepared_value['record'],output,signal)
    for diagnostic in output['raw_entry_diagnostics']:
        if diagnostic['source'] != 1:continue
        at=int(diagnostic['fill_row']);decision=int(diagnostic['decision_row']);side=int(diagnostic['side'])
        record=prepared_value['record'];stop=float(signal['entry_stop_prices'][decision]);target=float(signal['target_prices'][decision])
        clearing=float(record['bid'][at] if side==1 else record['ask'][at])
        mode=int(signal['entry_modes'][decision])
        planned=float(signal['entry_limit_prices'][decision] if mode==2 else record['ask'][decision] if side==1 else record['bid'][decision])
        diagnostic.update(entry_mode='MARKET' if mode==1 else 'LIMIT',posted_limit=float(signal['entry_limit_prices'][decision]) if mode==2 else None,
            fill_known_trend=bool(signal['range_pending_trend'][at]),fill_fixed_stop_broken=bool(side*(clearing-stop)<=record['tick']*1e-8),
            fill_target_already_reached=bool(side*(clearing-target)>=-record['tick']*1e-8),unfavourable_fill_ticks=side*(diagnostic['fill_price']-planned)/record['tick'],
            pending_rule='既livefillを保持。knownTRENDだけでは保有後退出せず、固定stop/target/forceを判断する。')
    output.update(entry_id=normal_case['entry_id'],config_id=config['id'],
        anchor_policy='同値selected_support_rootsは全て新anchorを要求し、最小int64anchorで比較。',
        input_contract='既存normal event/support/entry_quality/reset/map/lineageを同原行で使用。外部filterは当該行だけ。')
    return output


def assign_sources(record: dict, output: dict, signal: dict) -> None:
    """
    機能: 単一口座の各実親へC/Rの源を結び、実注文から源別時価を分ける。
    引数: record/output/signal(dict)は同正常入力、経済台帳と選択family。
    返り値: None。親番号を変えず、料金を別注文へ再計算しない。
    """
    mapping={int(o[2]):int(signal['entry_families'][int(o[1])])-1 for o in output['orders'] if o[7]}
    for row in output['events']:
        if row[3]==1:
            mapping[int(row[1])]=int(signal['entry_families'][int(row[0])])-1
    for name,parent_column,source_column in (('orders',2,3),('trades',0,1),('growth_cohorts',0,2)):
        for row in output[name]:row[source_column]=mapping[int(row[parent_column])]
    for row in output['events']:
        parent=int(row[1]);at=int(row[0])
        if parent in mapping:row[2]=mapping[parent]
        elif signal['entry_families'][at]>0:row[2]=int(signal['entry_families'][at])-1
    for diag in output['raw_entry_diagnostics']:
        source=mapping[int(diag['parent_id'])];diag.update(source=source,family='C' if source==0 else 'R_PRICE')
        if source==1:
            diag['fixed_price_stop']=diag.pop('fixed_support_price')
            diag['reference_kind']='純価格範囲外停止・板支持を意味しない'
    n=len(record['seq']);qok=(record['quote_valid']&np.isfinite(record['time_s'])&np.isfinite(record['bid'])&
        np.isfinite(record['ask'])&(record['bid']>0)&(record['ask']>record['bid']))
    latest=np.maximum.accumulate(np.where(qok,np.arange(n),-1));m=1000. if record['symbol']=='TOPIX' else 10.
    curves=[]
    for source in (0,1):
        cash,qty,fee=(np.zeros(n) for _ in range(3))
        for o in output['orders'][output['orders'][:,3]==source]:
            at=int(o[0]);q=int(o[5]);cash[at]-=o[4]*q*o[6]*m+o[9]
            qty[at]+=o[15]*q*(1 if o[7] else -1);fee[at]+=o[9]*(1 if o[7] else -1)
        cash=np.cumsum(cash);qty=np.cumsum(qty);fee=np.cumsum(fee)
        assert fee.min(initial=0)>=0
        held=qty!=0;assert np.all(latest[held]>=0)
        positive=qty>0;negative=qty<0
        cash[positive]+=qty[positive]*record['bid'][latest[positive]]*m
        cash[negative]+=qty[negative]*record['ask'][latest[negative]]*m
        curves.append(cash-fee)
    output['source_curve']=np.column_stack(curves)
    np.testing.assert_allclose(output['source_curve'].sum(axis=1),output['curve'],atol=1e-4,rtol=0)
    output['source_names']={0:'C進行',1:'R_PRICE価格往復の固定中心回帰'}

