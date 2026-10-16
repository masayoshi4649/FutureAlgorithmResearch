"""既存研究を変更せず、監査用キャッシュだけで今回の関数を読み込む。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode = True
import numba
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OLD = ROOT / 'work/wave_v81'
numba.config.CACHE_DIR = str(HERE / 'numba_cache')
spec = importlib.util.spec_from_file_location('engine', OLD / 'engine.py')
engine = importlib.util.module_from_spec(spec)
sys.modules['engine'] = engine
spec.loader.exec_module(engine)
sys.path.insert(0, str(WORK))
import research
numba.config.CACHE_DIR = str(HERE / 'numba_cache')


def load(path: Path) -> object:
    """機能: 保存済みファイルを読取専用で読む。

    引数: path(Path)。返り値: 復元内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 大きな保存ファイルの指紋を分割読取で求める。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def save(name: str, value: dict) -> None:
    """機能: 監査領域へ日本語の検査証跡を保存する。

    引数: name(str)、value(dict)。返り値: なし(None)。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def synthetic(times, bids, own, asks=None, **options) -> list:
    """機能: 売買反転の境界を明示した人工36引数を作る。

    引数: times/bids/own(list)、asks(list|None)、options(dict)。返り値: 入力(list)。
    """
    times = np.asarray(times, dtype=float)
    bids = np.asarray(bids, dtype=float)
    asks = bids + 1. if asks is None else np.asarray(asks, dtype=float)
    own = np.asarray(own, dtype=np.int8)
    n = len(times)
    k = dict(tick=1., start=0., limit=300., quantity=10, value=1000., fee_unit=41.8,
             latency=5., entry_mode=0, exit_mode=0, solo=0, repair=0)
    k.update(options)
    a = [times, bids, asks, np.ones(n, dtype=bool), np.zeros(n, dtype=bool), np.arange(n),
         times.copy(), own, np.arange(n), np.maximum(np.arange(n)-1, 0), bids.copy(), asks.copy(),
         *[k[x] for x in ('tick','start','limit','quantity','value','fee_unit','latency','entry_mode')],
         *([0]*6), own.copy(), np.ones(n,dtype=bool), np.ones(n,dtype=bool),
         *[k[x] for x in ('exit_mode','solo','repair')]]
    return a + [a[7], a[26], a[27], a[28]]


def opposite(args: list) -> list:
    """機能: 人工入力を複製して方向4列のみ独立に反転する。

    引数: args(list)。返り値: 新しい引数列(list)。
    """
    out = [x.copy() if isinstance(x,np.ndarray) else x for x in args]
    for i in (7,26,32,33):
        out[i] *= -1
    return out


def mirrored(forward: dict, reverse: dict, args: tuple) -> dict:
    """機能: 同時刻成行反転の組別恒等式と時計不変を検査する。

    引数: forward/reverse(dict:台帳)、args(tuple)。返り値: 照合件数(dict)。
    """
    assert args[19] == 0
    f, r = forward['orders'], reverse['orders']
    np.testing.assert_array_equal(f[:,[0,1,2,4,6,7,8,9,10,11,12,13,14,15,16,17]],
                                  r[:,[0,1,2,4,6,7,8,9,10,11,12,13,14,15,16,17]])
    np.testing.assert_array_equal(f[:,3], -r[:,3])
    t, u = forward['trades'], reverse['trades']
    np.testing.assert_array_equal(t[:,[0,1,2,4,7,8,11]], u[:,[0,1,2,4,7,8,11]])
    np.testing.assert_array_equal(t[:,3], -u[:,3])
    er, xr = t[:,1].astype(int), t[:,2].astype(int)
    mid = (args[1] + args[2]) / 2
    spread = t[:,3] * ((t[:,5]-mid[er]) + (mid[xr]-t[:,6])) * t[:,4] * args[16]
    costs = spread + t[:,7] + t[:,8]
    expected = -t[:,10] - 2 * costs
    np.testing.assert_allclose(u[:,10], expected, rtol=0, atol=1e-5)
    np.testing.assert_allclose(u[:,9]+t[:,9], -2*spread, rtol=0, atol=1e-5)
    for col in [0,1,2,3,6,7,8]:
        if col == 7:
            continue
        np.testing.assert_array_equal(forward['events'][:,col],reverse['events'][:,col])
    return dict(注文数=len(f), 決済組数=len(t), 元収支=float(t[:,10].sum()),
                逆収支=float(u[:,10].sum()), 気配差と料金=float(costs.sum()), 恒等式誤差=float(abs(u[:,10]-expected).max()) if len(t) else 0.)


def ledger(out: tuple) -> dict:
    """機能: エンジン配列を監査入力へ接続する。

    引数: out(tuple)。返り値: 台帳(dict)。
    """
    return dict(orders=out[0], trades=out[1], curve=out[2], stats=out[3], events=out[4])
