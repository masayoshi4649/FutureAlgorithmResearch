"""小試行・順行追加の固定予算と注文順を、市場なしの独立手計算で監査する。"""

from __future__ import annotations

import ast
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V3 = HERE.parent
BASE = V3.parent
ROOT = BASE.parents[1]
os.environ["NUMBA_CACHE_DIR"] = str(HERE / "private_numba_cache")
sys.path.insert(0, str(V3))
import engine_v3 as engine

CHECKS = 0
CASES = []
O = {name: i for i, name in enumerate(engine.ORDER_COLUMNS)}
P = {name: i for i, name in enumerate(engine.PARENT_COLUMNS)}


# ----------------------------------------


def check(value: bool, note: str) -> None:
    """
    機能: 手計算の期待条件を照合し、不一致なら停止する。
    引数: value(bool)、note(str) は条件と説明。
    返り値: None。
    """
    global CHECKS
    assert bool(value), note
    CHECKS += 1


def near(actual: object, expected: object, note: str) -> None:
    """
    機能: 数値又は配列の手計算期待値と照合する。
    引数: actual/expected(object)、note(str) は値と説明。
    返り値: None。
    """
    check(bool(np.allclose(actual, expected, rtol=1e-10, atol=1e-6, equal_nan=True)), note)


def fixture(bid: list[float], ask: list[float] | None = None, mode: int = 2, trail: float = 1.,
            exits: tuple[int, ...] = (), valid_off: tuple[int, ...] = (), times: list[float] | None = None,
            **changes: object) -> tuple[dict, dict, dict, dict]:
    """
    機能: 正常気配→同row公開の人工イベントと単一入口を作る。
    引数: bid/ask(list[float])、mode(int)、trail(float)、人工の退出・欠測・時刻・設定上書き。
    返り値: tuple[dict,dict,dict,dict] は既知足・気配・方針・設定。市場値は含まない。
    """
    b = np.asarray(bid, dtype=float)
    a = b + .5 if ask is None else np.asarray(ask, dtype=float)
    n = len(b)
    t = np.arange(n, dtype=float) if times is None else np.asarray(times, dtype=float)
    bars = dict(valid=np.ones(n, dtype=bool), anchor=(a + b) / 2.,
                pub_raw_row=np.arange(n, dtype=np.int64), pub_price_time_s=t.copy(), t_s=t.copy())
    quotes = dict(row=np.arange(n, dtype=np.int64), time=t, bid=b, ask=a)
    policy = dict(entry=np.zeros(n, dtype=np.int8), exit_long=np.zeros(n, dtype=bool),
                  exit_short=np.zeros(n, dtype=bool), width=np.full(n, 5.), valid=np.ones(n, dtype=bool))
    policy["entry"][0] = 1
    for row in exits:
        policy["exit_long"][row] = policy["exit_short"][row] = True
    for row in valid_off:
        policy["valid"][row] = False
    settings = dict(quantity=10, multiplier=1000., fee=41.8, allocation_mode=mode,
                    trail_multiple=trail, entry_end=1e9, close_time=1e9, entry_mode=0, execution_mode=0, guard=2)
    settings.update(changes)
    return bars, quotes, policy, settings


