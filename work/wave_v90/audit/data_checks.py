"""保存された二市場素材の過去端点と価格経路を、正式素材計算器から独立に照合する。"""

from bisect import bisect_left
import json
import pickle
from pathlib import Path

import numpy as np

import common


def load(path):
    """
    機能: 過去の固定保存入力を読み取り専用で読む。
    引数: path(Path)。
    返り値: dict。
    """
    with path.open('rb') as stream:
        return pickle.load(stream)


def endpoints(targets, times, eligible, reset, max_age=30.):
    """
    機能: 二分探索で期限の厳密過去の最新時計を取り、先頭行だけを検査する。
    引数: targets/times(float配列)、eligible/reset(bool配列)、max_age(float)。
    返り値: 行番号(int32配列)、古さ(float配列)のtuple。古い有効行への救済は行わない。
    """
    output = np.full(len(targets), -1, np.int32)
    age = np.full(len(targets), np.nan)
    stamps = times.tolist()
    for i, target in enumerate(targets):
        previous = bisect_left(stamps, float(target)) - 1
        if previous < 0 or not np.isfinite(target):
            continue
        first = bisect_left(stamps, stamps[previous])
        elapsed = float(target) - stamps[first]
        if eligible[first] and not reset[first] and 0 < elapsed <= max_age:
            output[i], age[i] = first, elapsed
    return output, age


def artificial():
    """
    機能: 同時計先頭、厳密過去、無効救済禁止、reset、古さ限界の人工反例を検査する。
    引数: なし。
    返り値: dict。取引又は損益は計算しない。
    """
    core = common.module('監査90端点76読取', common.ROOT / 'work/wave_v76/inputs/core.py')
    times = np.array([0, 0, 1, 2, 2, 30, 31, 62.], float)
    targets = np.array([-1, 0, .1, 1, 1.1, 2, 2.1, 30, 31, 31.1, 61, 61.1, 62, 62.1], float)
    comparisons = 0
    for age in (0., .1, 1., 30., 31.):
        for broken in (-1, 0, 1, 2, 3, 4, 5, 6, 7):
            for reset_at in (-1, 0, 2, 3, 5, 7):
                valid = np.ones(len(times), bool)
                reset = np.zeros(len(times), bool)
                if broken >= 0:
                    valid[broken] = False
                if reset_at >= 0:
                    reset[reset_at] = True
                expected = endpoints(targets, times, valid, reset, age)
                got = core.asof_indices(targets, times, valid, reset, age)
                np.testing.assert_array_equal(got[0], expected[0])
                np.testing.assert_allclose(got[1], expected[1], atol=2e-6, rtol=0, equal_nan=True)
                comparisons += len(targets)
    return dict(端点件数=comparisons, 同時計末尾の利用なし=True, 無効救済なし=True, 厳密過去=True)


