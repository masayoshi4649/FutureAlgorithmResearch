"""当時窓の独立純期待を完成診断源へ接続する。保存入力と金融は読まない。"""

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'work/e01_opportunity_trace_20261015/prepare'
OUTPUT = HERE / '当時窓と厳密結合及び分母の独立SOURCE_ONLY監査.json'
EXPECTED = {
    '厳密joinと公開符号及び当時窓接頭の純人工.json': '65cb800d28897035b51ff9f484eeab50ade455ab402a87c190f737101c4be7e8',
    '元公開と紙上継続窓の非金融一読診断計画.json': '77393676dcfa6ceb8d4a9558a18210462de3bb2ee32fb8a5bfe4fa73f859f460',
    '二cacheの小目録固定.json': '2892b5ff395ab87d13f4740e1495b3029ddad3f1f46e854dcf94db43509a5361',
}
COUNTS = Counter()


def sha(saved: bytes) -> str:
    """
    機能: 既に読んだsource又は小資料のbytesだけを指紋へ結ぶ。
    引数: saved(bytes) は明示許可範囲の内容。
    返り値: str はSHA256。元cache本文を取得しない。
    """
    return hashlib.sha256(saved).hexdigest()


def check(value: bool, label: str) -> None:
    """
    機能: 独立期待の判定を分類付きで累積し、不一致を停止する。
    引数: value(bool)、label(str) は判定と分類。
    返り値: None。不一致はAssertionError。
    """
    assert bool(value), label
    COUNTS[label] += 1


def same(left: object, right: object, label: str) -> None:
    """
    機能: 合成配列の欠測位置を保ったまま独立期待と比較する。
    引数: left/right(object)、label(str) は値と分類。
    返り値: None。不一致を零や中立に補完しない。
    """
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        np.testing.assert_array_equal(left, right, err_msg=label)
    elif isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right):
        pass
    else:
        assert left == right, (label, left, right)
    COUNTS[label] += 1


def volume_oracle(raw: dict, row: int, width: int, side: int) -> dict:
    """
    機能: 合成原行の接頭を直接走査し、出来高代理票と未知debugを独立に数える。
    引数: raw(dict)、row/width/side(int) は合成原列と終点・窓・向き。
    返り値: dict はscalarと全normalに対応する当時値。実装のcontext/cumsumは使わない。
    """
    stamp = float(raw['price_time_s'][row])
    if not math.isfinite(stamp):
        return dict(known=False, reason=2, up=0, down=0, balance=None, reference=-1, first=-1)
    high = -math.inf
    public = []
    bad = []
    directions = []
    for i in range(row + 1):
        clock = float(raw['price_time_s'][i])
        reverse = math.isfinite(clock) and clock < high
        if math.isfinite(clock) and clock > high:
            public.append(i)
        common = not math.isfinite(clock) or reverse or i == 0
        if i:
            common = common or int(raw['raw_seq'][i]) != int(raw['raw_seq'][i-1]) + 1 or not math.isfinite(float(raw['price_time_s'][i-1]))
        if math.isfinite(clock):
            high = max(high, clock)
        volume_known = bool(raw['volume_delta_usable'][i]) and int(raw['volume_reset_reason'][i]) == 0
        delta = float(raw['volume_delta'][i])
        increase = volume_known and math.isfinite(delta) and delta > 0
        last = float(raw['last'][i])
        last_ok = math.isfinite(last) and last > 0
        prior_ok = False
        if i:
            bid, ask = float(raw['bid'][i-1]), float(raw['ask'][i-1])
            prior_ok = math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask
        reason = (4 if common else 0) | (0 if volume_known else 8) | (16 if increase and not (last_ok and prior_ok) else 0)
        direction = 0
        if increase and last_ok and prior_ok and not common:
            direction = 1 if last >= ask else -1 if last <= bid else 0
        bad.append(reason)
        directions.append(direction)
    cutoff = stamp - width
    bases = [i for i in public if float(raw['price_time_s'][i]) <= cutoff]
    firsts = [i for i in public if float(raw['price_time_s'][i]) > cutoff]
    reference = bases[-1] if bases else -1
    first = firsts[0] if firsts else row + 1
    reason = 0 if bases else 1
    for flag in bad[first:row+1]:
        reason |= flag
    up = sum(value == 1 for value in directions[first:row+1])
    down = sum(value == -1 for value in directions[first:row+1])
    balance = side * (up-down) / (up+down) if reason == 0 and up+down else None
    return dict(known=reason == 0, reason=reason, up=up, down=down, balance=balance,
                reference=reference, first=first if first <= row else -1)


