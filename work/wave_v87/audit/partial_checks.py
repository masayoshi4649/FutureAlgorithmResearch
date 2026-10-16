"""原GUの一部追尾・共用枠・親組ゼロ円床を独立に反証する。"""

import argparse
import hashlib
import math
import os
import pickle
import sys
import numpy as np
from boundaries import module,fixture,old_boundary,compare
from diagnose import ROOT,HERE,save
from support import clip,compare_prefix


def load():
    """
    機能: 第2改修を読み、監査キャッシュを新領域へ向ける。
    引数: なし。
    返り値: tuple[module,dict]。
    """
    strategy=module('監査87部分戦略',ROOT/'work/wave_v87/round2/strategy.py')
    catalog=module('監査87部分条件',ROOT/'work/wave_v87/round2/catalog.py')
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache');os.environ['NUMBA_CACHE_DIR']=str(HERE/'cache')
    strategy.base.integration.reference.initialize()
    return strategy,{c['id']:c for c in catalog.catalog()}


def material(prices,*,symbol='TOPIX',reflected=False,offsets=None,**kwargs):
    """
    機能: 両商品それぞれの呼値と初期枚数に整合した人工入力を作る。
    引数: prices (list)、symbol (str)、reflected (bool)、offsets (list|None)、kwargs (dict)。
    返り値: tuple[dict,dict]。
    """
    ready,feature=fixture(prices,list(range(len(prices))) if offsets is None else offsets,reflected=reflected,**kwargs)
    ready['symbol']=symbol
    if symbol=='NK225':
        ready['last']*=20.;ready['atr']*=20.;ready['tick']=10.
    return ready,feature


def run(strategy,config,ready,feature,observed):
    """
    機能: 一人工入力を再生し、全注文の旧観測根拠を検査する。
    引数: strategy (module)、config/ready/feature (dict)、observed (bool)。
    返り値: dict。
    """
    result,_=strategy.play(config,ready,feature,observed=observed)
    old_boundary.check_source_order(result)
    return result


def floor_rules(result,ready):
    """
    機能: 親組ゼロ円床を注文現金・残数量・料金から独立に復元する。
    引数: result/ready (dict)。
    返り値: intの床更新数。
    """
    fee=41.8 if ready['symbol']=='TOPIX' else 11.;value=1000. if ready['symbol']=='TOPIX' else 10.
    count=0
    for e in result['partial_events']:
        row,cid,kind,source,side,qty,level=map(float,e[:7]);row=int(row);cid=int(cid)
        if kind in (2,4):assert source<row
        if kind!=3:continue
        orders=result['orders'][(result['orders'][:,2]==cid)&(result['orders'][:,0]<=row)]
        assert np.any(orders[:,6]==73),'原部分利確だけで新床を発動してはいけない'
        balance=-math.fsum(o[3]*o[4]*o[5] for o in orders)
        inventory=math.fsum(o[3]*o[4] for o in orders)
        paid=math.fsum(math.floor(o[4]*fee+1e-8) for o in orders)
        exit_fee=math.floor(abs(inventory)*fee+1e-8)
        assert inventory!=0 and abs(inventory)==qty
        net=(balance+inventory*level)*value-paid-exit_fee
        # 価格を一呼値だけ損失側へ戻すとゼロ円を割るのが新しい最小床。
        candidate=(paid+exit_fee-balance*value)/(inventory*value)
        rounded=(math.ceil(candidate/ready['tick']-1e-9) if side>0 else math.floor(candidate/ready['tick']+1e-9))*ready['tick']
        assert side*(level-rounded)>=-1e-8 and net>=-1e-5,(e,net,rounded)
        count+=1
    return count


