"""方向だけの判断中値採点を、次行約定気配の採点と分離する。"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pickle

import numpy as np
from numba import njit

import study


HERE=Path(__file__).resolve().parent


@njit(cache=True)
def touch(mid: np.ndarray,index: int,side: int,fraction: float) -> tuple:
    """機能: 判断中値からの対称幅について、未来経路の先着を採点する。

    引数: mid(ndarray)、index/side(int)、fraction(float)。
    返り値: 先着方向と原板行(tuple[int,int])。事後採点だけに使用する。
    """
    anchor=mid[index];width=anchor*fraction
    for i in range(index+1,len(mid)):
        gain=side*(mid[i]-anchor)
        if gain>=width-1.e-9:
            return 1,i
        if gain<=-width+1.e-9:
            return -1,i
    return 0,-1


def main() -> None:
    """機能: 気配差・次行建値を入れない中値の方向診断を結果前固定して計算する。

    引数: なし。返り値: なし(None)。元入口と売買結果は変更しない。
    """
    target=HERE/'判断中値の方向診断.json'
    assert not target.exists()
    sources=(HERE/'入口採点.json',HERE/'round2/入口採点.json')
    study.save(HERE/'判断中値診断の事前固定.json',dict(時刻=datetime.now(timezone.utc).isoformat(),
        理由='元の採点は次行実建値と返済気配を使うため、価格方向だけと経済的な約定採点を分ける。',
        基準='検知した原板行の中値。翌原板行以後〜同じ保存通常区間末。0.03/0.05/0.1/0.2%の対称先着と最大順行。',
        幅='割合の連続値。売買と同じ百分率で、ラージ呼値切上げなし。',
        用途='補助診断のみ。入口条件・方向・出入り・主案選定を変更しない。',
        SHA={str(p):study.digest(p) for p in (Path(__file__),*sources,study.exits.QUOTES)}))
    quotes=pickle.loads(study.exits.QUOTES.read_bytes())
    suffix={key:(np.maximum.accumulate(q['mid'][::-1])[::-1],np.minimum.accumulate(q['mid'][::-1])[::-1]) for key,q in quotes.items()}
    cache={};methods=[]
    for source in sources:
        packet=json.loads(source.read_text(encoding='utf-8'))
        for old in packet['methods']:
            rows=[]
            for r in old['rows']:
                key=(r['session'],r['symbol']);i,side=r['i'],r['side'];ck=(*key,i,side)
                if ck not in cache:
                    mid=quotes[key]['mid'];hi,lo=suffix[key];anchor=float(mid[i])
                    mfe=max(0.,hi[i+1]-anchor) if side>0 else max(0.,anchor-lo[i+1])
                    labels={}
                    for f in (.0003,.0005,.001,.002):
                        first,index=touch(mid,i,side,f)
                        labels[f'{f*100:.2f}']=dict(target=bool(mfe>=anchor*f-1.e-9),first=int(first),first_i=int(index))
                    cache[ck]=dict(session=key[0],symbol=key[1],i=i,seq=r['seq'],side=side,decision_mid=anchor,
                        mfe=float(mfe),mfe_fraction=float(mfe/anchor),labels=labels)
                rows.append(cache[ck])
            summary={}
            for symbol in ('TOPIX','NK225'):
                chosen=[r for r in rows if r['symbol']==symbol]
                a=study.score_summary(chosen);n=len(chosen)
                a['labels']['0.03']=dict(target_rate=sum(r['labels']['0.03']['target'] for r in chosen)/n if n else None,
                    targets=sum(r['labels']['0.03']['target'] for r in chosen),
                    first_rate=sum(r['labels']['0.03']['first']==1 for r in chosen)/n if n else None,
                    first=sum(r['labels']['0.03']['first']==1 for r in chosen),opposite=sum(r['labels']['0.03']['first']==-1 for r in chosen),
                    unresolved=sum(r['labels']['0.03']['first']==0 for r in chosen))
                summary[symbol]=a
            methods.append(dict(config=old['config'],summary=summary,rows=rows))
    study.save(target,dict(methods=methods,診断='判断中値起点の純価格方向。実現利益ではない。',独立経路数=len(cache)))
    print('72入口の判断中値診断を保存しました')


if __name__=='__main__':
    main()
