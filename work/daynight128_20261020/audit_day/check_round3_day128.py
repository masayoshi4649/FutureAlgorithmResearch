"""第三巡の中立許容と弱支持の整数数量変更を、純人工だけで独立検査する。"""

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
import adapter3


CHECKS = []
CASES = []


def check(name: str, condition: bool) -> None:
    """
    機能: 独立期待値に対する合否を記録する。
    引数: name(str)、condition(bool)は検査名と判定。
    返り値: None。不合格では停止する。
    """
    assert condition, name
    CHECKS.append(name)


def same(name: str, first: object, second: object) -> None:
    """
    機能: 配列を厳密照合する。
    引数: name(str)、first/second(object)は照合名と比較対象。
    返り値: None。
    """
    np.testing.assert_array_equal(first, second, err_msg=name)
    CHECKS.append(name)


def fixture(quantity: int, state: str = "中立") -> tuple:
    """
    機能: 新規一親と三段階部分返済を持つ合成値を作る。
    引数: quantity(int)は5又は10、state(str)は新規時の二市場状態。
    返り値: tupleはready/quotes/market/paper/history。
    """
    value = base.legacy.fixture([100.] * 11, [(0, 1, 8, 1)], quantity)
    ready, quotes, market, paper = value
    ready["session"] = "純人工_Day"; ready["start"] = 0.
    parts = [2, 1, 2] if quantity == 5 else [5, 2, 3]
    new = paper["orders"][0]
    paper["orders"] = np.array([new, [3, 2, 0, -1, parts[0], 100.5, 7, 0],
                               [6, 5, 0, -1, parts[1], 100.5, 30, 0],
                               [8, 7, 0, -1, parts[2], 100.5, 2, 0]], dtype=float)
    market[:, 11] = 1.; market[:, 4:8] = 0.
    if state == "強支持":
        market[:, 4] = .2; market[:, 6] = .2
    elif state == "弱支持":
        market[:, 4] = .02; market[:, 6] = .02
    elif state == "逆行":
        market[:, 4] = .2; market[:, 6] = -.2
    elif state == "未知":
        market[:, 6] = np.nan
    history = np.full((11, 15), np.nan)
    return ready, quotes, market, paper, history


