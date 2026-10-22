"""二市場基準からの撤退と同影内再参加を、純人工だけで確認する。"""

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
ROOT = HERE.parents[2]
OLD = ROOT / "work/daynight128_20261020"
sys.dont_write_bytecode = True
numba.config.CACHE_DIR = str(HERE / "jit")
sys.path.insert(0, str(TASK))
import bbo_order_kernel126
import day129
sys.path.insert(0, str(OLD))
import day_core2
LEGACY = ROOT / "work/stability126_20261019/input_audit/bbo_artificial126"
sys.path.insert(0, str(LEGACY))
import check_bbo126 as legacy
numba.config.CACHE_DIR = str(HERE / "jit")
FIELDS = (*legacy.interface.FIELDS, "shadow_links")
CHECKS = []
CASES = []


def check(name: str, condition: bool) -> None:
    """
    機能: 独立期待値の検査名と成否を保持する。
    引数: name(str)は検査名、condition(bool)は期待値との一致。
    返り値: None。不一致で停止する。
    """
    assert condition, name
    CHECKS.append(name)


def same(name: str, left: object, right: object) -> None:
    """
    機能: 配列の形状と全値を厳密比較する。
    引数: name(str)、left/right(object)は検査名と比較配列。
    返り値: None。
    """
    np.testing.assert_array_equal(left, right, err_msg=name)
    CHECKS.append(name)


