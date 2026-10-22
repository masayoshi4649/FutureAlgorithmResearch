"""保存会計を全場・方向・時系列で比較し、合計だけの選択を避ける。"""

import argparse
import sys
from common129 import HERE, PREV, read, save, reference
sys.path.insert(0, str(PREV))
from common128 import metrics
from analyze5 import score


def main():
    """
    機能: 旧基準と指定巡までの保存会計だけを再集計する。
    引数: --rounds(str複数)、--output(str)は既存金融結果と新規集計位置。
    返り値: None。未知期間への有効性や金融再生回数は増やさない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    old = read(PREV/"round5/前後半と方向別の比較.json")
    rows = [r for r in old["rows"] if r["method"] in ("D17", "N27", "N36")]
    meta = {(r["session"], r["symbol"]): r for r in old["rows"]}
    refs = [reference(PREV/"round5/前後半と方向別の比較.json")]
    for folder in args.rounds:
        path = HERE/folder/"全条件の会計.json"
        result = read(path)
        refs.append(reference(path))
        for row in result["rows"]:
            extra = meta[row["session"], row["symbol"]]
            rows.append(dict(row, **{k: extra[k] for k in
                ("regime", "week_start", "half_within_kind", "kind_session_index")}))
    summaries = []
    for method in sorted({r["method"] for r in rows}):
        for symbol in ("TOPIX", "NK225"):
            chosen = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
            result = dict(method=method, symbol=symbol, kind=chosen[0]["kind"], **metrics(chosen))
            result["halves"] = {h: metrics([r for r in chosen if r["half_within_kind"] == h])
                                for h in ("前半", "後半")}
            result["regimes"] = {h: metrics([r for r in chosen if r["regime"] == h])
                                 for h in sorted({r["regime"] for r in chosen})}
            result["weeks"] = {h: metrics([r for r in chosen if r["week_start"] == h])
                               for h in sorted({r["week_start"] for r in chosen})}
            summaries.append(result)
    rankings = {}
    for kind in ("Day", "Night"):
        methods = sorted({s["method"] for s in summaries if s["kind"] == kind})
        ranks = []
        for method in methods:
            pair = [s for s in summaries if s["method"] == method]
            ranks.append(dict(method=method, full_score=list(score(pair)),
                              first_half_score=list(score([s["halves"]["前半"] for s in pair]))))
        rankings[kind] = dict(full=sorted(ranks, key=lambda r: (r["full_score"], r["method"]), reverse=True),
            first_half=sorted(ranks, key=lambda r: (r["first_half_score"], r["method"]), reverse=True))
    save(HERE/args.output, dict(passed=True, rows=rows, summary=summaries, rankings=rankings,
         inputs=refs, financial_replays=0,
         scope="全43場は既知開発。前後半順位は時系列点検であり未見評価ではない。無取引を勝ちに含めない。"))
    for s in summaries:
        print(s["method"], s["symbol"], "収支", int(s["net"]), "黒赤休",
              s["black"], s["red"], s["flat"], "最悪", int(s["worst"]),
              "後半", int(s["halves"]["後半"]["net"]), "除上3", int(s["without_top3"]), flush=True)


if __name__ == "__main__":
    main()
