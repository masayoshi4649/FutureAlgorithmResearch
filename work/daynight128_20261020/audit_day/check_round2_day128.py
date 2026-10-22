"""第二巡の日中尺度と二市場二十分の失敗確認を純人工で監査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

import check_day128 as base

sys.path.insert(0, str(base.TASK))
import adapter2
import day_core2


CHECKS = []
CASES = []


def check(name: str, condition: bool) -> None:
    """
    機能: 独立期待値の合否を記録する。
    引数: name(str)、condition(bool)は検査名と判定。
    返り値: None。不合格では停止する。
    """
    assert condition, name
    CHECKS.append(name)


def same(name: str, left: object, right: object) -> None:
    """
    機能: 配列を厳密比較し、合格を記録する。
    引数: name(str)、left/right(object)は比較名と値。
    返り値: None。
    """
    np.testing.assert_array_equal(left, right, err_msg=name)
    CHECKS.append(name)


def run(value: tuple, config: dict, rule: int, risk_floor: float = .5,
        protect_start: float = .5, atr: np.ndarray | None = None,
        history: np.ndarray | None = None, jit: bool = False) -> dict:
    """
    機能: 第二巡核へ固定人工だけを渡し、FIFOと全行時価を外部再構築する。
    引数: value(tuple)、config(dict)、rule(int)、risk_floor/protect_start(float)、
        atr/history(ndarray又はNone)、jit(bool)は人工条件。
    返り値: dictは新数値核の実注文・返済・時価・状態。
    """
    ready, quotes, market, paper = value
    n = len(ready["time_s"])
    atr = ready["atr"].copy() if atr is None else atr
    history = np.full((n, 15), np.nan) if history is None else history
    policy = np.r_[base.legacy.interface.policy_parameters(config), [risk_floor, protect_start]]
    function = day_core2.simulate if jit else day_core2.simulate.py_func
    actual = function(ready["time_s"], ready["last"], quotes["bid"], quotes["ask"],
                      quotes["quote_valid"], base.legacy.interface.make_feed(paper),
                      float(ready["limit"]), 10 if ready["symbol"] == "TOPIX" else 20,
                      market, policy, atr, history, rule)
    result = dict(zip(base.legacy.interface.FIELDS, actual))
    base.legacy.audit(value, result)
    CASES.append(dict(rule=rule, risk_floor=risk_floor, protect_start=protect_start,
                      quantity=5 if ready["symbol"] == "TOPIX" else 10,
                      jit=jit, orders=len(result["orders"])))
    return result


def mirrors_and_future(value: tuple, config: dict, rule: int, risk_floor: float,
                       start: float, atr: np.ndarray, history: np.ndarray, label: str) -> dict:
    """
    機能: 方向鏡像と未来変更及び真の末尾切断に対して過去会計を照合する。
    引数: value(tuple)、config(dict)、rule(int)、risk_floor/start(float)、atr/history(ndarray)、label(str)。
    返り値: dictは元の人工結果。
    """
    result = run(value, config, rule, risk_floor, start, atr, history)
    reflected = run(base.legacy.mirror(value), config, rule, risk_floor, start, atr, base.reflect_history(history))
    same(label + "上下反射の損益", result["curve"][:, [0, 1, 4]], reflected["curve"][:, [0, 1, 4]])
    same(label + "上下反射の時刻", result["orders"][:, :3], reflected["orders"][:, :3])
    same(label + "上下反射の方向", result["orders"][:, 3], -reflected["orders"][:, 3])
    cut = 5
    altered = deepcopy(value)
    altered[0]["last"][cut:] += 100.
    altered[1]["bid"][cut:] += 100.
    altered[1]["ask"][cut:] += 100.
    new_atr = atr.copy(); new_atr[cut:] = .01
    new_history = history.copy(); new_history[cut:] = -100.
    changed = run(altered, config, rule, risk_floor, start, new_atr, new_history)
    same(label + "未来改変で過去時価不変", result["curve"][:cut], changed["curve"][:cut])
    same(label + "未来改変で過去注文不変", result["orders"][result["orders"][:, 0] < cut],
         changed["orders"][changed["orders"][:, 0] < cut])
    short = list(deepcopy(value))
    for field in ("seq", "time_s", "last", "atr"):
        short[0][field] = short[0][field][:cut]
    for field in short[1]:
        short[1][field] = short[1][field][:cut]
    short[2] = short[2][:cut]
    short[3]["orders"] = short[3]["orders"][short[3]["orders"][:, 0] < cut]
    prefix = run(tuple(short), config, rule, risk_floor, start, atr[:cut], history[:cut])
    same(label + "末尾切断で過去時価不変", result["curve"][:cut], prefix["curve"])
    same(label + "末尾切断で過去注文不変", result["orders"][result["orders"][:, 0] < cut], prefix["orders"])
    return result


def main() -> None:
    """
    機能: 第一巡互換、縮小三下限、二市場二十分の保護、接続と会計を確認する。
    引数: なし。
    返り値: None。最終源指紋を含む純人工証跡を新規保存する。
    """
    paths = [base.TASK / name for name in ("day_core2.py", "adapter2.py", "bbo_order_kernel126.py",
                                          "第二巡条件.json", "day_core128.py", "adapter128.py")]
    paths += [Path(__file__), base.HERE / "check_day128.py",
              base.OLD / "input_audit/bbo_artificial126/check_bbo126.py"]
    sources = {p.relative_to(base.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    configs = {c["id"]: c for c in base.legacy.catalog()}
    # ----------------------------------------
    # 出口なしと下限0.5の尺度縮小は、第一巡の全設定と同一に動く。
    for quantity in (5, 10):
        for case, value in base.legacy.mechanism_cases(quantity).items():
            n = len(value[0]["time_s"])
            atr = np.linspace(6., .25, n)
            history = np.full((n, 15), np.nan)
            for config in configs.values():
                for rule in (0, 1):
                    first = base.run(value, config, rule, atr, history)
                    second = run(value, config, rule, .5, .5, atr, history)
                    for field in base.legacy.interface.FIELDS:
                        same("第一巡同値_" + str((quantity, case, config["id"], rule, field)), first[field], second[field])
    config = configs["E01"]
    for quantity in (5, 10):
        # ----------------------------------------
        # 現尺度が初期4幅から十分小さくなった時、指定した下限でだけ予約する。
        value = base.legacy.fixture([100, 100, 100, 99.5, 98.5, 97.5, 97, 100, 100], [(0, 1, 7, 1)], quantity)
        atr = np.full(9, 4.); atr[3] = .1; atr[4:] = np.nan
        history = np.full((9, 15), np.nan)
        for floor, expected_source in ((.25, 3.), (.5, 4.), (.75, 5.)):
            result = mirrors_and_future(value, config, 1, floor, .5, atr, history,
                                        "幅下限_" + str((quantity, floor)))
            same("下限別予約と次約定_" + str((quantity, floor)), result["orders"][-1, :2],
                 [expected_source + 1., expected_source])
            reservation = result["execution_events"][result["execution_events"][:, 1] == 9.][0]
            check("実境界記録_" + str((quantity, floor)), reservation[7] == -4. * quantity * floor)
        # ----------------------------------------
        # 二十分支持が残る時は、第一巡で床を上げた平均割れ・五分逆行だけでは退出しない。
        value = base.legacy.fixture([100, 100, 100, 103, 101.5, 101, 100, 100, 100], [(0, 1, 7, 1)], quantity)
        atr = np.full(9, 4.)
        history = np.ones((9, 15)); history[:, 1] = 104.; history[:, 10] = -1.
        for own, peer in ((1., 1.), (-1., 1.), (1., -1.), (0., -1.), (-1., 0.)):
            h = history.copy(); h[:, 7] = own; h[:, 11] = peer
            result = run(value, config, 2, .5, .5, atr, h)
            check("両二十分反対以外は床なし_" + str((quantity, own, peer)), result["orders"][-1, 0] == 8.)
        history[:, 7] = -1.; history[:, 11] = -1.
        result = mirrors_and_future(value, config, 2, .5, .5, atr, history, "両二十分逆_" + str(quantity))
        same("両二十分反対で半益床予約", result["orders"][-1, :2], [5., 4.])
        check("半益床の値段で実約定を捏造しない", result["stats"][0] == 0.)
        for missing in (1, 7, 10, 11):
            unknown = history.copy(); unknown[:, missing] = np.nan
            result = run(value, config, 2, .5, .5, atr, unknown)
            check("未知履歴では床未起動_" + str((quantity, missing)), result["orders"][-1, 0] == 8.)
        for start in (.25, .5, .75):
            peak_price = 101. + start * 4.
            custom = base.legacy.fixture([100, 100, 100, peak_price, 101., 100., 100., 100., 100.],
                                         [(0, 1, 7, 1)], quantity)
            result = run(custom, config, 2, .5, start, atr, history)
            check("起動閾値に丁度到達した半益床_" + str((quantity, start)),
                  result["orders"][-1, 0] == 5. and result["orders"][-1, 6] == 70.)
            below = deepcopy(custom)
            below[1]["bid"][3] -= .01; below[1]["ask"][3] -= .01; below[0]["last"][3] -= .01
            inactive = run(below, config, 2, .5, start, atr, history)
            check("起動閾値未満は保護なし_" + str((quantity, start)), inactive["orders"][-1, 0] == 8.)
        delayed = deepcopy(value); delayed[1]["quote_valid"][5:7] = False
        result = run(delayed, config, 2, .5, .5, atr, history)
        check("利益床の正常気配待ち", result["orders"][-1, 0] == 7. and result["stats"][0] == -quantity)
        # ----------------------------------------
        # 部分利確と残数量の合計を床の会計へ使う。
        partial = base.legacy.fixture([100, 100, 100, 103, 103, 102, 100, 100, 100, 100, 100],
                                     [(0, 1, 9, 1)], quantity)
        part = quantity // 2
        partial[3]["orders"][1, 4] = quantity - part
        partial[3]["orders"] = np.vstack([partial[3]["orders"], [3, 2, 0, -1, part, 103.5, 7, 0]])
        partial[3]["orders"] = partial[3]["orders"][np.argsort(partial[3]["orders"][:, 0])]
        h = np.ones((11, 15)); h[:, 1] = 110.; h[:, 7] = -1.; h[:, 11] = -1.
        result = run(partial, config, 3, .5, .5, history=h)
        same("第二巡部分利確と床返済の数量", result["orders"][:, 4], [quantity, part, quantity - part])
        same("第二巡部分利確と床返済の行", result["orders"][:, 0], [2., 4., 7.])
        check("第二巡部分利確の二重計上なし", result["stats"][0] == 2. * part - (quantity - part))
        for rule in (0, 1, 2, 3):
            pure = run(value, config, rule, .5, .5, atr, history)
            compiled = run(value, config, rule, .5, .5, atr, history, jit=True)
            for field in base.legacy.interface.FIELDS:
                same("第二巡JIT一致_" + str((quantity, rule, field)), pure[field], compiled[field])
        specs = json.loads((base.TASK / "第二巡条件.json").read_text(encoding="utf-8"))
        for spec in [c for c in specs if c["engine"] == "day"]:
            ready, quotes, market, paper = value
            ready["start"] = 0.; ready["session"] = "人工_Day"
            actual = adapter2.play_day(spec, ready, quotes, market, history, base.legacy.interface.make_feed(paper))
            direct = run(value, config, spec["exit_rule"], spec["risk_floor"], spec["protect_start"], atr, history)
            for field in base.legacy.interface.FIELDS:
                same("第二巡日中全条件の接続_" + str((quantity, spec["id"], field)), actual[field], direct[field])
    check("全ソース指紋不変", all(hashlib.sha256((base.ROOT / p).read_bytes()).hexdigest() == sha for p, sha in sources.items()))
    target = base.HERE / ("第二巡日中の旧互換と二十分失敗の独立人工_" + str(time.time_ns()) + ".json")
    target.write_text(json.dumps(dict(
        passed=True, checks=CHECKS, count=len(CHECKS), cases=CASES,
        sources=sources, accounting_checks=len(base.legacy.CHECKS),
        market_reads=0, financial_replays=0, API=0,
    ), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, path=target.relative_to(base.ROOT).as_posix(),
                          checks=len(CHECKS), artificial_cases=len(CASES)), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        target = base.HERE / ("第二巡日中人工停止_" + str(time.time_ns()) + ".json")
        target.write_text(json.dumps(dict(passed=False, error=repr(error), checks=CHECKS, cases=CASES),
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
