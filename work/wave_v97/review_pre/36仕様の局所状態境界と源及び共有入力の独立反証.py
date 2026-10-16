"""97の少数の意味ある人工境界を確認し、正式損益を読まない。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace

os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
import numpy as np


def module(name: str, path: Path) -> object:
    """
    機能: 正式mainを呼ばず、診断対象のコードだけ読む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。JIT/バイトコードを保存しない。
    """
    spec = importlib.util.spec_from_file_location(name,path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(value: object) -> str:
    """
    機能: 人工入力の変更を検出する。
    引数: value(object)は辞書又は配列。
    返り値: strはpickle内容指紋。
    """
    return hashlib.sha256(pickle.dumps(value,protocol=5)).hexdigest()


def fixture(config: dict, side: int, progress: list[float], times: list[float] | None = None,
            peer_flat: bool = False) -> tuple[dict,dict]:
    """
    機能: 候補1回、現在J2許可、公開済みpeerを持つ局所TOPIX人工を作る。
    引数: config(dict)、side(int)、progress(list[float])、times(list|None)、peer_flat(bool)。
    返り値: tuple[dict,dict]は原板と信号。保存価格/新正式結果は読まない。
    """
    n = len(progress)
    stamps = np.asarray(times if times is not None else np.arange(n)+300.,float)
    quote = 4000.+side*np.asarray(progress)
    bid = quote-.5 if side == 1 else quote
    ask = quote if side == 1 else quote+.5
    record = dict(symbol='TOPIX',tick=.5,start=0.,limit=10000.,time_s=stamps,
                  price=(bid+ask)/2,bid=bid,ask=ask,price_valid=np.ones(n,bool),
                  quote_valid=np.ones(n,bool),seq=np.arange(n)+100)
    event = np.zeros(n,np.int8)
    event[0] = side
    peer_progress = np.zeros(n) if peer_flat else np.asarray(progress)/.5*10.
    peer_bid = 70000.+side*peer_progress
    peer = np.column_stack((np.arange(n),np.arange(n)+200,stamps-.25,
                            peer_bid,peer_bid+10.,np.ones(n)))
    def subordinate(multiple: float) -> float:
        """
        機能: 根仕様の副幅を人工で呼値化する。
        引数: multiple(float)はW4に掛ける倍率。
        返り値: floatは0又は最低1呼値で切上げた幅。
        """
        return 0. if multiple == 0 else max(1,math.ceil(4.*multiple/.5-1e-10))*.5
    signal = dict(grid=stamps.copy(),mapped=np.arange(n),mode=np.zeros(n,np.int8),
        event=event,quality=np.ones(n,bool),reset=np.zeros(n,bool),trend_width=16.,peer_tick=10.,
        trend_initial_stop_width=max(2,math.ceil(4000.*config['trend_initial_stop_bp']/10000./.5-1e-10))*.5,
        entry_wait_width=4.,entry_advance_width=subordinate(config['entry_advance_widths']),
        entry_pullback_width=subordinate(config['entry_pullback_widths']),
        entry_recovery_width=subordinate(config['entry_recovery_widths']),
        entry_j2_long=np.ones(n,bool),entry_j2_short=np.ones(n,bool),
        wait_opposite_long=np.zeros(n,bool),wait_opposite_short=np.zeros(n,bool),entry_peer_bbo=peer)
    return record,signal


def main() -> None:
    """
    機能: 局所人工・源境界・静的入力非変更を確認しreview_preだけへ保存する。
    引数: なし。
    返り値: None。正式再生/API/新損益閲覧を行わない。不一致は例外。
    """
    engine = module('97待機局所独立境界',BASE/'engine.py')
    catalog = module('97待機局所固定条件',BASE/'catalog.py')
    strategy = module('97待機局所共有copy',BASE/'strategy.py')
    configs = {c['id']:c for c in catalog.catalog()}
    assert len(configs)==36 and catalog.PRIMARY=='A7_X3'
    evidence = []
    def play(ident: str, side: int, values: list[float], change: object = None,
             times: list[float] | None = None, peer_flat: bool = False) -> dict:
        """
        機能: 当該境界だけの人工を実行し入力非変更も確認する。
        引数: ident(str)、side(int)、values(list[float])、change(callable|None)、times(list|None)、peer_flat(bool)。
        返り値: dictは人工出力。実資産及び新正式損益を使わない。
        """
        record,signal=fixture(configs[ident],side,values,times,peer_flat)
        if change is not None:
            change(record,signal)
        before=digest((record,signal,configs[ident]))
        value=engine.execute(record,signal,configs[ident],finish=False)
        assert before==digest((record,signal,configs[ident]))
        return value

    # ----------------------------------------
    # 追加条件の対照は意味が違う代表だけを買売反射で確認する。
    for side in (-1,1):
        a2=play('A2_X1',side,[0.,4.,4.5],peer_flat=True)
        a3=play('A3_X1',side,[0.,4.,4.5],peer_flat=True)
        assert a2['orders'][0,1]==1 and len(a3['orders'])==0
        a5=play('A5_X1',side,[0.,2.,2.5])
        a6=play('A6_X1',side,[0.,2.,2.5])
        assert a5['orders'][0,1]==1 and len(a6['orders'])==0
        arm=play('A6_X1',side,[0.,12.,10.,12.,12.5])
        cols={name:i for i,name in enumerate(arm['watch_state_columns'])}
        state=arm['watch_state_trace'][2]
        assert state[cols['phase_row']]==2 and state[cols['opposite_extreme']]==4000.+side*10.
        assert arm['orders'][0,1]==3 and arm['orders'][0,0]==4
        assert side*(arm['orders'][0,6]-4000.)==12.5
        assert arm['target_trace'][0,2 if side==1 else 3]==8 and arm['target_trace'][0,4]==8
        assert arm['target_trace'][3,4]==8 and arm['target_trace'].max()==8
        assert arm['target_trace'][0,0]+arm['target_trace'][0,1]==0 and arm['curve'][0]==0
        evidence.append(dict(方向=side,A2価格のみとA3確認追加一致=True,A5とA6押し追加一致=True,
            初arm極値初期化同行新規禁止=True,候補より悪い実取得を保持=True,待機占有二重無=True))

    # A2は正常復帰初回で可、確認系はfallback初回不可。
    def unknown(record: dict, signal: dict) -> None:
        """
        機能: 最初2原行の相手資格だけを不明にする。
        引数: record/signal(dict)は人工。
        返り値: None。値を0へ救済せずvalidを落とす。
        """
        signal['entry_peer_bbo'][:2,5]=0.
    a2=play('A2_X1',1,[0.,4.,4.5,5.,5.5],unknown)
    a3=play('A3_X1',1,[0.,4.,4.5,5.,5.5],unknown)
    assert a2['orders'][0,1]==2 and a3['orders'][0,1]==3
    fallback=a3['entry_wait_events'][a3['entry_wait_events'][:,1]==7]
    assert len(fallback)==1 and fallback[0,0]==2
    evidence.append(dict(A2正常復帰初回可=True,BBO系fallback行禁止=True))

    # 既知の取消と停止だけの条件を同一視しない。
    def quality(record: dict,signal: dict) -> None:
        """
        機能: qualityだけ1行不合格にする。
        引数: record/signal(dict)。
        返り値: None。qok及びresetは変えない。
        """
        signal['quality'][1]=False
    paused=play('A2_X1',1,[0.,4.,4.5,5.],quality)
    assert paused['orders'][0,1]==2 and not np.any(paused['entry_wait_events'][:,1]==3)
    def opposite(record: dict,signal: dict) -> None:
        """
        機能: 支持入力から独立した両反対3bpの取消旗を立てる。
        引数: record/signal(dict)。
        返り値: None。現在許可をTrueのままにして優先順を反証する。
        """
        signal['wait_opposite_long'][2]=True
    canceled=play('A2_X1',1,[0.,0.,4.,4.5],opposite)
    assert len(canceled['orders'])==0
    assert np.any((canceled['entry_wait_events'][:,1]==3)&(canceled['entry_wait_events'][:,2]==6))
    def arriving(record: dict,signal: dict) -> None:
        """
        機能: 失効と同じ行に別候補を置く。
        引数: record/signal(dict)。
        返り値: None。行頭watchの占有規則を確認する。
        """
        signal['event'][2]=-1
    ttl=play('A6_X1',1,[0.,0.,0.,0.],arriving,[300.,301.,600.,601.])
    assert not len(ttl['orders']) and ttl['watch_state_trace'][2,0]==0
    assert np.any((ttl['entry_wait_events'][:,1]==3)&(ttl['entry_wait_events'][:,2]==2))
    assert np.any((ttl['entry_wait_events'][:,1]==2)&(ttl['entry_wait_events'][:,2]==7))
    gap=play('A6_X1',1,[0.,0.,0.,0.],times=[300.,310.,320.01,321.])
    assert gap['watch_state_trace'][1,0]==1 and gap['watch_state_trace'][2,0]==0
    evidence.append(dict(quality単独は停止=True,硬い取消がtriggerより先=True,
        TTL等号取消=True,解除行の別候補拒否=True,自己gap10秒境界一致=True))

    # ----------------------------------------
    # helperの源/代理clock/未来上限と、anchorだけの再設定を確認。
    observation=np.array([2.,12.,102.,101.,102.,2.,22.,101.75,1010.,1020.])
    watch=np.full(32,np.nan)
    engine.entry_watch_start(watch,1,1,0,10,100.,100.,2.,0.,2.,1.,300.,7,
        np.array([1.,11.,100.,100.,101.,1.,21.,99.75,1000.,1010.]),True,0)
    assert engine.entry_pair_valid(observation,True,True)
    assert engine.entry_bbo_status(watch,observation,True,1.,10.)==(True,True)
    stale=observation.copy();stale[2]=100.
    assert engine.entry_bbo_status(watch,stale,True,1.,10.)==(False,False)
    future=observation.copy();future[7]=103.
    assert not engine.entry_pair_valid(future,True,True)
    state=watch[:17].copy()
    engine.entry_anchor(watch,observation,True,2,2)
    np.testing.assert_array_equal(watch[:17],state)
    assert engine.entry_bbo_status(watch,observation,True,1.,10.)==(False,False)

    # prefixは候補/arm/triggerを切り、未来の自己/相手価格を変形する。
    record,signal=fixture(configs['A7_X3'],1,[0.,12.,8.,10.,10.5,11.])
    output=engine.execute(record,signal,configs['A7_X3'],finish=False)
    for cut in (2,3,4):
        part={k:(v[:cut].copy() if isinstance(v,np.ndarray) else v) for k,v in record.items()}
        sig={k:(v[:cut].copy() if isinstance(v,np.ndarray) else v) for k,v in signal.items()}
        small=engine.execute(part,sig,configs['A7_X3'],finish=False)
        poisoned=deepcopy(record);poisoned['bid'][cut:]+=100.;poisoned['ask'][cut:]+=100.
        altered=deepcopy(signal);altered['entry_peer_bbo'][cut:,3:5]+=1000.
        changed=engine.execute(poisoned,altered,configs['A7_X3'],finish=False)
        for name in ('curve','target_trace','watch_state_trace'):
            np.testing.assert_array_equal(small[name],output[name][:cut])
            np.testing.assert_array_equal(changed[name][:cut],output[name][:cut])

    # 型/支持不足と0呼値を補完せず明示拒否する。
    for field, replacement in (('peer_tick',0.),('entry_j2_long',np.ones(1,bool))):
        record,signal=fixture(configs['A3_X1'],1,[0.,4.,4.5])
        signal[field]=replacement
        try:
            engine.execute(record,signal,configs['A3_X1'],finish=False)
        except AssertionError:
            pass
        else:
            raise AssertionError('待機必須素材の不適合を明示拒否してください: '+field)

    # 静的配列引数無mutationと、36設定の浅いcopyを確認。
    tree=ast.parse((BASE/'engine.py').read_text(encoding='utf-8'))
    body=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='simulate')
    params={v.arg for v in body.args.args}
    stores=[]
    for node in ast.walk(body):
        if isinstance(node,ast.Subscript) and isinstance(node.ctx,ast.Store):
            target=node.value
            while isinstance(target,ast.Subscript):
                target=target.value
            if isinstance(target,ast.Name) and target.id in params:
                stores.append((target.id,node.lineno))
    assert not stores
    capture=[];saved=strategy.ENGINE
    strategy.ENGINE=SimpleNamespace(execute=lambda record,signal,config,finish:capture.append(signal))
    common={('人工','TOPIX'):dict(record={'tick':.5},reference_open=4000.,
        signal={'trend_width':16.,'event':np.array([1],np.int8)})}
    before=digest(common)
    for cfg in configs.values():
        strategy.play(cfg,('人工','TOPIX'),common,finish=False)
    strategy.ENGINE=saved
    assert digest(common)==before and len(capture)==36
    assert all(v is not common['人工','TOPIX']['signal'] and v['entry_wait_width']==4. for v in capture)
    paths=[BASE/name for name in ('engine.py','strategy.py','catalog.py','結果前の設計案.json')]+[Path(__file__)]
    result=dict(全合格=True,段階='局所少数人工及び静的レビュー。正式損益/原本/APIなし。',
        条件数=36,主=catalog.PRIMARY,必要境界の証拠=evidence,
        源のclock厳密更新と未来上限一致=True,fallbackは価格状態を変更しない=True,
        人工prefix切断と自己相手未来変形3点=True,共有copy36条件無mutation=True,
        配列引数Store=stores,型及びpeer0tick拒否=True,
        限界='全36人工/実全248即時旧一致/全原本経路/CLI末尾は担当監査の別証跡。局所合格を正式成績又は全面監査の代用にしない。',
        SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        新97正式売買実行=0,新97正式損益計算=0,新97正式損益閲覧=0,API取得=0,実注文=0,旧96変更=0)
    path=HERE/'36仕様の局所状態境界と源及び共有入力の独立反証.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('97局所状態境界と源及び共有入力の独立反証が合格しました。正式PL0。')


if __name__=='__main__':
    main()
