"""保険・二市場途中判断・返済後ドテンの原本順を人工経路で独立検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys

import numba
import numpy as np

from adapters import check
from independent_account import CAP, POINT, fee, save


HERE = Path(__file__).resolve().parent
os.environ.setdefault("NUMBA_CACHE_DIR", str(HERE / "cache"))
numba.config.CACHE_DIR = str(HERE / "cache")
spec = importlib.util.spec_from_file_location("wave76_audit_engine", HERE.parent / "engine.py")
engine = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = engine
spec.loader.exec_module(engine)


def fixture(symbol: str, mode: int, side: int = 1) -> dict:
    """機能: 原本1秒・共同5秒格子の一定気配と反対合意を人工生成する。

    引数: symbol(str)、mode/side(int)。返り値: 再生引数に接続できる辞書(dict)。
    """
    tick, opening = (.5, 4000.) if symbol == "TOPIX" else (10., 65000.)
    n = 1900
    times = np.arange(n, dtype=float) + 10_000.
    grid = np.arange(300., 1801., 5.) + times[0]
    mapped = np.full(n, -1, dtype=np.int64)
    mapped[(grid - times[0]).astype(int)] = np.arange(len(grid))
    event = np.zeros(n, dtype=np.int8)
    event[300] = side
    opposite = grid >= times[0] + 320.
    strong = np.full(len(grid), -side, dtype=np.int8)
    strong[grid < times[0] + 320.] = side
    return dict(symbol=symbol, mode=mode, time_s=times, seq=np.arange(n, dtype=np.int64) * 3 + 7,
        bid=np.full(n, opening), ask=np.full(n, opening + tick), quality=np.ones(n, bool),
        reset=np.zeros(n, bool), event=event, mapped=mapped, tick=tick, start=times[0],
        limit=times[0] + 1800., quantity=CAP[symbol], value=POINT[symbol],
        fee_unit=41.8 if symbol == "TOPIX" else 11., width=4. * tick,
        grid=grid, valid=np.ones(len(grid), bool), strong=strong,
        loss_long=np.zeros(len(grid), bool), loss_short=np.zeros(len(grid), bool),
        opposite_long=opposite.copy() if side == 1 else np.zeros(len(grid), bool),
        opposite_short=opposite.copy() if side == -1 else np.zeros(len(grid), bool),
        hold=0., cooldown=30., flip_expiry=30.)


def arguments(d: dict) -> tuple:
    """機能: 人工証拠を凍結予定の途中判断再生器へ接続する。

    引数: d(dict)。返り値: simulateへ渡す位置引数(tuple)。
    """
    return (d["time_s"], d["bid"], d["ask"], d["quality"], d["reset"], d["event"], d["mapped"],
        d["tick"], d["start"], d["limit"], d["quantity"], d["value"], d["fee_unit"], d["width"],
        d["tick"], d["grid"], d["valid"], d["strong"], d["loss_long"], d["loss_short"],
        d["opposite_long"], d["opposite_short"], d["mode"], d["hold"], d["cooldown"], d["flip_expiry"])


def structure(out: tuple) -> list[tuple]:
    """機能: 注文の約定行・判断行・方向・理由・新規返済だけを抽出する。

    引数: out(tuple)。返り値: 注文構造(list[tuple])。
    """
    return [tuple(int(o[k]) for k in (0, 1, 3, 6, 7)) for o in out[0]]


def run(d: dict, expected: list[tuple] | None = None, require_flat: bool = True) -> tuple:
    """機能: 人工注文順序と気配・双方料金・全明細・清算時価を独立確認する。

    引数: d(dict)、expected(list[tuple]|None)、require_flat(bool)。返り値: 再生結果(tuple)。
    """
    out = engine.simulate(*arguments(d))
    if expected is not None:
        assert structure(out) == expected, (d["symbol"], d["mode"], structure(out), expected)
    account = check(d, d["symbol"], out[0], out[1], out[2], require_flat)
    for trade in out[1]:
        assert int(trade[4]) == CAP[d["symbol"]]
        assert int(trade[7]) == int(trade[8]) == fee(d["symbol"], CAP[d["symbol"]])
    assert account["fees"] == len(out[0]) * fee(d["symbol"], CAP[d["symbol"]])
    return out


def main() -> None:
    """機能: 人工の反転・欠測・優先順位・次気配約定と未来切断を検査する。

    引数: なし。返り値: なし(None)。実損益結果、原本、APIは読まない。
    """
    initial_sha = hashlib.sha256((HERE.parent / "engine.py").read_bytes()).hexdigest()
    checks = future_checks = 0
    for symbol in CAP:
        for side in (-1, 1):
            first = (301, 300, side, 10, 1)
            final = (1741, 1740, -side, 4, 0)
            for mode in range(4):
                d = fixture(symbol, mode, side)
                if mode == 0:
                    expected = [first, final]
                elif mode == 1:
                    expected = [first, (321, 320, -side, 6, 0)]
                else:
                    expected = [first, (321, 320, -side, 6, 0), (326, 325, -side, 12, 1),
                        (1741, 1740, side, 4, 0)]
                out = run(d, expected)
                assert int(out[4][7]) == int(mode >= 2)
                checks += 1
                # ----------------------------------------
                # 時計と原本seq途中の切断は、配列末尾での架空返済を発生させない。
                for cut in (301, 305, 321, 323, 326, 350, 1741):
                    prefix = deepcopy(d)
                    for key in ("time_s", "seq", "bid", "ask", "quality", "reset", "event", "mapped"):
                        prefix[key] = prefix[key][:cut].copy()
                    got = run(prefix, require_flat=False)
                    np.testing.assert_allclose(got[0], out[0][out[0][:, 0] < cut], rtol=0, atol=0)
                    np.testing.assert_allclose(got[1], out[1][out[1][:, 2] < cut], rtol=0, atol=0)
                    np.testing.assert_allclose(got[2], out[2][:cut], rtol=0, atol=1.e-4)
                    future_checks += 1
                for cut in (315, 325, 1700):
                    changed = deepcopy(d)
                    changed["bid"][cut:] *= .8
                    changed["ask"][cut:] *= 1.2
                    changed["quality"][cut:] = False
                    changed["reset"][cut:] = True
                    gfuture = changed["grid"] >= changed["time_s"][cut]
                    changed["strong"][gfuture] *= -1
                    changed["valid"][gfuture] = False
                    for field in ("loss_long", "loss_short", "opposite_long", "opposite_short"):
                        changed[field][gfuture] = ~changed[field][gfuture]
                    got = run(changed)
                    np.testing.assert_allclose(got[0][got[0][:, 0] < cut], out[0][out[0][:, 0] < cut], rtol=0, atol=0)
                    np.testing.assert_allclose(got[1][got[1][:, 2] < cut], out[1][out[1][:, 2] < cut], rtol=0, atol=0)
                    np.testing.assert_allclose(got[2][:cut], out[2][:cut], rtol=0, atol=1.e-4)
                    future_checks += 1
        # ----------------------------------------
        # 支持消失だけはM3で返済し、反対合意でないためドテン予約を作らない。
        d = fixture(symbol, 3)
        d["opposite_long"][:] = False
        d["strong"][d["grid"] >= d["start"] + 320.] = 0
        d["loss_long"][d["grid"] >= d["start"] + 320.] = True
        run(d, [(301, 300, 1, 10, 1), (321, 320, -1, 7, 0)])
        checks += 1
        for mode in (0, 1, 2):
            d["mode"] = mode
            run(d, [(301, 300, 1, 10, 1), (1741, 1740, -1, 4, 0)])
            checks += 1
        # ----------------------------------------
        # 反対確認・保険・期限が同時成立しても優先順位は固定される。
        d = fixture(symbol, 2)
        d["bid"][320:] -= 5 * d["tick"]
        d["ask"][320:] -= 5 * d["tick"]
        run(d, [(301, 300, 1, 10, 1), (321, 320, -1, 1, 0)])
        checks += 1
        d = fixture(symbol, 2)
        d["hold"] = 19.
        run(d, [(301, 300, 1, 10, 1), (321, 320, -1, 3, 0)])
        checks += 1
        d = fixture(symbol, 2)
        d["opposite_long"][:] = False
        d["opposite_long"][d["grid"] >= d["start"] + 1740.] = True
        run(d, [(301, 300, 1, 10, 1), (1741, 1740, -1, 4, 0)])
        checks += 1
        # ----------------------------------------
        # 次有効気配待ち中と同時計別seqでも、返済後の新格子を待つ。
        d = fixture(symbol, 2)
        d["bid"][321:325] = np.nan
        d["ask"][321:325] = np.nan
        run(d, [(301, 300, 1, 10, 1), (325, 320, -1, 6, 0),
            (331, 330, -1, 12, 1), (1741, 1740, 1, 4, 0)])
        checks += 1
        d = fixture(symbol, 2)
        d["time_s"][321] = d["time_s"][320]
        run(d, [(301, 300, 1, 10, 1), (321, 320, -1, 6, 0),
            (326, 325, -1, 12, 1), (1741, 1740, 1, 4, 0)])
        checks += 1
        for field in ("quality", "reset"):
            d = fixture(symbol, 2)
            d[field][320] = field == "reset"
            run(d, [(301, 300, 1, 10, 1), (326, 325, -1, 6, 0),
                (331, 330, -1, 12, 1), (1741, 1740, 1, 4, 0)])
            checks += 1
        d = fixture(symbol, 2)
        d["quality"][325] = False
        out = run(d, [(301, 300, 1, 10, 1), (321, 320, -1, 6, 0)])
        assert int(out[4][8]) == 1
        checks += 1
        d = fixture(symbol, 2)
        d["bid"][301:310] = np.nan
        d["ask"][301:310] = np.nan
        d["opposite_long"][d["grid"] >= d["start"] + 310.] = True
        d["strong"][d["grid"] >= d["start"] + 310.] = -1
        run(d, [(310, 300, 1, 10, 1), (316, 315, -1, 6, 0),
            (321, 320, -1, 12, 1), (1741, 1740, 1, 4, 0)])
        checks += 1
        # ----------------------------------------
        # 反転再確認が消えた時、又は格子が来る前に期限を過ぎた時に予約を取消す。
        d = fixture(symbol, 2)
        d["strong"][d["grid"] >= d["start"] + 325.] = 0
        out = run(d, [(301, 300, 1, 10, 1), (321, 320, -1, 6, 0)])
        assert int(out[4][8]) == 1
        checks += 1
        d = fixture(symbol, 2)
        d["mapped"][322:355] = -1
        out = run(d, [(301, 300, 1, 10, 1), (321, 320, -1, 6, 0)])
        assert int(out[4][8]) == 1
        checks += 1
        d = fixture(symbol, 2)
        d["reset"][300] = True
        run(d, [])
        checks += 1
        d = fixture(symbol, 0)
        d["bid"][301:1500] = np.nan
        d["ask"][301:1500] = np.nan
        run(d, [])
        checks += 1
    assert hashlib.sha256((HERE.parent / "engine.py").read_bytes()).hexdigest() == initial_sha
    save(HERE / "途中判断と実約定後ドテンの人工独立監査.json", dict(合格=True,
        人工経路数=checks, 未来改変及び切断比較数=future_checks,
        検査=["両方向のM0/M1/M2/M3", "支持消失と反対合意の区別", "場末・期限・保険・管理の優先",
            "返済fill後の新格子と次原本行新規", "同時計別seq", "次有効気配", "新規当行子判断禁止",
            "反転再確認消失と予約期限取消", "双方料金と全明細・全行清算時価", "配列終端の架空返済禁止"],
        engine_SHA256=initial_sha,
        限界="人工の共同状態入力を検査。実際の板特徴・共同状態計算・共通受信順の証明は別監査。",
        原本取得=0, API取得=0, 実注文=0))
    print(f"人工{checks}経路・未来{future_checks}比較の独立約定会計が合格しました")


if __name__ == "__main__":
    main()
