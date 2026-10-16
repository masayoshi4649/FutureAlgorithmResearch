"""旧goalの保存GUを同bytes一読台帳から復元し、二政策の共通入力へ再利用する。"""

import numpy as np


USED={0:'shadow_GU_orders',5:'shadow_GU_uids',6:'execution_events',7:'execution_states',
      8:'limit_events',9:'sizing_events',10:'sizing_fee_curve'}


def expand(value: object, count: int, normal: bool) -> np.ndarray:
    """
    機能: 保存された全行又はplateauを、同じnormal行順の配列へ復元する。
    引数: value(object)、count(int)、normal(bool) は保存項目・行数・全行曲線か。
    返り値: ndarray は読取り専用配列。末尾や欠測を未来値で補完しない。
    """
    if isinstance(value,dict):
        assert normal and set(value)=={'rows','values','length'} and value['length']==count
        rows=np.asarray(value['rows']);points=np.asarray(value['values'])
        assert np.issubdtype(rows.dtype,np.integer) and rows.ndim==1 and len(rows)>0
        assert rows[0]==0 and np.all(rows[1:]>rows[:-1]) and rows[-1]<count and len(points)==len(rows)
        positions=np.searchsorted(rows,np.arange(count),side='right')-1
        result=points[positions]
    else:
        assert isinstance(value,np.ndarray)
        result=value
    if normal:assert len(result)==count
    result.setflags(write=False)
    return result


def values(ledger: dict, count: int) -> tuple:
    """
    機能: account_outputが使用するGU七配列だけを保存台帳から取り出す。
    引数: ledger(dict)、count(int) は旧利確アンカー台帳と入力normal行数。
    返り値: tuple は11槽。未使用の1/2/3/4槽はNoneとし、新GUを実行しない。
    """
    output=[None]*11
    for index,name in USED.items():
        assert name in ledger,('保存GU項目不足',name)
        output[index]=expand(ledger[name],count,index in (7,10))
    assert output[0].ndim==2 and output[0].shape[1]==8
    assert output[5].shape==(len(output[0]),) and np.issubdtype(output[5].dtype,np.integer)
    for index,width in ((6,12),(7,10),(8,18),(9,16),(10,5)):
        assert output[index].ndim==2 and output[index].shape[1]==width,(index,output[index].shape)
    return tuple(output)


def pair(first: dict, second: dict, count: int) -> tuple:
    """
    機能: 同母P1/P2の二台帳が同じGU七配列を持つことをexact照合する。
    引数: first/second(dict)、count(int) は各一読した旧二政策とnormal行数。
    返り値: tuple は確認した共有GU。政策自身のordersやequityをGUへ取り違えない。
    """
    assert first['key']==second['key']
    one,two=values(first,count),values(second,count)
    for index in USED:np.testing.assert_array_equal(one[index],two[index])
    return one
