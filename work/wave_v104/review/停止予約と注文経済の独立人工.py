"""104出口を、符号付き価格座標と有理数会計の別モデルで反証する。"""

from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CURRENT = {}


def load(name: str, path: Path) -> object:
    """
    機能: 新104の出口と根条件を読取専用で接続する。
    引数: name(str)、path(Path)は小さい独立source。
    返り値: objectはモジュール。正式入力又は金融CLIは呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def fraction(value: float) -> Fraction:
    """
    機能: 人工の有限数値を十進文字列経由の有理数へ変換する。
    引数: value(float)は人工の既知価格又は時計。
    返り値: Fractionは独立会計値。未来データは参照しない。
    """
    return Fraction(str(float(value)))


def sha(path: Path) -> str:
    """
    機能: この検査が読んだ小さいsourceと証跡の指紋を作る。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。原本や巨大台帳は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------


def fixture(symbol: str, side: int, exit_id: str, quantity: int, case: str) -> tuple[dict, dict]:
    """
    機能: 固定15種類の予約・線・不明・時価境界を小さい人工へ構成する。
    引数: symbol/exit_id/case(str)、side/quantity(int)。
    返り値: tuple[dict,dict]はrecordとsignal。保存市場の行は使わない。
    """
    base, tick, multiplier, rate = (4000., .5, 1000, Decimal('41.8')) if symbol == 'TOPIX' else (60000., 10., 10, Decimal('11'))
    k = int(exit_id[1])
    fee = int((rate*quantity).to_integral_value(rounding=ROUND_FLOOR))
    fee_width = float(-(-Fraction(2*fee, quantity*multiplier)//Fraction(str(tick)))*Fraction(str(tick)))
    initial, wide = base*.001, base*.004
    times = [300., 301., 302., 303., 304., 305., 1000.]
    limit = 1000.
    quotes = [base-side*tick]+[base]*6
    events = {0: side}
    invalid, bad_quality, resets = [], [], []
    entry = base+side*tick
    if case == '平坦で長く保持':
        times = [299., 300., 301., 500., 2500., 4940., 5000.]
        limit, events = 5000., {1: side}
        quotes = [base]*7
    elif case == '支持ちょうど':
        quotes[2:] = [base-side*k*tick, base-side*(k+1)*tick]+[base-side*(k+1)*tick]*3
    elif case == '支持一呼値手前':
        quotes[2:] = [base-side*(k-1)*tick, base-side*k*tick]+[base-side*(k+1)*tick]*3
    elif case == '支持から遠いfill':
        quotes[1] = base+side*100*tick
        far_entry = quotes[1]+side*tick
        quotes[2:] = [far_entry-side*initial]+[far_entry-side*(initial+tick)]*4
    elif case == '支持線を越えたfill':
        quotes[1] = base-side*(k+2)*tick
        quotes[2:] = [base-side*(k+3)*tick]*5
    elif case == '利益発動後に次quote悪化':
        quotes[2:] = [entry+side*(fee_width+k*tick), entry+side*fee_width]+[entry-side*tick]*3
    elif case == '利益発動一呼値不足':
        quotes[2:] = [entry+side*(fee_width+(k-1)*tick), base-side*k*tick]+[base-side*(k+1)*tick]*3
    elif case == '広い追尾の大波':
        quotes[2:] = [entry+side*2*wide, entry+side*wide]+[entry+side*(wide-tick)]*3
    elif case == '新規予約後の資格悪化':
        invalid, bad_quality, resets = [1, 2], list(range(1, 7)), list(range(1, 7))
        quotes[3:] = [base-side*(k+3)*tick]*4
    elif case == '返済予約中の不明':
        quotes[2:] = [base-side*k*tick]+[base-side*(k+5)*tick]*4
        invalid = [3, 4]
    elif case == 'cutと新規fill競合':
        times, quotes, events = [698., 699., 700., 1000.], [base]*4, {1: side}
    elif case == '受付境界と返済後停止':
        times = [299., 300., 301., 302., 303., 332., 333., 334., 335., 336., 1000.]
        quotes = [base]*len(times)
        quotes[3:5] = [base-side*k*tick, base-side*(k+1)*tick]
        quotes[8:] = [base-side*k*tick]*3
        events = {0: side, 1: side, 2: side, 4: side, 5: side, 6: side, 7: side}
    elif case == '未知時価の評価だけ保持':
        invalid = [2, 3, 4]
        quotes[2:5] = [base-side*50*tick]*3
    elif case == '場末まで正常quoteなし':
        invalid = [2, 3, 4, 5, 6]
    elif case == '候補なし':
        events = {}
    else:
        raise AssertionError(case)
    n = len(times)
    quote = np.array(quotes, float)
    bid, ask = (quote.copy(), quote+tick) if side == 1 else (quote-tick, quote.copy())
    record = dict(symbol=symbol, session='独立人工', time_s=np.array(times), seq=np.arange(500, 500+n, dtype=np.int64),
        bid=bid, ask=ask, price=(bid+ask)/2, quote_valid=np.ones(n, bool), price_valid=np.ones(n, bool),
        start=0., end=limit, limit=limit, tick=tick, 人工素材=True)
    record['quote_valid'][invalid] = False
    event, support = np.zeros(n, np.int8), np.full(n, np.nan)
    for row, direction in events.items():
        event[row], support[row] = direction, base
    quality, reset = np.ones(n, bool), np.zeros(n, bool)
    quality[bad_quality], reset[resets] = False, True
    signal = dict(event=event, support_price=support, entry_quality=quality, entry_reset=reset,
        reference_open=base, trend_width=wide, execution_to_raw_index=np.arange(n, dtype=np.int64),
        decisions=[dict(row=row, normal_row=row, raw_row=row, raw_seq=int(record['seq'][row]),
            side=int(direction), support_price=base) for row, direction in events.items()])
    return record, signal


def oracle(record: dict, signal: dict, config: dict) -> dict:
    """
    機能: 売買共通のsigned価格座標で、次quote約定とFraction全玉会計を独立に進める。
    引数: record/signal/config(dict)は人工素材と結果前条件。
    返り値: dictは物理注文・完結親・全行時価・6保有・途中停止線。
    """
    symbol, q = record['symbol'], config['quantity']
    multiplier, rate = (1000, Decimal('41.8')) if symbol == 'TOPIX' else (10, Decimal('11'))
    fee = int((rate*q).to_integral_value(rounding=ROUND_FLOOR))
    tick = fraction(record['tick'])
    initial = max(2, -(-fraction(signal['reference_open'])/1000//tick))*tick
    wide = fraction(signal['trend_width'])
    fee_width = -(-Fraction(2*fee, q*multiplier)//tick)*tick
    k = config['support_ticks']
    cut, force = fraction(record['limit'])-300, fraction(record['limit'])-60
    cash, last_exit, last_quote = Fraction(0), None, None
    position, pending, parent, uid = None, None, 0, 0
    orders, trades, curves, traces, stale, judgments = [], [], [], [], [], {}
    candidates = []
    for row, clock in enumerate(record['time_s']):
        stamp = fraction(clock)
        good = bool(record['quote_valid'][row] and np.isfinite(record['bid'][row]) and np.isfinite(record['ask'][row])
                    and record['bid'][row] > 0 and record['ask'][row] > record['bid'][row])
        if good:
            last_quote = fraction(record['bid'][row]), fraction(record['ask'][row])
        exited = False
        if pending is not None and pending['kind'] == 'entry' and stamp >= cut:
            pending = None
        if position is not None and pending is None and stamp >= force:
            pending = dict(kind='exit', row=row-1, clock=force, reason=6)
        if pending is not None and good and row > pending['row'] and stamp >= pending['clock']:
            if pending['kind'] == 'entry':
                side = pending['side']
                price = last_quote[1] if side == 1 else last_quote[0]
                support = fraction(pending['support'])
                stop = max(side*support-k*tick, side*price-initial)
                position = dict(side=side, price=price, entry_row=row, entry_clock=stamp, entry_decision=pending['row'],
                    entry_decision_clock=pending['clock'], support=support, stop=stop,
                    peak=side*(last_quote[0] if side == 1 else last_quote[1]), active=False,
                    initial_risk=(side*price-stop)*q*multiplier+2*fee, parent=parent)
                uid += 1
                orders.append((row, pending['row'], parent, side, q, price, 1, 10, fee, pending['clock'], stamp, side, uid))
                cash -= side*q*price*multiplier+fee
                pending = None
            else:
                side, entry = position['side'], position['price']
                price = last_quote[0] if side == 1 else last_quote[1]
                uid += 1
                orders.append((row, pending['row'], position['parent'], -side, q, price, 0,
                    pending['reason'], fee, pending['clock'], stamp, side, uid))
                gross = side*q*(price-entry)*multiplier
                net = gross-2*fee
                trades.append((position['parent'], position['entry_row'], row, side, q, entry, price, fee, fee, gross, net,
                    pending['reason'], position['entry_decision']))
                cash += side*q*price*multiplier-fee
                pending, position, last_exit, exited = None, None, stamp, True
        if position is not None and pending is None and good:
            side, entry = position['side'], position['price']
            quote = last_quote[0] if side == 1 else last_quote[1]
            signed_quote = side*quote
            position['peak'] = max(position['peak'], signed_quote)
            before = position['stop']
            lines = [side*position['support']-k*tick, side*entry-initial, None, None, None]
            if config['profit_trail']:
                position['active'] |= position['peak']-side*entry >= fee_width+k*tick
                if position['active']:
                    lines[3], lines[4] = position['peak']-k*tick, side*entry+fee_width
            else:
                lines[2] = position['peak']-wide
            effective = max([position['stop']]+[line for line in lines if line is not None])
            position['stop'] = effective
            owners = sum(1 << j for j, line in enumerate(lines) if line == effective)
            hits = [int(line is not None and signed_quote <= line) for line in lines]
            reason = next((j+1 for j, line in enumerate(lines) if line == effective), 0) if signed_quote <= effective else 0
            if reason:
                pending = dict(kind='exit', row=row, clock=stamp, reason=reason)
            judgments[(position['parent'], row)] = (row, record['seq'][row], stamp, position['parent'], 3 if pending else 2,
                side, 1, quote, position['support'],
                *[None if line is None else side*line for line in lines[:2]], side*position['peak'],
                *[None if line is None else side*line for line in lines[2:]], int(position['active']),
                side*before, side*effective, owners, *hits, reason, position['entry_row'], fee_width, position['initial_risk'])
        if signal['event'][row]:
            allowed = position is None and pending is None and not exited and good and signal['entry_quality'][row] and not signal['entry_reset'][row]
            allowed &= stamp >= 300 and stamp < cut and (last_exit is None or stamp-last_exit >= 30)
            candidates.append((row, bool(allowed)))
            if allowed:
                parent += 1
                pending = dict(kind='entry', row=row, clock=stamp, side=int(signal['event'][row]), support=signal['support_price'][row])
        trace = [0]*6
        equity = cash
        if position is not None:
            side = position['side']
            liquidation = last_quote[0] if side == 1 else last_quote[1]
            equity += side*q*liquidation*multiplier-fee
            trace[0 if side == 1 else 1] = q
            trace[2 if side == 1 else 3] = q
            if pending is not None:
                trace[5] = q
        elif pending is not None:
            trace[2 if pending['side'] == 1 else 3], trace[4] = q, q
        curves.append(equity)
        traces.append(trace)
        stale.append(not good)
    return dict(orders=orders, trades=trades, curve=curves, trace=traces, stale=stale, judgments=judgments,
                candidates=candidates, cash=cash, initial_width=initial, fee_width=fee_width)


def numerical(rows: list, width: int) -> np.ndarray:
    """
    機能: 独立Fraction期待値を、比較する物理列だけの数値へ変換する。
    引数: rows(list)、width(int)は行列幅。
    返り値: ndarray[float]は空行も含む期待値。NoneはNaNへ写す。
    """
    return np.array([[np.nan if value is None else float(value) for value in row] for row in rows], float).reshape(-1, width)


def compare(actual: dict, expected: dict) -> int:
    """
    機能: 注文・親・全玉時価・保有・途中判断を、独立期待値と一致させる。
    引数: actual/expected(dict)は本体人工と別oracle。
    返り値: intは比較した途中判断の数。経済ヘルパーの自己一致へ依存しない。
    """
    order_fields = [0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16]
    trade_fields = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15]
    np.testing.assert_allclose(actual['orders'][:, order_fields], numerical(expected['orders'], len(order_fields)), rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual['trades'][:, trade_fields], numerical(expected['trades'], len(trade_fields)), rtol=0, atol=1e-9)
    np.testing.assert_allclose(actual['curve'], [float(x) for x in expected['curve']], rtol=0, atol=1e-9)
    np.testing.assert_array_equal(actual['target_trace'], expected['trace'])
    np.testing.assert_array_equal(actual['stale_equity'], expected['stale'])
    assert actual['stats'][15] == float(expected['cash'])
    assert actual['initial_width'] == float(expected['initial_width'])
    for judgment in actual['judgments']:
        key = int(judgment[3]), int(judgment[0])
        np.testing.assert_allclose(judgment, numerical([expected['judgments'][key]], 28)[0], rtol=0, atol=1e-9, equal_nan=True)
    actual_keys = {(int(row[3]), int(row[0])) for row in actual['judgments']}
    critical_keys = {key for key, row in expected['judgments'].items() if row[0] == row[25] or row[24] != 0}
    assert critical_keys <= actual_keys
    expected_candidates = np.array(expected['candidates'], float).reshape(-1, 2)
    np.testing.assert_array_equal(actual['candidate_diagnostics'][:, [0, 8]], expected_candidates)
    return len(actual['judgments'])


def prefix(record: dict, signal: dict, size: int) -> tuple[dict, dict]:
    """
    機能: 元の既知limitを維持したまま人工の観測接頭だけを作る。
    引数: record/signal(dict)、size(int)は残す原行数。
    返り値: tuple[dict,dict]は接頭。端点を新しい場末へ変更しない。
    """
    reduced = {name: value[:size].copy() if isinstance(value, np.ndarray) else value for name, value in record.items()}
    smaller = {name: value[:size].copy() if isinstance(value, np.ndarray) else value for name, value in signal.items()}
    smaller['decisions'] = [deepcopy(row) for row in signal['decisions'] if row['row'] < size]
    return reduced, smaller


# ----------------------------------------


def main() -> None:
    """
    機能: 固定人工だけでB/T出口と会計を独立に判定し、現在sourceへ証跡を結ぶ。
    引数: なし。
    返り値: None。reviewへ小JSONを保存する。正式再生・原本・APIは0。
    """
    sources = [ROOT/'engine/core.py', ROOT/'engine/interface.py', ROOT/'engine/支持境界と利益保険及び予約順序の人工検査.json',
               ROOT/'catalog.py', ROOT/'数値設計案.json', Path(__file__)]
    before = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    # ownerのNumba保存cacheが参照する実装名へ接続し、金融ロジックは変更しない。
    engine, catalog = load('104の支持境界と利益追尾執行', ROOT/'engine/core.py'), load('104独立経済条件', ROOT/'catalog.py')
    cases = ('平坦で長く保持', '支持ちょうど', '支持一呼値手前', '支持から遠いfill', '支持線を越えたfill',
        '利益発動後に次quote悪化', '利益発動一呼値不足', '広い追尾の大波', '新規予約後の資格悪化',
        '返済予約中の不明', 'cutと新規fill競合', '受付境界と返済後停止', '未知時価の評価だけ保持',
        '場末まで正常quoteなし', '候補なし')
    counts = dict(独立経済ケース=0, 独立途中判断=0, 接頭と未来改変=0, 完全入力偽装拒否=0, 未返済隠蔽拒否=0,
                  必須quote_valid欠測拒否=0, 方向反転等価=0)
    mirrors = {}
    for symbol, cap in (('TOPIX', 10), ('NK225', 20)):
        for quantity in (1, cap//2):
            for side in (1, -1):
                for exit_id in ('B1', 'B2', 'B4', 'T2', 'T4'):
                    config = dict(catalog.exit_config(exit_id), quantity=quantity)
                    for case in cases:
                        CURRENT.update(商品=symbol, 枚数=quantity, 方向=side, 出口=exit_id, 人工条件=case)
                        record, signal = fixture(symbol, side, exit_id, quantity, case)
                        expected = oracle(record, signal, config)
                        actual = engine.execute(record, signal, config, finish=False)
                        counts['独立途中判断'] += compare(actual, expected)
                        counts['独立経済ケース'] += 1
                        if not actual['target_trace'][-1].any():
                            complete = engine.execute(record, signal, config, finish=True)
                            np.testing.assert_array_equal(complete['orders'], actual['orders'])
                        else:
                            try:
                                engine.execute(record, signal, config, finish=True)
                            except AssertionError:
                                counts['未返済隠蔽拒否'] += 1
                            else:
                                raise AssertionError('未返済がある完全入力を受理しました。')
                        key = symbol, quantity, exit_id, case
                        economic = actual['trades'][:, [2, 3, 5, 8, 9, 10, 11, 13]]
                        if side == 1:
                            mirrors[key] = economic
                        else:
                            np.testing.assert_array_equal(economic, mirrors[key])
                            counts['方向反転等価'] += 1
                        if quantity == 1 and case in ('平坦で長く保持', '支持線を越えたfill', '利益発動後に次quote悪化', '返済予約中の不明'):
                            for size in range(1, len(record['seq'])):
                                reduced, smaller = prefix(record, signal, size)
                                partial = engine.execute(reduced, smaller, config, finish=False)
                                compare(partial, oracle(reduced, smaller, config))
                                np.testing.assert_array_equal(partial['orders'], actual['orders'][actual['orders'][:, 0] < size])
                                np.testing.assert_array_equal(partial['curve'], actual['curve'][:size])
                                np.testing.assert_array_equal(partial['target_trace'], actual['target_trace'][:size])
                                future = deepcopy(record)
                                future['bid'][size:] -= 100*record['tick']
                                future['ask'][size:] -= 100*record['tick']
                                changed = engine.execute(future, signal, config, finish=False)
                                np.testing.assert_array_equal(changed['orders'][changed['orders'][:, 0] < size], partial['orders'])
                                np.testing.assert_array_equal(changed['curve'][:size], partial['curve'])
                                counts['接頭と未来改変'] += 1
                        if case == '候補なし':
                            reduced, smaller = prefix(record, signal, 2)
                            try:
                                engine.execute(reduced, smaller, config, finish=True)
                            except AssertionError:
                                counts['完全入力偽装拒否'] += 1
                            else:
                                raise AssertionError('flat接頭を完全入力へ誤認しました。')
                            invalid = dict(record)
                            del invalid['quote_valid']
                            try:
                                engine.execute(invalid, signal, config, finish=True)
                            except KeyError:
                                counts['必須quote_valid欠測拒否'] += 1
                            else:
                                raise AssertionError('必須quote_valid欠測をfallbackで救済しました。')
    after = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    assert before == after, '独立人工中に検査対象sourceが変わりました。'
    proof = dict(全合格=True, scope='104 B1/B2/B4/T2/T4の固定人工。旧O正式32nullと新104正式金融を含まない。',
        検査件数=counts, 人工条件=list(cases), SHA256=before,
        独立性='買売をd*price座標へ写し、Fraction価格線・Decimal注文料・予約順序の別モデルで、自己会計helperを使わず照合した。',
        限界='正常quoteの指定価格約定モデル。遅延最悪約定・潜在板・受信順・将来収益の保証ではない。',
        実行=dict(新104正式金融=0, 原本読取=0, 保存cache読取=0, 旧金融損益読取=0, API=0, 実注文=0))
    target = HERE/'停止予約と注文経済の独立人工.json'
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=counts, 証跡=str(target), SHA256=sha(target)), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        folder = HERE/('独立出口人工False_'+time.strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(exist_ok=False)
        original = Path(__file__).read_bytes()
        (folder/Path(__file__).name).write_bytes(original)
        (folder/'False.json').write_text(json.dumps(dict(全合格=False, 人工条件=CURRENT, 例外=str(error),
            traceback=traceback.format_exc(), 独立sourceSHA256=hashlib.sha256(original).hexdigest(),
            新104正式金融=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