def run(f: tuple[dict, dict, dict, dict]) -> dict:
    """
    機能: 純人工で実装を実行し、ログから独立した全会計と停止予算を確認する。
    引数: f(tuple) は人工足・気配・方針・設定。
    返り値: dict は純人工結果。実市場又は既金融結果を読み込まない。
    """
    answer = engine.run_policy(*f)
    orders, parents, s = answer["orders"], answer["parents"], answer["summary"]
    cap, multiplier, fee = f[3]["quantity"], f[3]["multiplier"], f[3]["fee"]
    check(np.all(orders[:, O["fill_raw_row"]] > orders[:, O["decision_raw_row"]]), "全注文で同row約定禁止")
    check(np.all(orders[:, O["basket_quantity_after"]] <= cap), "上限枚数")
    near(orders[:, O["fee"]], np.floor(orders[:, O["quantity"]] * fee + 1e-9), "注文単位の費用切捨て")
    near(s["fees"], sum(orders[:, O["fee"]]), "実支払費用総和")
    near(s["fills"], len(orders), "約定は実注文ログ数")
    near(s["profit"] - s["loss"], sum(parents[:, P["net"]]), "利益損失は親単位")
    for parent in np.unique(orders[:, O["parent"]]):
        selected = orders[orders[:, O["parent"]] == parent]
        buys = selected[selected[:, O["kind"]] != 3]
        d = int(buys[0, O["side"]])
        q0 = int(buys[0, O["quantity"]])
        r = Fraction(str(buys[0, O["fixed_risk_width"]]))
        qsum = 0
        value = Fraction(0)
        paid = 0
        fixed_budget = q0 * r * Fraction(str(multiplier)) + 2 * math.floor(q0 * fee + 1e-9)
        previous_stop = -math.inf if d == 1 else math.inf
        for order in buys:
            q = int(order[O["quantity"]])
            qsum += q
            value += q * Fraction(str(order[O["price"]]))
            paid += math.floor(q * fee + 1e-9)
            weighted = value / qsum
            closefee = math.floor(qsum * fee + 1e-9)
            hard = weighted + d * (Fraction(paid + closefee) - fixed_budget) / (qsum * Fraction(str(multiplier)))
            stop = order[O["stop_after"]]
            near(order[O["wac_after"]], float(weighted), "WACは全実約定の加重平均")
            near(order[O["basket_quantity_after"]], qsum, "追加後数量")
            check(d * (stop - float(hard)) >= -1e-7, "停止線は当初予算を広げない")
            check(d * (stop - previous_stop) >= -1e-7, "停止線は有利側だけ更新")
            previous_stop = stop
        closed = selected[selected[:, O["kind"]] == 3]
        if len(closed):
            check(len(closed) == 1, "部分返済をしない")
            parent_row = parents[parents[:, P["parent"]] == parent][0]
            gross = d * (closed[0, O["price"]] - float(value / qsum)) * qsum * multiplier
            net = gross - paid - closed[0, O["fee"]]
            near(parent_row[P["gross"]], gross, "親grossの独立WAC会計")
            near(parent_row[P["net"]], net, "全初回追加費用と一括返済費用")
            near(parent_row[P["initial_loss_budget"]], float(fixed_budget), "初回円予算は追加で不変")
            near(parent_row[P["entry_fees"]], paid, "親新規追加費用")
            near(parent_row[P["closed_quantity"]], qsum, "親全枚数を一括返済")
    if s["unclosed"] == 0:
        near(s["realized"], sum(parents[:, P["gross"]]) - s["fees"], "全場現金会計")
        near(s["net"], s["realized"], "全返済なら参考評価で補完しない")
    return answer