def run(value: tuple, config: dict, summarize: bool = True) -> dict:
    """
    機能: 第三巡の公開接続を純人工で実行し、会計と料金を独立確認する。
    引数: value(tuple)、config(dict)、summarize(bool)は合成値・条件・終端会計の有無。
    返り値: dictは新規と返済の実注文・会計。
    """
    ready, quotes, market, paper, history = value
    result = adapter3.play_day(config, ready, quotes, market, history, base.legacy.interface.make_feed(paper))
    base.legacy.audit(value[:4], result)
    if summarize:
        report = adapter3.summarize(result, ready, config)
        rate = 418 if ready["symbol"] == "TOPIX" else 110
        multiplier = 1000. if ready["symbol"] == "TOPIX" else 10.
        fees = sum(int(order[4]) * rate // 10 for order in result["orders"])
        gross = float(result["trades"][:, 10].sum() * multiplier)
        check("実注文だけの料金会計_" + str(len(CASES)), report["fees"] == fees and report["net"] == gross - fees)
        check("実親の勝敗件数_" + str(len(CASES)), report["parent_wins"] + report["parent_losses"] <= len(result["cycles"]))
        if len(result["orders"]):
            check("数量上限は実使用枚数_" + str(len(CASES)), report["max_quantity"] == result["orders"][result["orders"][:, 7] == 1., 4].max())
        else:
            check("無取引の数量と料金は零_" + str(len(CASES)), report["max_quantity"] == report["fees"] == report["net"] == 0.)
    CASES.append(dict(id=config["id"], orders=len(result["orders"]),
                      new_quantity=float(result["orders"][result["orders"][:, 7] == 1., 4].sum())))
    return result


def main() -> None:
    """
    機能: 全D16〜20の整数配分・入口・途中返済・費用・因果性を確認する。
    引数: なし。
    返り値: None。金融再生0の監査証跡を最終源へ拘束して保存する。
    """
    paths = [base.TASK / name for name in ("adapter3.py", "adapter2.py", "day_core2.py",
                                          "bbo_order_kernel126.py", "第三巡条件.json", "run3.py")]
    paths += [Path(__file__), base.HERE / "check_day128.py",
              base.OLD / "input_audit/bbo_artificial126/check_bbo126.py"]
    sources = {p.relative_to(base.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    configs = {c["id"]: c for c in json.loads((base.TASK / "第三巡条件.json").read_text(encoding="utf-8"))
               if c["engine"] == "day"}
    for quantity in (5, 10):
        for state in ("中立", "弱支持", "強支持", "逆行", "未知"):
            value = fixture(quantity, state)
            feed = base.legacy.interface.make_feed(value[3])
            same("配分1は通知完全互換_" + str((quantity, state)), adapter3.resize_feed(feed, value[2], 1.), feed)
            for identifier, config in configs.items():
                result = run(value, config)
                if identifier == "D16":
                    expected = quantity if state == "強支持" else 0
                elif identifier == "D17":
                    expected = quantity if state in ("中立", "弱支持", "強支持") else 0
                elif identifier == "D18":
                    expected = quantity if state == "強支持" else int(quantity * .4)
                else:
                    fraction = .4 if identifier == "D19" else .6
                    expected = quantity if state == "強支持" else int(quantity * fraction) if state in ("中立", "弱支持") else 0
                entries = result["orders"][result["orders"][:, 7] == 1.]
                check("弱強中立逆行未知の採用枚数_" + str((quantity, state, identifier)),
                      entries[:, 4].sum() == expected)
                mirrored = list(base.legacy.mirror(value[:4])) + [base.reflect_history(value[4])]
                reflected = run(tuple(mirrored), config)
                same("鏡像の全行収支_" + str((quantity, state, identifier)),
                     result["curve"][:, [0, 1, 4]], reflected["curve"][:, [0, 1, 4]])
                same("鏡像の注文方向_" + str((quantity, state, identifier)),
                     result["orders"][:, 3], -reflected["orders"][:, 3])
        # ----------------------------------------
        # 比率別に独立した整数列を照合する。飛ばした返済も含め総新規と総返済を保存。
        value = fixture(quantity)
        feed = base.legacy.interface.make_feed(value[3])
        expected_parts = {
            (5, .4): [2., 1., 1.], (5, .6): [3., 1., 1., 1.],
            (10, .4): [4., 2., 1., 1.], (10, .6): [6., 3., 1., 2.],
        }
        expected_fees = {(5, .4): 165, (5, .6): 248, (10, .4): 88, (10, .6): 132}
        for fraction, identifier in ((.4, "D19"), (.6, "D20")):
            resized = adapter3.resize_feed(feed, value[2], fraction)
            same("累計丸めの独立整数列_" + str((quantity, fraction)),
                 resized[:, 4], expected_parts[quantity, fraction])
            check("紙上通知の総全返済保存_" + str((quantity, fraction)),
                  resized[resized[:, 7] == 1., 4].sum() == resized[resized[:, 7] == 0., 4].sum())
            result = run(value, configs[identifier])
            report = adapter3.summarize(result, value[0], configs[identifier])
            check("注文単位切捨て料金の手計算_" + str((quantity, fraction)),
                  report["fees"] == expected_fees[quantity, fraction])
            # ----------------------------------------
            # 部分返済の予約と実予算が競合しても、実残玉だけを返す。
            adverse = deepcopy(value)
            adverse[1]["bid"][3:6] = [96., 95., 94.]
            adverse[1]["ask"][3:6] = [97., 96., 95.]
            adverse[0]["last"][3:6] = [96.5, 95.5, 94.5]
            stopped = run(adverse, configs[identifier])
            desired = int(quantity * fraction)
            first_part = 1 if quantity == 5 else (2 if fraction == .4 else 3)
            same("部分返済競合時の実数量_" + str((quantity, fraction)),
                 stopped["orders"][:, 4], [desired, first_part, desired - first_part])
            same("部分返済競合時の実行行_" + str((quantity, fraction)),
                 stopped["orders"][:, 0], [2., 4., 5.])
            check("早期全返済後の紙上注文で過剰返済しない_" + str((quantity, fraction)),
                  stopped["stats"][9] == 0. and len(stopped["cycles"]) == 1)
            # ----------------------------------------
            # 新規後に強支持へ変わっても初回枚数や将来の部分返済を増やさない。
            changed = deepcopy(value); changed[2][2:, 4] = 100.; changed[2][2:, 6] = 100.
            changed_result = run(changed, configs[identifier])
            for field in base.legacy.interface.FIELDS:
                same("新規後支持更新で過去配分を変更しない_" + str((quantity, fraction, field)), result[field], changed_result[field])
            cut = 5
            short = list(deepcopy(value))
            for field in ("seq", "time_s", "last", "atr"):
                short[0][field] = short[0][field][:cut]
            for field in short[1]:
                short[1][field] = short[1][field][:cut]
            short[2], short[4] = short[2][:cut], short[4][:cut]
            short[3]["orders"] = short[3]["orders"][short[3]["orders"][:, 0] < cut]
            prefix = run(tuple(short), configs[identifier], summarize=False)
            same("配分処理の真の末尾切断_" + str((quantity, fraction)), result["curve"][:cut], prefix["curve"])
            same("配分処理の未来返済非参照_" + str((quantity, fraction)),
                 result["orders"][result["orders"][:, 0] < cut], prefix["orders"])
        # ----------------------------------------
        # 30秒に必要な条件だけを使い、120秒欠測を勝手に逆行へ分類しない。
        value = fixture(quantity)
        feed = base.legacy.interface.make_feed(value[3])
        for boundary, allowed in ((-.05, True), (-.050001, False)):
            market = value[2].copy(); market[1, 4] = boundary; market[1, 6] = boundary
            actual = adapter3.day_filter(feed, value[0], market, value[4], 5)
            check("明確逆行境界の包含_" + str((quantity, boundary)), bool(len(actual)) == allowed)
        market = value[2].copy(); market[:, 5] = np.nan; market[:, 7] = np.nan
        same("120秒だけの欠測は30秒条件を無効化しない_" + str(quantity),
             adapter3.day_filter(feed, value[0], market, value[4], 5), feed)
        market[:, 11] = 0.
        check("現在二市場未知を中立へ補完しない_" + str(quantity),
              len(adapter3.day_filter(feed, value[0], market, value[4], 5)) == 0)
        # ----------------------------------------
        # 量を変えない時の旧adapterとの全配列互換を全入口条件で確認する。
        for state in ("中立", "強支持", "逆行", "未知"):
            value = fixture(quantity, state)
            for entry_filter in range(5):
                config = dict(configs["D17"], entry_filter=entry_filter, weak_fraction=1.)
                ready, quotes, market, paper, history = value
                raw = base.legacy.interface.make_feed(paper)
                original = adapter2.play_day(config, ready, quotes, market, history, raw)
                updated = adapter3.play_day(config, ready, quotes, market, history, raw)
                for field in base.legacy.interface.FIELDS:
                    same("fraction1旧adapter同値_" + str((quantity, state, entry_filter, field)),
                         original[field], updated[field])
    check("最終源の監査中変更なし", all(hashlib.sha256((base.ROOT / name).read_bytes()).hexdigest() == sha for name, sha in sources.items()))
    target = base.HERE / ("第三巡日中の中立許容と整数数量の独立人工_" + str(time.time_ns()) + ".json")
    target.write_text(json.dumps(dict(
        passed=True, checks=CHECKS, count=len(CHECKS), cases=CASES, sources=sources,
        accounting_checks=len(base.legacy.CHECKS), market_reads=0, financial_replays=0, API=0,
    ), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, path=target.relative_to(base.ROOT).as_posix(),
                          checks=len(CHECKS), cases=len(CASES)), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        target = base.HERE / ("第三巡日中人工停止_" + str(time.time_ns()) + ".json")
        target.write_text(json.dumps(dict(passed=False, error=repr(error), checks=CHECKS, cases=CASES),
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
