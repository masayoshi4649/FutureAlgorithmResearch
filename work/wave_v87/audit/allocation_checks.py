"""少数開始・順行追加・親組損失床を、実数量と料金から独立に検証する。"""

import argparse
import hashlib
import math
import os
import pickle
import numpy as np
from diagnose import ROOT,HERE,save
from boundaries import module,old_boundary,compare
from support import clip,compare_prefix

helper=module('監査87追加用人工素材',HERE/'partial_checks.py')
ROUND=ROOT/'work/wave_v87/round4'


def load():
    """
    機能: 新数量戦略を読み、コンパイル先を監査領域へ固定する。
    引数: なし。
    返り値: tuple[module,dict]。
    """
    strategy=module('監査87数量戦略',ROUND/'strategy.py')
    catalog=module('監査87数量条件',ROUND/'catalog.py')
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache');os.environ['NUMBA_CACHE_DIR']=str(HERE/'cache')
    strategy.base.integration.reference.initialize()
    return strategy,{c['id']:c for c in catalog.catalog()}


def hashes():
    """
    機能: 監査中に売買・生成コードが変わらないことを確認する。
    引数: なし。
    返り値: dict[str,str]。
    """
    return {name:hashlib.sha256((ROUND/name).read_bytes()).hexdigest()
        for name in ('catalog.py','strategy.py','build_engine.py','engine.py')}


def floor_rules(result,ready,config):
    """
    機能: 全約定・各建値脚・注文別丸め料から床の価格を独立に復元する。
    引数: result/ready/config(dict)。
    返り値: intの床更新数。初回予算は最大実損の保証としない。
    """
    fee=41.8 if ready['symbol']=='TOPIX' else 11.;value=1000. if ready['symbol']=='TOPIX' else 10.
    orders=result['orders'];trades=result['trades'];opened=orders[orders[:,7]==1]
    count=0;last={}
    for e in result['allocation_events']:
        row,cid,kind,source,side,qty,level=map(float,e[:7]);row=int(row);cid=int(cid)
        if kind in (2,4):assert source<row
        if kind!=3:continue
        used=orders[(orders[:,2]==cid)&(orders[:,0]<=row)]
        assert np.any(used[:,6]==75)
        balance=-math.fsum(o[3]*o[4]*o[5] for o in used)
        inventory=math.fsum(o[3]*o[4] for o in used)
        paid=math.fsum(math.floor(o[4]*fee+1e-8) for o in used)
        remaining=[]
        for leg,o in enumerate(opened):
            if int(o[2])!=cid or o[0]>row:continue
            closed=trades[(trades[:,1]==leg)&(trades[:,7]<=row)]
            left=o[4]-np.sum(closed[:,3]);assert left>=0
            if left:remaining.append(left)
        expected=math.fsum(math.floor(q*fee+1e-8) for q in remaining)
        assert math.fsum(remaining)==abs(inventory)==qty
        assert abs(e[10]*value-paid)<1e-5 and abs(e[11]*value-expected)<1e-5
        target=-e[9]*value if config['floor_mode']==1 else 0.
        candidate=(target+paid+expected-balance*value)/(inventory*value)
        rounded=(math.ceil(candidate/ready['tick']-1e-9) if side>0 else math.floor(candidate/ready['tick']+1e-9))*ready['tick']
        expected_level=rounded if cid not in last else (max(last[cid],rounded) if side>0 else min(last[cid],rounded))
        assert abs(level-expected_level)<1e-7,(e,expected_level)
        net=(balance+inventory*level)*value-paid-expected
        assert net>=target-1e-5
        last[cid]=level;count+=1
    return count


