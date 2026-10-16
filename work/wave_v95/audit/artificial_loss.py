"""38条件の実fill起点・四源反転・最新親解除を、合法呼値の人工経路で監査する。"""

import math
from pathlib import Path
import socket

import numba
import numpy as np

import common
import check_loss


SCENARIOS = (
    '正常な四源反転', 'LP順行なし', '四源時計が返済と同時', '相手板源未更新',
    '相手LP源未更新', 'peer未知の別基準', '自己LP未知の別基準', '異時点支持を足さない',
    '持続の格子欠落', '持続開始後同clock後続', '返済予約中は失敗にしない',
    '予約負でも実fill利益', '料金だけ負の追跡停止', '同方向は制限しない',
    '最新nonstop負でS解除', '最新純利益で解除',
)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 人工監査からのネットワーク接続を禁止する。
    引数: args(tuple)、kwargs(dict)。接続引数。
    返り値: None。呼出し時は例外。
    """
    raise RuntimeError('人工監査の通信は禁止')


def fixture(symbol: str, scenario: str, reflected: bool, config: dict) -> tuple[dict, dict]:
    """
    機能: 旧J8幅・合法ラージ呼値のまま、実失敗後の反対候補と四源境界を作る。
    引数: symbol/scenario(str)、reflected(bool)。上下反射。config(dict)。38条件の一つ。
    返り値: tuple[dict,dict]。原板recordと信号signal。実データ及び損益結果を読まない。
    """
    base, tick, peer_base, peer_tick = ((4000., .5, 68000., 10.) if symbol == 'TOPIX'
                                      else (68000., 10., 4000., .5))
    width = max(2, math.ceil(base * config['trend_width_fraction'] / tick - 1e-10)) * tick
    long_path = scenario in ('最新nonstop負でS解除', '最新純利益で解除')
    n = 1101 if long_path else 211
    times = 300. + np.arange(n) * 5.
    changes = np.zeros(n)
    changes[10:] = -2 * width
    changes[16:] = -3 * width
    changes[35:] = -4 * width
    event = np.zeros(n, np.int8)
    event[1], event[20], event[40] = 1, -1, -1
    if long_path:
        event[:] = 0
        event[1], event[20], event[500] = 1, 1, -1
        changes[16:] = -2 * width
        if scenario == '最新純利益で解除':
            changes[375:] += 3 * tick
        changes[490:] -= width
    elif scenario == '予約負でも実fill利益':
        changes[11:16] = 2 * width
    elif scenario == '料金だけ負の追跡停止':
        changes[3:10] = width + tick
        changes[10:16] = tick
    elif scenario == '同方向は制限しない':
        event[20] = 1
    bid = base + changes
    ask = bid + tick
    record = dict(symbol=symbol, session='人工95_Day', time_s=times, price=bid.copy(), bid=bid.copy(),
                  ask=ask.copy(), price_valid=np.ones(n, bool), quote_valid=np.ones(n, bool),
                  seq=np.arange(n, dtype=np.int64) * 3 + 100, tick=tick, start=0., limit=float(times[-1]))
    if scenario == '返済予約中は失敗にしない':
        record['quote_valid'][11:16] = False
    elif scenario == '自己LP未知の別基準':
        record['price_valid'][11] = False
    previous = np.maximum(np.arange(n) - 1, 0)
    peer_delta = changes / tick * peer_tick
    observed = np.zeros((n, 22), float)
    observed[:, 0] = previous
    observed[:, 1] = record['seq'][previous]
    observed[:, 2] = times[previous]
    observed[:, 3] = bid[previous]
    observed[:, 4] = ask[previous]
    observed[:, 5] = previous + 800
    observed[:, 6] = previous * 4 + 200
    observed[:, 7] = times[previous] - 1.
    observed[:, 8] = peer_base + peer_delta[previous]
    observed[:, 9] = observed[:, 8] + peer_tick
    observed[:, 10] = previous * 2 + 5000
    observed[:, 11] = record['seq'][previous]
    observed[:, 12] = times[previous]
    observed[:, 13] = bid[previous]
    observed[:, 14] = previous * 2 + 9000
    observed[:, 15] = previous * 4 + 200
    observed[:, 16] = times[previous] - 2.
    observed[:, 17] = peer_base + peer_delta[previous]
    observed[:, 18:] = True
    observed[0, 18:] = False
    mapped = np.arange(n, dtype=np.int32)
    if scenario == 'LP順行なし':
        observed[16:35, 13] = base - 2 * width
        observed[16:35, 17] = peer_base - 2 * width / tick * peer_tick
    elif scenario == '四源時計が返済と同時':
        observed[16:35, [2, 7, 12, 16]] = times[11]
    elif scenario == '相手板源未更新':
        observed[16:35, 5:8] = observed[11, 5:8]
    elif scenario == '相手LP源未更新':
        observed[16:35, 14:17] = observed[11, 14:17]
    elif scenario == 'peer未知の別基準':
        observed[11:20, 19] = False
    elif scenario == '異時点支持を足さない':
        observed[16:20, 8:10] = observed[11, 8:10]
        observed[20:35, 3:5] = np.array([bid[11], ask[11]])
    elif scenario == '持続の格子欠落':
        mapped[19] = -1
    elif scenario == '持続開始後同clock後続':
        observed[17:35, [2, 7, 12, 16]] = observed[17, [2, 7, 12, 16]]
    signal = dict(grid=times.copy(), mapped=mapped, event=event,
                  mode=np.zeros(n, np.int8), quality=np.ones(n, bool), reset=np.zeros(n, bool),
                  trend_width=width, current_valid=np.ones(n, bool), arm_common=np.zeros(n, np.int8),
                  peer_tick=peer_tick, loss_observations=observed,
                  execution_lp_index=np.arange(n, dtype=np.int64) * 2 + 5000)
    if reflected:
        original_bid = record['bid'].copy()
        record['price'] = 2 * base - record['price']
        record['bid'] = 2 * base - record['ask']
        record['ask'] = 2 * base - original_bid
        signal['event'] *= -1
        for left, right, center in ((3, 4, base), (8, 9, peer_base)):
            original = observed[:, left].copy()
            observed[:, left] = 2 * center - observed[:, right]
            observed[:, right] = 2 * center - original
        observed[:, 13] = 2 * base - observed[:, 13]
        observed[:, 17] = 2 * peer_base - observed[:, 17]
    for name in ('price', 'bid', 'ask'):
        scaled = record[name] / tick
        np.testing.assert_array_equal(scaled, np.round(scaled))
    return record, signal


def money(record: dict, result: dict) -> dict:
    """
    機能: 注文だけで全親net及び各原板の清算時価を独立計算する。
    引数: record/result(dict)。人工原板と人工結果。
    返り値: dict。注文数、親数、全原板行の照合数。
    """
    multiplier, fee_unit, cap = (1000., 41.8, 10) if record['symbol'] == 'TOPIX' else (10., 11., 20)
    orders, parents = result['orders'], result['trades']
    opened = {}
    computed = []
    cash, held = 0., None
    cursor = 0
    expected_curve = np.zeros(len(record['time_s']))
    last_bid, last_ask = record['bid'][0], record['ask'][0]
    for row in range(len(record['time_s'])):
        valid = (record['quote_valid'][row] and np.isfinite(record['bid'][row])
                 and np.isfinite(record['ask'][row]) and 0 < record['bid'][row] < record['ask'][row])
        if valid:
            last_bid, last_ask = record['bid'][row], record['ask'][row]
        while cursor < len(orders) and orders[cursor, 0] == row:
            order = orders[cursor]
            assert valid and order[0] > order[1] and order[3] == 0 and order[5] <= cap
            action, quantity, price = int(order[4]), order[5], order[6]
            assert price == (record['ask'][row] if action == 1 else record['bid'][row])
            fee = math.floor(quantity * fee_unit + 1e-8)
            assert order[9] == fee
            cash -= action * quantity * price * multiplier + fee
            if order[7]:
                assert held is None
                held = order.copy()
                opened[int(order[2])] = order.copy()
            else:
                assert held is not None and held[2] == order[2] and action == -held[4]
                gross = held[4] * (price - held[6]) * quantity * multiplier
                computed.append((order[2], gross, gross - held[9] - fee))
                held = None
            cursor += 1
        equity = cash
        if held is not None:
            quote = last_bid if held[4] == 1 else last_ask
            equity += held[4] * held[5] * quote * multiplier - math.floor(held[5] * fee_unit + 1e-8)
        expected_curve[row] = equity
    assert cursor == len(orders)
    for parent, gross, net in computed:
        saved = parents[parents[:, 0] == parent]
        assert len(saved) == 1 and saved[0, 10] == gross and saved[0, 11] == net
    assert len(computed) == len(parents)
    common.exact(expected_curve, result['curve'])
    common.exact(np.c_[expected_curve, np.zeros(len(expected_curve))], result['source_curve'])
    return dict(注文=len(orders), 親=len(parents), 全原板=len(expected_curve))


def intended(scenario: str, config: dict, result: dict) -> None:
    """
    機能: ケース名だけで網羅したことにせず、意図した正負境界への到達を確認する。
    引数: scenario(str)、config/result(dict)。人工経路名と条件及び結果。
    返り値: None。対象行の新規/拒否と実親netが予定境界と違えば例外。
    """
    kind = check_loss.KINDS[config['loss_reentry_kind']]
    reserves = result['events'][(result['events'][:, 2] == 0) & (result['events'][:, 3] == 1)]
    first = result['trades'][0]
    row = 500 if scenario in ('最新nonstop負でS解除', '最新純利益で解除') else 20
    accepted = bool(np.any(reserves[:, 0] == row))
    expected = kind == 0 or kind >= 2
    if scenario == 'LP順行なし':
        expected = kind in (0, 2)
    elif scenario in ('四源時計が返済と同時', '相手板源未更新', '相手LP源未更新',
                      'peer未知の別基準', '異時点支持を足さない'):
        expected = kind == 0
    elif scenario in ('持続の格子欠落', '持続開始後同clock後続'):
        expected = kind in (0, 2, 3)
    elif scenario == '返済予約中は失敗にしない':
        expected = False
        assert first[3] == 16
    elif scenario == '予約負でも実fill利益':
        expected = True
        assert first[11] > 0 and first[13] == 1
    elif scenario == '料金だけ負の追跡停止':
        assert first[10] == 0 and first[11] < 0 and first[13] == 2
    elif scenario == '同方向は制限しない':
        expected = True
    elif scenario == '最新nonstop負でS解除':
        second = result['trades'][1]
        assert second[11] < 0 and second[13] == 3
        expected = kind == 0 or kind >= 2 or config['loss_reentry_trigger'] == 'stop_net_negative'
    elif scenario == '最新純利益で解除':
        second = result['trades'][1]
        assert second[11] > 0
        expected = True
    assert accepted == expected, ('意図した正負境界に達していません', scenario, config['id'], row, accepted, expected)
    if scenario == 'peer未知の別基準' and kind >= 2:
        anchored = result['loss_reentry_events'][result['loss_reentry_events'][:, 1] == 3]
        assert len(anchored) and anchored[0, 0] == 20 and anchored[0, 9] == 2
    if scenario == '自己LP未知の別基準' and kind >= 2:
        anchored = result['loss_reentry_events'][result['loss_reentry_events'][:, 1] == 3]
        assert len(anchored) and anchored[0, 0] > first[3] and anchored[0, 9] == 2


def main() -> None:
    """
    機能: 全38×16族×両商品×上下反射の人工fillと66列を独立検算する。
    引数: なし。
    返り値: None。人工専用証跡を新95/auditへ保存し、正式95PLは読まない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    catalog = common.module('独立反転監査95の条件読取', common.WORK / 'catalog.py')
    engine = common.module('独立反転監査95の人工執行', common.WORK / 'engine.py')
    numba.config.CACHE_DIR = str(common.HERE / 'jit')
    codes = common.fingerprint([Path(__file__), Path(common.__file__), Path(check_loss.__file__),
                                common.WORK / 'catalog.py', common.WORK / 'engine.py'])
    totals = dict(人工台帳=0, 注文=0, 親=0, 全原板=0, 改竄拒否=0)
    states = {}
    seen = {name: 0 for name in SCENARIOS}
    for config in catalog.catalog():
        for scenario in SCENARIOS:
            for symbol in common.SYMBOLS:
                for reflected in (False, True):
                    record, signal = fixture(symbol, scenario, reflected, config)
                    result = engine.execute(record, signal, config, finish=True)
                    counts = money(record, result)
                    checked = check_loss.verify(record, signal, config, result)
                    common.exact(check_loss.restore(record, signal, config, result['orders'], result['events']),
                                 check_loss.restore(record, signal, config, result['orders'], result['events'], all_rows=True))
                    intended(scenario, config, result)
                    for name, amount in checked.items():
                        states[name] = states.get(name, 0) + amount
                    for name, amount in counts.items():
                        totals[name] += amount
                    totals['人工台帳'] += 1
                    seen[scenario] += 1
                    if len(result['loss_reentry_events']):
                        poisoned = result['loss_reentry_events'].copy()
                        poisoned[0, 7] += 1.
                        try:
                            common.exact(check_loss.restore(record, signal, config, result['orders'], result['events']), poisoned)
                        except AssertionError:
                            totals['改竄拒否'] += 1
                        else:
                            raise AssertionError('実返済clock改竄を監査が拒否しません')
        print(f"{config['id']}: 16族×両商品×上下反射の実親netと全66列が独立一致", flush=True)
    assert totals['人工台帳'] == 38 * 16 * 4
    common.exact(common.fingerprint([common.ROOT / path for path in codes]), codes)
    common.save('全38の実親料金負と四源反転及び最新親解除の独立人工検算.json',
                dict(合格=True, 検査=totals, 状態=states, ケース族=seen, SHA256=codes,
                     全2432で公開変化行と元全原行Pythonの66列完全一致=True,
                     正式95損益実行=0, 正式95損益閲覧=0, API取得=0, 実注文=0,
                     限界='人工執行/会計/失敗記憶の実装監査。価格予測、正式収益、真受信時計の証明ではない。'))


if __name__ == '__main__':
    main()
