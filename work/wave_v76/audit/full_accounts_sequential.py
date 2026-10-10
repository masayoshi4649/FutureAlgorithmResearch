"""全996条件と固定感度84条件の金額・管理・前半選定を独立監査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from account_parts import study, ROOT, row_account, aggregate, same_fields
from independent_account import save


HERE = Path(__file__).resolve().parent


def score(period: dict, ident: str) -> tuple:
    """機能: 前半の両商品金額損失割合から、悪い側・合計・件数の順に比較する。

    引数: period(dict)、ident(str)。返り値: 評価(tuple)。
    """
    a = [period[s] for s in ("TOPIX", "NK225")]
    loss = [d["money_loss_share"] if d["money_loss_share"] is not None else 1. for d in a]
    return max(loss), sum(loss), -sum(d["trades"] for d in a), ident


def controls(c: dict) -> list[str]:
    """機能: 同じ入口・幅・期限の管理M0/M1/M2/M3対照を別式で列挙する。

    引数: c(dict)。返り値: 七対照のID(list[str])。
    """
    ids = []
    for mode, confirm in [(0, 0), (1, 15), (1, 30), (2, 15), (2, 30), (3, 15), (3, 30)]:
        signal = "F15" if c["legacy_entry"] and mode == 0 else c["signal_id"]
        prefix = "B_" if c["legacy_entry"] else ""
        hold = str(int(c["hold_seconds"] / 60)) if c["hold_seconds"] else "S"
        ids.append(f"{prefix}{signal}_E{c['entry_confirm']}_M{mode}_C{confirm}_T{int(c['width_fraction']*10000)}_H{hold}")
    return ids


def main() -> None:
    """機能: 全台帳・全行清算時価・管理理由・商品会計・代表選定を再構成する。

    引数: なし。返り値: なし(None)。凍結設定を変更しない。
    """
    fixed = study.load(HERE.parent / "事前固定.json")
    assert all(study.digest(ROOT / p) == expected for p, expected in fixed["SHA256"].items())
    catalog = fixed["条件"]
    assert len(catalog) == len({c["id"] for c in catalog}) == 996
    selected = study.load(HERE.parent / "前半選定.json")
    by_id = {c["id"]: c for c in catalog}
    sensitivity = set()
    for r in selected["代表"]:
        expected = controls(by_id[r["id"]])
        assert r["controls"] == expected
        sensitivity.update(expected)
    benchmark = "B_F15_E0_M0_C0_T40_H30"
    sensitivity.add(benchmark)
    assert sensitivity == set(selected["感度対象"]) and len(sensitivity) == 42
    materials = {d: study.material(d) for d in (5, 1, 15)}
    assert len(materials[5][0]) == 58
    assert len(list((HERE.parent / "results").glob("*.json"))) == 996
    cases = [(5, c, HERE.parent) for c in catalog]
    for delay in (1, 15):
        area = HERE.parent / "sensitivity" / f"delay{delay}"
        assert len(list((area / "results").glob("*.json"))) == 42
        cases.extend((delay, c, area) for c in catalog if c["id"] in sensitivity)
    counts = dict(条件会計数=0, 口座会計数=0, 全決済明細数=0, 全注文数=0, 期間商品会計数=0, 比較項目数=0,
        実約定反転数=0, 反転予約取消数=0, 発注後場末失効反転数=0,
        予定撤収limit超過返済数=0, 予定撤収limit超過口座数=0, 予定撤収limit超過最大秒=0., 判断から次有効原本行約定の最大秒=0.)
    independent = {}
    for index, (delay, c, area) in enumerate(cases):
        packet = study.load(area / "results" / f"{c['id']}.json")
        assert packet["config"] == dict(c, delay=delay) and packet["delay"] == delay
        path = area / "ledgers" / f"{c['id']}.pkl"
        assert packet["ledger_SHA256"] == study.digest(path)
        ledgers = study.load(path)
        ready, book, state, maps, legacy, meta = materials[delay]
        assert set(ledgers) == set(ready) and len(packet["rows"]) == 58
        saved = {(r["session"], r["symbol"]): r for r in packet["rows"]}
        rows, front = [], hashlib.sha256()
        for key in sorted(ready):
            args = study.arguments(c, key, *materials[delay])
            ledger = ledgers[key]
            actual = row_account(key, c, ready[key], book[key], args, ledger)
            counts["比較項目数"] += same_fields(actual, saved[key], (c["id"], delay, key))
            rows.append(actual)
            if key[0] in fixed["前16"]:
                front.update(str(key).encode("utf-8"))
                front.update(ledger["orders"].tobytes())
            counts["口座会計数"] += 1
            counts["全決済明細数"] += actual["trades"]
            counts["全注文数"] += len(ledger["orders"])
            counts["実約定反転数"] += actual["flip_count"]
            counts["反転予約取消数"] += actual["flip_cancel_count"]
            counts["発注後場末失効反転数"] += actual["発注後場末失効の反転数"]
            counts["予定撤収limit超過返済数"] += actual["予定撤収時刻超過返済数"]
            counts["予定撤収limit超過口座数"] += int(actual["予定撤収時刻超過返済数"] > 0)
            counts["予定撤収limit超過最大秒"] = max(counts["予定撤収limit超過最大秒"], actual["予定撤収超過最大秒"])
            counts["判断から次有効原本行約定の最大秒"] = max(counts["判断から次有効原本行約定の最大秒"], actual["判断から約定の最大秒"])
        assert front.hexdigest() == packet["front_orders_SHA256"]
        periods = {}
        for name in ("前16", "後13", "全29"):
            periods[name] = {}
            for symbol in ("TOPIX", "NK225"):
                actual = aggregate(rows, symbol, fixed[name])
                counts["比較項目数"] += same_fields(actual, packet["periods"][name][symbol], (c["id"], delay, name, symbol))
                periods[name][symbol] = actual
                counts["期間商品会計数"] += 1
        independent[(delay, c["id"])] = dict(config=c, periods=periods, front_orders_SHA256=front.hexdigest())
        if c["id"] == benchmark:
            old_area = ROOT / "work/wave_v75" if delay == 5 else ROOT / "work/wave_v75/sensitivity" / f"delay{delay}"
            old = study.load(old_area / "ledgers/J1_W300_L0_T40_H30.pkl")
            for key in ready:
                assert np.array_equal(old[key]["orders"], ledgers[key]["orders"])
                assert np.array_equal(old[key]["trades"], ledgers[key]["trades"])
                assert old[key]["curve_hash"] == ledgers[key]["curve_hash"]
        counts["条件会計数"] += 1
        if (index + 1) % 24 == 0 or index + 1 == len(cases):
            print(f"全金額・途中管理監査 {index + 1}/{len(cases)}", flush=True)
    choices, qualifying = [], {}
    for family in range(1, 7):
        pool = [c for c in catalog if c["family"] == family]
        eligible = [c for c in pool if all(independent[(5, c["id"])]["periods"]["前16"][s]["trades"] >= 20
            and independent[(5, c["id"])]["periods"]["前16"][s]["active_sessions"] >= 8 for s in ("TOPIX", "NK225"))]
        qualified = bool(eligible)
        qualifying[str(family)] = len(eligible)
        if not eligible:
            eligible = [c for c in pool if all(independent[(5, c["id"])]["periods"]["前16"][s]["trades"] > 0 for s in ("TOPIX", "NK225"))] or pool
        c = min(eligible, key=lambda v: score(independent[(5, v["id"])]["periods"]["前16"], v["id"]))
        follow = independent[(5, c["id"])]["periods"]["後13"]
        passed = all(follow[s]["net"] > 0 and follow[s]["payoff"] is not None and follow[s]["payoff"] > 1
            and follow[s]["without_best_session"] > 0 for s in ("TOPIX", "NK225"))
        choices.append(dict(id=c["id"], family=family, eligible=qualified,
            score=list(score(independent[(5, c["id"])]["periods"]["前16"], c["id"])), 後13有望条件=passed,
            front_orders_SHA256=independent[(5, c["id"])]["front_orders_SHA256"], controls=controls(c)))
    assert choices == selected["代表"]
    main_ids, seen = [], set()
    for c in sorted((c for c in choices if c["eligible"]), key=lambda c: c["score"]):
        if c["front_orders_SHA256"] not in seen:
            main_ids.append(c["id"])
            seen.add(c["front_orders_SHA256"])
        if len(main_ids) == 3:
            break
    assert main_ids == selected["主3"]
    save(HERE / "全996条件と固定遅延84条件の会計選定独立監査.json", dict(合格=True, **counts,
        主条件数=996, 固定感度条件数=84, 全行清算曲線指紋照合数=counts["口座会計数"],
        主3=main_ids, 機構別代表=choices, 最低件数充足条件数=qualifying,
        主3期間={ident: independent[(5, ident)]["periods"] for ident in main_ids},
        六代表固定感度={c["id"]: {str(d): independent[(d, c["id"])]["periods"] for d in (5, 1, 15)} for c in choices},
        旧J1全口座一致数=58 * 3, 固定SHA256=fixed["SHA256"],
        商品別全損失明細を計上=True, 前16だけで選定=True, 感度で代表変更なし=True,
        限界="全29場は既知保存データ。共通受信時計がないため代理時計と原本順の検査。予定limit超過は次有効原本行待ちで、全返済は保存end=limit+300未満。",
        原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, **counts, 主3=main_ids), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
