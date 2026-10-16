"""新しい売買を実行せず、既知原本LPの15秒・300秒価格窓を別保存する。"""

import json
from pathlib import Path
import pickle
import socket
import sys

import numba
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
import data


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 入力準備による外部通信を拒否する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None。接続を呼ぶと例外を出す。
    """
    raise RuntimeError('保存入力だけで追従価格素材を作ります')


def save(path: Path, value: object) -> None:
    """
    機能: 新しい準備領域へ入力を保存し、完成入力の上書きを防ぐ。
    引数: path(Path)、value(object)。
    返り値: None。JSON又はpickleを新規作成する。
    """
    assert path.resolve().is_relative_to((HERE / 'prepared').resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def price_features(grid: np.ndarray, record: dict) -> dict:
    """
    機能: 1秒より厳密に前の独立LP源から、15秒・300秒の正常価格変位を求める。
    引数: grid(ndarray[float])、record(dict)は独立LP系列。
    返り値: dictはcurrent/windows。Q、OFI、BBO及び約定品質を生成しない。
    """
    source = data.module('独立LP窓94の関数読取95', HERE.parent / 'wave_v94/inputs_r1/last_price.py')
    numba.config.CACHE_DIR = str(HERE / 'jit_input')
    times, prices, seq = record['time_s'], record['last'], record['seq']
    assert np.isfinite(times).all() and (np.diff(times) >= 0).all()
    if not len(times):
        missing = np.full(len(grid), np.nan)
        index = np.full(len(grid), -1, np.int32)
        sequence = np.full(len(grid), -1, np.int64)
        flags = np.zeros(len(grid), bool)
        current = dict(index=index, raw_seq=sequence, time_s=missing.copy(), value=missing.copy(),
                       valid=flags, age=missing.copy(), actual_age=missing.copy())
        windows = {seconds: dict(now=index.copy(), old=index.copy(), now_seq=sequence.copy(),
                   old_seq=sequence.copy(), source_valid=flags.copy(), same_row=flags.copy(),
                   reset_or_invalid_cross=flags.copy(), now_time_s=missing.copy(),
                   old_time_s=missing.copy(), now_value=missing.copy(), old_value=missing.copy(),
                   old_age=missing.copy(), actual_seconds=missing.copy(), ret_bp=missing.copy(),
                   ratio_ret_bp=missing.copy())
                   for seconds in (15, 300)}
        return dict(current=current, windows=windows)
    endpoint = record['valid'] & np.isfinite(prices) & (prices > 0)
    now, age = source.CORE.LEGACY.asof_indices(grid - 1., times, endpoint, record['reset'], 30.)
    safe_now = np.maximum(now, 0)
    current = dict(index=now, raw_seq=seq[safe_now].copy(), time_s=times[safe_now].copy(),
                   value=prices[safe_now].copy(), valid=now >= 0, age=age, actual_age=age + 1.)
    current['raw_seq'][now < 0] = -1
    current['time_s'][now < 0] = np.nan
    current['value'][now < 0] = np.nan
    broken = np.r_[0, np.cumsum(~endpoint | record['reset'], dtype=np.int64)]
    windows = {}
    for seconds in (15, 300):
        old, old_age = source.CORE.LEGACY.asof_indices(grid - 1. - seconds, times,
                                                    endpoint, record['reset'], 30.)
        safe_old = np.maximum(old, 0)
        available = (now >= 0) & (old >= 0)
        crossed = available & ((broken[safe_now + 1] - broken[safe_old + 1]) > 0)
        valid = available & (old < now) & ~crossed
        values = dict(now=now.copy(), old=old, now_seq=current['raw_seq'].copy(),
                      old_seq=seq[safe_old].copy(), source_valid=valid,
                      same_row=available & (old == now), reset_or_invalid_cross=crossed,
                      now_time_s=current['time_s'].copy(), old_time_s=times[safe_old].copy(),
                      now_value=current['value'].copy(), old_value=prices[safe_old].copy(),
                      old_age=old_age, actual_seconds=times[safe_now] - times[safe_old],
                      ret_bp=(prices[safe_now] - prices[safe_old]) / prices[safe_old] * 10000.,
                      ratio_ret_bp=(prices[safe_now] / prices[safe_old] - 1.) * 10000.)
        values['old_seq'][old < 0] = -1
        values['old_time_s'][old < 0] = np.nan
        values['old_value'][old < 0] = np.nan
        for field in ('actual_seconds', 'ret_bp', 'ratio_ret_bp'):
            values[field][~valid] = np.nan
        windows[seconds] = values
    return dict(current=current, windows=windows)


def main() -> None:
    """
    機能: 62口座の価格窓と独立源対応を生成し、既存300秒計算と旧入力不変を検査する。
    引数: なし。
    返り値: None。新しい売買及び損益の計算は行わない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    target = HERE / 'prepared'
    assert not (target / 'metadata.json').exists()
    artificial_path = target / '独立価格15秒と300秒の人工境界及び未来不変.json'
    artificial = data.read(artificial_path)
    assert artificial['全合格'] and artificial['人工種類'] == 10
    for relative, expected in artificial['SHA256'].items():
        assert data.digest(ROOT / relative) == expected, relative
    material = data.previous.load_inputs()
    sessions = material['metadata']['sessions']
    assert len(sessions) == 31
    before = {str(path.relative_to(ROOT)): data.digest(path) for path in material['paths']}
    raw_path = HERE.parent / 'wave_v94/prepared_r1/raw_last_records.pkl'
    records = data.read(raw_path)
    before[str(raw_path.relative_to(ROOT))] = data.digest(raw_path)
    codes = {str(path.relative_to(ROOT)): data.digest(path)
             for path in (Path(__file__), HERE / 'data.py', artificial_path,
                          HERE / '価格窓の事前人工検査.py')}
    output, mappings, checks = {}, {}, []
    for session in sessions:
        grid = material['grids'][session]['grid']
        reference = material['prices'][session, 'TOPIX']
        candidate_grid = np.arange(reference['start'] + 300., reference['limit'] - 300., 15.)
        positions = np.searchsorted(grid, candidate_grid)
        assert (positions < len(grid)).all()
        np.testing.assert_array_equal(candidate_grid, grid[positions])
        markets = {}
        for symbol in data.SYMBOLS:
            key = session, symbol
            raw, old = records[key], material['price_lanes']['I3'][session]['markets'][symbol]
            computed = price_features(grid, raw)
            for field in ('index', 'raw_seq', 'time_s', 'value', 'valid', 'age', 'actual_age'):
                np.testing.assert_array_equal(computed['current'][field], old['current'][field])
            for field in ('now', 'old', 'now_seq', 'old_seq', 'source_valid', 'same_row',
                          'reset_or_invalid_cross', 'actual_seconds', 'ret_bp', 'old_age'):
                np.testing.assert_array_equal(computed['windows'][300][field], old['windows'][300][field])
            record = material['prices'][key]
            indexes = np.searchsorted(raw['seq'], record['seq'])
            assert (indexes < len(raw['seq'])).all()
            np.testing.assert_array_equal(raw['seq'][indexes], record['seq'])
            np.testing.assert_array_equal(raw['time_s'][indexes], record['time_s'])
            np.testing.assert_array_equal(raw['last'][indexes], record['price'])
            mappings[key] = indexes.astype(np.int32)
            assert len(candidate_grid) == len(material['legacy'][key]['states'])
            markets[symbol] = computed
            checks.append(dict(場=session, 商品=symbol, 全格子=len(grid), 発火格子=len(candidate_grid),
                               価格300秒完全一致=True, 執行原seq時計価格の全対応一致=True,
                               LP15秒有効=int(computed['windows'][15]['source_valid'].sum())))
        output[session] = dict(grid=grid, markets=markets, candidate_grid=candidate_grid,
                               candidate_positions=positions.astype(np.int32))
        print(f'{session}: 独立15秒窓・旧300秒一致・候補格子と執行原seq対応を保存準備', flush=True)
    for relative, expected in before.items():
        assert data.digest(ROOT / relative) == expected, relative
    for relative, expected in codes.items():
        assert data.digest(ROOT / relative) == expected, relative
    path = target / 'trend_prices.pkl'
    save(path, dict(I3=output, execution_lp_index=mappings))
    save(target / 'metadata.json', dict(全31既知=True, 新未見場数=0, sessions=sessions, 口座数=62,
         検査=checks, 旧入力SHA256=before, 新コードSHA256=codes,
         新入力SHA256={str(path.relative_to(ROOT)): data.digest(path)},
         源の分離='価格indexは原本LP系列。執行indexは旧retained板系列。原seqで一致を全検査。',
         旧BBO及びQ及びOFI変更=0, 正式新売買実行=0, 正式新損益閲覧=0, API取得=0, 実注文=0))
    print('62口座の追従用価格素材を保存。正式新損益は未実行。', flush=True)


if __name__ == '__main__':
    main()
