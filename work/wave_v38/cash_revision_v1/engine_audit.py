"""注文遅延と復元分岐を人工経路で検査し、既定のみ旧実装と比較する。"""

from copy import deepcopy
import argparse
import hashlib
import importlib.util
import json
import pickle
from pathlib import Path
import socket
import sys
import urllib.request

import numpy as np

HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'wave_v37'
sys.path.insert(0,str(HERE.parent/'wave_v33'))
import dynamic_atr_engine_audit as helpers


def load_module(name: str, path: Path):
    """機能: 読取専用の旧モジュールを衝突しない名前で取得する。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


old_shadow=load_module('v37_audit_shadow',PRIOR/'engine_shadow_plan.py')
sys.modules['engine_shadow_plan']=old_shadow
old=load_module('v37_audit_partial',PRIOR/'engine_partial_restore.py')
old_design=load_module('v37_audit_design',PRIOR/'partial_design.py')
sys.path.insert(0,str(HERE))
sys.modules.pop('engine_shadow_plan',None)
import engine_partial_restore as engine

POLICIES={p['id']:p for p in old_design.policies()}
PRIMARY=POLICIES[old_design.PRIMARY_POLICY]
OLD_FIELDS=engine.FIELDS+('prepare_events','entry_preparations','control_curve','slot_curve','slot_events','adjustment_events','budget_events')


def reject(*args: object, **kwargs: object) -> None:
    """機能: 監査からの通信を拒否する。

    引数: 任意(object)。返り値: なし(None)、常に例外。
    """
    raise AssertionError('新規API・外部通信は禁止です')


def fixture(prices: list, bad_rows: tuple=(), good_rows: tuple=(), spacing: float=1.) -> tuple:
    """機能: 既存人工価格へ当行sourceと場末の遅延余裕を付ける。

    引数: prices(list)、bad_rows/good_rows(tuple)、spacing(float)。返り値: 旧run引数(tuple)。
    """
    r,s,c,_=helpers.fixture(prices)
    r['time_s'][:-2]*=spacing
    r['time_s'][-1]=r['limit']+30.
    bad=np.zeros(len(s),np.int8);good=bad.copy();bad[list(bad_rows)]=-1;good[list(good_rows)]=1
    source=np.arange(len(s),dtype=np.int64)
    return r,s,c,bad,source,good,source.copy()


def same(a: dict,b: dict,fields: tuple=OLD_FIELDS) -> None:
    """機能: 配列全値を欠測位置込みで厳密比較する。

    引数: a/b(dict)、fields(tuple)。返り値: なし(None)。
    """
    for field in fields:np.testing.assert_array_equal(a[field],b[field],err_msg=field)


def invariants(args: tuple,result: dict,delay: float) -> None:
    """機能: 独立現金会計・元注文一致・注文遅延・枠・期限を検算する。

    引数: args(tuple)、result(dict)、delay(float)。返り値: なし(None)。
    """
    ready,state,config=args[:3];shadow=result['shadow'];n=len(state)
    helpers.account(ready,result,config)
    np.testing.assert_array_equal((result['slot_curve']&2!=0).sum(axis=1),result['curve'][:,2]+result['curve'][:,3])
    a=result['orders'][result['orders'][:,6]==20];b=shadow['orders'][shadow['orders'][:,6]==20]
    np.testing.assert_array_equal(a[:,[0,1,2,3,5]],b[:,[0,1,2,3,5]])
    shadow_end={int(c[0]):int(c[2]) for c in shadow['cycles']}
    for c in result['cycles']:
        assert int(c[0]) not in shadow_end or c[2]<=shadow_end[int(c[0])]
    for row in result['orders']:
        i,j=int(row[0]),int(row[1]);assert 0<=j<i<n
        assert ready['time_s'][i]>=ready['time_s'][j]+delay-1e-8
        assert ready['time_s'][i]<ready.get('session_close',ready['limit']+600.)
    for i,p in enumerate(shadow['execution_plans']):
        if np.isfinite(p[33]):
            source=int(p[33]);assert source<i and ready['time_s'][source]+delay<=ready['time_s'][i]+1e-8


def prefix(result: dict, other: dict, cut: int) -> None:
    """機能: 価格や根拠の将来変更によって過去の全状態が変わらないか確認する。

    引数: result/other(dict)、cut(int)。返り値: なし(None)。
    """
    for field in ('curve','atr_curve','control_curve','slot_curve','branch_curve'):
        np.testing.assert_array_equal(result[field][:cut],other[field][:cut],err_msg=field)
    for field,col in (('orders',0),('trades',7),('cycles',2),('slot_events',0),('adjustment_events',0),
                      ('budget_events',0),('branch_events',0),('prepare_events',1),('entry_preparations',1)):
        np.testing.assert_array_equal(result[field][result[field][:,col]<cut],other[field][other[field][:,col]<cut],err_msg=field)
    for field in ('plans','execution_plans'):
        np.testing.assert_array_equal(result['shadow'][field][:cut],other['shadow'][field][:cut],err_msg=field)


def synthetic() -> list:
    """機能: 分岐・予約・伝達遅延の反例を固定人工入力で確認する。

    引数: なし。返り値: 検査記録(list[dict])。
    """
    rows=[]
    args=fixture([100,101,102,101,100,101,103,104,109,106,95],(2,),(4,))
    for name in ('A0','CORE25','CORE50','SMALL25','SMALL50',old_design.PRIMARY_POLICY,'B06_T120_F50_N1'):
        for observed in (False,True):
            kwargs=dict(observed_fill=observed,good_valid=np.ones(len(args[1]),np.bool_))
            a=engine.run(*args,POLICIES[name],**kwargs);b=old.run(*args,POLICIES[name],**kwargs)
            same(a,b);same(a['shadow'],b['shadow'],engine.FIELDS+('prepare_events','entry_preparations','plans'))
            invariants(args,a,0)
            rows.append(dict(検査='遅延0旧全値一致',方針=name,観測=observed,合格=True))
    # ----------------------------------------
    # 約定時の四分類と選択反転。分岐後にB01が変わっても方式は保持する。
    args=fixture([100,101,102,102,102,102,102,102,95],(2,),(6,))
    args[0]['time_s'][:9]=[0,1,2,3,122,123,124,125,126]
    n=len(args[1]);valid=np.ones(n,np.bool_);source=np.arange(n,dtype=np.int64)
    for direction,is_valid,label in ((-1,True,'逆'),(1,True,'順'),(0,True,'中立'),(0,False,'欠測')):
        bd=np.full(n,direction,np.int8);bv=np.full(n,is_valid,np.bool_);bs=source.copy()
        if not is_valid:bs[:]=-1
        for mode in ('adverse_signal','reverse','random'):
            kwargs=dict(branch_direction=bd,branch_source=bs,branch_valid=bv,branch_mode=mode,good_valid=valid)
            if mode=='random':kwargs.update(branch_choice=np.ones(n,np.int8),branch_seed=7)
            result=engine.run(*args,PRIMARY,**kwargs)
            e=result['branch_events'];assert len(e)==1 and e[0,0]==3
            signal=(is_valid and direction==-1)
            expected=1 if (signal if mode=='adverse_signal' else not signal if mode=='reverse' else True) else 2
            assert e[0,3]==expected
            fills=result['orders'][result['orders'][:,6]==31]
            assert len(fills)==1 and fills[0,0]==(7 if expected==1 else 6)
            invariants(args,result,0)
            rows.append(dict(検査='減量約定時の有効性と固定分岐',分類=label,方式=mode,合格=True))
    # ----------------------------------------
    # 頻繁な公開更新でも成熟した旧価格線は使用できる。
    args=fixture([100]*20+[101]*20+[104]*20+[107]*20+[110]*20+[105]*20+[94]*20, (42,), (48,))
    for delay in (1.,5.,15.):
        for observed in (False,True):
            result=engine.run(*args,PRIMARY,min_delay_seconds=delay,observed_fill=observed)
            invariants(args,result,delay)
            assert len(result['orders'])>0 and result['stats'][9]==0
            a0=engine.run(*args,POLICIES['A0'],min_delay_seconds=delay,observed_fill=observed)
            same(a0,a0['shadow'],engine.FIELDS+('prepare_events','entry_preparations'))
            rows.append(dict(検査='成熟線維持・A0影実同値・次行と秒遅延',秒=delay,観測=observed,合格=True))
    # ----------------------------------------
    # 全予約遅延は同時刻の別行では成熟しない。
    args=fixture([100,101,102,103,104,105,106,107,108,109,95],(6,),(8,))
    args[0]['time_s'][:8]=[0,0,0,0,1,1,1,1]
    result=engine.run(*args,PRIMARY,min_delay_seconds=1.)
    invariants(args,result,1.)
    rows.append(dict(検査='同時刻群で秒遅延を省略しない',合格=True))
    # ----------------------------------------
    # 累積損失による追加退出だけを除去し、元A0全返済は維持する。
    args=fixture([100,101,103,100,103,104,100,99,101,104,100,98,95],(2,6,10),(4,8))
    policy=POLICIES['B06_RB06_F50_N3']
    on=engine.run(*args,policy);off=engine.run(*args,policy,budget_enabled=False)
    assert np.any(on['orders'][:,6]==32) and not len(off['budget_events'])
    assert not np.any(off['orders'][:,6]==32) and off['cycles'][0,2]==off['shadow']['cycles'][0,2]
    same(on['shadow'],off['shadow'],engine.FIELDS+('plans','execution_plans'))
    invariants(args,on,0);invariants(args,off,0)
    for lag in (0.,1.,5.,15.):
        material=list(deepcopy(args));material[0]['time_s'][:-2]*=20
        material[0]['last'][11:13]=[109,110]
        result=engine.run(*material,policy,min_delay_seconds=lag)
        assert np.any((result['budget_events'][:,2]==3)&(result['budget_events'][:,0]==11))
        assert np.any((result['orders'][:,6]==32)&(result['orders'][:,0]==12))
        invariants(tuple(material),result,lag)
        rows.append(dict(検査='元部分利確優先・実R予約は保持・元注文の二重遅延なし',秒=lag,合格=True))
    rows.append(dict(検査='追加R退出だけのON/OFFと影不変',合格=True))
    # ----------------------------------------
    # 欠測価格中は約定せず、有効行でだけ成熟線を使う。
    args=fixture([100,101,102,float('nan'),100,103,109,95],(2,),())
    for lag in (0.,1.):
        result=engine.run(*args,PRIMARY,min_delay_seconds=lag)
        assert not np.any(result['orders'][:,0]==3)
        if lag==0:
            same(result,old.run(*args,PRIMARY))
    rows.append(dict(検査='価格欠測中の約定禁止と遅延0旧一致',合格=True))
    # ----------------------------------------
    # 正の遅延でも買売反射と未来改変が独立した選択根拠を先取りしない。
    args=fixture([100,101,102,102,102,104,105,107,109,104,103,101,100],(2,),(6,),spacing=20.)
    n=len(args[1]);sources=np.arange(n,dtype=np.int64)
    for lag in (0.,1.,5.,15.):
        for mode in ('fixed','adverse_signal','reverse','random'):
            kwargs=dict(min_delay_seconds=lag,good_valid=np.ones(n,np.bool_),branch_mode=mode,
                branch_direction=np.full(n,-1,np.int8),branch_source=sources.copy(),branch_valid=np.ones(n,np.bool_))
            if mode=='random':kwargs.update(branch_seed=3,branch_choice=np.arange(n,dtype=np.int8)%2)
            result=engine.run(*args,PRIMARY,**kwargs);invariants(args,result,lag)
            mirrored=list(deepcopy(args));mirrored[0]['last']=400-mirrored[0]['last']
            for k in (1,3,5):mirrored[k]=-mirrored[k]
            mirror_kwargs=deepcopy(kwargs);mirror_kwargs['branch_direction']*=-1
            other=engine.run(*mirrored,PRIMARY,**mirror_kwargs)
            expected=result['orders'].copy();expected[:,3]*=-1;expected[:,5]=400-expected[:,5]
            np.testing.assert_array_equal(other['orders'],expected)
            np.testing.assert_allclose(other['curve'][:,0],result['curve'][:,0],rtol=0,atol=1e-8)
            for cut in (4,8):
                short=[{k:v[:cut].copy() if isinstance(v,np.ndarray) and len(v)==n else v for k,v in args[0].items()}]
                short.extend(v[:cut].copy() if isinstance(v,np.ndarray) else deepcopy(v) for v in args[1:])
                short_kwargs={k:v[:cut].copy() if isinstance(v,np.ndarray) else v for k,v in kwargs.items()}
                prefix(result,engine.run(*short,PRIMARY,**short_kwargs),cut)
                future=list(deepcopy(args));future[0]['last'][cut:]+=20;future[0]['atr'][cut:]*=2
                for k in (1,3,5):future[k][cut:]*=-1
                changed=deepcopy(kwargs);changed['branch_direction'][cut:]*=-1
                changed['branch_valid'][cut:]=False
                if mode=='random':changed['branch_choice'][cut:]=1-changed['branch_choice'][cut:]
                prefix(result,engine.run(*future,PRIMARY,**changed),cut)
            rows.append(dict(検査='上下反射・prefix・未来価格ATR方向分岐変更',秒=lag,分岐=mode,合格=True))
    # ----------------------------------------
    # 必要な有効行が終場までに来なければ、場外へ架空返済しない。
    args=fixture([100,101,102,102],spacing=20.)
    args[0]['time_s'][-1]=args[0]['limit']+600.
    try:engine.run(*args,POLICIES['A0'],min_delay_seconds=15.)
    except ValueError as exc:assert '終場' in str(exc)
    else:raise AssertionError('終場以降の返済を拒否しませんでした')
    rows.append(dict(検査='場内返済行不足は例外・場外約定禁止',合格=True))
    # ----------------------------------------
    # 複写キャッシュでも公開行・成熟時刻を偽装できない。
    args=fixture([100,101,102,103,104,100,95],spacing=20.)
    source=engine.make_shadow(*args[:3],min_delay_seconds=5.)
    for cause in ('future','immature','delay','price'):
        corrupted=deepcopy(source);changed=deepcopy(args)
        if cause=='future':corrupted['execution_plans'][2,33]=2
        elif cause=='immature':
            changed[0]['time_s'][2]=changed[0]['time_s'][1]+1.
            corrupted=engine.make_shadow(*changed[:3],min_delay_seconds=5.)
            corrupted['execution_plans'][2]=corrupted['plans'][1]
        elif cause=='price':changed[0]['last'][2]+=1
        try:engine.run(*changed,PRIMARY,min_delay_seconds=1. if cause=='delay' else 5.,shadow=corrupted)
        except ValueError:pass
        else:raise AssertionError('不正計画/指紋を拒否しませんでした: '+cause)
    rows.append(dict(検査='未来・未成熟注文計画・別遅延・別価格キャッシュ4破損拒否',合格=True))
    # ----------------------------------------
    # 取消と新規も伝達を経る。期限は準備時点から延長しない。
    args=list(fixture([100,100,101,102,95]))
    args[0]['time_s'][:5]=[0,1,5,6,20]
    args[1][1:]=-1
    result=engine.run(*args,POLICIES['A0'],min_delay_seconds=5.)
    first=result['orders'][result['orders'][:,6]==20][0]
    assert first[0]==2 and first[1]==0 and first[3]==1
    invariants(tuple(args),result,5.)
    args=list(fixture([100,101,103]))
    args[0]['time_s'][:3]=[0,300,306]
    result=engine.run(*args,POLICIES['A0'],min_delay_seconds=5.)
    opened=result['orders'][result['orders'][:,6]==20]
    assert len(opened)==1 and opened[0,0]==2 and opened[0,1]==1
    assert result['entry_preparations'][0,2]==1
    invariants(tuple(args),result,5.)
    rows.append(dict(検査='取消未成熟中の旧新規約定・期限等号失効・寿命延長なし',合格=True))
    return rows


def old_identity() -> int:
    """機能: 既定A0の全26入力だけを旧版へ厳密照合する。

    引数: なし。返り値: 一致した入力数(int)。新分岐・R無効の実データは再生しない。
    """
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    states=np.load(HERE.parent/'wave_v27/directions/H019.npz',allow_pickle=False)
    count=0
    for key,ready in inputs.items():
        s=states['|'.join(key)];c=helpers.config(key[1],ready)
        z=np.zeros(len(s),np.int8);src=np.full(len(s),-1,np.int64)
        args=(ready,s,c,z,src,z,src)
        actual=engine.run(*args,POLICIES['A0']);reference=old.run(*args,POLICIES['A0'])
        same(actual,reference);same(actual['shadow'],reference['shadow'],engine.FIELDS+('prepare_events','entry_preparations','plans'))
        invariants(args,actual,0);count+=1
        print('IDENTITY',count,'/26',flush=True)
    return count


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--old-identity',action='store_true');opts=parser.parse_args()
    socket.socket.connect=reject;socket.create_connection=reject;urllib.request.urlopen=reject
    old_paths=[PRIOR/'engine_partial_restore.py',PRIOR/'engine_shadow_plan.py',HERE.parent/'wave_v23/inputs.pkl',
               HERE.parent/'wave_v27/directions/H019.npz']
    old_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_paths}
    results=synthetic()
    count=old_identity() if opts.old_identity else 0
    assert old_hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_paths}
    output=dict(全合格=True,人工件数=len(results),結果=results,
        ソースSHA256={str(HERE/name):hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                      for name in ('engine_shadow_plan.py','engine_partial_restore.py','engine_audit.py')},
        旧A0一致入力数=count,旧原本不変=True,旧原本SHA256=old_hashes,新実相場損益=False,API取得数=0)
    name='engine_audit.json' if opts.old_identity else 'engine_synthetic_audit.json'
    (HERE/name).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',len(results))