def slot_rules(result,ready,config):
    """
    機能: 未開枠と閉枠を区別し、累計上限・返済重複・停止後追加を検査する。
    引数: result/ready/config(dict)。
    返り値: intの枠イベント数。
    """
    cap=10 if ready['symbol']=='TOPIX' else 20
    ever=set();alive=set();stopped={}
    for e in result['allocation_events']:
        if e[2]==6:stopped[int(e[1])]=min(stopped.get(int(e[1]),np.inf),e[0])
        if e[2]==2:
            assert e[3]<e[0] and e[7]<=cap
            assert int(e[1]) not in stopped or e[0]<stopped[int(e[1])]
    for e in result['slot_events']:
        cid,slot,kind,qty=int(e[2]),int(e[3]),int(e[4]),int(e[8]);key=cid,slot
        assert 1<=slot<=cap
        if kind in (1,6):
            assert key not in ever and key not in alive
            ever.add(key);alive.add(key)
        elif kind==3:
            raise AssertionError('今回の元GU条件には復元を入れない')
        elif qty:
            assert key in alive,(e,alive)
            alive.remove(key)
    return len(result['slot_events'])


def run(strategy,config,ready,features,observed):
    """
    機能: 人工素材を再生し、源行・枠・料金床を独立照合する。
    引数: strategy(module)、config/ready/features(dict)、observed(bool)。
    返り値: dict。
    """
    result,_=strategy.play(config,ready,features,observed=observed)
    old_boundary.check_source_order(result);floor_rules(result,ready,config);slot_rules(result,ready,config)
    return result