def synthetic(strategy,configs):
    """
    機能: 枠割合、既存部分との重複、床料金、次行有効、全返済優先を検査する。
    引数: strategy (module)、configs (dict)。
    返り値: list[dict]。
    """
    original_catalog=module('監査87部分旧カタログ',ROOT/'work/wave_v86/catalog.py')
    old=next(c for c in original_catalog.catalog() if c['id']=='E01_G_U')
    records=[]
    for symbol in ('TOPIX','NK225'):
        q0=5 if symbol=='TOPIX' else 10
        for reflected in (False,True):
            for observed in (False,True):
                # ----------------------------------------
                # 狭い返済枠と原2ATR分割の先頭枠を共用し、総数量を超えて返済しない。
                ready,f=material([100,101,105,103,109,114,110],symbol=symbol,reflected=reflected)
                original,_=strategy.old.play(old,ready,f,observed=observed)
                for protect in (0,1):
                    out=run(strategy,configs[f'Q00_B{protect}'],ready,f,observed)
                    # 元と同じ実配列を比較し、新機能の空配列は対象外。
                    fields={k:v for k,v in original.items() if k in out}
                    compare(out,fields)
                    assert len(out['partial_events'])==0
                    records.append(dict(検査='0%は床有無とも原GU一致',商品=symbol,ショート=reflected,観測=observed,床=protect))
                for percent in (20,40,60):
                    out=run(strategy,configs[f'Q{percent}_B0'],ready,f,observed)
                    orders=out['orders'];narrow=orders[orders[:,6]==73];oldsplit=orders[orders[:,6]==7]
                    count=int(math.floor(q0*percent/100))
                    assert len(narrow)==1 and narrow[0,4]==count and narrow[0,0]==3
                    assert sum(oldsplit[:,4])==max(0,q0//2-count)
                    assert sum(orders[orders[:,7]==0,4])<=q0
                    assert not np.any(orders[orders[:,7]==0,0]==2),'新しい追尾線を当行へ逆用しない'
                    records.append(dict(検査='先行枠と原分割の重複返済なし',商品=symbol,ショート=reflected,観測=observed,割合=percent))
                # ----------------------------------------
                # 狭い実部分を約定した後にだけ親組床を作り、同じ行に全返済しない。
                ready,f=material([100,101,105,103,100,99],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['Q40_B1'],ready,f,observed)
                floor_rules(out,ready)
                assert out['orders'][out['orders'][:,6]==73,0].tolist()==[3]
                assert out['orders'][out['orders'][:,6]==74,0].tolist()==[4]
                assert not np.any((out['orders'][:,0]==3)&(out['orders'][:,6]==74))
                records.append(dict(検査='料金込み親組床は実部分返済後の次行有効',商品=symbol,ショート=reflected,観測=observed))
                # 原2ATR先行返済だけでは新保護を起動しない。
                ready,f=material([100,101,109,106,100],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['Q40_B1'],ready,f,observed)
                assert not np.any(np.isin(out['orders'][:,6],[73,74]))
                assert not np.any(out['partial_events'][:,2]==3)
                records.append(dict(検査='元2ATR部分返済だけでは床なし',商品=symbol,ショート=reflected,観測=observed))
                # B00で先頭枠が既に返済された場合、空枠を利確して床を作らない。
                ready,f=material([100,101,107,106,106,104],symbol=symbol,reflected=reflected,
                    source=[-1,-1,-1,3,3,3],bad=[0,0,0,-1,-1,-1])
                out=run(strategy,configs['Q40_B1'],ready,f,observed)
                assert np.any(out['orders'][:,6]==30)
                assert not np.any(np.isin(out['orders'][:,6],[73,74]))
                assert not np.any(out['partial_events'][:,2]==3)
                records.append(dict(検査='B00で空になった先頭枠を二重返済せず床なし',商品=symbol,ショート=reflected,観測=observed))
                out=run(strategy,configs['Q60_B1'],ready,f,observed)
                narrow=out['orders'][out['orders'][:,6]==73]
                assert len(narrow)==1 and narrow[0,4]==1
                floor_rules(out,ready)
                records.append(dict(検査='B00減量後に先行枠が一枚だけ残ればその一枚だけ返済',商品=symbol,ショート=reflected,観測=observed))
                # 床を通り越した現在値約定ではゼロ円を保証しない。
                ready,f=material([100,101,105,103,99.5],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['Q40_B1'],ready,f,observed)
                assert out['orders'][out['orders'][:,6]==74,0].tolist()==[4]
                floor_rules(out,ready)
                records.append(dict(検査='親組床飛越でも原本現在値又は指定線という約定モデルを維持',商品=symbol,ショート=reflected,観測=observed))
                # 大きな飛越で元全返済と狭返済が同時成立すれば元だけ約定。
                ready,f=material([100,101,105,97],symbol=symbol,reflected=reflected)
                out=run(strategy,configs['Q40_B1'],ready,f,observed)
                assert out['orders'][out['orders'][:,7]==0,6].tolist()==[1]
                records.append(dict(検査='初期全損切りを狭部分返済より優先',商品=symbol,ショート=reflected,観測=observed))
                # 米国静観も狭い返済より全返済を優先。
                ready,f=material([100,101,105,103],symbol=symbol,reflected=reflected,
                    offsets=[0,1,2,5],anchor='2026-10-02T22:14:55+09:00')
                out=run(strategy,configs['Q40_B1'],ready,f,observed)
                assert out['orders'][out['orders'][:,7]==0,6].tolist()==[71]
                records.append(dict(検査='米国静観の全返済優先',商品=symbol,ショート=reflected,観測=observed))
                print('部分人工',symbol,reflected,observed,len(records),flush=True)
    return records


def prefix(strategy,configs):
    """
    機能: 日夜両商品・両モデルで部分売買と親組床の未来切断を照合する。
    引数: strategy (module)、configs (dict)。
    返り値: list[dict]。
    """
    sessions=('2026-09-25_Day','2026-09-28_Night')
    inputs=pickle.loads((ROOT/'work/wave_v67/prepared/old23/new_inputs.pkl').read_bytes())
    inputs={k:v for k,v in inputs.items() if k[0] in sessions}
    signals=pickle.loads((ROOT/'work/wave_v67/prepared/old23/signals.pkl').read_bytes())
    signals={code:{k:v for k,v in values.items() if k in inputs} for code,values in signals.items()}
    features=strategy.initialize(inputs,signals);records=[]
    for key in sorted(inputs):
        ready=inputs[key];f=features[key];n=len(ready['last'])
        for observed in (False,True):
            for ident in ('Q40_B0','Q60_B1'):
                full=run(strategy,configs[ident],ready,f,observed);floor_count=floor_rules(full,ready)
                cuts={int(n*.37),int(n*.77)}
                for kind in (1,2,3,4):
                    ev=full['partial_events'];selected=ev[ev[:,2]==kind]
                    for event in selected[:2]:
                        i=int(event[0]);cuts.update((max(2,i),min(n-1,i+1),min(n-1,i+2)))
                checks=0
                for count in sorted(cuts):
                    part=run(strategy,configs[ident],clip(ready,count,n),clip(f,count,n),observed)
                    checks+=compare_prefix(full,part,count)
                    a,b=full['partial_events'],part['partial_events']
                    np.testing.assert_array_equal(a[a[:,0]<count],b[b[:,0]<count]);checks+=1
                    np.testing.assert_array_equal(full['partial_curve'][:count],part['partial_curve'][:count]);checks+=1
                records.append(dict(セッション=key[0],商品=key[1],条件=ident,観測=observed,切断数=len(cuts),
                    配列一致数=checks,料金込み床更新照合数=floor_count))
                print('部分切断',key,ident,observed,len(cuts),'一致',flush=True)
    return records


def main():
    """
    機能: 独立人工検査又は原板未来切断を実行し証跡を保存する。
    引数: --prefix (bool) は未来切断を指定する。
    返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',action='store_true');args=parser.parse_args()
    strategy,configs=load()
    paths=[ROOT/'work/wave_v87/round2'/n for n in ('catalog.py','strategy.py','build_engine.py','engine.py')]
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    records=prefix(strategy,configs) if args.prefix else synthetic(strategy,configs)
    assert before=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    save('一部追尾と親組床の未来切断.json' if args.prefix else '一部追尾と親組床の人工境界.json',
        dict(全合格=True,検査=records,実装SHA256=before))
    print('全合格',len(records),flush=True)


if __name__=='__main__':
    main()
