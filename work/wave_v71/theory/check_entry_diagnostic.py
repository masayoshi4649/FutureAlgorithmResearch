"""機能: 実損益を読まず、方向採点を人工気配の単純逐次採点と照合する。"""

import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('entry_diagnostic71', HERE.parent / 'analysis/entry_diagnostic.py')
DIAG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAG)


def brute(bid, ask, schedule, tick, end):
    """機能: 区間木を使わず人工気配を左から読んで先着と最大順逆行を求める。

    引数: bid/ask/schedule(ndarray)、tick(float)、end(int)。
    返り値: ndarray12列の独立採点。
    """
    result = np.zeros((len(schedule), 12), dtype=float)
    for k, item in enumerate(schedule):
        entry, decision, side = int(item[0]), int(item[1]), int(item[3])
        price = ask[entry] if side == 1 else bid[entry]
        result[k, :4] = [entry, decision, side, price]
        result[k, 5] = result[k, 7] = result[k, 10] = result[k, 11] = -1
        for row in range(entry + 1, end + 1):
            if not (np.isfinite(bid[row]) and np.isfinite(ask[row]) and bid[row] > 0 and ask[row] >= bid[row]):
                continue
            signed = side * ((bid[row] if side == 1 else ask[row]) - price) / tick
            for j, width in enumerate((8, 16)):
                if result[k, 4 + 2 * j] == 0 and abs(signed) >= width:
                    result[k, 4 + 2 * j] = 1 if signed > 0 else -1
                    result[k, 5 + 2 * j] = row
            if signed > result[k, 8]:
                result[k, 8], result[k, 10] = signed, row
            if -signed > result[k, 9]:
                result[k, 9], result[k, 11] = -signed, row
    return result


def main():
    """機能: 乱数人工経路・幅飛越・無効気配・終端切断の採点を独立照合する。

    引数: なし。
    返り値: None。theory/入口採点の人工検査.jsonを保存する。
    """
    rng = np.random.default_rng(7109)
    count = 0
    for n in (1, 2, 19, 1027):
        for tick in (.5, 10.):
            mid = (200 + np.cumsum(rng.integers(-6, 7, n))) * tick
            spread = rng.integers(1, 4, n) * tick
            bid, ask = mid - spread / 2, mid + spread / 2
            valid_rows = np.arange(1, n - 1, max(1, n // 17))
            invalid = np.arange(3, n, 11)
            invalid = np.setdiff1d(invalid, valid_rows)
            bid[invalid] = ask[invalid] = np.nan
            entries = np.asarray([[r, r - 1, r - 1, s, 0] for r in valid_rows for s in (1, -1)], dtype=float).reshape((-1, 5))
            for end in (n - 1, max(0, n // 2)):
                tree, size = DIAG._trees(bid, ask)
                actual = DIAG._score(tree, size, bid, ask, entries, tick, end)
                expected = brute(bid, ask, entries, tick, end)
                assert np.allclose(actual, expected, rtol=0, atol=1e-8), (n, tick, end, actual, expected)
                # ----------------------------------------
                # 採点終端の後を大きく変えても、終端までの入口の採点を変えない。
                before = entries[entries[:, 0] <= end]
                changed_bid, changed_ask = bid.copy(), ask.copy()
                changed_bid[end + 1:] = 1e7
                changed_ask[end + 1:] = 1e7 + 100
                changed_tree, changed_size = DIAG._trees(changed_bid, changed_ask)
                modified = DIAG._score(changed_tree, changed_size, changed_bid, changed_ask, before, tick, end)
                fixed = DIAG._score(tree, size, bid, ask, before, tick, end)
                assert np.array_equal(modified, fixed)
                count += len(entries)
    # ----------------------------------------
    # 判断行が無効でも、その後の最初の有効行までを終端にする。
    times = np.arange(8, dtype=float)
    bid = np.array([100., 100., 100., 100., np.nan, np.nan, 90., 200.])
    ask = np.array([101., 101., 101., 101., np.nan, np.nan, 91., 201.])
    assert DIAG._endpoint(times, bid, ask, 64.) == (6, True, 4)
    assert DIAG._endpoint(times, bid, ask, 80.) == (7, False, -1)
    # ----------------------------------------
    # 全件分母・未到達右打切り・到達済み分母を混同しない。
    sample = [{'session': '人工', 'mfe_ticks': 10., 'mae_ticks': 5., 'remaining_seconds': 60.,
               '8': {'outcome': outcome, 'censored': censored}}
              for outcome, censored in ((1, False), (-1, False), (0, True))]
    summary = DIAG._summary(sample, 8)
    assert summary['total'] == 3 and summary['favorable'] == 1 and summary['adverse'] == 1
    assert summary['unreached'] == summary['censored'] == 1
    assert summary['favorable_rate_all'] == 1 / 3 and summary['favorable_rate_reached'] == .5
    assert DIAG._summary([], 8)['favorable_rate_all'] is None
    result = {'人工入口採点照合数': count, '全合格': True,
              '検査': ['単純逐次採点の全12列一致', '終端後の価格変更不変',
                       '判断無効行の次有効気配終端', '右打切りと未到達の別集計', '全件と到達済みの分母区別'],
              '実原本・実損益の閲覧': False}
    (HERE / '入口採点の人工検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
