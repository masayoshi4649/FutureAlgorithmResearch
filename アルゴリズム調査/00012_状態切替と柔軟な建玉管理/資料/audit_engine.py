"""建玉の役割から独立した現金勘定と人工価格経路で状態機械を検算する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import engine

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DEFAULT = dict(initial_qty=10, entry_atr=.25, stop_atr=1., main_trail=2.,
               add_mode=1, add_step=.5, add_qty=10, hedge_ratio=.5,
               hedge_trigger=.75, cover_add=1, cover_step=.5, cover_trail=.5,
               reverse_mode=1, lock_fraction=.5, split_target=0., timeout_min=180.,
               neutral_min=0., us_mode=0)


def equal(actual: np.ndarray, expected: np.ndarray, label: str) -> None:
    """機能: 浮動小数の丸め誤差だけを許し、独立計算と照合する。

    引数: actual/expected (ndarray)、label (str)。返り値: なし (None)。
    """
    if not np.allclose(actual, expected, rtol=1e-12, atol=1e-6):
        raise AssertionError(f'{label}: 最大差 {np.max(np.abs(actual-expected))}')


def inspect(ready: dict, result: dict, require_closed: bool = True) -> dict:
    """機能: 売買から現金と数量を再構築し、全行の資産・台帳・上限を照合する。

    引数: ready/result (dict)、require_closed (bool)。返り値: 検査件数 (dict)。
    """
    price = ready['last']
    n = len(price)
    orders, trades, curve, cycles = (result[k] for k in ['orders', 'trades', 'curve', 'cycles'])
    assert len(curve) == n
    assert np.all(np.isfinite(price)) and np.all(price > 0)
    rows = orders[:, 0].astype(np.int64)
    assert np.all((rows >= 0) & (rows < n))
    assert np.all(np.diff(rows) >= 0)
    assert np.all(orders[:, 1] < orders[:, 0]), '成立行より後で約定していません'
    assert np.all(orders[:, 1] >= 0), '原本に存在しない発注元です'
    assert np.all(orders[:, 4] > 0) and np.all(orders[:, 4] == np.floor(orders[:, 4]))
    assert np.all(np.isin(orders[:, 3], [-1, 1]))
    assert np.all(np.isin(orders[:, 7], [0, 1]))
    lower = np.minimum(price[rows-1], price[rows])
    upper = np.maximum(price[rows-1], price[rows])
    assert np.all((orders[:, 5] >= lower-1e-8) & (orders[:, 5] <= upper+1e-8)), \
        '直前行と現在行の価格範囲外へ、新規生成した注文を遡及約定しています'

    # ----------------------------------------
    # 約定だけから現金とネット数量、役割を使わない両側数量を再構築する。
    signed = orders[:, 3] * orders[:, 4]
    delta_cash, delta_net = np.zeros(n), np.zeros(n)
    delta_long, delta_short = np.zeros(n), np.zeros(n)
    np.add.at(delta_cash, rows, -signed * orders[:, 5])
    np.add.at(delta_net, rows, signed)
    opened = orders[:, 7] == 1
    long_change = np.where(opened, np.where(signed > 0, signed, 0), np.where(signed < 0, signed, 0))
    short_change = np.where(opened, np.where(signed < 0, -signed, 0), np.where(signed > 0, -signed, 0))
    np.add.at(delta_long, rows, long_change)
    np.add.at(delta_short, rows, short_change)
    cash, net = np.cumsum(delta_cash), np.cumsum(delta_net)
    long_qty, short_qty = np.cumsum(delta_long), np.cumsum(delta_short)
    equity = cash + net * price
    equal(curve[:, 0], equity, '全行の総資産')
    equal(curve[:, 2], long_qty, '買い数量')
    equal(curve[:, 3], short_qty, '売り数量')
    equal(curve[:, 5], cash, '現金勘定')
    equal(curve[:, 6], net, 'ネット数量')
    assert np.all((long_qty >= 0) & (long_qty <= 100)), '買い100単位上限'
    assert np.all((short_qty >= 0) & (short_qty <= 100)), '売り100単位上限'
    high = np.maximum.accumulate(np.maximum(equity, 0))
    dd = np.maximum.accumulate(high - equity)
    equal(curve[:, 4], dd, '全行の最大下落')

    # ----------------------------------------
    # 元約定の数量を減らし、昇格や部分返済でも建値が消えていないか確かめる。
    balances = {}
    for order in orders[opened]:
        key = (int(order[2]), int(order[0]), int(order[3]), float(order[5]))
        balances[key] = balances.get(key, 0) + int(order[4])
    pnl = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
    equal(trades[:, 10], pnl, '返済ごとの損益')
    assert np.all(trades[:, 6] < trades[:, 7]), '新規と返済が同じ行です'
    for trade in trades:
        key = (int(trade[0]), int(trade[6]), int(trade[2]), float(trade[4]))
        assert key in balances, f'元約定が不明です: {key}'
        balances[key] -= int(trade[3])
        assert balances[key] >= 0, f'元約定数量より多い返済です: {key}'
    closed_orders = orders[~opened]
    assert len(closed_orders) == len(trades)
    equal(closed_orders[:, 0], trades[:, 7], '返済注文の行')
    equal(closed_orders[:, 3], -trades[:, 2], '返済注文の方向')
    equal(closed_orders[:, 4], trades[:, 3], '返済注文の数量')
    equal(closed_orders[:, 5], trades[:, 5], '返済注文の価格')
    closed_delta = np.zeros(n)
    np.add.at(closed_delta, trades[:, 7].astype(np.int64), pnl)
    closed = np.cumsum(closed_delta)
    equal(curve[:, 1], closed, '全行の確定損益')
    for cycle in cycles:
        equal(np.array([cycle[3]]), np.array([pnl[trades[:, 0] == cycle[0]].sum()]), '組の損益')
    if require_closed:
        assert long_qty[-1] == 0 and short_qty[-1] == 0, 'セッション末尾に建玉があります'
        assert all(value == 0 for value in balances.values())
        equal(equity[-1:], closed[-1:], '最終確定損益')
        equal(cycles[:, 3].sum(keepdims=True), closed[-1:], '全組損益')
    assert result['stats'][6] <= 1e-6
    return dict(原本行数=n, 注文件数=len(orders), 返済件数=len(trades), 完了組数=len(cycles),
                最大買い単位=float(long_qty.max()), 最大売り単位=float(short_qty.max()),
                最終評価損益=float(equity[-1]), 最終確定損益=float(closed[-1]))


def path_ready(prices: list[float], sides: list[int] | None = None) -> tuple[dict, np.ndarray]:
    """機能: 次行処理と末尾返済を確かめるため、人工の有効原本列を作る。

    引数: prices (list[float])、sides (list[int]|None)。返り値: 入力と方向列 (tuple)。
    """
    values = np.asarray(prices + [prices[-1], prices[-1]], dtype=float)
    time = np.r_[1200. + np.arange(len(prices)) * 10, 4800., 4801.]
    state = np.asarray((sides or [1] * len(prices)) + [(sides or [1])[-1]] * 2, dtype=np.int64)
    return dict(time_s=time, last=values, atr=np.full(len(values), 10.), tick=1.,
                start=0., limit=4800., us_open=np.inf), state


def prefix(ready: dict, state: np.ndarray, config: dict, result: dict, cuts: list[int]) -> int:
    """機能: 未来を除いた入力で再実行し、打切り前の判断・約定・資産が同じか確かめる。

    引数: ready/result/config (dict)、state (ndarray)、cuts (list[int])。返り値: 比較した回数 (int)。
    """
    done = 0
    for cut in cuts:
        if cut <= 1 or cut >= len(state):
            continue
        part = dict(ready)
        for key in ['time_s', 'last', 'atr']:
            part[key] = ready[key][:cut]
        actual = engine.run(part, state[:cut], config, True)
        inspect(part, actual, False)
        equal(actual['curve'], result['curve'][:cut], '未来打切りの資産')
        equal(actual['orders'], result['orders'][result['orders'][:, 0] < cut], '未来打切りの注文')
        equal(actual['trades'], result['trades'][result['trades'][:, 7] < cut], '未来打切りの返済')
        done += 1
    return done


def synthetic() -> list[dict]:
    """機能: 主玉損切り、追跡、増玉、カバー利確、昇格、数量上限を既知解で検査する。

    引数: なし。返り値: 人工経路ごとの検査結果 (list[dict])。
    """
    base = dict(DEFAULT, entry_atr=0., main_trail=np.inf, add_mode=0, hedge_ratio=0.,
                cover_add=0, reverse_mode=0, lock_fraction=0., timeout_min=np.inf)
    cases = [
        ('初期損失上限', [100, 100, 96, 89, 88], None, {}, -100., [1]),
        ('主玉の追跡返済', [100, 100, 105, 112, 115, 108, 100], None, {'main_trail': .5}, 100., [2]),
        ('カバーだけ追跡利確', [100, 100, 112, 107, 100, 105], [1, 1, 1, 0, 0, 0],
         {'hedge_ratio': .5, 'hedge_trigger': .5}, 60., [3]),
        ('カバー昇格と反転', [100, 100, 98, 95, 95, 90], [1, 1, 1, -1, -1, -1],
         {'hedge_ratio': 1., 'hedge_trigger': .2, 'cover_trail': 100., 'reverse_mode': 1}, 30., [5]),
        ('順行増玉', [100, 100, 105, 110, 115, 120], None, {'add_mode': 1}, 500., []),
        ('押し目増玉', [100, 100, 95, 90, 85], None,
         {'add_mode': 2, 'stop_atr': 10.}, -300., []),
        ('両側100単位の上限', [100, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 160, 155, 150],
         [1] * 12 + [0, 0], {'add_mode': 1, 'hedge_ratio': 1., 'hedge_trigger': .5, 'cover_trail': 100.}, None, []),
    ]
    checks = []
    for name, prices, sides, changes, expected, reasons in cases:
        ready, state = path_ready(prices, sides)
        config = dict(base, **changes)
        result = engine.run(ready, state, config, True)
        checked = inspect(ready, result)
        if expected is not None:
            equal(result['stats'][:1], np.array([expected]), name)
        for reason in reasons:
            assert reason in result['trades'][:, 9], f'{name}: 想定する返済がありません'
        if name == 'カバー昇格と反転':
            promoted = result['trades'][result['trades'][:, 2] < 0]
            assert len(promoted) == 1 and promoted[0, 4] == 98 and promoted[0, 3] == 10
        if name == '両側100単位の上限':
            assert checked['最大買い単位'] == 100 and checked['最大売り単位'] == 100
        checked.update(経路=name, 未来打切り回数=prefix(ready, state, config, result, list(range(2, len(state)))))
        checks.append(checked)

        # ----------------------------------------
        # 価格と方向を鏡映し、買いと売りが同じ計算になることも確認する。
        mirror = dict(ready, last=300. - ready['last'])
        other = engine.run(mirror, -state, config, True)
        inspect(mirror, other)
        equal(other['curve'][:, 0], result['curve'][:, 0], name + 'の売買対称性')
    return checks


def real_checks() -> list[dict]:
    """機能: 保存20セル・３方向の同じ可変建玉条件を、独立会計と未来打切りで検査する。

    引数: なし。返り値: セルごとの監査結果 (list[dict])。通信は行わない。
    """
    inputs = {}
    for stage in ['development', 'holdout']:
        with (ROOT / 'work/wave_v16' / f'入力_{stage}.pkl').open('rb') as stream:
            inputs.update(pickle.load(stream))
    with (OUT / '主方向状態.pkl').open('rb') as stream:
        states = pickle.load(stream)
    checks = []
    for key, ready in inputs.items():
        for family, state in states[key].items():
            result = engine.run(ready, state, DEFAULT, True)
            checked = inspect(ready, result)
            cuts = [len(state) // 3, len(state) * 2 // 3]
            checked.update(セッション=key[0], 銘柄=key[1], 系統=family,
                           未来打切り回数=prefix(ready, state, DEFAULT, result, cuts))
            checks.append(checked)
    return checks


def selected_checks() -> list[dict]:
    """機能: 表示候補20セルと部分返済・米国時間分岐６セルを独立に検算する。

    引数: なし。返り値: 対象26セルの監査結果 (list[dict])。条件の再選択はしない。
    """
    import catalog

    inputs = {}
    for stage in ['development', 'holdout']:
        with (ROOT / 'work/wave_v16' / f'入力_{stage}.pkl').open('rb') as stream:
            inputs.update(pickle.load(stream))
    with (OUT / '主方向状態.pkl').open('rb') as stream:
        states = pickle.load(stream)
    configurations = {value['id']: value for value in catalog.configs()}
    target = {'NK225': 'M3_逆_A08', 'TOPIX': 'M2_逆_A02'}
    checks = []
    for key, ready in inputs.items():
        identifiers = [target[key[1]]]
        if key[0] == '2026-09-25_Night':
            stem = target[key[1]][:5]
            identifiers.extend(stem + manager for manager in ['C05', 'D03', 'D04'])
        for identifier in identifiers:
            config = configurations[identifier]
            state = states[key][config['signal']] * config['sign']
            result = engine.run(ready, state, config, True)
            checked = inspect(ready, result)
            reasons, counts = np.unique(result['trades'][:, 9].astype(int), return_counts=True)
            checked['返済理由の件数'] = {engine.REASONS[int(reason)]: int(count) for reason, count in zip(reasons, counts)}
            if config['manager'] in ['D03', 'D04']:
                orders = result['orders']
                entry = orders[orders[:, 6] == 20]
                stamps = ready['time_s'][entry[:, 0].astype(np.int64)]
                assert not np.any((stamps >= ready['us_open']-900) & (stamps < ready['us_open']+1800)), \
                    '米国開始休止中に新しい組を開始しています'
                checked['米国開始休止中の新規組'] = 0
                if config['manager'] == 'D04':
                    begin = int(np.searchsorted(ready['time_s'], ready['us_open']-900))
                    finish = int(np.searchsorted(ready['time_s'], ready['us_open']+1800))
                    assert np.all(result['curve'][begin+1:finish, 2:4] == 0), '全玉整理帯に建玉が残っています'
                    checked['米国開始整理帯の保有単位'] = 0
            cuts = [len(state) // 3, len(state) * 2 // 3]
            checked.update(セッション=key[0], 銘柄=key[1], 条件=identifier,
                           未来打切り回数=prefix(ready, state, config, result, cuts))
            checks.append(checked)
    assert len(checks) == 26
    partial = [row for row in checks if row['条件'].endswith('C05')]
    assert all(row['返済理由の件数'].get('一部利確', 0) > 0 for row in partial), '一部利確分岐が未実行です'
    return checks


def main() -> None:
    """機能: 人工経路と任意の実入力を監査し、検査対象コードのハッシュとともに保存する。

    引数: コマンドライン --real/--selected (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--real', action='store_true')
    parser.add_argument('--selected', action='store_true')
    args = parser.parse_args()
    source = (OUT / 'engine.py').read_bytes()
    report = dict(目的='既知データの実装監査。未知データへの有効性の証明ではない。',
                  エンジンSHA256=hashlib.sha256(source).hexdigest(), 人工経路=[] if args.selected else synthetic())
    if args.real:
        report['保存データ'] = real_checks()
    if args.selected:
        report['保存データ'] = selected_checks()
    assert source == (OUT / 'engine.py').read_bytes(), '監査中にエンジンが変更されています'
    report['結果'] = '全検査一致'
    name = '表示候補と分岐の独立監査.json' if args.selected else ('エンジン独立監査.json' if args.real else '人工経路監査.json')
    (OUT / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(結果=report['結果'], 人工経路数=len(report['人工経路']),
                         保存データセル数=len(report.get('保存データ', []))), ensure_ascii=False))


if __name__ == '__main__':
    main()
