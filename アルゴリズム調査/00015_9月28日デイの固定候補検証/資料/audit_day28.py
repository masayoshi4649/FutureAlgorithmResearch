"""固定済み二条件の追加日中再生を、原本価格・足・全台帳から独立検算する。"""

from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
MULT = {'TOPIX': 1000., 'NK225': 10.}


def module(path: Path, name: str):
    """機能: 監査対象の実装を、旧成果を変更せず別名で読み込む。

    引数: path (Path)、name (str)。返り値: 読み込んだモジュール (module)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def read(name: str):
    """機能: 今回作業の保存済み入力を読み込む。

    引数: name (str)。返り値: 保存内容 (object)。
    """
    path = OUT / name
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf-8'))


def check_input(ready: dict) -> dict:
    """機能: 原本同一行の価格・時刻、独立計算した過去足ATRを全行照合する。

    引数: ready (dict)。返り値: 検査件数など (dict)。
    """
    symbol, session = ready['symbol'], ready['session']
    wanted = ready['seq']
    assert np.all(np.diff(wanted) > 0)
    assert np.all(np.diff(ready['time_s']) >= 0)
    index = 0
    with (ROOT / 'book' / symbol / f'{session}.jsonl').open('rb') as source:
        for seq, line in enumerate(source):
            if index < len(wanted) and seq == wanted[index]:
                raw = json.loads(line)
                assert raw['CurrentPrice'] == ready['last'][index]
                assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == ready['time_s'][index]
                index += 1
    assert index == len(wanted)
    bars = pd.read_csv(ROOT / 'candle_5min' / symbol / f'{session}.csv')
    bars = bars.loc[bars.closed.astype(str).str.lower().eq('true')].copy()
    available = pd.to_datetime(bars.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 360.
    assert np.all(np.diff(available) > 0)
    values, previous_close, smooth = [], None, None
    for number, row in enumerate(bars.itertuples(index=False)):
        tr = row.high - row.low
        if previous_close is not None:
            tr = max(tr, abs(row.high - previous_close), abs(row.low - previous_close))
        smooth = tr if smooth is None else smooth * (11. / 12.) + tr / 12.
        values.append(max(smooth, ready['tick'] * 2) if number >= 2 else np.nan)
        previous_close = row.close
    positions = np.searchsorted(available, ready['time_s'], side='right') - 1
    own_atr = np.full(len(wanted), np.nan)
    valid = positions >= 0
    own_atr[valid] = np.asarray(values)[positions[valid]]
    np.testing.assert_allclose(own_atr, ready['atr'], rtol=1e-12, atol=1e-9, equal_nan=True)
    assert np.all(available[positions[valid]] <= ready['time_s'][valid])
    return dict(セッション=session, 銘柄=symbol, 原本価格時刻一致行数=index, ATR一致行数=index,
                五分足公開遅延秒=360, 将来足参照なし=True)


def rounded(value: float, tick: float, side: int) -> float:
    """機能: 売買方向へ逆指値水準を呼値単位に丸める。

    引数: value/tick (float)、side (int)。返り値: 丸めた価格 (float)。
    """
    return float((np.ceil(value / tick - 1e-9) if side > 0 else np.floor(value / tick + 1e-9)) * tick)


def exit_check(ready: dict, trade: np.ndarray, cycle: np.ndarray, config: dict) -> None:
    """機能: 固定枚数取引の初期損切り・追跡・保有時間・場末の最初の出口を独立計算する。

    引数: ready/config (dict)、trade/cycle (ndarray)。返り値: なし (None)。
    """
    en, actual_exit = int(trade[6]), int(trade[7])
    direction, anchor, atr = int(trade[2]), float(trade[4]), float(cycle[5])
    price, time, tick = ready['last'], ready['time_s'], ready['tick']
    stop = rounded(anchor - direction * config['stop_atr'] * atr, tick, -direction)
    extreme, main, pending = anchor, np.nan, 0
    for index in range(en, actual_exit + 1):
        current = price[index]
        if index > en:
            reason, fill = pending, current
            if not reason:
                choices = []
                for level, kind in [(stop, 1), (main, 2)]:
                    if np.isfinite(level) and -direction * (current - level) >= -1e-8:
                        passed = -direction * (price[index - 1] - level) >= -1e-8
                        distance = 0. if passed else max(0., -direction * (level - price[index - 1]))
                        choices.append((distance, kind, current if passed else level))
                if choices:
                    _, reason, fill = min(choices, key=lambda item: (item[0], item[1]))
            if reason:
                assert index == actual_exit, ('先行する返済条件', ready['symbol'], en, index, actual_exit)
                assert reason == int(trade[9]), ('返済理由', reason, trade[9])
                np.testing.assert_allclose(fill, trade[5], rtol=0, atol=1e-8)
                return
        extreme = max(extreme, current) if direction > 0 else min(extreme, current)
        if direction * (extreme - anchor) >= config['activation_atr'] * atr:
            candidate = rounded(extreme - direction * config['main_trail'] * atr, tick, -direction)
            if not np.isfinite(main) or direction * (candidate - main) > 0:
                main = candidate
        pending = 9 if time[index] >= ready['limit'] else (8 if time[index] - time[en] >= config['timeout_min'] * 60 else 0)
    raise AssertionError('記録された返済の成立を確認できません')


def check_result(key: tuple, block: dict, ready: dict, direction: np.ndarray, config: dict) -> dict:
    """機能: 返済・注文・場末数量・全行資産を独立再構築して照合する。

    引数: key (tuple)、block/ready/config (dict)、direction (ndarray)。返り値: 検算指標 (dict)。
    """
    trades, cycles, orders, stats = (block[name] for name in ['trades', 'cycles', 'orders', 'stats'])
    quantity = config['initial_qty']
    assert quantity == config['audit_cap'] == 1
    assert len(trades) == len(cycles) and len(orders) == 2 * len(trades)
    assert np.all(orders[:, 1] < orders[:, 0])
    assert np.all(trades[:, 3] == quantity) and np.all(trades[:, 8] == 0)
    np.testing.assert_array_equal(orders[:, 7], np.tile([1, 0], len(trades)))
    en, ex = trades[:, 6].astype(int), trades[:, 7].astype(int)
    assert np.all(en < ex) and np.all(en[1:] > ex[:-1])
    assert np.all(ready['time_s'][en] >= ready['start'] + 1200)
    assert np.all(ready['time_s'][en] < ready['limit'] - 1800)
    assert np.all(ready['time_s'][en[1:]] - ready['time_s'][ex[:-1]] >= 300)
    for trade, cycle, opening in zip(trades, cycles, orders[::2]):
        source = int(opening[1])
        assert direction[source] == trade[2]
        np.testing.assert_allclose(cycle[5], ready['atr'][source], rtol=0, atol=1e-8)
        expected = rounded(ready['last'][source] + trade[2] * config['entry_atr'] * cycle[5], ready['tick'], int(trade[2]))
        np.testing.assert_allclose(expected, trade[4], rtol=0, atol=1e-8)
        exit_check(ready, trade, cycle, config)
    values = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
    np.testing.assert_allclose(values, trades[:, 10], rtol=0, atol=1e-8)
    np.testing.assert_allclose(values, cycles[:, 3], rtol=0, atol=1e-8)
    size = len(ready['seq'])
    signed_qty = trades[:, 2] * trades[:, 3]
    changes = np.bincount(en, weights=signed_qty, minlength=size) - np.bincount(ex, weights=signed_qty, minlength=size)
    inventory = np.cumsum(changes)
    cash_changes = np.bincount(en, weights=-signed_qty * trades[:, 4], minlength=size) + np.bincount(ex, weights=signed_qty * trades[:, 5], minlength=size)
    cash = np.cumsum(cash_changes)
    equity = cash + inventory * ready['last']
    assert inventory[-1] == stats[9] == 0 and max(abs(inventory)) <= quantity
    peaks = np.maximum.accumulate(np.r_[0., equity])[1:]
    expected_stats = {0: values.sum(), 1: max(peaks - equity), 2: max(np.maximum(inventory, 0)),
                      3: max(np.maximum(-inventory, 0)), 4: max(abs(inventory)), 5: max(abs(inventory)),
                      7: min(0., min(equity)), 8: max(0., max(equity))}
    for index, expected in expected_stats.items():
        np.testing.assert_allclose(stats[index], expected, rtol=0, atol=1e-8)
    if len(block['curve']) == size:
        np.testing.assert_allclose(block['curve'][:, 0], equity, rtol=0, atol=1e-8)
    currency = values * MULT[ready['symbol']]
    return dict(手法=key[0], セッション=key[1], 銘柄=key[2], 取引数=len(values),
                利益=float(currency[currency > 0].sum()), 損失=float(-currency[currency < 0].sum()), 収支=float(currency.sum()),
                勝ち枚数=int((currency > 0).sum()), 負け枚数=int((currency < 0).sum()),
                原本全行会計一致数=size, 場末在庫ゼロ=True, 入口と最初の出口の独立計算一致=True)


def main() -> None:
    """機能: 当日の保存済み入力と固定条件の結果だけを監査してJSONへ保存する。

    引数: なし。返り値: なし (None)。現在API取得とパラメータ探索は行わない。
    """
    sys.path.insert(0, str(ROOT / 'work/wave_v19'))
    import engine
    signals = module(ROOT / 'work/wave_v19/signal_variants.py', 'day28_audit_signals')
    bundle = read('再生台帳.pkl')
    inputs, states, directions = (bundle[name] for name in ['inputs', 'states', 'directions'])
    blocks = {(identifier, '2026-09-28_Day', symbol): block
              for (identifier, symbol, quantity), block in bundle['blocks'].items() if quantity == 1}
    frozen = json.loads((ROOT / 'work/wave_v19/主候補の条件.json').read_text(encoding='utf-8'))
    config_base = frozen['一枚でのエンジン設定']
    input_checks = [check_input(ready) for ready in inputs.values()]
    expected_direction = signals.build_one(frozen['信号条件'], inputs, states)
    for key in inputs:
        np.testing.assert_array_equal(expected_direction[key], directions[key])
    records = []
    for key, block in blocks.items():
        config = block.get('config', dict(config_base, timeout_min=360. if key[0] == 'V0800' else 180.))
        assert config['timeout_min'] == (360. if key[0] == 'V0800' else 180.)
        ready, direction = inputs[key[1:]], directions[key[1:]]
        records.append(check_result(key, block, ready, direction, config))
    summaries = {(row['method_id'], row['symbol'], row['quantity']): row for row in read('結果.json')}
    assert len(summaries) == len(bundle['blocks']) == 8
    for key, block in bundle['blocks'].items():
        row = summaries[key]
        values = block['trades'][:, 10] * MULT[key[1]]
        quantity = block['trades'][:, 3]
        winning, losing = values > 1e-6, values < -1e-6
        expected = dict(gross_profit_yen=values[winning].sum(), gross_loss_yen=-values[losing].sum(),
                        net_yen=values.sum(), profit_units=quantity[winning].sum(), loss_units=quantity[losing].sum(),
                        unit_balance=quantity[winning].sum()-quantity[losing].sum(), closed_units=quantity.sum(),
                        cycles=len(block['cycles']), drawdown_yen=block['stats'][1]*MULT[key[1]])
        for field, value in expected.items():
            np.testing.assert_allclose(row[field], value, rtol=0, atol=1e-8)
        assert block['stats'][9] == 0
    # ----------------------------------------
    # 未来行を取り除き、公開済み足抽出から方向・売買を再計算する。
    prefixes = []
    for elapsed in [90 * 60, 180 * 60, 300 * 60]:
        parts = {}
        for key, ready in inputs.items():
            count = int(np.searchsorted(ready['time_s'], ready['start'] + elapsed, side='right'))
            parts[key] = {name: value[:count].copy() if isinstance(value, np.ndarray) and len(value) == len(ready['seq']) else value
                          for name, value in ready.items() if name != 'families'}
        part_directions = signals.build_one(frozen['信号条件'], parts, states)
        for key, block in blocks.items():
            ready, side = parts[key[1:]], part_directions[key[1:]]
            count = len(ready['seq'])
            np.testing.assert_array_equal(side, directions[key[1:]][:count])
            config = block.get('config', dict(config_base, timeout_min=360. if key[0] == 'V0800' else 180.))
            result = engine.run(ready, side, config, detail=True)
            for field, index in [('trades', 7), ('cycles', 2), ('orders', 0)]:
                expected = block[field][block[field][:, index] < count]
                np.testing.assert_allclose(result[field], expected, rtol=0, atol=1e-8)
            prefixes.append(dict(手法=key[0], 銘柄=key[2], 打切り開始後分=elapsed / 60, 一致=True))
    # ----------------------------------------
    # 許容される全固定数量の再生経路と金額比例を確認する。
    scales = []
    for key, block in blocks.items():
        ready, direction = inputs[key[1:]], directions[key[1:]]
        base = block.get('config', dict(config_base, timeout_min=360. if key[0] == 'V0800' else 180.))
        cap = 10 if key[2] == 'TOPIX' else 20
        for quantity in range(1, cap + 1):
            config = dict(base, initial_qty=quantity, audit_cap=quantity)
            result = engine.run(ready, direction, config)
            expected = block['trades'].copy()
            expected[:, [3, 10]] *= quantity
            np.testing.assert_allclose(result['trades'], expected, rtol=0, atol=1e-8)
            expected_orders = block['orders'].copy()
            expected_orders[:, 4] *= quantity
            np.testing.assert_allclose(result['orders'], expected_orders, rtol=0, atol=1e-8)
            if (key[0], key[2], quantity) in bundle['blocks']:
                saved = bundle['blocks'][(key[0], key[2], quantity)]
                for field in ['trades', 'orders', 'cycles', 'stats']:
                    np.testing.assert_allclose(result[field], saved[field], rtol=0, atol=1e-8)
            assert result['stats'][2] <= cap and result['stats'][3] <= cap and result['stats'][9] == 0
            scales.append(dict(手法=key[0], 銘柄=key[2], 枚数=quantity, 一致=True))
    result = dict(合格=True, API取得数=0, 新規条件探索数=0, 原本入力=input_checks, 独立会計=records, 保存集計検算セル数=len(summaries),
                  途中切断件数=len(prefixes), 途中切断=prefixes, 全許容固定枚数の再生件数=len(scales), 全許容固定枚数=scales,
                  限界='CurrentPriceTimeは受信時刻ではない。既存ルールと同じ代理時刻・原本行順での因果性を検査した。')
    (OUT / 'audit_day28.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ['途中切断', '全許容固定枚数']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
