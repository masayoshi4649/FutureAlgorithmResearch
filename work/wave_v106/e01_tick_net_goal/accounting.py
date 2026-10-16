"""保存実口座の復元・五寄与・同商品集計を旧予算版と同じ数式で再利用する。"""

import numpy as np
import daily


def dense(value: dict, count: int) -> dict:
    """
    機能: 保存schema2のplateau配列を、元normal全行へ因果的な前方保持でexact復元する。
    引数: value(dict)、count(int)は保存GU台帳とnormal行数。
    返り値: dictは配列の復元。後行へのnearest補完や再売買はしない。
    """
    result=dict(value)
    for name,item in value.items():
        if isinstance(item,dict) and set(item)=={'rows','values','length'}:
            assert item['length']==count;rows=item['rows'];assert rows[0]==0 and np.all(np.diff(rows)>0)
            index=np.searchsorted(rows,np.arange(count),side='right')-1
            result[name]=item['values'][index]
    return result


def stored(value: dict, count: int) -> dict:
    """
    機能: 新政策の実注文・UID・玉だけを公開し、口座価格列をplateau保存する。
    引数: value(dict)、count(int)は新実口座会計とnormal行数。
    返り値: dictはschema2台帳。元影GUのstate/virtual feedを新実状態へ流用しない。
    """
    result=dict(value)
    for name in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
        array=value[name];assert len(array)==count;rows=np.r_[0,np.flatnonzero(array[1:]!=array[:-1])+1].astype(np.int64)
        result[name]=dict(rows=rows,values=array[rows],length=count)
    result['schema_version']=2
    return result


def compare(before: dict, after: dict) -> dict:
    """
    機能: 同じ実新規cidの完結親で、基準P1L8に対する5寄与と勝ち→負けを分類する。
    引数: before/after(dict)は完成P1L8保存と新政策の実会計。
    返り値: dictは収支差・以後消失・共通出口・新親及び勝ちの赤字化件数。
    """
    a={p['親']:p for p in before['parent']};b={p['親']:p for p in after['parent']}
    removed=a.keys()-b.keys();added=b.keys()-a.keys();joined=a.keys()&b.keys()
    avoid=sum(-a[k]['収支'] for k in removed if a[k]['収支']<0)
    missed=sum(a[k]['収支'] for k in removed if a[k]['収支']>0)
    exit_change=sum(b[k]['収支']-a[k]['収支'] for k in joined);new=sum(b[k]['収支'] for k in added)
    delta=after['summary']['収支']-before['summary']['収支']
    assert np.isclose(delta,avoid-missed+exit_change+new,atol=1e-5,rtol=0.)
    turned=[dict(parent=int(k),base_net=float(a[k]['収支']),new_net=float(b[k]['収支'])) for k in joined if a[k]['収支']>0 and b[k]['収支']<0]
    rescued=[dict(parent=int(k),base_net=float(a[k]['収支']),new_net=float(b[k]['収支'])) for k in joined if a[k]['収支']<0 and b[k]['収支']>0]
    return dict(収支変化=float(delta),避けた基準損失=float(avoid),失った基準利益=float(missed),共通入口の出口変化=float(exit_change),新たな入口の収支=float(new),
        元勝ち親が赤字化=turned,元負け親が黒字化=rescued,消えた基準親=[int(k) for k in removed],新しい親=[int(k) for k in added])


def aggregate(rows: list[dict], parents: list[dict]) -> dict:
    """
    機能: 同一商品33場の親金額割合と活動安定性・大勝ち除外を再集計する。
    引数: rows/parents(list[dict])は同商品の会計と実親。
    返り値: dictは金額/枚数と黒赤無取引。取引なしを勝ちにしない。
    """
    assert len(rows)==33 and len({r['session'] for r in rows})==33
    total=daily.metric([p['収支'] for p in parents]);active=[r for r in rows if r['親数']>0]
    positive=sorted((r for r in rows if r['収支']>0),key=lambda r:r['収支'],reverse=True);negative=[r for r in rows if r['収支']<0]
    return dict(**total,全場=33,活動場=len(active),黒字場=len(positive),赤字場=len(negative),無取引場=33-len(active),
        活動黒字率=len(positive)/len(active) if active else None,中央値=float(np.median([r['収支'] for r in rows])),
        活動場中央値=float(np.median([r['収支'] for r in active])) if active else None,
        上位3利益場除外収支=total['収支']-sum(r['収支'] for r in positive[:3]),最大場損失=max([0.]+[-r['収支'] for r in rows]),
        最悪場=min(rows,key=lambda r:r['収支'])['session'],費用=sum(r['費用'] for r in rows),新規枚数=sum(r['新規枚数'] for r in rows),
        勝ち枚数=sum(r['勝ち枚数'] for r in rows),負け枚数=sum(r['負け枚数'] for r in rows),零枚数=sum(r['零枚数'] for r in rows),
        注文件数=sum(r['注文件数'] for r in rows),全33黒字=len(positive)==33)
