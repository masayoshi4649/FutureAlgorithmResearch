"""機能: 縮小復帰対照を人工注文・気配で検算する。実損益ファイルは読まない。"""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('management_net', ROOT.parent / 'net.py')
NET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NET)


def price_order(row, decision, cid, side, quantity, reason, new, role, bid, ask):
    """機能: 買ask・売bidの人工注文1件を作成する。

    引数: 行/判断/組/方向/枚数/理由/新規/役割(int)、bid/ask(ndarray)。
    返り値: list[float]の9列注文。
    """
    return [row, decision, cid, side, quantity, ask[row] if side == 1 else bid[row],
            reason, new, role]


def reference_curve(orders, bid, ask, value, rate):
    """機能: 人工原本の全玉時価を単純逐次台帳で独立検算する。

    引数: orders(ndarray9列)、bid/ask(ndarray)、value/rate(float)。
    返り値: tuple(ndarray時価,ndarray買残,ndarray売残)。人工短列だけを逐次処理する。
    """
    cash = 0.0
    long = short = 0
    cursor = 0
    curve, longs, shorts = [], [], []
    previous_bid = previous_ask = 0.0
    for row in range(len(bid)):
        while cursor < len(orders) and int(orders[cursor, 0]) == row:
            order = orders[cursor]
            side, quantity, new = int(order[3]), int(order[4]), int(order[7])
            cash -= side * quantity * order[5] * value + math.floor(quantity * rate + 1e-8)
            if new:
                if side == 1:
                    long += quantity
                else:
                    short += quantity
            elif side == 1:
                short -= quantity
            else:
                long -= quantity
            cursor += 1
        if np.isfinite(bid[row]) and np.isfinite(ask[row]) and bid[row] > 0 and ask[row] >= bid[row]:
            previous_bid, previous_ask = bid[row], ask[row]
        curve.append(cash + long * previous_bid * value - short * previous_ask * value)
        longs.append(long)
        shorts.append(short)
    return np.asarray(curve), np.asarray(longs), np.asarray(shorts)


def run_case(cap, hedge, side, value, rate, tick, terminal_reason, return_cover):
    """機能: カバー再展開・残玉終了の人工例で写像、手数料、時価を検査する。

    引数: cap/hedge/side/terminal_reason(int)、value/rate/tick(float)、return_cover(bool)。
    返り値: dictの検査摘要。検査不一致はAssertionError。
    """
    times = np.arange(12, dtype=float)
    mid = (100 + side * np.array([0, 0, -1, -2, -3, -2, -3, -4, -3, -2, -1, 0])) * tick
    spread = np.array([1, 1, 2, 1, 1, 2, 1, 2, 1, 1, 1, 1], dtype=float) * tick
    bid, ask = mid - spread / 2, mid + spread / 2
    oo = [price_order(1, 0, 0, side, cap, 10, 1, 0, bid, ask),
          price_order(3, 2, 0, -side, hedge, 7, 1, 1, bid, ask)]
    if return_cover:
        oo.extend([price_order(5, 4, 0, side, hedge, 8, 0, 1, bid, ask),
                   price_order(7, 6, 0, -side, hedge, 7, 1, 1, bid, ask)])
    oo.extend([price_order(9, 8, 0, -side, cap, terminal_reason, 0, 0, bid, ask),
               price_order(9, 8, 0, side, hedge, terminal_reason, 0, 1, bid, ask)])
    source = np.asarray(oo, dtype=float)
    mapped, trades, curve, metadata = NET.pair(times, bid, ask, source, cap, value, rate)
    reference_net, _, _ = reference_curve(mapped, bid, ask, value, rate)
    reference_source, source_long, source_short = reference_curve(source, bid, ask, value, rate)
    assert np.allclose(curve, reference_net, atol=1e-8, rtol=0)
    saving = metadata['終了群の理論節約合計円']
    expected_difference = np.minimum(source_long, source_short) * spread * value
    expected_difference[9:] += saving
    assert np.allclose(curve - reference_source, expected_difference, atol=1e-8, rtol=0)
    assert abs(trades[:, 10].sum() - curve[-1]) < 1e-8
    assert trades[:, 7].sum() == metadata['新規手数料']
    assert trades[:, 8].sum() == metadata['返済手数料']
    assert metadata['最大絶対ネット保有'] <= cap
    assert metadata['終端買い保有'] == metadata['終端売り保有'] == 0
    assert metadata['完了組数'] == 1
    # ----------------------------------------
    # 途中切断は次観測から実現する判断・約定に依存しない。
    cut = 6
    prefix_source = source[source[:, 0] < cut]
    prefix = NET.pair(times[:cut], bid[:cut], ask[:cut], prefix_source, cap, value, rate)
    assert np.array_equal(prefix[0], mapped[mapped[:, 0] < cut])
    assert np.allclose(prefix[2], curve[:cut], atol=1e-8, rtol=0)
    assert prefix[3]['継続組数'] == 1
    # ----------------------------------------
    # 無効気配行では直前の有効両気配で残玉時価を評価する。
    bad_bid, bad_ask = bid.copy(), ask.copy()
    bad_bid[4] = bad_ask[4] = np.nan
    bad = NET.pair(times, bad_bid, bad_ask, source, cap, value, rate)
    independent_bad, _, _ = reference_curve(bad[0], bad_bid, bad_ask, value, rate)
    assert np.allclose(bad[2], independent_bad, atol=1e-8, rtol=0)
    return {'上限': cap, '保険枚数': hedge, '元方向': side, '再カバー': return_cover,
            '終了理由': terminal_reason, '最終節約円': saving,
            '注文数': len(mapped), '決済明細数': len(trades), '全合格': True}


def main():
    """機能: 両商品・両方向・不均等配賦・終了理由1〜6を検査して保存する。

    引数: なし。
    返り値: None。理論フォルダに縮小復帰対照の人工検査.jsonを保存する。
    """
    rows = []
    for cap, value, rate, tick in ((10, 1000., 41.8, .5), (20, 10., 11., 10.)):
        for hedge in (cap // 2, cap, 3):
            for side in (-1, 1):
                for terminal_reason in range(1, 7):
                    for return_cover in (False, True):
                        rows.append(run_case(cap, hedge, side, value, rate, tick,
                                             terminal_reason, return_cover))
    # ----------------------------------------
    # 注文のない場合も価格を先読みせずゼロ時価を返す。
    empty = NET.pair(np.arange(3), np.array([np.nan, 1., 2.]),
                     np.array([np.nan, 2., 3.]), np.empty((0, 9)), 10, 1000., 41.8)
    assert np.array_equal(empty[2], np.zeros(3))
    result = {'人工例数': len(rows), '各例検査': ['現金時価', '元両建てとの差額',
              'FIFO料金完全配賦', '上限', '途中切断', '無効気配継続'],
              '全合格': True, '空注文検査合格': True, '人工例': rows}
    (ROOT / '縮小復帰対照の人工検査.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'人工例数': len(rows), '全合格': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
