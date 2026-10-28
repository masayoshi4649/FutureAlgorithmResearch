"""登録済みの十二残玉条件と四部分利確条件を、費用0・全50場で比較する。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE),str(ROOT/'work/research145_engine'),str(ROOT/'work/nikkei143_20261024')]
import residual145 as engine
import source145
import common143 as shared
import account145


def save(path,value):
    """JSONを一時ファイル経由で確定する。

    引数: path(Path)、value(dict又はlist)は保存先と内容。
    返り値: None。途中生成を完成済みとして読ませない。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def ref(path):
    """作業資料の相対パスとSHAを返す。

    引数: path(Path)は既存資料。
    返り値: dictは参照記録。
    """
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(path.relative_to(ROOT)).replace('\\','/'),sha256=sha,bytes=path.stat().st_size)


def verify(data,orders,maximum):
    """全約定の価格・先後・所有数量・費用を独立検査する。

    引数: data(dict)、orders(ndarray)、maximum(int)は時系列・約定・片方向上限。
    返り値: dictは会計前の機械検査結果。
    """
    normal=np.flatnonzero(np.asarray(data['quotes']['quote_valid'],bool)&(data['quotes']['ask']>data['quotes']['bid']))
    holdings={};sides={};peak=0;by_side={1:0,-1:0}
    for row in orders:
        fill,decision,parent,side,qty,price,reason,new,uid,fee=row
        assert fill>decision and qty>0 and qty==int(qty) and fee==0
        assert int(fill)==normal[np.searchsorted(normal,int(decision),side='right')]
        assert price==data['quotes']['ask' if side>0 else 'bid'][int(fill)]
        key=parent,uid
        if new:
            holdings[key]=holdings.get(key,0)+int(qty)
            sides[key]=int(side)
            by_side[int(side)]+=int(qty)
        else:
            assert sides[key]==-int(side)
            holdings[key]-=int(qty)
            by_side[-int(side)]-=int(qty)
        assert holdings[key]>=0 and min(by_side.values())>=0
        peak=max(peak,max(by_side.values()))
        assert peak<=maximum
    assert not any(holdings.values()),'全場再生に未返済がある'
    return dict(orders=len(orders),max_per_side=peak,all_closed=True,fees_zero=True,next_normal_bbo=True)


def run(registration,wait_seconds):
    """事前登録受領と完成入力を確認して全場を一度ずつ比較する。

    引数: registration(Path)は登録受領JSON、wait_seconds(float)は入力待機期限。
    返り値: None。既存成果は上書きしない。
    """
    receipt=json.loads(registration.read_text(encoding='utf-8-sig'))
    assert receipt.get('returncode')==0 or receipt.get('registered') is True or receipt.get('registration_committed') is True
    inventory=json.loads((ROOT/'work/research145_data/全保存資料の再照合145.json').read_text(encoding='utf-8'))
    assert inventory['all_checks_passed']
    configs=engine.configurations()
    frozen=json.loads((HERE/'残玉条件145.json').read_text(encoding='utf-8'))
    assert configs==frozen
    allrows,manifest,audits=[],[],[]
    for scene in inventory['known_sessions']:
        cache=ROOT/'work/research145_engine/cache'/f'{scene}.pkl'
        deadline=time.monotonic()+wait_seconds
        while not cache.exists():
            assert time.monotonic()<deadline,f'入力待機が期限に達した: {scene}'
            time.sleep(1.)
        target=HERE/'results'/f'{scene}.json'
        assert not target.exists(),'同じ金融再生の黙った再実行をしない'
        with cache.open('rb') as stream:packet,data,raw,baseline,label=pickle.load(stream)
        arrays,traces,accounts={}, {}, []
        for cfg in configs:
            method=cfg['id']
            cg,ct=engine.replay(data,raw['CG'],cfg)
            cs,st=(baseline['CS04'].copy(),np.empty((0,len(engine.TRACE_COLUMNS)))) if method.startswith('P') else engine.replay(data,raw['CS'],cfg)
            if method=='R00':
                np.testing.assert_array_equal(cg,baseline['CG04'])
                np.testing.assert_array_equal(cs,baseline['CS04'])
            orders=shared.merge(cg,baseline['A3'],cs)
            arrays[method],traces['CG_'+method],traces['CS_'+method]=orders,ct,st
            arrays['CG_'+method],arrays['CS_'+method]=cg,cs
            verification=verify(data,orders,10)
            verification.update(session=scene,method=method,reference_equal=method=='R00')
            audits.append(verification)
            row=account145.account(orders,packet,method,label)
            row['scope']=cfg['scope'];row['fees_policy']='手数料0、気配差は計上'
            row['source_prepared']=ref(cache)
            row['trace_counts']={str(int(k)):int(np.sum(ct[:,2]==k)+np.sum(st[:,2]==k)) for k in (1,2,3,4,5,6,7)}
            accounts.append(row)
        output=HERE/'orders'/f'{scene}.npz';output.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(output,**arrays)
        tracepath=HERE/'traces'/f'{scene}.npz';tracepath.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(tracepath,**traces)
        item=dict(session=scene,orders=ref(output),traces=ref(tracepath),cache=ref(cache))
        save(target,dict(session=scene,rows=accounts,cache=item))
        allrows.extend(accounts);manifest.append(item)
        print(scene+' 残玉12・部分利確後4条件 完了',flush=True)
    save(HERE/'残玉と部分利確後の全場結果145.json',dict(rows=allrows,cache=manifest,configs=configs,
        registration=ref(registration),implementation=[ref(Path(__file__)),ref(HERE/'residual145.py')],
        financial_accounts=len(allrows),API=0,real_orders=0,source_readonly=True))
    save(HERE/'全注文機械検査145.json',dict(all_passed=True,rows=audits))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--registration',required=True,type=Path)
    parser.add_argument('--wait-seconds',default=1800.,type=float)
    args=parser.parse_args();run(args.registration,args.wait_seconds)
