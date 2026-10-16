"""公開変化行によるloss66復元を、元全原行Python経路と長い人工経路で計時照合する。"""

from pathlib import Path
import time

import numpy as np

import common
import check_loss


def fixture(size: int) -> tuple[dict, dict, np.ndarray, np.ndarray]:
    """
    機能: 一実失敗親の後に、5秒格子と0.25秒原行を持つ長い人工経路を作る。
    引数: size(int)。原行数。
    返り値: tuple[dict,dict,ndarray,ndarray]。record、signal、確定orders、旧events。
    収益探索や正式PLではなく、同一66列計算の性能比較だけに使用する。
    """
    times = 300. + np.arange(size) * .25
    price = np.full(size, 4000.)
    price[10:] = 3960.
    raw = dict(symbol='TOPIX', time_s=times, price=price, bid=price.copy(), ask=price + .5,
               price_valid=np.ones(size, bool), quote_valid=np.ones(size, bool),
               seq=np.arange(size, dtype=np.int64) * 3 + 100, tick=.5, start=0., limit=times[-1])
    indexes = np.arange(0, size, 20)
    source = np.maximum(indexes - 1, 0)
    grid = times[indexes]
    observed = np.zeros((len(grid), 22))
    observed[:, 0] = source
    observed[:, 1] = raw['seq'][source]
    observed[:, 2] = times[source]
    observed[:, 3] = price[source]
    observed[:, 4] = price[source] + .5
    observed[:, 5] = source + 800
    observed[:, 6] = source * 4 + 200
    observed[:, 7] = times[source] - 1.
    observed[:, 8] = 68000.
    observed[:, 9] = 68010.
    observed[:, 10] = source * 2 + 5000
    observed[:, 11] = raw['seq'][source]
    observed[:, 12] = times[source]
    observed[:, 13] = price[source]
    observed[:, 14] = source * 2 + 9000
    observed[:, 15] = source * 4 + 200
    observed[:, 16] = times[source] - 2.
    observed[:, 17] = 68000.
    observed[:, 18:] = True
    observed[0, 18:] = False
    mapped = np.full(size, -1, np.int32)
    mapped[indexes] = np.arange(len(grid))
    event = np.zeros(size, np.int8)
    event[1] = 1
    signal = dict(grid=grid, mapped=mapped, event=event, quality=np.ones(size, bool),
                  reset=np.zeros(size, bool), peer_tick=10., loss_observations=observed,
                  execution_lp_index=np.arange(size, dtype=np.int64) * 2 + 5000)
    orders = np.array([[2, 1, 1, 0, 1, 8, 4000.5, 1, 10, 334, times[1], times[2], 0, 1, 0, 1, 1],
                       [11, 10, 1, 0, -1, 8, 3960., 0, 1, 334, times[10], times[11], 0, 1, 0, 1, 2]], float)
    events = np.zeros((4, 12))
    for index, (row, code) in enumerate(((1, 1), (2, 4), (10, 2), (11, 5))):
        events[index, 0:6] = [row, 1, 0, code, 1, 8]
    return raw, signal, orders, events


def main() -> None:
    """
    機能: 100万原行のR1〜R4を全原行と公開変化行の同式で計算し、全66列と計時を保存する。
    引数: なし。
    返り値: None。人工性能証跡を95auditへ保存。正式PL及び収益認定は0。
    """
    record, signal, orders, events = fixture(1000000)
    rows = []
    for kind in ('ban_opposite', 'fresh_quotes', 'fresh_price_quotes', 'sustained_price_quotes'):
        config = dict(loss_reentry_kind=kind, loss_reentry_trigger='any_net_negative', loss_confirm_seconds=10.)
        began = time.perf_counter()
        original = check_loss.restore(record, signal, config, orders, events, all_rows=True)
        original_seconds = time.perf_counter() - began
        began = time.perf_counter()
        reduced = check_loss.restore(record, signal, config, orders, events)
        reduced_seconds = time.perf_counter() - began
        common.exact(original, reduced)
        _, fresh = check_loss.publication(record, signal)
        rows.append(dict(kind=kind, 全原行=len(record['time_s']), 公開処理行=len(check_loss.observation_rows(signal, fresh, orders, events)),
                         旧全原行秒=original_seconds, 公開変化行秒=reduced_seconds,
                         倍率=original_seconds / reduced_seconds, 全66列完全一致=True, 履歴数=len(reduced)))
        print(f'{kind}: 100万行の全66列一致、旧{original_seconds:.3f}秒/公開{reduced_seconds:.3f}秒', flush=True)
    common.save('100万人工原行の公開変化と元全原行による同一loss66及び性能検査.json',
                dict(合格=True, 検査=rows, 全原板会計の間引き=0, 元全原行Pythonを保持=True,
                     SHA256=common.fingerprint([Path(__file__), Path(common.__file__), Path(check_loss.__file__)]),
                     正式95損益実行=0, 正式95損益閲覧=0, API取得=0, 実注文=0,
                     限界='人工100万行の同式コスト。正式全2356口座の全会計検算を置換又は省略しない。'))


if __name__ == '__main__':
    main()
