"""共同336条件と固定遅延感度の全会計・前半選定を独立再構成する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from account_parts import study, ROOT, row_account, aggregate, same_fields
from independent_account import save
from real_signals import load_material


HERE = Path(__file__).resolve().parent


def prepared(c: dict, key: tuple, ready: dict, book: dict, entry: dict, meta: dict) -> dict:
    """機能: 監査済共同候補を自市場の疎な方向配列と会計条件へ接続する。

    引数: c/ready/book/entry/meta(dict)、key(tuple)。返り値: 独立会計器の参照条件(dict)。
    """
    r, f = ready[key], book[key]
    direct = np.zeros(len(r["seq"]), np.int8)
    candidates = entry[c["signal_id"]][key]["candidates"]
    if len(candidates):
        direct[candidates[:, 1].astype(int)] = candidates[:, 2].astype(np.int8)
    return dict(open_price=meta["references"]["|".join(key)]["ref_open"]["value"], missing_previous=False,
        direction=direct, quality=f["valid"] & (f["bid"] > 0) & (f["ask"] > f["bid"]) & (f["ask"] - f["bid"] <= 2 * r["tick"] + 1.e-9))


def independent_score(period: dict, ident: str) -> tuple:
    """機能: 前16だけの両商品の最悪金額損失割合から採点する。

    引数: period(dict)、ident(str)。返り値: 昇順評価(tuple)。
    """
    values = [period[s] for s in ("TOPIX", "NK225")]
    shares = [value["money_loss_share"] if value["money_loss_share"] is not None else 1. for value in values]
    return max(shares), sum(shares), -sum(value["trades"] for value in values), ident


def main() -> None:
    """機能: 全378設定の台帳、予定超過、商品会計、前半選択と感度固定を検査する。

    引数: なし。返り値: なし(None)。後半や感度で選び直さない。
    """
    fixed = study.load(HERE.parent / "事前固定.json")
    assert all(study.digest(ROOT / name) == expected for name, expected in fixed["SHA256"].items())
    assert (HERE.parent / "engine.py").read_bytes() == (ROOT / "work/wave_v74/engine.py").read_bytes()
    ready, book, sync, meta = load_material()
    all_entries = {delay: study.load(HERE.parent / f"prepared/signals_delay{delay}.pkl") for delay in (5, 1, 15, 60)}
    configuration = fixed["条件"]
    assert len(configuration) == 336 and len({c["id"] for c in configuration}) == 336
    selected = study.load(HERE.parent / "前半選定.json")
    expected_sensitivity_ids = {r["id"] for r in selected["代表"]}
    expected_sensitivity_ids |= {"S" + ident[1:] for ident in expected_sensitivity_ids.copy()}
    cases = [(5, c, HERE.parent) for c in configuration]
    for delay in (1, 15, 60):
        cases += [(delay, c, HERE.parent / "sensitivity" / f"delay{delay}") for c in configuration if c["id"] in expected_sensitivity_ids]
        assert len(list((HERE.parent / "sensitivity" / f"delay{delay}" / "results").glob("*.json"))) == 14
    assert len(cases) == 378 and len(list((HERE.parent / "results").glob("*.json"))) == 336
    counts = dict(条件会計数=0, 口座会計数=0, 全決済明細数=0, 全注文数=0, 期間商品会計数=0, 比較項目数=0,
        予定撤収limit超過返済数=0, 予定撤収limit超過口座数=0, 予定撤収limit超過最大秒=0., 判断から次有効原本行約定の最大秒=0.)
    independent = {}
    for index, (delay, c, area) in enumerate(cases):
        packet = study.load(area / "results" / (c["id"] + ".json"))
        expected_config = dict(c, delay=delay)
        assert packet["config"] == expected_config and packet["delay"] == delay
        ledger_path = area / "ledgers" / (c["id"] + ".pkl")
        assert packet["ledger_SHA256"] == study.digest(ledger_path)
        ledgers = study.load(ledger_path)
        assert set(ledgers) == set(ready) and len(packet["rows"]) == 58
        saved_rows = {(r["session"], r["symbol"]): r for r in packet["rows"]}
        rows = []
        front = hashlib.sha256()
        for key in sorted(ready):
            p = prepared(c, key, ready, book, all_entries[delay], meta)
            ledger = ledgers[key]
            actual = row_account(key, c, ready[key], book[key], p, ledger)
            assert len(ledger["pauses"]) == 0 and ledger["stats"][3] == ledger["stats"][5] == ledger["stats"][6] == 0
            actual["candidate_count"] = len(all_entries[delay][c["signal_id"]][key]["candidates"])
            counts["比較項目数"] += same_fields(actual, saved_rows[key], (c["id"], delay, key))
            rows.append(actual)
            if key[0] in fixed["前16"]:
                front.update(str(key).encode("utf-8"))
                front.update(ledger["orders"].tobytes())
            counts["口座会計数"] += 1
            counts["全決済明細数"] += actual["trades"]
            counts["全注文数"] += len(ledger["orders"])
            counts["予定撤収limit超過返済数"] += actual["予定撤収時刻超過返済数"]
            counts["予定撤収limit超過口座数"] += int(actual["予定撤収時刻超過返済数"] > 0)
            counts["予定撤収limit超過最大秒"] = max(counts["予定撤収limit超過最大秒"], actual["予定撤収超過最大秒"])
            counts["判断から次有効原本行約定の最大秒"] = max(counts["判断から次有効原本行約定の最大秒"], actual["判断から約定の最大秒"])
        assert front.hexdigest() == packet["front_orders_SHA256"]
        periods = {}
        for period in ("前16", "後13", "全29"):
            periods[period] = {}
            for symbol in ("TOPIX", "NK225"):
                actual = aggregate(rows, symbol, fixed[period])
                counts["比較項目数"] += same_fields(actual, packet["periods"][period][symbol], (c["id"], delay, period, symbol))
                periods[period][symbol] = actual
                counts["期間商品会計数"] += 1
        independent[(delay, c["id"])] = dict(config=c, periods=periods, front_orders_SHA256=front.hexdigest())
        counts["条件会計数"] += 1
        if (index + 1) % 24 == 0 or index + 1 == len(cases):
            print(f"共同＋固定感度の全会計監査: {index + 1}/{len(cases)}", flush=True)
    choices = []
    qualifying_counts = {}
    for family in range(1, 8):
        pool = [c for c in configuration if c["paired"] and c["family"] == family]
        qualified = [c for c in pool if all(independent[(5, c["id"])]["periods"]["前16"][s]["trades"] >= 20 and independent[(5, c["id"])]["periods"]["前16"][s]["active_sessions"] >= 8 for s in ("TOPIX", "NK225"))]
        eligible = bool(qualified)
        qualifying_counts[str(family)] = len(qualified)
        if not qualified:
            qualified = [c for c in pool if all(independent[(5, c["id"])]["periods"]["前16"][s]["trades"] > 0 for s in ("TOPIX", "NK225"))]
        if not qualified:
            qualified = pool
        chosen = min(qualified, key=lambda c: independent_score(independent[(5, c["id"])]["periods"]["前16"], c["id"]))
        packet = independent[(5, chosen["id"])]
        follow = packet["periods"]["後13"]
        passed = all(follow[s]["net"] > 0 and follow[s]["payoff"] is not None and follow[s]["payoff"] > 1 and follow[s]["without_best_session"] > 0 for s in ("TOPIX", "NK225"))
        choices.append(dict(id=chosen["id"], family=family, eligible=eligible,
            score=list(independent_score(packet["periods"]["前16"], chosen["id"])), 後13有望条件=passed, front_orders_SHA256=packet["front_orders_SHA256"]))
    assert choices == selected["代表"]
    main_ids, used = [], set()
    for c in sorted((c for c in choices if c["eligible"]), key=lambda c: c["score"]):
        if c["front_orders_SHA256"] not in used:
            used.add(c["front_orders_SHA256"])
            main_ids.append(c["id"])
        if len(main_ids) == 3:
            break
    assert main_ids == selected["主3"]
    save(HERE / "全336条件と固定遅延42条件の会計選定独立監査.json", dict(合格=True, **counts,
        主条件数=336, 感度条件数=42, 全行清算曲線指紋照合数=counts["口座会計数"], 固定SHA256=fixed["SHA256"],
        主3=main_ids, 機構別代表=choices, 最低件数充足条件数=qualifying_counts,
        主3期間={ident: independent[(5, ident)]["periods"] for ident in main_ids},
        機構別代表固定感度={c["id"]: {str(delay): independent[(delay, c["id"])]["periods"] for delay in (5, 1, 15, 60)} for c in choices},
        商品別全損失明細を計上=True, 感度で代表変更なし=True, 前16だけで選定=True,
        限界="代理時計上の同期と原本順を検査した。実受信の同期は証明しない。予定limit超過は次有効原本行を待つためで、全返済は保存監視end=limit+300未満。前16/後13は既知データの時間分割。",
        原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, **counts, 主3=main_ids), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
