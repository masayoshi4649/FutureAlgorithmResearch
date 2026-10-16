"""凍結済みの同一売買台帳から、手数料だけを除いた親組会計の上限を求める。"""

from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCES = [('round7', 'C_GU'), ('round7', 'C_H05_S25'),
           ('round7', 'C_H05_S50'), ('round8', 'I_P00_R50_C1')]


def fee(quantity, unit):
    """
    機能: 元の注文単位を維持して片道料金の円未満を切り捨てる。
    引数: quantity(int)は数量、unit(str)は1枚の片道料金。
    返り値: intの注文全体の料金。
    """
    return int((Decimal(quantity) * Decimal(unit)).to_integral_value(rounding=ROUND_FLOOR))


def summarize(values):
    """
    機能: 親組ごとの損益を符号で分類し、金額利益割合を求める。
    引数: values(list[float])は同一親組の完了損益。
    返り値: dictの総利益、総損失、収支、勝ち負けゼロ数と金額利益割合。
    """
    a = np.asarray(values, dtype=float)
    profit = float(a[a > 1e-7].sum())
    loss = -float(a[a < -1e-7].sum())
    return {'親組数': len(a), '利益': profit, '損失': loss, '収支': float(a.sum()),
            '勝ち': int((a > 1e-7).sum()), '負け': int((a < -1e-7).sum()),
            'ゼロ': int((np.abs(a) <= 1e-7).sum()),
            '金額利益割合': profit / (profit + loss) if profit + loss else None}


def account(ledger, symbol):
    """
    機能: 保存注文から親組の現金と料金を独立計算し、全脚と既存台帳に照合する。
    引数: ledger(dict)は1口座の凍結台帳、symbol(str)はTOPIX又はNK225。
    返り値: list[dict]の親組別料金前、元料金、元料金後損益。
    """
    value, unit = (1000, '41.8') if symbol == 'TOPIX' else (10, '11')
    orders = ledger['orders']
    grouped = defaultdict(lambda: {'gross': 0.0, 'fees': 0, 'long': 0, 'short': 0})
    calculated_fees = []
    for order in orders:
        _, _, cid, side, qty, price, _, new = order
        cid, side, qty, new = int(cid), int(side), int(qty), int(new)
        order_fee = fee(qty, unit)
        calculated_fees.append(order_fee)
        row = grouped[cid]
        row['gross'] -= side * qty * price * value
        row['fees'] += order_fee
        if new:
            row['long' if side > 0 else 'short'] += qty
        else:
            row['short' if side > 0 else 'long'] -= qty
        assert row['long'] >= 0 and row['short'] >= 0
    assert np.array_equal(np.asarray(calculated_fees), ledger['fees'])
    # ----------------------------------------
    # 料金配賦後の脚だけに依存せず、実価格差・注文現金・親組を相互照合する。
    rows = []
    assert set(grouped) == {int(x[0]) for x in ledger['cycles']}
    for cid, row in grouped.items():
        assert row['long'] == row['short'] == 0
        legs = [x for x in ledger['trades'] if int(x[0]) == cid]
        gross = sum(float(x[2] * x[3] * (x[5] - x[4]) * value) for x in legs)
        assert abs(gross - sum(float(x[10] * value) for x in legs)) < 1e-6
        assert abs(gross - row['gross']) < 1e-6
        saved = [x for x in ledger['net_trades'] if int(x['組']) == cid]
        assert abs(sum(float(x['利益損失前']) for x in saved) - gross) < 1e-6
        assert abs(sum(float(x['手数料']) for x in saved) - row['fees']) < 1e-6
        net = gross - row['fees']
        assert abs(sum(float(x['収支']) for x in saved) - net) < 1e-6
        rows.append({'組': cid, '料金前': gross, '料金': row['fees'], '元収支': net})
    return rows


