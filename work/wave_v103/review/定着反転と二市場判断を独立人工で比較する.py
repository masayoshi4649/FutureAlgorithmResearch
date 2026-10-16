"""金融及び正式原本を読まず、仕様から作る別状態機械で103入口を反証する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = HERE.parent / 'engine'


def digest(path: Path) -> str:
    """
    機能: 小さいsource又は仕様の内容指紋を取る。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。生原本と金融資料は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name: str, path: Path) -> object:
    """
    機能: 人工に使う入口sourceだけを独立した名前で読み込む。
    引数: name(str)、path(Path)はモジュール名とsource。
    返り値: objectは読み込み済みモジュール。金融関数を呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


# ----------------------------------------

def market_row(bid: float = 100, ask: float = 101, bidq: float = 10,
               askq: float = 10, last: float | None = None,
               volume: float = 0, normal: bool = True, **extras: object) -> dict:
    """
    機能: 呼値単位で記述した一人工観測を作る。
    引数: bid/ask/bidq/askq/volume(float)、last(float|None)、normal(bool)、extras(dict)。
    返り値: dictは板と最終価格。実データではない。
    """
    return dict(bid=bid, ask=ask, bidq=bidq, askq=askq,
                last=ask if last is None else last, volume=volume, normal=normal, **extras)


def raw_fixture(rows: list[dict], tick: float, reflection: bool = False) -> dict:
    """
    機能: 人工仕様を正常資格付きの原行配列へする。価格は呼値倍率だけで二商品へ変換する。
    引数: rows(list[dict])、tick(float)、reflection(bool)は人工観測、呼値、買売反射。
    返り値: dictは正式保存入力と同型の人工配列。
    """
    n = len(rows)
    times = np.array([row.get('time', i) for i, row in enumerate(rows)], np.float64)
    good = np.array([row['normal'] for row in rows], bool)
    good[0] = False
    bid_prices, ask_prices, bid_quantities, ask_quantities = [], [], [], []
    last_values, delta, synchronous = [], [], []
    for row in rows:
        b, a = row['bid'], row['ask']
        bp, ap = np.arange(b, b - 10, -1., dtype=float), np.arange(a, a + 10, dtype=float)
        bq, aq = np.full(10, 10.), np.full(10, 10.)
        bq[0], aq[0] = row['bidq'], row['askq']
        for price, quantity in row.get('bmods', {}).items():
            bq[bp == price] = quantity
        for price, quantity in row.get('amods', {}).items():
            aq[ap == price] = quantity
        last = row['last']
        if reflection:
            bp, ap, bq, aq, last = 300 - ap, 300 - bp, aq, bq, 300 - last
        bid_prices.append(bp * tick)
        ask_prices.append(ap * tick)
        bid_quantities.append(bq)
        ask_quantities.append(aq)
        last_values.append(last * tick)
        delta.append(row['volume'])
        synchronous.append(row.get('synchronous', True))
    bp, ap = np.array(bid_prices), np.array(ask_prices)
    bq, aq = np.array(bid_quantities), np.array(ask_quantities)
    result = dict(price_time_s=times, last=np.array(last_values),
                  bid=bp[:, 0], ask=ap[:, 0], bid_qty=bq[:, 0], ask_qty=aq[:, 0],
                  bid_prices=bp, ask_prices=ap, bid_quantities=bq, ask_quantities=aq,
                  volume_delta=np.array(delta, dtype=float), raw_seq=np.arange(n, dtype=np.int64),
                  volume_time_s=times - np.where(synchronous, 0., .25))
    for name in ('price_time_valid', 'in_session', 'price_row_valid', 'best_price_valid',
                 'best_quantity_valid', 'depth_valid', 'depth_transition_valid', 'volume_delta_usable'):
        result[name] = good.copy()
    result['price_time_valid'][:] = True
    for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
        result[name] = np.where(good, 0, 1).astype(np.uint16)
    result['独立正常資格'] = good
    return result


# ----------------------------------------

def observed_quantity(raw: dict, row: int, price: float, bid_side: bool) -> float | None:
    """
    機能: 人工完全板を価格辞書として参照し、遠端外と既知空価格を区別する。
    引数: raw(dict)、row(int)、price(float)、bid_side(bool)は板、行、価格、側。
    返り値: float|Noneは表示量、既知0又は範囲外不明。engineの数量関数を使わない。
    """
    prefix = 'bid' if bid_side else 'ask'
    prices = raw[prefix + '_prices'][row]
    quantities = raw[prefix + '_quantities'][row]
    table = dict(zip(prices.tolist(), quantities.tolist()))
    if price in table:
        return table[price]
    if (bid_side and price < min(table)) or (not bid_side and price > max(table)):
        return None
    return 0.


def proxy_oracle(raw: dict) -> np.ndarray:
    """
    機能: 補足05の資格と一意価格代理を人工仕様から直接計算する。
    引数: raw(dict)は独立人工配列。
    返り値: ndarray[int8]は区間方向代理。真の方向別約定量ではない。
    """
    signs = np.zeros(len(raw['raw_seq']), np.int8)
    for row in range(1, len(signs)):
        if not (raw['独立正常資格'][row] and raw['独立正常資格'][row - 1]
                and raw['volume_delta'][row] > 0
                and raw['volume_time_s'][row] == raw['price_time_s'][row]):
            continue
        last, bid, ask = raw['last'][row], raw['bid'][row - 1], raw['ask'][row - 1]
        signs[row] = 1 if last >= ask else -1 if last <= bid else 0
    return signs


def seed_state(raw: dict, row: int, intent: int) -> dict:
    """
    機能: 独立oracleの基準を名称付き状態として保存する。
    引数: raw(dict)、row/intent(int)は人工と基準行、想定方向。
    返り値: dictは固定価格及び固定分母。engineの添字配列を使わない。
    """
    buy = intent == 1
    opposite_q = float(raw['ask_qty' if buy else 'bid_qty'][row])
    return dict(anchor=row, stamp=raw['price_time_s'][row], bid=raw['bid'][row], ask=raw['ask'][row],
                p=raw['ask' if buy else 'bid'][row], r=raw['bid' if buy else 'ask'][row],
                q0=opposite_q, own_q0=raw['bid_qty' if buy else 'ask_qty'][row],
                previous_q=opposite_q, decreased=0., initial_volume=0., post_volume=0.,
                phase='活動待ち', saw_move=False, first_ready=False, ready=False)


def state_oracle(raw: dict, config: dict, tick: float) -> dict:
    """
    機能: 補足01〜06の仕様を別の辞書状態機械で原行順に実行する。
    引数: raw/config(dict)、tick(float)は人工、入口条件及び呼値。
    返り値: dictはready、固定基準seq、段階。sourceのsimulateやイベントログは参照しない。
    """
    family = config['family']
    n = len(raw['raw_seq'])
    ready = np.zeros((n, 2), bool)
    anchors = np.full((n, 2), -1, np.int64)
    phases = np.full((n, 2), -1, np.int8)
    signs, states = proxy_oracle(raw), {1: None, -1: None}
    for row in range(n):
        for intent in (1, -1):
            out_side = intent if family == 'C' else -intent
            col = 0 if out_side == 1 else 1
            state = states[intent]
            if not raw['独立正常資格'][row]:
                states[intent] = None
                continue
            if state is None:
                state = seed_state(raw, row, intent)
                states[intent] = state
            else:
                b, a = raw['bid'][row], raw['ask'][row]
                opposite_q = observed_quantity(raw, row, state['p'], intent == -1)
                support_p = state['p'] if family == 'C' else state['r']
                support_q = observed_quantity(raw, row, support_p, out_side == 1)
                if family == 'C':
                    moved = (b >= state['p'] and a >= state['ask'] + tick) if intent == 1 else (a <= state['p'] and b <= state['bid'] - tick)
                else:
                    moved = (b <= state['bid'] - tick and a <= state['ask'] - tick) if intent == 1 else (b >= state['bid'] + tick and a >= state['ask'] + tick)
                original_reached = (b >= state['p']) if intent == 1 else (a <= state['p'])
                expired = (raw['price_time_s'][row] - state['stamp'] >= 120
                           or row - state['anchor'] >= 5000)
                reset = expired or opposite_q is None or support_q is None
                reset |= family == 'R' and original_reached
                reset |= state['saw_move'] and not moved
                if reset:
                    state = seed_state(raw, row, intent)
                    states[intent] = state
                elif state['phase'] == '活動待ち':
                    decrease = max(0., state['previous_q'] - opposite_q)
                    aligned = (signs[row] == intent and raw['volume_delta'][row] > 0
                               and abs(raw['last'][row] - state['p']) <= tick)
                    if config['use_supply'] and (not config['use_volume'] or aligned):
                        state['decreased'] += decrease
                    if config['use_volume'] and aligned and (not config['use_supply'] or decrease > 0):
                        state['initial_volume'] += raw['volume_delta'][row]
                    state['previous_q'] = opposite_q
                    supply_ok = not config['use_supply'] or state['decreased'] >= .5 * state['q0']
                    volume_ok = not config['use_volume'] or state['initial_volume'] >= config['strength'] * state['q0']
                    if supply_ok and volume_ok:
                        state['phase'] = '回復待ち' if family == 'R' else '移動待ち'
                elif state['phase'] == '回復待ち':
                    recovered = opposite_q > state['previous_q'] and opposite_q >= .8 * state['q0']
                    state['previous_q'] = opposite_q
                    if not config['use_supply'] or recovered:
                        state['phase'] = '移動待ち'
                elif state['phase'] == '移動待ち':
                    if moved:
                        state['saw_move'] = True
                        denominator = state['q0'] if family == 'C' else state['own_q0']
                        if not config['use_supply'] or support_q >= .5 * denominator:
                            state['phase'] = '移動後待ち'
                            state['post_volume'] = 0.
                else:
                    denominator = state['q0'] if family == 'C' else state['own_q0']
                    supported = not config['use_supply'] or support_q >= .5 * denominator
                    progress = out_side * (raw['last'][row] - support_p)
                    if (config['use_volume'] and signs[row] == out_side and raw['volume_delta'][row] > 0
                            and 0 <= progress <= 2 * tick):
                        state['post_volume'] += raw['volume_delta'][row]
                    state['ready'] = bool(supported and (not config['use_volume']
                                          or state['post_volume'] >= config['strength'] * state['q0']))
                    if state['ready']:
                        state['first_ready'] = True
            phase_names = {'活動待ち': 0, '回復待ち': 1,
                           '移動待ち': 1 if family == 'C' else 2,
                           '移動後待ち': (3 if state['first_ready'] else 2) if family == 'C'
                                         else (4 if state['first_ready'] else 3)}
            anchors[row, col] = raw['raw_seq'][state['anchor']]
            phases[row, col] = phase_names[state['phase']]
            ready[row, col] = state['ready']
    return dict(ready=ready, anchor_raw_seq=anchors, phases=phases)


# ----------------------------------------

def scenarios() -> list[tuple[str, list[dict]]]:
    """
    機能: 正例と失敗境界を利益結果と無関係に定義する。
    引数: なし。
    返り値: list[tuple[str,list[dict]]]は共通入力の固定人工集。
    """
    base = [market_row(), market_row()]
    c = base + [market_row(askq=4, volume=30),
                market_row(101, 102, bidq=5, volume=30),
                market_row(101, 102, bidq=5, volume=30)]
    r = base + [market_row(askq=4, volume=30), market_row(askq=8),
                market_row(99, 100, askq=5, last=99, volume=30),
                market_row(99, 100, askq=5, last=99, volume=30)]
    result = [('C正例', c), ('R正例', r)]
    result.append(('C移動行だけ出来高', c[:-1] + [market_row(101, 102, bidq=5)]))
    result.append(('C帯超過', c[:-1] + [market_row(101, 102, bidq=5, last=104, volume=30)]))
    result.append(('R数量9反復の偽回復', base + [market_row(askq=9, volume=30), market_row(askq=10)] * 5
                   + [market_row(askq=9, volume=30), market_row(askq=9), market_row(99, 100, last=99, volume=30)]))
    result.append(('R未到達を破るC移動', r[:3] + [market_row(101, 102, volume=30)] + r[3:]))
    result.append(('C支持不足後回復', c[:3] + [market_row(101, 102, bidq=1, volume=30),
                  market_row(101, 102, bidq=5), market_row(101, 102, bidq=5, volume=30)]))
    result.append(('C支持不足中に価格破れ', c[:3] + [market_row(101, 102, bidq=1, volume=30),
                  market_row(), market_row(101, 102, bidq=5, volume=30)]))
    result.append(('C確認後支持不足と当該回復ready', c + [market_row(101, 102, bidq=1),
                  market_row(101, 102, bidq=5)]))
    result.append(('R固定own分母2対opposite20', [market_row(bidq=2, askq=20),
                  market_row(bidq=2, askq=20), market_row(bidq=2, askq=8, volume=60),
                  market_row(bidq=2, askq=16), market_row(99, 100, askq=1, last=99, volume=60),
                  market_row(99, 100, askq=1, last=99, volume=60)]))
    result.append(('資格不明後基準だけ', c[:3] + [market_row(normal=False)] + c[3:] + c[2:]))
    result.append(('価格時計120秒期限', c[:3] + [market_row(101, 102, bidq=5, volume=30, time=121)]))
    result.append(('固定価格遠端外', c[:3] + [market_row(120, 121, volume=30)]))
    result.append(('最終価格spread内不明', base + [market_row(askq=4, last=100.5, volume=30)] + c[3:]))
    result.append(('二時計不一致', base + [market_row(askq=4, volume=30, synchronous=False)] + c[3:]))
    result.append(('既知出来高0と価格対照', base + [market_row(askq=4)] + [market_row(101, 102, bidq=5)] * 3))
    result.append(('深板内p価格未表示0', c[:3] + [market_row(102, 103, bmods={101: 0}, volume=30)] * 2))
    result.append(('初期spread2呼値', [market_row(100, 102), market_row(100, 102),
                   market_row(100, 102, askq=4, volume=30), market_row(102, 103, bidq=5, volume=30),
                   market_row(102, 103, bidq=5, volume=30)]))
    return result


def peer_packet(times: list[float], qualified: list[bool], ready: list[tuple[bool, bool]],
                family: str = 'C', anchors: list[tuple[int, int]] | None = None) -> tuple[dict, dict]:
    """
    機能: 公表と候補消費だけを独立に検査する小人工packetを作る。
    引数: times(list[float])、qualified(list[bool])、ready/anchors(list[tuple])、family(str)。
    返り値: tuple[dict,dict]はstate packetとraw時計。状態再生を行わない。
    """
    n = len(times)
    raw = dict(price_time_s=np.array(times, float), price_time_valid=np.isfinite(times),
               raw_seq=np.arange(n, dtype=np.int64))
    packet = dict(qualified=np.array(qualified, bool), ready=np.array(ready, bool),
                  anchor_raw_seq=np.array(anchors if anchors is not None else [(1, 1)] * n, np.int64),
                  config=dict(family=family))
    return packet, raw


def candidate_oracle(own: dict, peer: dict, own_raw: dict, peer_raw: dict, family: str) -> list[list[tuple]]:
    """
    機能: 各相手新最大時計の最初行を逐次で固定し、厳密過去の有効方向を列挙する。
    引数: own/peer/own_raw/peer_raw(dict)、family(str)は人工stateと原時計。
    返り値: list[list[tuple]]は消費済をまだ除外しない方向候補。searchsortedを使わない。
    """
    published, high = [], -math.inf
    for index, stamp in enumerate(peer_raw['price_time_s']):
        if peer_raw['price_time_valid'][index] and stamp > high:
            published.append((float(stamp), index))
            high = stamp
    rows = []
    for row, stamp in enumerate(own_raw['price_time_s']):
        candidates = []
        sources = [(time, index) for time, index in published if time < stamp]
        if own['qualified'][row] and sources:
            time, source = sources[-1]
            if stamp - time <= 15 and peer['qualified'][source]:
                for col, side in enumerate((1, -1)):
                    if own['ready'][row, col] and peer['ready'][source, col]:
                        candidates.append((side, (family, side if family == 'C' else -side,
                                            int(own['anchor_raw_seq'][row, col])), source))
        rows.append(candidates)
    return rows


def pulse_oracle(families: dict, own_raw: dict) -> np.ndarray:
    """
    機能: 全valid-readyで方向を決め、未消費がある単一方向だけを一度消費する。
    引数: families(dict)、own_raw(dict)は各familyのpacket及び自己時計。
    返り値: ndarray[int8]は人工pulse。金融注文の実行はしない。
    """
    candidates = {family: candidate_oracle(value['own'], value['peer'], own_raw,
                                          value['peer_raw'], family)
                  for family, value in families.items()}
    event, consumed = np.zeros(len(own_raw['raw_seq']), np.int8), set()
    for row in range(len(event)):
        current = [candidate for values in candidates.values() for candidate in values[row]]
        sides = {candidate[0] for candidate in current}
        if len(sides) == 1 and any(candidate[1] not in consumed for candidate in current):
            event[row] = next(iter(sides))
            consumed.update(candidate[1] for candidate in current)
    return event


# ----------------------------------------

def main() -> None:
    """
    機能: 全14入口条件、売買反射、両呼値、二市場と自動競合を人工で独立に比較する。
    引数: なし。
    返り値: None。review新JSONのみ保存し、正式素材と金融は一切読まない。
    """
    destination = HERE / '定着反転と二市場判断の独立人工反証.json'
    assert not destination.exists(), '完了資料は上書きしません'
    states = load_module('独立103入口検査対象', ENGINE / 'states.py')
    catalog = load_module('独立103入口条件読取', HERE.parent / 'catalog.py')
    # ----------------------------------------
    # source本体のPython関数を使い、人工検査でengine領域へJITを書き込まない。
    for name in ('fixed_quantity', 'seed', 'log_event'):
        setattr(states, name, getattr(states, name).py_func)
    passed, failures, compared_rows = [], [], 0
    configurations = [config for config in catalog.catalog() if config['kind'] == 'single']
    for label, rows in scenarios():
        for tick, symbol in ((.5, 'TOPIX'), (10., 'NK225')):
            for reflected in (False, True):
                raw = raw_fixture(rows, tick, reflected)
                np.testing.assert_array_equal(states.row_qualified(raw), raw['独立正常資格'])
                np.testing.assert_array_equal(states.volume_direction_proxy(raw), proxy_oracle(raw))
                for config in configurations:
                    expected = state_oracle(raw, config, tick)
                    actual = states.run(raw, dict(tick=tick), config, python=True)
                    identifier = f'{label}/{symbol}/{"反射" if reflected else "元"}/{config["id"]}'
                    errors = [name for name in expected if not np.array_equal(expected[name], actual[name])]
                    compared_rows += len(rows) * 2
                    if errors:
                        failures.append(dict(検査=identifier, 不一致列=errors,
                                             期待={name: expected[name].tolist() for name in errors},
                                             実装={name: actual[name].tolist() for name in errors}))
                    else:
                        passed.append(identifier)
    # ----------------------------------------
    # 候補消費済でも現在の対向判断を消さず、失効後だけ未消費へ参加する。
    union_cases = []
    c, own_raw = peer_packet([1, 2, 3, 4], [True] * 4,
                             [(True, False), (True, False), (False, False), (False, False)])
    r, _ = peer_packet([1, 2, 3, 4], [True] * 4,
                      [(False, False), (False, True), (False, True), (False, True)], 'R')
    peer_c, peer_raw = peer_packet([0, 1, 2, 3], [True] * 4, [(True, False)] * 4)
    peer_r, _ = peer_packet([0, 1, 2, 3], [True] * 4, [(False, True)] * 4, 'R')
    components = dict(C=dict(own=c, peer=peer_c, peer_raw=peer_raw),
                      R=dict(own=r, peer=peer_r, peer_raw=peer_raw))
    expected = pulse_oracle(components, own_raw)
    actual = states.union_pulses(components, own_raw)['event']
    union_cases.append(dict(検査='既消費C買と新R売の競合後、C失効', 期待=expected.tolist(),
                            実装=actual.tolist(), 一致=np.array_equal(expected, actual)))
    assert expected.tolist() == [1, 0, -1, 0]
    for label, times, normal, peer_ready in (
            ('同時計後続のreadyを過去化しない', [0, 0, 1], [True, True, True], [(False, False), (True, False), (True, False)]),
            ('同時計最初不正を後続で救済しない', [0, 0, 1], [False, True, True], [(True, False)] * 3),
            ('逆行行を公表へ救済しない', [0, 2, 1, 3], [True] * 4, [(False, False), (False, False), (True, False), (True, False)]),
            ('厳密過去と15秒境界', [0, 1], [True, True], [(True, False)] * 2)):
        peer, pr = peer_packet(times, normal, peer_ready)
        own, ownraw = peer_packet([0, 1, 2, 16, 16.001, 17], [True] * 6, [(True, False)] * 6,
                                 anchors=[(i, i) for i in range(6)])
        expected = pulse_oracle(dict(C=dict(own=own, peer=peer, peer_raw=pr)), ownraw)
        actual = states.pulses(own, peer, ownraw, pr)['event']
        union_cases.append(dict(検査=label, 期待=expected.tolist(), 実装=actual.tolist(),
                                一致=np.array_equal(expected, actual)))
    result = dict(全合格=not failures and all(case['一致'] for case in union_cases),
                  scope='仕様に基づく独立の名称付き辞書状態機械と最終sourceのPython本体を人工だけで比較。正式金融・JIT・実接頭未検査。',
                  入口条件数=len(configurations), 人工状況数=len(scenarios()), 呼値商品数=2, 売買反射数=2,
                  一致ケース数=len(passed), 不一致ケース数=len(failures), 比較状態行数=compared_rows,
                  不一致=failures, 二市場及び競合検査=union_cases,
                  SHA256={str(path.relative_to(ROOT)): digest(path) for path in (
                      Path(__file__), ENGINE / 'states.py', HERE.parent / 'catalog.py',
                      *[HERE.parent / f'数値設計補足{index:02d}.json' for index in range(1, 7)
                        if (HERE.parent / f'数値設計補足{index:02d}.json').exists()])},
                  正式原本読取=0, 正式入力再抽出=0, 金融再生=0, 現在API取得=0, 実注文=0,
                  旧source変更=0, JIT実行=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=result['全合格'], 一致ケース数=len(passed), 不一致ケース数=len(failures),
                          比較状態行数=compared_rows, 二市場検査=len(union_cases), SHA256=digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
