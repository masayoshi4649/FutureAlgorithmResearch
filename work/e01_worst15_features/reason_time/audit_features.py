"""価格特徴の全469注文を、分析実装を呼ばず保存入力から独立に検算する。"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FEATURE_PATH = HERE.parent / '価格特徴分析.json'
SOURCE_PATH = next((ROOT / 'アルゴリズム調査').glob('00046*/計算結果.json'))


def close(actual: float, expected: float) -> None:
    """機能: 浮動小数の丸めだけを許容して照合する。

    引数: actual/expected(float)。返り値: なし(None)。不一致では例外。
    """
    assert math.isclose(actual, expected, abs_tol=1e-8, rel_tol=1e-10), (actual, expected)


def main() -> None:
    """機能: 過去参照、差額分解、窓単調性と4呼値分類を全件検証する。

    引数: なし。返り値: なし(None)。
    """
    original_bytes = SOURCE_PATH.read_bytes()
    original = json.loads(original_bytes)
    features_bytes = FEATURE_PATH.read_bytes()
    features = json.loads(features_bytes)
    book = json.loads((HERE.parent / 'book/板特徴注文.json').read_text(encoding='utf-8'))
    book_by_key = {(o['session'], o['symbol'], o['order']): o for o in book}
    ready_all = {}
    input_hashes = {}
    for relative, expected_hash in original['sources'].items():
        if not relative.endswith('.pkl'):
            continue
        raw = (ROOT / relative).read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        assert actual_hash == expected_hash
        input_hashes[relative] = actual_hash
        ready_all.update(pickle.loads(raw))
    by_key = {(a['session'], a['symbol'], o['order']): o for a in original['sessions'] for o in a['orders']}
    assert len(features['orders']) == len(by_key) == len(book_by_key) == 469
    grouped = defaultdict(lambda: defaultdict(list))
    sum_values = defaultdict(lambda: defaultdict(float))
    window_totals = defaultdict(lambda: defaultdict(float))
    windows_monotonic = 0
    causal_rows = 0
    for row in features['orders']:
        session, symbol, number = row['session'], row['symbol'], row['order']
        original_order = by_key[session, symbol, number]
        board = book_by_key[session, symbol, number]
        ready = ready_all[session, symbol]
        times, prices = ready['time_s'], ready['last']
        d = original_order['decision_row']
        at = original_order['decision_time']
        tick, factor = float(ready['tick']), 1000 if symbol == 'TOPIX' else 10
        side, quantity = original_order['side'], original_order['quantity']
        assert row['decision_row'] == d
        assert float(times[d]) == at
        close(row['price'], float(prices[d]))
        close(row['atr'], float(ready['atr'][d]))
        # ----------------------------------------
        # 過去区間は判断行で物理的に切り、判断後の同時刻行も含めない。
        left = bisect_left(times, at - 30, 0, d + 1)
        past_prices = [float(prices[i]) for i in range(left, d + 1)]
        assert all(at - 30 <= times[i] <= at for i in range(left, d + 1))
        range30 = (max(past_prices) - min(past_prices)) / tick
        changes30 = sum(a != b for a, b in zip(past_prices, past_prices[1:]))
        close(row['range30_ticks'], range30)
        assert row['price_changes30'] == changes30
        ref = bisect_right(times, at - 30, 0, d + 1) - 1
        if ref >= 0 and at - 30 - times[ref] <= 60:
            close(row['momentum30_side_ticks'], side * (float(prices[d]) - float(prices[ref])) / tick)
        else:
            assert row['momentum30_side_ticks'] is None
        causal_rows += 1
        # ----------------------------------------
        # 保存した元の価格から即時差・15秒内の後続差を直接算出する。
        immediate = side * (float(prices[d]) - original_order['ideal_price']) * quantity * factor
        following = side * (original_order['worst_price'] - float(prices[d])) * quantity * factor
        close(row['immediate_yen'], immediate)
        close(row['following_yen'], following)
        close(row['adverse_yen'], immediate + following)
        close(row['adverse_yen'], original_order['adverse_yen'])
        close(board['threshold_gap_ticks'] * quantity * factor * tick, immediate)
        close(board['postdecision_ticks'] * quantity * factor * tick, following)
        curve = []
        close_time = ready.get('session_close', ready['limit'] + 600)
        for seconds in (0, 1, 3, 5, 10, 15):
            right = bisect_right(times, at + seconds)
            assert right > d and float(times[right - 1]) < close_time
            future_prices = [float(prices[i]) for i in range(d, right)]
            worst = max(future_prices) if side > 0 else min(future_prices)
            cost = side * (worst - original_order['ideal_price']) * quantity * factor
            close(row['window_cost'][str(seconds)], cost)
            curve.append(cost)
            window_totals[symbol][str(seconds)] += cost
        assert all(a <= b for a, b in zip(curve, curve[1:]))
        close(curve[-1], row['adverse_yen'])
        windows_monotonic += 1
        for key, value in [('immediate_yen', immediate), ('following_yen', following), ('adverse_yen', immediate + following)]:
            sum_values[symbol][key] += value
        grouped[symbol]['4呼値以上' if range30 >= 4 else '4呼値未満'].append((quantity, row['adverse_yen'], tick * factor))
    results = {}
    for symbol, groups in grouped.items():
        independently_grouped = {}
        for name, values in groups.items():
            n, units = len(values), sum(v[0] for v in values)
            total = sum(v[1] for v in values)
            weighted = sum(v[1] / v[2] for v in values) / units
            expected = features['summary'][symbol]['groups']['range30'][name]
            assert expected['n'] == n and expected['units'] == units
            close(expected['adverse_yen'], total)
            close(expected['per_unit_ticks'], weighted)
            independently_grouped[name] = {'件数': n, '枚数': units, '悪化額円': total, '1枚平均呼値': weighted}
        ratio = independently_grouped['4呼値以上']['1枚平均呼値'] / independently_grouped['4呼値未満']['1枚平均呼値']
        for key, value in sum_values[symbol].items():
            close(features['summary'][symbol][key], value)
        close(sum_values[symbol]['adverse_yen'], original['totals'][symbol]['adverse_yen'])
        for seconds, value in window_totals[symbol].items():
            close(features['summary'][symbol]['window_cost'][seconds], value)
        # ----------------------------------------
        # 週を分ける・最大悪化だけ除外する補助検査も同じ計算で照合する。
        own = [row for row in features['orders'] if row['symbol'] == symbol]
        largest_key = max(own, key=lambda row: row['adverse_yen'])
        robustness = {}
        subsets = {'09/21〜09/25': [row for row in own if row['session'][:10] <= '2026-09-25'],
                   '09/28〜10/02': [row for row in own if row['session'][:10] >= '2026-09-28'],
                   '最大悪化1注文を除外': [row for row in own if row is not largest_key]}
        for name, subset in subsets.items():
            values = {}
            for label in ['low', 'high']:
                part = [row for row in subset if (row['range30_ticks'] >= 4) == (label == 'high')]
                denominator = sum(row['quantity'] for row in part) * (500 if symbol == 'TOPIX' else 100)
                average = sum(row['adverse_yen'] for row in part) / denominator
                expected = features['summary'][symbol]['range_robustness'][name][label]
                assert expected['n'] == len(part)
                close(expected['per_unit_ticks'], average)
                values[label] = average
            ratio_check = values['high'] / values['low']
            close(features['summary'][symbol]['range_robustness'][name]['ratio'], ratio_check)
            robustness[name] = ratio_check
        results[symbol] = {'30秒値幅分類': independently_grouped, '高変動群の悪化倍率': ratio,
                           '悪化内訳円': dict(sum_values[symbol]), '時間窓別悪化額円': dict(window_totals[symbol]),
                           '週別と最大除外の倍率': robustness}
    output = {'全合格': True, '検証注文数': 469, '判断行以前の参照一致注文数': causal_rows,
              '0_1_3_5_10_15秒窓の単調性成立注文数': windows_monotonic,
              '板独立分析との即時後続差の全注文一致': True,
              '元の370000円と161200円の一致': True, '結果': results,
              '注記': '0秒の窓には判断行以後の同じ価格時刻の行を含む。即時差と同義ではない。',
              '原本SHA256': hashlib.sha256(original_bytes).hexdigest(),
              '価格特徴SHA256': hashlib.sha256(features_bytes).hexdigest(), '入力SHA256': input_hashes}
    (HERE / '価格特徴独立監査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
