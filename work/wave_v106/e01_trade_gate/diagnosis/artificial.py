"""保存診断だけの親清算・部分返済料金・5寄与を小人工で確認する。"""

import hashlib
import numpy as np

import tools
import detail


def run() -> None:
    """
    機能: 診断の料金/鏡像/圧縮/寄与を金融や実入力なしで検査する。
    引数: なし。
    返り値: None。登録経済source・結果は使わない。
    """
    bid=np.array([99.5,99.5,103.,102.,100.,99.,99.]);ask=bid+.5
    orders=np.array([[1,0,0,1,5,100.,90,1],[3,2,0,-1,2,102.,91,0],[5,4,0,-1,3,99.,91,0]],float)
    q=dict(bid=bid,ask=ask,quote_valid=np.ones(7,bool),seq=np.arange(7),time_s=1700000000.+np.arange(7))
    a=dict(symbol='TOPIX',quotes=q)
    l=dict(orders=orders,order_uids=np.array([0,-1,-1]),parent=[{'親':0,'収支':583.}],summary={'収支':583.})
    value=tools.parent_path(l,a,0)
    assert value['事後の最大清算利益']==14582. and value['最大利益から返した金額']==13999.
    mirror=dict(q,bid=200.-ask,ask=200.-bid);opposite=orders.copy();opposite[:,3]*=-1;opposite[:,5]=200.-opposite[:,5]
    reflected=tools.parent_path(dict(l,orders=opposite),dict(a,quotes=mirror),0)
    assert reflected==value
    before=dict(parent=[{'親':0,'収支':10.},{'親':1,'収支':-20.},{'親':2,'収支':-5.}],summary={'収支':-15.})
    after=dict(parent=[{'親':1,'収支':-25.},{'親':3,'収支':15.}],summary={'収支':-10.})
    d=tools.contribution(before,after)
    assert [d[k] for k in detail.FIVE]==[5.,5.,10.,-5.,15.]
    np.testing.assert_array_equal(detail.expand(dict(rows=np.array([0,2,4]),values=np.array([1.,2.,3.]),length=6),6),[1,1,2,2,3,3])
    assert detail.vote_group(dict(known=False))=='未知'
    assert detail.vote_group(dict(known=True,direction_votes=1))=='既知2票未満'
    assert detail.vote_group(dict(known=True,direction_votes=2,balance=.25))=='既知2票以上・強同向'
    assert detail.vote_group(dict(known=True,direction_votes=2,balance=-.25))=='既知2票以上・強逆向'
    assert detail.vote_group(dict(known=True,direction_votes=2,balance=0.))=='既知2票以上・中間'
    source={p.relative_to(tools.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in tools.HERE.glob('*.py')}
    print(tools.write('親清算と5寄与診断の小人工.json',dict(全合格=True,検査数=9,
        観点=['TOP5枚2/3部分返済209/83/125料金と残UID料','買売鏡像','5寄与全額式','plateau全行復元','票区分5境界'],
        source_SHA256=source,実入力読取=0,金融結果読取=0,金融再生=0,原NPZ=0,API=0)),flush=True)


if __name__=='__main__':run()
