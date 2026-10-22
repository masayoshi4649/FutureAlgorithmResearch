"""両商品を別々に評価し、原版の改修を場の安定性で比較する。"""

import statistics
from common126 import HERE, read, save, sha


def metrics(rows: list[dict], metadata: dict) -> dict:
    """
    機能: 円建ての利益・損失と、上位依存・方向・価格幅を別々に集計する。
    引数: rows(list[dict])は一条件一商品の全場、metadata(dict)は場初末情報。
    返り値: dictは場を省かない評価値。
    """
    positive = [r["net"] for r in rows if r["net"] > 0.]
    worst = min(r["net"] for r in rows)
    mean_positive = statistics.mean(positive) if positive else 0.
    symbol = rows[0]["symbol"]
    cap, multiplier = (10, 1000.) if symbol == "TOPIX" else (20, 10.)
    rates = [r["net"]/(cap*multiplier*metadata[r["session"], symbol]["first"]) for r in rows]
    values = dict(symbol=symbol, sessions=len(rows),
        profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
        net=sum(r["net"] for r in rows), red=sum(r["net"] < 0. for r in rows),
        black=len(positive), zero=sum(r["net"] == 0. for r in rows),
        no_entry=sum(r["entry_orders"] == 0 for r in rows),
        total_entries=sum(r["entry_orders"] for r in rows),
        median=statistics.median(r["net"] for r in rows),
        average=sum(r["net"] for r in rows)/len(rows), worst=worst,
        average_positive=mean_positive,
        worst_to_typical=-min(0., worst)/mean_positive if mean_positive else None,
        excluding_best_three=sum(r["net"] for r in rows)-sum(sorted(positive, reverse=True)[:3]),
        average_price_fraction=statistics.mean(rates),
        long_net=sum(r["long_net"] for r in rows), short_net=sum(r["short_net"] for r in rows),
        regimes={}, strong_regimes={})
    for target, column in (("regimes", "regime"), ("strong_regimes", "strong_regime")):
        for label in ("上昇", "下落", "同値", "小変動"):
            chosen = [r for r in rows if metadata[r["session"], symbol][column] == label]
            if chosen:
                values[target][label] = dict(sessions=len(chosen),
                    profit=sum(r["profit"] for r in chosen), loss=sum(r["loss"] for r in chosen),
                    net=sum(r["net"] for r in chosen), median=statistics.median(r["net"] for r in chosen),
                    red=sum(r["net"] < 0. for r in chosen))
    return values


def execute() -> None:
    """
    機能: 結果を改変せず、金融前の優先順で共通条件を選ぶ。
    引数: なし。
    返り値: None。全条件と方向別の比較を非公開作業資料へ保存する。
    """
    path = HERE / "原版と十五改修の全四十一場会計.json"
    data = read(path)
    assert data["passed"] and len(data["rows"]) == 1312
    metadata = {(m["session"], m["symbol"]): m for m in data["metadata"]}
    comparisons = []
    for spec in data["specs"]:
        item = dict(id=spec["id"], name=spec["name"], products={})
        for symbol in ("TOPIX", "NK225"):
            rows = [r for r in data["rows"] if r["method"] == spec["id"] and r["symbol"] == symbol]
            assert len(rows) == 41
            item["products"][symbol] = metrics(rows, metadata)
        products = list(item["products"].values())
        item["rank_key"] = [sum(p["no_entry"] for p in products),
            max(p["red"] for p in products),
            max(p["worst_to_typical"] if p["worst_to_typical"] is not None else 1e12 for p in products),
            sum(p["median"] <= 0. or p["excluding_best_three"] <= 0. for p in products),
            sum(p["regimes"].get(label, {}).get("net", 0.) <= 0.
                for p in products for label in ("上昇", "下落"))]
        item["full_target_passed"] = all(p["no_entry"] == 0 and p["average_price_fraction"] >= .005
                                          for p in products)
        comparisons.append(item)
    comparisons.sort(key=lambda item: tuple(item["rank_key"]))
    selected = next(item for item in comparisons if item["id"] != "E01")
    save(HERE / "十六条件の方向別比較と固定優先順による選定.json", dict(passed=True,
        source=dict(path=path.relative_to(HERE.parents[1]).as_posix(), sha256=sha(path)),
        selected=selected["id"], ranking=comparisons,
        target_achieved=any(item["full_target_passed"] for item in comparisons),
        caveat="結果からの既知範囲内選定。上下に対称な式は、有限標本の上下両区分が同利益になることを保証しない。"))
    for item in comparisons:
        print(item["id"], " / ".join(f'{s}:純{p["net"]:,.0f} 赤{p["red"]}/41 中央{p["median"]:,.0f} 最悪{p["worst"]:,.0f}'
              for s, p in item["products"].items()), flush=True)


if __name__ == "__main__":
    execute()
