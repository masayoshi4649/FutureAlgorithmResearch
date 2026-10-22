"""保存会計の候補比較を、入口選別・昼夜合算・大勝ち依存の観点から独立再集計する。"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import pickle
import statistics
import time

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
BASE = ROOT / "work/daynight128_20261020"
CHECKS = []


def read(path):
    """
    機能: 読み取り専用で日本語JSONを読み込む。
    引数: path(Path)は保存資料。
    返り値: dict又はlistは復元資料。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path):
    """
    機能: 参照した保存資料を指紋で識別する。
    引数: path(Path)は保存資料。
    返り値: dict[str,str]は相対位置と指紋。
    """
    return dict(path=path.relative_to(ROOT).as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def check(label, truth):
    """
    機能: 検算条件を記録し、不一致時に停止する。
    引数: label(str)、truth(bool)は条件と成否。
    返り値: None。
    """
    assert bool(truth), label
    CHECKS.append(label)


def stats(rows):
    """
    機能: 親別損益を集約した商品場を、独立の標準ライブラリ計算で集計する。
    引数: rows(list[dict])は同一商品・条件の保存商品場。
    返り値: dictは全場・無取引・同値を分けた記述統計。
    """
    ns = [float(r["net"]) for r in rows]
    positive = [n for n in ns if n > 0]
    negative = [n for n in ns if n < 0]
    p = sum(r["profit"] for r in rows)
    l = sum(r["loss"] for r in rows)
    mean_black = statistics.mean(positive) if positive else 0.
    worst = min(ns, default=0.)
    return dict(sessions=len(rows), net=sum(ns), profit=p, loss=l,
                black=len(positive), red=len(negative),
                empty=sum(r["entries"] == 0 for r in rows),
                breakeven=sum(r["entries"] > 0 and r["net"] == 0 for r in rows),
                entries=sum(r["entries"] for r in rows),
                mean=statistics.mean(ns) if ns else 0.,
                median=statistics.median(ns) if ns else 0., worst=worst,
                mean_black=mean_black,
                mean_red=-statistics.mean(negative) if negative else 0.,
                without_top3=sum(ns) - sum(sorted(positive, reverse=True)[:3]),
                profit_share=p / (p + l) if p + l else None,
                worst_to_mean_black=(-min(worst, 0.) / mean_black
                                     if mean_black else None))


def equal_stats(label, measured, expected):
    """
    機能: 公開集計の各数値を独立再集計値と照合する。
    引数: label(str)、measured/expected(dict)は検査名と比較値。
    返り値: None。
    """
    for k in ("sessions", "net", "profit", "loss", "black", "red", "empty",
              "entries", "mean", "median", "worst", "mean_black", "mean_red",
              "without_top3", "profit_share"):
        a, b = measured[k], expected[k]
        check(label + "/" + k, (a is None and b is None) or
              (a is not None and b is not None and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-7)))


def directions():
    """
    機能: 全43場の最初・最後の有限Lastから、事後採点専用の方向を独立に作る。
    引数: なし。
    返り値: tuple[dict,list]は商品場方向と指紋付き両端値。
            この値を売買判断へ渡すことはない。
    """
    result, refs = {}, []
    for item in read(BASE / "入力準備.json")["packets"]:
        path = ROOT / item["path"]
        ref = reference(path)
        check("入力指紋/" + item["session"], ref["sha256"] == item["sha256"])
        packet = pickle.loads(path.read_bytes())
        for key, ready in packet["inputs"].items():
            values = ready["last"]
            indices = np.flatnonzero(np.isfinite(values))
            first, last = float(values[indices[0]]), float(values[indices[-1]])
            label = "上昇" if last > first else ("下落" if last < first else "同値")
            result[key] = label
            refs.append(dict(session=key[0], symbol=key[1], first=first, last=last,
                             first_row=int(indices[0]), last_row=int(indices[-1]),
                             direction=label, source=ref))
        del packet
    return result, refs


