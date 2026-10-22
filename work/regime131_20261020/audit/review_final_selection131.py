"""第四巡後の公開候補を、最新の損失規模重視と大勝ち保持の両面から独立確認する。"""

from pathlib import Path
import json
import time

from review_portfolio_comparison131 import (
    WORK, ROOT, HERE, CHECKS, read, reference, check, equal_stats,
)
from review_risk131 import metrics


def main():
    """
    機能: 公開候補の全86商品場と方向別集計を照合し、未解決点付きの独立意見を保存する。
    引数: なし。
    返り値: None。金融判断を再生せず、既存公開候補も変更しない。
    """
    CHECKS.clear()
    cp = WORK / "公開結論.json"
    sp = WORK / "公開候補の43場統合.json"
    rp = HERE / "第四巡の赤字規模と失う利益の独立比較_1792505422642686900.json"
    conclusion, selected, risk = read(cp), read(sp), read(rp)
    check("数量対照監査合格", risk["passed"])
    check("結論選択と集約一致", selected["selection"] == conclusion["defaults"])
    dp = HERE / "round3_候補比較と追加寄与の独立再集計_1792504230554973500.json"
    previous = read(dp)
    direction = {(r["session"], r["symbol"]): r["direction"] for r in previous["direction_endpoints"]}
    datasets = {}
    expected = []
    for kind in ("Day", "Night"):
        for symbol in ("TOPIX", "NK225"):
            folder, method = selected["selection"][kind][symbol].split("::")
            if folder not in datasets:
                datasets[folder] = read(WORK / folder / "全条件の会計.json")
            rows = [dict(r, selected_round=folder) for r in datasets[folder]["rows"]
                    if (r["method"], r["kind"], r["symbol"]) == (method, kind, symbol)]
            check(kind + symbol + "/件数", len(rows) == (22 if kind == "Day" else 21))
            expected += rows
    check("全86行を元会計から再構成", selected["rows"] == expected and len(expected) == 86)
    summaries = {}
    for symbol in ("TOPIX", "NK225"):
        full = sorted([r for r in expected if r["symbol"] == symbol], key=lambda r: r["session"])
        check(symbol + "/全場参加", len(full) == 43 and all(r["entries"] > 0 for r in full))
        summaries[symbol] = {}
        for kind, rows in (("全体", full),
                           ("日中", [r for r in full if r["kind"] == "Day"]),
                           ("夜間", [r for r in full if r["kind"] == "Night"])):
            stored = selected["summary"][symbol][kind]
            measured = metrics(rows)
            equal_stats(symbol + kind, measured, stored)
            for section, labels in (("components", ("旧核", "追加")),
                                    ("directions", ("上昇", "下落", "同値")),
                                    ("halves", ("前半", "後半"))):
                measured[section] = {}
                for label in labels:
                    if section == "components":
                        subset = [r["components"][label] for r in rows]
                    elif section == "directions":
                        subset = [r for r in rows if direction[r["session"], symbol] == label]
                    else:
                        half = len(rows) // 2
                        subset = rows[:half] if label == "前半" else rows[half:]
                    m = metrics(subset)
                    equal_stats(symbol + kind + section + label, m, stored[section][label])
                    measured[section][label] = m
            measured["sides"] = {}
            for side in ("買い", "売り"):
                m = dict(entries=sum(r["direction"][side]["entries"] for r in rows),
                         net=sum(r["direction"][side]["net"] for r in rows))
                check(symbol + kind + side, m == stored["sides"][side])
                measured["sides"][side] = m
            check(symbol + kind + "/黒赤無取引同値", sum(measured[k] for k in
                  ("black", "red", "empty", "breakeven")) == len(rows))
            summaries[symbol][kind] = measured
    for ref in selected["sources"]:
        check("選定入力指紋/" + ref["path"], reference(ROOT / ref["path"]) == ref)
    check("結論指紋", selected["decision"] == reference(cp))
    alternatives = [r for r in risk["summary"] if r["kind"] == "Night" and
                    ((r["symbol"] == "NK225" and r["method"] in ("U05", "U06", "U07", "U08")) or
                     (r["symbol"] == "TOPIX" and r["method"] in ("U01", "U05", "U06")))]
    stamp = time.time_ns()
    target = HERE / f"公開候補86行と最新価値観の独立レビュー_{stamp}.json"
    result = dict(passed=True, financial_replays=0, check_count=len(CHECKS), checks=CHECKS,
        sources=[reference(p) for p in (cp, sp, rp, dp, WORK / "第四巡前の評価補足.json", Path(__file__))],
        selection=selected["selection"], summary=summaries, alternatives=alternatives,
        opinion="日中T06・夜間TOPIX T04・日経U06をバランス候補として支持。U05は損失軽量化の別案として保持。",
        limitations=["既知43場からの開発選択。未来の優位性や安定運用の証明ではない。",
                     "数量変更は予測・入口・出口の改善ではなく、同じ経路の円リスク調整。",
                     "上昇場・夜間後半の大勝ち依存は解消していない。",
                     "U06の減枚効果は20追加親中4親、うち2敗の縮小が改善源。"])
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = HERE / f"第四巡後の比較候補への独立意見_{stamp}.md"
    md.write_text("""# 第四巡後の独立意見

**日中T06、夜間TOPIX T04・日経U06を、今回の比較候補として支持する。** 大勝ちを消す目的ではなく、黒字場数、負け場の平均・中央値、上位3黒字を除いた収支、失う勝ちの釣合いからの判断。日付ごとの後付け選択ではないが、パラメータ選択自体は既知43場を見た後であり、未知検証ではない。

| 夜間日経 | 黒／赤 | 収支 | 赤字平均 | 赤字中央値 | 最大赤字 | 上位3黒字除外 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T05 固定10枚 | 15／6 | ＋88,640円 | 11,663円 | 8,720円 | 28,220円 | ＋27,400円 |
| U05 8呼値予算 | 14／7 | ＋109,352円 | 6,341円 | 5,644円 | 15,518円 | ＋33,436円 |
| **U06 12呼値予算** | **15／6** | **＋112,692円** | **8,841円** | **8,720円** | **16,440円** | **＋39,842円** |
| U07 16呼値予算 | 15／6 | ＋108,160円 | 9,312円 | 8,720円 | 16,440円 | ＋39,954円 |

U06はT05の追加20親中4親だけを減枚した。10月1日と16日の勝ちを合計4,490円削る一方、14日と15日の負けを28,542円縮め、純改善24,052円。勝ち親を選んで残したのではなく、当時の初期停止幅が広い親を機械的に減枚した。追加単独も＋26,600→＋50,652円、上位3追加黒字除外−21,740→＋3,690円。入口・出口の時刻と価格はすべて同一で、予測力が上がった結果ではない。中央値8,720円は変わらず、「典型的な全敗を一律に軽くした」のではなく、一部の大きい負けを縮めた改善である。

U05も価値のある対照である。平均・中央値はさらに軽く、追加赤字1場は10月5日の＋560→−396円という小額。これだけを理由に劣ると断定しない。ただし追加20親中16親を減枚し、失う勝ち22,006円がU06より大きい。大勝ちを保持しつつ赤字場数も維持するバランスとしてU06を優先する。U07の上位3除外はU06より112円多いが、平均赤字が約470円大きく、収支は4,532円少ない。112円だけで選び替える根拠は弱い。

TOPIX T04に対応するU01〜04は、追加3親とも5枚のままで全注文・損益が同じだった。見かけ上4条件で再確認できても、新たな優位性の4件の証拠には数えない。別入口のU05は平均損失が軽くなるが、夜間黒18→16・赤3→5、最大赤字53,754→74,172円、上位3除外57,444→52,850円となる。累計だけは増えるが、今回の優先度ならT04を維持する方が説明しやすい。

日中のU系は赤字場数・赤字平均・中央値を改善せず、T06の収支を上回らない。両商品とも日中T06を維持する。

## 残る弱点

- 全体はTOPIX＋787,561円・33黒10赤、日経＋386,612円・31黒12赤、全場参加。上位3黒字を除いても＋486,484円・＋221,012円。昼夜別も各々除外後黒字であり、特定の3場だけで全損失を補っているわけではない。
- ただしTOPIX上昇22場は除外後−72,386円。日経夜間の上昇10場も＋16,594円、除外後−31,268円で、方向の偏りは残る。
- 夜間後半11場の除外後はTOPIX−60,024円・日経−17,148円。全体の除外後黒字から、すべての期間・方向が安定とは一般化できない。
- TOPIX夜間は赤字3場と少ないが、平均黒字23,006円に対し平均赤字49,448円。負けの大きさはまだ課題。日経U06夜間は平均黒字11,049円が平均赤字8,841円を上回るが、将来も同様とは確定していない。

このため結論は「両銘柄で全場参加し、大勝ち依存を抑えた、既知資料内のベター候補」。完成や普遍的な最適手法としない。独立監査は新金融再生0回で、元会計・売買源・公開選択を変更していない。
""", encoding="utf-8")
    print(target.relative_to(ROOT), len(CHECKS), "合格", flush=True)
    print(md.relative_to(ROOT), flush=True)
    for symbol, parts in summaries.items():
        print(symbol, {kind: {k: v[k] for k in
              ("net", "black", "red", "mean_loss", "median_loss", "without_top3")}
              for kind, v in parts.items()}, flush=True)


if __name__ == "__main__":
    main()
