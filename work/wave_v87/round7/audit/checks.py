"""元玉を固定した独立追加玉の原本順序・合算会計・未来切断を検証する。"""

import argparse
from collections import defaultdict, deque
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[2]


def module(name, path):
    """
    機能: 読み取り専用の既存実装を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def save(name, value):
    """
    機能: 今回の監査領域だけへ有限値の証拠を保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    target = (HERE / name).resolve()
    assert target.is_relative_to(HERE)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def hashes():
    """
    機能: 検査中の売買実装と条件の変更を検知する。
    引数: なし。
    返り値: dict[str,str]。
    """
    return {n: hashlib.sha256((WORK / n).read_bytes()).hexdigest() for n in ('catalog.py', 'strategy.py', 'engine.py')}


def load():
    """
    機能: 戦略を読み、コンパイル先を独立監査領域へ向ける。
    引数: なし。
    返り値: tuple[module,dict]。
    """
    strategy = module('監査87独立追加戦略', WORK / 'strategy.py')
    catalog = module('監査87独立追加条件', WORK / 'catalog.py')
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    strategy.base.integration.reference.initialize()
    return strategy, {c['id']: c for c in catalog.catalog()}


def material(prices, core, symbol, reflected, quiet=None, times=None, end=1000.):
    """
    機能: 商品の呼値・数量と売買反射に整合する人工価格・当行元注文を作る。
    引数: prices/core(list)、symbol(str)、reflected(bool)、quiet/times(list|None)、end(float)。
    返り値: tuple[dict,ndarray]。元注文は9列で新規時点のATRのみ含む。
    """
    scale = 1 if symbol == 'TOPIX' else 20
    quantity = 5 if symbol == 'TOPIX' else 10
    sign = -1 if reflected else 1
    p = np.asarray(prices, float)
    if reflected:
        p = 200 - p
    p *= scale
    orders = []
    for row, entering, part, price in core:
        fill = (200 - price if reflected else price) * scale
        orders.append([row, row - 1, 0, sign if entering else -sign, part * quantity,
                       fill, 20 if entering else 9, entering, 4 * scale if entering else 0])
    n = len(p)
    ready = dict(symbol=symbol, last=p, time_s=np.arange(n, dtype=float) if times is None else np.array(times, float),
                 tick=.5 * scale, atr=4 * scale, end=end,
                 quiet=np.zeros(n, bool) if quiet is None else np.array(quiet, bool))
    return ready, np.asarray(orders, float).reshape(-1, 9)


def run(strategy, ready, core, relation, observed, stop=.25):
    """
    機能: 人工経路を一度再生し、追加約定の根拠行と方向別上限を確認する。
    引数: strategy(module)、ready(dict)、core(ndarray)、relation(int)、observed(bool)、stop(float)。
    返り値: tupleの追加玉結果。
    """
    before = core.copy()
    result = strategy.engine.simulate(ready['time_s'], ready['last'], core, ready['quiet'], ready['quiet'],
        ready['end'], 0., ready['tick'], relation, 1., stop, .5, .25, observed)
    np.testing.assert_array_equal(core, before)
    orders, trades, curve, events, stats = result
    assert all(0 <= o[1] < o[0] < len(ready['last']) for o in orders)
    assert stats[3] <= (5 if ready['symbol'] == 'TOPIX' else 10)
    assert stats[4] <= (5 if ready['symbol'] == 'TOPIX' else 10)
    return result


