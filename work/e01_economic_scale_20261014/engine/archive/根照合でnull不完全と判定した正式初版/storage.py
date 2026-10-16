"""保護traceを同値plateauへ圧縮し、金融保存の容量を抑える準備部品。"""

import numpy as np


def pack(trace: np.ndarray|None) -> dict|None:
    """
    機能: 当時高水準・保護状態・停止線・理由の4列を、同NaN位置を保って圧縮する。
    引数: trace(ndarray|None) は全normal4列又は未受理の未定義。
    返り値: dict|None は型・dtype・shape・rows/values/lengthを持つ保存形。
    """
    if trace is None:return None
    assert trace.ndim==2 and trace.shape[1]==4 and len(trace)>0 and np.issubdtype(trace.dtype,np.floating)
    changed=np.any((trace[1:]!=trace[:-1])&~(np.isnan(trace[1:])&np.isnan(trace[:-1])),axis=1)
    rows=np.r_[0,np.flatnonzero(changed)+1].astype(np.int64)
    return dict(type='plateau',dtype=trace.dtype.str,shape=list(trace.shape),rows=rows,values=trace[rows].copy(),length=len(trace))


def expand(value: dict|None) -> np.ndarray|None:
    """
    機能: 保存4列を同normal行へ戻し、型・長さ・並びの不正を拒否する。
    引数: value(dict|None) は圧縮trace又は未定義。
    返り値: ndarray|None は元traceとexact同値の配列。
    """
    if value is None:return None
    assert value['type']=='plateau' and value['shape']==[value['length'],4] and value['length']>0
    rows=np.asarray(value['rows']);points=np.asarray(value['values'])
    assert rows.ndim==1 and np.issubdtype(rows.dtype,np.integer) and len(rows)>0 and rows[0]==0
    assert np.all(rows[1:]>rows[:-1]) and rows[-1]<value['length']
    assert points.shape==(len(rows),4) and points.dtype.str==value['dtype']
    return points[np.searchsorted(rows,np.arange(value['length']),side='right')-1]
