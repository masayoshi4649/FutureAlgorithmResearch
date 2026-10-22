"""日中核の単調損失幅、部分返済、入口条件と旧通知同値を追加反証する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

import check_day128 as test

sys.path.insert(0, str(test.TASK))
import adapter128

sys.path.insert(0, str(test.OLD / "gated_bbo126"))
from feed_filter126 import economic_key


def main() -> None:
    """
    機能: 日中核の修正後境界と全日中保存通知の同値を確認する。
    引数: なし。
    返り値: None。保存通知の指紋照合を含むが、実市場の金融再生は行わない。
    """
    paths = [test.TASK / name for name in ("day_core128.py", "bbo_order_kernel126.py",
                                          "catalog128.py", "adapter128.py", "prepare128.py")]
    paths += [Path(__file__), test.HERE / "check_day128.py"]
    sources = {p.relative_to(test.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    cfg = {c["id"]: c for c in test.legacy.catalog()}["E01"]
    for quantity in (5, 10):
        for tail in (4., 100., np.nan, -1.):
            value = test.legacy.fixture([100, 100, 100, 100, 98.5, 98, 100, 100, 100], [(0, 1, 7, 1)], quantity)
            atr = np.full(9, 4.); atr[3] = 2.; atr[4:] = tail
            result = test.run(value, cfg, 1, atr)
            test.same("一度縮めた損切りを再拡大未知で緩めない" + str((quantity, tail)),
                      result["orders"][-1, :2], [5., 4.])
            reservation = result["execution_events"][result["execution_events"][:, 1] == 9.][0]
            test.check("保持した縮小境界も記録" + str((quantity, tail)), reservation[7] == -2. * quantity)
        # ----------------------------------------
        # 親が変われば縮小率を一度だけ初期化する。
        value = test.legacy.fixture([100, 100, 100, 100, 98.5, 98, 100, 100, 100, 100, 98.5, 98.5, 100, 100, 100],
                                   [(0, 1, 6, 1), (1, 8, 13, 1)], quantity)
        atr = np.full(15, 4.); atr[3:5] = 2.
        result = test.run(value, cfg, 1, atr)
        test.same("新しい親の縮小率は初期化", result["orders"][result["orders"][:, 7] == 0., 0], [5., 14.])
        # ----------------------------------------
        # 部分利確の実現益を床へ含め、返済を二重計上しない。
        value = test.legacy.fixture([100, 100, 100, 103, 103, 102, 100, 100, 100, 100, 100],
                                   [(0, 1, 9, 1)], quantity)
        part = quantity // 2
        value[3]["orders"][1, 4] = quantity - part
        value[3]["orders"] = np.vstack([value[3]["orders"], [3, 2, 0, -1, part, 103.5, 7, 0]])
        value[3]["orders"] = value[3]["orders"][np.argsort(value[3]["orders"][:, 0])]
        history = np.full((11, 15), np.nan); history[:, 1] = 110.; history[:, 10] = -1.
        result = test.run(value, cfg, 2, history=history)
        test.same("部分利確後の床返済行" + str(quantity), result["orders"][:, 0], [2., 4., 7.])
        test.same("部分利確後の数量保存" + str(quantity), result["orders"][:, 4], [quantity, part, quantity - part])
        test.check("部分利確の二重計上なし" + str(quantity), result["stats"][0] == 2. * part - (quantity - part))
        # ----------------------------------------
        # 追加入口条件は新規通知行だけを読み、親の後続返済を同じ判断で通す。
        value = test.legacy.fixture([100.] * 16, [(0, 2, 6, 1), (1, 9, 14, -1)], quantity)
        ready, quotes, market, paper = value
        ready["start"] = 0.; ready["time_s"] = np.arange(16, dtype=float) * 300.
        feed = test.legacy.interface.make_feed(paper)
        history = np.ones((16, 15)); history[:, 8] = 100.; history[:, 13] = 1.
        market[:, 11] = 1.; market[:, 4:8] = 0.
        for kind in (0, 1, 2, 3, 4):
            actual = adapter128.day_filter(feed, ready, market, history, kind)
            expected = {0: [0, 1, 2, 3], 1: [0, 1, 2, 3], 2: [], 3: [2, 3], 4: [0, 1]}[kind]
            test.same("入口の基本条件" + str((quantity, kind)), actual, feed[expected])
        changed = market.copy(); changed[2, 5] = -.2; changed[2, 7] = -.3
        result = adapter128.day_filter(feed, ready, changed, history, 1)
        test.same("両市場逆行は親返済ごと拒否", result, feed[2:])
        changed[2, 7] = .1
        test.same("片市場反対だけでは拒否しない", adapter128.day_filter(feed, ready, changed, history, 1), feed)
        changed[:, 11] = 0.
        test.check("未知は逆行なしと同一視しない", len(adapter128.day_filter(feed, ready, changed, history, 1)) == 0)
        changed = market.copy(); changed[2, 4] = .051; changed[2, 6] = .051
        test.same("両市場短期支持を通知行で判定", adapter128.day_filter(feed, ready, changed, history, 2), feed[:2])
        changed[3:, 4:8] = -100.
        future_changed = adapter128.day_filter(feed, ready, changed, history, 2)
        test.same("採用後に未来反対があっても入口を遡及取消しない",
                  future_changed[future_changed[:, 2] == 0.], feed[:2])
    # ----------------------------------------
    # 全44日中口座の準備済み通知と四数値方策が、既存G_Qの経済キーに一致する。
    files = [test.OLD / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json",
             test.OLD / "update_20261020/追加二場の八公開選択会計.json"]
    rows = []
    for path in files:
        payload = path.read_bytes()
        sources[path.relative_to(test.ROOT).as_posix()] = hashlib.sha256(payload).hexdigest()
        data = json.loads(payload)
        rows += [row for row in data["rows"] if row["method"] == "G_Q" and row["session"].endswith("_Day")]
    test.check("日中全口座44件", len(rows) == 44)
    feed_proofs = []
    for row in rows:
        path = test.TASK / "prepared" / (row["session"] + ".npz")
        with np.load(path, allow_pickle=False) as data:
            key = economic_key(data[row["symbol"] + "__feed"], np.zeros(4))
        test.check("全日中通知と元GQ方策の厳密一致_" + row["symbol"] + "_" + row["session"],
                   key == row["economic_key"])
        feed_proofs.append(dict(session=row["session"], symbol=row["symbol"], economic_key=key,
                               feature_path=path.relative_to(test.ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    test.check("監査中の数値源変更なし",
               all(hashlib.sha256((test.ROOT / name).read_bytes()).hexdigest() == sha for name, sha in sources.items()))
    target = test.HERE / ("単調幅と部分返済及び全四十四通知の独立追加監査_" + str(time.time_ns()) + ".json")
    target.write_text(json.dumps(dict(
        passed=True, checks=test.CHECKS, count=len(test.CHECKS), cases=test.CASES,
        sources=sources, feed_proofs=feed_proofs, market_reads=0, financial_replays=0, API=0,
    ), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, path=target.relative_to(test.ROOT).as_posix(),
                          checks=len(test.CHECKS), artificial_cases=len(test.CASES), saved_feed_checks=len(feed_proofs)), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        target = test.HERE / ("追加監査停止_" + str(time.time_ns()) + ".json")
        target.write_text(json.dumps(dict(passed=False, error=repr(error), checks=test.CHECKS, cases=test.CASES),
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
