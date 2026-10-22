"""商品と昼夜の固定選択が保存値に一致するか、方向・追加損失の弱点を含めて確認する。"""

import json
from pathlib import Path
import time

from review_portfolio_comparison131 import (
    WORK, ROOT, HERE, CHECKS, read, reference, check, stats, equal_stats,
)


def main():
    """
    機能: 選定86商品場を原会計から独立構成し、公開統計と既知資料内の限界を点検する。
    引数: なし。
    返り値: None。源や公開文を変更せず、証拠と短い敵対レビューを新規保存する。
    """
    CHECKS.clear()
    selected_path = WORK / "比較候補の43場統合.json"
    conclusion_path = WORK / "結論.json"
    selected, conclusion = read(selected_path), read(conclusion_path)
    comparison_path = HERE / "round3_候補比較と追加寄与の独立再集計_1792504230554973500.json"
    previous_proof = read(comparison_path)
    check("第三巡独立再集計を確認", previous_proof["passed"])
    direction = {(r["session"], r["symbol"]): r["direction"]
                 for r in previous_proof["direction_endpoints"]}
    check("選定指定一致", selected["selection"] == conclusion["defaults"])
    datasets = {n: read(WORK / n / "全条件の会計.json") for n in ("round1_final", "round2", "round3")}
    expected = []
    for kind in ("Day", "Night"):
        for symbol in ("TOPIX", "NK225"):
            folder, method = selected["selection"][kind][symbol].split("::")
            subset = [dict(r, selected_round=folder) for r in datasets[folder]["rows"]
                      if (r["method"], r["kind"], r["symbol"]) == (method, kind, symbol)]
            check(kind + symbol + "/場数", len(subset) == (22 if kind == "Day" else 21))
            expected.extend(subset)
    check("選定86行と元会計完全一致", selected["rows"] == expected and len(expected) == 86)
    summaries, rankings = {}, []
    for symbol in ("TOPIX", "NK225"):
        full = sorted([r for r in expected if r["symbol"] == symbol], key=lambda r: r["session"])
        check(symbol + "/全43場参加", len(full) == 43 and all(r["entries"] > 0 for r in full))
        summaries[symbol] = {}
        for name, segment in (("全体", full),
                              ("日中", [r for r in full if r["kind"] == "Day"]),
                              ("夜間", [r for r in full if r["kind"] == "Night"])):
            stored = selected["summary"][symbol][name]
            measured = stats(segment)
            equal_stats(symbol + name, measured, stored)
            measured["components"] = {}
            for component in ("旧核", "追加"):
                value = stats([r["components"][component] for r in segment])
                equal_stats(symbol + name + component, value, stored["components"][component])
                measured["components"][component] = value
            measured["directions"] = {}
            for label in ("上昇", "下落", "同値"):
                value = stats([r for r in segment if direction[r["session"], symbol] == label])
                equal_stats(symbol + name + label, value, stored["directions"][label])
                measured["directions"][label] = value
            middle = len(segment) // 2
            measured["halves"] = {}
            for half, rs in (("前半", segment[:middle]), ("後半", segment[middle:])):
                value = stats(rs)
                equal_stats(symbol + name + half, value, stored["halves"][half])
                measured["halves"][half] = value
            measured["sides"] = {}
            for side in ("買い", "売り"):
                value = dict(entries=sum(r["direction"][side]["entries"] for r in segment),
                             net=sum(r["direction"][side]["net"] for r in segment))
                check(symbol + name + side, value == stored["sides"][side])
                measured["sides"][side] = value
            measured["newly_red"] = [r["session"] for r in segment
                                     if r["components"]["旧核"]["net"] >= 0 > r["net"]]
            measured["newly_black"] = [r["session"] for r in segment
                                       if r["components"]["旧核"]["net"] <= 0 < r["net"]]
            summaries[symbol][name] = measured
        # ----------------------------------------
        # 事前に指定された二つの最優先尺度に、選定が整合するかを全28条件で確かめる。
        for kind in ("Day", "Night"):
            candidates = []
            for folder, data in datasets.items():
                for config in data["configs"]:
                    rs = [r for r in data["rows"]
                          if (r["method"], r["kind"], r["symbol"]) == (config["id"], kind, symbol)]
                    st = stats(rs)
                    if st["empty"]:
                        continue
                    ratio = st["worst_to_mean_black"]
                    candidates.append(dict(key=folder + "::" + config["id"], **st,
                                           order=(st["red"], ratio if ratio is not None else float("inf"))))
            ordered = sorted(candidates, key=lambda c: c["order"])
            chosen = next(c for c in candidates if c["key"] == selected["selection"][kind][symbol])
            check(symbol + kind + "/赤字数と最悪対平均黒字で整合", chosen["order"] == ordered[0]["order"])
            rankings.append(dict(symbol=symbol, kind=kind, selected=chosen["key"],
                                 policy="赤字場数、最大赤字÷平均黒字の二優先尺度を照合。合計利益で順位を付けていない。",
                                 candidates=ordered))
    stamp = time.time_ns()
    target = HERE / f"選定86行と残存偏りの独立レビュー_{stamp}.json"
    proof = dict(passed=True, check_count=len(CHECKS), checks=CHECKS, financial_replays=0,
                 selected_summary=summaries, ranking_checks=rankings,
                 sources=[reference(p) for p in (selected_path, conclusion_path, comparison_path,
                                                 WORK / "第二巡の選定方針.json", Path(__file__))],
                 selection_scope="商品・昼夜のみの固定選択。日付・終値方向ごとの選択はない。",
                 limitation="選択自体は全43既知場の結果を用いる。順位の整合は将来優位性の証明ではない。")
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = HERE / f"選定候補の敵対レビュー_{stamp}.md"
    report.write_text("""# 比較候補の評価：改善は確認、共通の安定性は未完成

全28新条件の比較から、日中T06、夜間TOPIX T04・日経T05を選ぶことは、「赤字場数→最大赤字と平均黒字の釣合い」という事前の優先順位と整合する。各商品43場すべて参加し、選定86行は元会計と完全一致した。終値方向や個別日付で手法を選んでいない。ただし、この選定自体は既知43場の結果を見た後の選択である。

| 商品・区分 | 収支 | 黒／赤 | 最悪場 | 上位3黒字除外 |
| --- | ---: | ---: | ---: | ---: |
| TOPIX・日中 | ＋521,797円 | 15／7 | −79,172円 | ＋245,301円 |
| TOPIX・夜間 | ＋265,764円 | 18／3 | −53,754円 | ＋57,444円 |
| 日経・日中 | ＋273,920円 | 16／6 | −25,100円 | ＋108,320円 |
| 日経・夜間 | ＋88,640円 | 15／6 | −28,220円 | ＋27,400円 |

合算はTOPIX＋787,561円・33黒10赤、日経＋362,560円・31黒12赤。全体の前後半もそれぞれ黒字で、上位3黒字を除いても黒字。これは以前より良い比較候補を得た根拠だが、次の弱点は残る。

1. **上昇場への弱さはTOPIXだけではない。** TOPIX上昇22場は＋172,446円でも上位3黒字除外−72,386円。特に日中上昇12場は＋94,560円、同除外−150,272円。日経夜間も上昇10場＋1,040円・赤4場・同除外−48,200円に対し、下落9場＋78,260円・赤1場。買い／売り双方の累計黒字や上下対称実装だけで、方向への偏りが解消したとは呼べない。
2. **追加単独の安定性は、合算より弱い。** TOPIXの追加は日中2親−836円、夜間3親＋8,746円。日経は日中4親＋13,120円、夜間20親＋26,600円。日経夜間は旧S07追加−43,400円から改善したが、上位3追加黒字を除くと−21,740円。全体側の上位3除外黒字を、追加手法単独の証明へ転用しない。追加単独に無取引があるのは役割上自然で、合算全場参加と分ける。
3. **参加を増やした分の新たな赤字もある。** TOPIX日中は旧2無取引を1黒字・1赤字へ変え、赤字6→7場、収支−836円。日経夜間は旧8無取引を解消する一方、赤字4→6場、最悪−8,220→−28,220円。9月21日・10月15日・10月19日の夜間は旧非赤字から合算赤字へ変わった。全場参加の達成を、全損失尺度の改善と同義にしない。
4. **大勝ち依存を十分に取り除けたわけではない。** 夜間後半11場の上位3黒字除外はTOPIX−60,024円・日経−34,080円。TOPIX日中後半は−28,850円、日経日中前半は−7,460円。区分全体で正でも、より短い範囲で同じ安定性は確認できない。
5. **大きい負けは残る。** 夜間の最大赤字は平均黒字に対しTOPIX約2.34倍、日経約2.67倍。以前の固定合否基準を復活させる意味ではないが、損小利大の弱点として表示する。TOPIX夜間平均黒字23,006円に対し平均赤字49,448円、日経10,575円に対し11,663円で、場の勝率だけでは負けの大きさを説明できない。

結論は「全場参加という新条件を満たし、今回の既知資料では相対的に良い候補」。日中も夜間も完成とはしない。TOPIXの追加は5親しかなく、出口4設定や時刻を同じ資料で比べた選択誤差が大きい。前後半・上位3除外は感度分析であり、未知期間のバックテストにはならない。ニュースの理由付けは市場時計の根拠であって、個々の利益の因果を証明するものではない。

保存会計・出典指紋・全数値の独立証拠は、同時刻のJSONを参照。金融再生0回、旧源・既存会計は変更していない。
""", encoding="utf-8")
    print(target.relative_to(ROOT), len(CHECKS), "合格", flush=True)
    print(report.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
