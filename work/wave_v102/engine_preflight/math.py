"""停止線据置と初期幅余裕の草案を、注文再生なしの有理数だけで反証する。"""

from fractions import Fraction
import hashlib
import json
from math import ceil, floor
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TARGET = HERE / '停止線据置と初期幅余裕の結果前数理.json'
F = Fraction
TICK = F(1, 2)
VALUE = F(1000)
ENTRY = F(5000)
INITIAL_WIDTH = F(5)
TRAIL_WIDTH = F(20)
FEE_UNIT = F('41.8')


def digest(path: Path) -> str:
    """
    機能: 読取専用の根拠資料と検査自身の指紋を計算する。
    引数: path (Path) は既存ファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def order_fee(quantity: int) -> int:
    """
    機能: 純数学例の一注文手数料を整数円へ切り捨てる。
    引数: quantity (int) は実約定したと仮定する正の枚数。
    返り値: int。TOPIXミニの数量別片道料金。
    """
    assert quantity > 0
    return floor(quantity * FEE_UNIT)


def protective_round(price: Fraction, side: int) -> Fraction:
    """
    機能: 価格全体を予算又は費用床の保護側へ呼値で丸める。
    引数: price (Fraction)、side (int、買い1又は売り-1)。
    返り値: Fraction。買いは切上げ、売りは切下げした全体価格。
    """
    assert side in (-1, 1)
    return (ceil(price / TICK) if side == 1 else floor(price / TICK)) * TICK


def net_at(price: Fraction, side: int, quantity: int,
           entry_cash: Fraction, fees: Fraction) -> Fraction:
    """
    機能: 仮定した全量清算価格で実建値金額と全費用を差し引く。
    引数: price/entry_cash/fees (Fraction)、side/quantity (int)。
    返り値: Fraction。親内相殺後の純数学上の費用後損益。
    """
    return side * (quantity * VALUE * price - entry_cash) - fees


def merged_lines(side: int, quantity: int, cash: Fraction, fees: Fraction,
                 risk: Fraction, old_stop: Fraction, peak: Fraction,
                 active: bool) -> dict:
    """
    機能: 101の数式を有理数で独立に表し、R0線と全費用床を既存線へ合成する。
    引数: side/quantity (int)、cash/fees/risk/old_stop/peak (Fraction)、active (bool)。
    返り値: dict。予算線・費用床・有効線。費用が予算を超えても差額をゼロへ丸めない。
    実エンジンを呼ばず、入力系列・約定順・支持資格の正しさを認定しない。
    """
    weighted = cash / (quantity * VALUE)
    budget = protective_round(weighted - side * (risk - fees) / (quantity * VALUE), side)
    fee_line = protective_round(weighted + side * fees / (quantity * VALUE), side) + side * TICK
    initial_line = ENTRY - side * INITIAL_WIDTH
    trail_line = peak - side * TRAIL_WIDTH
    candidates = [old_stop, initial_line, trail_line, budget]
    if active:
        candidates.append(fee_line)
    effective = max(candidates, key=lambda price: side * price)
    return dict(budget=budget, fee_line=fee_line, effective=effective,
                weighted=weighted, initial_line=initial_line, trail_line=trail_line)


def reflect(price: Fraction, side: int) -> Fraction:
    """
    機能: 買いの価格例を同じ建値中心の売りへ反射する。
    引数: price (Fraction)、side (int、買い1又は売り-1)。
    返り値: Fraction。費用を保持した方向対称の価格。
    """
    return ENTRY + side * (price - ENTRY)


def plain(value):
    """
    機能: 純数理の辞書を日本語JSONで保存できる数値へ変換する。
    引数: value (Fraction又はdict/list/tuple又はJSON互換値)。
    返り値: JSON互換値。整数と分母が2の倍数の価格を有限値で保存する。
    """
    if isinstance(value, Fraction):
        return int(value) if value.denominator == 1 else float(value)
    if isinstance(value, dict):
        return {name: plain(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def cases() -> list[dict]:
    """
    機能: 結果を見る前の五例を買いと売りへ反射して判定する。
    引数: なし。
    返り値: list[dict]。10方向例の期待値と検算事実。実売買損益ではない。
    """
    risk = INITIAL_WIDTH * VALUE + order_fee(1) * 2
    fees = F(order_fee(1) * 2 + order_fee(2))
    assert risk == 5082 and fees == 165
    rows = [
        ('現在利益が正でも旧線で予算超過', F(4995), F(5015), F('5015.5'), F(5015), False,
         F('5005.5'), F('5008.5'), F('5005.5'), F(-25665), False),
        ('予算合格でも起動済み費用床が寄る', F(5016), F(5036), F('5036.5'), F(5036), True,
         F(5016), F(5019), F(5019), F(-4665), False),
        ('固定予算と費用床の双方が据置可能', F(5030), F(5050), F('5050.5'), F(5050), True,
         F(5023), F(5026), F(5030), F(9335), True),
        ('判断時の予定追加は据置可能', F(5015), F(5020), F('5020.5'), F(5035), True,
         F(5008), F(5011), F(5015), F(9335), True),
        ('次正常約定の悪化で実線が寄る', F(5015), F(5035), F('5035.5'), F(5035), True,
         F('5015.5'), F('5018.5'), F('5018.5'), F(-5665), False),
    ]
    output = []
    for label, old, quote, addition, peak, active, expected_budget, expected_fee, expected_stop, expected_net, expected_t1 in rows:
        paired = []
        for side in (1, -1):
            stop, liquidation = reflect(old, side), reflect(quote, side)
            add, price_peak = reflect(addition, side), reflect(peak, side)
            cash = (ENTRY + add) * VALUE
            actual = merged_lines(side, 2, cash, fees, risk, stop, price_peak, active)
            at_old = net_at(stop, side, 2, cash, fees)
            assert actual['budget'] == reflect(expected_budget, side)
            assert actual['fee_line'] == reflect(expected_fee, side)
            assert actual['effective'] == reflect(expected_stop, side)
            assert at_old == expected_net
            budget_allowed = at_old >= -risk
            full_allowed = side * (actual['effective'] - stop) == 0
            assert full_allowed == expected_t1
            assert not full_allowed or budget_allowed
            assert net_at(actual['budget'], side, 2, cash, fees) >= -risk
            assert side * (actual['effective'] - stop) >= 0
            if active:
                assert net_at(actual['fee_line'], side, 2, cash, fees) >= 2 * VALUE * TICK
            current_net = net_at(liquidation, side, 1, ENTRY * VALUE, F(order_fee(1) * 2))
            proposed_net = net_at(liquidation, side, 2, cash, fees)
            assert current_net >= 0 and proposed_net >= 0
            if label == '予算合格でも起動済み費用床が寄る':
                assert budget_allowed and not full_allowed
                assert side * (actual['budget'] - stop) == 0
                assert side * (actual['fee_line'] - stop) == 3
            paired.append(dict(例=label, 方向='買い' if side == 1 else '売り', 初回価格=ENTRY,
                旧有効線=stop, 清算気配=liquidation, 追加価格=add, 既存価格ピーク=price_peak,
                現在利益=current_net, 追加後現在利益=proposed_net, 初回R0=risk, 全費用=fees,
                旧線での追加後損益=at_old, 旧線での予算条件=budget_allowed, 費用床起動済み=active,
                予算線=actual['budget'], 費用床=actual['fee_line'], 合成線=actual['effective'],
                T1判断条件=full_allowed, 清算気配から合成線まで=side * (liquidation-actual['effective'])))
        assert paired[0]['清算気配から合成線まで'] == paired[1]['清算気配から合成線まで']
        assert paired[0]['旧線での追加後損益'] == paired[1]['旧線での追加後損益']
        output.extend(paired)
    return output


def thresholds() -> dict:
    """
    機能: 余裕条件をB×初回固定Sで比較し、幅の丸めや将来最大利益を混ぜない。
    引数: なし。
    返り値: dict。数学等号27件、非整数呼値の幅、最小Sでの旧幅同値を検算する。
    """
    outcomes = []
    for width in (F(1), F('2.5'), F(5)):
        for multiple in (F(1, 2), F(1), F(2)):
            required = multiple * width
            for offset in (-TICK / 2, F(0), TICK / 2):
                distance = required + offset
                accepted = distance >= required
                assert accepted == (offset >= 0)
                outcomes.append(dict(初回S=width, 倍率B=multiple, 数学閾値=required,
                                     距離=distance, 受理=accepted))
    half_odd = F('2.5') / 2
    assert half_odd == F('1.25')
    assert not F(1) >= half_odd and F('1.5') >= half_odd
    assert F(1) / 2 == TICK and F(1) == 2 * TICK
    return dict(等号と両側の数学検査=outcomes, 未丸め閾値=half_odd,
                呼値上の1幅は拒否=True, 呼値上の1_5幅は受理=True,
                最低2呼値のSでは半Sが旧1呼値と同値=True,
                最低2呼値のSではSが旧2呼値と同値=True,
                注記='非格子の等号例は数学境界。正常板系列の再生ではない。価格全体の保護丸めと余裕閾値の無丸めは別処理。')


# ----------------------------------------


def main() -> None:
    """
    機能: 根拠の開始終端SHAを固定し、売買実装前の小さな数理証跡だけを保存する。
    引数: なし。
    返り値: None。102の売買コード、損益再生、主の確定を行わない。
    """
    assert not TARGET.exists(), '既存の結果前数理証跡は上書きしません'
    paths = [Path(__file__), ROOT / 'work/wave_v101/engine.py',
             ROOT / 'work/wave_v101/audit/math_oracle.py', ROOT / 'work/wave_v101/catalog.py',
             ROOT / 'work/wave_v101/実装前の仕様明確化.json',
             ROOT / 'work/wave_v102/結果前の設計草案.json']
    begin = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    plan = json.loads(paths[-1].read_text(encoding='utf-8'))
    assert plan['新売買実装'] == plan['正式新損益'] == plan['現在API取得'] == plan['実注文'] == 0
    assert plan['金融成功の認定'] is False
    examples = cases()
    margins = thresholds()
    assert len(examples) == 10 and len(margins['等号と両側の数学検査']) == 27
    end = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    assert begin == end
    proof = dict(全合格=True, 純数理全合格=True, 結果前検査=True,
                 純Fraction例数=5, 買売反射後の方向例数=10, 余裕等号と両側検査数=27,
                 草案主は未確定=True, 売買実装は未実装=True, 正式102損益=0,
                 実データ損益読取=0, 凍結101ソース変更=0, 報告101変更=0, API取得=0, 実注文=0,
                 数学例=examples, 初期幅余裕=margins,
                 T1の完全条件='現在通常追尾更新後の旧有効線Lに対して、追加Q・費用・価格全体で丸めたR0線・起動済み費用床を合成したL\'のside×(L\'−L)=0。旧線net>=−R0だけでは不十分。',
                 実約定悪化の反例='判断時bid5020/ask5020.5、既存peak5035・旧線5015なら据置可。次正常bid5035/ask5035.5ではpeak更新なしでも実予算線5015.5、費用床5018.5となる。未来取消せず実約定から全線を再計算する必要がある。売りへ反射して同じ。',
                 予算の限界='R0は理論停止線の数理予算。次気配の実返済価格又はギャップによる実損失上限を保証しない。',
                 反証範囲='有理数での線と判定だけ。原板系列、現在支持、未知源復帰、予約競合、成行約定順の実エンジン検査は未実施。',
                 因果範囲='将来MFEや損益で入口を選ばない。草案9/30事例は成功保証として使わない。',
                 開始と終端の全依存SHA一致=True, 開始SHA256=begin, SHA256=end)
    TARGET.write_text(json.dumps(plain(proof), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 方向例=10, 閾値境界=27,
                         証跡=str(TARGET.relative_to(ROOT)), 証跡SHA256=digest(TARGET),
                         売買実装=0, 正式102損益=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
