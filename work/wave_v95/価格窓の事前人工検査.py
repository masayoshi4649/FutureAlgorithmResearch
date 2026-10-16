"""売買前に独立LP窓の欠測・同時計・断裂と未来不変を確かめる。"""

import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
import data
import prepare_prices


def record(times: np.ndarray, prices: np.ndarray) -> dict:
    """
    機能: 数量・板を持たない人工の正常LP系列を用意する。
    引数: times/prices(ndarray[float])。
    返り値: dictはseq/time_s/last/valid/resetの系列。
    """
    reasons = np.zeros(len(times), np.uint8)
    if len(times):
        reasons[0] = 1
    return dict(time_s=times, last=prices, seq=np.arange(len(times), dtype=np.int64),
                valid=np.isfinite(prices) & (prices > 0), reset=reasons != 0, reset_reason=reasons)


def equal(left: object, right: object) -> None:
    """
    機能: 全入力列の一致を、未定義値を含めて検査する。
    引数: left/right(dict又はndarray)。
    返り値: None。不一致で例外を出す。
    """
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            equal(left[key], right[key])
    else:
        np.testing.assert_array_equal(left, right)


def main() -> None:
    """
    機能: 10種類の入力境界と実接頭・未来汚染を損益抜きで検査する。
    引数: なし。
    返り値: None。検査内容とコード指紋を新95/preparedへ保存する。
    """
    checks = []
    grid = np.arange(320., 601., 5.)
    times = np.arange(0., 701., 5.)
    raw = record(times, 100. + times / 100.)
    normal = prepare_prices.price_features(grid, raw)
    assert normal['current']['valid'].all()
    assert normal['windows'][15]['source_valid'].all() and normal['windows'][300]['source_valid'].all()
    assert (normal['current']['time_s'] < grid - 1.).all()
    checks.append('正常な厳密過去15秒と300秒')
    empty = prepare_prices.price_features(grid, record(np.array([], float), np.array([], float)))
    assert not empty['current']['valid'].any() and not empty['windows'][15]['source_valid'].any()
    checks.append('空価格系列は観測不能')
    flat = prepare_prices.price_features(grid, record(times, np.full(len(times), 100.)))
    assert flat['windows'][15]['source_valid'].all() and (flat['windows'][15]['ret_bp'] == 0).all()
    checks.append('価格不変は欠測に置換しない')
    expired = prepare_prices.price_features(np.array([100.]), record(np.array([0., 5.]), np.array([100., 101.])))
    assert not expired['current']['valid'][0]
    checks.append('30秒を超えた価格は新鮮にしない')
    duplicate = record(np.array([0., 15., 285., 300., 300., 315.]),
                       np.array([100., 101., 102., 103., 99999., 104.]))
    value = prepare_prices.price_features(np.array([317.]), duplicate)
    assert value['windows'][15]['old_seq'][0] == 3 and value['windows'][15]['old_value'][0] == 103.
    checks.append('同時計は先頭の源を選ぶ')
    boundary = prepare_prices.price_features(np.array([301.]), duplicate)
    assert boundary['current']['time_s'][0] == 285.
    checks.append('判断境界と1秒遅延の同時計は参照しない')
    invalid = record(np.array([0., 280., 290., 295., 299.]), np.array([100., 101., np.nan, 102., 103.]))
    value = prepare_prices.price_features(np.array([301.]), invalid)
    assert not value['windows'][15]['source_valid'][0]
    checks.append('窓内の不正価格を跨がない')
    reset = record(np.array([0., 280., 290., 295., 299.]), np.array([100., 101., 102., 103., 104.]))
    reset['reset'][2] = True
    value = prepare_prices.price_features(np.array([301.]), reset)
    assert not value['windows'][15]['source_valid'][0]
    checks.append('原本の断裂を跨がない')
    prefix_grid = grid[grid < 450.]
    prefix = {key: value[:np.searchsorted(times, 450.)] for key, value in raw.items()}
    expected = prepare_prices.price_features(prefix_grid, raw)
    equal(expected, prepare_prices.price_features(prefix_grid, prefix))
    checks.append('接頭部だけの再計算で全列不変')
    future = {key: value.copy() for key, value in raw.items()}
    future['last'][times >= 450.] = np.nan
    future['valid'][times >= 450.] = False
    future['reset'][times >= 450.] = True
    equal(expected, prepare_prices.price_features(prefix_grid, future))
    checks.append('将来価格と断裂の汚染でも全列不変')
    assert len(checks) == 10
    paths = [Path(__file__), HERE / 'data.py', HERE / 'prepare_prices.py',
             HERE.parent / 'wave_v94/inputs_r1/last_price.py', HERE.parent / 'wave_v94/inputs_r1/core.py']
    target = HERE / 'prepared/独立価格15秒と300秒の人工境界及び未来不変.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(全合格=True, 人工種類=10, 内容=checks,
        SHA256={str(path.relative_to(data.ROOT)): data.digest(path) for path in paths},
        新損益計算=0, 新売買計算=0, API取得=0, 実注文=0), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('独立LPの10境界・接頭部・未来汚染検査が合格', flush=True)


if __name__ == '__main__':
    main()
