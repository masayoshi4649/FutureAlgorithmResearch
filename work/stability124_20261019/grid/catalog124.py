"""前場IVによる新規幅と保有上限の変更を結果前に固定する。"""

import math


def specifications() -> list[dict]:
    """
    機能: 十個の基準・IV部品と二つの固定幅対照を列挙する。
    引数: なし。
    返り値: list[dict]は固定十二条件。全条件で途中利確・損切りなし。
    """
    items=[
        ('O00','オプションなし・3/3','none'),
        ('O01','IVで追加間隔を緩く調整','gap_sqrt'),
        ('O02','IVで追加間隔を調整','gap'),
        ('O03','IVで初回幅を緩く調整','initial_sqrt'),
        ('O04','IVで初回幅を調整','initial'),
        ('O05','IVで初回と追加を緩く調整','both_sqrt'),
        ('O06','IVで初回と追加を調整','both'),
        ('O07','IVで幅調整・高IV時は枚数減','both_cap'),
        ('O08','対照・IVと逆に幅調整','inverse'),
        ('O09','高IV時の枚数減だけ','cap'),
        ('O10','固定幅対照・初回3/間隔10','fixed10'),
        ('O11','固定幅対照・初回15/間隔15','fixed15'),
    ]
    return [dict(id=i,name=n,rule=r) for i,n,r in items]


def parameters(spec: dict,feature: dict,symbol: str) -> dict:
    """
    機能: 当場開始前に確定した前場IVだけで初回・段間隔・枚数を固定する。
    引数: spec/feature(dict)は固定仕様と前場特徴、symbol(str)は二先物の一方。
    返り値: dictは単位数initial/spacing、cap(int)、unit(float)、IV利用有無。
        IV不明なら基準3/3へ戻し、不明をゼロIVとしない。
    """
    assert symbol in ('TOPIX','NK225')
    cap=10 if symbol=='TOPIX' else 20
    unit=1. if symbol=='TOPIX' else 20.
    initial=spacing=3.;rule=spec['rule'];known=feature['known']
    ratio=min(2.,max(.5,float(feature['iv_median_percent'])/30.)) if known else 1.
    used=known and rule not in ('none','fixed10','fixed15')
    if rule=='fixed10':spacing=10.
    elif rule=='fixed15':initial=spacing=15.
    elif used:
        if rule=='gap_sqrt':spacing*=math.sqrt(ratio)
        elif rule=='gap':spacing*=ratio
        elif rule=='initial_sqrt':initial*=math.sqrt(ratio)
        elif rule=='initial':initial*=ratio
        elif rule=='both_sqrt':initial*=math.sqrt(ratio);spacing*=math.sqrt(ratio)
        elif rule in ('both','both_cap'):initial*=ratio;spacing*=ratio
        elif rule=='inverse':initial/=ratio;spacing/=ratio
        elif rule!='cap':raise AssertionError(rule)
        if rule in ('both_cap','cap'):cap=max(1,math.floor(cap/max(1.,ratio)))

    # ----------------------------------------
    # 入口価格の幅だけ呼値へ上丸めし、気配資格のunitは拡大しない。
    tick=.5 if symbol=='TOPIX' else 10.
    initial=math.ceil(initial*unit/tick-1e-12)*tick/unit
    spacing=math.ceil(spacing*unit/tick-1e-12)*tick/unit
    return dict(initial=initial,spacing=spacing,cap=cap,unit=unit,used=used,
        ratio=ratio if known else None,iv_pct=feature['iv_median_percent'] if known else None)