def fixture(zero: bool = False) -> tuple[dict, dict, dict]:
    """
    機能: 非恒等mapping、同時計、部分返済、同行撤回、未知を含む独立合成二cacheを作る。
    引数: zero(bool) は正出来高増無しの既知零票を指定する。
    返り値: tuple[dict,dict,dict] はGate型、Exit型、合成raw。保存packetを使わない。
    """
    gate = dict(schema_version=1, session='独立合成_Day', accounts={})
    exit_packet = dict(schema_version=1, session='独立合成_Day', accounts={})
    raws = {}
    n = 80
    mapping = 2 * np.arange(n, dtype=np.int64) + 1
    index = np.arange(2*n, dtype=np.int64)
    for symbol in ('TOPIX', 'NK225'):
        tick, base, qty = (.5, 4000., 5) if symbol == 'TOPIX' else (10., 70000., 10)
        clocks = (index//2).astype(float)*10.
        clocks[60:66] = 300.
        if symbol == 'NK225':
            clocks -= .125
        prices = base + tick*np.where(index < 55, index, np.where(index < 95, 110-index, index-80))
        raw = dict(raw_seq=index+1000, price_time_s=clocks, last=prices.astype(float),
                   bid=prices-tick/2, ask=prices+tick/2,
                   volume_delta=np.zeros(2*n) if zero else (index%4+1).astype(float),
                   volume_delta_usable=np.ones(2*n, bool), volume_reset_reason=np.zeros(2*n, np.uint8))
        raw['volume_delta_usable'][0] = False
        if not zero:
            raw['volume_delta'][::7] = 0.
            raw['last'][102] = np.nan
            raw['volume_delta_usable'][115] = False
            raw['volume_reset_reason'][115] = 8
        record = dict(price=raw['last'][mapping].copy(), seq=raw['raw_seq'][mapping].copy(),
                      time_s=clocks[mapping].copy(), start=0., end=1000., limit=1000., tick=tick)
        quotes = dict(bid=raw['bid'][mapping].copy(), ask=raw['ask'][mapping].copy(),
                      quote_valid=np.ones(n, bool), seq=record['seq'].copy(), time_s=record['time_s'].copy())
        quotes['quote_valid'][17] = False
        orders = [(30, 7, 1, qty, 1), (36, 7, -1, qty//2, 0), (40, 7, -1, qty-qty//2, 0),
                  (45, 9, -1, qty, 1), (52, 9, 1, qty, 0), (55, 13, 1, qty, 1),
                  (55, 13, -1, qty, 0), (58, 16, -1, qty, 1), (65, 16, 1, qty, 0)]
        feed = np.asarray([[row, row-1, cid, side, q, record['price'][row], 0, new, 0, tick*8]
                           for row, cid, side, q, new in orders], float)
        quiet = np.zeros(n, bool)
        quiet[30:33] = True
        account = dict(symbol=symbol, record=record, quotes=quotes, mapping=mapping.copy(), feed=feed,
                       quiet=quiet, quiet_force=np.zeros(n, bool), trade_features={})
        full = {}
        for width in (10, 30, 60):
            vals = [volume_oracle(raw, int(row), width, 1) for row in mapping]
            full[str(width)] = dict(known=np.asarray([v['known'] for v in vals], bool),
                reason=np.asarray([v['reason'] for v in vals], np.uint8),
                up_votes=np.asarray([v['up'] for v in vals], np.int32), down_votes=np.asarray([v['down'] for v in vals], np.int32),
                balance=np.asarray([v['balance'] if v['balance'] is not None else np.nan for v in vals], float),
                reference_raw_row=np.asarray([v['reference'] for v in vals], np.int64),
                first_vote_raw_row=np.asarray([v['first'] for v in vals], np.int64),
                candidate_raw_row=mapping.copy(), candidate_raw_seq=record['seq'].copy(), candidate_price_time_s=record['time_s'].copy())
            scalar = {}
            for row, _, side, _, new in orders:
                if not new:
                    continue
                rr = int(mapping[row])
                v = volume_oracle(raw, rr, width, side)
                scalar[row] = dict(known=v['known'], reason=v['reason'], window_seconds=width,
                    candidate_raw_row=rr, candidate_raw_seq=int(raw['raw_seq'][rr]), candidate_price_time_s=float(clocks[rr]),
                    cutoff_price_time_s=float(clocks[rr])-width, reference_raw_row=v['reference'] if v['reference'] >= 0 else None,
                    first_vote_raw_row=v['first'] if v['first'] >= 0 else None,
                    measured_up_votes=v['up'], measured_down_votes=v['down'], up_votes=v['up'] if v['known'] else None,
                    down_votes=v['down'] if v['known'] else None, direction_votes=v['up']+v['down'] if v['known'] else None,
                    balance=v['balance'])
            account['trade_features'][str(width)] = scalar
        gate['accounts'][symbol] = account
        exit_packet['accounts'][symbol] = dict(symbol=symbol, record=deepcopy(record), quotes=deepcopy(quotes), votes=full)
        raws[symbol] = raw
    return gate, exit_packet, raws


def cut(gate: dict, packet: dict, length: int) -> tuple[dict, dict]:
    """
    機能: 合成二cacheを当行まで切り、未来paper公開とscalarを除く。
    引数: gate/packet(dict)、length(int) は合成列と接頭長。
    返り値: tuple[dict,dict] は独立接頭。過去票を未来で再補完しない。
    """
    g, e = deepcopy(gate), deepcopy(packet)
    for symbol in ('TOPIX', 'NK225'):
        for account in (g['accounts'][symbol], e['accounts'][symbol]):
            for group in ('record', 'quotes'):
                account[group] = {k: v[:length].copy() if isinstance(v, np.ndarray) else v for k, v in account[group].items()}
        a = g['accounts'][symbol]
        for name in ('mapping', 'quiet', 'quiet_force'):
            a[name] = a[name][:length].copy()
        a['feed'] = a['feed'][a['feed'][:, 0] < length].copy()
        a['trade_features'] = {w: {k: v for k, v in vals.items() if k < length} for w, vals in a['trade_features'].items()}
        e['accounts'][symbol]['votes'] = {w: {k: v[:length].copy() for k, v in vals.items()}
                                        for w, vals in e['accounts'][symbol]['votes'].items()}
    return g, e


def independent_state(account: dict) -> list[dict]:
    """
    機能: 合成紙上注文を符号付き在庫として時点ごとに直接集計する。
    引数: account(dict) は合成feedとrecord。
    返り値: list[dict] は全行の方向/残量/親/PUB情報。実在庫とは呼ばない。
    """
    inventory, cid, origin, begin = 0, -1, -1, -1
    price, atr = math.nan, math.nan
    prior = (0, -1)
    output = []
    for row in range(len(account['mapping'])):
        original, withdrawn = False, False
        for order in account['feed']:
            if order[0] != row:
                continue
            if order[7] == 1:
                assert inventory == 0
                inventory = int(order[3]*order[4])
                cid, origin, price, atr = int(order[2]), row, float(order[5]), float(order[9])
                original, withdrawn = True, False
            else:
                inventory += int(order[3]*order[4])
                withdrawn = withdrawn or original
        side = int(inventory > 0)-int(inventory < 0)
        if (side, cid) != prior:
            begin, prior = row, (side, cid)
        output.append(dict(direction=side, remaining=abs(inventory), paper_parent=cid, origin_row=origin,
                           direction_start_row=begin, paper_price=price, paper_atr=atr,
                           original=original, withdrawn_same_row=withdrawn))
    return output


def price_oracle(account: dict, reference: object) -> tuple[list, list]:
    """
    機能: 独立の逐次Point窓へ合成recordを変換し、当行までの正常資格を検証する。
    引数: account(dict)、reference(module) は合成口座と旧独立純参照。
    返り値: tuple[list,list] はPoint列と各行の窓期待。価格票の実装を呼ばない。
    """
    r, q = account['record'], account['quotes']
    max_clock, max_seq = -math.inf, -1
    points = []
    for row in range(len(r['price'])):
        t, p, bid, ask, seq = float(r['time_s'][row]), float(r['price'][row]), float(q['bid'][row]), float(q['ask'][row]), int(r['seq'][row])
        normal = bool(q['quote_valid'][row]) and all(math.isfinite(v) for v in (t, p, bid, ask)) and p > 0 and 0 < bid < ask and t >= max_clock and seq > max_seq
        points.append(reference.Point(t, p, normal, seq))
        if math.isfinite(t):
            max_clock = max(max_clock, t)
        max_seq = max(max_seq, seq)
    return points, [reference.window(points, row) for row in range(len(points))]


def verify_measurement(analysis: object, price: object, volume: object, normal: object, reference: object) -> None:
    """
    機能: 独立原行票・価格窓・紙上在庫・scalar条件を完成実装と接続する。
    引数: 各module(object) は所有私有複製と独立純参照。
    返り値: None。保存cache・金融・台帳を読まない。
    """
    for zero in (False, True):
        gate, packet, raws = fixture(zero)
        analysis.strict_join(gate, packet)
        result = analysis.analyze(gate, packet)
        pairs = price.pair(gate)
        expected_prices = {s: price_oracle(a, reference) for s, a in gate['accounts'].items()}
        for symbol, account in gate['accounts'].items():
            raw = raws[symbol]
            context = volume.context(raw)
            for width in (10, 30, 60):
                observed = normal.all_normal(raw, context, account['mapping'], width)
                for name, values in packet['accounts'][symbol]['votes'][str(width)].items():
                    same(observed[name], values, '独立原行直接走査と全normal票')
                for row, scalar in account['trade_features'][str(width)].items():
                    order = account['feed'][(account['feed'][:, 0] == row) & (account['feed'][:, 7] == 1)][0]
                    actual = volume.measure(raw, context, int(account['mapping'][row]), width, int(order[3]))
                    for key, val in scalar.items():
                        same(actual[key], val, '独立元PUBの原row符号未知debug')
            state = analysis.paper_state(account)
            expected_state = independent_state(account)
            for name, values in state.items():
                same(values, np.asarray([v[name] for v in expected_state], dtype=values.dtype), '独立紙上在庫と同行順序')
            current = packet['accounts'][symbol]['votes']['60']
            observed = analysis.observe(account, current, pairs[symbol], state)
            points, own_windows = expected_prices[symbol]
            peer_symbol = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            peer_points = expected_prices[peer_symbol][0]
            cap, mult, threshold = (10, 1000, .5) if symbol == 'TOPIX' else (20, 10, .25)
            fee = math.floor(cap*41.8) if symbol == 'TOPIX' else cap*11
            for row, state_row in enumerate(expected_state):
                own = own_windows[row]
                peer = reference.peer(peer_points, points[row].clock) if points[row].normal else dict(known=False, count=0, balance=None, end_row=None)
                actual = pairs[symbol]
                for key in ('known', 'count'):
                    same(actual['own'][key][row], own[key], '独立価格窓正常cutoffと当行上限')
                same(actual['own']['balance'][row], own['balance'] if own['balance'] is not None else math.nan, '独立価格窓balance')
                same(actual['peer_known'][row], peer['known'], '独立peer厳密過去年齢')
                same(actual['peer_count'][row], peer['count'] if peer['known'] else 0, '独立peer厳密過去年齢')
                same(actual['peer_balance'][row], peer['balance'] if peer['known'] else math.nan, '独立peerbalance')
                side = state_row['direction']
                v = volume_oracle(raw, int(account['mapping'][row]), 60, side)
                vol_ok = v['known'] and v['up']+v['down'] >= 2 and v['balance'] is not None and v['balance'] >= threshold
                price_ok = side != 0 and reference.supports(own, peer, side)
                strong = side != 0 and reference.supports(own, peer, side, .75)
                q = account['quotes']
                good = bool(q['quote_valid'][row]) and all(math.isfinite(float(x)) for x in (q['bid'][row], q['ask'][row])) and 0 < q['bid'][row] < q['ask'][row]
                quote = float(q['ask'][row] if side > 0 else q['bid'][row])
                cost = float(q['ask'][row]-q['bid'][row])*cap*mult+2*fee
                cost_ok = good and cost <= .5*quote*cap*mult*.00075
                quiet = bool(account['quiet'][row] or account['quiet_force'][row])
                t = points[row].clock
                period = account['record']['start']+300 <= t < account['record']['limit']-300
                paper_ok = math.isfinite(state_row['paper_price']) and state_row['paper_price'] > 0 and math.isfinite(state_row['paper_atr']) and state_row['paper_atr'] > 0
                market = side != 0 and not quiet and t < account['record']['limit'] and period and points[row].normal and paper_ok and cost_ok
                for name, condition in (('VOL_SELECTED', vol_ok), ('PRICE_BOTH', price_ok), ('VOL_SELECTED_PRICE_BOTH', vol_ok and price_ok)):
                    same(bool(observed['window_profiles'][name][row]), condition, '独立現在volume価格profile')
                    same(bool(observed['eligible'][name][row]), market and condition, '独立市場資格と現在profile交差')
                same(bool(observed['market'][row]), market, '独立当時市場資格')
                same(int(observed['allowance'][row]), int(strong), '独立現在二価格票強支持予定許容')
                if state_row['original']:
                    expected = 93 if t >= account['record']['limit'] else 92 if quiet else 151 if state_row['withdrawn_same_row'] else 153 if not period else 96 if not (side and points[row].normal and paper_ok) else 95 if not vol_ok else 154 if not cost_ok else 0
                    same(int(observed['public_reason_without_actual_state'][row]), expected, '独立元PUB暫定拒否先後')
            item = result['accounts'][symbol]
            expected_active = sum(v['direction'] != 0 for v in expected_state)
            same(item['counts']['active_normal_observations'], expected_active, '紙上条件付き分母')
            same(item['counts']['original_publications'], 4, '元PUB分母')
            same(item['counts']['paper_direction_episodes'], 3, '紙上方向区間と同行消滅')
            for side, label in ((1, 'BUY'), (-1, 'SELL')):
                normal_summary = item['all_normal_directional_qualification'][label]
                same(normal_summary['normal_observations'], len(points), '全normal両side別群分母')
                check(expected_active < len(points), '全normal群が紙上zeroを含む')
                for name in ('VOL_SELECTED', 'PRICE_BOTH', 'VOL_SELECTED_PRICE_BOTH'):
                    masks, qualified = [], []
                    for row, point in enumerate(points):
                        v = volume_oracle(raw, int(account['mapping'][row]), 60, side)
                        vol = bool(v['known'] and v['up']+v['down'] >= 2 and v['balance'] is not None and v['balance'] >= threshold)
                        peer = reference.peer(peer_points, point.clock) if point.normal else dict(known=False, count=0, balance=None)
                        pri = reference.supports(own_windows[row], peer, side)
                        condition = vol if name == 'VOL_SELECTED' else pri if name == 'PRICE_BOTH' else vol and pri
                        market = point.normal and account['record']['start']+300 <= point.clock < account['record']['limit']-300 and not account['quiet'][row] and not account['quiet_force'][row] and point.clock < account['record']['limit']
                        masks.append(condition)
                        qualified.append(bool(condition and market))
                    details = normal_summary['profiles'][name]
                    same(details['window_qualified_observations'], sum(masks), '全normal独立直接集計')
                    same(details['qualified_with_common_market_observations'], sum(qualified), '全normal市場群分母はpaper非依存')
                    same(details['continuous_qualified_normal_runs'], sum(v and (i == 0 or not qualified[i-1]) for i, v in enumerate(qualified)), '連続区間は観測群であって独立成功でない')
                    same(details['qualified_price_clock_values'], len({p.clock for p, ok in zip(points, qualified) if ok}), '同時計観測と価格時計値の分離')


def verify_boundaries(analysis: object, price: object, volume: object, normal: object) -> None:
    """
    機能: 合成未来suffixと誤結合を攻撃し、過去判定の因果境界を独立に確認する。
    引数: 各module(object) は所有私有source。
    返り値: None。将来区間長を接頭不変とは呼ばない。
    """
    gate, packet, raws = fixture()
    full_price = price.pair(gate)
    for length in (1, 18, 31, 33, 37, 41, 46, 53, 56, 59, 66, 79):
        g, e = cut(gate, packet, length)
        analysis.strict_join(g, e)
        part_price = price.pair(g)
        for symbol in ('TOPIX', 'NK225'):
            full_state = analysis.paper_state(gate['accounts'][symbol])
            part_state = analysis.paper_state(g['accounts'][symbol])
            for key, value in part_state.items():
                same(value, full_state[key][:length], '独立十二接頭紙上state')
            full_obs = analysis.observe(gate['accounts'][symbol], packet['accounts'][symbol]['votes']['60'], full_price[symbol], full_state)
            part_obs = analysis.observe(g['accounts'][symbol], e['accounts'][symbol]['votes']['60'], part_price[symbol], part_state)
            for group in ('flags', 'window_profiles', 'eligible'):
                for key, value in part_obs[group].items():
                    same(value, full_obs[group][key][:length], '独立十二接頭現在flag')
            for key in ('volume_count', 'volume_signed', 'allowance', 'market', 'cost', 'cost_limit', 'public_reason_without_actual_state'):
                same(part_obs[key], full_obs[key][:length], '独立十二接頭公開値')
    for symbol, raw in raws.items():
        changed = deepcopy(raw)
        end = int(gate['accounts'][symbol]['mapping'][30])
        check(raw['price_time_s'][end+1] == raw['price_time_s'][end], '同時計未来原row攻撃の素材')
        changed['last'][end+1:] += 20000.
        changed['bid'][end+1:] += 10000.
        changed['volume_delta'][end+1:] = 1000000.
        for side in (-1, 1):
            same(volume.measure(raw, volume.context(raw), end, 60, side), volume.measure(changed, volume.context(changed), end, 60, side), '同clock未来raw票は候補上限外')
        mapping = gate['accounts'][symbol]['mapping'][:31]
        old = normal.all_normal(raw, volume.context(raw), mapping, 60)
        new = normal.all_normal(changed, volume.context(changed), mapping, 60)
        for key in old:
            same(old[key], new[key], '同clock未来raw全normal票上限')
        raw_nan = deepcopy(raw)
        raw_nan['price_time_s'][end] = np.nan
        prefix = {k: v[:end+1].copy() for k, v in raw_nan.items()}
        large = normal.all_normal(raw_nan, volume.context(raw_nan), mapping, 60)
        small = normal.all_normal(prefix, volume.context(prefix), mapping, 60)
        for key in large:
            same(large[key], small[key], '非有限clock未知接頭に未来窓系譜なし')
        check(not large['known'][-1] and large['reason'][-1] == 2 and large['up_votes'][-1] == large['down_votes'][-1] == 0 and large['reference_raw_row'][-1] == large['first_vote_raw_row'][-1] == -1, '非有限clock未知debugは中立票でない')
    changed = deepcopy(gate)
    for symbol, account in changed['accounts'].items():
        for field in ('price', 'time_s', 'seq'):
            if field == 'price':
                account['record'][field][31:] += 100000.
        account['quotes']['bid'][31:] += 50000.
        account['quotes']['ask'][31:] += 50000.
    altered = price.pair(changed)
    for symbol in ('TOPIX', 'NK225'):
        for key in ('known', 'count', 'balance', 'reference_row', 'normal'):
            same(full_price[symbol]['own'][key][:31], altered[symbol]['own'][key][:31], '自己同clock後半価格票を先頭へ混ぜない')
    for group, field in (('record', 'seq'), ('record', 'time_s'), ('record', 'price'), ('quotes', 'bid'), ('quotes', 'ask'), ('quotes', 'quote_valid')):
        broken = deepcopy(packet)
        value = broken['accounts']['TOPIX'][group][field]
        value[45] = not value[45] if field == 'quote_valid' else value[45] + 1
        try:
            analysis.strict_join(gate, broken)
        except AssertionError:
            COUNTS['seq時計LastBBO資格の誤join拒否'] += 1
        else:
            raise AssertionError('誤joinを受理 ' + field)
    for field in ('candidate_raw_row', 'candidate_raw_seq', 'candidate_price_time_s', 'reference_raw_row', 'first_vote_raw_row', 'measured_up_votes', 'balance'):
        broken = deepcopy(gate)
        val = broken['accounts']['TOPIX']['trade_features']['60'][45]
        val[field] = -val[field] if field == 'balance' else val[field] + 1
        try:
            analysis.strict_join(broken, packet)
        except AssertionError:
            COUNTS['元公開原row系譜又は二重符号の誤結合拒否'] += 1
        else:
            raise AssertionError('誤公開を受理 ' + field)
    for field in ('candidate_raw_row', 'candidate_raw_seq', 'candidate_price_time_s'):
        broken = deepcopy(packet)
        broken['accounts']['TOPIX']['votes']['60'][field][45] += 1
        try:
            analysis.strict_join(gate, broken)
        except AssertionError:
            COUNTS['全normal候補map原seq時計の誤結合拒否'] += 1
        else:
            raise AssertionError('誤全normalを受理 ' + field)


def main() -> None:
    """
    機能: 明示小metadataと23sourceを束縛し、独立合成だけの監査を保存する。
    引数: なし。
    返り値: None。原cache/NPZ/金融/API/共有編集は全て0。
    """
    assert not OUTPUT.exists()
    values, metadata = {}, {}
    for name, expected in EXPECTED.items():
        saved = (SOURCE/name).read_bytes()
        check(sha(saved) == expected, '根指定小metadata指紋')
        values[name] = json.loads(saved)
        metadata[name] = expected
    art = values['厳密joinと公開符号及び当時窓接頭の純人工.json']
    plan = values['元公開と紙上継続窓の非金融一読診断計画.json']
    fixed = values['二cacheの小目録固定.json']
    signatures = art['source_SHA256']
    check(len(signatures) == 23 and signatures == plan['source_SHA256'] == fixed['source_SHA256'], '私有九と参照十四の同じ最終署名')
    source_bytes = {}
    for relative, expected in signatures.items():
        check(Path(relative).suffix == '.py' and (ROOT/relative).resolve().is_relative_to(ROOT/'work'), 'source限定path')
        saved = (ROOT/relative).read_bytes()
        check(sha(saved) == expected, '完成source二十三の現在指紋')
        ast.parse(saved.decode('utf-8-sig'))
        source_bytes[relative] = saved
    check(plan['人工SHA256'] == fixed['人工SHA256'] == metadata['厳密joinと公開符号及び当時窓接頭の純人工.json'], '人工と正式計画固定接続')
    check(fixed['計画SHA256'] == metadata['元公開と紙上継続窓の非金融一読診断計画.json'], '計画と小目録固定接続')
    check(art['全合格'] and fixed['全合格'] and art['検査数'] == 509 and fixed['大型本文読取'] == fixed['金融'] == fixed['API'] == 0, 'owner人工の範囲は非金融')
    check(len(fixed['sessions']) == len(set(fixed['sessions'])) == len(fixed['inputs']) == 33 and set(fixed['sessions']) == set(fixed['inputs']), '小目録三十三場同範囲')
    paths = set()
    for session in fixed['sessions']:
        check(set(fixed['inputs'][session]) == {'TradeGate', 'TradeExit'}, '各場二cacheのみ固定')
        for name, item in fixed['inputs'][session].items():
            path = Path(item['path'])
            base = ROOT / ('work/wave_v106/e01_trade_gate/input' if name == 'TradeGate' else 'work/wave_v106/e01_trade_exit/input')
            check((ROOT/path).resolve().is_relative_to(base.resolve()) and item['path'] not in paths and path.name == session+'.pkl.gz' and len(item['SHA256']) == 64 and item['stat_bytes'] > 0, '六十六cache位置指紋のみ本文なし')
            paths.add(item['path'])
    copies = {'price_features.py': 'work/e01_fak_evidence_20261014/engine/price_votes.py',
              'volume_reference.py': 'work/wave_v106/trade_gate/votes.py',
              'normal_reference.py': 'work/wave_v106/e01_trade_exit/features.py'}
    snapshot = HERE / 'source_snapshot'
    snapshot.mkdir(exist_ok=False)
    for relative, saved in source_bytes.items():
        if relative.startswith('work/e01_opportunity_trace_20261015/prepare/'):
            (snapshot/Path(relative).name).write_bytes(saved)
    for local, old in copies.items():
        check(source_bytes['work/e01_opportunity_trace_20261015/prepare/'+local] == source_bytes[old], '複製三部品は元署名同bytes')
    run_text = source_bytes['work/e01_opportunity_trace_20261015/prepare/run.py'].decode('utf-8')
    for text in ('args.root_input_review_complete', '診断開始guard.json', '診断False.json', "hashlib.sha256(saved).hexdigest()==item['SHA256']", "len(seen)==66", "common.sources()==before", "元111実台帳=0,原NPZ=0,原board=0,API=0"):
        check(text in run_text, 'reader授権指紋一読guardと禁止範囲source')
    check(plan['大型本文予定'] == {'TradeGatecache': 33, 'TradeExitcache': 33, '合計cache': 66, '元111台帳': 0, '原NPZ': 0, '原book': 0, '元金融本文': 0, '金融': 0, 'API': 0}, '授権待ち読取scopeは非金融六十六')
    sys.path.insert(0, str(snapshot))
    import analysis
    import normal_reference
    import price_features
    import volume_reference
    reference_path = ROOT/'work/e01_protect_reentry_20261014/audit/owned/price_vote_reference.py'
    reference_saved = reference_path.read_bytes()
    (snapshot/'独立価格窓参照.py').write_bytes(reference_saved)
    spec = importlib.util.spec_from_file_location('independent_price_reference', snapshot/'独立価格窓参照.py')
    reference = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = reference
    spec.loader.exec_module(reference)
    verify_measurement(analysis, price_features, volume_reference, normal_reference, reference)
    verify_boundaries(analysis, price_features, volume_reference, normal_reference)
    for relative, expected in signatures.items():
        check(sha((ROOT/relative).read_bytes()) == expected, '完成source開始終端不変')
    for relative, expected in plan['source111不変の確認対象'].items():
        check(sha((ROOT/relative).read_bytes()) == expected, '旧金融一一一十七源不変更')
    proof = dict(全合格=True,状態='SOURCE_ONLYと合成例。実cache結合・参加機会・金融効果は未測。',
        検査数=sum(COUNTS.values()),分類=dict(COUNTS),source_SHA256=signatures,
        metadata_SHA256=metadata,独立参照SHA256=sha(reference_saved),監査source_SHA256=sha(Path(__file__).read_bytes()),
        指摘=['source上の停止すべき欠陥は今回確認なし。授権を自動発行しない。'],
        限界=['価格票は正常Last非零隣接更新、出来高票は正増Last対直前raw BBOの一行一票proxy。真の攻撃注文ではない。',
            'peerは価格代理時計でstrict過去。共通受信時刻や受信連番が無く、物理受信先後の証明ではない。',
            '原公開scalarはsigned済み、全normal票はunsigned。現在紙上sideは後者へ一度だけ掛ける。',
            '全normal両方向群はpaperの方向とATR、公開費用を条件にしない。紙上方向区間の市場資格群とは別の分母。',
            '元PUB、normal行数、価格時計値数、連続適格区間は独立機会や勝率ではない。',
            '実busy/場停止/FAK失効・distinct最後方向票seq・深板補充・参加者心理・新規返済は未測。',
            '接頭確認は当時票・state・flag。後の区間最終長や未来最後の適格行は接頭不変とは呼ばない。'],
        読取=dict(完成source=23,旧源の指紋確認=17,小metadata=3,根元小目録本文=0,cache=0,NPZ=0,金融本文=0,金融=0,実台帳=0,原board=0,API=0,共有編集=0),
        授権判断='独立確認範囲では次の非金融cache一読診断を妨げる不具合なし。実行許可は根が別途判断。')
    OUTPUT.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('独立SOURCE_ONLY '+str(proof['検査数'])+' 合格。SHA '+sha(OUTPUT.read_bytes()), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        failed = HERE/'独立SOURCE_ONLY初版False.json'
        assert not failed.exists()
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),分類=dict(COUNTS),
            監査source_SHA256=sha(Path(__file__).read_bytes()),cache=0,金融=0,NPZ=0,実台帳=0,API=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
