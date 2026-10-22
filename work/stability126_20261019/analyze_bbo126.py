"""同じ固定優先順を実建値と次正常気配の完成会計へ適用する。"""

from analyze126 import metrics
from common126 import HERE, read, save, sha


def execute() -> None:
    """
    機能: 元LastとBBOの会計を混ぜず、全十六条件の安定性を再集計する。
    引数: なし。
    返り値: None。新たな売買再生は行わない。
    """
    path = HERE / "engine/bbo_next/全十六条件の次原行BBO会計.json"
    data = read(path)
    metadata = {(r["session"], r["symbol"]): r for r in data["metadata"]}
    ranking = []
    for spec in data["specs"]:
        products = {s: metrics([r for r in data["rows"] if r["method"] == spec["id"] and r["symbol"] == s], metadata)
                    for s in ("TOPIX", "NK225")}
        items = list(products.values())
        rank = [sum(p["no_entry"] for p in items), max(p["red"] for p in items),
            max(p["worst_to_typical"] if p["worst_to_typical"] is not None else 1e12 for p in items),
            sum(p["median"] <= 0. or p["excluding_best_three"] <= 0. for p in items),
            sum(p["regimes"].get(label, {}).get("net", 0.) <= 0. for p in items for label in ("上昇", "下落"))]
        ranking.append(dict(id=spec["id"], name=spec["name"], products=products, rank_key=rank,
            full_target_passed=all(p["no_entry"] == 0 and p["average_price_fraction"] >= .005 for p in items)))
    ranking.sort(key=lambda r: tuple(r["rank_key"]))
    save(HERE / "次正常気配の十六条件と方向別比較.json", dict(passed=True,
        source=dict(path=path.relative_to(HERE.parents[1]).as_posix(), sha256=sha(path)),
        selected=next(r["id"] for r in ranking if r["id"] != "E01"), ranking=ranking,
        target_achieved=any(r["full_target_passed"] for r in ranking),
        selection="Last比較の金融前に定めた優先順をそのまま適用。既知全41場での比較。"))
    for r in ranking:
        print(r["id"], " / ".join(f'{s}:純{p["net"]:,.0f} 赤{p["red"]}/41 中央{p["median"]:,.0f} 最悪{p["worst"]:,.0f}'
                                  for s, p in r["products"].items()), flush=True)


if __name__ == "__main__":
    execute()
