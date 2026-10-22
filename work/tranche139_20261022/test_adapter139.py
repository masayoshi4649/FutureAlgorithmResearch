"""主担当と補完の接続、独立出口、予定終端を人工データで監査する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import common139
from audit139 import compare, ledger
from test_audit139 import fixture, prices


HERE = Path(__file__).resolve().parent
CHECKS = []


def check(condition, label):
    """
    機能: 人工の期待結果を検査して記録する。
    引数: condition(bool)、label(str)は結果と検査名。
    返り値: None。不一致は例外。
    """
    assert bool(condition), label
    CHECKS.append(label)


def source(data, items):
    """
    機能: 元通知の新規・返済を指定した親単位で作る。
    引数: data(dict)は人工気配、items(list[tuple])は親/新規行/判断行/返済行/枚数。
    返り値: ndarrayは十列の元通知。
    """
    rows = []
    for pid, start, decision, end, amount in items:
        rows.append([start, decision, pid, 1, amount, data['quotes']['ask'][start], 1, 1, 0, 0])
        rows.append([end, end-1, pid, -1, amount, data['quotes']['bid'][end], 3, 0, 0, 0])
    return np.array(sorted(rows), float)


def execute(data, core, extra, config, symbol='NK225'):
    """
    機能: 人工通知を接続層へ渡し、本会計と独立会計を照合する。
    引数: data/config(dict)、core/extra(ndarray)、symbol(str)。
    返り値: tupleは十列注文・見送り記録・場会計。
    """
    ready = dict(time_s=data['times'], atr=data['atr'], limit=70.)
    orders, skipped = common139.replay(ready, data['quotes'], data['market'], data['phase'], core, extra, config, symbol)
    actual = common139.account(orders, data['times'], data['quotes'], '人工', '人工_Day', symbol)
    setting = common139.product(symbol)
    q = data['quotes']
    independent = ledger(orders, data['times'], q['bid'], q['ask'], q['quote_valid'],
                         setting['fee_tenths'], setting['multiplier'])
    compare(actual, independent)
    return orders, skipped, actual


def main():
    """
    機能: 独立出口の先行保有・予定終了・商品数量を人工例で点検する。
    引数: なし。
    返り値: None。人工確認_adapter.jsonへ保存する。
    """
    empty = np.empty((0, 10))
    config = common139.base_config()
    config.update(source_style='独立出口', increments=[], steps=[], stop_width=[1.],
                  exit_activation=[2.], exit_width=[1.], tighten_at=[0.])
    d = prices(fixture(), {30: 980., 50: 1005.})
    core = source(d, [(1, 1, 0, 12, 10), (2, 15, 14, 25, 10), (3, 40, 39, 60, 10)])
    out, skipped, account = execute(d, core, empty, config)
    check([s['parent'] for s in skipped] == [2], '先行玉の保有中に判断する二親目を見送る')
    check(set(out[:, 2]) == {1., 3.}, '自前損切りで全返済した後の三親目は受け付ける')
    check(out[(out[:, 2] == 1) & (out[:, 7] == 0)][0, 0] == 31, '元親12行目返済を無視し自前停止30判断31約定')
    check(out[(out[:, 2] == 3) & (out[:, 7] == 0)][0, 0] == 71, '予定終端70判断の次正常71行で必ず全返済')
    check(not np.any(out[:, 0] == 12) and not np.any(out[:, 0] == 60), '独立出口は旧親返済価格を使わない')
    # ----------------------------------------
    # 予定終端が異常気配でも次の正常気配まで予約を保持する。
    broken = prices(fixture(), {30: 980., 50: 1005.})
    broken['quotes']['quote_valid'][71] = False
    broken['quotes']['bid'][72] = np.nan
    broken['quotes']['ask'][72] = np.nan
    out, skipped, account = execute(broken, core, empty, config)
    check(out[-1, 0] == 73 and out[-1, 1] == 70 and out[-1, 6] == 1399, '予定終端の後二行が無効でも73行へ繰越す')
    # ----------------------------------------
    # TOPIX補完の五枚は維持し、旧日経十枚だけを五枚へ換算する。
    d = fixture()
    topix_extra = source(d, [(7, 5, 4, 20, 5)])
    nk_extra = source(d, [(7, 5, 4, 20, 10)])
    tx, _, txa = execute(d, empty, topix_extra, config, 'TOPIX')
    nk, _, nka = execute(d, empty, nk_extra, config, 'NK225')
    check(tx[0, 4] == nk[0, 4] == 5, '補完はTOPIX五枚維持と日経十→五枚で一致')
    check(tx[0, 9] == 209 and nk[0, 9] == 192, '補完も商品別の注文手数料を使用')
    check(set(tx[:, 2]) == {10007.} and set(tx[:, 8]) == {999.}, '補完の親IDとUIDを主担当から分離')
    # ----------------------------------------
    # 発注判断中はまだ先行保有、約定予定だけ後という候補を禁止する。
    d = prices(fixture(), {30: 980., 50: 1005.})
    crossed = source(d, [(1, 1, 0, 12, 10), (2, 32, 30, 60, 10)])
    out, skipped, account = execute(d, crossed, empty, config)
    check([s['parent'] for s in skipped] == [2], '先行返済後の予定約定でも判断時に保有中なら見送る')
    same_row = source(d, [(1, 1, 0, 12, 10), (2, 32, 31, 60, 10)])
    out, skipped, account = execute(d, same_row, empty, config)
    check(not skipped and set(out[:, 2]) == {1., 2.}, '先行返済と同じ行は返済後の新規判断として許可')
    result = dict(status='合格', checks=CHECKS, count=len(CHECKS), market_files_read=0,
                  common_sha256=hashlib.sha256((HERE/'common139.py').read_bytes()).hexdigest(),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'人工確認_adapter.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=result['status'], checks=len(CHECKS)), ensure_ascii=False))


if __name__ == '__main__':
    main()
