"""実市場を読まず、固定の人工注文と外部算術で原版と三部品を調べる。"""

from __future__ import annotations

import importlib
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine"
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ENGINE))
import legacy126

legacy126.CACHE = str(HERE / "jit")
OPENED = []


def read_boundary(event, args):
    """
    機能: 人工監査中の市場原本・実市場配列と金融結果の読取を拒否する。
    引数: event(str)、args(tuple)は標準監査イベント。
    返り値: None。許可した源と所有監査書込以外の本文読取は例外。
    """
    if event != "open" or not isinstance(args[0], (str, bytes, Path)):
        return
    path = Path(os.fsdecode(args[0])).resolve()
    if not path.is_relative_to(ROOT):
        return
    mode = str(args[1] or "")
    flags = int(args[2] or 0)
    if any(v in mode for v in ("w", "a", "x", "+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
        assert path.is_relative_to(HERE), ("監査所有域外の書込", str(path))
        return
    if path.suffix in (".py", ".pyc", ".nbi", ".nbc", ".pyd", ".dll"):
        return
    allowed = {ENGINE / "legacy_root" / relative for relative in legacy126.SMALL_FIXED}
    assert path in allowed, ("人工監査による本文読取拒否", str(path))
    OPENED.append(str(path.relative_to(ROOT)))


def artificial(prices, quantity=5, side=1, atr=2.0, partial=3, terminal=None, step=30.0):
    """
    機能: 明示された価格と新規・返済行だけから人工の旧署名引数を作る。
    引数: prices(list[float])、quantity/side/partial(int)、atr/step(float)、terminal(int|None)。
    返り値: dict[str, object]。市場入力・金融保存値は含まない。
    """
    price = np.asarray(prices, dtype=float)
    n = len(price)
    time = 1000.0 + np.arange(n) * step
    plans = np.zeros((n, 34), dtype=float)
    plans[:, 12:15] = np.nan
    plans[:, 33] = np.arange(n) - 1
    plans[0, 33] = np.nan
    plans[:, 21] = 0
    plans[:, 1] = 0
    plans[:, 7] = quantity
    plans[:, 23] = time[-1] + 1000.0
    plans[:, 24] = atr
    plans[:, 27] = np.maximum(0, np.arange(n) - 1)
    plans[:, 28] = np.maximum(0, np.arange(n) - 1)
    plans[:, 29] = np.maximum(0, np.arange(n) - 1)
    plans[1, 1] = -1
    plans[1, 21] = side
    plans[1, 22] = price[1]
    plans[1, 26] = 1.0
    plans[2:, 0] = side
    if partial is not None:
        plans[partial, 18] = 7
        plans[partial, 19] = partial - 1
    last = n - 1 if terminal is None else terminal
    plans[last, 18] = 9
    plans[last, 19] = last - 1
    plan_source = plans.copy()
    shadow_atr = np.zeros((n, 12))
    zero = np.zeros(n, dtype=np.int8)
    source = np.arange(n, dtype=np.int64)
    valid = np.ones(n, dtype=bool)
    losspar = np.zeros(19)
    losspar[8] = 1.0
    losspar[13] = 1.0
    args = [time, price, plan_source, plans, shadow_atr,
            zero.copy(), source.copy(), zero.copy(), source.copy(), valid.copy(),
            time[-1] + 1000.0, 5.0, quantity, quantity * 2,
            3, 0.5, 0, 1, 120.0, True, True, False, 0.0,
            zero.copy(), source.copy(), valid.copy(), zero.copy(), 0, -1,
            losspar, zero.copy(), source.copy(), valid.copy(), zero.copy(),
            source.copy(), source.copy(), valid.copy()]
    market = np.full((n, 12), np.nan)
    market[:, 0] = price
    market[:, 1] = price
    market[:, 2:4] = atr
    market[:, 4:8] = 0.2 * side
    market[:, 8] = time - 1.0
    market[:, 9] = time - 30.0
    market[:, 10] = time - 31.0
    market[:, 11] = 1.0
    return dict(args=args, market=market, quantity=quantity, side=side)


def run(core, case, policy=None):
    """
    機能: 人工署名を旧又は新の低層数値関数へ渡す。
    引数: core(object)、case(dict)、policy(ndarray|None)。
    返り値: tuple[ndarray, ...]は数値実装の全返却配列。
    """
    if policy is None:
        return core.simulate(*case["args"])
    return core.simulate(*case["args"], policy126=np.asarray(policy, float), market126=case["market"])


def set_entry(case, row, side, campaign=1, atr=2.0):
    """
    機能: 指定行にだけ人工の既公表新規計画を置く。
    引数: case(dict)、row/side/campaign(int)、atr(float)。
    返り値: None。計画は一行前の情報として扱う。
    """
    p = case["args"][3][row]
    p[:] = 0
    p[12:15] = np.nan
    p[1] = campaign - 1
    p[7] = case["quantity"]
    p[21] = side
    p[22] = case["args"][1][row]
    p[23] = case["args"][0][-1] + 1000
    p[24] = atr
    p[26] = 1
    p[27:30] = row - 1
    p[33] = row - 1


def reentry_case(second=18, opposite=False, profitable=False, missing=False, early_window=False):
    """
    機能: 損切り後の拒否・新アンカー・解除を別行に持つ人工列を作る。
    引数: second(int)、opposite/profitable/missing/early_window(bool)。
    返り値: dictは純人工の低層署名と対応特徴。
    """
    prices = [100.0] * 35
    prices[3] = 102.0 if profitable else 98.0
    prices[4:17] = [98.0] * 13
    prices[17:] = [100.0] * 18
    prices[-1] = 96.0 if opposite else 104.0
    case = artificial(prices, partial=None, step=30.0)
    plans = case["args"][3]
    plans[:, 0] = 0
    plans[2:4, 0] = 1
    plans[3, 18] = 1
    plans[3, 19] = 2
    plans[4:, 1] = 0
    set_entry(case, 16, -1 if opposite else 1)
    if second != 16:
        set_entry(case, second, -1 if opposite else 1)
    plans[second + 1:, 0] = -1 if opposite else 1
    market = case["market"]
    market[4, 8] = case["args"][0][3]
    market[5:17, 1] = 98.0
    market[5:17, 4:8] = 0.2
    market[17:, 1] = 100.0
    if missing:
        market[4:, 11] = 0
        market[4:, 1] = np.nan
        market[4:, 3] = np.nan
        market[4:, 6:9] = np.nan
    if early_window:
        market[17, 9] = case["args"][0][5] - 1
    return case


def mirror(case):
    """
    機能: 一〇〇中心の価格鏡像と売買符号反転を作る。
    引数: case(dict)は人工の一方方向ケース。
    返り値: dictは反対方向で同じ損益となる独立人工ケース。
    """
    value = copy.deepcopy(case)
    value["side"] *= -1
    value["args"][1] = 200.0 - value["args"][1]
    for index in (2, 3):
        plans = value["args"][index]
        plans[:, 0] *= -1
        plans[:, 21] *= -1
        plans[:, 22] = 200.0 - plans[:, 22]
        for col in (12, 13, 14):
            finite = np.isfinite(plans[:, col])
            plans[finite, col] = 200.0 - plans[finite, col]
    value["market"][:, :2] = 200.0 - value["market"][:, :2]
    value["market"][:, 4:8] *= -1
    return value


def prefix(case, count):
    """
    機能: 予定終端を変えず、観測列だけを過去の接頭へ切断する。
    引数: case(dict)、count(int)は残す観測数。
    返り値: dictは将来のない人工入力。
    """
    value = copy.deepcopy(case)
    for index, array in enumerate(value["args"]):
        if isinstance(array, np.ndarray) and index != 29:
            value["args"][index] = array[:count].copy()
    value["market"] = value["market"][:count].copy()
    return value


def assert_prefix(full, cut, count):
    """
    機能: 将来までの実行と接頭だけの実行で過去の経済結果を比較する。
    引数: full/cut(tuple[ndarray,...])、count(int)は切断長。
    返り値: intは確認配列数。未返済を強制清算しない。
    """
    comparisons = [(0, 7), (1, 2), (3, 0), (8, 0), (9, 0), (10, 0),
                   (11, 0), (13, 0), (15, 0), (16, 0), (17, 0), (19, 0)]
    for index, column in comparisons:
        expected = full[index][full[index][:, column] < count]
        np.testing.assert_array_equal(expected, cut[index])
    for index in (2, 5, 6, 7, 12, 14, 18):
        np.testing.assert_array_equal(full[index][:count], cut[index])
    return len(comparisons) + 7


def external_accounts(result):
    """
    機能: 注文価格と数量から現金・在庫・全返済損益を独立に計算する。
    引数: result(tuple[ndarray, ...])は人工実行の返却配列。
    返り値: dict[str, float]は独立算術の結果。不一致は例外。
    """
    trades, cycles, curve, orders, stats = result[:5]
    cash, inventory = 0.0, 0.0
    for row in orders:
        cash -= row[3] * row[4] * row[5]
        inventory += row[3] * row[4]
    gains = [row[2] * row[3] * (row[5] - row[4]) for row in trades]
    np.testing.assert_allclose(gains, trades[:, 10], atol=1e-12, rtol=0)
    np.testing.assert_allclose(sum(gains), stats[0], atol=1e-12, rtol=0)
    np.testing.assert_allclose(sum(gains), cycles[:, 3].sum(), atol=1e-12, rtol=0)
    np.testing.assert_allclose(inventory, 0.0, atol=1e-12, rtol=0)
    np.testing.assert_allclose(cash, sum(gains), atol=1e-12, rtol=0)
    np.testing.assert_allclose(stats[9], 0.0, atol=1e-12, rtol=0)
    entry = orders[orders[:, 7] == 1]
    assert len(entry) > 0 and np.all(entry[:, 4] == case_quantity(orders))
    np.testing.assert_allclose(entry[:, 4].sum(), trades[:, 3].sum(), atol=0, rtol=0)
    return dict(cash=float(cash), inventory=float(inventory), net=float(sum(gains)))


def case_quantity(orders):
    """
    機能: 人工ケースの初回全量を最初の実新規から得る。
    引数: orders(ndarray)は実注文。
    返り値: intは五枚又は十枚。
    """
    quantity = int(orders[orders[:, 7] == 1][0, 4])
    assert quantity in (5, 10)
    return quantity


def main():
    """
    機能: 非空の人工注文で旧新一致と独立在庫算術を検査する。
    引数: なし。
    返り値: None。結果は所有監査領域だけへ保存する。
    """
    sys.addaudithook(read_boundary)
    with legacy126.isolated():
        rt = legacy126.runtime()
        old = rt["old"].engine
        new = importlib.import_module("last_core126")
        policy_module = importlib.import_module("policy126")
        namespace = {}
        source = HERE.parent / "design/catalog126.py"
        exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), namespace)
        candidates = namespace["catalog"]()
        prices = [100, 100, 103, 106, 110, 108, 113, 112, 111, 108, 106, 104, 102, 100, 98, 94]
        records = []
        checks = 0
        for quantity in (5, 10):
            case = artificial(prices, quantity=quantity)
            before = run(old, case)
            after = run(new, case, [0, 0.5, 0, 0])
            assert len(after) == len(before) + 2
            for left, right in zip(before, after):
                np.testing.assert_array_equal(left, right)
                checks += 1
            accounts = external_accounts(after)
            records.append(dict(quantity=quantity, legacy_arrays=len(before), **accounts))
        # ----------------------------------------
        # 全条件は通常の初回数量と原部分返済を維持し、鏡像でも同じ収支になる。
        all_conditions = []
        for config in candidates:
            parameters = policy_module.policy_parameters(config)
            for quantity in (5, 10):
                case = artificial(prices, quantity=quantity)
                outcome = run(new, case, parameters)
                accounts = external_accounts(outcome)
                assert np.any(outcome[3][:, 6] == 7), "原の部分返済がない"
                opposite = run(new, mirror(case), parameters)
                external_accounts(opposite)
                mirror_stats = opposite[4].copy()
                mirror_stats[[2, 3]] = mirror_stats[[3, 2]]
                np.testing.assert_allclose(outcome[4], mirror_stats, atol=1e-12, rtol=0)
                np.testing.assert_array_equal(outcome[3][:, [0, 1, 2, 4, 6, 7]], opposite[3][:, [0, 1, 2, 4, 6, 7]])
                np.testing.assert_array_equal(outcome[3][:, 3], -opposite[3][:, 3])
                np.testing.assert_allclose(outcome[3][:, 5] + opposite[3][:, 5], 200.0, atol=1e-12, rtol=0)
                mutated = copy.deepcopy(case)
                mutated["args"][33][:] = -1
                mutated["args"][34][:] = 999999
                mutated["args"][35][:] = 999999
                mutated["args"][36][:] = True
                changed = run(new, mutated, parameters)
                for index in range(len(outcome)):
                    np.testing.assert_array_equal(outcome[index], changed[index])
                checks += 27
                all_conditions.append(dict(id=config["id"], quantity=quantity, **accounts))
        # ----------------------------------------
        # 実装から導出せず、固定した注文価格の外部算術で床の金額を指定する。
        profit_records = []
        for quantity, first_floor, next_floor, fill_row, expected_net in ((5, 21.0, 25.5, 12, 18.0), (10, 40.0, 47.5, 13, 30.0)):
            case = artificial(prices, quantity=quantity)
            case["market"][[5, 9], 4:8] = [-0.2, -0.3, -0.2, -0.3]
            outcome = run(new, case, [1.0, 0.5, 0, 0])
            accounts = external_accounts(outcome)
            events = outcome[19]
            floors = events[events[:, 2] == 6]
            np.testing.assert_array_equal(floors[:, 0], [5, 9])
            np.testing.assert_allclose(floors[:, 7], [first_floor, next_floor], atol=1e-12, rtol=0)
            np.testing.assert_allclose(outcome[18][6:9, 8], first_floor, atol=1e-12, rtol=0)
            np.testing.assert_allclose(outcome[18][9:fill_row, 8], next_floor, atol=1e-12, rtol=0)
            closes = outcome[3][outcome[3][:, 6] == 70]
            assert len(closes) == 1 and closes[0, 0] == fill_row
            assert closes[0, 1] == fill_row - 1
            assert accounts["net"] == expected_net
            for counter in ("片側", "不明", "同時計", "弱い逆行"):
                value = artificial(prices, quantity=quantity)
                value["market"][[5, 9], 4:8] = [-0.2, -0.3, -0.2, -0.3]
                if counter == "片側":
                    value["market"][:, 6:8] = 0.2
                elif counter == "不明":
                    value["market"][[5, 9], 11] = 0
                    value["market"][[5, 9], 6:9] = np.nan
                elif counter == "同時計":
                    value["market"][[5, 9], 11] = 0
                else:
                    value["market"][[5, 9], 4:8] = -0.05
                other = run(new, value, [1.0, 0.5, 0, 0])
                assert not np.any(other[19][:, 2] == 6)
                checks += 1
            checks += 8
            for length in (4, 6, 8, 10, 12, 14):
                checks += assert_prefix(outcome, run(new, prefix(case, length), [1.0, 0.5, 0, 0]), length)
            profit_records.append(dict(quantity=quantity, first_floor=first_floor, next_floor=next_floor, fill_row=fill_row, **accounts))
        # ----------------------------------------
        # 損失後のアンカーと解除は、同方向の権利だけを変更する。
        rearm_records = []
        for label, case, expected_entries, expected_release in (
            ("両方進行", reentry_case(), [1, 18], 17),
            ("窓が古い", reentry_case(second=19, early_window=True), [1, 19], 18),
            ("相手不明", reentry_case(missing=True), [1], None),
            ("逆方向独立", reentry_case(second=16, opposite=True), [1, 16], 17),
            ("黒字後制限なし", reentry_case(second=16, profitable=True, missing=True), [1, 16], None),
        ):
            outcome = run(new, case, [0, 0.5, 0.25, 0])
            accounts = external_accounts(outcome)
            entry_rows = outcome[3][outcome[3][:, 7] == 1, 0].astype(int).tolist()
            assert entry_rows == expected_entries, (label, entry_rows, expected_entries)
            event = outcome[19]
            anchors = event[event[:, 2] == 2]
            releases = event[event[:, 2] == 3]
            if label == "黒字後制限なし":
                assert not len(anchors) and not np.any(event[:, 2] == 1)
            elif label == "相手不明":
                assert not len(anchors) and not len(releases)
            else:
                assert anchors[0, 0] == 5, (label, anchors)
                assert anchors[0, 0] > 3 and anchors[0, 9] > case["args"][0][3]
                assert releases[0, 0] == expected_release, (label, releases)
            checks += 5
            rearm_records.append(dict(case=label, entries=entry_rows, release=expected_release, **accounts))
        # ----------------------------------------
        # 場予算は最初のリスク固定、次行の悪化も全て払う。
        case = artificial([100, 100, 100, 98, 96, 80, 90, 95, 100, 110, 120, 120, 120, 120, 120, 120, 120, 120], partial=None, atr=2.0)
        case["args"][3][:, 24] = 20.0
        case["args"][3][1, 24] = 2.0
        set_entry(case, 16, 1, campaign=1, atr=20.0)
        outcome = run(new, case, [0, 0.5, 0, 1.5])
        account = external_accounts(outcome)
        events = outcome[19]
        budget = events[events[:, 2] == 4]
        assert budget.shape[0] == 1 and budget[0, 0] == 4
        assert budget[0, 6] == 10.0
        close = outcome[3][outcome[3][:, 6] == 73]
        assert len(close) == 1 and close[0, 0] == 5 and close[0, 5] == 80.0
        assert account["net"] == -100.0 and account["net"] < -15.0
        assert (outcome[3][:, 7] == 1).sum() == 1
        checks += 6
        result = dict(全合格=True, 確認数=checks, 旧新既定無効=records,
                      全十六条件と二数量=all_conditions, 条件付き利益床=profit_records,
                      損失後再参加=rearm_records, 場損失の価格飛び=account,
                      許可小設定読取=OPENED, 新金融=0, 市場原本読取=0, 実市場配列読取=0,
                      実装源指紋={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (ENGINE/"last_core126.py", ENGINE/"policy126.py", source)})
    assert sys.argv[1:] in ([], ["--final"])
    output = HERE / ("原版と十六条件の最終源による独立純人工監査.json"
                     if sys.argv[1:] else "原版と十六条件の独立純人工監査.json")
    assert not output.exists()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
