"""相手の無変更GUを参照する入口・途中判断の人工境界を独立検査する。"""

from collections import defaultdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[2]
NAMES = ('orders', 'trades', 'curve', 'stats', 'cycles', 'order_uids', 'execution_events', 'execution_states', 'peer_events')


def module(name, path):
    """
    機能: 元ソースを変更せず監査固有名で読み込む。
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
    機能: 今回の監査領域へだけ有限JSONを保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def hashes():
    """
    機能: 取引実装と監査器を指紋化し、編集中の研究実行器を除外する。
    引数: なし。
    返り値: dict[str,str]。
    """
    paths = [WORK / name for name in ('engine.py', 'strategy.py', 'prepare.py', 'catalog.py')]
    paths += [WORK.parent / 'round10' / name for name in ('engine.py', 'strategy.py', 'fee_account.py', 'prepare.py')
              if (WORK.parent / 'round10' / name).exists()]
    paths += [Path(__file__)]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def load():
    """
    機能: 新実行層と前段の独立UID会計を読み、監査キャッシュを分離する。
    引数: なし。
    返り値: tuple[module,module,module,module]。
    """
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    engine = module('監査87相手判断実行', WORK / 'engine.py')
    prepare = module('監査87相手判断素材', WORK / 'prepare.py')
    previous = module('監査87相手判断UID検算', WORK.parent / 'round10/audit/checks.py')
    fees = module('監査87相手判断UID料金', WORK.parent / 'round10/fee_account.py')
    return engine, prepare, previous, fees


def fixture(symbol, reflected, case):
    """
    機能: 時計、自己仮想新規、相手保有・停止を分離した人工入力を作る。
    引数: symbol(str)、reflected(bool)、case(str)。
    返り値: dict。相手は実玉でなく独立の元仮想注文を使用する。
    """
    n = 16
    times = np.arange(n, dtype=float)
    prices = np.array([100, 100, 100, 100, 101, 102, 100, 99, 98, 101, 102, 100, 99, 98, 100, 100], float)
    ptime = np.arange(n, dtype=float) - .5
    pprice = np.full(n, 100.)
    own = [[3, 0, 1, 5, 1, 20], [7, 0, -1, 2, 0, 7], [12, 0, -1, 3, 0, 1]]
    peer = [[1, 0, 1, 5, 1, 20], [5, 0, -1, 5, 0, 1]]
    pprice[5:] = 99
    quiet = np.zeros(n, bool)
    force = np.zeros(n, bool)
    limit = 1000.
    fee_override = None
    if case == '相手なし':
        peer = []
    elif case == '相手反対':
        peer = [[r, c, -s, q, k, reason] for r, c, s, q, k, reason in peer]
        pprice[5:] = 101
    elif case == '同時計は未公開':
        ptime = np.arange(n, dtype=float)
        peer[0][0] = 3
    elif case == '許可後の相手支持消失だけでは降りない':
        peer[-1][-1] = 2
    elif case == '入口拒否後に相手が新規':
        peer = [[4, 0, 1, 5, 1, 20], [9, 0, -1, 5, 0, 1]]
        pprice[:] = 100
        pprice[9:] = 99
    elif case == 'E3は非負を要求しない':
        peer = [[1, 0, 1, 5, 1, 20], [2, 0, -1, 3, 0, 7], [12, 0, -1, 2, 0, 1]]
        pprice[2] = 99
        pprice[3:12] = 101
        pprice[12:] = 99
    elif case == 'E3は現在順行であって最大順行ではない':
        pprice[2] = 102
        pprice[3:5] = 100
    elif case == 'E2は清算ゼロを含む':
        fee_override = 0.
    elif case in ('入口鮮度180秒', '入口鮮度180秒超'):
        offset = 0. if case.endswith('180秒') else .001
        times = np.r_[0., 1., 181., np.arange(182., 195.) + offset]
        ptime = np.r_[-2., 0., 2., np.arange(500., 513.)]
        peer = [[1, 0, 1, 5, 1, 20], [5, 0, -1, 5, 0, 1]]
        pprice[:] = 100
    elif case in ('通知鮮度180秒', '通知鮮度180秒超'):
        offset = 0. if case.endswith('180秒') else .001
        times = np.r_[0., .25, .5, 1., np.arange(182., 194.) + offset]
        ptime = np.r_[-2., 0., 2., np.arange(500., 513.)]
        peer = [[1, 0, 1, 5, 1, 20], [2, 0, -1, 5, 0, 1]]
        pprice[2:] = 99
    elif case == '実新規の当行通知':
        peer[-1][0] = 4
        pprice[4:] = 99
    elif case == '自己仮想新規の当行通知':
        peer[-1][0] = 3
        pprice[3:] = 99
    elif case == '元部分返済と同時通知':
        peer[-1][0] = 7
        pprice[5:7] = 100
        pprice[7:] = 99
    elif case == '元部分返済の翌行通知':
        peer[-1][0] = 8
        pprice[5:8] = 100
        pprice[8:] = 99
    elif case == '残一枚の切上げ':
        own = [[3, 0, 1, 1, 1, 20], [12, 0, -1, 1, 0, 1]]
    elif case == '二つの相手負けでも反復半減しない':
        peer += [[6, 1, 1, 5, 1, 20], [9, 1, -1, 5, 0, 32]]
        pprice[6:9] = 100
        pprice[9:] = 99
    elif case == '利益全返済は停止通知でない':
        pprice[5:] = 101
    elif case == '料金前同額でも料金後負け':
        pprice[:] = 100
    elif case == '停止理由32も含む':
        peer[-1][-1] = 32
    elif case == '予定による新規予約取消':
        quiet[4:7] = True
        own = [[3, 0, 1, 5, 1, 20], [4, 0, -1, 5, 0, 71]]
    elif case == '予定中欠測の次有効清算':
        quiet[6] = True
        prices[6] = np.nan
    elif case == '通知公開行の自己無効価格':
        prices[5] = np.nan
    elif case == '既知場末は前予約より先':
        limit = 6.
    elif case == '親組交換で制限解除':
        own = [[3, 0, 1, 5, 1, 20], [9, 0, -1, 5, 0, 1], [10, 8, 1, 5, 1, 20], [13, 8, -1, 5, 0, 1]]
    sign = -1 if reflected else 1
    factor = 1 if symbol == 'TOPIX' else 20
    p_factor = 20 if symbol == 'TOPIX' else 1
    own_qty = 1 if symbol == 'TOPIX' else 2
    peer_qty = 2 if symbol == 'TOPIX' else 1
    prices = (200 - prices if reflected else prices) * factor
    pprice = (200 - pprice if reflected else pprice) * p_factor
    feed, pfeed = [], []
    for records, dest, values, multiplier, atr in ((own, feed, prices, own_qty, 4 * factor), (peer, pfeed, pprice, peer_qty, 4 * p_factor)):
        for row, cid, side, qty, new, reason in records:
            dest.append([row, row - 1, cid, side * sign, qty * multiplier, values[row], reason, new, 0, atr if new else 0])
    ready = dict(session='人工相手判断', symbol=symbol, last=prices, time_s=times,
                 seq=np.arange(n), tick=.5 if symbol == 'TOPIX' else 10.)
    return dict(ready=ready, feed=np.asarray(feed, float).reshape(-1, 10), quiet=quiet, force=force, end=limit,
        peer_time=ptime, peer_price=pprice, peer_feed=np.asarray(pfeed, float).reshape(-1, 10),
        peer_value=10. if symbol == 'TOPIX' else 1000.,
        peer_fee=fee_override if fee_override is not None else (11. if symbol == 'TOPIX' else 41.8),
        cap=10 if symbol == 'TOPIX' else 20)


def run(engine, prepare, sample, entry, holding):
    """
    機能: 人工の独立素材を実行層へ渡す。
    引数: engine/prepare(module)、sample(dict)、entry/holding(int)。
    返り値: dictの実行結果。
    """
    ready = sample['ready']
    refs = prepare.strict_refs(ready['time_s'], sample['peer_time'], sample['peer_price'])
    values = engine.simulate(ready['time_s'], ready['last'], sample['feed'], sample['quiet'], sample['force'], sample['end'],
        entry, holding, sample['cap'], sample['peer_time'], sample['peer_price'], sample['peer_feed'], refs,
        sample['peer_value'], sample['peer_fee'])
    return dict(zip(NAMES, values))


def peer_reference(times, prices, feed, value, fee, ref):
    """
    機能: 相手公開済み注文だけから現在親組の現金、清算損益と現在順行を独立復元する。
    引数: times/prices/feed(ndarray)、value/fee(float)、ref(int)。
    返り値: dict。
    """
    cash = paid = qty = 0.
    cid = side = start = -1
    entry = atr = 0.
    stops = []
    for o in feed:
        row = int(o[0])
        if row > ref:
            break
        if o[7]:
            cid, side, start = int(o[2]), int(o[3]), row
            entry, atr = o[5], o[9]
            cash = paid = 0.
        qty += o[3] * o[4]
        cash -= o[3] * o[4] * o[5] * value
        paid += int(np.floor(o[4] * fee + 1e-8))
        if not o[7] and qty == 0 and o[6] in (1, 32) and cash - paid < 0:
            stops.append(dict(row=row, cid=cid, side=side, net=cash - paid, reason=int(o[6]), entry=start, atr=atr, price=entry))
    liquidation = cash + qty * prices[ref] * value - paid - np.floor(abs(qty) * fee + 1e-8) if ref >= 0 and qty else 0.
    progress = side * (prices[ref] - entry) / atr if ref >= 0 and qty else 0.
    return dict(cash=cash, paid=paid, qty=qty, cid=cid, side=side, entry=start, price=entry, atr=atr,
                liquidation=liquidation, progress=progress, stops=stops)


def inspect(ready, feed, peer, result, entry, holding, prepare):
    """
    機能: 全入口証拠と初公開停止の条件・反復防止・縮小目標を独立照合する。
    引数: ready/peer/result(dict)、feed(ndarray)、entry/holding(int)、prepare(module)。
    返り値: dictの照合数。
    """
    times = ready['time_s']
    refs = prepare.strict_refs(times, peer['time_s'], peer['last'])
    assert np.array_equal(refs, peer['ref'])
    proofs = result['peer_events']
    own = {int(o[2]): o for o in feed if o[7]}
    assert len(proofs[proofs[:, 1] == 1]) == len(own)
    permission, reduced = {}, {}
    first_stops = {}
    pending_stops = []
    # ----------------------------------------
    # 停止の公開時点は相手の停止時計より後の最初の有効自己観測。
    # 前回の相手状態変更時刻や、後の新しい価格の時計では判定しない。
    complete = peer_reference(peer['time_s'], peer['last'], peer['feed'], peer['value'], peer['fee'], len(peer['last']) - 1)
    for stop in complete['stops']:
        valid = np.flatnonzero((times > peer['time_s'][stop['row']]) & np.isfinite(ready['last']) & (ready['last'] > 0))
        if len(valid):
            first_stops[stop['row']] = int(valid[0])
            pending_stops.append((int(valid[0]), stop))
    actual_stop_events = [(int(e[0]), int(e[4])) for e in proofs if e[1] == 2]
    assert actual_stop_events == [(i, s['row']) for i, s in pending_stops]
    for e in proofs:
        i, code, cid = map(int, e[:3])
        side, ref = int(e[3]), int(e[4])
        assert e[12] == entry and e[13] == holding
        if code == 1:
            assert i == own[cid][0] and ref == refs[i]
            snapshot = peer_reference(peer['time_s'], peer['last'], peer['feed'], peer['value'], peer['fee'], ref)
            age = times[i] - peer['time_s'][ref] if ref >= 0 else -1.
            same = ref >= 0 and age <= 180 and snapshot['qty'] * side > 0
            expected = entry == 0 or (same and (entry == 1 or (entry == 2 and snapshot['liquidation'] >= 0)
                                                or (entry == 3 and snapshot['progress'] >= .25)))
            assert bool(e[14]) == bool(expected)
            np.testing.assert_allclose(e[[6, 7, 8, 9, 16, 17, 18, 19, 20]],
                [snapshot['cid'], snapshot['qty'], snapshot['liquidation'], snapshot['progress'], age,
                 snapshot['entry'], i, snapshot['atr'], snapshot['price']], rtol=0, atol=1e-7)
            permission[cid] = bool(expected)
        elif code == 2:
            stop = next(s for _, s in pending_stops if s['row'] == ref)
            assert i == first_stops[ref]
            assert e[8] == stop['net'] and e[15] == stop['reason']
            assert e[5] == peer['time_s'][ref] < times[i]
            assert e[16] == times[i] - e[5]
            if e[14]:
                assert holding > 0 and cid not in reduced and permission[cid]
                assert own[cid][0] < i and own[cid][3] == stop['side']
                assert e[16] <= 180 and e[10] > 0 and e[11] > 0
                assert np.any((result['orders'][:, 2] == cid) & (result['orders'][:, 7] == 1) & (result['orders'][:, 0] <= i))
                reduced[cid] = i
        else:
            assert code == 3 and reduced[cid] == i
    states = result['execution_states']
    plans = result['execution_events'][result['execution_events'][:, 1] == 2]
    for plan in plans:
        i, cid = int(plan[0]), int(plan[3])
        current = int(states[i, 1])
        target = current if permission[cid] else 0
        if cid in reduced and reduced[cid] <= i:
            target = 0 if holding == 2 else int(np.sign(current)) * ((abs(current) + 1) // 2)
        assert plan[4] == target
    for cid, permitted in permission.items():
        if not permitted:
            assert not np.any(result['orders'][:, 2] == cid)
    return dict(入口判定数=len(permission), 停止通知数=len(pending_stops), 実縮小数=len(reduced))


def main():
    """
    機能: 二商品と売買反射、四入口・三途中方式で人工境界と独立UID会計を検査する。
    引数: なし。
    返り値: None。新条件の全セッション損益は計算しない。
    """
    engine, prepare, previous, fees = load()
    before = hashes()
    names = ['基本半減と元部分返済', '相手なし', '相手反対', '同時計は未公開',
        '許可後の相手支持消失だけでは降りない', '入口拒否後に相手が新規', 'E3は非負を要求しない',
        'E3は現在順行であって最大順行ではない', 'E2は清算ゼロを含む', '入口鮮度180秒', '入口鮮度180秒超',
        '通知鮮度180秒', '通知鮮度180秒超', '実新規の当行通知', '自己仮想新規の当行通知',
        '元部分返済と同時通知', '元部分返済の翌行通知', '残一枚の切上げ', '二つの相手負けでも反復半減しない',
        '利益全返済は停止通知でない', '料金前同額でも料金後負け', '停止理由32も含む',
        '予定による新規予約取消', '予定中欠測の次有効清算', '通知公開行の自己無効価格',
        '既知場末は前予約より先', '親組交換で制限解除']
    records = []
    for symbol in ('TOPIX', 'NK225'):
        for reflected in (False, True):
            for case in names:
                sample = fixture(symbol, reflected, case)
                ready = sample['ready']
                peer = dict(time_s=sample['peer_time'], last=sample['peer_price'], feed=sample['peer_feed'],
                    value=sample['peer_value'], fee=sample['peer_fee'],
                    ref=prepare.strict_refs(ready['time_s'], sample['peer_time'], sample['peer_price']))
                for entry in range(4):
                    for holding in range(3):
                        result = run(engine, prepare, sample, entry, holding)
                        tally = previous.account(ready, result, fees, sample['cap'])
                        found = inspect(ready, sample['feed'], peer, result, entry, holding, prepare)
                        gate = result['peer_events'][result['peer_events'][:, 1] == 1][0]
                        if case == 'E3は非負を要求しない':
                            assert gate[8] < 0 and gate[9] == .25
                            assert bool(gate[14]) == (entry != 2)
                        if case in ('同時計は未公開', '入口拒否後に相手が新規', '相手なし', '相手反対', '入口鮮度180秒超'):
                            assert bool(gate[14]) == (entry == 0)
                        if case == '入口鮮度180秒' and entry == 1:
                            assert gate[14] and gate[16] == 180
                        if case == 'E2は清算ゼロを含む' and entry == 2:
                            assert gate[8] == 0 and gate[14]
                        if case in ('自己仮想新規の当行通知', '通知鮮度180秒超', '利益全返済は停止通知でない'):
                            assert found['実縮小数'] == 0
                        if case in ('実新規の当行通知', '通知鮮度180秒') and entry in (0, 1) and holding:
                            assert found['実縮小数'] == 1
                            trig = result['peer_events'][result['peer_events'][:, 1] == 3][0]
                            assert trig[0] == result['orders'][result['orders'][:, 7] == 1][0, 0]
                        if case == '予定による新規予約取消':
                            assert not len(result['orders'])
                        if case == '二つの相手負けでも反復半減しない':
                            assert found['実縮小数'] <= 1
                        records.append(dict(検査=case, 商品=symbol, 反射=reflected, 入口=entry, 途中=holding, **found, **tally))
    # ----------------------------------------
    # 参照行の決定を同時計重複と無効価格だけで単独検査する。
    own = np.array([0., 1., 1.001, 2., 3., 4.])
    peer_times = np.array([0., 1., 1., 2., 3.])
    peer_prices = np.array([100., 101., 102., np.nan, 103.])
    np.testing.assert_array_equal(prepare.strict_refs(own, peer_times, peer_prices), [-1, 0, 2, 2, 2, 4])
    assert before == hashes()
    save('相手GUの入口途中判断と順序の人工検査.json', dict(全合格=True, 検査数=len(records),
        厳密過去参照境界=True, 検査=records, コードSHA256=before))
    print(json.dumps(dict(全合格=True, 検査数=len(records)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