def main():
    """
    機能: 4ソースの固定台帳だけを読み、商品別の費用操作の上限をJSONへ保存する。
    引数: なし。市場データの再生、条件変更、注文エンジン呼出しは行わない。
    返り値: None。担当theory領域に説明付きJSONを出力する。
    """
    rows = []
    references = {}
    accounts = parents = 0
    for folder, identity in SOURCES:
        base = ROOT / 'work' / 'wave_v87' / folder / 'observed'
        ledger_path = base / 'ledgers' / f'{identity}.pkl'
        result_path = base / 'results' / f'{identity}.json'
        raw = ledger_path.read_bytes()
        ledgers = pickle.loads(raw)
        published = json.loads(result_path.read_text(encoding='utf-8-sig'))
        ledger_hash = hashlib.sha256(raw).hexdigest()
        assert ledger_hash == published['ledger_SHA256']
        assert published['model'] == 'observed' and len(ledgers) == 60
        references[str(ledger_path.relative_to(ROOT))] = ledger_hash
        references[str(result_path.relative_to(ROOT))] = hashlib.sha256(result_path.read_bytes()).hexdigest()
        grouped = defaultdict(list)
        for (session, symbol), ledger in ledgers.items():
            assert session == ledger['session'] and symbol == ledger['symbol']
            actual = account(ledger, symbol)
            grouped[symbol].extend(actual)
            accounts += 1
            parents += len(actual)
        # ----------------------------------------
        # 同じ親組を手数料前の符号でも分類し直す。元の勝敗区分を固定しない。
        for symbol in ['TOPIX', 'NK225']:
            data = grouped[symbol]
            original = summarize([x['元収支'] for x in data])
            free = summarize([x['料金前'] for x in data])
            paid = sum(x['料金'] for x in data)
            recorded = published['periods']['全30'][symbol]
            for ours, theirs in [('利益', 'campaign_profit'), ('損失', 'campaign_loss'), ('収支', 'net')]:
                assert abs(original[ours] - recorded[theirs]) < 1e-6
            assert original['親組数'] == recorded['campaigns']
            assert abs(paid - recorded['fees']) < 1e-6
            assert abs(free['収支'] - original['収支'] - paid) < 1e-6
            required = max(0, original['損失'] - original['利益'] / 4)
            less_loss = original['損失'] - free['損失']
            more_profit = free['利益'] - original['利益']
            assert abs(less_loss + more_profit - paid) < 1e-6
            free_gap = max(0, free['損失'] - free['利益'] / 4)
            closure = less_loss + more_profit / 4
            assert abs(required - free_gap - closure) < 1e-6
            rows.append({
                'ソース': identity, '商品': symbol, 'セッション数': 30,
                '元の料金後親組集計': original,
                '全料金ゼロの同一経路上限': free,
                '原注文の全料金': paid,
                '現利益固定で80パーセントに必要な損失削減額': required,
                '全料金を必要削減額へ充当できると仮定した楽観的比率': paid / required if required else None,
                '全料金ゼロで実際に減る親組総損失': less_loss,
                '現利益固定の必要削減額を実際の損失減で埋める比率': less_loss / required if required else None,
                '全料金ゼロで増える親組総利益': more_profit,
                '利益増も4対1条件へ反映した不足額改善': closure,
                '利益増も反映して不足額を埋める比率': closure / required if required else None,
                '全料金ゼロでも80パーセントに残る不足額': free_gap,
                '料金を外して負けから勝ちに変わった親組': sum(x['元収支'] < 0 < x['料金前'] for x in data),
                '料金を外して負けからゼロになった親組': sum(x['元収支'] < 0 and abs(x['料金前']) < 1e-7 for x in data),
                '全料金ゼロでも80パーセント未達': free['金額利益割合'] < .8,
            })
    result = {
        '目的': '同じ価格・同じ売買・同じ親組を固定し、注文手数料操作だけで達成できる上限を測る。',
        '結論': '4ソースとも両商品で、原注文の全料金をなくしても金額利益割合80%に届かない。差引相殺による部分的な費用削減だけでは目標を達成できない。',
        '注意': '料金ゼロは会計上の上限であり、新戦略の成績ではない。実注文の減少、次観測への遅れ、価格経路、保有数量、保険終了規則は一切変更していない。',
        '適用範囲': 'この数値上限は旧4ソースの保存済み観測現在値経路に対するもの。round10の次観測執行で価格経路が変わる場合や、Fで保有区間が変わる場合の上限としては流用しない。遅れGに対するNの費用削減上限は、完成後の遅れGと同じ経路で別途計上する。',
        '分類': '部分決済や保険脚ごとの勝率ではなく、同じ元CIDでコアと保険の全玉を合計した完了親組の金額利益割合。料金除去後は同じ親組を料金前の符号で再分類し、ゼロは勝ちに含めない。',
        '式': {
            '目標': 'P/(P+L) >= 0.8 と L <= P/4 は同値。Pは総利益、Lは総損失の絶対額。',
            '現利益固定の必要削減': 'R = L - P/4。',
            '全料金の楽観的上限': '原注文全料金Fをすべて損失削減に充当できたとしてF/R。実際は勝ち親の料金もあるため、この比率だけでは効果を過大表示する。',
            '固定利益で実際に埋まる比率': '(L-L0)/R。L0は料金ゼロで再分類した総損失。',
            '利益増も含めた正確な不足額改善': '[(L-L0)+(P0-P)/4]/R。P0は料金ゼロで再分類した総利益。利益が1円増えても許容損失の増加は0.25円なので、全料金を1対1で不足へ充当しない。',
        },
        '対象件数': {'独立照合口座': accounts, '親組': parents, '商品別集計': len(rows)},
        '監査': ['元結果の台帳SHA256一致', '全注文単位の円未満切捨て料金一致',
                 '注文現金と全決済価格差一致', '保存済み親組利益・損失・収支と一致',
                 '全親組の両方向残玉ゼロ', '料金除去後収支差が原注文全料金と一致'],
        '商品別': rows,
        '参照SHA256': references,
    }
    assert all(x['全料金ゼロでも80パーセント未達'] for x in rows)
    output = HERE / '固定4ソースの全手数料除去上限と80割合への不足.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    compact = [{
        'ソース': x['ソース'], '商品': x['商品'],
        '元利益割合': x['元の料金後親組集計']['金額利益割合'],
        '料金ゼロ割合': x['全料金ゼロの同一経路上限']['金額利益割合'],
        '必要損失削減': x['現利益固定で80パーセントに必要な損失削減額'],
        '全料金': x['原注文の全料金'],
        '楽観的充当割合': x['全料金を必要削減額へ充当できると仮定した楽観的比率'],
        '正確な不足改善割合': x['利益増も反映して不足額を埋める比率'],
    } for x in rows]
    print(json.dumps({'対象': result['対象件数'], '集計': compact}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