def synthetic(strategy):
    """
    機能: 元玉終了と追加新規の同じ行、子注文、欠測、静観・終場を人工的に反証する。
    引数: strategy(module)。
    返り値: None。人工利益を市場での有効性の根拠にはしない。
    """
    before = hashes()
    records = []
    for symbol in ('TOPIX', 'NK225'):
        q = 5 if symbol == 'TOPIX' else 10
        scale = 1 if symbol == 'TOPIX' else 20
        for reflected in (False, True):
            sign = -1 if reflected else 1
            for observed in (False, True):
                for relation in (1, -1):
                    r, c = material([100, 100, 104, 104, 104], [(1, 1, 1, 100), (2, 0, 1, 104)], symbol, reflected)
                    out = run(strategy, r, c, relation, observed)
                    assert out[0][:, 0].tolist() == [2, 3]
                    assert out[0][1, 1] == 2 and out[0][1, 6] == 83
                    assert out[0][0, 3] == sign * relation
                    records.append(dict(検査='同じ行の追加成立を元終了で遡及取消せず次行返済', 商品=symbol, 反射=reflected, 観測=observed, 方向関係=relation))
                    r, c = material([100, 106, 107, 107, 107], [(1, 1, 1, 100), (3, 0, 1, 107)], symbol, reflected)
                    out = run(strategy, r, c, relation, observed)
                    assert out[0][0, 0] == 2 and out[0][0, 5] == r['last'][2]
                    records.append(dict(検査='既通過予約は指定モデルでも次観測価格', 商品=symbol, 反射=reflected, 観測=observed, 方向関係=relation))
                    r, c = material([100, 100, 104, np.nan, 104, 104], [(1, 1, 1, 100), (2, 0, 1, 104)], symbol, reflected)
                    out = run(strategy, r, c, relation, observed)
                    assert out[0][:, 0].tolist() == [2, 4] and out[0][-1, 1] == 2
                    np.testing.assert_array_equal(out[2][3], out[2][2])
                    records.append(dict(検査='元終了後は次の有効観測で返済', 商品=symbol, 反射=reflected, 観測=observed, 方向関係=relation))
                    r, c = material([100, 100, 104, 104, 104], [(1, 1, 1, 100), (2, 0, 1, 104)], symbol, reflected,
                                    times=[0, 1, 2, 2, 3])
                    out = run(strategy, r, c, relation, observed)
                    assert out[0][:, 0].tolist() == [2, 3] and out[0][-1, 6] == 83
                    records.append(dict(検査='同時計でも別原本行で因果順を保つ', 商品=symbol, 反射=reflected, 観測=observed, 方向関係=relation))
                    r, c = material([100, 100, 104, 104, 104], [(1, 1, 1, 100), (3, 0, 1, 104)], symbol, reflected,
                                    quiet=[False, False, True, True, False])
                    out = run(strategy, r, c, relation, observed)
                    assert not len(out[0])
                    records.append(dict(検査='静観開始で待機追加を取消す', 商品=symbol, 反射=reflected, 観測=observed, 方向関係=relation))
                    r, c = material([100, 100, 104, 104, 104], [(1, 1, 1, 100), (3, 0, 1, 104)], symbol, reflected,
                                    quiet=[False, False, False, True, False])
                    out = run(strategy, r, c, relation, observed)
                    assert out[0][-1, 0] == 3 and out[0][-1, 6] == 84
                    records.append(dict(検査='静観予定は元終了後の次行待ちより優先', 商品=symbol, 反射=reflected, 観測=observed, 方向関係=relation))
                    r, c = material([100, 100, 104, 104, 104], [(1, 1, 1, 100), (3, 0, 1, 104)], symbol, reflected, end=3.)
                    out = run(strategy, r, c, relation, observed)
                    assert out[0][-1, 0] == 3 and out[0][-1, 6] == 85
                    records.append(dict(検査='場末は追加玉自身の予定で当該有効観測返済', 商品=symbol, 反射=reflected, 観測=observed, 方向関係=relation))
                # ----------------------------------------
                # 子線は新規当行で執行せず、追尾更新も次の原本行から。
                r, c = material([100, 100, 110, 111, 111, 111], [(1, 1, 1, 100), (4, 0, 1, 111)], symbol, reflected)
                out = run(strategy, r, c, -1, observed)
                assert out[0][:, 0].tolist() == [2, 3] and out[0][-1, 6] == 81
                if not observed:
                    assert out[0][-1, 5] == r['last'][3]
                records.append(dict(検査='新規当行で通過済みの子線も次観測成行', 商品=symbol, 反射=reflected, 観測=observed))
                r, c = material([100, 100, 104, 106, 105, 110, 110], [(1, 1, 1, 100), (5, 0, 1, 110)], symbol, reflected)
                out = run(strategy, r, c, 1, observed)
                assert out[0][:, 0].tolist() == [2, 4] and out[0][-1, 6] == 82
                assert out[0][-1, 1] == 3 and np.count_nonzero(out[0][:, 7]) == 1
                records.append(dict(検査='追尾更新は次行有効で同親組の再追加なし', 商品=symbol, 反射=reflected, 観測=observed))
                r, c = material([100, 100, 104, 104, 104, 104], [(1, 1, 1, 100), (3, 0, .4, 104), (4, 0, .6, 104)], symbol, reflected)
                out = run(strategy, r, c, -1, observed)
                assert out[0][:, 0].tolist() == [2, 5]
                assert out[2][3, 6] == -sign * q
                core_after = sign * .6 * q
                assert core_after + out[2][3, 6] == -sign * .4 * q
                records.append(dict(検査='元部分返済で反対玉を縮めず純数量は反対へ', 商品=symbol, 反射=reflected, 観測=observed))
    assert before == hashes()
    save('独立追加の人工境界.json', dict(全合格=True, 検査数=len(records), 検査=records, コードSHA256=before))


