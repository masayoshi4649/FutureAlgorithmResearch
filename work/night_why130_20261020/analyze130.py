"""旧結果を再利用し、夜間の新しい会計を分母を保って比較する。"""

import argparse
import sys
from common130 import HERE, PREV, BASE, read, save, reference

sys.path.insert(0, str(BASE))
from common128 import metrics as old_metrics


def metrics(rows):
    """
    機能: 旧安定性指標を保持し、無取引と実取引後の収支ゼロを区別する。
    引数: rows(list[dict])は同じ条件の商品場会計。
    返り値: dictは黒字・赤字・無取引・収支ゼロを区別した指標。
    """
    result = old_metrics(rows)
    result["flat"] = sum(r["entries"] == 0 for r in rows)
    result["breakeven"] = sum(r["entries"] > 0 and r["net"] == 0 for r in rows)
    assert result["black"] + result["red"] + result["flat"] + result["breakeven"] == len(rows)
    return result


def main():
    """
    機能: 夜間の全条件を方向別・時系列前後半・上位場除外で採点する。
    引数: --rounds(str複数)、--output(str)は対象と新しい保存名。
    返り値: None。売買判断や金融再生は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    old = read(PREV / "最終全場比較_確定.json")
    metadata = {(r["session"], r["symbol"]): r for r in old["rows"]}
    rows = [dict(r, origin="既存の保存会計を再利用") for r in old["rows"]
            if r["method"] in ("N36", "NV01", "NV25", "D17", "DV05", "DV07")]
    evidence = [reference(PREV / "最終全場比較_確定.json")]
    for name in args.rounds:
        data = read(HERE / name / "全条件の会計.json")
        assert data["passed"]
        evidence.append(reference(HERE / name / "全条件の会計.json"))
        for row in data["rows"]:
            info = metadata[row["session"], row["symbol"]]
            rows.append(dict(row, regime=info["regime"], week_start=info["week_start"],
                half_within_kind=info["half_within_kind"], kind_session_index=info["kind_session_index"]))
    seen = [(r["method"], r["session"], r["symbol"]) for r in rows]
    assert len(seen) == len(set(seen))
    summary = []
    for method in sorted({r["method"] for r in rows}):
        for symbol in ("TOPIX", "NK225"):
            selected = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
            stat = dict(method=method, symbol=symbol, kind=selected[0]["kind"], **metrics(selected))
            stat["regimes"] = {kind: metrics([r for r in selected if r["regime"] == kind])
                               for kind in sorted({r["regime"] for r in selected})}
            stat["halves"] = {kind: metrics([r for r in selected if r["half_within_kind"] == kind])
                              for kind in ("前半", "後半")}
            summary.append(stat)
            print(method, symbol, "収支", int(stat["net"]), "黒赤休", stat["black"], stat["red"], stat["flat"],
                  "最悪", int(stat["worst"]), "除上3", int(stat["without_top3"]), flush=True)
    save(HERE / args.output, dict(passed=True, rows=rows, summary=summary, evidence=evidence,
         financial_replays=0, note="全43場は既知の開発資料。日中は保存引用。無取引を黒字に数えない。"))


if __name__ == "__main__":
    main()
