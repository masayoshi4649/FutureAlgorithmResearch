"""追加担当を元の利益に埋めず、参加回復と赤字増減を分ける。"""

import argparse
from common131 import HERE, read, reference, save
from analyze131 import statistics


def main():
    """
    機能: 旧核と追加の単独成績、黒字化・赤字化した場を再集計する。
    引数: --round(str)は合算の保存会計があるフォルダ。
    返り値: None。注文の再実行はせず、追加担当の全活動場を保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = HERE/args.round
    account = read(folder/"全条件の会計.json")
    result = []
    for config in account["configs"]:
        for symbol in ("TOPIX", "NK225"):
            rows = [r for r in account["rows"] if r["method"] == config["id"] and r["symbol"] == symbol]
            for kind in ("全体", "Day", "Night"):
                selected = [r for r in rows if kind == "全体" or r["kind"] == kind]
                components = {}
                for component in ("旧核", "追加"):
                    simple = [dict(session=r["session"], **r["components"][component]) for r in selected]
                    components[component] = statistics(simple)
                improved = [r["session"] for r in selected if r["components"]["旧核"]["net"] <= 0 < r["net"]]
                worsened = [r["session"] for r in selected if r["components"]["旧核"]["net"] >= 0 > r["net"]]
                activity = [r for r in selected if r["components"]["追加"]["entries"]]
                result.append(dict(method=config["id"], symbol=symbol, kind=kind,
                    combined=statistics(selected), components=components,
                    maximum_long=max(r["max_long"] for r in selected),
                    maximum_short=max(r["max_short"] for r in selected),
                    newly_black=improved, newly_red=worsened,
                    previously_empty=sum(r["components"]["旧核"]["entries"] == 0 for r in selected),
                    extra_sessions=[dict(session=r["session"], original=r["components"]["旧核"]["net"],
                        extra=r["components"]["追加"]["net"], net=r["net"]) for r in activity]))
                if kind != "全体":
                    print(config["id"],symbol,kind,
                        "合算",round(sum(r["net"] for r in selected)),
                        "赤",sum(r["net"]<0 for r in selected),
                        "追加",round(components["追加"]["net"]),
                        "追加場",len(activity),"休",sum(r["entries"]==0 for r in selected),flush=True)
    save(folder/"旧核と追加の寄与.json",dict(passed=True, summary=result,
         source=reference(folder/"全条件の会計.json"), financial_replays=0))


if __name__ == "__main__":
    main()