def main():
    """
    機能: 指定巡の全比較を独立再集計し、旧核・追加・方向・前後半の弱点を保存する。
    引数: --round(str)は完了通知を受けた保存巡。
    返り値: None。金融再生・旧源変更は行わず新証拠のみ保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = WORK / args.round
    account = read(folder / "全条件の会計.json")
    published = read(folder / "区分別の比較.json")
    components = read(folder / "旧核と追加の寄与.json")
    direction, direction_refs = directions()
    rows = account["rows"]
    check("商品場一意", len(rows) == len({(r["method"], r["session"], r["symbol"]) for r in rows}))
    for r in rows:
        tag = r["method"] + "/" + r["symbol"] + "/" + r["session"]
        for k in ("net", "profit", "loss", "gross", "fees", "entries"):
            check(tag + "/独立部品合計/" + k,
                  abs(r[k] - sum(p[k] for p in r["components"].values())) < 1e-7)
        check(tag + "/親利益損失", abs(r["profit"] - r["loss"] - r["net"]) < 1e-7)
        check(tag + "/粗と費用", abs(r["gross"] - r["fees"] - r["net"]) < 1e-7)
        check(tag + "/全場参加", r["entries"] > 0)
        check(tag + "/追加最大一親", r["components"]["追加"]["entries"] in (0, 1))
        cap = 10 if r["symbol"] == "TOPIX" else 20
        check(tag + "/両側上限", r["max_long"] <= cap and r["max_short"] <= cap)
    summaries = []
    for p in published["summary"]:
        method, symbol = p["method"], p["symbol"]
        chosen = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
        tag = method + "/" + symbol
        check(tag + "/全43場", len(chosen) == 43)
        s = dict(method=method, symbol=symbol, **stats(chosen))
        equal_stats(tag, s, p)
        for key, groups in (
            ("daynight", {k: [r for r in chosen if r["kind"] == k] for k in ("Day", "Night")}),
            ("directions", {k: [r for r in chosen if direction[r["session"], symbol] == k]
                            for k in ("上昇", "下落", "同値")}),
        ):
            s[key] = {k: stats(rs) for k, rs in groups.items()}
            for k, st in s[key].items():
                equal_stats(tag + "/" + key + "/" + k, st, p[key][k])
        ordered = sorted(chosen, key=lambda r: r["session"])
        middle = len(ordered) // 2
        s["halves"] = {"前半": stats(ordered[:middle]), "後半": stats(ordered[middle:])}
        for k, st in s["halves"].items():
            equal_stats(tag + "/halves/" + k, st, p["halves"][k])
        s["buy_sell"] = {}
        for side in ("買い", "売り"):
            q = dict(entries=sum(r["direction"][side]["entries"] for r in chosen),
                     net=sum(r["direction"][side]["net"] for r in chosen))
            check(tag + "/" + side, q == p["buy_sell"][side])
            s["buy_sell"][side] = q
        s["components"] = {}
        for kind in ("全体", "Day", "Night"):
            selected = [r for r in chosen if kind == "全体" or r["kind"] == kind]
            c = next(c for c in components["summary"]
                     if c["method"] == method and c["symbol"] == symbol and c["kind"] == kind)
            equal_stats(tag + "/合算/" + kind, stats(selected), c["combined"])
            detail = {}
            for component in ("旧核", "追加"):
                simple = [r["components"][component] for r in selected]
                detail[component] = stats(simple)
                equal_stats(tag + "/" + component + "/" + kind, detail[component],
                            c["components"][component])
            new_red = [r["session"] for r in selected
                       if r["components"]["旧核"]["net"] >= 0 > r["net"]]
            new_black = [r["session"] for r in selected
                         if r["components"]["旧核"]["net"] <= 0 < r["net"]]
            check(tag + "/" + kind + "/赤字化", new_red == c["newly_red"])
            check(tag + "/" + kind + "/黒字化", new_black == c["newly_black"])
            detail["newly_red"] = new_red
            detail["newly_black"] = new_black
            detail["worst_added_sessions"] = sorted([
                dict(session=r["session"], original=r["components"]["旧核"]["net"],
                     extra=r["components"]["追加"]["net"], total=r["net"])
                for r in selected if r["components"]["追加"]["entries"]],
                key=lambda r: r["extra"])[:3]
            s["components"][kind] = detail
        summaries.append(s)
    # ----------------------------------------
    # 第三巡は入口を動かさず、追加出口の差だけを第二巡の対応元と比較する。
    changes = []
    if args.round == "round3":
        previous = read(WORK / "round2/全条件の会計.json")
        lookup = {(r["method"], r["symbol"], r["session"]): r for r in previous["rows"]}
        for config in account["configs"]:
            base = "S03" if config["style"] == 0 else "S07"
            for symbol in ("TOPIX", "NK225"):
                selected = [r for r in rows if r["method"] == config["id"] and r["symbol"] == symbol]
                delta = []
                for row in selected:
                    old = lookup[base, symbol, row["session"]]
                    check(config["id"] + "/" + symbol + "/" + row["session"] + "/旧核不変",
                          row["components"]["旧核"] == old["components"]["旧核"])
                    check(config["id"] + "/" + symbol + "/" + row["session"] + "/参加数不変",
                          row["components"]["追加"]["entries"] == old["components"]["追加"]["entries"])
                    delta.append(dict(session=row["session"], before=old["net"], after=row["net"],
                                      delta=row["net"] - old["net"]))
                changes.append(dict(method=config["id"], symbol=symbol, comparison=base,
                                    total_change=sum(d["delta"] for d in delta),
                                    improved=sum(d["delta"] > 0 for d in delta),
                                    worsened=sum(d["delta"] < 0 for d in delta),
                                    newly_red=sum(d["before"] >= 0 > d["after"] for d in delta),
                                    newly_black=sum(d["before"] <= 0 < d["after"] for d in delta),
                                    losses=sorted(delta, key=lambda d: d["delta"])[:3],
                                    gains=sorted(delta, key=lambda d: -d["delta"])[:3],
                                    all_sessions=delta))
    sources = [reference(folder / n) for n in
               ("全条件の会計.json", "区分別の比較.json", "旧核と追加の寄与.json", "固定計画.json")]
    sources.append(reference(WORK / "第二巡の選定方針.json"))
    target = HERE / f"{args.round}_候補比較と追加寄与の独立再集計_{time.time_ns()}.json"
    result = dict(passed=True, check_count=len(CHECKS), checks=CHECKS,
                  financial_replays=0, input_use="Last両端は事後採点専用。新金融判断なし。",
                  sources=sources, summaries=summaries, changes=changes, direction_endpoints=direction_refs,
                  limitations=[
                      "全43場は既知開発資料であり、前後半も独立した未知テストではない。",
                      "全場参加は必要条件だが、赤字・最大赤字・上昇下落・追加寄与の安定を保証しない。",
                      "上位3除外は感度分析。最適条件を選んだ不確実性や多重比較は解消しない。",
                      "追加を含む片方向上限10/20と旧5/10を同一リスクとして単純比較しない。"],
                  audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.relative_to(ROOT), len(CHECKS), "合格", flush=True)
    for s in summaries:
        print(s["method"], s["symbol"], int(s["net"]), "赤", s["red"],
              "最悪", int(s["worst"]), "大勝ち除外", int(s["without_top3"]), flush=True)


if __name__ == "__main__":
    main()
