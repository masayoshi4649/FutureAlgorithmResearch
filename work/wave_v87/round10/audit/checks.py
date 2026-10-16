"""仮想注文から次観測の実建玉へ変換する実行層を独立に検査する。"""

import hashlib
import importlib.util
import json
import math
import os
from collections import defaultdict
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[2]


def module(name, path):
    """
    機能: 既存ソースを変更せず独立した監査名で読み込む。
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
    機能: 今回の監査領域だけへ有限JSONを保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    target = (HERE / name).resolve()
    assert target.is_relative_to(HERE)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def hashes():
    """
    機能: 売買実装と監査器の指紋を取り、編集中の研究実行器は含めない。
    引数: なし。
    返り値: dict[str,str]。
    """
    paths = [WORK / p for p in ('engine.py', 'strategy.py', 'catalog.py', 'fee_account.py')]
    paths += [Path(__file__), WORK.parent / 'round9/engine.py', WORK.parent / 'round9/strategy.py']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def load():
    """
    機能: 新実行層とUID会計を読んで、キャッシュを監査領域へ向ける。
    引数: なし。
    返り値: tuple[module,module,module]。
    """
    engine = module('監査87差引実行層', WORK / 'engine.py')
    fees = module('監査87差引UID会計', WORK / 'fee_account.py')
    catalog = module('監査87差引条件', WORK / 'catalog.py')
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    return engine, fees, catalog


def fixture(symbol, reflected, values, instructions, quiet=None, force=None, times=None, end=1000.):
    """
    機能: 商品倍率と売買反射を揃えた仮想注文列を作る。
    引数: symbol(str)、reflected(bool)、values/instructions(list)、quiet/force/times(list|None)、end(float)。
    返り値: tuple[dict,ndarray,ndarray,ndarray,float,int]。
    instructionsは行・親ID・方向・基準枚数・新規区分・役割の六列。
    """
    factor = 1 if symbol == 'TOPIX' else 20
    lots = 1 if symbol == 'TOPIX' else 2
    sign = -1 if reflected else 1
    prices = np.asarray(values, float)
    prices = (200 - prices if reflected else prices) * factor
    n = len(prices)
    clock = np.arange(n, dtype=float) if times is None else np.asarray(times, float)
    q = np.zeros(n, bool) if quiet is None else np.asarray(quiet, bool)
    f = np.zeros(n, bool) if force is None else np.asarray(force, bool)
    feed = []
    for row, cid, side, count, new, role in instructions:
        feed.append([row, max(0, row - 1), cid, side * sign, count * lots, prices[row],
                     20 if new else 1, new, role, 4 * factor if new and role == 0 else 0.])
    ready = dict(symbol=symbol, session='人工境界', last=prices, time_s=clock,
                 seq=np.arange(n, dtype=np.int64), tick=.5 if symbol == 'TOPIX' else 10.)
    return ready, np.asarray(feed, float).reshape(-1, 10), q, f, end, 10 if symbol == 'TOPIX' else 20


def account(ready, result, fees, cap, complete=True):
    """
    機能: UID別建値・注文料金・全原板時価・親組を注文から独立に再構成する。
    引数: ready/result(dict)、fees(module)、cap(int)、complete(bool)。
    返り値: dict。親会計との照合は独立計算後だけに実施する。
    """
    orders, trades, cycles = result['orders'], result['trades'], result['cycles']
    n = len(ready['last'])
    rate = 41.8 if ready['symbol'] == 'TOPIX' else 11.
    scale = 1000 if ready['symbol'] == 'TOPIX' else 10
    cash, quantity, gross, charge, longs, shorts = (np.zeros(n) for _ in range(6))
    entries, exits = {}, defaultdict(list)
    held = [0, 0]
    maximum = [0, 0, 0, 0]
    parent_max = defaultdict(lambda: [0, 0])
    for order, uid in zip(orders, result['order_uids']):
        row, source, cid, side, qty = map(int, order[:5])
        assert 0 <= source < row < n and qty > 0
        assert order[5] == ready['last'][row]
        cost = math.floor(qty * rate + 1e-8)
        cash[row] -= side * qty * order[5]
        quantity[row] += side * qty
        charge[row] += cost
        direction = side if order[7] else -side
        at = 0 if direction > 0 else 1
        held[at] += qty if order[7] else -qty
        assert min(held) >= 0 and max(held) <= cap
        maximum = [max(a, b) for a, b in zip(maximum,
            (held[0], held[1], sum(held), abs(held[0] - held[1])))]
        parent_max[cid][0] = max(parent_max[cid][0], sum(held))
        parent_max[cid][1] = max(parent_max[cid][1], abs(held[0] - held[1]))
        (longs if direction > 0 else shorts)[row] += qty if order[7] else -qty
        if order[7]:
            assert uid >= 0 and int(uid) not in entries
            entries[int(uid)] = [qty, qty, cost, order[5], cid, row, side]
        else:
            assert uid == -1
            exits[cid, row, side, order[5], int(order[6])].append([qty, cost / qty])
    assert maximum == result['stats'][2:6].tolist()
    if complete:
        assert not any(held)
    net_legs, parents = [], defaultdict(list)
    for t in trades:
        cid, uid, side, qty = map(int, t[:4])
        start, end = int(t[6]), int(t[7])
        lot = entries[uid]
        assert lot[0] >= qty and lot[3:] == [t[4], cid, start, side]
        lot[0] -= qty
        remaining = qty
        exit_fee = 0.
        queue = exits[cid, end, -side, t[5], int(t[9])]
        while remaining:
            assert queue
            take = min(remaining, queue[0][0])
            exit_fee += take * queue[0][1]
            queue[0][0] -= take
            remaining -= take
            if queue[0][0] == 0:
                queue.pop(0)
        gain = side * qty * (t[5] - t[4])
        assert abs(gain - t[10]) < 1e-8
        gross[end] += gain
        net_legs.append(gain * scale - qty * lot[2] / lot[1] - exit_fee)
        parents[cid].append(t)
    if complete:
        assert all(v[0] == 0 for v in entries.values()) and all(not v for v in exits.values())
        assert set(parents) == {int(c[0]) for c in cycles}
    for c in cycles:
        cid = int(c[0])
        parts = parents[cid]
        assert c[1] == min(t[6] for t in parts) and c[2] == max(t[7] for t in parts)
        assert c[9] == parts[-1][9] and c[6:8].tolist() == parent_max[cid]
        assert abs(c[3] - math.fsum(t[10] for t in parts)) < 1e-8
    arrays = list(map(np.cumsum, (cash, quantity, gross, charge, longs, shorts)))
    cash, quantity, gross, charge, longs, shorts = arrays
    prices = ready['last'].copy()
    last = 0.
    for row, price in enumerate(prices):
        if np.isfinite(price) and price > 0:
            last = price
        else:
            prices[row] = last
    equity = cash + quantity * prices
    for column, values in ((0, equity), (1, gross), (2, longs), (3, shorts), (5, cash), (6, quantity)):
        np.testing.assert_allclose(values, result['curve'][:, column], atol=1e-8, rtol=0)
    dd = np.maximum.accumulate(np.maximum.accumulate(np.maximum(equity, 0)) - equity)
    np.testing.assert_allclose(dd, result['curve'][:, 4], atol=1e-8, rtol=0)
    if complete:
        row, ledger, net_curve = fees.account(ready, result, dict(audit_cap=cap))
        np.testing.assert_allclose(net_curve, equity * scale - charge, atol=1e-5, rtol=0)
        np.testing.assert_allclose([t['収支'] for t in ledger['trades']], net_legs, atol=1e-5, rtol=0)
        assert abs(row['net'] - math.fsum(net_legs)) < 1e-5
    return dict(注文数=len(orders), 決済脚数=len(trades), 新規UID数=len(entries), 親組数=len(cycles),
                最大両建枚数=maximum[2], 手数料=int(charge[-1]))


def synthetic(engine, fees):
    """
    機能: 三実行方式の同時注文、差引復元、親ID、予定優先と欠測境界を検査する。
    引数: engine/fees(module)。
    返り値: None。人工結果だけを保存し新候補の全場損益は計算しない。
    """
    before = hashes()
    scenarios = [
        ('単独次観測', [100,101,102,103,104,105,106,107], [(1,0,1,2,1,0),(5,0,-1,2,0,0)], {}),
        ('差引ゼロから同じ親組へ復元', [100,101,102,103,104,105,106,107], [(1,0,1,4,1,0),(2,0,-1,4,1,1),(4,0,1,4,0,1),(6,0,-1,4,0,0)], {}),
        ('コア半減で反対差引へ変化', [100,101,102,103,104,105,106,107,108], [(1,0,1,4,1,0),(2,0,-1,4,1,1),(3,0,-1,2,0,0),(5,0,1,4,0,1),(7,0,-1,2,0,0)], {}),
        ('コア終了後の反対玉をFだけ抑止', [100,101,102,103,104,105,106,107], [(1,0,1,4,1,0),(2,0,-1,4,1,1),(3,0,-1,4,0,0),(6,0,1,4,0,1)], {}),
        ('同方向でも親ID交換は返済新規', [100,101,102,103,104,105,106,107], [(1,0,1,2,1,0),(3,0,-1,2,0,0),(3,1,1,2,1,0),(5,1,-1,2,0,0)], {}),
        ('同じ行の別UIDと部分料金', [100,101,102,103,104,105,106,107], [(1,0,1,4,1,0),(1,0,1,2,1,1),(3,0,-1,2,0,0),(4,0,-1,2,0,1),(5,0,-1,2,0,0)], {}),
        ('瞬間両建て最大を注文毎に記録', [100,101,102,103,104,105,106,107], [(1,0,1,4,1,0),(2,0,-1,4,1,1),(2,0,-1,4,0,0),(5,0,1,4,0,1)], {}),
        ('無効価格は次の有効行まで待つ', [100,101,np.nan,103,104,np.nan,106,107], [(1,0,1,2,1,0),(4,0,-1,2,0,0)], {}),
        ('同じ代理時計でも次原本行', [100,101,102,103,104,105,106,107], [(1,0,1,2,1,0),(5,0,-1,2,0,0)], dict(times=[0,1,1,2,3,4,4,5])),
        ('予定が未約定新規を取消す', [100,101,102,103,104,105], [(1,0,1,2,1,0),(2,0,-1,2,0,0)], dict(quiet=[False,False,True,True,False,False])),
        ('予定中欠測でも最初の有効行で清算', [100,101,102,np.nan,104,105,106], [(1,0,1,2,1,0),(4,0,-1,2,0,0)], dict(quiet=[False,False,False,True,False,False,False])),
        ('場末は次観測より先に全返済', [100,101,102,103,104,105], [(1,0,1,2,1,0),(4,0,-1,2,0,0)], dict(end=4.)),
        ('欠番親IDは数量容量と独立', [100,101,102,103,104,105,106,107], [(1,5000,1,2,1,0),(3,5000,-1,2,0,0),(3,5008,1,2,1,0),(5,5008,-1,2,0,0)], {}),
    ]
    records = []
    for symbol in ('TOPIX','NK225'):
        for reflected in (False,True):
            for label, prices, orders, extra in scenarios:
                ready, feed, quiet, force, end, cap = fixture(symbol, reflected, prices, orders, **extra)
                outputs = []
                for mode in range(3):
                    values = engine.simulate(ready['time_s'], ready['last'], feed, quiet, force, end, mode, cap)
                    result = dict(zip(('orders','trades','curve','stats','cycles','order_uids','execution_events','execution_states'),values))
                    tally = account(ready,result,fees,cap)
                    if label.startswith('差引ゼロ'):
                        assert len(result['cycles']) == 1
                    if label.startswith('同方向でも'):
                        assert len(result['cycles']) == 2
                        assert len(result['orders']) == 4
                    if label.startswith('コア終了後') and mode == 2:
                        assert not np.any(result['curve'][4:,6])
                    if label.startswith('予定が未'):
                        assert not len(result['orders'])
                    if label.startswith('瞬間両建て') and mode == 0:
                        assert result['stats'][4] == (8 if symbol=='TOPIX' else 16)
                        assert result['cycles'][0,6] == result['stats'][4]
                    outputs.append(result)
                    records.append(dict(検査=label,商品=symbol,反射=reflected,実行方式=mode,**tally))
                for col in (0,5,6):
                    np.testing.assert_array_equal(outputs[0]['curve'][:,col],outputs[1]['curve'][:,col])
    assert before == hashes()
    save('差引実行のUID会計と次観測境界の人工検査.json',dict(全合格=True,検査数=len(records),検査=records,コードSHA256=before))


def main():
    """
    機能: 最新実行層の人工境界検査を開始する。
    引数: なし。
    返り値: None。
    """
    engine, fees, _ = load()
    synthetic(engine,fees)


if __name__ == '__main__':
    main()