def market(grid, record, book, saved):
    """
    機能: 全格子の現在・300秒前端点、総変動ER、180秒直前範囲を別計算で復元する。
    引数: grid(float配列)、record/book/saved(dict)。
    返り値: dictの照合件数と未来切断件数。正式特徴計算器は呼ばない。
    """
    times = record['time_s']
    np.testing.assert_array_equal(record['seq'], book['seq'])
    np.testing.assert_array_equal(times, book['time_s'])
    np.testing.assert_array_equal(record['price'], book['last'])
    np.testing.assert_array_equal(record['bid'], book['bid'])
    np.testing.assert_array_equal(record['ask'], book['ask'])
    tick = record['tick']
    eligible = book['valid'] & np.isfinite(book['bid']) & np.isfinite(book['ask'])
    eligible &= (book['bid'] > 0) & (book['ask'] > book['bid']) & (book['ask'] - book['bid'] <= 2 * tick + 1e-9)
    now, age = endpoints(grid - 1., times, eligible, book['reset'])
    np.testing.assert_array_equal(now, saved['current']['index'])
    np.testing.assert_allclose(age, saved['current']['age'], atol=2e-6, rtol=0, equal_nan=True)
    valid_now = now >= 0
    np.testing.assert_array_equal(valid_now, saved['current']['valid'])
    assert (times[now[valid_now]] < (grid - 1)[valid_now]).all()
    assert (np.searchsorted(times, times[now[valid_now]], side='left') == now[valid_now]).all()

    first = np.flatnonzero(np.r_[True, times[1:] != times[:-1]])
    first_mid = book['mid'][first]
    variation_prefix = np.r_[0., np.cumsum(np.abs(np.diff(first_mid)))]
    bad_prefix = np.r_[0, np.cumsum(~book['valid'] | book['reset'])]
    now_position = np.searchsorted(first, np.maximum(now, 0))
    er_count = range_count = 0
    for window in (300, 180):
        old, old_age = endpoints(grid - 1. - window, times, eligible, book['reset'])
        expected = saved['windows'][300] if window == 300 else saved['ranges'][180]
        np.testing.assert_array_equal(old, expected['old'])
        np.testing.assert_array_equal(now, expected['now'])
        available = (old >= 0) & (now >= 0)
        crossed = bad_prefix[np.maximum(now, 0) + 1] - bad_prefix[np.maximum(old, 0) + 1] > 0
        valid = available & (old < now) & ~crossed
        old_position = np.searchsorted(first, np.maximum(old, 0))
        if window == 300:
            np.testing.assert_array_equal(valid, expected['source_valid'])
            np.testing.assert_array_equal(available & (old == now), expected['same_row'])
            np.testing.assert_array_equal(available & crossed, expected['reset_or_invalid_cross'])
            displacement = book['mid'][np.maximum(now, 0)] - book['mid'][np.maximum(old, 0)]
            variation = variation_prefix[now_position] - variation_prefix[old_position]
            efficiency = np.full(len(grid), np.nan)
            nonzero = valid & (variation > 0)
            efficiency[nonzero] = np.abs(displacement[nonzero]) / variation[nonzero]
            np.testing.assert_allclose(efficiency, expected['efficiency'], atol=1e-9, rtol=0, equal_nan=True)
            np.testing.assert_array_equal(valid & (variation <= 0), expected['zero_variation'])
            assert (efficiency[nonzero] >= 0).all() and (efficiency[nonzero] <= 1 + 1e-9).all()
            er_count = int(nonzero.sum())
        else:
            high = np.full(len(grid), np.nan)
            low = high.copy()
            count = now_position - old_position
            range_valid = valid & (count >= 2)
            for g in np.flatnonzero(range_valid):
                past = first_mid[old_position[g]:now_position[g]]
                assert len(past) >= 2
                high[g], low[g] = np.max(past), np.min(past)
            np.testing.assert_array_equal(range_valid, expected['source_valid'])
            np.testing.assert_allclose(high, expected['high'], atol=1e-9, rtol=0, equal_nan=True)
            np.testing.assert_allclose(low, expected['low'], atol=1e-9, rtol=0, equal_nan=True)
            position_valid = range_valid & (high > low)
            np.testing.assert_array_equal(position_valid, expected['position_valid'])
            position = np.full(len(grid), np.nan)
            position[position_valid] = (book['mid'][now[position_valid]] - low[position_valid]) / (high[position_valid] - low[position_valid])
            np.testing.assert_allclose(position, expected['position'], atol=1e-9, rtol=0, equal_nan=True)
            range_count = int(position_valid.sum())

    # ----------------------------------------
    # 任意の未来を切っても、切断前の端点は同時計先頭を含めて変わらない。
    cuts = 0
    for end in np.unique(np.rint(np.linspace(1, len(times), 17)).astype(int)):
        past = grid - 1 < times[end - 1]
        reduced = endpoints((grid - 1)[past], times[:end], eligible[:end], book['reset'][:end])
        np.testing.assert_array_equal(reduced[0], now[past])
        cuts += 1
    return dict(rows=len(times), grid_rows=len(grid), 有効現在=int(valid_now.sum()), 有限ER300=er_count,
                有効直前範囲180=range_count, 入力端点未来切断=cuts)


def main():
    """
    機能: 全30場60口座の読取素材を監査し、損益なしの証跡を今回領域へ保存する。
    引数: なし。
    返り値: None。
    """
    paths = [common.ROOT / p for p in ('work/wave_v83/prepared/inputs.pkl', 'work/wave_v77/inputs/grids_delay1.pkl',
                                      'work/wave_v69/prepared/features.pkl', 'work/wave_v71/prepared/extra_features.pkl',
                                      'work/wave_v77/inputs/extra_features.pkl')]
    prices, grids = load(paths[0]), load(paths[1])
    books = {}
    for path in paths[2:]:
        values = load(path)
        assert not books.keys() & values.keys()
        books.update(values)
    assert len(prices) == len(books) == 60 and len(grids) == 30
    records = []
    for session in sorted(grids):
        for symbol in common.SYMBOLS:
            key = session, symbol
            counts = market(grids[session]['grid'], prices[key], books[key], grids[session]['markets'][symbol])
            records.append(dict(session=session, symbol=symbol, **counts))
        print(f'{session} 二市場端点・ER・範囲の独立照合', flush=True)
    proof = dict(全合格=True, 対象='全60口座のstrict過去素材独立再計算', 全期間既知=True,
                 人工=artificial(), 口座=records, 未来切断数=sum(r['入力端点未来切断'] for r in records),
                 損益計算=0, 損益閲覧=0, 現在API取得=0, 実注文=0, 旧変更=0,
                 SHA256=common.fingerprint(paths + [Path(__file__), Path(common.__file__)]))
    common.save('全60口座の厳密過去端点とER及び直前範囲の独立照合.json', proof)
    print('全60口座の素材監査合格。損益計算なし。', flush=True)


if __name__ == '__main__':
    main()
