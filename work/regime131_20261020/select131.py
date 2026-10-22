"""商品と昼夜ごとに固定した比較候補を、同じ43場の一つの表へ接続する。"""

import argparse
import pickle
import numpy as np
from common131 import HERE, ROOT, BASE, read, reference, save
from analyze131 import statistics


def main():
    """
    機能: 明示した四つの候補を日付別の後付け変更なしで合成し、偏りを集計する。
    引数: --conclusion(str)はdefaultsを含む結論JSON、--output(str)は新保存先。
    返り値: None。金融再生なし。既知資料で選んだ比較候補であり、未知検証ではない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--conclusion", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    selection = read(HERE/args.conclusion)["defaults"]
    datasets, references = {}, []
    rows = []
    for kind in ("Day", "Night"):
        for symbol in ("TOPIX", "NK225"):
            folder, method = selection[kind][symbol].split("::")
            if folder not in datasets:
                path = HERE/folder/"全条件の会計.json"
                datasets[folder] = read(path)
                references.append(reference(path))
            part = [dict(r, selected_round=folder) for r in datasets[folder]["rows"]
                    if r["method"] == method and r["kind"] == kind and r["symbol"] == symbol]
            assert len(part) == (22 if kind == "Day" else 21)
            assert all(r["entries"] > 0 for r in part)
            rows.extend(part)
    directions = {}
    for ref in read(BASE/"入力準備.json")["packets"]:
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        for key, ready in packet["inputs"].items():
            prices = ready["last"][np.isfinite(ready["last"])]
            directions[key] = "上昇" if prices[-1] > prices[0] else ("下落" if prices[-1] < prices[0] else "同値")
    summary = {}
    for symbol in ("TOPIX", "NK225"):
        part = sorted([r for r in rows if r["symbol"] == symbol], key=lambda r:r["session"])
        details = {}
        for name, segment in (("全体",part),("日中",[r for r in part if r["kind"]=="Day"]),
                              ("夜間",[r for r in part if r["kind"]=="Night"])):
            components = {label:statistics([r["components"][label] for r in segment])
                          for label in ("旧核","追加")}
            directions_stats = {d:statistics([r for r in segment if directions[r["session"],symbol]==d])
                                for d in ("上昇","下落","同値")}
            middle = len(segment)//2
            sides = {side:dict(entries=sum(r["direction"][side]["entries"] for r in segment),
                        net=sum(r["direction"][side]["net"] for r in segment)) for side in ("買い","売り")}
            details[name] = dict(**statistics(segment), components=components,
                directions=directions_stats, sides=sides,
                halves={"前半":statistics(segment[:middle]),"後半":statistics(segment[middle:])})
        summary[symbol] = details
        print(symbol, {k:{f:v[f] for f in ("net","black","red","worst","without_top3")}
                       for k,v in details.items()},flush=True)
    save(HERE/args.output,dict(passed=True, selection=selection, rows=rows, summary=summary,
        sources=references, decision=reference(HERE/args.conclusion), financial_replays=0,
        note="商品・昼夜ごとの固定候補。個別日付や将来の上昇下落で切替しない。選択自体は既知資料内。"))


if __name__ == "__main__":
    main()
