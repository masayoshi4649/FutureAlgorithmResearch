"""損益を参照せず、二市場の入口十二条件と保有判断用の共同状態を作る。"""

import importlib.util
from pathlib import Path
import sys

import numba
import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SYMBOLS=('TOPIX','NK225')


def legacy_module() -> object:
    """機能: 旧入口の確認・イベント化を、名前やキャッシュの衝突なしで読み込む。

    引数: なし。返り値: 旧wave76の信号モジュール(object)。旧成果には書き込まない。
    """
    name='二市場信号76の固定読取77'
    if name in sys.modules:return sys.modules[name]
    previous=numba.config.CACHE_DIR
    spec=importlib.util.spec_from_file_location(name,ROOT/'work/wave_v76/signals.py')
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value
    try:spec.loader.exec_module(value)
    finally:numba.config.CACHE_DIR=previous
    return value


LEGACY=legacy_module()


def defs() -> list[dict]:
    """機能: 入口十二種類の固定仕様と平易な説明を返す。

    引数: なし。返り値: ID・群・変種・説明・条件の列(list[dict])。
    """
    texts={
        'J0':'従来の両市場5分方向一致の入口をそのまま使う。',
        'J1':'従来入口で、どちらかの15秒注文増減が明確に逆向きなら入らない。',
        'J2':'逆向き注文増減を除外し、両市場の5分進行が同方向で、弱い側も強い側の4分の1以上を求める。',
        'J3':'足並みに加え、両市場の5分純移動が総価格変動の2割以上を求める。',
        'Q0':'両市場の最良1段の板偏りが同方向に25%以上の状態を、双方の更新を伴って10秒確認して入る。',
        'Q1':'従来の最良1段入口で、どちらかの15秒注文増減が明確に逆向きなら入らない。',
        'Q2':'従来の最良1段入口で、両市場の3分価格が入口方向へ各1bp以上進んでいる時だけ入る。',
        'Q3':'3分価格の支持に加え、明確な逆向き注文増減も除外する。',
        'P0':'両市場の5分方向を保ったまま、両方が30秒で反落した後に再進行を10秒確認して入る。',
        'P1':'30秒の反落後再進行に、明確な逆向き注文増減の除外を加える。',
        'P2':'両市場の5分方向を保ったまま、両方が60秒で反落した後に再進行を10秒確認して入る。',
        'P3':'60秒の反落後再進行に、明確な逆向き注文増減の除外を加える。'}
    output=[]
    for family in ('J','Q','P'):
        for variant in range(4):
            ident=f'{family}{variant}'
            output.append(dict(id=ident,family=family,variant=variant,説明=texts[ident],
                逆OFI除外=variant>=1 if family=='J' else variant in (1,3),
                反落窓秒=(30 if variant<2 else 60) if family=='P' else None))
    return output


def confirmation(grid: np.ndarray,condition: np.ndarray,valid: np.ndarray,
                 source_a: np.ndarray,source_b: np.ndarray,seconds: float) -> np.ndarray:
    """機能: 旧検証と同じ、連続条件と両市場の参照行更新による確認を行う。

    引数: grid(float配列)、condition/valid(bool配列)、source_a/source_b(int配列)、seconds(float)。
    返り値: 確認完了(bool配列)。旧JITのPython本体を使い、旧キャッシュを変更しない。
    """
    return LEGACY.confirmation.py_func(grid,condition,valid,source_a,source_b,seconds)


def pulses(grid: np.ndarray,strong: np.ndarray,valid: np.ndarray,confirmed: np.ndarray) -> np.ndarray:
    """機能: 旧検証と同じ60秒間隔・中立10秒で再準備する入口を作る。

    引数: grid(float配列)、strong/confirmed(int配列)、valid(bool配列)。
    返り値: 入口方向(int8配列)。追加フィルタはこのイベント化後に適用する。
    """
    return LEGACY.pulses.py_func(grid,strong,valid,confirmed)


def q_market(market: dict) -> dict:
    """機能: 旧Q25の十段データ品質判定を、新価格素材の品質と混ぜず接続する。

    引数: market(dict)。返り値: current.validだけq_validへ置換した浅いコピー(dict)。
    最良1段の偏りは十段が揃った時だけ有効とする旧仕様を保ち、元素材を書き換えない。
    """
    return dict(market,current=dict(market['current'],valid=market['current']['q_valid']))