def synthetic(strategy,configs):
    """
    機能: 元GU一致、段差飛越、床の次行・飛越、共有半減枠を人工的に反証する。
    引数: strategy(module)、configs(dict)。
    返り値: None。人工利益を実相場の優位と呼ばない。
    """
    before=hashes();records=[]
    old_catalog=module('監査87数量旧条件',ROOT/'work/wave_v86/catalog.py')
    prior=next(c for c in old_catalog.catalog() if c['id']=='E01_G_U')
    for symbol in ('TOPIX','NK225'):
        unit=1 if symbol=='TOPIX' else 2;scale=1 if symbol=='TOPIX' else 20
        for reflected in (False,True):
            for observed in (False,True):
                r,f=helper.material([100,101,103,105,107,109,114,110],symbol=symbol,reflected=reflected)
                original,_=strategy.old.play(prior,r,f,observed=observed)
                out=run(strategy,configs['GU'],r,f,observed)
                compare(out,{k:v for k,v in original.items() if k in out})
                assert len(out['allocation_events'])==0
                records.append(dict(検査='追加なし元GU全配列一致',商品=symbol,ショート=reflected,観測=observed))
                # ----------------------------------------
                # 直線順行の2ATRで元部分が先に働き、次の追加を打ち切る。
                out=run(strategy,configs['D05_R'],r,f,observed)
                add=out['orders'][out['orders'][:,6]==75]
                assert add[:,0].astype(int).tolist()==[2,3,4]
                assert add[:,4].tolist()==[2*unit]*3
                oldsplit=out['orders'][out['orders'][:,6]==7]
                assert np.sum(oldsplit[:,4])==4*unit and np.all(oldsplit[:,0]==5)
                assert out['allocation_curve'][5,0]==8*unit and out['allocation_curve'][5,5]==1
                records.append(dict(検査='段階追加は一観測一段と2ATR停止',商品=symbol,ショート=reflected,観測=observed,最大累計枠=8*unit))
                # ----------------------------------------
                # 一観測で多段を越えても、二段目は過去の有利線へ遡って約定しない。
                r,f=helper.material([100,101,107,107,107,106],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['D05_R'],r,f,observed)
                add=out['orders'][out['orders'][:,6]==75]
                assert len(add)>=2 and add[0,0]==2 and add[1,0]==3
                assert add[1,5]==r['last'][3]
                assert np.max(np.unique(add[:,0],return_counts=True)[1])==1
                records.append(dict(検査='多段飛越の後続は次観測成行',商品=symbol,ショート=reflected,観測=observed))
                r,f=helper.material([100,101,107,107,107,106],symbol=symbol,reflected=reflected,offsets=[0,1,2,2,2,3])
                out=run(strategy,configs['D05_R'],r,f,observed)
                add=out['orders'][out['orders'][:,6]==75]
                assert add[:,0].astype(int).tolist()==[2,3,4]
                assert np.all(add[1:,5]==r['last'][3])
                records.append(dict(検査='同時計別原本行でも一観測一段で遡及しない',商品=symbol,ショート=reflected,観測=observed))
                # ----------------------------------------
                # 実追加後の床は次行から。価格飛越時の実損を予算で切り詰めない。
                r,f=helper.material([100,101,105,100],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['J1_R'],r,f,observed)
                assert out['orders'][out['orders'][:,6]==75,0].tolist()==[2]
                exits=out['orders'][out['orders'][:,6]==76]
                assert len(exits)>0 and np.all(exits[:,0]==3)
                used=out['orders'];fee=41.8 if symbol=='TOPIX' else 11.;value=1000. if symbol=='TOPIX' else 10.
                net=-sum(o[3]*o[4]*o[5] for o in used)*value-sum(math.floor(o[4]*fee+1e-8) for o in used)
                budget=2*unit*.75*4*scale*value
                assert net < -budget if observed else net>=-budget-1e-5
                records.append(dict(検査='床は実追加後の次行で飛越実損を保持',商品=symbol,ショート=reflected,観測=observed,親組収支=net,予算=budget))
                r,f=helper.material([100,101,105,np.nan,97],symbol=symbol,reflected=reflected)
                missing=run(strategy,configs['J1_R'],r,f,observed)
                r2,f2=helper.material([100,101,105,97],symbol=symbol,reflected=reflected)
                direct=run(strategy,configs['J1_R'],r2,f2,observed)
                a=missing['orders'][missing['orders'][:,7]==0];b=direct['orders'][direct['orders'][:,7]==0]
                assert np.all(a[:,6]==76) and np.all(a[:,0]==4)
                np.testing.assert_array_equal(a[:,4:7],b[:,4:7])
                records.append(dict(検査='欠測後も既読有効価格で床と元停止の先後を比較',商品=symbol,ショート=reflected,観測=observed))
                r,f=helper.material([100,101,105,100],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['J1_N'],r,f,observed)
                assert not np.any(np.isin(out['allocation_events'][:,2],[3,4]))
                records.append(dict(検査='新床なし対照は床を作らない',商品=symbol,ショート=reflected,観測=observed))
                # ----------------------------------------
                # B00で返した先頭枠を再建も二重返済もしない。
                r,f=helper.material([100,101,103,105,107,106,106,109,114,110],symbol=symbol,reflected=reflected,
                    source=[-1,-1,-1,-1,-1,5,5,5,5,5],bad=[0,0,0,0,0,-1,-1,-1,-1,-1])
                out=run(strategy,configs['D05_R'],r,f,observed)
                reduced=out['orders'][out['orders'][:,6]==30]
                assert np.sum(reduced[:,4])==4*unit and np.all(reduced[:,0]==6)
                assert not np.any(out['orders'][:,6]==7)
                assert np.max(out['orders'][out['orders'][:,6]==75,0])<6
                records.append(dict(検査='B00半減後の追加禁止と元分割共用',商品=symbol,ショート=reflected,観測=observed))
                r,f=helper.material([100,101,109,110,114,110],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['L05_R'],r,f,observed)
                assert not np.any(out['orders'][:,6]==75)
                assert np.sum(out['orders'][out['orders'][:,6]==7,4])==unit//2
                stopped=out['allocation_events'][out['allocation_events'][:,2]==6]
                assert len(stopped)==1 and stopped[0,0]==2 and stopped[0,12]==7
                records.append(dict(検査='2ATR優先は初回一枚で実部分ゼロでも追加停止',商品=symbol,ショート=reflected,観測=observed))
                # ----------------------------------------
                # 初期失敗は初回数量だけで終了し、静観窓は追加より全返済を優先。
                r,f=helper.material([100,101,97,97],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['D05_R'],r,f,observed)
                assert out['orders'][out['orders'][:,7]==1,4].tolist()==[2*unit]
                assert np.sum(out['orders'][out['orders'][:,7]==0,4])==2*unit
                records.append(dict(検査='未順行の初期失敗は少枚数だけ',商品=symbol,ショート=reflected,観測=observed))
                r,f=helper.material([100,101,105],symbol=symbol,reflected=reflected,offsets=[0,1,5],anchor='2026-10-02T22:14:55+09:00')
                out=run(strategy,configs['J1_R'],r,f,observed)
                assert not np.any(out['orders'][:,6]==75) and np.any(out['orders'][:,6]==71)
                records.append(dict(検査='米国静観返済が追加より優先',商品=symbol,ショート=reflected,観測=observed))
                print('数量人工',symbol,reflected,observed,len(records),flush=True)
    assert before==hashes()
    save('順行追加と初回損失予算床の人工境界.json',dict(全合格=True,検査数=len(records),検査=records,実装SHA256=before))


