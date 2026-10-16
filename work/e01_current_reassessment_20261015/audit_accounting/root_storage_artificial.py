"""根の保存・snapshot・登録guardを純関数抽出と独立小素材で確認する。"""

import ast
from copy import deepcopy
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace
import traceback

import numpy as np

sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
SOURCE=BASE/'root_review/finance.py'


def sha(path: Path) -> str:
    """
    機能: source又は自所有toy保存のSHA256を計算する。
    引数: path(Path)は実cacheでない小ファイル。
    返り値: strはbytes指紋。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(raw: bytes) -> dict:
    """
    機能: driverのimport/runを実行せず、保存とguardの六関数だけをASTから抽出する。
    引数: raw(bytes)はfinance.py源。
    返り値: dictは抽出関数namespace。金融/cache/input読取関数は含めない。
    """
    names={'finite','write','packed','snapshots','save_ledger','guard'}
    tree=ast.parse(raw.decode('utf-8'));nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes}==names
    target=dict(np=np,math=math,Path=Path,json=json,gzip=gzip,io=io,pickle=pickle,hashlib=hashlib,HERE=HERE,ROOT=ROOT,OUT=HERE/'保存人工')
    code=compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'::純抽出','exec')
    exec(code,target)
    return target


def guard_artificial(t: dict) -> int:
    """
    機能: 実登録/manifestを読まず、八部品・源・登録の不一致を小辞書で拒否させる。
    引数: t(dict)は抽出namespace。root_plan/catを純toyへ束縛する。
    返り値: intは拒否境界数。登録や金融を開始しない。
    """
    configs=[dict(id='合成九条件')];source={'合成.py':'abc'};case={'合成九条件':'def'};reg=HERE/'未読の合成登録.json'
    t['REGISTRY']=reg;t['catalog']=SimpleNamespace(TRIAL_ID='合成',configs=lambda:deepcopy(configs))
    state={'trials':[]}
    def read(path: Path) -> dict:
        """
        機能: 実ファイルを開かず合成登録だけを返す。
        引数: path(Path)は期待するtoy登録名。
        返り値: dictはメモリだけの登録。
        """
        assert path==reg
        return deepcopy(state)
    def source_hash(path: Path) -> str:
        """
        機能: 合成計画/manifestの固定値を返し、大型本文を開かない。
        引数: path(Path)は二つの合成識別先。
        返り値: strはfixture内の固定指紋。
        """
        values={HERE/'試行計画.json':'plan',ROOT/'合成目録.json':'manifest'}
        return values[path]
    t['root_plan']=SimpleNamespace(case_hashes=lambda c:deepcopy(case),sources=lambda:deepcopy(source),sha=source_hash,read=read)
    proposal=dict(id='合成',正式freeze=True,spec=dict(entry=dict(conditions=deepcopy(configs)),implementation=deepcopy(source),data=dict(input_manifests=[dict(path='合成目録.json',sha256='manifest')])))
    fixed=dict(全合格=True,正式freeze=True,configs=deepcopy(configs),case_SHA256=deepcopy(case),source_SHA256=deepcopy(source),計画SHA256='plan')
    state['trials']=[dict(id='合成',spec=deepcopy(proposal['spec']))]
    t['guard'](fixed,proposal)
    mutations=[('全合格',False),('正式freeze',False),('configs',[]),('case_SHA256',{}),('source_SHA256',{}),('計画SHA256','bad')]
    rejected=0
    for k,value in mutations:
        f=deepcopy(fixed);f[k]=value
        try:t['guard'](f,proposal)
        except AssertionError:rejected+=1
        else:raise AssertionError(('固定不一致の拒否漏れ',k))
    for k,value in (('正式freeze',False),('id','別試行')):
        p=deepcopy(proposal);p[k]=value
        try:t['guard'](fixed,p)
        except AssertionError:rejected+=1
        else:raise AssertionError(('計画不一致の拒否漏れ',k))
    for trials in ([],state['trials']*2,[dict(id='合成',spec={})]):
        original=deepcopy(state);state['trials']=trials
        try:t['guard'](fixed,proposal)
        except AssertionError:rejected+=1
        else:raise AssertionError('登録不一致の拒否漏れ')
        state.clear();state.update(original)
    p=deepcopy(proposal);p['spec']['data']['input_manifests'][0]['sha256']='bad'
    try:t['guard'](fixed,p)
    except AssertionError:rejected+=1
    else:raise AssertionError('目録不一致の拒否漏れ')
    original=t['OUT'];t['OUT']=SimpleNamespace(exists=lambda:True)
    try:t['guard'](fixed,proposal)
    except AssertionError:rejected+=1
    else:raise AssertionError('二度金融の拒否漏れ')
    t['OUT']=original
    return rejected


def storage_artificial(t: dict) -> dict:
    """
    機能: NumPy真偽/整数/未知・階段圧縮・要求された全根拠行を独立素材で照合する。
    引数: t(dict)は保存関数の純namespace。
    返り値: dictはsnapshot/圧縮/保存の検査数。
    """
    finite=t['finite'];checked=0
    raw=dict(flag=np.bool_(False),count=np.int64(0),unknown=np.float64(np.nan),infinite=np.inf,
             nested=(np.array([np.nan,0.,2.]),{'valid':True}),text='未知は零にしない')
    expected=dict(flag=False,count=0,unknown=None,infinite=None,nested=[[None,0.,2.],{'valid':True}],text='未知は零にしない')
    result=finite(raw);assert result==expected and type(result['flag']) is bool and type(result['count']) is int
    json.dumps(result,allow_nan=False);checked+=7
    for bad in (set(),object(),complex(1,2)):
        try:finite(bad)
        except TypeError:checked+=1
        else:raise AssertionError('非JSON型の拒否漏れ')
    rng=np.random.default_rng(113);packed_cases=0
    for shape in ((1,), (1,3),(20,),(20,3)):
        for dtype in (np.float64,np.int64):
            arr=rng.integers(-2,3,size=shape).astype(dtype)
            if len(arr)>1:arr[1:4]=arr[0]
            if dtype==np.float64 and len(arr)>5:arr[5:8]=np.nan
            p=t['packed'](arr);rows=p['rows'];values=p['values']
            index=np.searchsorted(rows,np.arange(len(arr)),side='right')-1
            np.testing.assert_array_equal(values[index],arr)
            encoded=finite(p);loaded=json.loads(json.dumps(encoded,allow_nan=False))
            restored=np.array(loaded['values'],dtype=arr.dtype)[index]
            np.testing.assert_array_equal(restored,arr)
            assert loaded['dtype']==arr.dtype.str and loaded['shape']==list(arr.shape)
            checked+=arr.size*2+2;packed_cases+=1
    n=40;idx=np.arange(n,dtype=np.int64);times=idx.astype(float)+600
    q=dict(bid=100.+idx,ask=100.5+idx,quote_valid=np.ones(n,bool),seq=idx+100,time_s=times)
    record=dict(price=100.25+idx,seq=idx+100,time_s=times,start=0.,end=1000.,limit=1000.,tick=.5)
    account=dict(symbol='TOPIX',record=record,quotes=q,mapping=idx+1000)
    volume=dict(known=np.ones(n,bool),reason=np.zeros(n,np.int64),up_votes=np.full(n,2,np.int64),down_votes=np.ones(n,np.int64),
                balance=np.full(n,1/3),first_vote_raw_row=np.maximum(0,idx-3),reference_raw_row=np.maximum(-1,idx-4))
    volume['known'][4]=False;volume['reason'][4]=9;volume['up_votes'][4]=17
    volume['up_votes'][6]=volume['down_votes'][6]=0;volume['balance'][6]=np.nan
    price=dict(own=dict(known=np.ones(n,bool),count=np.full(n,2,np.int64),balance=np.ones(n)),
               peer_known=np.ones(n,bool),peer_count=np.full(n,2,np.int64),peer_balance=np.ones(n),
               peer_row=np.maximum(0,idx-1),peer_raw_seq=idx+200,peer_price_age_seconds=np.full(n,.1))
    f=dict(volume=volume,price=price,flow=dict(interval_known=np.ones(n,bool),new_up_lower=np.zeros(n,np.int64),new_down_lower=np.ones(n,np.int64)),
           bar=dict(high=np.full(n,98.),low=np.full(n,97.),confirmed_row=np.full(n,3,np.int64)))
    orders=np.array([[19,18,0,1,10,119.5,90,1],[35,34,0,-1,10,135.,143,0]],float)
    pub=np.zeros((1,24));pub[0,[0,14,15,18]]=[30,6,8,4]
    support=np.zeros((1,10));support[0,[0,5,9]]=[32,24,23]
    origins=np.zeros((1,16));origins[0,[2,3]]=[16,14]
    net=154164.;output=dict(orders=orders,order_uids=np.array([0,-1]),exit_target_uids=np.array([-1,-1]),summary=dict(収支=net,費用=836),
        parent=[dict(親=0,収支=net)],actual_legs=[dict(uid=0,収支=net)],uid_accounts=[dict(uid=0,残枚数=0)],
        publication_events=pub,support_events=support,actual_origins=origins,
        exit_judgments=np.array([[29,0,-1,143]],float),execution_events=np.array([[20,1],[36,2]],float),
        parent_diagnostics=[dict(unknown=np.nan,known=np.bool_(True),count=np.int64(2))],
        equity_yen=np.repeat(np.array([0.,net]),20),liquidation_yen=np.repeat(np.array([0.,net]),20))
    expected_rows={4,6,8,14,16,18,19,20,23,24,29,30,32,34,35,36}
    snapshots=t['snapshots'](account,f,output)
    assert {s['row'] for s in snapshots}==expected_rows and len(snapshots)==len(expected_rows)
    converted=finite(snapshots);byrow={s['row']:s for s in converted}
    for row in expected_rows:
        s=byrow[row];assert s['raw_row']==row+1000 and s['raw_seq']==row+100 and s['price_time_s']==600+row
        assert s['bid']==100+row and s['ask']==100.5+row;checked+=5
    assert byrow[4]['volume_known'] is False and byrow[4]['volume_up'] is None and byrow[4]['volume_balance'] is None
    assert byrow[6]['volume_known'] is True and byrow[6]['volume_up']==byrow[6]['volume_down']==0 and byrow[6]['volume_balance'] is None
    checked+=7
    # ----------------------------------------
    # 保存先は自所有の新toyだけで、原台帳やroot-ownedを開かない。
    saved=t['save_ledger'](dict(id='合成'), '合成_Day', 'TOPIX',account,f,output)
    path=ROOT/saved['path'];assert path.resolve().is_relative_to(HERE)
    byte=path.read_bytes();assert hashlib.sha256(byte).hexdigest()==saved['SHA256']
    restored=pickle.loads(gzip.decompress(byte))
    np.testing.assert_array_equal(restored['orders'],orders)
    assert restored['summary']['収支']==net and len(restored['snapshots'])==len(expected_rows)
    destination=HERE/'保存人工'/'最終合成.json'
    t['write'](destination,dict(saved=saved,snapshots=snapshots,diagnostics=output['parent_diagnostics'],summary=output['summary']))
    loaded=json.loads(destination.read_text(encoding='utf-8'))
    assert loaded['diagnostics'][0]==dict(unknown=None,known=True,count=2)
    assert loaded['summary']['収支']==net
    try:t['write'](destination,{})
    except AssertionError:checked+=1
    else:raise AssertionError('保存上書き拒否漏れ')
    try:t['write'](ROOT/'所有外の未保存人工.json',{})
    except AssertionError:checked+=1
    else:raise AssertionError('所有外保存拒否漏れ')
    return dict(検査項目=checked,圧縮ケース=packed_cases,snapshot原行=len(expected_rows),snapshot列系譜='origin2/3、pub14/15/18、support5/9を異なる原行へ固定し全取得。',合成台帳SHA256=saved['SHA256'],最終JSON_SHA256=sha(destination))


def main() -> None:
    """
    機能: SOURCE_ONLYで根保存経路の独立人工を実行し、源前後同値へ束縛する。
    引数: なし。
    返り値: None。私有の成功/Falseとtoyだけを作成する。
    """
    raw=SOURCE.read_bytes();before=hashlib.sha256(raw).hexdigest();path=HERE/'根snapshotとguard及び未知保持の独立保存純人工.json'
    assert not path.exists()
    try:
        target=extract(raw);rejected=guard_artificial(target);checked=storage_artificial(target)
        assert before==sha(SOURCE)
        proof=dict(全合格=True,source=dict(path=SOURCE.relative_to(ROOT).as_posix(),SHA256=before),監査source_SHA256=sha(Path(__file__)),
            抽出範囲=['finite','write','packed','snapshots','save_ledger','guard'],guard拒否境界=rejected,counts=checked,
            制限='root run/load_cache/mainは抽出・実行しない。実登録/実cache/台帳は読まない。保存toyの実証は実入力の系譜や金融効能証拠でない。',
            原入力=0,実金融=0,原板=0,NPZ=0,API=0)
        path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,proof_SHA256=sha(path),guard拒否境界=rejected,counts=checked),ensure_ascii=False))
    except BaseException:
        out=HERE/'根保存純人工_初回False.json';assert not out.exists()
        out.write_text(json.dumps(dict(全合格=False,source_SHA256=before,原因=traceback.format_exc(),実入力=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8');raise


if __name__=='__main__':main()
