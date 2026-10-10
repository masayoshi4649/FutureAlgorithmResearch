"""注文単位料金と同一ネット建玉経路の両建てを人工例で独立確認する。"""

from __future__ import annotations

from decimal import Decimal,ROUND_FLOOR
import hashlib
import importlib.util
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
PATH=HERE.parent/'medium/fees.py'
SPEC=importlib.util.spec_from_file_location('fee_v60',PATH)
FEES=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FEES)


def portfolio(symbol: str,orders: list,marks: list) -> list:
    """機能: 売買の現金変化とネット保有量から資産を計算する。

    引数: symbol(str)、orders(list[tuple]) は(行,方向,枚数,価格)、marks(list[float])。
    返り値: 各行の現金・ネット枚数・資産を持つ一覧(list[dict])。
    """
    value=FEES.instrument(symbol)['value']
    cash=0.;position=0;fees=0;out=[]
    for i,mark in enumerate(marks):
        for index,side,quantity,price in orders:
            if index==i:
                cost=FEES.order_fee(symbol,quantity)
                cash-=side*quantity*price*value+cost
                position+=side*quantity;fees+=cost
        out.append(dict(現金=cash,ネット枚数=position,資産=cash+position*mark*value,累積料金=fees))
    return out


def main() -> None:
    """機能: 整数料金と両建て比較の人工会計を保存する。

    引数: なし。
    返り値: なし(None)。実相場損益・原本・APIは使わない。
    """
    checked=0;proofs=[]
    for symbol,unit,maximum in (('TOPIX','41.8',10),('NK225','11',20)):
        for qty in range(1,maximum+1):
            expected=int((Decimal(unit)*qty).to_integral_value(rounding=ROUND_FLOOR))
            assert FEES.order_fee(symbol,qty)==expected
            checked+=1
        for invalid in (0,-1,1.5,True):
            try:
                FEES.order_fee(symbol,invalid)
            except ValueError:
                checked+=1
            else:
                raise AssertionError('不正枚数を受理しました')
        q=maximum;cover=maximum//2
        marks=[100.,90.,85.,80.,95.]
        # ----------------------------------------
        # 建玉の新規・返済ラベルは異なるが、同じネット経路なら同じキャッシュフローとなる。
        hedge=[(0,1,q,100.),(1,-1,cover,90.),(3,1,cover,80.),(4,-1,q,95.)]
        reduction=[(0,1,q,100.),(1,-1,cover,90.),(3,1,cover,80.),(4,-1,q,95.)]
        a=portfolio(symbol,hedge,marks);b=portfolio(symbol,reduction,marks)
        assert a==b and a[-1]['ネット枚数']==0
        base=portfolio(symbol,[],[100.])
        extra=portfolio(symbol,[(0,1,q,100.),(0,-1,q,100.)],[100.])
        assert extra[0]['ネット枚数']==0
        assert extra[0]['資産']-base[0]['資産']==-2*FEES.order_fee(symbol,q)
        proofs.append(dict(銘柄=symbol,同じネット経路の両建てと減量の全行一致=True,
                           同一価格の追加相殺注文による資産減少円=2*FEES.order_fee(symbol,q),
                           比較経路=a))
    evidence=dict(合格=True,料金検査数=checked,機構検査=proofs,
                  限定='同じ売買方向・枚数・価格・注文単位なら両建てと減量の手数料も一致。余分な相殺注文だけが料金を増やす。',
                  売買結果参照=False,料金コードSHA256=hashlib.sha256(PATH.read_bytes()).hexdigest())
    (HERE/'手数料と両建ての独立合成監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'合格':True,'料金検査数':checked,'両建て比較数':len(proofs)},ensure_ascii=False))


if __name__=='__main__':
    main()