def flow_test(session: dict,direction: int) -> tuple[np.ndarray,np.ndarray]:
    """機能: 観測十分な15秒注文増減の逆向き証拠と、両側支持を分ける。

    引数: session(dict)、direction(int:1/-1)。返り値: 逆向きあり、双方支持(bool配列のtuple)。
    無効・少数・零注文増減は逆行の証拠にも支持の証拠にも使わない。
    """
    size=len(session['grid']);reverse=np.zeros(size,dtype=bool);support=np.ones(size,dtype=bool)
    for symbol in SYMBOLS:
        f=session['markets'][symbol]['flow'][15]
        sufficient=f['source_valid']&f['valid']&~f['missing_ofi']&(f['nonzero_ofi_count']>=3)&np.isfinite(f['ofi_ratio'])
        signed=direction*f['ofi_ratio']
        reverse |= sufficient&(signed<=-.1)
        support &= sufficient&(signed>=.1)
    return reverse,support


def direction_condition(session: dict,window: int,direction: int,threshold_bp: float,
                        inclusive: bool=True) -> np.ndarray:
    """機能: 二市場の同じ過去価格窓から、方向と必要な相対進行を判定する。

    引数: session(dict)、window/direction(int)、threshold_bp(float)、inclusive(bool)。
    返り値: 双方が条件を満たす格子(bool配列)。1bpは0.01%でATRは使わない。
    """
    out=np.ones(len(session['grid']),dtype=bool)
    for symbol in SYMBOLS:
        w=session['markets'][symbol]['windows'][window];signed=direction*w['ret_bp']
        out &= w['source_valid']&np.isfinite(signed)&((signed>=threshold_bp) if inclusive else (signed>threshold_bp))
    return out


def recovery_events(session: dict,window: int) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    """機能: 共通の5分方向を保つ反落から、短期再進行を確認して一度だけ入口にする。

    引数: session(dict)、window(int:30/60)。返り値: 入口(int8配列)、買/売再進行状態(bool配列のtuple)。
    反落開始だけで準備し期限180秒。条件が無効・共通方向が消失/反転・格子欠落で準備を破棄する。
    期限切れの同じ反落で再準備せず、新しい反落開始を待つ。未来に確認された入口は過去へ戻さない。
    """
    grid=session['grid'];size=len(grid);valid=np.ones(size,dtype=bool)
    sources=[session['markets'][s]['current']['index'] for s in SYMBOLS]
    trend={d:direction_condition(session,300,d,3.) for d in (-1,1)}
    pull={};resume={}
    for d in (-1,1):
        pull[d]=np.ones(size,dtype=bool);resume[d]=np.ones(size,dtype=bool)
        for symbol in SYMBOLS:
            m=session['markets'][symbol];w=m['windows'][window]
            valid &= m['current']['valid']&w['source_valid']
            pull[d] &= d*w['ret_bp']<0
            resume[d] &= (d*w['ret_bp']>0)&(d*w['bid_change_ticks']>=1.-1e-8)&(d*w['ask_change_ticks']>=1.-1e-8)
    event=np.zeros(size,dtype=np.int8);armed=0;arm_time=-1.;confirm_start=-1
    prior_direction=0;prior_pullback=False;last_event=-1e30;previous=-1e30
    for i in range(size):
        gap=grid[i]-previous>5.+1e-8;previous=grid[i]
        d=1 if trend[1][i] else -1 if trend[-1][i] else 0
        if gap or not valid[i] or d==0:
            armed=0;arm_time=-1.;confirm_start=-1;prior_direction=0;prior_pullback=False
            continue
        if d!=prior_direction:
            armed=0;arm_time=-1.;confirm_start=-1;prior_pullback=False
        current_pullback=bool(pull[d][i])
        if armed and grid[i]-arm_time>180.+1e-8:
            armed=0;arm_time=-1.;confirm_start=-1
        if not armed and current_pullback and not prior_pullback:
            armed=d;arm_time=grid[i];confirm_start=-1
        if armed:
            if not resume[d][i]:confirm_start=-1
            elif confirm_start<0:confirm_start=i
            elif grid[i]-grid[confirm_start]>=10. and sources[0][i]>sources[0][confirm_start] and sources[1][i]>sources[1][confirm_start]:
                if grid[i]-last_event>=60.:
                    event[i]=d;last_event=grid[i]
                armed=0;arm_time=-1.;confirm_start=-1
        prior_direction=d;prior_pullback=current_pullback
    return event,trend[1]&resume[1]&valid,trend[-1]&resume[-1]&valid