def execute(value: tuple, width: float, retry: bool, *, jit: bool = False,
            rule: int = 1, policy: np.ndarray | None = None) -> dict:
    """
    機能: 固定人工を新核へ渡し、FIFO・時価・数量・料金を別に確認する。
    引数: value(tuple)は人工入力、width(float)、retry/jit(bool)、rule(int)、policy(ndarray又はNone)。
    返り値: dictは完成した人工会計。
    """
    ready, quote, market, paper = value
    feed = legacy.interface.make_feed(paper)
    parameters = np.array([0., .5, 0., 0., .75, .5]) if policy is None else policy
    history = np.full((len(ready["time_s"]), 15), np.nan)
    method = day129.simulate if jit else day129.simulate.py_func
    result = dict(zip(FIELDS, method(ready["time_s"], ready["last"], quote["bid"],
        quote["ask"], quote["quote_valid"], feed, ready["limit"],
        10 if ready["symbol"] == "TOPIX" else 20, market, parameters,
        ready["atr"], history, rule, width, retry)))
    legacy.audit(value, result)
    orders = result["orders"]
    entry = orders[:, 7] == 1
    check("次原行_" + str(len(CASES)), bool(np.all(orders[:, 0] > orders[:, 1])))
    check("初回と再参加の片方向上限_" + str(len(CASES)),
          max(result["stats"][2], result["stats"][3]) <= (10 if ready["symbol"] == "TOPIX" else 20))
    for cid in np.unique(orders[:, 2]):
        own = orders[orders[:, 2] == cid]
        check("実親一新規_" + str((len(CASES), cid)), (own[:, 7] == 1).sum() == 1)
    if result["stats"][9] == 0:
        same("全数量保存_" + str(len(CASES)), orders[entry, 4].sum(), orders[~entry, 4].sum())
        mult, rate = (1000., 418) if ready["symbol"] == "TOPIX" else (10., 110)
        cash = -np.sum(orders[:, 3]*orders[:, 4]*orders[:, 5])*mult
        fees = int(np.sum(orders[:, 4].astype(np.int64)*rate//10))
        same("現金と返済脚一致_" + str(len(CASES)), cash, result["trades"][:, 10].sum()*mult)
        result["fee_net"] = float(cash-fees)
        result["fees"] = fees
    CASES.append(dict(width=width, retry=retry, jit=jit, orders=len(orders), parents=len(result["cycles"])))
    return result


def fixture(quantity: int = 5, partial_before: bool = False) -> tuple:
    """
    機能: 入口後に二市場が逆行し、撤退後に再順行する人工列を作る。
    引数: quantity(int)は5又は10、partial_before(bool)は撤退前の影部分返済の有無。
    返り値: tupleはready、気配、二市場、紙上通知。
    """
    bids = [100, 100, 100, 98, 97, 97, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108]
    value = legacy.fixture(bids, [(0, 1, 12, 1)], quantity)
    ready, quote, market, paper = value
    times = ready["time_s"]
    market[:, 0] = ready["last"]
    market[:, 1] = ready["last"]
    market[:, 2:4] = 4.
    market[:, 4:8] = .2
    market[:, 8] = times-1.
    market[:, 9] = times-31.
    market[:, 10] = times-32.
    market[:, 11] = 1.
    new = paper["orders"][0]
    if partial_before:
        first, second = (2, 1) if quantity == 5 else (5, 2)
        paper["orders"] = np.array([new, [3, 2, 0, -1, first, 98.5, 7, 0],
            [8, 7, 0, -1, second, 101.5, 30, 0],
            [12, 11, 0, -1, quantity-first-second, 105.5, 9, 0]], dtype=float)
    else:
        first = 2 if quantity == 5 else 5
        paper["orders"] = np.array([new, [8, 7, 0, -1, first, 101.5, 7, 0],
            [12, 11, 0, -1, quantity-first, 105.5, 9, 0]], dtype=float)
    return value


def main() -> None:
    """
    機能: 旧互換・上下・未知・再参加数量・次行・未来接頭・JITを確認する。
    引数: なし。
    返り値: None。実市場再生なしの証拠を実装指紋付きで保存する。
    """
    source_paths = [TASK/"day129.py", TASK/"bbo_order_kernel126.py", OLD/"day_core2.py",
                    Path(__file__), LEGACY/"check_bbo126.py"]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    configs = legacy.catalog()
    for quantity in (5, 10):
        for label, value in legacy.mechanism_cases(quantity).items():
            ready, quote, market, paper = value
            history = np.full((len(ready["time_s"]), 15), np.nan)
            for config in configs:
                parameters = np.r_[legacy.interface.policy_parameters(config), [.75, .5]]
                original = day_core2.simulate.py_func(ready["time_s"], ready["last"], quote["bid"],
                    quote["ask"], quote["quote_valid"], legacy.interface.make_feed(paper), ready["limit"],
                    10 if quantity == 5 else 20, market, parameters, ready["atr"], history, 1)
                revised = execute(value, 0., False, policy=parameters)
                for field, expected in zip(legacy.interface.FIELDS, original):
                    same("D17旧互換_" + str((quantity, label, config["id"], field)), revised[field], expected)
        for before in (False, True):
            value = fixture(quantity, before)
            for width in (.25, .5):
                without = execute(value, width, False)
                with_retry = execute(value, width, True)
                same("撤退だけは一新規_" + str((quantity, before, width)),
                     without["orders"][without["orders"][:, 7] == 1, 4], [quantity])
                same("再参加は元数量の二新規_" + str((quantity, before, width)),
                     with_retry["orders"][with_retry["orders"][:, 7] == 1, 4], [quantity, quantity])
                same("影親は同一・実親は分離_" + str((quantity, before, width)),
                     with_retry["shadow_links"][:, :3], [[0, 0, 0], [1, 0, 1]])
                expected = ([quantity, 2, 3] if quantity == 5 else [quantity, 4, 6]) if before else (
                    [quantity, 2, 3] if quantity == 5 else [quantity, 5, 5])
                same("再参加影残数による累計整数返済_" + str((quantity, before, width)),
                     with_retry["orders"][with_retry["orders"][:, 2] == 1, 4], expected)
                if before:
                    same("影部分返済と同時撤退の次二行順_" + str((quantity, width)),
                         without["orders"][:, 0], [2, 4, 5])
                else:
                    same("新撤退判断3から約定4_" + str((quantity, width)), without["orders"][:, 0], [2, 4])
                mirrored = execute(legacy.mirror(value), width, True)
                same("上下鏡像時価_" + str((quantity, before, width)),
                     with_retry["curve"][:, [0, 1, 4]], mirrored["curve"][:, [0, 1, 4]])
                same("上下鏡像方向_" + str((quantity, before, width)),
                     with_retry["orders"][:, 3], -mirrored["orders"][:, 3])
                compiled = execute(value, width, True, jit=True)
                for field in FIELDS:
                    same("JIT一致_" + str((quantity, before, width, field)), compiled[field], with_retry[field])
        # ----------------------------------------
        # 無効・不鮮明な相手情報と、片市場だけの逆行を追加撤退に使わない。
        for label in ("相手欠測", "片方順行", "古い相手時計"):
            value = fixture(quantity)
            if label == "相手欠測":
                value[2][:, 1] = np.nan
            elif label == "片方順行":
                value[2][:, 1] = 110.
            else:
                value[2][:, 8] = value[2][2, 8]
            result = execute(value, .25, True)
            check(label+"で75撤退なし_"+str(quantity), not np.any(result["orders"][:, 6] == 75))
        value = fixture(quantity)
        value[2][:, 6] = .04
        result = execute(value, .25, True)
        same("再参加の片方支持不足_"+str(quantity), result["orders"][result["orders"][:, 7] == 1, 4], [quantity])
        value = fixture(quantity)
        value[2][8:10, :2] = 98.
        result = execute(value, .25, True)
        same("再参加後の再撤退でも第三参加禁止_"+str(quantity),
             result["orders"][result["orders"][:, 7] == 1, 4], [quantity, quantity])
        check("再参加後も実親別に撤退_"+str(quantity), np.sum(result["orders"][:, 6] == 75) == 2)
        # ----------------------------------------
        # 影終了、気配欠落、次の別親、未来改変を対照にする。
        value = fixture(quantity)
        value[3]["orders"] = value[3]["orders"][[0, -1]].copy()
        value[3]["orders"][-1, 0:2] = [6, 5]
        value[3]["orders"][-1, 4] = quantity
        result = execute(value, .25, True)
        same("影終了後の再参加禁止_"+str(quantity), result["orders"][result["orders"][:, 7] == 1, 4], [quantity])
        value = fixture(quantity)
        value[1]["quote_valid"][7] = False
        result = execute(value, .25, True)
        same("再参加も正常次行まで待つ_"+str(quantity), result["orders"][result["orders"][:, 7] == 1, 0], [2, 8])
        # 正常気配が戻る前に元影が終わったなら、再参加予約も取消す。
        value = fixture(quantity)
        value[1]["quote_valid"][7:10] = False
        value[3]["orders"] = value[3]["orders"][[0, -1]].copy()
        value[3]["orders"][-1, :2] = [8, 7]
        value[3]["orders"][-1, 4] = quantity
        result = execute(value, .25, True)
        same("再参加予約中の影終了で取消_"+str(quantity),
             result["orders"][result["orders"][:, 7] == 1, 4], [quantity])
        # Qの幅超過では、反発条件が満たされてもその行で予約しない。
        value = fixture(quantity)
        value[1]["ask"][6:] = value[1]["bid"][6:]+3.
        result = execute(value, .25, True)
        same("再参加にも判断行のQ予算_"+str(quantity),
             result["orders"][result["orders"][:, 7] == 1, 4], [quantity])
        # 後から来る元影親の番号と再参加親番号を衝突させない。
        first = fixture(quantity)
        value = legacy.fixture(list(first[1]["bid"])+[108., 108., 108., 108.],
                               [(0, 1, 12, 1), (1, 14, 18, -1)], quantity)
        value[2][:16] = first[2]
        value[2][16:, 0] = value[0]["last"][16:]
        value[2][16:, 1] = value[0]["last"][16:]
        value[2][16:, 2:4] = 4.
        value[2][16:, 4:8] = 0.
        value[2][16:, 8] = value[0]["time_s"][16:]-1.
        value[2][16:, 9:11] = value[0]["time_s"][16:, None]-31.
        value[2][16:, 11] = 1.
        value[3]["orders"] = np.vstack([first[3]["orders"], value[3]["orders"][-2:]])
        result = execute(value, .25, True)
        same("次の元親と再参加親のID独立_"+str(quantity),
             result["shadow_links"][:, :3], [[0, 0, 0], [1, 0, 1], [2, 1, 0]])
        same("後続影も全返済_"+str(quantity), result["stats"][9], 0.)
        changed = deepcopy(value)
        changed[3]["orders"][changed[3]["orders"][:, 2] == 1, 2] = 37
        changed[3]["cycles"][changed[3]["cycles"][:, 0] == 1, 0] = 37
        altered = execute(changed, .25, True)
        same("未来影IDを変えても過去実注文同値_"+str(quantity),
             result["orders"][result["orders"][:, 0] < 14],
             altered["orders"][altered["orders"][:, 0] < 14])
        same("未来影IDを変えても過去実親同値_"+str(quantity),
             result["shadow_links"][:2], altered["shadow_links"][:2])
        # 返済時計以前の相手資料では、撤退後のアンカーを作らない。
        value = fixture(quantity)
        closed_at = value[0]["time_s"][4]
        value[2][5:8, 8] = closed_at-1.
        value[2][8:, 9:11] = closed_at-2.
        result = execute(value, .25, True)
        anchors = result["execution_events"][result["execution_events"][:, 1] == 16]
        same("返済後相手を待ってアンカー化_"+str(quantity), anchors[:, 0], [8])
        same("返済前を含む30秒窓で再参加なし_"+str(quantity),
             result["orders"][result["orders"][:, 7] == 1, 4], [quantity])
        value = fixture(quantity)
        original = execute(value, .25, True)
        changed = deepcopy(value)
        cut = 8
        for key in ("last",):
            changed[0][key][cut:] += 50.
        for key in ("bid", "ask"):
            changed[1][key][cut:] += 50.
        changed[2][cut:, :2] -= 50.
        altered = execute(changed, .25, True)
        same("未来改変の時価接頭_"+str(quantity), original["curve"][:cut], altered["curve"][:cut])
        same("未来改変の注文接頭_"+str(quantity), original["orders"][original["orders"][:, 0] < cut],
             altered["orders"][altered["orders"][:, 0] < cut])
        short = list(deepcopy(value))
        for key in ("time_s", "seq", "last", "atr"):
            short[0][key] = short[0][key][:cut]
        for key in short[1]:
            short[1][key] = short[1][key][:cut]
        short[2] = short[2][:cut]
        short[3]["orders"] = short[3]["orders"][short[3]["orders"][:, 0] < cut]
        prefix = execute(tuple(short), .25, True)
        same("真の接頭切断_"+str(quantity), prefix["curve"], original["curve"][:cut])
        same("真の接頭注文_"+str(quantity), prefix["orders"], original["orders"][original["orders"][:, 0] < cut])
    assert hashes == {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    result = dict(passed=True, checks=CHECKS, cases=CASES, source_hashes=hashes,
                  financial_replays=0, original_market_reads=0, API=0,
                  note="作成者の純人工確認。実市場の有効性とは別。独立第三者監査を別途受ける。")
    target = HERE/f"日中撤退再参加の純人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, checks=len(CHECKS), cases=len(CASES), path=str(target),
                         sha256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=True))


if __name__ == "__main__":
    main()
