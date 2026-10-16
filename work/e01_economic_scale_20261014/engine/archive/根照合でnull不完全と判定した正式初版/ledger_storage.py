"""旧gateの集計・五寄与・plateau保存を同一関数sourceで私有コピーする。"""

import numpy as np
import daily


def aggregate(rows: list[dict], parents: list[dict], sessions: list[str]) -> dict:
    """
    機能: 保存した同商品33場の金額・枚数・活動・上位3場除外を集計する。
    引数: rows/parents(list[dict])、sessions(list[str])は保存会計と固定場順。
    返り値: dictは集計。無取引を黒字・勝ちに含めない。
    """
    assert len(rows)==len(sessions) and {r['session'] for r in rows}==set(sessions)
    totals=daily.metric([p['収支'] for p in parents]);active=[r for r in rows if r['親数']]
    positive=sorted((r for r in rows if r['収支']>0),key=lambda r:r['収支'],reverse=True)
    negative=[r for r in rows if r['収支']<0]
    return dict(**totals,全場=len(rows),活動場=len(active),黒字場=len(positive),赤字場=len(negative),
        無取引場=len(rows)-len(active),中央値=float(np.median([r['収支'] for r in rows])),
        活動場中央値=float(np.median([r['収支'] for r in active])) if active else None,
        上位3利益場除外収支=totals['収支']-sum(r['収支'] for r in positive[:3]),
        最大場損失=max([0.]+[-r['収支'] for r in rows]),
        費用=sum(r['費用'] for r in rows),新規枚数=sum(r['新規枚数'] for r in rows),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows),負け枚数=sum(r['負け枚数'] for r in rows),
        零枚数=sum(r['零枚数'] for r in rows),全33黒字=len(positive)==len(rows))


def delta(before: dict, after: dict) -> dict:
    """
    機能: 不変紙上親cidで入口の削除・新参加・共通親の数量及び出口差を分解する。
    引数: before/after(dict)は同場・同paper親に対応する完結親会計。数量は異なってよい。
    返り値: dictは避け損失・失った利益・共通親の数量及び出口差・新入口・総差の5寄与。
    """
    a={p['親']:p for p in before['parent']};b={p['親']:p for p in after['parent']}
    removed=a.keys()-b.keys();joined=a.keys()&b.keys();added=b.keys()-a.keys()
    avoid=sum(-a[k]['収支'] for k in removed if a[k]['収支']<0)
    missed=sum(a[k]['収支'] for k in removed if a[k]['収支']>0)
    exit_change=sum(b[k]['収支']-a[k]['収支'] for k in joined);new=sum(b[k]['収支'] for k in added)
    net=after['summary']['収支']-before['summary']['収支']
    assert np.isclose(net,avoid-missed+exit_change+new,atol=1e-5,rtol=0.)
    return {'収支変化':net,'避けた基準損失':avoid,'失った基準利益':missed,
            '共通入口の数量/出口差':exit_change,'新たな入口の収支':new}


def stored(value: dict, count: int) -> dict:
    """
    機能: 全normal行と同値のplateau圧縮で大配列だけを保存する。
    引数: value(dict)、count(int)は台帳とnormal行数。
    返り値: dictはschema_version2。rows/values/lengthから前方値保持で復元できる。
    """
    output=dict(value)
    names={'equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty',
           'execution_states','gate_accepted','gate_reasons','sizing_fee_curve'}
    for k,v in value.items():
        if k not in names or not isinstance(v,np.ndarray) or len(v)!=count:continue
        changed=np.any(v[1:]!=v[:-1],axis=1) if v.ndim==2 else v[1:]!=v[:-1]
        rows=np.r_[0,np.flatnonzero(changed)+1].astype(np.int64)
        output[k]=dict(rows=rows,values=v[rows],length=count)
    output['schema_version']=2;return output