def accounting(ready, result, settings, strategy, complete=True):
    """
    機能: 独立建玉ごとの料金配賦と合算現金・方向枚数を注文から検算する。
    引数: ready/result/settings(dict)、strategy(module)、complete(bool)。
    返り値: dict。元玉と追加玉を同方向の単一FIFOへ誤って混ぜない。
    """
    orders, trades = result['orders'], result['trades']
    fee = 41.8 if ready['symbol'] == 'TOPIX' else 11.
    scale = 1000 if ready['symbol'] == 'TOPIX' else 10
    n = len(ready['last'])
    balances, quantity, longs, shorts, gross, charge = (np.zeros(n) for _ in range(6))
    entries = {}
    exits = defaultdict(list)
    held = [0, 0]
    maximum = [0, 0]
    max_gross = max_net = 0
    for o in orders:
        row, source, cid, side, q = map(int, o[:5])
        assert source < row
        paid = math.floor(q * fee + 1e-8)
        balances[row] -= side * q * o[5]
        quantity[row] += side * q
        charge[row] += paid
        direction = side if o[7] else -side
        index = 0 if direction > 0 else 1
        held[index] += q if o[7] else -q
        assert min(held) >= 0 and max(held) <= settings['audit_cap']
        maximum = [max(a, b) for a, b in zip(maximum, held)]
        max_gross = max(max_gross, sum(held))
        max_net = max(max_net, abs(held[0] - held[1]))
        inventory = longs if direction > 0 else shorts
        inventory[row] += q if o[7] else -q
        if o[7]:
            key = cid, row, side
            assert key not in entries
            entries[key] = [q, q, o[5], paid]
        else:
            exits[cid, row, side, o[5], int(o[6])].append([q, paid / q])
    net_legs = []
    for t in trades:
        cid, side, q, entry, end = int(t[0]), int(t[2]), int(t[3]), int(t[6]), int(t[7])
        lot = entries[cid, entry, side]
        assert lot[0] >= q and lot[2] == t[4]
        lot[0] -= q
        key = cid, end, -side, t[5], int(t[9])
        remaining = q
        exit_fee = 0.
        while remaining:
            assert exits[key]
            order = exits[key][0]
            taken = min(remaining, order[0])
            exit_fee += taken * order[1]
            order[0] -= taken
            remaining -= taken
            if order[0] == 0:
                exits[key].pop(0)
        gain = side * q * (t[5] - t[4])
        assert abs(gain - t[10]) < 1e-8
        gross[end] += gain
        net_legs.append(gain * scale - q * lot[3] / lot[1] - exit_fee)
    if complete:
        assert not any(held) and all(v[0] == 0 for v in entries.values()) and all(not v for v in exits.values())
    balances, quantity, longs, shorts, gross, charge = map(np.cumsum, (balances, quantity, longs, shorts, gross, charge))
    equity = balances + quantity * ready['last']
    for column, array in ((0, equity), (1, gross), (2, longs), (3, shorts), (5, balances), (6, quantity)):
        np.testing.assert_allclose(array, result['curve'][:, column], atol=1e-8, rtol=0)
    drawdown = np.maximum.accumulate(np.maximum.accumulate(np.maximum(equity, 0)) - equity)
    np.testing.assert_allclose(drawdown, result['curve'][:, 4], atol=1e-8, rtol=0)
    assert maximum == result['stats'][2:4].tolist()
    assert max_gross == result['stats'][4] and max_net == result['stats'][5]
    if complete:
        row, ledger, curve = strategy.previous.account(ready, result, settings)
        np.testing.assert_allclose(curve, equity * scale - charge, atol=1e-5, rtol=0)
        np.testing.assert_allclose([t['収支'] for t in ledger['trades']], net_legs, atol=1e-5, rtol=0)
        assert abs(row['net'] - math.fsum(net_legs)) < 1e-5
    return dict(注文数=len(orders), 決済脚数=len(trades), 料金=int(charge[-1]), 最大買い=maximum[0], 最大売り=maximum[1], 最大両建枚数=max_gross, 最大純枚数=max_net)


