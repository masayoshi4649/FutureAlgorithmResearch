"""再参加制約を人工列で独立に反証し、旧P1の基準一致を確認する。"""

import importlib.util
import os
from pathlib import Path
import sys
import numpy as np
from diagnose import ROOT, HERE, save

sys.path.insert(0, str(ROOT/'work/wave_v86/audit'))
spec=importlib.util.spec_from_file_location('旧人工境界86',ROOT/'work/wave_v86/audit/boundaries.py')
old_boundary=importlib.util.module_from_spec(spec);spec.loader.exec_module(old_boundary)
fixture=old_boundary.fixture


def module(name,path):
    """
    機能: 新旧コードを読取り用の固有名で読み込む。
    引数: name (str)、path (Path)。
    返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    item=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(item);sys.modules[name]=result;item.loader.exec_module(result)
    return result


def load():
    """
    機能: 改修戦略と条件を読み、コンパイル先だけ今回監査領域へ変更する。
    引数: なし。
    返り値: tuple[module,dict]。
    """
    strategy=module('監査87戦略',ROOT/'work/wave_v87/round1/strategy.py')
    catalog=module('監査87条件',ROOT/'work/wave_v87/round1/catalog.py')
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache');os.environ['NUMBA_CACHE_DIR']=str(HERE/'cache')
    strategy.base.integration.reference.initialize()
    return strategy,{c['id']:c for c in catalog.catalog()}


def compare(a,b):
    """
    機能: 旧P1に存在する売買・制御・両影の全配列を比較する。
    引数: a/b (dict)。
    返り値: intの照合配列数。
    """
    count=0
    for name,v in b.items():
        if isinstance(v,np.ndarray):
            np.testing.assert_array_equal(a[name],v,err_msg=name);count+=1
        elif isinstance(v,dict):
            count+=compare(a[name],v)
    return count


def directions(feature,values,*,valid=None,source=None,peer=None):
    """
    機能: 同調と元行を人工的に指定し、入口Gも整合させる。
    引数: feature (dict)、values (list[int])、valid/source/peer (list|None)。
    返り値: None。
    """
    n=len(values);state=np.asarray(values,np.int8)
    feature['columns']=(state,*feature['columns'][1:])
    feature['gate']=state!=0
    feature['ema']=(state,np.arange(n) if source is None else np.asarray(source),
        np.arange(n) if peer is None else np.asarray(peer),np.ones(n,bool) if valid is None else np.asarray(valid,bool))


def run(strategy,config,ready,features,observed):
    """
    機能: 一人工列だけを再生し、前行注文順序を検査する。
    引数: strategy (module)、config/ready/features (dict)、observed (bool)。
    返り値: dict。
    """
    result,_=strategy.play(config,ready,features,observed=observed)
    old_boundary.check_source_order(result)
    return result


def main():
    """
    機能: 価格反射・約定2モデルで制約の境界を反証し合格証跡を保存する。
    引数: なし。
    返り値: None。実場の追加成績は計算しない。
    """
    strategy,configs=load();records=[]
    pc=module('監査87旧条件',ROOT/'work/wave_v86/phase2/catalog.py')
    old=next(c for c in pc.catalog() if c['id']=='T2_P1')
    for reflected in (False,True):
        sign=-1 if reflected else 1
        for observed in (False,True):
            prices=[100,101,106,104,100,100,101,105,106.5,108,105]
            times=[0,1,2,3,63,64,65,66,67,68,69]
            ready,f=fixture(prices,times,reflected=reflected)
            result=run(strategy,configs['R0_S75'],ready,f,observed)
            prior,_=strategy.prior.play(old,ready,f,observed=observed)
            arrays=compare(result,prior)
            records.append(dict(検査='生成器経由R0は旧P1全配列一致',ショート=reflected,観測=observed,照合配列数=arrays))
            # ----------------------------------------
            # 支持の持続、無効非支持、古い公開元では再同調権を与えない。
            for kind in ('持続','無効非支持','自己古い','相手古い','有効再成立'):
                ready,f=fixture(prices,times,reflected=reflected)
                state=[sign]*len(prices);valid=[True]*len(prices);src=list(range(len(prices)));peer=src.copy()
                if kind!='持続':state[4]=0
                if kind=='無効非支持':valid[4]=False
                if kind=='自己古い':src[4]=3
                if kind=='相手古い':peer[4]=3
                directions(f,state,valid=valid,source=src,peer=peer)
                out=run(strategy,configs['R1_S75'],ready,f,observed)
                entries=out['orders'][out['orders'][:,7]==1,0].astype(int).tolist()
                assert entries==([1,6] if kind=='有効再成立' else [1]),(kind,entries,out['restart_events'])
                records.append(dict(検査='別周期_'+kind,ショート=reflected,観測=observed,新規行=entries))
            # ----------------------------------------
            # 前高安の外側一呼値が、途中で価格が戻っても緩まない。
            for gate in (2,3):
                ready,f=fixture(prices,times,reflected=reflected)
                state=[sign]*len(prices)
                if gate==3:state[4]=0
                directions(f,state)
                out=run(strategy,configs[f'R{gate}_S75'],ready,f,observed)
                entries=out['orders'][out['orders'][:,7]==1,0].astype(int).tolist()
                assert entries==[1,8],(gate,entries)
                for name in ('normal_shadow','shadow'):
                    plans=out[name]['plans']
                    pending=(plans[:,21]==sign)&(np.arange(len(plans))>3)&(np.arange(len(plans))<8)
                    assert np.all(sign*(plans[pending,22]-(106.5 if sign>0 else 93.5))>=-1e-8)
                records.append(dict(検査=f'R{gate}_前高安一呼値と追跡下限維持',ショート=reflected,観測=observed,新規行=entries))
            # ----------------------------------------
            # 期限切れでも待機境界は解放しない。
            ready,f=fixture([100,101,106,104,100,100,101,105,106.5],
                [0,1,2,3,63,364,365,366,367],reflected=reflected)
            out=run(strategy,configs['R2_S75'],ready,f,observed)
            entries=out['orders'][out['orders'][:,7]==1,0].astype(int).tolist()
            assert entries==[1,8],entries
            records.append(dict(検査='TTL後も前極値制約を維持',ショート=reflected,観測=observed,新規行=entries))
            # ----------------------------------------
            # 米国窓は新準備を止めるが、前極値を忘れる理由にはしない。
            ready,f=fixture([100,101,106,104,100,100,101,105,106.5],
                [0,1,2,3,63,1861,1862,1863,1864],reflected=reflected,anchor='2026-10-02T22:14:00+09:00')
            out=run(strategy,configs['R2_S75'],ready,f,observed)
            entries=out['orders'][out['orders'][:,7]==1,0].astype(int).tolist()
            assert entries==[1,8],entries
            assert all(p[1]!=4 for p in out['prepare_events'])
            records.append(dict(検査='米国静観窓を跨いでも前極値制約を維持',ショート=reflected,観測=observed,新規行=entries))
            # ----------------------------------------
            # 片方の出口だけを狭くし、途中半減の根拠となる通常影を維持する。
            ready,f=fixture([100,101,100.5,100,99.5,99,98,97,100,101],
                [0,1,2,3,4,5,6,7,400,401],reflected=reflected)
            outputs={s:run(strategy,configs[f'R0_S{s}'],ready,f,observed) for s in ('75','50','25')}
            for s in ('50','25'):
                np.testing.assert_array_equal(outputs['75']['normal_shadow']['plans'],outputs[s]['normal_shadow']['plans'])
            assert [outputs[s]['trades'][0,7] for s in ('75','50','25')]==[6,5,3]
            records.append(dict(検査='初期止め三幅の順序と通常影不変',ショート=reflected,観測=observed))
            print('人工監査',reflected,observed,len(records),flush=True)
    save('再参加条件と初期止めの人工境界.json',dict(全合格=True,検査=records,
        注記='人工列のみ。手法の有効性や利益はこの検査から推定しない。'))
    print('合格',len(records),flush=True)


if __name__=='__main__':
    main()
