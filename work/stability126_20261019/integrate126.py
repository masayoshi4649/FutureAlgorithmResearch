"""元Ｅ０１・既知入口・損失改善を、価格モデルを混ぜずに最終集計する。"""

from common126 import ROOT, HERE, read, save, sha
from analyze126 import metrics


def compare(rows: list[dict], metadata: list[dict]) -> list[dict]:
    """
    機能: 各場参加と上下両区分の黒字を満たす候補を先に分け、安定性を比較する。
    引数: rows(list[dict])は一価格モデルの会計、metadata(list[dict])は採点用場情報。
    返り値: list[dict]は事前に定めた安定性指標の順位と未達判定。
    """
    index = {(r["session"], r["symbol"]): r for r in metadata}
    result = []
    for method in dict.fromkeys(r["method"] for r in rows):
        products = {s: metrics([r for r in rows if r["method"] == method and r["symbol"] == s], index)
                    for s in ("TOPIX", "NK225")}
        both = list(products.values())
        minimum = all(p["no_entry"] == 0 and p["net"] > 0. and p["median"] > 0.
            and p["excluding_best_three"] > 0.
            and all(p["regimes"].get(label, {}).get("net", 0.) > 0. for label in ("上昇", "下落"))
            for p in both)
        score = [int(not minimum), sum(p["no_entry"] for p in both), max(p["red"] for p in both),
            max(p["worst_to_typical"] if p["worst_to_typical"] is not None else 1e12 for p in both),
            sum(p["regimes"].get(label, {}).get("net", 0.) <= 0. for p in both for label in ("上昇", "下落"))]
        result.append(dict(id=method, products=products, minimum_passed=minimum, rank_key=score,
            worst_compensated_by_typical=all(p["worst_to_typical"] is not None and p["worst_to_typical"] <= 1. for p in both),
            previous_price_target_passed=all(p["no_entry"] == 0 and p["average_price_fraction"] >= .005 for p in both)))
    return sorted(result, key=lambda r: tuple(r["rank_key"]))


def name_for(row: dict, old_names: dict) -> str:
    """
    機能: 取引条件の識別子に平易な短い表示名を付ける。
    引数: row(dict)は一場会計、old_names(dict)は固定条件名。
    返り値: strは入口・気配予算・出口の区別が付く表示名。
    """
    method = row["method"]
    if method in old_names:
        return old_names[method]
    parent = {"G": "入口再確認", "GU": "入口再確認と米国寄付き回避", "E01": "原版E01"}[row["paper_source"]]
    if row.get("quote_gate_enabled"):
        parent += "・気配予算"
    policy = row["policy_id"]
    if policy == "E01":
        return parent
    if policy in ("P025", "P050", "P075"):
        return parent+"・早期利益保護"+{"P025": "0.25R", "P050": "0.5R", "P075": "0.75R"}[policy]
    return parent+"・"+old_names[policy]


def execute() -> None:
    """
    機能: 保存済み全比較を統合し、公開する代表と原版を選ぶ。
    引数: なし。
    返り値: None。売買再生や市場本文の読取は行わない。
    """
    paths = [HERE / "原版と十五改修の全四十一場会計.json",
        HERE / "rearm126/ＧとＧＵの全四十一場会計.json",
        HERE / "engine/bbo_next/全十六条件の次原行BBO会計.json",
        HERE / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json"]
    sources = [read(p) for p in paths]
    assert all(d["passed"] for d in sources)
    original, gates, bbo, extension = sources
    old_names = {s["id"]: s["name"] for s in original["specs"]}
    old_names.update(E01="原版E01", E01_G="入口を再確認するE01", E01_G_U="入口再確認と米国寄付き回避")
    models = []
    for label, records, indexes, metadata, expected in (
        ("next_normal_bbo", bbo["rows"]+extension["rows"], (2, 3), bbo["metadata"], 5658),
        ("observed", original["rows"]+gates["rows"], (0, 1), original["metadata"], 1476)):
        assert len(records) == expected
        assert len({(r["method"], r["session"], r["symbol"]) for r in records}) == expected
        ranking = compare(records, metadata)
        selected = ranking[0]["id"]
        full_names = {r["method"]: name_for(r, old_names) for r in records}
        baseline_ids = ["E01", "G_E01", "GU_E01"] if label == "next_normal_bbo" else ["E01", "E01_G", "E01_G_U"]
        choices = list(dict.fromkeys([selected]+baseline_ids))
        models.append(dict(id=label, selected=selected, methods=[dict(id=m, name=full_names[m]) for m in choices],
            rows=[{k: r[k] for k in ("method", "session", "symbol", "profit", "loss", "net")}
                  for r in records if r["method"] in choices],
            sources=[dict(path=paths[i].relative_to(ROOT).as_posix(), sha256=sha(paths[i])) for i in indexes],
            ranking=ranking, minimum_passed=any(r["minimum_passed"] for r in ranking),
            price_target_passed=any(r["previous_price_target_passed"] for r in ranking)))
    save(HERE / "最終統合の価格モデル別比較と公開会計.json", dict(passed=True, models=models,
        sessions=original["sessions"], new_financial_accounts=0,
        original_market_reads=0, API=0,
        classification="場末の上下ラベルは採点だけ。選定は既知データ内であり未知場の保証ではない。",
        count_note="表示会計に同一金融の同値引用が含まれる。独立した有効性標本数又は新金融回数とは呼ばない。"))
    for model in models:
        for r in model["ranking"][:8]:
            print(model["id"], r["id"], "上下等最低通過", r["minimum_passed"],
                [(s, p["net"], p["red"], p["no_entry"], p["worst"]) for s, p in r["products"].items()], flush=True)


if __name__ == "__main__":
    execute()
