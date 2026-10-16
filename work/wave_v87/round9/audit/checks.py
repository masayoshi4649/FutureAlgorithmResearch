"""保険の入口を固定し、建値・過去極値の初期停止を因果境界で検査する。"""

import argparse
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
    機能: 原実装を変更せず監査専用名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def save(name, value):
    """
    機能: 今回の監査フォルダだけへ有限値JSONを保存する。
    引数: name(str)、value(dict)。
    返り値: None。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def hashes():
    """
    機能: 監査開始後の実装変更を検知する。
    引数: なし。
    返り値: dict[str,str]。
    """
    return {name: hashlib.sha256((WORK / name).read_bytes()).hexdigest()
            for name in ('catalog.py', 'strategy.py', 'engine.py', 'build_engine.py', 'prepare.py')}


def load():
    """
    機能: 新戦略と旧素材道具を読み込み、監査用キャッシュを分ける。
    引数: なし。
    返り値: tuple[module,dict,module,module]。
    """
    strategy = module('監査87構造停止戦略', WORK / 'strategy.py')
    catalog = module('監査87構造停止条件', WORK / 'catalog.py')
    fixture = module('監査87構造停止人工素材', WORK.parent / 'round7/audit/checks.py')
    old = module('監査87構造停止旧基準', WORK.parent / 'round8/strategy.py')
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    strategy.base.integration.reference.initialize()
    return strategy, {c['id']: c for c in catalog.catalog()}, fixture, old


def rounded(price, tick, side):
    """
    機能: 原エンジンを呼ばず停止方向の呼値丸めを計算する。
    引数: price/tick(float)、side(int)。
    返り値: float。
    """
    return (math.ceil(price / tick - 1e-9) if side > 0 else math.floor(price / tick + 1e-9)) * tick


def initial_line(mode, entry, extreme, side, atr, tick):
    """
    機能: 四対照の初期停止線を定義から独立に復元する。
    引数: mode/side(int)、entry/extreme/atr/tick(float)。
    返り値: float。
    """
    if mode in (0, 3):
        raw = entry - side * max(tick, (.25 if mode == 0 else .5) * atr)
    else:
        raw = extreme - side * (tick if mode == 2 else 0.)
    return rounded(raw, tick, -side)


def arguments(ready, core, observed, support_start=0):
    """
    機能: 同一の元注文と公開済み支持から人工再生引数を構成する。
    引数: ready(dict)、core(ndarray)、observed(bool)、support_start(int)。
    返り値: tuple。支持は指定観測より前には中立とする。
    """
    n = len(ready['last'])
    seq = np.arange(n, dtype=np.int64) * 10
    values = np.zeros(n)
    values[support_start:] = -.1 * core[0, 3]
    valid = np.ones(n, bool)
    return (ready['time_s'], ready['last'], core, ready['quiet'], ready['quiet'],
        ready['end'], 0., ready['tick'], -1, 0., .25, .5, .25, observed, .5, .5, 1,
        seq, values, valid, values.copy(), valid.copy(), seq.copy(), ready['time_s'] - 1)


def verify_result(out, ready, mode):
    """
    機能: 新規前極値、初期停止、次観測発動とトレール更新の因果順を検算する。
    引数: out(tuple)、ready(dict)、mode(int)。
    返り値: None。
    """
    orders, _, _, events, _, proofs = out
    for proof in proofs:
        row, cid = map(int, proof[:2])
        assert proof[5] < row and proof[2] < row and proof[3] < row
        entry = orders[(orders[:, 2] == cid) & (orders[:, 7] == 1)][0]
        child = events[(events[:, 1] == cid) & (events[:, 2] == 3)]
        assert child[0, 0] == row and child[0, 9] == 81
        expected = initial_line(mode, entry[5], proof[4], entry[3], child[0, 8], ready['tick'])
        assert abs(expected - child[0, 6]) < 1e-8
        for first, later in zip(child, child[1:]):
            assert later[0] > row and later[9] == 82
            assert entry[3] * (later[6] - first[6]) > 0
            values = ready['last'][row + 1:int(later[0]) + 1]
            values = values[np.isfinite(values) & (values > 0)]
            peak = max(entry[5], values.max()) if entry[3] > 0 else min(entry[5], values.min())
            assert entry[3] * (peak - entry[5]) >= .5 * later[8] - 1e-8
            line = rounded(peak - entry[3] * max(ready['tick'], .25 * later[8]), ready['tick'], -entry[3])
            assert abs(line - later[6]) < 1e-8
    assert all(o[1] < o[0] for o in orders)


def synthetic(strategy, fixture, old):
    """
    機能: 売買反射・両商品・両約定について入口不変と構造停止の境界を確認する。
    引数: strategy/fixture/old(module)。
    返り値: None。人工損益は市場優位の選抜へ用いない。
    """
    before = hashes()
    records = []
    scenarios = [
        ('四停止の呼値と接触', [100, 100, 102, 100, 101, 102, 103, 104, 104], 0, None, None, None),
        ('入口が線を通過した観測約定', [100, 100, 102, 99, 100, 101, 102, 103, 104, 104], 0, None, None, None),
        ('支持遅れ後の構造線破断は次観測成行', [100, 100, 103, 100, 99, 105, 101, 101, 101], 4, None, None, None),
        ('構造線破断後の無効価格を飛ばす', [100, 100, 103, 100, 99, 105, np.nan, 101, 101, 101], 4, None, None, None),
        ('保険側追尾だけが初期線を短縮', [100, 100, 104, 102, 100, 99, 100, 101, 101], 0, None, None, None),
        ('新規と元終了が同じ観測', [100, 100, 102, 100, 100, 100], 0, 3, None, None),
        ('代理時計同値でも子は次原本行', [100, 100, 102, 100, 100, 100], 0, 3, [0, 1, 2, 3, 3, 4], None),
        ('米国静観を初期停止より優先', [100, 100, 102, 100, 100, 100], 0, 4, None, [False, False, False, False, True, False]),
        ('予定場末を初期停止より優先', [100, 100, 102, 100, 100, 100], 0, 4, None, 'end'),
    ]
    for symbol in ('TOPIX', 'NK225'):
        for reflected in (False, True):
            for observed in (False, True):
                for label, values, support_start, closed, times, quiet in scenarios:
                    last = len(values) - 2 if closed is None else closed
                    kwargs = dict(symbol=symbol, reflected=reflected)
                    if times is not None:
                        kwargs['times'] = times
                    if isinstance(quiet, list):
                        kwargs['quiet'] = quiet
                    if quiet == 'end':
                        kwargs['end'] = 4.
                    ready, core = fixture.material(values, [(1, 1, 1, 100), (last, 0, 1, values[last])], **kwargs)
                    args = arguments(ready, core, observed, support_start)
                    baseline = old.engine.simulate(*args)
                    openings = baseline[0][baseline[0][:, 7] == 1]
                    for mode in range(4):
                        out = strategy.engine.simulate(*args, mode)
                        verify_result(out, ready, mode)
                        np.testing.assert_array_equal(out[0][out[0][:, 7] == 1], openings)
                        np.testing.assert_array_equal(out[5], baseline[5])
                        if mode == 0:
                            for actual, expected in zip(out, baseline):
                                np.testing.assert_array_equal(actual, expected)
                        if label.startswith('支持遅れ') or label.startswith('構造線破断後'):
                            if mode in (1, 2):
                                exit_row = 6 if np.isfinite(values[6]) else 7
                                assert out[0][-1, 0] == exit_row and out[0][-1, 6] == 81
                                assert out[0][-1, 5] == ready['last'][exit_row]
                        if label.startswith('新規と') or label.startswith('代理時計'):
                            assert out[0][:, 0].tolist() == [3, 4] and out[0][-1, 6] == 83
                        if label.startswith('米国'):
                            assert out[0][-1, 6] == 84
                        if label.startswith('予定場末'):
                            assert out[0][-1, 6] == 85
                        records.append(dict(検査=label, 商品=symbol, 反射=reflected, 観測約定=observed, 停止方式=mode))
    assert before == hashes()
    save('構造停止の入口不変と発動境界の人工検査.json', dict(全合格=True, 検査数=len(records), 検査=records, コードSHA256=before))


def main():
    """
    機能: 構造停止の人工境界検査を実行する。
    引数: なし。
    返り値: None。
    """
    strategy, _, fixture, old = load()
    synthetic(strategy, fixture, old)


if __name__ == '__main__':
    main()
