"""損失回数停止・管理幅・夜間静観を人工経路で確認する。"""

import copy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

import early_guard139_v2 as early_guard139
from common139 import product
from run_early139 import joined as old_joined


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def fixture(points=None, night=False, length=202, window_end=180):
    """
    機能: 値動きと時刻が指定できる人工の正常気配を作る。
    引数: points(dict/None)、night(bool)、length/window_end(int)。
    返り値: dictは既存早期接続層へ渡せる人工特徴。
    """
    clock = '17:00:00' if night else '08:45:00'
    start = datetime.fromisoformat('2026-10-22T' + clock).replace(tzinfo=ZoneInfo('Asia/Tokyo')).timestamp()
    seconds = np.arange(length, dtype=float)
    points = points or {0: 1000., length - 1: 1000.}
    anchors = sorted(points)
    middle = np.interp(seconds, anchors, [points[x] for x in anchors])
    times = start + seconds
    quotes = dict(bid=middle - .5, ask=middle + .5, quote_valid=np.ones(length, dtype=bool))
    market = np.ones((length, 12))
    market[:, 8] = times - .01
    return dict(time_s=times, quotes=quotes, atr=np.full(length, 20.), market=market,
                phase=np.ones(length, dtype=np.int64), window_start=start, candidate_until=start + window_end - 5., window_end=start + window_end)


def candidates(ready, items):
    """
    機能: 指定原行の早期新規だけを十二列で作る。
    引数: ready(dict)、items(list[tuple])は親ID・約定行・判断行・方向。
    返り値: ndarrayは十二列新規通知。
    """
    rows = []
    for pid, fill, decision, side in items:
        price = ready['quotes']['ask'][fill] if side > 0 else ready['quotes']['bid'][fill]
        rows.append([fill, decision, pid, side, 5, price, 13910, 1, 0,
                     ready['time_s'][fill], ready['time_s'][decision], 1])
    return np.asarray(rows, dtype=float).reshape(-1, 12)


