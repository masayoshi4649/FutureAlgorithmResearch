"""早期候補と通常担当の接続を、人工的な競合と全返済で確認する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

from audit139 import compare, ledger
import common139
from run_early139 import joined
from test_adapter139 import source
from test_audit139 import fixture, prices


HERE = Path(__file__).resolve().parent
CHECKS = []


def check(condition, label):
    """
    機能: 事前に決めた接続規則へ照合する。
    引数: condition(bool)、label(str)は結果と内容。
    返り値: None。不一致の場合は例外。
    """
    assert bool(condition), label
    CHECKS.append(label)


def actual_source(data, items, symbol):
    """
    機能: 通常担当の人工通知へ商品別の実注文手数料を付ける。
    引数: data(dict)、items(list[tuple])、symbol(str)。
    返り値: ndarrayは既存通常担当として採用できる十列注文。
    """
    orders = source(data, items)
    orders[:, 9] = orders[:, 4]*common139.product(symbol)['fee_tenths']//10
    return orders


def execute(data, base, candidates, config, symbol='NK225'):
    """
    機能: 早期と通常を接続し、全売買を独立会計で点検する。
    引数: data/config(dict)、base/candidates(ndarray)、symbol(str)。
    返り値: tupleは全注文・見送り・独立会計。
    """
    ready = dict(time_s=data['times'], quotes=data['quotes'], atr=data['atr'],
                 market=data['market'], phase=data['phase'], window_end=70.)
    orders, skips = joined(base, candidates, ready, config, symbol)
    setting = common139.product(symbol)
    quotes = data['quotes']
    independent = ledger(orders, data['times'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                         setting['fee_tenths'], setting['multiplier'])
    actual = common139.account(orders, data['times'], quotes, '人工接続', '人工_Day', symbol)
    compare(actual, independent)
    return orders, skips, independent


def main():
    """
    機能: 早期保有と通常候補の順序・同時刻優先・上限・終端を検査する。
    引数: なし。
    返り値: None。早期接続_人工確認.jsonへ保存する。
    """
    config = common139.base_config()
    config.update(initial=2, target=2, increments=[], steps=[], stop_width=[1.],
                  exit_activation=[2.], exit_width=[1.], tighten_at=[0.])
    empty = np.empty((0, 10))
    for symbol in ('NK225', 'TOPIX'):
        d = prices(fixture(), {30: 980., 50: 1005.})
        regular = actual_source(d, [(7, 15, 14, 25, 2), (8, 40, 39, 60, 2)], symbol)
        raw = source(d, [(1, 1, 0, 10, 5), (2, 45, 44, 65, 5)])
        candidates = raw[raw[:, 7] == 1]
        orders, skips, account = execute(d, regular, candidates, config, symbol)
        check(set(orders[:, 2]) == {20001., 8.}, symbol+'・早期保有中の通常を飛ばし返済後の通常を採用')
        check({s['parent'] for s in skips} == {7, 20002}, symbol+'・通常保有中に来る後続早期も見送る')
        check(np.array_equal(orders[orders[:, 2] == 8], regular[regular[:, 2] == 8]), symbol+'・採用した通常親の全注文は固定')
        check(orders[(orders[:, 2] == 20001) & (orders[:, 7] == 0)][0, 0] == 31, symbol+'・通常の予定入口で早期玉を事後返済しない')
        check(account['max_per_side'] == 2, symbol+'・競合する担当の枚数を二重保有しない')
    # ----------------------------------------
    # 同じ原行で判断が並んだ場合は通常を先に扱い、早期は見送る。
    d = fixture()
    regular = actual_source(d, [(7, 5, 4, 20, 2)], 'NK225')
    early = source(d, [(1, 5, 4, 10, 5)])[:1]
    out, skips, _ = execute(d, regular, early, config)
    check(np.array_equal(out, regular) and skips[0]['parent'] == 20001, '同時判断では通常担当を優先')
    # ----------------------------------------
    # 早期玉が伸びない場合でも区間終端に全返済し、将来の通常入口で前倒ししない。
    raw = source(d, [(1, 1, 0, 10, 5)])[:1]
    first = actual_source(d, [(7, 20, 19, 30, 2)], 'NK225')
    second = actual_source(d, [(7, 55, 54, 60, 2)], 'NK225')
    out1, skipped1, _ = execute(d, first, raw, config)
    out2, skipped2, _ = execute(d, second, raw, config)
    check(np.array_equal(out1, out2), '未来の通常候補時刻を変えても早期出口は不変')
    check(out1[-1, 0] == 71 and out1[-1, 1] == 70 and out1[-1, 6] == 1399, '早期は予定70判断の次正常71で全返済')
    # ----------------------------------------
    # 最大十枚への追撃も上限検査を通り、予定終了で全て戻す。
    d = prices(fixture(), {2: 1040.})
    big = common139.base_config()
    big.update(initial=2, target=10, increments=[2, 2, 2, 2], steps=[.25, .5, .75, 1.],
               support_hold=2., min_after_initial=0., exit_activation=[0.], tighten_at=[0.])
    raw = source(d, [(1, 1, 0, 10, 5)])[:1]
    out, skips, account = execute(d, empty, raw, big)
    check(account['max_per_side'] == 10 and account['quantity'] == 10, '四段追加でも同時最大十枚を維持')
    check(sum(out[out[:, 7] == 0, 4]) == 10, '区間終端で最大十枚を残さず返済')
    result = dict(status='合格', count=len(CHECKS), checks=CHECKS, market_files_read=0,
                  source_sha256=hashlib.sha256((HERE/'run_early139.py').read_bytes()).hexdigest(),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'早期接続_人工確認.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='合格', count=len(CHECKS)), ensure_ascii=False))


if __name__ == '__main__':
    main()
