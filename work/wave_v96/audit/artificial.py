"""18出口の意味ある価格経路を、両商品と上下反射で独立再生する。"""

from copy import deepcopy
import hashlib
from pathlib import Path
import socket

import numpy as np

import common
import independent

SCENARIOS = ('初期SL等号', '保護開始直前', '費用床と次気配gap', '半分床の呼値切捨',
             '最大順行後のD40反落', '不正気配で停止を作らない', '期限と停止の同時成立',
             '長保有の場末返済', '返済予約中の欠測と回復', '実返済後30秒の再参加')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 人工検査の外部接続を禁止する。
    引数: args(tuple)、kwargs(dict)は接続引数。
    返り値: None。呼出し時は例外。
    """
    raise RuntimeError('保存又は人工データだけを使用します')


def fixture(symbol: str, side: int, scenario: str, config: dict) -> tuple[dict, dict, float]:
    """
    機能: 合法ラージ呼値で新出口の各条件へ実際に到達する価格経路を作る。
    引数: symbol/scenario(str)、side(int)、config(dict)。
    返り値: tuple[dict,dict,float]。人工原板、信号、既知始値。
    """
    base, tick = (4000., .5) if symbol == 'TOPIX' else (68000., 10.)
    n = 801
    times = 300. + np.arange(n) * 5.
    record = dict(symbol=symbol, session='人工96_Day', time_s=times, seq=np.arange(n),
                  tick=tick, start=0., limit=float(times[-1]),
                  quote_valid=np.ones(n, bool), price_valid=np.ones(n, bool))
    initial, trail, protected = independent.widths(record, config, base)
    moves = np.full(n, -tick)
    if scenario == '初期SL等号':
        moves[10:] = -initial
        moves[11:] -= tick
    elif scenario == '保護開始直前':
        moves[10:20] = 2 * initial - tick
        moves[20:] = -initial
    elif scenario == '費用床と次気配gap':
        moves[10:20] = 2 * initial
        moves[20:] = protected
        moves[21:] = -2 * initial
    elif scenario == '半分床の呼値切捨':
        progress = 2 * initial + 3 * tick
        moves[10:20] = progress
        moves[20:] = np.floor(progress * .5 / tick) * tick
        moves[21:] -= tick
    elif scenario == '最大順行後のD40反落':
        moves[10:20] = 3 * trail
        moves[20:] = 2 * trail
        moves[21:] -= tick
    elif scenario == '不正気配で停止を作らない':
        moves[10:15] = -2 * initial
        record['quote_valid'][10:15] = False
        moves[15:20] = 2 * initial
        moves[20:] = 0
    elif scenario == '期限と停止の同時成立':
        moves[362:] = -initial
    elif scenario == '長保有の場末返済':
        moves[10:] = initial
    elif scenario == '返済予約中の欠測と回復':
        moves[10:15] = -initial
        record['quote_valid'][11:15] = False
        moves[15:] = 2 * initial
    elif scenario == '実返済後30秒の再参加':
        moves[10:16] = -initial
        moves[16:] = 0
    event = np.zeros(n, np.int8)
    event[1] = 1
    if scenario == '実返済後30秒の再参加':
        event[16], event[17] = 1, -1
    bid = base + tick + moves
    ask = bid + tick
    if side == -1:
        bid, ask = 2 * base + tick - ask, 2 * base + tick - bid
        event *= -1
    record.update(bid=bid, ask=ask, price=(bid + ask) * .5)
    signal = dict(grid=times.copy(), mapped=np.arange(n, dtype=np.int32), mode=np.zeros(n, np.int8),
                  quality=np.ones(n, bool), reset=np.zeros(n, bool), event=event,
                  trend_width=trail, trend_initial_stop_width=initial)
    for name in ('bid', 'ask'):
        common.exact(record[name] / tick, np.round(record[name] / tick), '合法呼値')
    return record, signal, base


def prefix(record: dict, signal: dict, cut: int) -> tuple[dict, dict]:
    """
    機能: 既知セッション末を保持したまま、原板と対応信号を接頭部に切断する。
    引数: record/signal(dict)、cut(int)は残す行数。
    返り値: tuple[dict,dict]。終端清算を追加しない人工接頭部。
    """
    n = len(record['time_s'])
    shorten = lambda data: {k: v[:cut].copy() if isinstance(v, np.ndarray) and len(v) == n else deepcopy(v)
                             for k, v in data.items()}
    return shorten(record), shorten(signal)


def main() -> None:
    """
    機能: 全18人工、独立出口23/27列、経済null、人工接頭部不変を証跡へ保存する。
    引数: なし。
    返り値: None。不一致を修正せず例外で停止する。
    """
    socket.create_connection = deny
    catalog = common.module('96独立人工条件', common.BASE / 'catalog.py')
    engine = common.module('96独立人工本体', common.BASE / 'engine.py')
    counts = dict(経路=0, 注文=0, 決済親=0, 原板行=0, 接頭部=0, 未来変形=0, S40経済null=0)
    signatures, reached = {}, {}
    for config in catalog.catalog():
        for symbol in catalog.SYMBOLS:
            for side in (1, -1):
                for scenario in SCENARIOS:
                    record, signal, reference = fixture(symbol, side, scenario, config)
                    actual = engine.execute(record, signal, config)
                    checked = independent.compare(record, signal, config, reference, actual)
                    assert len(actual['trades']) >= 1
                    for name, amount in checked.items():
                        counts[name] += amount
                    counts['経路'] += 1
                    first = actual['trend_parent_diagnostics'][0]
                    if scenario == '初期SL等号':
                        assert first[14] == 10 and first[23] == 1
                    if scenario == '期限と停止の同時成立':
                        assert first[14] == 362 and first[23] == (3 if config['trend_hold_seconds'] else 1)
                    if scenario == '長保有の場末返済':
                        assert first[23] == (3 if config['trend_hold_seconds'] else 4)
                    if scenario == '保護開始直前':
                        assert actual['trend_exit_state_trace'][10, 14] == 0
                    if scenario == '費用床と次気配gap' and config['trend_protection_mode']:
                        assert actual['trend_exit_state_trace'][10, 14] == 1
                        assert first[14] == 20 and first[25] < 0, '停止床は次BBO約定益を保証しない'
                    if scenario == '返済予約中の欠測と回復':
                        assert first[14] == 10 and first[2] == 15 and first[25] > 0
                    if scenario == '実返済後30秒の再参加':
                        assert len(actual['trades']) == 2 and actual['orders'][2, 1] == 17
                    reached[config['id'] + '/' + symbol + '/' + str(side) + '/' + scenario] = dict(
                        初回判断行=int(first[14]), 初回fill行=int(first[2]), 理由=int(first[23]))
                    if config['trend_initial_stop_bp'] == 40:
                        key = (symbol, side, scenario, config['trend_hold_seconds'])
                        value = [actual[name].tobytes() for name in ('orders', 'trades', 'target_trace', 'curve')]
                        if key in signatures:
                            assert value == signatures[key]
                            counts['S40経済null'] += 1
                        else:
                            signatures[key] = value
                    if scenario in ('費用床と次気配gap', '返済予約中の欠測と回復'):
                        for cut in (10, 11, 15, 25):
                            short_record, short_signal = prefix(record, signal, cut)
                            short = engine.execute(short_record, short_signal, config, finish=False)
                            independent.compare(short_record, short_signal, config, reference, short)
                            for name in ('orders', 'trades', 'trend_parent_diagnostics'):
                                row_column = 2 if name == 'trend_parent_diagnostics' else 3 if name == 'trades' else 0
                                common.exact(short[name], actual[name][actual[name][:, row_column] < cut], '人工切断/' + name)
                            for name in ('target_trace', 'curve', 'trend_exit_state_trace'):
                                common.exact(short[name], actual[name][:cut], '人工切断/' + name)
                            counts['接頭部'] += 1
                            future_record, future_signal = deepcopy(record), deepcopy(signal)
                            future_record['bid'][cut:] += 20 * record['tick']
                            future_record['ask'][cut:] += 20 * record['tick']
                            future_signal['event'][cut:] *= -1
                            future = engine.execute(future_record, future_signal, config, finish=False)
                            for name in ('target_trace', 'curve', 'trend_exit_state_trace'):
                                common.exact(future[name][:cut], actual[name][:cut], '人工未来/' + name)
                            counts['未来変形'] += 1
        print(config['id'] + ': 人工独立出口と料金及び接頭部が一致', flush=True)
    paths = [common.BASE / 'engine.py', common.BASE / 'strategy.py', common.BASE / 'catalog.py',
             Path(__file__), common.HERE / 'common.py', common.HERE / 'independent.py']
    common.save(common.HERE / '全18人工価格経路と独立出口及び料金と未来不変.json', dict(
        合格=True, 検査件数=counts, 到達した初回条件=reached, SHA256=common.fingerprint(paths),
        比較='注文/親/保有/23出口状態/27親診断は公差0。全原板現金の演算順だけ絶対1e-5。',
        旧変更=0, 正式96損益=0, API取得=0, 実注文=0))
    print('人工最終証跡保存及び再読込: 合格', flush=True)


if __name__ == '__main__':
    main()
