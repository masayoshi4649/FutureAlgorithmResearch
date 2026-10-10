"""方向判定と建玉管理を分けて比較する、結果を読む前に固定する条件一覧。"""

from __future__ import annotations

import math

BASE=dict(initial_qty=10,entry_atr=.25,stop_atr=1.,main_trail=2.,add_mode=0,
          add_step=.5,add_qty=10,hedge_ratio=0.,hedge_trigger=.75,cover_add=0,
          cover_step=.5,cover_trail=.5,reverse_mode=0,lock_fraction=0.,
          split_target=0.,timeout_min=180.,neutral_min=0.,us_mode=0)


def managers() -> list[dict]:
    """機能: 固定型、段階増玉、カバー、反転、配分変更を比較する管理条件を返す。

    引数: なし。返り値: 日本語説明を含む条件 (list[dict])。
    """
    rows=[
        ('A00','固定10枚','方向を確認して10枚入り、１ATR損切り・２ATR追跡で全返済。',{}),
        ('A01','広い追跡で保持','固定10枚を４ATRの広い追跡で保有する対照。',dict(main_trail=4.)),
        ('A02','方向維持と反転','価格追跡で主玉を切らず、反対方向が確認されたら主玉を返済して反転。',dict(main_trail=math.inf,reverse_mode=1)),
        ('A03','均等な順行増玉','有利に0.5ATR進むたび10枚追加し、片方向100枚まで積む。',dict(add_mode=1)),
        ('A04','半分カバー','主玉の最高益から0.75ATR戻ったら、主玉の半分を逆方向に建てる。',dict(hedge_ratio=.5)),
        ('A05','全量カバー','0.75ATRの戻りで主玉と同数を逆方向に建て、逆玉の利益を追跡する。',dict(hedge_ratio=1.)),
        ('A06','固定玉の判断撤回','固定10枚の追跡に加え、方向状態が逆転したら次行で反転。',dict(reverse_mode=1)),
        ('A07','増玉と半分カバー','順行時10枚ずつ増玉し、戻りでは主玉の半分をカバー。',dict(add_mode=1,hedge_ratio=.5)),
        ('A08','増玉・カバー・反転','順行増玉と半分カバーを行い、方向撤回時は主玉を閉じてカバーを主玉にする。',dict(add_mode=1,hedge_ratio=.5,reverse_mode=1)),
        ('B01','主玉保持と全量カバー','主玉を広い追跡で保持し、同数カバーで一時的な逆行を抑える。',dict(main_trail=4.,hedge_ratio=1.)),
        ('B02','主玉維持とカバー昇格','主玉の価格追跡返済を外し、全量カバーと方向撤回による昇格で進む。',dict(main_trail=math.inf,hedge_ratio=1.,reverse_mode=1)),
        ('B03','両方向の均等増玉','主方向と逆方向のどちらも、進んだ側に10枚ずつ追加。方向撤回時は役割を交代。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=1)),
        ('B04','両方向の加速増玉','順行側の枚数を倍増型で増やす。両方向100枚と全玉損失上限で制限。',dict(main_trail=math.inf,add_mode=3,hedge_ratio=.5,cover_add=2,reverse_mode=1)),
        ('B05','利益を半分保護する両方向増玉','両方向増玉に、全玉合計の最高利益50％を残す追跡を加える。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.5)),
        ('B06','利益75％を保護する両方向増玉','両方向増玉に、全玉合計の最高利益75％を残す追跡を加える。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.75)),
        ('B07','価格でも確認して反転','反対方向状態に加えて主玉基準から0.75ATR逆行したら反転する。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=2,lock_fraction=.5)),
        ('B08','逆方向を厚くするカバー','戻りで主玉の1.5倍を逆方向に建て、さらに進めば増玉する。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=1.5,cover_add=1,reverse_mode=2,lock_fraction=.5)),
        ('C01','小刻みな順行増玉','0.25ATR進むたび５枚追加。小さい変化で枚数を増減する。',dict(add_mode=1,add_step=.25,add_qty=5,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.5)),
        ('C02','大きく進んだ時だけ増玉','１ATR進むたび10枚追加。細かい波で追加し過ぎない。',dict(add_mode=1,add_step=1.,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.5)),
        ('C03','初期を厚く追加を小さく','順行するほど追加枚数を減らし、高値での大量追加を抑える。',dict(add_mode=4,hedge_ratio=.5,reverse_mode=1,lock_fraction=.5)),
        ('C04','押し目だけ追加','方向状態を保つ間だけ、逆行0.5ATRごとに10枚追加。全玉損失上限は固定。',dict(add_mode=2,hedge_ratio=.5,reverse_mode=1,lock_fraction=.5)),
        ('C05','一部利確と順行再配置','１ATR進んだら主玉の半数を利確し、その後も順行時に増玉する。',dict(add_mode=1,hedge_ratio=.5,reverse_mode=1,split_target=1.,lock_fraction=.5)),
        ('C06','カバーの追跡を短縮','逆方向カバーの追跡を0.25ATRに縮め、戻りの利益を早めに確保。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,cover_trail=.25,reverse_mode=1,lock_fraction=.5)),
        ('C07','小さな戻りでカバー','0.4ATR戻ったら半分カバー。浅い逆行から純保有量を減らす。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,hedge_trigger=.4,cover_add=1,reverse_mode=1,lock_fraction=.5)),
        ('C08','深い戻りだけカバー','1.25ATR戻ったときだけカバーし、細かい波では主玉を保持。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,hedge_trigger=1.25,cover_add=1,reverse_mode=1,lock_fraction=.5)),
        ('D01','短い損失予算','初期損失予算を0.5ATR×10枚に半減し、両方向の増玉と反転を行う。',dict(stop_atr=.5,main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.5)),
        ('D02','90分で一旦撤退','両方向の増玉を使い、建玉一式の寿命を90分に制限。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.5,timeout_min=90.)),
        ('D03','米国開始前後は新規休止','両方向増玉を使い、22:15〜23:00は新しい組を始めない。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.5,us_mode=2)),
        ('D04','米国開始前は全玉整理','両方向増玉を使い、米国開始15分前から30分後は全玉を返済して待つ。',dict(main_trail=math.inf,add_mode=1,hedge_ratio=.5,cover_add=1,reverse_mode=1,lock_fraction=.5,us_mode=1)),
        ('D05','保護つき固定玉','固定10枚でも全玉利益50％保護と方向撤回を使う比較対象。',dict(reverse_mode=1,lock_fraction=.5)),
    ]
    return [dict(BASE,id=code,name=name,description=description,**changes) if not changes else
            dict(dict(BASE,**changes),id=code,name=name,description=description) for code,name,description,changes in rows]


def configs() -> list[dict]:
    """機能: ３方向状態、順方向・逆方向、30管理手法の180条件を固定する。

    引数: なし。返り値: 完全条件 (list[dict])。
    """
    out=[]
    for signal in ['M1','M2','M3']:
        for sign in [1,-1]:
            for manager in managers():
                out.append(dict(manager,id=f'{signal}_{"順" if sign==1 else "逆"}_{manager["id"]}',
                                manager=manager['id'],signal=signal,sign=sign))
    assert len(out)==180
    return out
