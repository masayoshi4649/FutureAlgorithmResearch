"""公表活動特徴の因果性・上下対称・欠測処理を人工値だけで確かめる。"""

import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import activity130 as source
from common130 import reference


def fixture(n: int = 96) -> list[np.ndarray]:
    """
    機能: 公表買い方向代理が既知の連続原行を作る。
    引数: n(int)は長さ。
    返り値: list[ndarray]は計算関数に渡す七配列。
    """
    t = np.arange(n, dtype=float)
    bid = 100. + .1 * t
    ask = bid + 1.
    last = ask.copy()
    volume = 1000. + t
    return [t, last, volume, bid, ask, np.arange(n), np.ones(n, dtype=np.bool_)]


def same(left: tuple, right: tuple) -> bool:
    """
    機能: 欠測を保ち人工結果を比較する。
    引数: left/right(tuple)は特徴・始端・内訳。
    返り値: boolは全配列の一致。
    """
    return all(np.allclose(a, b, equal_nan=True, atol=1e-10, rtol=0.) for a, b in zip(left, right))


def main() -> None:
    """
    機能: 人工基準・未来切断・毒化・未知・上下対称を確認する。
    引数: なし。
    返り値: None。金融・実注文・約定シミュレーションは一切実行しない。
    """
    checks = []
    base = fixture()
    expected = source.calculate(*base)
    assert expected[1][60] == 29
    assert np.allclose(expected[0][60], [3.1, 31., 31., 1.])
    checks.append("厳密前始端と公表正増分31件")
    assert same(expected, source.calculate.py_func(*base))
    checks.append("コンパイル有無同値")
    for badtime in (np.nan, np.inf, -100.):
        bad = [a.copy() for a in base]
        bad[0][48] = badtime
        try:
            source.calculate(*bad)
        except ValueError:
            checks.append("非有限又は逆行価格時計を明示拒否")
        else:
            raise AssertionError("不正時計が拒否されなかった")
    for cut in range(32, 96, 3):
        prefix = source.calculate(*[a[:cut].copy() for a in base])
        assert same(prefix, tuple(a[:cut] for a in expected))
        changed = [a.copy() for a in base]
        for k in (1, 2, 3, 4):
            changed[k][cut:] = np.nan
        poisoned = source.calculate(*changed)
        assert same(tuple(a[:cut] for a in poisoned), prefix)
        checks.extend([f"未来切断{cut}", f"未来値毒化{cut}"])
    mirror = [a.copy() for a in base]
    mirror[1], mirror[3], mirror[4] = 300. - base[1], 300. - base[4], 300. - base[3]
    reflected = source.calculate(*mirror)
    assert np.allclose(expected[0][:, 0], -reflected[0][:, 0], equal_nan=True)
    assert np.allclose(expected[0][:, 2], -reflected[0][:, 2], equal_nan=True)
    assert np.array_equal(expected[0][:, 1], reflected[0][:, 1], equal_nan=True)
    checks.append("価格上下反転で数量不変・価格差と方向代理反転")
    for column in (1, 2, 3, 4, 6):
        bad = [a.copy() for a in base]
        bad[column][48] = False if column == 6 else np.nan
        out = source.calculate(*bad)
        assert out[0][60, 3] == 0. and np.isnan(out[0][60, :3]).all()
        assert out[0][82, 3] == 1.
        checks.append(f"必要値欠測{column}と窓経過後回復")
    bad = [a.copy() for a in base]
    bad[2][48:] -= 1000.
    out = source.calculate(*bad)
    assert out[0][60, 3] == 0. and out[0][82, 3] == 1.
    checks.append("出来高逆戻りを累計増分へ足さず未知・回復")
    bad = [a.copy() for a in base]
    bad[5][48:] += 1
    out = source.calculate(*bad)
    assert out[0][60, 3] == 0. and out[0][82, 3] == 1.
    checks.append("原行飛びは未知・回復")
    bad = [a.copy() for a in base]
    bad[4][48] = bad[3][48]
    out = source.calculate(*bad)
    assert out[0][60, 3] == 0. and out[0][82, 3] == 1.
    checks.append("交差及び同値気配は未知")
    zero = [a.copy() for a in base]
    zero[2][:] = 1000.
    out = source.calculate(*zero)
    assert np.array_equal(out[0][60, 1:], [0., 0., 1.])
    checks.append("出来高ゼロは既知ゼロであり候補正増分条件を満たさない")
    amb = [a.copy() for a in base]
    amb[1] = (amb[3] + amb[4]) / 2.
    out = source.calculate(*amb)
    assert out[0][60, 2] == 0. and out[0][60, 1] == 31. and out[2][60, 2] == 31.
    checks.append("気配間内の公表値は曖昧量・符号ゼロ")
    repeated = fixture(180)
    repeated[0] = np.repeat(np.arange(90, dtype=float), 2)
    full = source.calculate(*repeated)
    for cut in (101, 102, 103):
        prefix = source.calculate(*[a[:cut] for a in repeated])
        assert same(prefix, tuple(a[:cut] for a in full))
        changed = [a.copy() for a in repeated]
        changed[2][cut:] += 1000000.
        assert same(prefix, tuple(a[:cut] for a in source.calculate(*changed)))
        checks.append(f"同時計後続行を見ない{cut}")
    result = dict(passed=True, financial_replays=0, checks=len(checks), details=checks,
        source=reference(Path(source.__file__)), producer=reference(Path(__file__)))
    target = HERE / f"原板活動の作者人工_{time.time_ns()}.json"
    source.dump(target, result)
    print(target)
    print(len(checks), "人工確認 合格")


if __name__ == "__main__":
    main()
