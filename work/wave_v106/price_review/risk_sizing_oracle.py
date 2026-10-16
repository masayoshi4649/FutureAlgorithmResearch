"""数量・分割返済・料金の独立算術を人工だけで固定する。"""

from decimal import Decimal, ROUND_FLOOR
from itertools import product
from pathlib import Path
import hashlib
import json
import math


HERE = Path(__file__).resolve().parent
VALUE = {'TOPIX': 1000, 'NK225': 10}
RATE = {'TOPIX': Decimal('41.8'), 'NK225': Decimal('11')}
CAP = {'TOPIX': 5, 'NK225': 10}
LOSS = {'TOPIX': 5000., 'NK225': 2000.}


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 独立した十進料金規則で注文一つの片道料を計算する。
    引数: quantity(int)は0以上の実枚数、symbol(str)は商品。
    返り値: intは円未満を切り捨てた料金。原入力及び実装関数を呼ばない。
    """
    assert type(quantity) is int and quantity >= 0 and symbol in RATE
    return int((Decimal(quantity)*RATE[symbol]).to_integral_value(rounding=ROUND_FLOOR))


def sized_quantity(atr: float, bid: float, ask: float, remaining: float, symbol: str) -> dict:
    """
    機能: 公開時の既知値だけから予定額を払える最大整数数量を独立列挙する。
    引数: atr/bid/ask/remaining(float)は当時値、symbol(str)は商品。
    返り値: dictは既知、最大q、各数量予定額。残予算の実口座生成は別監査する。
    """
    assert symbol in CAP
    if not (all(math.isfinite(v) for v in (atr,bid,ask,remaining)) and atr > 0 and 0 < bid < ask):
        return dict(known=False,quantity=None,amounts=[])
    amount = (atr+ask-bid)*VALUE[symbol]
    if not math.isfinite(amount):
        return dict(known=False,quantity=None,amounts=[])
    costs = [q*amount+2*fee(q,symbol) for q in range(1,CAP[symbol]+1)]
    if not all(math.isfinite(v) for v in costs):
        return dict(known=False,quantity=None,amounts=[])
    q = max([0]+[i+1 for i,v in enumerate(costs) if v <= remaining])
    return dict(known=True,quantity=q,amounts=costs)


def scaled_returns(real: int, virtual: int, pieces: tuple[int,...]) -> tuple[int,...]:
    """
    機能: 影の累積返済数を実初回数量へ整数演算で写像する。
    引数: real/virtual(int)は初期数量、pieces(tuple[int,...])は影の完結返済列。
    返り値: tuple[int,...]は今回ごとの実返済数。0枚は注文を作らない。
    """
    assert 0 <= real <= virtual and virtual > 0 and all(x > 0 for x in pieces) and sum(pieces)==virtual
    closed=0; previous=0; result=[]
    for x in pieces:
        closed+=x; target=real*closed//virtual; result.append(target-previous); previous=target
    return tuple(result)


def partitions(quantity: int):
    """
    機能: 正整数の全順序付き分割を人工生成する。
    引数: quantity(int)は1以上の影枚数。
    返り値: generator[tuple[int,...]]は合計がquantityの返済列。
    """
    assert quantity > 0
    for cut in product((False,True),repeat=quantity-1):
        pieces=[]; held=1
        for flag in cut:
            if flag: pieces.append(held); held=1
            else: held+=1
        yield tuple(pieces+[held])


def main() -> None:
    """
    機能: 実装未接続の人工契約を独立算術で検査し、非金融証跡を保存する。
    引数: なし。原板・既知資料・エンジン・金融処理を使用しない。
    返り値: Noneは人工証跡。実装合格又は戦略有効性を表さない。
    """
    checks=0; split_count=0; boundaries=[]
    for virtual in range(1,11):
        for pieces in partitions(virtual):
            for real in range(virtual+1):
                observed=scaled_returns(real,virtual,pieces)
                assert sum(observed)==real and all(q >= 0 for q in observed)
                cumulative=0; actual=0
                for part,q in zip(pieces,observed):
                    cumulative+=part; actual+=q
                    assert actual==real*cumulative//virtual and actual <= real
                    checks+=1
                split_count+=1
    assert scaled_returns(3,5,(2,1,2))==(1,0,2)
    assert scaled_returns(1,5,(2,3))==(0,1)
    assert fee(3,'TOPIX')==125 and fee(1,'TOPIX')+fee(2,'TOPIX')==124
    assert fee(3,'TOPIX')+fee(1,'TOPIX')+fee(2,'TOPIX')==249
    for symbol in CAP:
        for q in range(1,CAP[symbol]+1):
            atr=1.; bid=100.; ask=100.5 if symbol=='TOPIX' else 110.
            amount=q*(atr+ask-bid)*VALUE[symbol]+2*fee(q,symbol)
            exact=sized_quantity(atr,bid,ask,amount,symbol)
            under=sized_quantity(atr,bid,ask,math.nextafter(amount,-math.inf),symbol)
            assert exact['quantity']==q and under['quantity']==q-1
            boundaries.append(dict(商品=symbol,数量=q,予定額=amount,等値受付=q,直前浮動値受付=q-1)); checks+=2
        for values in ((0.,100.,101.,1.),(math.nan,100.,101.,1.),(1.,100.,100.,1.),
                       (1.,101.,100.,1.),(1.,100.,math.inf,1.),(1.,100.,101.,math.nan)):
            assert not sized_quantity(*values,symbol)['known']; checks+=1
        zero=sized_quantity(1.,100.,101.,0.,symbol)
        assert zero['known'] and zero['quantity']==0; checks+=1
    # ----------------------------------------
    # 利益目標と赤字境界が等しくても、少額黒字の混在だけで平均補填は不成立になる。
    gains=[5000.,1000.,500.]; average=sum(gains)/len(gains); loss=4000.
    assert loss <= LOSS['TOPIX'] and loss > average
    proof=dict(全合格=True,種別='独立算術の非金融契約。新engine実装の合格又は戦略成績ではない。',
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        累積返済分割組合せ数=split_count,算術確認数=checks,予定額厳密境界=boundaries,
        返済例=dict(影=[2,1,2],影初回=5,実初回=3,実返済=[1,0,2],実新規料=125,実返済料=124,実料金合計=249),
        平均補填反例=dict(黒字収支=gains,平均黒字=average,赤字=loss,利益目標=5000.,損失予算=5000.,補填可能=False),
        実装接続=False,原入力=0,原板=0,NPZ=0,API=0,金融=0)
    output=HERE/'risk_sizing_累積返済と料金及び平均補填の独立算術人工.json'
    assert not output.exists()
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,算術確認数=checks,分割数=split_count),ensure_ascii=False))


if __name__=='__main__': main()
