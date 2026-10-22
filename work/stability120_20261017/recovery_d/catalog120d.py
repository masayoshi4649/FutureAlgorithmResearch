"""不利時少枚数という仮説を直接満たす、利益条件付き追加の四対照。"""

from catalog120 import settings


def specifications() -> list[dict]:
    """
    機能: 二十四条件を実測前に列挙する。
    引数: なし。
    返り値: list[dict]はmode8〜11、三幅、二追尾の固定条件。
    """
    modes=(
        (8,'CREDIT','小試行と含み益後の追加','各方向最初は一枚。同方向の清算純益が追加一枚の三単位リスクを賄えるときだけ増やし、同方向全玉の清算純損失が三単位なら返済する。'),
        (9,'ONE','片方向に絞る小試行','小試行型を一方向だけで動かす。反対の新規待機水準は保有中の現在最終約定値へ戻し、旧い逆方向の合図を持ち越さない。'),
        (10,'LIMIT','新規価格を限定する小試行','片方向型の新規を判断時ask又はbidから観測一刻みまでに限定。最初の次正常気配で超過なら一回で失効し、都合のよい後の気配を待たない。'),
        (11,'COST','広い気配を避ける小試行','価格限定型に、判断時と最初の次気配の売買気配差が一単位以内という条件を加える。幅が広い行では新規極値を更新しない。'),
    )
    result=[]
    for mode,tag,name,description in modes:
        for width,fraction in enumerate((.000125,.00025,.0005),1):
            for trail in (1.,3.):
                result.append(dict(id=f'{tag}_LAST_S{width}_T{int(trail)}',mode=mode,name=name,
                    description=description,fraction=fraction,width_id=width,trail=trail,activation=trail+1.,
                    rules=dict(入口='動く最終約定値極値から3/4/5…単位。ただし最初一枚、追加は既存の同方向清算純益>=3単位×(新規予約済枚数+1)。',
                        途中='方向別の返済予約中は追加しない。その方向が全返済済みになったら空き枠の極値を現在最終約定値へ戻す。',
                        出口='玉別利益追尾は基準と同じ。同方向の全残玉清算netが一枚分の三単位損なら全返済予約。次気配の損失超過も計上。')))
    assert len(result)==24
    return result
