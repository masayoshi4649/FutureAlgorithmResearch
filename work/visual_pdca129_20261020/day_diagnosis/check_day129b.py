"""両市場逆行の持続確認を純人工で検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numba
import numpy as np

import check_day129 as prior


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(TASK))
import day129b

numba.config.CACHE_DIR = str(HERE/"jit_b")
CHECKS = []
CASES = []


def check(name: str, condition: bool) -> None:
    """
    機能: 期待結果の一致を記録する。
    引数: name(str)、condition(bool)は検査名と成否。
    返り値: None。不一致なら停止する。
    """
    assert condition, name
    CHECKS.append(name)


def same(name: str, left, right) -> None:
    """
    機能: 配列の全値・形状を厳密比較する。
    引数: name(str)、left/right(object)は比較対象。
    返り値: None。
    """
    np.testing.assert_array_equal(left, right, err_msg=name)
    CHECKS.append(name)


def run(value: tuple, seconds: float, retry: bool, *, old: bool = False, jit: bool = False) -> dict:
    """
    機能: 人工入力を核へ渡し、保存約定からFIFOと数量会計を別に照合する。
    引数: value(tuple)、seconds(float)、retry/old/jit(bool)は人工設定。
    返り値: dictは検査対象配列。
    """
    ready, quote, market, paper = value
    method = prior.day129.simulate if old else day129b.simulate
    method = method if jit else method.py_func
    args = (ready["time_s"], ready["last"], quote["bid"], quote["ask"], quote["quote_valid"],
            prior.legacy.interface.make_feed(paper), ready["limit"], 10 if ready["symbol"] == "TOPIX" else 20,
            market, np.array([0., .5, 0., 0., .75, .5]), ready["atr"],
            np.full((len(ready["time_s"]), 15), np.nan), 1, .25, retry)
    result = dict(zip(prior.FIELDS, method(*args) if old else method(*args, seconds)))
    prior.legacy.audit(value, result)
    orders = result["orders"]
    check("次原行_"+str(len(CASES)), bool(np.all(orders[:, 0] > orders[:, 1])))
    if result["stats"][9] == 0.:
        same("全量保存_"+str(len(CASES)), orders[orders[:, 7] == 1, 4].sum(),
             orders[orders[:, 7] == 0, 4].sum())
        mult, rate = (1000., 418) if ready["symbol"] == "TOPIX" else (10., 110)
        cash = -np.sum(orders[:, 3]*orders[:, 4]*orders[:, 5])*mult
        fees = int(np.sum(orders[:, 4].astype(np.int64)*rate//10))
        same("現金と約定脚_"+str(len(CASES)), cash, result["trades"][:, 10].sum()*mult)
        result["fee_net"] = cash-fees
    CASES.append(dict(seconds=seconds, retry=retry, old=old, jit=jit, count=len(orders)))
    return result


def dense_fixture(quantity: int, seconds: int, *, retry: bool = False) -> tuple:
    """
    機能: 毎秒の人工で10秒時点から両市場が小逆行する列を作る。
    引数: quantity(int)、seconds(int)、retry(bool)は数量・持続時間・後の回復。
    返り値: tupleは価格・気配・二市場・紙上通知。
    """
    bids = np.full(400, 100.)
    bids[10:] = 98.5
    if retry:
        bids[45+seconds:] = 100.
    value = prior.legacy.fixture(bids.tolist(), [(0, 1, 350, 1)], quantity)
    ready, quote, market, paper = value
    times = np.arange(len(bids), dtype=float)
    ready["time_s"] = times
    ready["limit"] = 450.
    quote["time_s"] = times.copy()
    market[:, :2] = ready["last"][:, None]
    market[:, 2:4] = 4.
    market[:, 4:8] = .2
    market[:, 8] = times-.01
    market[:, 9] = times-30.
    market[:, 10] = times-30.01
    market[:, 11] = 1.
    first = 2 if quantity == 5 else 5
    paper["orders"] = np.vstack([paper["orders"][0],
        [250, 249, 0, -1, first, 100.5, 7, 0],
        [350, 349, 0, -1, quantity-first, 100.5, 9, 0]])
    return value


def main() -> None:
    """
    機能: 0秒互換、連続/解除/欠測/空白/新親、緊急出口、因果性を確認する。
    引数: なし。
    返り値: None。源指紋付きの純人工証拠JSONを保存する。
    """
    paths = [TASK/"day129b.py", TASK/"day129.py", TASK/"bbo_order_kernel126.py", Path(__file__),
             HERE/"check_day129.py", Path(prior.legacy.__file__), Path(prior.legacy.interface.__file__)]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for quantity in (5, 10):
        for before in (False, True):
            value = prior.fixture(quantity, before)
            for retry in (False, True):
                old, new = run(value, 0., retry, old=True), run(value, 0., retry)
                for field in prior.FIELDS:
                    same("0秒全配列互換_"+str((quantity, before, retry, field)), old[field], new[field])
        for seconds in (60, 120):
            for retry in (False, True):
                value = dense_fixture(quantity, seconds, retry=retry)
                result = run(value, seconds, retry)
                forced = result["orders"][result["orders"][:, 6] == 75]
                same("連続成立の次行_"+str((quantity, seconds, retry)), forced[:, :2],
                     [[11+seconds, 10+seconds]])
                count = 2 if retry else 1
                same("初回と再参加枚数_"+str((quantity, seconds, retry)),
                     result["orders"][result["orders"][:, 7] == 1, 4], [quantity]*count)
                events = result["execution_events"]
                same("75の連続観測秒数_"+str((quantity, seconds, retry)),
                     events[events[:, 1] == 15, 12], [seconds])
                mirrored = run(prior.legacy.mirror(value), seconds, retry)
                same("上下対称_"+str((quantity, seconds, retry)), result["orders"][:, 3], -mirrored["orders"][:, 3])
                same("上下時価_"+str((quantity, seconds, retry)), result["curve"][:, [0, 1, 4]],
                     mirrored["curve"][:, [0, 1, 4]])
                compiled = run(value, seconds, retry, jit=True)
                for field in prior.FIELDS:
                    same("JIT一致_"+str((quantity, seconds, retry, field)), result[field], compiled[field])
            # ----------------------------------------
            # 一度解除・不明・空白になれば、以前の経過秒を足さない。
            for reset in ("条件解除", "気配不明", "市場不明", "時計空白", "相手欠測"):
                value = dense_fixture(quantity, seconds)
                if reset == "条件解除":
                    value[2][40, 1] = 101.
                elif reset == "気配不明":
                    value[1]["quote_valid"][40] = False
                elif reset == "市場不明":
                    value[2][40, 11] = 0.
                elif reset == "時計空白":
                    value[0]["time_s"][40:] += 20.
                    value[1]["time_s"] = value[0]["time_s"].copy()
                    value[2][40:, 8:11] += 20.
                else:
                    value[2][40, 1] = np.nan
                result = run(value, seconds, False)
                decision = 40+seconds if reset == "時計空白" else 41+seconds
                same("連続時計リセット_"+str((quantity, seconds, reset)),
                     result["orders"][result["orders"][:, 6] == 75, :2], [[decision+1, decision]])
            value = dense_fixture(quantity, seconds)
            value[0]["time_s"][40:] += 14.
            value[1]["time_s"] = value[0]["time_s"].copy()
            value[2][40:, 8:11] += 14.
            result = run(value, seconds, False)
            same("15秒ちょうどは連続_"+str((quantity, seconds)),
                 result["orders"][result["orders"][:, 6] == 75, 1], [10+seconds-14])
            value = dense_fixture(quantity, seconds)
            value[0]["time_s"][30:41] = 30.
            value[1]["time_s"] = value[0]["time_s"].copy()
            value[2][30:41, 8] = 29.99
            result = run(value, seconds, False)
            same("同じ時計の複数行を秒数へ加算しない_"+str((quantity, seconds)),
                 result["orders"][result["orders"][:, 6] == 75, 1], [10+seconds])
            # 追加撤退の確認待ちでも従来の硬い損切りは待たない。
            value = dense_fixture(quantity, seconds)
            value[1]["bid"][40:] = 95.
            value[1]["ask"][40:] = 96.
            value[0]["last"][40:] = 95.5
            value[2][40:, :2] = 95.5
            result = run(value, seconds, False)
            same("硬い損切りは即時予約_"+str((quantity, seconds)), result["orders"][result["orders"][:, 6] == 32, :2],
                 [[41, 40]])
            # 紙上の通常返済と引けも確認秒を待たない。
            value = dense_fixture(quantity, seconds)
            value[3]["orders"] = value[3]["orders"][[0, -1]].copy()
            value[3]["orders"][-1, :2] = [30, 29]
            value[3]["orders"][-1, 4] = quantity
            result = run(value, seconds, False)
            same("通常返済は確認待ち不要_"+str((quantity, seconds)), result["orders"][-1, [0, 1, 6]], [31, 30, 9])
            value = dense_fixture(quantity, seconds)
            value[0]["limit"] = 30.
            result = run(value, seconds, False)
            same("引けは確認待ち不要_"+str((quantity, seconds)), result["orders"][-1, [0, 6]], [30, 93])
            # 再参加の新規時点で時計をゼロにし、前の逆行秒を継がない。
            value = dense_fixture(quantity, seconds, retry=True)
            renewed_failure = 56+seconds
            value[1]["bid"][renewed_failure:] = 98.5
            value[1]["ask"][renewed_failure:] = 99.5
            value[0]["last"][renewed_failure:] = 99.
            value[2][renewed_failure:, :2] = 99.
            result = run(value, seconds, True)
            forced = result["orders"][result["orders"][:, 6] == 75]
            same("新実親で持続時計リセット_"+str((quantity, seconds)), forced[:, 1],
                 [10+seconds, renewed_failure+seconds])
            same("再々参加なし_"+str((quantity, seconds)),
                 result["orders"][result["orders"][:, 7] == 1, 4], [quantity, quantity])
        # ----------------------------------------
        # 未来の変更と真の接頭切断が、確定済み出力を変えない。
        value = dense_fixture(quantity, 60, retry=True)
        original = run(value, 60., True)
        cut = 140
        changed = deepcopy(value)
        changed[0]["last"][cut:] += 20.
        changed[1]["bid"][cut:] += 20.
        changed[1]["ask"][cut:] += 20.
        changed[2][cut:, :2] += 20.
        altered = run(changed, 60., True)
        same("未来価格の接頭時価_"+str(quantity), original["curve"][:cut], altered["curve"][:cut])
        same("未来価格の接頭注文_"+str(quantity), original["orders"][original["orders"][:, 0] < cut],
             altered["orders"][altered["orders"][:, 0] < cut])
        short = list(deepcopy(value))
        for key in ("time_s", "seq", "last", "atr"):
            short[0][key] = short[0][key][:cut]
        for key in short[1]:
            short[1][key] = short[1][key][:cut]
        short[2] = short[2][:cut]
        short[3]["orders"] = short[3]["orders"][short[3]["orders"][:, 0] < cut]
        prefix = run(tuple(short), 60., True)
        same("真の接頭時価_"+str(quantity), prefix["curve"], original["curve"][:cut])
        same("真の接頭注文_"+str(quantity), prefix["orders"], original["orders"][original["orders"][:, 0] < cut])
    assert hashes == {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output = dict(passed=True, checks=CHECKS, cases=CASES, source_hashes=hashes,
                  financial_replays=0, original_market_reads=0, API=0)
    path = HERE/f"日中持続確認の純人工_{time.time_ns()}.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(path=str(path), checks=len(CHECKS), cases=len(CASES),
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()), ensure_ascii=True))


if __name__ == "__main__":
    main()
