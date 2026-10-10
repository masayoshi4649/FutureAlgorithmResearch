"""主492・固定感度・追加1場の全台帳を、設定単位6並列で独立会計する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json

import numpy as np

from account_parts import HERE, ROOT, study, row_account, aggregate, same_fields
from independent_account import save


def score(periods: dict, ident: str) -> tuple:
    """機能: 前16の悪い商品・割合和・組数・IDを独立に並べる。

    引数: periods(dict)、ident(str)。返り値: 昇順選定値(tuple)。
    """
    own = [periods[s] for s in ("TOPIX", "NK225")]
    ratios = [r["money_loss_share"] if r["money_loss_share"] is not None else 1. for r in own]
    return max(ratios), sum(ratios), -sum(r["trades"] for r in own), ident


def control_ids(c: dict) -> list[str]:
    """機能: 同入口・幅・期限の管理と配分の固定対照を独立列挙する。

    引数: c(dict)。返り値: 対照ID(list[str])。
    """
    if c["policy"] == 0:
        return [c["id"]]
    return [f"{c['entry']}_P{p}_R{c['stop_bp']}_T{c['stop_bp'] if p == 2 else 2*c['stop_bp']}_H{c['hold_minutes']}_A{a}"
        for p in range(1, 6) for a in (0, 1)]


def audit_case(case: tuple, materials: dict, fixed: dict, template: dict) -> tuple:
    """機能: 一設定の全口座・全曲線・追加リスク・商品別期間を検算する並列単位。

    引数: case(tuple)、materials/fixed/template(dict)。返り値: 条件識別・独立結果・計数(tuple)。
    """
    delay, c, area, unseen = case
    counts = template.copy()
    packet = study.load(area/"results"/f"{c['id']}.json")
    assert packet["config"] == dict(c, delay=delay)
    path = area/"ledgers"/f"{c['id']}.pkl"
    assert study.digest(path) == packet["ledger_SHA256"]
    ledgers = study.load(path)
    ready, _, _, _, _, _ = materials[delay]
    sessions = fixed["追加1"] if unseen else fixed["全29"]
    keys = sorted(k for k in ready if k[0] in sessions)
    assert set(ledgers) == set(keys) and len(packet["rows"]) == len(keys)
    saved = {(r["session"], r["symbol"]): r for r in packet["rows"]}
    rows = []; front = hashlib.sha256()
    for key in keys:
        args = study.arguments(c, key, *materials[delay])
        ledger = ledgers[key]
        actual = row_account(key, c, args, ledger, ready[key])
        counts["比較項目数"] += same_fields(actual, saved[key], (delay, unseen, c["id"], key))
        rows.append(actual)
        if key[0] in fixed["前16"]:
            front.update(str(key).encode("utf-8")); front.update(ledger["orders"].tobytes())
        counts["口座数"] += 1; counts["全注文数"] += len(ledger["orders"])
        counts["全組数"] += actual["trades"]; counts["全建値決済数"] += actual["legs"]
        counts["予定時刻超過返済数"] += actual["予定時刻超過返済数"]
        counts["予定時刻超過最大秒"] = max(counts["予定時刻超過最大秒"], actual["予定時刻超過最大秒"])
        counts["判断約定最大秒"] = max(counts["判断約定最大秒"], actual["判断約定最大秒"])
        for field in ("追加判断証跡数", "追加約定証跡数", "場末取消追加数", "約定後予算超過数"):
            counts[field] += actual[field]
    assert packet["front_orders_SHA256"] == front.hexdigest()
    periods = {}
    names = ("追加1",) if unseen else ("前16", "後13", "全29")
    for name in names:
        periods[name] = {}
        for symbol in ("TOPIX", "NK225"):
            actual = aggregate(rows, symbol, fixed[name])
            counts["比較項目数"] += same_fields(actual, packet["periods"][name][symbol], (delay, unseen, c["id"], name, symbol))
            periods[name][symbol] = actual
            counts["期間商品会計数"] += 1
    if c["id"] == fixed["基準"] and not unseen:
        old_area = ROOT/"work/wave_v76" if delay == 5 else ROOT/"work/wave_v76/sensitivity"/f"delay{delay}"
        before = study.load(old_area/"ledgers/B_F15_E0_M0_C0_T40_H30.pkl")
        for key in keys:
            np.testing.assert_array_equal(ledgers[key]["orders"][:, :8], before[key]["orders"])
            np.testing.assert_array_equal(ledgers[key]["trades"][:, :11], before[key]["trades"])
            assert ledgers[key]["curve_hash"] == before[key]["curve_hash"]
            counts["旧J1一致口座数"] += 1
    counts["条件数"] += 1
    return (delay, unseen, c["id"]), dict(config=c, periods=periods, front_orders_SHA256=front.hexdigest()), counts


def main() -> None:
    """機能: 全会計と前16選定を再現し、未見固定群の差替えがないことも照合する。

    引数: なし。返り値: なし(None)。新Nightの再生や根拠にした再選定は行わない。
    """
    fixed = study.load(HERE.parent/"事前固定.json")
    assert all(study.digest(ROOT/p) == expected for p, expected in fixed["SHA256"].items())
    catalog = fixed["条件"]
    assert len(catalog) == len({c["id"] for c in catalog}) == 492
    selected = study.load(HERE.parent/"前半選定.json")
    by_id = {c["id"]: c for c in catalog}
    controls = {fixed["基準"]}
    for chosen in selected["代表"]:
        group = control_ids(by_id[chosen["id"]])
        assert group == chosen["controls"]
        controls.update(group)
    assert sorted(controls) == selected["感度対象"] == selected["未見対象"]
    start = study.load(HERE.parent/"未見確認開始.json")
    assert set(start["対象"]) == controls and start["選定SHA256"] == study.digest(HERE.parent/"前半選定.json")
    assert start["未見"] == fixed["追加1"]
    assert study.load(HERE.parent/"未見確認完了.json")["差替え"] is False
    materials = {d: study.material(d) for d in (5, 1, 15)}
    cases = [(5, c, HERE.parent, False) for c in catalog]
    for delay in (1, 15):
        area = HERE.parent/"sensitivity"/f"delay{delay}"
        assert len(list((area/"results").glob("*.json"))) == len(controls)
        cases.extend((delay, c, area, False) for c in catalog if c["id"] in controls)
    area = HERE.parent/"unseen"
    assert len(list((area/"results").glob("*.json"))) == len(controls)
    cases.extend((5, c, area, True) for c in catalog if c["id"] in controls)
    template = dict(条件数=0, 口座数=0, 全注文数=0, 全組数=0, 全建値決済数=0, 比較項目数=0, 期間商品会計数=0,
        追加判断証跡数=0, 追加約定証跡数=0, 場末取消追加数=0, 約定後予算超過数=0, 旧J1一致口座数=0,
        予定時刻超過返済数=0, 予定時刻超過最大秒=0., 判断約定最大秒=0.)
    counts = template.copy(); independent = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [pool.submit(audit_case, c, materials, fixed, template) for c in cases]
        for index, job in enumerate(as_completed(jobs), 1):
            key, result, local = job.result(); independent[key] = result
            for k, value in local.items():
                counts[k] = max(counts[k], value) if k.endswith("最大秒") else counts[k]+value
            if index % 24 == 0 or index == len(cases):
                print(f"全曲線・明細・追加枠独立監査 {index}/{len(cases)}", flush=True)
    choices = []; qualifying = {}
    for family in ("J", "Q", "P"):
        pool = [c for c in catalog if c["family"] == family]
        eligible = [c for c in pool if all(independent[(5, False, c["id"])]["periods"]["前16"][s]["trades"] >= 20
            and independent[(5, False, c["id"])]["periods"]["前16"][s]["active_sessions"] >= 8 for s in ("TOPIX", "NK225"))]
        qualifying[family] = len(eligible)
        options = eligible or [c for c in pool if all(independent[(5, False, c["id"])]["periods"]["前16"][s]["trades"] > 0
            for s in ("TOPIX", "NK225"))] or pool
        chosen = min(options, key=lambda c: score(independent[(5, False, c["id"])]["periods"]["前16"], c["id"]))
        choices.append(dict(id=chosen["id"], family=family, eligible=bool(eligible),
            score=list(score(independent[(5, False, chosen["id"])]["periods"]["前16"], chosen["id"])), controls=control_ids(chosen)))
    assert choices == selected["代表"]
    assert all(study.digest(ROOT/p) == expected for p, expected in fixed["SHA256"].items())
    representatives = {c["id"]: dict(既往=independent[(5, False, c["id"])]["periods"],
        感度={str(d): independent[(d, False, c["id"])]["periods"] for d in (1, 15)},
        追加=independent[(5, True, c["id"])]["periods"]) for c in choices}
    save(HERE/"主492条件と固定感度追加の全会計独立監査.json", dict(合格=True, **counts,
        主条件数=492, 感度条件数=len(controls)*2, 追加場条件数=len(controls), 全曲線照合数=counts["口座数"],
        前16代表=choices, 前半最低件数充足数=qualifying, 固定三代表の会計=representatives,
        前16だけで選定=True, 追加場で選び直しなし=True, 全明細損失を計上=True,
        SHA256=fixed["SHA256"], 限界="既往29は既知保存場。追加1場は固定群の初回確認。代理時計に基づく約定検査で実受信順の保証ではない。",
        原本取得=0, API取得=0, 実注文=0, 新Night再生回数=0))
    print(json.dumps(dict(合格=True, **counts, 代表=[c["id"] for c in choices]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