def session_state(session: dict,ticks: dict) -> dict:
    """機能: 一場の入口十二条件と追加・反対返済・構造損切り用状態を作る。

    引数: session(dict:共通格子と市場素材)、ticks(dict:商品別ラージ呼値)。
    返り値: grid/valid/common/opposite/reference/entries(dict)。損益台帳は参照しない。
    """
    grid=session['grid'];a=session['markets']['TOPIX'];b=session['markets']['NK225']
    valid=a['current']['valid']&b['current']['valid'];size=len(grid)
    sa,sb=a['current']['index'],b['current']['index']
    reverse={};support={}
    for d in (-1,1):reverse[d],support[d]=flow_test(session,d)
    entries={}
    # ----------------------------------------
    # 従来J入口のイベントはstudyが原本へ接続する。ここでは当該時点の許可だけを返す。
    for variant in range(4):
        allowed={}
        for d in (-1,1):
            yes=np.ones(size,dtype=bool) if variant==0 else valid&~reverse[d]
            if variant>=2:
                ra=d*a['windows'][300]['ret_bp'];rb=d*b['windows'][300]['ret_bp']
                yes &= direction_condition(session,300,d,0.,inclusive=False)
                yes &= np.minimum(ra,rb)>=.25*np.maximum(ra,rb)
            if variant>=3:
                for market in (a,b):
                    w=market['windows'][300]
                    yes &= np.isfinite(w['efficiency'])&(w['efficiency']>=.2)
            allowed[d]=yes
        entries[f'J{variant}']=dict(event=np.zeros(size,dtype=np.int8),long_allowed=allowed[1],short_allowed=allowed[-1])
    # ----------------------------------------
    # Q0は旧Q25の最良1段・10秒確認・イベント化と同一。追加条件で時計を作り直さない。
    definition=next(x for x in LEGACY.definitions() if x['id']=='Q25')
    qa,_,va,_=LEGACY.market_state(definition,q_market(a));qb,_,vb,_=LEGACY.market_state(definition,q_market(b))
    qvalid=va&vb;strong=np.where(qvalid&(qa==qb),qa,0).astype(np.int8)
    confirmed=confirmation(grid,strong==1,qvalid,sa,sb,10.).astype(np.int8)
    confirmed-=confirmation(grid,strong==-1,qvalid,sa,sb,10.).astype(np.int8)
    qevent=pulses(grid,strong,qvalid,confirmed)
    for variant in range(4):
        allowed={}
        for d in (-1,1):
            yes=qvalid.copy()
            if variant in (1,3):yes &= ~reverse[d]
            if variant>=2:yes &= direction_condition(session,180,d,1.)
            allowed[d]=yes
        event=qevent.copy();event[(event==1)&~allowed[1]]=0;event[(event==-1)&~allowed[-1]]=0
        entries[f'Q{variant}']=dict(event=event,long_allowed=allowed[1],short_allowed=allowed[-1])
    # ----------------------------------------
    # 反落後の入口は30/60秒の二通りだけ。OFI除外は同じ確認完了イベントを棄却する。
    for window,base in ((30,0),(60,2)):
        pevent,long_allowed,short_allowed=recovery_events(session,window)
        for variant in (base,base+1):
            allowed={1:long_allowed.copy(),-1:short_allowed.copy()}
            if variant%2:
                for d in (-1,1):allowed[d] &= ~reverse[d]
            event=pevent.copy();event[(event==1)&~allowed[1]]=0;event[(event==-1)&~allowed[-1]]=0
            entries[f'P{variant}']=dict(event=event,long_allowed=allowed[1],short_allowed=allowed[-1])
    # ----------------------------------------
    # 追加に用いる共通方向と、反対合意の30秒確認は入口とは独立に作る。
    common=np.zeros(size,dtype=np.int8);opposite={}
    for d in (-1,1):
        long_direction=valid&direction_condition(session,300,d,3.)&direction_condition(session,30,d,0.,inclusive=False)
        common[long_direction]=d
        condition=valid&direction_condition(session,30,d,0.,inclusive=False)&support[d]
        opposite[d]=confirmation(grid,condition,valid,sa,sb,30.)
    reference={}
    for symbol in SYMBOLS:
        bounds=session['markets'][symbol]['ranges'][180];available=bounds['source_valid']
        reference[symbol]=dict(long=np.where(available,bounds['low']-ticks[symbol],np.nan),
                               short=np.where(available,bounds['high']+ticks[symbol],np.nan))
    assert set(entries)=={x['id'] for x in defs()}
    return dict(grid=grid,valid=valid,common=common,opposite_long=opposite[-1],opposite_short=opposite[1],
                reference=reference,entries=entries)


def mapping(grid: np.ndarray,ready: dict) -> np.ndarray:
    """機能: 共通格子を以後10秒以内の最初の自原本行へ対応付ける。

    引数: grid(float配列)、ready(dict:time_s)。返り値: 原本各行の最新格子番号(int32配列)。
    同一行に複数格子が届いた場合は最新だけを残し、古い入口を遅れて執行しない。
    """
    return LEGACY.mapping(grid,ready)


def build(grids: dict,ready: dict) -> dict:
    """機能: 全場の共同状態を保存素材だけから作る。

    引数: grids(dict:場別素材)、ready(dict:(場,商品)別原本メタ)。
    返り値: 場→十二入口と共通状態(dict)。料金計算や損益採点は行わない。
    """
    return {session:session_state(value,{s:ready[(session,s)]['tick'] for s in SYMBOLS}) for session,value in grids.items()}