def prefixes(strategy, configs):
    """
    機能: 代表日夜と両商品で元玉不変・独立会計・未来の注文と価格の切断を確認する。
    引数: strategy(module)、configs(dict)。
    返り値: None。全場の候補成績は探索しない。
    """
    before = hashes()
    helper = module('監査87独立追加切断道具', ROOT / 'work/wave_v86/audit/support.py')
    prepare = module('監査87独立追加入力', ROOT / 'work/wave_v85/prepare.py')
    inputs, signals, _ = prepare.load_inputs(verify=False)
    keys = [(s, p) for s in ('2026-09-25_Day', '2026-09-28_Night') for p in ('TOPIX', 'NK225')]
    selected = {k: inputs[k] for k in keys}
    features = strategy.initialize(selected, signals)
    records = []
    for key, ready in selected.items():
        feature = features[key]
        for observed in (False, True):
            core, _ = strategy.old.play(dict(id='E01_G_U', mask=1, time_mode='U', changes={}), ready, feature, observed)
            for ident in ('C_F10_S25', 'C_H10_S25', 'C_H10_W'):
                result, settings = strategy.play(configs[ident], ready, feature, observed)
                for name in ('orders', 'trades', 'cycles', 'curve', 'stats'):
                    np.testing.assert_array_equal(result['core_result'][name], core[name])
                tally = accounting(ready, result, settings, strategy)
                events = result['satellite_events']
                cuts = {int(len(ready['last']) * .37), int(len(ready['last']) * .77)}
                for code in range(1, 8):
                    for e in events[events[:, 2] == code][:2]:
                        cuts.update((int(e[0]), int(e[0]) + 1))
                cuts = sorted(i for i in cuts if 2 < i < len(ready['last']))
                checked = 0
                for count in cuts:
                    short_ready = helper.clip(ready, count, len(ready['last']))
                    short_feature = helper.clip(feature, count, len(ready['last']))
                    short, _ = strategy.play(configs[ident], short_ready, short_feature, observed)
                    checked += helper.compare_prefix(result, short, count)
                    checked += helper.compare_prefix(result['core_result'], short['core_result'], count)
                    for name, column in (('satellite_orders', 0), ('satellite_trades', 7), ('satellite_events', 0)):
                        values = result[name]
                        np.testing.assert_array_equal(values[values[:, column] < count], short[name], err_msg=name)
                        checked += 1
                    np.testing.assert_array_equal(result['satellite_curve'][:count], short['satellite_curve'])
                    checked += 1
                records.append(dict(セッション=key[0], 商品=key[1], 条件=ident, 観測約定=observed,
                    切断地点=len(cuts), 配列照合数=checked, **tally))
                print(key, ident, observed, len(cuts), '元玉不変・会計・未来切断一致', flush=True)
    assert before == hashes()
    save('独立追加の元玉不変と会計と未来切断.json', dict(全合格=True, 条件口座数=len(records),
        切断地点=sum(r['切断地点'] for r in records), 配列照合数=sum(r['配列照合数'] for r in records),
        検査=records, コードSHA256=before))


def main():
    """
    機能: 人工境界又は代表経路の未来切断を指定して実行する。
    引数: --prefix(bool)。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', action='store_true')
    args = parser.parse_args()
    strategy, configs = load()
    if args.prefix:
        prefixes(strategy, configs)
    else:
        synthetic(strategy)


if __name__ == '__main__':
    main()
