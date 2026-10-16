"""作成した一次台帳からJSON最終保存までを、実入力無しの小会計で接続する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'engine'))
import catalog
import daily

ms=importlib.util.spec_from_file_location('根金融の保存人工',HERE/'finance.py')
finance=importlib.util.module_from_spec(ms)
ms.loader.exec_module(finance)


def main() -> None:
    """
    機能: 合成の実新規/全量返済/支持事象を一次台帳とJSONへ保存して検算する。
    引数: なし。
    返り値: None。原板・cache・NPZ・API・実金融は読まない。
    """
    destination=HERE/'人工保存統合'
    assert not destination.exists()
    destination.mkdir()
    finance.OUT=destination/'synthetic_ledger'
    n=6
    b=np.arange(n,dtype=float)+100.
    a=b+1.
    time=np.arange(n,dtype=float)
    seq=np.arange(n,dtype=np.int64)
    q=dict(bid=b,ask=a,quote_valid=np.ones(n,bool),seq=seq,time_s=time)
    r=dict(price=b+.5,seq=seq,time_s=time,start=0.,end=5.,limit=5.,tick=.5)
    account=dict(symbol='TOPIX',record=r,quotes=q,mapping=seq.copy())
    orders=np.array([[1,0,0,1,10,102,90,1],[4,3,0,-1,10,104,143,0]],float)
    uids=np.array([0,-1],np.int64)
    output=daily.reconstruct(('合成_Day','TOPIX'),orders,uids,q)
    assert output['summary']['収支']==19164 and output['summary']['費用']==836
    pub=np.zeros((1,24))
    pub[0,[0,1,2,12,14,15,18]]=[0,0,1,1,0,-1,-1]
    origin=np.zeros((1,16))
    origin[0,[0,1,2,3,4,5,6,15]]=[0,0,1,0,1,10,102,-1]
    support=np.array([[3,0,1,99,100,2,101,102,1,1]],float)
    output.update(publication_events=pub,actual_origins=origin,support_events=support,
                  exit_judgments=np.array([[3,0,-1,143]],float),execution_events=np.array([[1,1],[4,2]],float),
                  parent_diagnostics=[dict(known=np.bool_(True),count=np.int64(2),unknown=np.float64(np.nan),net=np.float64(19164))])
    up=np.full(n,2,np.int64)
    down=np.ones(n,np.int64)
    volume=dict(known=np.ones(n,bool),reason=np.zeros(n,np.int64),up_votes=up,down_votes=down,
                balance=np.full(n,1/3),first_vote_raw_row=np.zeros(n,np.int64),reference_raw_row=np.zeros(n,np.int64))
    volume['balance'][0]=np.nan
    volume['up_votes'][0]=volume['down_votes'][0]=0
    price=dict(own=dict(known=np.ones(n,bool),count=np.full(n,2,np.int64),balance=np.ones(n)),
        peer_known=np.ones(n,bool),peer_count=np.full(n,2,np.int64),peer_balance=np.ones(n),
        peer_row=np.zeros(n,np.int64),peer_raw_seq=np.zeros(n,np.int64),peer_price_age_seconds=np.ones(n))
    features=dict(volume=volume,price=price,flow=dict(interval_known=np.ones(n,bool),new_up_lower=np.zeros(n,np.int64),new_down_lower=np.zeros(n,np.int64)),
        bar=dict(high=np.full(n,99.),low=np.full(n,98.),confirmed_row=np.zeros(n,np.int64)))
    snapshots=finance.snapshots(account,features,output)
    assert {p['row'] for p in snapshots}=={0,1,2,3,4}
    converted=finance.finite(snapshots)
    assert converted[0]['volume_known'] and converted[0]['volume_up']==converted[0]['volume_down']==0
    assert converted[0]['volume_balance'] is None
    saved=finance.save_ledger(catalog.configs()[0],'合成_Day','TOPIX',account,features,output)
    assert saved['SHA256']==hashlib.sha256((finance.ROOT/saved['path']).read_bytes()).hexdigest()
    result=dict(全合格=np.bool_(True),親=np.int64(1),会計=output['summary'],parents=output['parent'],診断=output['parent_diagnostics'],
                保存=saved,観測=snapshots,圧縮=finance.packed(np.array([0.,0.,np.nan,np.nan,2.,2.])))
    finance.write(destination/'最終保存の合成結果.json',result)
    loaded=json.loads((destination/'最終保存の合成結果.json').read_text(encoding='utf-8'))
    assert loaded['全合格'] is True and loaded['親']==1 and loaded['会計']['収支']==19164
    assert loaded['診断'][0]['known'] is True and loaded['診断'][0]['count']==2 and loaded['診断'][0]['unknown'] is None
    assert loaded['圧縮']['values']==[0.,None,2.]
    rejected=False
    try:
        finance.financial_metrics.amounts([float('nan')])
    except AssertionError:
        rejected=True
    assert rejected
    paths=[HERE/name for name in ('finance.py','financial_metrics.py','plan.py')]
    paths.append(Path(__file__).resolve())
    proof=dict(全合格=True,対象='根の一次台帳/原行snapshot/NumPy保存型/未知保持/最終JSON保存までの合成統合',
        source_SHA256={p.relative_to(finance.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        合成会計=dict(新規10mini=102,返済10mini=104,粗利益=20000,実料=836,収支=19164),
        既知零票と未知balanceを区別=True,NumPy_bool_int_floatの最終保存=True,実金融=0,cache=0,NPZ=0,原板=0,API=0)
    finance.write(HERE/'根の一次台帳と未知保持及び最終JSON保存の純人工.json',proof)
    print('根の全保存経路・原行snapshot・既知零/未知・金額定義の人工合格。実入力0。')


if __name__=='__main__':
    main()