def main() -> None:
    """
    機能: 少量・全量・順行増加、gap、場予算、期限、EOF、prefixを独立人工で確認する。
    引数: なし。
    返り値: None。市場入力・cache・実成績・金融再生・APIへの接続は0。
    """
    sources = [V3 / name for name in ("engine_v3.py", "run_v3.py", "plan_v3.py")] + [Path(__file__)]
    before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    r = run(fixture([3999.5]))
    check(r["summary"]["fills"] == 0, "判断と同rowの初回約定禁止")
    r = run(fixture([3999.5, 3999.5], times=[0., 0.]))
    check(r["summary"]["unclosed"] == 2 and not len(r["parents"]), "同時計後row新規とEOF未清算")
    near(r["summary"]["net"], -1166., "EOFは全含み損と予定返済費用を含む")
    near(r["summary"]["realized"], -83., "EOFで架空返済料を実払いにしない")
    CASES.append("同row禁止・同時計後row・EOF未清算と実現/予定費用の分離")

    for mode, quantity, expected in ((0, 2, 5834.), (1, 10, 29164.)):
        r = run(fixture([3999.5, 3999.5, 4002.5, 4003.], mode=mode, exits=(2,)))
        near(r["summary"]["net"], expected, "小試行/全量の手計算対照")
        near(r["summary"]["initial_quantity_min"], quantity, "初回数量")
        near(r["summary"]["session_loss_budget_yen"], 20000., "全配分で同じscout基準場予算")
        check(r["summary"]["add_fills"] == 0, "固定数量は順行しても追加しない")
    CASES.append("少量固定2枚/全量固定10枚と同一円の場予算")

    path = [3999.5, 3999.5, 4002.5, 4002.5, 4005., 4005., 4007.5, 4007.5, 4008., 4006.]
    for trail, expected_stop in ((.5, 4005.5), (1., 4004.7334)):
        r = run(fixture(path, trail=trail, exits=(8,)))
        near(r["orders"][:, O["quantity"]], [2, 2, 3, 3, 10], "累計20/40/70/100%と一括返済")
        near(r["summary"]["net"], 12666., "増加後の純額手計算")
        near(r["summary"]["fees"], 834., "各追加切捨てと10枚一括close418円")
        near(r["parents"][0, P["wac"]], 4004.65, "全増加後WAC")
        near(r["parents"][0, P["initial_loss_budget"]], 10166., "小試行の親予算を保持")
        near(r["stop"][8], expected_stop, "費用後BEと二つの保険幅")
        check(r["parents"][0, P["be_armed"]] == 1, "+R順行で費用後BEを発動")
    CASES.append("2→4→7→10と固定当初予算・費用BE・.5R/1R追尾")

    r = run(fixture([3999.5, 3999.5, 4002.5, 3989.5, 3980.]))
    near(r["summary"]["net"], -60333., "悪い追加gapの純損失を隠さない")
    near(r["orders"][:, O["fill_raw_row"]], [1, 3, 4], "悪い追加fillの後さらに次rowで返済")
    near(r["orders"][:, O["decision_raw_row"]], [0, 2, 3], "予約済み追加を遡及取消しない")
    near(r["parents"][0, P["wac"]], 3995., "悪い追加もWACへ反映")
    near(r["parents"][0, P["initial_loss_budget"]], 10166., "gapでも予算値は変更しない")
    check(r["parents"][0, P["stop_reason"]] == 5, "このgapは共通場budgetの超過が優先")
    check(r["summary"]["loss"] > 10166., "損失予算は実約定損失上限ではない")
    CASES.append("追加予約→悪気配実fill→場stop判断→後row返済の−60,333円")

    r = run(fixture([3999.5, 3999.5, 4008., 4008., 4008.], exits=(3,)))
    check(r["summary"]["add_fills"] == 1, "複数段階を同quoteで通過したら不足分一注文")
    near(r["orders"][1, O["quantity"]], 8, "20%から100%へ最大到達段階まで")
    near(r["summary"]["fees"], 835., "一回8枚追加と段階追加の丸め差")
    expired = run(fixture([3999.5, 3999.5, 4008., 4008., 4008.], times=[0., 1., 2., 63., 64.], exits=(3,)))
    check(expired["summary"]["add_fills"] == 0 and expired["summary"]["canceled"] == 1, "60秒失効後も同段階を再予約しない")
    CASES.append("最大到達段階を一注文・失効しても段階予約を消費")

    full = run(fixture([3999.5, 3999.5, 3997.5, 3997.], mode=1))
    near(full["summary"]["net"], -30836., "FULLは親1Rより先に共通場budgetで返済")
    check(full["parents"][0, P["stop_reason"]] == 5, "FULLの共通場budget理由")
    near(full["parents"][0, P["initial_loss_budget"]], 50836., "FULL親予算は初回実枚数基準")
    scout = run(fixture([3999.5, 3999.5, 3997.5, 3997.], mode=0))
    check(scout["summary"]["halted"] == 0 and scout["summary"]["unclosed"] == 2, "同じ値動きのscoutは円損失が小さい")
    CASES.append("同じ場budgetでFULLだけ先に止まる比較")

    r = run(fixture([3999.5, 3999.5, 4002.5, 4001.5, 4001.], exits=(2,), valid_off=(2, 3, 4)))
    near(r["orders"][:, O["kind"]], [1, 2, 3], "valid消失とfamily撤回後も先行追加を約定")
    near(r["orders"][:, O["fill_raw_row"]], [1, 3, 4], "先行追加と撤回返済の同row禁止")
    check(r["parents"][0, P["stop_reason"]] == 4, "入口validと独立に撤回を維持")
    CASES.append("入口valid消失/撤回と先行追加の競合順序")

    r = run(fixture([3999.5, 3999.5, 4000., 4001.], close_time=2., entry_end=1.5))
    check(r["summary"]["unclosed"] == 0 and r["parents"][0, P["stop_reason"]] == 7, "場末は後rowで全返済")
    r = run(fixture([3999.5, 3999.5, 4000.], close_time=2., entry_end=1.5))
    check(r["summary"]["unclosed"] == 2 and len(r["parents"]) == 0, "場末後rowなしは未清算")
    CASES.append("場末返済と観測EOFの区別")

    # ----------------------------------------
    # 全配分と追尾幅で、鏡像と前方prefixの注文/完結親/全公開資産を照合する。
    for mode in (0, 1, 2):
        for trail in (.5, 1.):
            f = fixture(path, mode=mode, trail=trail, exits=(8,))
            full = run(f)
            mb = {k: v.copy() for k, v in f[0].items()}
            mq = {k: v.copy() for k, v in f[1].items()}
            mp = {k: v.copy() for k, v in f[2].items()}
            mb["anchor"] = 8000. - mb["anchor"]
            mq["bid"], mq["ask"] = 8000. - f[1]["ask"], 8000. - f[1]["bid"]
            mp["entry"] *= -1
            opposite = run((mb, mq, mp, dict(f[3])))
            for key in ("net", "profit", "loss", "fees", "fills", "max_quantity", "max_drawdown"):
                near(full["summary"][key], opposite["summary"][key], "買売鏡像の全会計")
            near(full["orders"][:, O["price"]], 8000. - opposite["orders"][:, O["price"]], "鏡像約定価格")
            for cut in (2, 4, 6, 8):
                pf = tuple({k: v[:cut].copy() for k, v in item.items()} for item in f[:3]) + (dict(f[3]),)
                prefix = run(pf)
                for key in ("equity", "position", "cash", "drawdown", "quantity", "stop", "parent_liquidation_net"):
                    near(prefix[key], full[key][:cut], "未来に依存しない公開" + key)
                near(prefix["orders"], full["orders"][full["orders"][:, O["fill_raw_row"]] < cut], "未来に依存しない実注文")
                near(prefix["parents"], full["parents"][full["parents"][:, P["exit_raw_row"]] < cut], "未来に依存しない完結親")
    CASES.append("全3配分×2追尾の売買鏡像と4prefixの注文・親・資産・stop不変")

    nk = fixture([59990., 59990., 60050., 60050., 60100., 60100., 60150., 60150., 60160., 60120.],
                 quantity=20, multiplier=10., fee=11., exits=(8,))
    nk[2]["width"][:] = 100.
    nk[1]["ask"] = nk[1]["bid"] + 10.
    nk[0]["anchor"] = (nk[1]["bid"] + nk[1]["ask"]) / 2.
    r = run(nk)
    near(r["orders"][:, O["quantity"]], [4, 4, 6, 6, 20], "NK20枚の20/40/70/100%")
    near(r["summary"]["session_loss_budget_yen"], 8000., "NK4枚の共通場予算")
    CASES.append("NKmicro20上限・4/8/14/20・11円単価")

    # ----------------------------------------
    # driver/planは実行せずASTと定義だけで36列・設定・登録順を照合する。
    driver = ast.parse((V3 / "run_v3.py").read_text(encoding="utf-8"))
    constants = {}
    for node in driver.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("ENTRIES", "ALLOCATIONS"):
                    constants[target.id] = ast.literal_eval(node.value)
    check([v[0] for v in constants["ENTRIES"]] == ["COMMON20", "OPEN20", "CENTER20", "FAIL20", "A20", "D20"], "既6入口の列順")
    check(len(constants["ENTRIES"]) * len(constants["ALLOCATIONS"]) * 2 == 36, "6×3×2の36spec接続")
    driver_text = (V3 / "run_v3.py").read_text(encoding="utf-8")
    plan_text = (V3 / "plan_v3.py").read_text(encoding="utf-8")
    check("run_v2.settings(symbol, scene, 0, 4, 2)" in driver_text and "setting.update(allocation_mode=" in driver_text, "初回成行/共通guardと配分settings接続")
    check("engine_v3.ORDER_COLUMNS" in driver_text and "engine_v3.PARENT_COLUMNS" in driver_text and "answer['parents'].tolist()" in driver_text, "注文15/親27列とsummary保存接続")
    check("'COMMON', 'OPEN', 'CENTER', 'FAIL'" in plan_text and "('A', 'D')" in plan_text, "初回4入口とv2追加2入口のindices構成")
    check("proposal_complete" in plan_text and "m['sha256']" in driver_text, "正式照合完備とmanifestSHAを入力より前に検査")
    CASES.append("SOURCE_ONLYの既6入口indices・36spec・settings・ログ列・登録/manifest接続")
    after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    check(before == after, "監査中source不変")
    proof = dict(全合格=True, 検査数=CHECKS, 検査群=CASES, source_SHA256=after,
                 市場入力読取=0, cache読取=0, 金融結果読取=0, 金融再実行=0, API=0,
                 NumBa隔離="監査専用private_numba_cache。標準engine_v3名でimportし既運用cacheへ書かない。",
                 限界="人工会計・因果順・SOURCE_ONLY接続の確認。手法収益性や未知場の成功証明ではない。")
    destination = HERE / "小試行と順行追加の固定予算及び次原row会計の独立純人工監査.json"
    assert not destination.exists()
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
