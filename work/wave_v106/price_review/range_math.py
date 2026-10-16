"""レンジ候補の料金後余地を、未読損益に依存せず呼値・整数料金から点検する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent


def order_fee(qty: int, per_contract: str) -> int:
    """
    機能: 注文単位の片道料金を円単位で切り捨てる。
    引数: qty(int)は枚数、per_contract(str)は税込片道料金。
    返り値: intは当該注文料金。別注文を先に合算しない。
    """
    return int((Decimal(qty)*Decimal(per_contract)).to_integral_value(rounding=ROUND_FLOOR))


def planned(side: int, qty: int, multiplier: int, fee: int,
            entry: float, target: float, stop: float) -> dict:
    """
    機能: 丸め後の固定価格から、予定手数料後利益と損失を測る。
    引数: side/qty/multiplier/fee(int)、entry/target/stop(float)は当時固定値。
    返り値: dictは予定RR。判断後の実約定価格を保証しない。
    """
    profit = side*(target-entry)*qty*multiplier-2*fee
    loss = side*(entry-stop)*qty*multiplier+2*fee
    return {'料金後予定利益':profit,'料金込み予定損失':loss,'予定RR':profit/loss if loss > 0 else None,
        'RR1_25以上': loss > 0 and profit >= 1.25*loss}


def main() -> None:
    """
    機能: quarter上端の不足・狭幅の不参加・丸め差・将来gapを純数学で確認する。
    引数: なし。正式sourceや金融値を用いない。
    返り値: Noneは料金尺度と小人工例を保存する。
    """
    rows = []; checks = 0
    for symbol,qty,tick,multiplier,fee_str in [('TOPIX',5,.5,1000,'41.8'),('NK225',10,10.,10,'11')]:
        fee = order_fee(qty,fee_str); cash_tick = qty*tick*multiplier; c = 2*fee/cash_tick
        assert fee == (209 if symbol == 'TOPIX' else 110); checks += 1
        for side in (-1,1):
            for width,margin,x in [(4,1,0.),(6,1,0.),(8,2,0.),(40,1,10.)]:
                lower = 100.5*tick; upper = lower+width*tick; centre = (lower+upper)/2
                mid = lower+x*tick if side > 0 else upper-x*tick
                entry = mid+side*tick/2
                target = (math.ceil(centre/tick) if side > 0 else math.floor(centre/tick))*tick
                stop = (math.floor((lower-margin*tick)/tick) if side > 0 else math.ceil((upper+margin*tick)/tick))*tick
                result = planned(side,qty,multiplier,fee,entry,target,stop)
                assert abs(entry/tick-round(entry/tick)) < 1e-10
                assert abs(target/tick-round(target/tick)) < 1e-10 and abs(stop/tick-round(stop/tick)) < 1e-10
                if width == 40: assert not result['RR1_25以上']
                if width == 4: assert not result['RR1_25以上']
                if width == 6: assert result['RR1_25以上']
                if width == 8: assert not result['RR1_25以上']
                checks += 4
                rows.append({'symbol':symbol,'方向':side,'幅tick':width,'margin_tick':margin,'quarter内位置tick':x,
                    '予定entry':entry,'丸めtarget':target,'丸めstop':stop,'実初期価格距離tick':side*(entry-stop)/tick,
                    '往復料金tick換算':c,**result})
        # ----------------------------------------
        # 標本から閾値を選ばず、丸め前の必要条件だけを単位明示で保存する。
        rows.append({'symbol':symbol,'種類':'丸め前の必要条件','近境界x0_spread1_margin2の必要span_tick':
            2.25+2.5*2+4.5*c,'式':'W >= 4.5x + 2.25s + 2.5m + 4.5c',
            'c定義':'往復整数料金/(初回枚数×1tickの金額倍率)',
            '限界':'呼値丸め後は必要幅が変わる。実sourceの判定は丸め後価格で行う。'})
    example = rows[1]
    gap = planned(-1 if example['方向'] < 0 else 1,5,1000,209,
        example['丸めtarget']+example['方向']*.5,example['丸めtarget'],example['丸めstop'])
    assert gap['料金後予定利益'] < 0; checks += 1
    output = {'全合格':True,'scope':'新R_PRICE金融前の純数学・市場結果未使用','検査数':checks,'例':rows,
        '将来約定gapの例':gap,'要点':['span>=4は活動の必要条件の一つで、RR通過の保証ではない',
            'quarter上端では中心への利幅より損切りが広く、RR1.25を満たせない',
            '予定market ask/bid又は予定limit bid/askからのRRであり、nextqの実RRは変わる',
            'target/stopの呼値丸めをRR審査前に行い、源との計算差を残す',
            '保有枚数上限は予約と未約定を含めた状態機械で別途検査する'],
        '料金モデル':'TOPIXmini5枚・NK225micro10枚、料金は各注文floor、初回全量返済を予定',
        '金融結果読取':0,'金融再生':0,'原本NPZAPI':0,
        'source_SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (HERE/'range_料金と呼値及び予定RRの独立数学.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('レンジ純数学',checks,'合格',flush=True)


if __name__ == '__main__':
    main()