def normal(ready, items, symbol='NK225'):
    """
    機能: 通常親の保存済み相当注文を十列で作る。
    引数: ready(dict)、items(list[tuple])は親・新規行・判断行・返済行・方向・枚数、symbol(str)。
    返り値: ndarrayは新規返済の十列注文。
    """
    fee = product(symbol)['fee_tenths']
    rows = []
    for pid, fill, decision, end, side, qty in items:
        opened = ready['quotes']['ask'][fill] if side > 0 else ready['quotes']['bid'][fill]
        closed = ready['quotes']['bid'][end] if side > 0 else ready['quotes']['ask'][end]
        rows.extend([[fill, decision, pid, side, qty, opened, 1, 1, 0, qty * fee // 10],
                     [end, end - 1, pid, -side, qty, closed, 2, 0, 0, qty * fee // 10]])
    return np.asarray(rows, dtype=float).reshape(-1, 10)


def ledger(orders, symbol):
    """
    機能: 注文費用・玉UID・方向上限・全返済を独立に点検する。
    引数: orders(ndarray)、symbol(str)。
    返り値: intは同方向最大枚数。
    """
    fee = product(symbol)['fee_tenths']
    inventory = {}
    held = {1: 0, -1: 0}
    maximum = 0
    for order in orders:
        fill, decision, parent, side, qty = map(int, order[:5])
        uid, new = int(order[8]), bool(order[7])
        key = (parent, uid)
        assert decision < fill and qty > 0 and order[9] == qty * fee // 10
        if new:
            assert key not in inventory
            inventory[key] = [side, qty]
            held[side] += qty
        else:
            previous = inventory[key]
            assert previous[0] == -side and previous[1] >= qty
            previous[1] -= qty
            held[-side] -= qty
        maximum = max(maximum, held[1], held[-1])
        assert 0 <= held[1] <= 10 and 0 <= held[-1] <= 10
    assert all(x[1] == 0 for x in inventory.values()) and held[1] == held[-1] == 0
    return maximum


def main():
    """
    機能: 因果的な損失回数、通常優先、幅変更、既知時計の静観を検査する。
    引数: なし。
    返り値: None。金融データを読まずSHA256付き結果を保存する。
    """
    checks = []

    def check(label, condition):
        """
        機能: 期待結果を検査して名称を記録する。
        引数: label(str)、condition(bool)。
        返り値: None。
        """
        assert condition, label
        checks.append(label)

    empty = np.empty((0, 10))
    c = dict(initial=1, target=1, adaptive=False, increments=[], steps=[],
             exit_activation=[0.], stop_width=[1.])
    ready = fixture({0: 1000., 1: 1000., 10: 970., 11: 970., 20: 1000., 21: 1000.,
                     30: 970., 31: 970., 40: 1000., 41: 1000., 50: 970., 51: 970., 60: 1000., 201: 1000.})
    source = candidates(ready, [(1, 1, 0, 1), (2, 6, 5, 1), (3, 21, 20, 1), (4, 41, 40, 1)])
    original_source = source.copy()
    old, _ = old_joined(empty, source, ready, c, 'NK225')
    unlimited, _ = early_guard139.joined(empty, source, ready, c, 'NK225')
    check('無制限同幅は旧接続と注文完全一致', np.array_equal(old, unlimited))
    check('候補配列を変更せず別IDへ格納', np.array_equal(source, original_source) and np.all(unlimited[:, 2] >= 20000))
    once, skips = early_guard139.joined(empty, source, ready, c, 'NK225', dict(max_early_losses=1))
    check('一敗後の早期だけ停止', set(once[:, 2]) == {20001.})
    busy = next(x for x in skips if x['parent'] == 20002)
    check('保有中に将来損失を数えない', busy['reason'] == '保有中' and busy['early_losses'] == 0)
    blocked = next(x for x in skips if x['parent'] == 20003)
    check('実返済後だけ一敗を確定', blocked['reason'] == '早期損失回数の上限' and blocked['early_losses'] == 1)
    twice, skips = early_guard139.joined(empty, source, ready, c, 'NK225', dict(max_early_losses=2))
    check('二敗で停止する場合は二親を実行', set(twice[:, 2]) == {20001., 20003.})
    check('二敗停止記録の当時回数', next(x for x in skips if x['parent'] == 20004)['early_losses'] == 2)

    # ----------------------------------------
    # 通常親を停止に巻き込まず、通常の負けを早期の回数へ混ぜない。
    base = normal(ready, [(90, 41, 40, 51, 1, 5)])
    orders, skips = early_guard139.joined(base, source, ready, c, 'NK225', dict(max_early_losses=1))
    check('早期停止後も通常担当を継続', 90. in set(orders[:, 2]))
    check('同判断行は通常を優先', next(x for x in skips if x['parent'] == 20004)['reason'] == '保有中')
    normal_first = normal(ready, [(90, 1, 0, 11, 1, 5)])
    later = candidates(ready, [(3, 21, 20, 1), (4, 41, 40, 1)])
    orders, skips = early_guard139.joined(normal_first, later, ready, c, 'NK225', dict(max_early_losses=1))
    check('通常担当の負けは早期停止へ混ぜない', 20003. in set(orders[:, 2]))
    high_normal = normal(ready, [(1010000, 1, 0, 11, 1, 5)])
    high_orders, high_skips = early_guard139.joined(high_normal, later, ready, c, 'NK225', dict(max_early_losses=1))
    check('通常補完1010000の注文を不変で通す', np.array_equal(high_orders[high_orders[:, 2] == 1010000], high_normal))
    check('通常補完1010000の損失を早期停止に数えない', 20003. in set(high_orders[:, 2]) and next(x for x in high_skips if x['parent'] == 20004)['early_losses'] == 1)
    invalid_normal = high_normal.copy()
    invalid_normal[:, 2] = 50000
    rejected = False
    try:
        early_guard139.joined(invalid_normal, later, ready, c, 'NK225')
    except AssertionError:
        rejected = True
    check('通常親が早期予約範囲へ侵入した場合は拒否', rejected)
    invalid_early = later.copy()
    invalid_early[0, 2] = 980000
    rejected = False
    try:
        early_guard139.joined(empty, invalid_early, ready, c, 'NK225')
    except AssertionError:
        rejected = True
    check('早期親の加算後IDが百万以上なら拒否', rejected)
    same = candidates(ready, [(1, 1, 0, 1), (3, 21, 20, 1)])
    orders, skips = early_guard139.joined(normal_first, same, ready, c, 'NK225', dict(max_early_losses=1))
    check('同時通常を先に採用し早期を見送る', 90. in set(orders[:, 2]) and 20001. not in set(orders[:, 2]))

    # ----------------------------------------
    # 未確定の将来損益を変えても、そこより前の見送り情報は変わらない。
    altered = copy.deepcopy(ready)
    altered['quotes']['bid'][10:] += 100.
    altered['quotes']['ask'][10:] += 100.
    changed, changed_skips = early_guard139.joined(empty, source[:2], altered, c, 'NK225', dict(max_early_losses=1))
    check('将来差替えでも保有中候補の回数不変', changed_skips[0]['early_losses'] == busy['early_losses'] == 0)
    check('将来差替えでも既知新規は不変', np.array_equal(changed[changed[:, 0] < 10], once[once[:, 0] < 10]))

    # ----------------------------------------
    # 管理幅だけを拡げ、二市場支持の原配列と初回候補は変更しない。
    width_ready = fixture({0: 1000., 9: 1000., 10: 975., 11: 975., 20: 1050., 21: 1050., 201: 1050.})
    one = candidates(width_ready, [(1, 1, 0, 1)])
    market_before = width_ready['market'].copy()
    narrow, _ = early_guard139.joined(empty, one, width_ready, c, 'NK225', dict(risk_scale=1.))
    wide, _ = early_guard139.joined(empty, one, width_ready, c, 'NK225', dict(risk_scale=2.))
    check('幅二倍は短い逆行を許容', narrow[-1, 0] == 11. and wide[-1, 0] == 181.)
    check('幅比較で初回注文を維持', np.array_equal(narrow[0], wide[0]))
    check('支持の短ATR正規化は不変', np.array_equal(width_ready['market'], market_before))
    add_ready = fixture({0: 1000., 201: 1201.})
    add_c = dict(c, initial=2, target=10, increments=[2, 2, 2, 2], steps=[.25, .5, .75, 1.])
    adds = candidates(add_ready, [(1, 1, 0, 1)])
    many, _ = early_guard139.joined(empty, adds, add_ready, add_c, 'NK225')
    single, _ = early_guard139.joined(empty, adds, add_ready, add_c, 'NK225', dict(initial_only=True))
    check('初回一枚条件は追加を行わない', np.sum(single[:, 7] == 1) == 1 and single[0, 4] == 1.)
    check('上限十枚と全返済を独立点検', ledger(many, 'NK225') == 10 and ledger(single, 'NK225') == 1)
    for symbol in ('NK225', 'TOPIX'):
        orders, _ = early_guard139.joined(empty, one, width_ready, c, symbol, dict(risk_scale=2.))
        check(symbol + 'の商品費用と全返済', ledger(orders, symbol) == 1)

    # ----------------------------------------
    # 夜の区切りは新規前に既知。静観を越える待機新規は取り消し、後半は新候補で再開する。
    night = fixture(night=True, length=19010, window_end=18900)
    gap_start, gap_end = early_guard139._gap(night, True)
    check('米国08時30分相当前後十五分', gap_start - night['window_start'] == 15300. and gap_end - night['window_start'] == 17100.)
    passive = dict(c, stop_width=[0.])
    night_candidates = candidates(night, [(1, 100, 99, 1), (2, 16000, 15999, 1), (3, 17200, 17199, 1)])
    orders, skips = early_guard139.joined(empty, night_candidates, night, passive, 'NK225', dict(event_gap=True, max_early_losses=2))
    check('前区間は静観開始で返済判断', np.any((orders[:, 1] == 15300.) & (orders[:, 0] == 15301.) & (orders[:, 7] == 0)))
    check('静観帯の新規を禁止', next(x for x in skips if x['parent'] == 20002)['reason'] == '米国指標時計帯の静観')
    check('静観終了後の新候補で再開', 20003. in set(orders[:, 2]))
    check('静観後も累積損失を維持', next(x for x in skips if x['parent'] == 20002)['early_losses'] == 1)
    crossing = candidates(night, [(1, 15301, 15299, 1)])
    crossed, skips = early_guard139.joined(empty, crossing, night, passive, 'NK225', dict(event_gap=True))
    check('静観境界を跨ぐ未約定新規は取消', len(crossed) == 0 and '取消' in skips[0]['reason'])
    normal_gap = normal(night, [(91, 16000, 15999, 17000, 1, 5)])
    usual, _ = early_guard139.joined(normal_gap, np.empty((0, 12)), night, passive, 'NK225', dict(event_gap=True))
    check('静観は通常担当を止めない', np.array_equal(usual, normal_gap))
    day_a, _ = early_guard139.joined(empty, source, ready, c, 'NK225', dict(max_early_losses=2))
    day_b, _ = early_guard139.joined(empty, source, ready, c, 'NK225', dict(max_early_losses=2, event_gap=True))
    check('昼は静観設定で注文を変えない', np.array_equal(day_a, day_b))
    check('全十二設定を事前固定', len(early_guard139.settings()) == 12)
    paths = [HERE / name for name in ('early_guard139.py', 'early_guard139_v2.py', 'test_early_guard139_v2.py', 'engine139_native.py', 'common139.py', 'run_early139.py')]
    output = dict(結果='全件合格', 確認数=len(checks), 確認=checks, 金融再生=0, API=0, 実注文=0,
                  実装={p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths})
    (HERE / 'early_guard_v2_人工確認.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(結果=output['結果'], 確認数=len(checks)), ensure_ascii=False))


if __name__ == '__main__':
    main()
