"""日中核の旧互換と新しい出口を実市場なしで独立に反証する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
OLD = ROOT / "work/stability126_20261019"
sys.dont_write_bytecode = True
sys.path.insert(0, str(OLD / "input_audit/bbo_artificial126"))
import check_bbo126 as legacy

sys.path.insert(0, str(TASK))
import day_core128 as core

numba.config.CACHE_DIR = str(HERE / "jit")
CHECKS = []
CASES = []


def check(name: str, condition: bool) -> None:
    """
    機能: 独立期待値の合否を記録する。
    引数: name(str)は検査名、condition(bool)は判定値。
    返り値: None。不合格では停止する。
    """
    assert condition, name
    CHECKS.append(name)


def same(name: str, left: object, right: object) -> None:
    """
    機能: 配列の値と形状を厳密照合する。
    引数: name(str)、left/right(object)は名称と比較対象。
    返り値: None。不合格では停止する。
    """
    np.testing.assert_array_equal(left, right, err_msg=name)
    CHECKS.append(name)


def run(value: tuple, config: dict, rule: int, atr: np.ndarray | None = None,
        history: np.ndarray | None = None, jit: bool = False) -> dict:
    """
    機能: 合成入力だけを日中核へ渡し、独立FIFO会計を検査する。
    引数: value(tuple)、config(dict)、rule(int)、atr/history(ndarray又はNone)、jit(bool)。
    返り値: dictは純人工の注文・親会計・全行時価。
    """
    ready, quotes, market, paper = value
    n = len(ready["time_s"])
    atr = ready["atr"].copy() if atr is None else atr
    history = np.full((n, 15), np.nan) if history is None else history
    parameters = legacy.interface.policy_parameters(config)
    feed = legacy.interface.make_feed(paper)
    function = core.simulate if jit else core.simulate.py_func
    result = dict(zip(legacy.interface.FIELDS, function(
        ready["time_s"], ready["last"], quotes["bid"], quotes["ask"], quotes["quote_valid"],
        feed, float(ready["limit"]), 10 if ready["symbol"] == "TOPIX" else 20,
        market, parameters, atr, history, rule,
    )))
    legacy.audit(value, result)
    CASES.append(dict(rule=rule, quantity=5 if ready["symbol"] == "TOPIX" else 10,
                      jit=jit, orders=len(result["orders"]), unclosed=float(result["stats"][9])))
    return result


def reflect_history(history: np.ndarray) -> np.ndarray:
    """
    機能: 人工価格を200中心で上下反射した場合の履歴を作る。
    引数: history(ndarray)は十五列の人工履歴。
    返り値: ndarrayは価格列と符号付き差分だけを反射した別配列。
    """
    result = history.copy()
    for column in (0, 1, 3, 4, 8):
        result[:, column] = 200. - result[:, column]
    for column in (6, 7, 10, 11, 13):
        result[:, column] *= -1.
    return result


def pair_checks(value: tuple, config: dict, rule: int, atr: np.ndarray,
                history: np.ndarray, label: str) -> dict:
    """
    機能: 売買反射、未来価格変更、真の末尾切断を同じ人工で確認する。
    引数: value(tuple)、config(dict)、rule(int)、atr/history(ndarray)、label(str)。
    返り値: dictは元入力の結果。
    """
    result = run(value, config, rule, atr, history)
    reflected = run(legacy.mirror(value), config, rule, atr, reflect_history(history))
    same(label + "上下鏡像の全行損益", result["curve"][:, [0, 1, 4]], reflected["curve"][:, [0, 1, 4]])
    same(label + "上下鏡像の注文元行", result["orders"][:, :3], reflected["orders"][:, :3])
    same(label + "上下鏡像の方向", result["orders"][:, 3], -reflected["orders"][:, 3])
    cut = 5
    changed = deepcopy(value)
    changed[0]["last"][cut:] += 500.
    changed[1]["bid"][cut:] += 50.
    changed[1]["ask"][cut:] += 50.
    changed_atr, changed_history = atr.copy(), history.copy()
    changed_atr[cut:] = .01
    changed_history[cut:] = -1000.
    altered = run(changed, config, rule, changed_atr, changed_history)
    same(label + "未来改変の過去曲線不変", result["curve"][:cut], altered["curve"][:cut])
    same(label + "未来改変の過去注文不変", result["orders"][result["orders"][:, 0] < cut],
         altered["orders"][altered["orders"][:, 0] < cut])
    short = list(deepcopy(value))
    for field in ("seq", "time_s", "last", "atr"):
        short[0][field] = short[0][field][:cut]
    for field in short[1]:
        short[1][field] = short[1][field][:cut]
    short[2] = short[2][:cut]
    short[3]["orders"] = short[3]["orders"][short[3]["orders"][:, 0] < cut]
    prefix = run(tuple(short), config, rule, atr[:cut], history[:cut])
    same(label + "真の末尾切断の過去曲線不変", result["curve"][:cut], prefix["curve"])
    same(label + "真の末尾切断の過去注文不変", result["orders"][result["orders"][:, 0] < cut], prefix["orders"])
    return result


def main() -> None:
    """
    機能: 原版全設定との同値と二出口の反例を、ソース指紋に拘束して検査する。
    引数: なし。
    返り値: None。純人工監査JSONだけを新規保存する。
    """
    sources = [
        TASK / "day_core128.py", TASK / "bbo_order_kernel126.py", TASK / "catalog128.py",
        OLD / "engine/bbo_next/core126.py", OLD / "engine/bbo_next/bbo_order_kernel126.py",
        OLD / "engine/bbo_next/policy_bbo126.py", OLD / "engine/policy126.py",
        OLD / "input_audit/bbo_artificial126/check_bbo126.py", Path(__file__),
    ]
    fingerprint = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    configs = {config["id"]: config for config in legacy.catalog()}
    # ----------------------------------------
    # 追加出口を切った場合、原版16設定・三機構・両数量・上下で全九配列が一致する。
    for quantity in (5, 10):
        for case, value in legacy.mechanism_cases(quantity).items():
            for config in configs.values():
                for mirrored in (False, True):
                    actual = legacy.mirror(value) if mirrored else value
                    original = legacy.interface.play(config, *actual[:3], actual[3], use_python=True)
                    updated = run(actual, config, 0)
                    for field in legacy.interface.FIELDS:
                        same("旧互換" + str((quantity, case, config["id"], mirrored, field)), original[field], updated[field])
    base_config = configs["E01"]
    for quantity in (5, 10):
        # ----------------------------------------
        # 初回4幅から2幅へ縮小した後、2.5幅逆行で予約し次行の98で清算する。
        value = legacy.fixture([100, 100, 100, 98.5, 98, 100, 100, 100, 100], [(0, 1, 7, 1)], quantity)
        atr = np.full(9, 4.); atr[3:] = 2.
        history = np.full((9, 15), np.nan)
        result = pair_checks(value, base_config, 1, atr, history, "収縮" + str(quantity))
        same("縮小予算の判断行と次約定行" + str(quantity), result["orders"][-1, :2], [4., 3.])
        check("縮小予算の現実価格清算" + str(quantity), result["orders"][-1, 5] == 98. and result["stats"][0] == -3. * quantity)
        events = result["execution_events"]
        reservation = events[(events[:, 1] == 9.) & (events[:, 13] == 32.)][0]
        check("縮小予算の記録境界" + str(quantity), reservation[7] == -2. * quantity)
        for special in (.01, 40., np.nan, -1.):
            adjusted = atr.copy(); adjusted[3:] = special
            tested = run(value, base_config, 1, adjusted, history)
            check("ATR下限又は未知の保持" + str((quantity, special)),
                  tested["orders"][-1, 0] == (4. if special == .01 else 8.))
        delayed = deepcopy(value); delayed[1]["quote_valid"][4:6] = False
        waited = run(delayed, base_config, 1, atr, history)
        check("縮小停止は正常気配待ち" + str(quantity), waited["orders"][-1, 0] == 6.)
        # ----------------------------------------
        # 0.5Rに到達しても自己平均割れと相手5分反対の両条件がない限り保護しない。
        value = legacy.fixture([100, 100, 100, 103, 101.5, 101, 100, 100, 100], [(0, 1, 7, 1)], quantity)
        atr = np.full(9, 4.)
        history = np.full((9, 15), np.nan); history[:, 1] = 104.; history[:, 10] = -1.
        result = pair_checks(value, base_config, 2, atr, history, "中期失敗" + str(quantity))
        same("利益床の判断行と次約定行" + str(quantity), result["orders"][-1, :2], [5., 4.])
        check("利益床の価格を保証しない" + str(quantity), result["stats"][0] == 0.)
        for missing in ("自己平均", "相手差", "相手順行", "自己順行"):
            altered = history.copy()
            if missing == "自己平均": altered[:, 1] = np.nan
            elif missing == "相手差": altered[:, 10] = np.nan
            elif missing == "相手順行": altered[:, 10] = 1.
            else: altered[:, 1] = 90.
            tested = run(value, base_config, 2, atr, altered)
            check("中期失敗は両条件必須" + str((quantity, missing)), tested["orders"][-1, 0] == 8.)
        below = deepcopy(value); below[1]["bid"][3] = 102.99; below[1]["ask"][3] = 103.99
        below[0]["last"][3] = 103.49
        tested = run(below, base_config, 2, atr, history)
        check("0.5R未満では未起動" + str(quantity), tested["orders"][-1, 0] == 8.)
        delayed = deepcopy(value); delayed[1]["quote_valid"][5:7] = False
        waited = run(delayed, base_config, 2, atr, history)
        check("利益床の正常気配待ちと損失" + str(quantity),
              waited["orders"][-1, 0] == 7. and waited["stats"][0] == -quantity)
        for rule in (0, 1, 2):
            python_result = run(value, base_config, rule, atr, history)
            compiled = run(value, base_config, rule, atr, history, jit=True)
            for field in legacy.interface.FIELDS:
                same("JITと純Pythonの全配列" + str((quantity, rule, field)), python_result[field], compiled[field])
    check("監査中のソース変更なし", all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha for name, sha in fingerprint.items()))
    result = dict(passed=True, checks=CHECKS, count=len(CHECKS), cases=CASES,
                  accounting_checks=len(legacy.CHECKS), sources=fingerprint,
                  market_reads=0, financial_replays=0, API=0, real_orders=0)
    target = HERE / ("日中核の独立純人工_" + str(time.time_ns()) + ".json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, path=target.relative_to(ROOT).as_posix(), checks=len(CHECKS), cases=len(CASES)), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        target = HERE / ("日中核の独立純人工停止_" + str(time.time_ns()) + ".json")
        target.write_text(json.dumps(dict(passed=False, error=repr(error), checks=CHECKS, cases=CASES,
                                         market_reads=0, financial_replays=0), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
