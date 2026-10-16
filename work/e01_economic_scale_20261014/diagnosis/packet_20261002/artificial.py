"""一場価格診断の自己原行/相手strict時計/影方向と未知保存を純小人工で確認する。"""

import copy
import numpy as np
import inspect_packet as reader


def fixture() -> dict:
    """
    機能: 同時計後続と紙上部分返済を持つ人工口座だけを作る。
    引数: なし。
    返り値: dict は小配列/影feed。実素材又は金融sourceをimportしない。
    """
    n=8;times=np.array([1.,2.,2.,3.,4.,5.,6.,7.]);bid=np.array([100.,102.,101.,101.,100.,99.,98.,100.])
    seq=np.arange(n,dtype=np.int64)+100;feed=np.zeros((3,10))
    feed[:,0]=[0,4,7];feed[:,2]=2;feed[:,3]=[1,-1,-1];feed[:,4]=[5,2,3];feed[:,5]=100.;feed[0,7]=1;feed[:,9]=3.
    return dict(record=dict(price=bid+.5,time_s=times,seq=seq),quotes=dict(bid=bid,ask=bid+1.,quote_valid=np.ones(n,bool),time_s=times,seq=seq),
        mapping=np.arange(n,dtype=np.int64)*2,feed=feed)


def run() -> None:
    """
    機能: strict過去/自己当行/未補完/影残量と価格のみ戻りを小人工で検査する。
    引数: なし。
    返り値: None。source拘束証跡を保存。実input/金融/ledger/API0。
    """
    source=reader.sources();a=fixture();count=0
    peer=reader.peer_point(a,2.);assert peer['観測']['normal_row']==0 and peer['age_price_proxy_seconds']==1.;count+=2
    peer=reader.peer_point(a,3.);assert peer['観測']['normal_row']==2;count+=1
    assert not reader.peer_point(a,1.)['既知'];count+=1
    broken=copy.deepcopy(a);broken['quotes']['quote_valid'][2]=False
    assert reader.peer_point(broken,3.)['観測']['normal_row']==1;count+=1
    for row,expected in ((0,5),(3,5),(4,3),(6,3),(7,0)):
        state=reader.paper_state(a,row);assert state['影残数量']==expected and state['影方向']==int(expected>0);count+=2
    data=reader.point(a,1);assert data['raw_seq']==101 and data['bid']==102. and data['raw_index']==2;count+=3
    out=reader.sample_path(a,a,0,7,1,100.)
    assert out['事後最大点以後の初戻り観測']['1pt']['自己']['normal_row']==2
    assert out['事後最大点以後の初戻り観測']['2pt']['自己']['normal_row']==4
    assert out['事後最大点以後の初戻り観測']['4pt']['自己']['normal_row']==6;count+=3
    altered=copy.deepcopy(a);altered['quotes']['bid'][4:]+=100.;altered['quotes']['ask'][4:]+=100.
    assert reader.point(altered,1)==data
    assert reader.peer_point(altered,3.)==reader.peer_point(a,3.)
    assert reader.paper_state(altered,3)==reader.paper_state(a,3);count+=3
    assert reader.safe({'値':float('nan'),'既知零':0.})=={'値':None,'既知零':0.};count+=2
    saved=reader.schema(a);assert saved['内容']['record']['全key']==['price','time_s','seq']
    assert saved['内容']['record']['内容']['price']['shape']==[8];count+=2
    assert source==reader.sources()
    reader.write('一場価格観測の純人工.json',dict(全合格=True,検査=count,source_SHA256=source,
        実packet読取=0,金融=0,原board=0,NPZ=0,台帳=0,API=0))
    print('一場価格観測の純人工合格 '+str(count)+'検査。実packet0。')


if __name__=='__main__':run()