def prefix(strategy,configs):
    """
    機能: 代表日夜・両商品で追加と床の前後を未来切断して照合する。
    引数: strategy(module)、configs(dict)。
    返り値: None。新条件の全場評価を行わない。
    """
    before=hashes();sessions=('2026-09-25_Day','2026-09-28_Night')
    inputs=pickle.loads((ROOT/'work/wave_v67/prepared/old23/new_inputs.pkl').read_bytes())
    inputs={k:v for k,v in inputs.items() if k[0] in sessions}
    signals=pickle.loads((ROOT/'work/wave_v67/prepared/old23/signals.pkl').read_bytes())
    signals={name:{k:v for k,v in values.items() if k in inputs} for name,values in signals.items()}
    features=strategy.initialize(inputs,signals)
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache')
    records=[]
    for key,ready in sorted(inputs.items()):
        feature=features[key];n=len(ready['last'])
        for observed in (False,True):
            for ident in ('D05_R','J1_Z','L05_R'):
                full,_=strategy.play(configs[ident],ready,feature,observed=observed)
                old_boundary.check_source_order(full)
                floors=floor_rules(full,ready,configs[ident]);slots=slot_rules(full,ready,configs[ident])
                cuts={int(n*.37),int(n*.78)};events=full['allocation_events']
                for kind in (1,2,3,4,5,6):
                    for event in events[events[:,2]==kind][:2]:
                        row=int(event[0]);cuts.update((max(2,row),min(n-1,row+1)))
                checks=0
                for count in sorted(cuts):
                    part,_=strategy.play(configs[ident],clip(ready,count,n),clip(feature,count,n),observed=observed)
                    checks+=compare_prefix(full,part,count)
                    a,b=full['allocation_events'],part['allocation_events']
                    np.testing.assert_array_equal(a[a[:,0]<count],b[b[:,0]<count]);checks+=1
                    np.testing.assert_array_equal(full['allocation_curve'][:count],part['allocation_curve'][:count]);checks+=1
                records.append(dict(セッション=key[0],商品=key[1],条件=ident,観測約定=observed,
                    切断地点=len(cuts),配列照合数=checks,床独立復元数=floors,共有枠照合数=slots))
                print(key,ident,observed,len(cuts),checks,'追加prefix一致',flush=True)
    assert before==hashes()
    save('順行追加と初回損失予算床の未来切断.json',dict(全合格=True,条件口座数=len(records),
        切断地点=sum(r['切断地点'] for r in records),配列照合数=sum(r['配列照合数'] for r in records),
        床独立復元数=sum(r['床独立復元数'] for r in records),検査=records,実装SHA256=before))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',action='store_true');args=parser.parse_args()
    strategy,configs=load();prefix(strategy,configs) if args.prefix else synthetic(strategy,configs)
