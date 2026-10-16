"""有利指値の成立・永久取消と、元返済を借りない会計を人工検査する。"""

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
NAMES = ('orders', 'trades', 'curve', 'stats', 'cycles', 'order_uids', 'execution_events', 'execution_states', 'limit_events')


def module(name, path):
    """
    機能: 保存ソースを監査名で読み取る。
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
    機能: 今回の監査領域だけへ有限JSONを書き出す。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    target = HERE / name
    assert target.resolve().is_relative_to(HERE)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def hashes():
    """
    機能: 取引・監査・凍結元の指紋を取得する。編集中の研究実行器は除外する。
    引数: なし。
    返り値: dict[str,str]。
    """
    paths = [WORK / n for n in ('engine.py', 'strategy.py', 'catalog.py')]
    paths += [WORK.parent / 'round10' / n for n in ('engine.py', 'strategy.py', 'fee_account.py')]
    paths += [WORK.parent / 'round11' / n for n in ('engine.py', 'strategy.py', 'prepare.py', 'catalog.py')]
    paths += [Path(__file__)]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def load():
    """
    機能: 新しい指値層と、凍結済みの独立UID検算器を読み込む。
    引数: なし。
    返り値: tuple[module,module,module,module]。
    """
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    engine = module('監査87有利指値実行', WORK / 'engine.py')
    prior = module('監査87有利指値独立会計', WORK.parent / 'round10/audit/checks.py')
    fees = module('監査87有利指値料金', WORK.parent / 'round10/fee_account.py')
    old = sys.modules['wave87_round10_engine']
    return engine, prior, fees, old


def line(price, side, atr, offset, tick):
    """
    機能: 売買方向に対する有利側の呼値線を独立計算する。
    引数: price/atr/offset/tick(float)、side(int)。
    返り値: float。
    """
    raw = (price - side * offset * atr) / tick
    return (math.floor(raw + 1e-12) if side > 0 else math.ceil(raw - 1e-12)) * tick


def fixture(symbol, reflected, case, offset):
    """
    機能: 指値接触と元の部分・全返済を独立に配置した人工素材を作る。
    引数: symbol(str)、reflected(bool)、case(str)、offset(float)。
    返り値: dict。
    """
    prices = np.array([100, 100, 100, 100, 101, 99, 99, 98, 101, 102, 101, 99, 100, 100, 100, 100], float)
    n = len(prices)
    times = np.arange(n, dtype=float)
    own = [[3, 0, 1, 5, 1, 20], [7, 0, -1, 2, 0, 7], [12, 0, -1, 3, 0, 1]]
    quiet, force = np.zeros(n, bool), np.zeros(n, bool)
    end = 1000.
    atr = 4.
    level = line(100., 1, atr, offset, .5)
    if case == '条件線ちょうど':
        prices[4] = level
    elif case == '条件線の手前から接触':
        prices[4], prices[5] = level + .5, level
    elif case == '条件線を有利に飛越し':
        prices[4] = level - 2
    elif case == '最初の部分返済と同時成立':
        prices[4:7] = 101
        prices[7] = 90
    elif case == '部分返済後の有利価格でも永久取消':
        prices[4:8] = 101
        prices[8:] = 90
    elif case == '最初の全返済と同時成立':
        prices[4:8] = 101
        prices[8] = 90
        own = [[3, 0, 1, 5, 1, 20], [8, 0, -1, 5, 0, 1]]
    elif case == '全返済後の有利価格でも永久取消':
        prices[4:9] = 101
        prices[9:] = 90
        own = [[3, 0, 1, 5, 1, 20], [8, 0, -1, 5, 0, 1]]
    elif case == '同時計の次原本行':
        times[4] = times[3]
        prices[4] = level
    elif case == '無効観測を跨いで成立':
        prices[4] = np.nan
        prices[5] = level
    elif case == '予定が指値成立より先':
        quiet[4:7] = True
        prices[4] = level
        own = [[3, 0, 1, 5, 1, 20], [4, 0, -1, 5, 0, 71]]
    elif case == '予定中の無効価格で取消':
        quiet[4] = True
        prices[4] = np.nan
        prices[5] = level
        own = [[3, 0, 1, 5, 1, 20], [5, 0, -1, 5, 0, 71]]
    elif case == '成立済み玉の予定返済':
        prices[4] = level
        quiet[6] = True
        own = [[3, 0, 1, 5, 1, 20], [6, 0, -1, 5, 0, 71]]
    elif case == '成立済み玉の予定欠測':
        prices[4] = level
        quiet[6] = True
        prices[6] = np.nan
        own = [[3, 0, 1, 5, 1, 20], [7, 0, -1, 5, 0, 71]]
    elif case == '場末が成立より先':
        end = 4.
        prices[4] = level
        own = [[3, 0, 1, 5, 1, 20], [4, 0, -1, 5, 0, 9]]
    elif case == '一枚の元全返済':
        prices[4] = level
        own = [[3, 0, 1, 1, 1, 20], [12, 0, -1, 1, 0, 1]]
    elif case == '同観測の二返済注文を区別':
        prices[4] = level
        own = [[3, 0, 1, 5, 1, 20], [7, 0, -1, 2, 0, 7], [7, 0, -1, 3, 0, 1]]
    elif case == '欠番親交換で一度ずつ新規':
        prices[4] = level
        prices[9] = level - 1
        own = [[3, 5000, 1, 5, 1, 20], [8, 5000, -1, 5, 0, 1], [8, 5007, 1, 5, 1, 20], [12, 5007, -1, 5, 0, 1]]
    elif case == '呼値へ丸める固定ATR':
        atr = 3.3
        prices[4] = line(100., 1, atr, offset, .5)
    elif case == '有利でも最後は損失':
        prices[4] = level
        prices[7:] = 80
    sign = -1 if reflected else 1
    factor = 1 if symbol == 'TOPIX' else 20
    quantity = 1 if symbol == 'TOPIX' else 2
    prices = (200 - prices if reflected else prices) * factor
    feed = []
    for row, cid, side, qty, new, reason in own:
        feed.append([row, row - 1, cid, side * sign, qty * quantity, prices[row], reason, new, 0, atr * factor if new else 0.])
    ready = dict(symbol=symbol, session='人工有利指値', last=prices, time_s=times,
                 seq=np.arange(n), tick=.5 if symbol == 'TOPIX' else 10.)
    return dict(ready=ready, feed=np.asarray(feed, float), quiet=quiet, force=force, end=end,
                cap=10 if symbol == 'TOPIX' else 20)


def play(engine, sample, offset, unconditional=False):
    """
    機能: 固定人工素材を新しい指値層へ渡す。
    引数: engine(module)、sample(dict)、offset(float)、unconditional(bool)。
    返り値: dictの実行結果。
    """
    r = sample['ready']
    values = engine.simulate(r['time_s'], r['last'], sample['feed'], sample['quiet'], sample['force'], sample['end'],
                            sample['cap'], r['tick'], offset, unconditional)
    return dict(zip(NAMES, values))


def inspect(ready, result, feed, offset, unconditional, quiet, force, end, baseline):
    """
    機能: 成立・取消の最初の行と、対応親の後続返済および入口差だけの損益を検算する。
    引数: ready/result/baseline(dict)、feed(ndarray)、offset/end(float)、unconditional(bool)、quiet/force(ndarray)。
    返り値: dictの成立・見送り親数。
    """
    orders, proofs = result['orders'], result['limit_events']
    scheduled = quiet | force | (ready['time_s'] >= end)
    prices = ready['last']
    valid = np.isfinite(prices) & (prices > 0)
    entries = {int(o[2]): o for o in feed if o[7]}
    allowed, rejected, benefits = 0, 0, []
    assert len(proofs[proofs[:, 1] == 1]) == len(entries)
    for cid, original in entries.items():
        source, side, qty = int(original[0]), int(original[3]), int(original[4])
        level = line(original[5], side, original[9], offset, ready['tick'])
        own = orders[orders[:, 2] == cid]
        opening = own[own[:, 7] == 1]
        events = proofs[proofs[:, 2] == cid]
        prep = events[events[:, 1] == 1]
        assert len(prep) == 1 and prep[0, 0] == source and prep[0, 3] == source
        np.testing.assert_allclose(prep[0, [4, 5, 6, 7, 8, 15]],
            [side, qty, original[5], original[9], level, offset], rtol=0, atol=1e-8)
        returns = feed[(feed[:, 2] == cid) & (feed[:, 7] == 0)]
        first_return = int(returns[0, 0])
        hit, cancelled = None, None
        for i in range(source, len(prices)):
            if scheduled[i]:
                cancelled = i
                break
            if i == source:
                continue
            if valid[i] and (unconditional or side * (prices[i] - level) <= 0):
                hit = i
                break
            if i == first_return:
                cancelled = i
                break
        if hit is None:
            assert not len(own)
            assert not len(result['cycles'][result['cycles'][:, 0] == cid])
            if cancelled is not None and cancelled > source:
                stopped = events[np.isin(events[:, 1], [3, 4])]
                assert len(stopped) == 1 and stopped[0, 0] == cancelled
                assert stopped[0, 1] == (4 if scheduled[cancelled] else 3)
            rejected += 1
            continue
        assert len(opening) == 1 and opening[0, 0] == hit and opening[0, 1] == source
        assert opening[0, 5] == prices[hit] and opening[0, 4] == qty
        fills = events[events[:, 1] == 2]
        assert len(fills) == 1 and fills[0, 0] == hit and fills[0, 10] == hit
        reference = baseline['orders'][baseline['orders'][:, 2] == cid]
        ref_entry = reference[reference[:, 7] == 1]
        assert len(ref_entry) == 1
        np.testing.assert_array_equal(own[own[:, 7] == 0], reference[reference[:, 7] == 0])
        advantage = side * qty * (ref_entry[0, 5] - opening[0, 5])
        assert advantage >= -1e-8
        mine = result['trades'][result['trades'][:, 0] == cid]
        theirs = baseline['trades'][baseline['trades'][:, 0] == cid]
        assert abs(mine[:, 10].sum() - theirs[:, 10].sum() - advantage) < 1e-8
        fee = 418 if ready['symbol'] == 'TOPIX' else 110
        assert sum(int(o[4]) * fee // 10 for o in own) == sum(int(o[4]) * fee // 10 for o in reference)
        allowed += 1
        benefits.append(float(advantage))
    assert allowed + rejected == len(entries)
    return dict(成立親数=allowed, 見送り親数=rejected, 入口改善幅枚数積=sum(benefits))


def main():
    """
    機能: 二商品・売買反射・八幅の人工条件を検査し、元Gコピー対照も確認する。
    引数: なし。
    返り値: None。
    """
    engine, previous, fees, old = load()
    before = hashes()
    scenarios = ['通常の待機と元部分返済', '条件線ちょうど', '条件線の手前から接触', '条件線を有利に飛越し',
        '最初の部分返済と同時成立', '部分返済後の有利価格でも永久取消', '最初の全返済と同時成立',
        '全返済後の有利価格でも永久取消', '同時計の次原本行', '無効観測を跨いで成立',
        '予定が指値成立より先', '予定中の無効価格で取消', '成立済み玉の予定返済', '成立済み玉の予定欠測',
        '場末が成立より先', '一枚の元全返済', '同観測の二返済注文を区別', '欠番親交換で一度ずつ新規',
        '呼値へ丸める固定ATR', '有利でも最後は損失']
    records = []
    for symbol in ('TOPIX', 'NK225'):
        for reflected in (False, True):
            for case in scenarios:
                for digit in range(8):
                    offset = digit / 10
                    sample = fixture(symbol, reflected, case, offset)
                    ready = sample['ready']
                    baseline = play(engine, sample, 0., True)
                    earlier = old.simulate(ready['time_s'], ready['last'], sample['feed'], sample['quiet'], sample['force'],
                                          sample['end'], 0, sample['cap'])
                    for name, value in zip(NAMES[:7], earlier[:7]):
                        if name == 'execution_events':
                            continue
                        np.testing.assert_array_equal(baseline[name], value, err_msg=name)
                    result = play(engine, sample, offset)
                    tally = previous.account(ready, result, fees, sample['cap'])
                    found = inspect(ready, result, sample['feed'], offset, False, sample['quiet'], sample['force'], sample['end'], baseline)
                    if case in ('部分返済後の有利価格でも永久取消', '全返済後の有利価格でも永久取消',
                                '予定が指値成立より先', '予定中の無効価格で取消', '場末が成立より先'):
                        assert not len(result['orders'])
                    if case == '最初の部分返済と同時成立':
                        assert result['orders'][0, 0] == 7 and result['orders'][1, 0] == 8
                    if case == '最初の全返済と同時成立':
                        assert result['orders'][0, 0] == 8 and result['orders'][1, 0] == 9
                    if case == '有利でも最後は損失':
                        assert result['trades'][:, 10].sum() < 0
                    records.append(dict(検査=case, 商品=symbol, 反射=reflected, 幅ATR=offset, **found, **tally))
    assert before == hashes()
    save('有利指値待機の条件成立と取消順序の人工検査.json', dict(全合格=True, 検査数=len(records),
        無条件旧G対照数=len(records), 検査=records, コードSHA256=before,
        重要な区別='有利に入れたことはその親が黒字という意味ではない。未成立親は元の利益を一切計上しない。'))
    print(json.dumps(dict(全合格=True, 検査数=len(records)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
