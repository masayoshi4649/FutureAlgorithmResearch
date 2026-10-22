"""参加・方向偏り・大勝ち依存を、保存済み会計から再集計する。"""

import argparse
import pickle
import numpy as np
from common131 import HERE, ROOT, BASE, read, reference, save


def statistics(rows):
    """
    機能: 全場と活動場を区別し、典型利益と大きな負けを計算する。
    引数: rows(list[dict])は保存商品場。
    返り値: dictは再集計値。無取引を勝ちに数えない。
    """
    net = np.array([r["net"] for r in rows])
    black, red = net[net > 0.], net[net < 0.]
    positive, negative = sum(r["profit"] for r in rows), sum(r["loss"] for r in rows)
    return dict(sessions=len(rows), net=float(net.sum()), profit=positive, loss=negative,
        black=len(black), red=len(red), empty=sum(r["entries"] == 0 for r in rows),
        entries=sum(r["entries"] for r in rows), mean=float(net.mean()) if len(net) else 0.,
        median=float(np.median(net)) if len(net) else 0., worst=float(min(net,default=0.)),
        mean_black=float(black.mean()) if len(black) else 0.,
        mean_red=float(-red.mean()) if len(red) else 0.,
        without_top3=float(net.sum()-np.sort(black)[-3:].sum()),
        profit_share=positive/(positive+negative) if positive+negative else None)


def main():
    """
    機能: 全商品場を方向・前後半・時計別にまとめる。
    引数: --round(str)は完了した金融フォルダ。
    返り値: None。金融核を再実行せず新規資料を保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = HERE / args.round
    account = read(folder / "全条件の会計.json")
    rows = account["rows"]
    directions = {}
    for ref in read(BASE / "入力準備.json")["packets"]:
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        for key, ready in packet["inputs"].items():
            valid = np.isfinite(ready["last"])
            p = ready["last"][valid]
            directions[key] = "上昇" if p[-1] > p[0] else ("下落" if p[-1] < p[0] else "同値")
    summaries = []
    for config in account["configs"]:
        for symbol in ("TOPIX","NK225"):
            selected = [r for r in rows if r["method"] == config["id"] and r["symbol"] == symbol]
            result = dict(method=config["id"],name=config["name"],symbol=symbol,
                          **statistics(selected))
            result["daynight"] = {kind: statistics([r for r in selected if r["kind"] == kind])
                                  for kind in ("Day","Night")}
            result["directions"] = {d: statistics([r for r in selected
                if directions[r["session"],symbol] == d]) for d in ("上昇","下落","同値")}
            ordered = sorted(selected,key=lambda r:r["session"])
            middle = len(ordered)//2
            result["halves"] = {"前半":statistics(ordered[:middle]),"後半":statistics(ordered[middle:])}
            result["entry_phases"] = {name: dict(
                entries=sum(r["phases"][name]["entries"] for r in selected),
                net=sum(r["phases"][name]["net"] for r in selected))
                for name in selected[0]["phases"]}
            result["phase_equity_changes"] = {name:sum(r["phase_equity_changes"][name] for r in selected)
                                              for name in selected[0]["phase_equity_changes"]}
            result["buy_sell"] = {side:dict(entries=sum(r["direction"][side]["entries"] for r in selected),
                net=sum(r["direction"][side]["net"] for r in selected)) for side in ("買い","売り")}
            result["worst_sessions"] = sorted(selected,key=lambda r:r["net"])[:3]
            summaries.append(result)
            print(config["id"],symbol,int(result["net"]),
                  "黒赤休",result["black"],result["red"],result["empty"],
                  "最悪",int(result["worst"]),"上位3除外",int(result["without_top3"]),flush=True)
    save(folder / "区分別の比較.json",dict(passed=True,summary=summaries,rows=rows,
        source=reference(folder / "全条件の会計.json"),financial_replays=0,
        note="上昇下落は事後採点。全43場は既知の開発資料。"))


if __name__ == "__main__":
    main()
