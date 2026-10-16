"""実入力なしで方向採点の分母・打切・同候補対照と全場再加算を検査する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

import numpy as np

import aggregate
import input_contract


HERE=Path(__file__).resolve().parent


def fixture() -> dict:
    """
    機能: 同じpub行系列に六状態・反対方向・重複と負MFEを持つ採点配列を作る。
    引数: なし。
    返り値: dict はengine.measureの純合成返却形。
    """
    fields=list(input_contract.FIELDS)
    e=np.zeros((6,31),np.float64)
    pub=np.array([0,1,2,3,8,9],np.int64)
    directions=np.array([1,-1,-1,1,1,-1],np.int8)
    for name,values in (('pub_i',pub),('d',directions),('type',[0,1,0,1,0,1]),
                        ('opposite_q0',[10]*6),('opposite_min_q',[10]*6),
                        ('bid_q_at_public',[10,10,10,20,20,20]),
                        ('ask_q_at_public',[10,20,10,10,10,10])):
        e[:,fields.index(name)]=values
    available=np.array([True,True,False,True,True,True])
    entry=pub+1;entry[~available]=-1
    prices=np.full(6,100.,np.float64);prices[~available]=np.nan
    ends=np.array([[7,7],[8,8],[7,-1],[8,8],[14,14],[15,15]],np.int64)
    labels=np.full((6,3,2),2,np.int8)
    terminal=np.repeat((ends-1)[:,None,:],3,axis=1)
    labels[~available,:,1]=-2;terminal[~available,:,1]=-1
    labels[[0,2],:,0]=0;terminal[[0,2],:,0]=7
    labels[0,:,1]=0;terminal[0,:,1]=7
    labels[[1,3],:,:]=3;terminal[[1,3],:,:]=8
    labels[0,0,:]=1;terminal[0,0,:]=1
    labels[0,1,:]=-1;terminal[0,1,:]=3
    labels[1,0,:]=1;terminal[1,0,:]=2
    labels[1,1,:]=-1;terminal[1,1,:]=4
    labels[4,0,0]=1;terminal[4,0,0]=10
    labels[4,:,1]=-1;terminal[4,:,1]=9
    labels[5,:,0]=1;terminal[5,:,0]=11
    mfe=np.array([[3.,2.],[3.,2.],[1.,np.nan],[2.,1.],[2.,-1.],[4.,3.]],np.float64)
    mae=np.array([[-2.,-3.],[-2.,-3.],[-1.,np.nan],[-1.,-2.],[0.,-2.],[-1.,-2.]],np.float64)
    eligible=np.array([[1,0,0],[0,1,1],[1,0,0],[0,1,1],[1,0,0],[0,1,0]],bool)
    chosen=np.array([[1,0,0],[0,1,1],[0,0,0],[0,0,0],[1,0,0],[0,1,0]],bool)
    return dict(events=e,fields=fields,widths=list(aggregate.WIDTHS),origin_names=list(aggregate.ORIGIN_CODES),
        rule_names=list(aggregate.RULES),labels=labels,terminal_rows=terminal,eligible=eligible,nonoverlap=chosen,
        entry_available=available,entry_rows=entry,entry_prices=prices,mfe=mfe,mae=mae,continuous_end_exclusive=ends)


def empty_fixture() -> dict:
    """
    機能: 候補が一件もない正常な採点形を作る。
    引数: なし。
    返り値: dict。ゼロ候補を勝率0又は100%へ置き換えない。
    """
    result=fixture()
    for key,value in result.items():
        if isinstance(value,np.ndarray):result[key]=value[:0].copy()
    return result


def reject(function: object) -> None:
    """
    機能: 不正な形・符号・未知の混入がAssertionErrorで拒否されることを確認する。
    引数: function(Callable)。
    返り値: None。
    """
    try:function()
    except AssertionError:return
    raise AssertionError('不正な集計入力を受理した')


def integration() -> dict:
    """
    機能: 完成engineの所有合成素材をそのまま測り、集計接口と空・欠測・終端を照合する。
    引数: なし。
    返り値: dict はSource指紋と素材別件数。実入力は使わない。
    """
    import artificial
    import engine
    expected={'engine.py':'c62d3c93c745038843c5d10d8b4f8520340955e48db0fba116777d88fcd9fd1e',
        'artificial.py':'f4cb411ed8591ef248cb67e2917e6f56c6e9f1161ac28801202f42cd39fa22d3'}
    assert all(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==value for name,value in expected.items())
    cases=[]
    for symbol in ('TOPIX','NK225'):
        for reflected in (False,True):
            data=artificial.fixture(symbol,reflected)
            result=engine.measure(*data)
            row=aggregate.account(symbol,'2026-09-21_Day',result)
            assert row['全保存候補数']==len(result['events'])
            cases.append(dict(symbol=symbol,素材='所有基準鏡映'+str(reflected),候補数=row['全保存候補数']))
        for mode in ('空','末尾公開','数量不明','価格逆行cut','窓末','EOF短接頭'):
            data=artificial.fixture(symbol)
            arrays,signal,_,start,end,tick,policy=data
            if mode=='空':data=artificial.rebuild(data,[],[])
            elif mode=='末尾公開':data=artificial.rebuild(data,[len(arrays['raw_seq'])-1],[1])
            elif mode=='数量不明':
                arrays['best_quantity_valid'][2]=False;arrays['bid_qty'][2]=0
                data=artificial.rebuild(data,[1],[1])
            elif mode=='価格逆行cut':
                arrays['price_time_s'][5]=3
                data=artificial.rebuild(data,[1],[1])
            elif mode=='窓末':
                arrays['price_time_s'][5:]=end+np.arange(len(arrays['raw_seq'])-5)
                data=artificial.rebuild(data,[1],[1])
            elif mode=='EOF短接頭':
                data=(dict((key,value[:3].copy()) for key,value in arrays.items()),signal,symbol,start,end,tick,policy)
                data=artificial.rebuild(data,[1],[1])
            result=engine.measure(*data)
            row=aggregate.account(symbol,'2026-09-21_Day',result)
            assert all(cell['n']==sum(cell[name] for name in aggregate.COUNT_FIELDS) for cell in row['cells'])
            if mode=='空':assert row['全保存候補数']==0
            if mode in ('末尾公開','数量不明'):
                assert row['直後新規可能数']==0
                assert np.all(result['labels'][:,:,1]==-2)
            cases.append(dict(symbol=symbol,素材=mode,候補数=row['全保存候補数'],仮新規気配参照数=row['直後新規可能数']))
    assert all(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==value for name,value in expected.items())
    return dict(全合格=True,完成engine素材=len(cases),cases=cases,source_SHA256=expected,
        範囲='所有合成の末尾・空・cut・数量不明を完成engine→accountへ接続。原入力と保存eventは0。')


def main() -> None:
    """
    機能: 六状態と固定方向対照・共通非重複・33場の分母を純合成だけで検査する。
    引数: なし。
    返り値: None。原NPZ・event・金融結果・APIを読まない。
    """
    artifact=HERE/'方向採点の分母と非重複及び固定方向対照の純人工_v2.json'
    assert not artifact.exists()
    measured=fixture()
    account=aggregate.account('TOPIX','2026-09-21_Day',measured)
    assert len(account['cells'])==108 and len(account['profiles'])==36
    main=account['primary']
    assert main['n']==1 and main['adverse_first']==1 and main['resolved']==1
    assert main['favorable_rate_all']==main['favorable_rate_resolved']==0 and main['resolution_rate']==1
    assert main['baseline']['常時買い']['favorable_first']==1
    assert main['baseline']['常時売り']['adverse_first']==1
    cells=account['cells']
    c_all=next(c for c in cells if c['rule']=='C' and c['group']=='全候補' and c['width_fraction']==.001 and c['origin']=='公開mid' and c['direction']=='全体')
    assert c_all['n']==2 and c_all['adverse_first']==1 and c_all['window_end']==1
    assert c_all['favorable_rate_all']==0 and c_all['resolution_rate']==.5
    available=next(c for c in cells if c['rule']=='A' and c['group']=='全候補' and c['width_fraction']==.001 and c['origin']==aggregate.ORIGINS[1] and c['direction']=='全体')
    assert available['n']==3 and available['entry_unavailable']==1 and available['baseline'] is None
    states=aggregate._labels(np.array([1,-1,0,2,3,-2],np.int8))
    assert states['n']==6 and states['resolved']==2 and all(states[name]==1 for name in aggregate.COUNT_FIELDS)
    assert states['favorable_rate_all']==1/6 and states['favorable_rate_resolved']==.5 and states['resolution_rate']==1/3
    assert aggregate._stats([-5.,-3.])['median']==-4
    pooled=aggregate._pooled_stats([aggregate._stats([0.,100.]),aggregate._stats([3.])])
    assert pooled['n']==3 and pooled['mean']==103/3 and pooled['median'] is None
    assert pooled['場中央値の分布']['median']==26.5
    blank=aggregate.account('NK225','2026-09-21_Day',empty_fixture())
    assert all(c['n']==0 and c['favorable_rate_all'] is None and c['favorable_rate_resolved'] is None and c['resolution_rate'] is None for c in blank['cells'])
    assert all(p['mfe']['median'] is None and p['mae']['median'] is None for p in blank['profiles'])
    for bad in (True,False,None,float('nan'),float('inf')):
        reject(lambda bad=bad:aggregate._scalar(bad))
    for case in ('dtype','unavailable','nonoverlap','terminal','mfe','sort','width'):
        broken=deepcopy(measured)
        if case=='dtype':broken['labels']=broken['labels'].astype(np.int64)
        elif case=='unavailable':broken['labels'][2,0,1]=0
        elif case=='nonoverlap':broken['nonoverlap'][2,0]=True
        elif case=='terminal':broken['terminal_rows'][0,2,0]=6
        elif case=='mfe':broken['mfe'][4,1]=0
        elif case=='sort':broken['events'][2,broken['fields'].index('pub_i')]=0
        elif case=='width':broken['widths'][1]=.0009
        if case=='mfe':
            # 0への丸め自体を入力から見抜けないので、signed値保持の別期待を比較する。
            assert aggregate.account('TOPIX','2026-09-21_Day',broken)['profiles']!=account['profiles']
        else:
            reject(lambda broken=broken:aggregate.account('TOPIX','2026-09-21_Day',broken))
    sessions=[(date(2026,9,21)+timedelta(days=i//2)).isoformat()+('_Day' if i%2==0 else '_Night') for i in range(33)]
    accounts=[]
    for symbol in ('TOPIX','NK225'):
        for session in sessions:
            copy=deepcopy(account);copy['symbol']=symbol;copy['session']=session
            accounts.append(copy)
    combined=aggregate.combine(accounts,sessions)
    assert combined['全合格'] is True
    for symbol in ('TOPIX','NK225'):
        periods=combined['symbols'][symbol]['periods']
        assert periods['全33']['session_count']==33 and periods['全33']['primary']['n']==33
        assert periods['前16']['primary']['n']==16 and periods['後17']['primary']['n']==17
        assert periods['デイ']['primary']['n']==17 and periods['ナイト']['primary']['n']==16
        assert periods['全33']['primary']['baseline']['常時買い']['favorable_first']==33
    reject(lambda:aggregate.combine(accounts[:-1],sessions))
    reject(lambda:aggregate.combine(accounts,sessions[:-1]+[sessions[0]]))
    text=json.dumps(combined,ensure_ascii=False,allow_nan=False)
    assert 'NaN' not in text and 'Infinity' not in text
    connected=integration()
    proof=dict(全合格=True,口座セル=108,口座極値profile=36,合成口座=66,合成期間=10,完成engine接口=connected,
        未知と打切='六状態を別分母。0件率はNone。常時買売は同じ候補の派生。',
        極値='負MFE/負MAE保持。全観測median未算定、場中央値分布だけ別記。',
        source_SHA256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('aggregate.py','artificial_aggregate.py')},
        原NPZ=0,eventNPZ=0,金融結果=0,新金融=0,API=0)
    artifact.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=hashlib.sha256(artifact.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
