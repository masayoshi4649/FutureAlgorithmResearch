"""出口改修の具体差を四例だけ描く。保存金融結果は変更しない。"""

import pickle
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

from render_entry130 import PUBLIC
from diagnose_entry130 import HERE, ROOT, OLD, PREV, read, save
sys.path.insert(0, str(PREV))
import features129

IMAGES = PUBLIC / "画像/第一巡差分"


def render(account: dict, parent: int, packet: dict, cut: bool) -> str:
    """
    機能: 同じ親の旧新出口と、早期返済後に新しく発生した入口を描く。
    引数: account(dict)、parent(int)、packet(dict)、cut(bool)は比較・対象親・原入力・判断切断。
    返り値: strは公開域内の図の相対位置。
    """
    scene, symbol, method = account["session"], account["symbol"], account["method"]
    pair = next(p for p in account["pairs"] if p["new"] and p["new"]["parent"] == parent)
    new, old = pair["new"], pair["old"]
    kind = "last" if account["base"] == "NV01" else "mid"
    inputs, markets, _, _ = features129.build(packet, kind)
    rd = packet["inputs"][scene, symbol]
    q = packet["quotes"][scene, symbol]
    ts, m = rd["time_s"], markets[scene, symbol]
    decision = new["exits"][0]["decision_row"]
    changed = next((e for e in new["exits"] if e["reason"] == 76), new["exits"][0])
    decision = changed["decision_row"]
    focus = ts[decision]
    left = ts[new["entry_row"]] - 300.
    end = max(ts[new["exit_row"]], ts[old["exit_row"]]) + 180.
    if method == "W01":
        end = max(end, max(ts[p["new"]["exit_row"]] for p in account["pairs"] if p["new"]) + 180.)
    right = focus if cut else end
    ids = np.where((ts >= left) & (ts <= right))[0]
    if cut:
        ids = ids[ids <= decision]
    good = q["quote_valid"] & (q["bid"] > 0.) & (q["ask"] > q["bid"])
    mid = np.where(good, (q["bid"] + q["ask"]) / 2., np.nan)
    x = (ts[ids] - focus) / 60.
    fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True, layout="constrained",
        gridspec_kw={"height_ratios": [3, 2, 2, 2]})
    axes[0].plot(x, rd["last"][ids], color="#929cae", lw=.8, label="最終約定値")
    axes[0].plot(x, mid[ids], color="#57c8ff", lw=1.0, label="正常気配中値")
    axes[0].fill_between(x, q["bid"][ids], q["ask"][ids], where=good[ids], color="#57c8ff", alpha=.10)
    for r, color, label in ((old, "#d7b966", "旧"), (new, "#ff8791", "改修")):
        kept = ids[(ids >= r["entry_row"]) & (ids <= r["exit_row"]) & good[ids]]
        mark = q["bid"][kept] if r["side"] > 0 else q["ask"][kept]
        peak = np.maximum.accumulate(np.maximum(r["side"] * (mark - r["entry"]), 0.))
        floor = np.full(len(kept), -r["width"])
        if label == "改修" and method in ("W01", "W03", "W04", "W06"):
            floor = np.maximum(floor, peak - r["width"])
        floor = np.maximum(floor, np.where(peak >= r["width"], peak - .75*r["width"], -r["width"]))
        axes[0].plot((ts[kept] - focus)/60., r["entry"] + r["side"]*floor, color=color, ls="--",
            lw=1., label=label + "の損切り・追尾線")
        for e in r["exits"]:
            if cut and e["fill_row"] > decision:
                continue
            axes[0].scatter([(ts[e["fill_row"]]-focus)/60.], [e["price"]], color=color, s=52, marker="x")
            axes[0].annotate(f'{label}返済{e["quantity"]}', ((ts[e["fill_row"]]-focus)/60.,e["price"]),
                xytext=(3, 7 if label == "旧" else -14), textcoords="offset points", color=color, fontsize=8)
    for p in account["pairs"]:
        r = p["new"]
        if r is None or ts[r["entry_row"]] < left or ts[r["entry_row"]] > right or (cut and r["entry_row"] > decision):
            continue
        axes[0].scatter([(ts[r["entry_row"]]-focus)/60.], [r["entry"]], color="#76d5a7", s=60,
            marker="^" if r["side"] > 0 else "v")
        axes[0].annotate("新規" + str(r["parent"]+1), ((ts[r["entry_row"]]-focus)/60.,r["entry"]),
            xytext=(3, 8), textcoords="offset points", color="#76d5a7", fontsize=8)
    axes[0].set_ylabel(symbol)
    # ----------------------------------------
    # 相手の図も判断時計より後の原行を隠す。原資料に受信時計は無い。
    peer = "TOPIX" if symbol == "NK225" else "NK225"
    pr, pq = packet["inputs"][scene, peer], packet["quotes"][scene, peer]
    pi = np.where((pr["time_s"] >= left) & (pr["time_s"] <= right))[0]
    if cut:
        pi = pi[pr["time_s"][pi] < focus]
    pg = pq["quote_valid"][pi] & (pq["ask"][pi] > pq["bid"][pi])
    axes[1].plot((pr["time_s"][pi]-focus)/60., np.where(pg,(pq["bid"][pi]+pq["ask"][pi])/2.,np.nan),
        color="#f6b66b", label=peer+"中値")
    axes[1].set_ylabel("相手市場")
    for ax, columns, name in ((axes[2], (4, 6), "30秒"), (axes[3], (5, 7), "120秒")):
        for col, color, label in zip(columns, ("#57c8ff","#f6b66b"), ("自己","相手")):
            ax.plot(x, new["side"]*m[ids,col], color=color, lw=.9, label=label)
        ax.axhline(0.,color="#8b97a9",ls="--",lw=.8)
        ax.set_ylabel(name+"変化／ATR\n建玉と同方向が＋")
    for ax in axes:
        ax.axvline(0.,color="#ff8791",ls="--")
        ax.grid(alpha=.3)
        ax.legend(loc="best",fontsize=8)
    axes[3].set_xlabel("改修の初回返済判断からの価格時計分")
    title = f'{scene} {symbol} {account["base"]} → {method} / 親{parent+1}'
    if cut:
        detail = changed["decision_time"][11:19]+" の判断まで（以降の原行・結果は非表示）"
    else:
        detail = f'親損益 {old["net"]:+,.0f}円 → {new["net"]:+,.0f}円 / 場差 {account["delta"]:+,.0f}円'
    axes[0].set_title(title+"\n"+detail)
    IMAGES.mkdir(parents=True, exist_ok=True)
    target = IMAGES / f'{method}_{scene}_{symbol}_親{parent+1}_{"判断まで" if cut else "後の経路"}.png'
    fig.savefig(target,dpi=120)
    plt.close(fig)
    return target.relative_to(PUBLIC).as_posix()


def main() -> None:
    """
    機能: 悪化三例と救済一例の図・固定数値を別ファイルに保存する。
    引数: なし。
    返り値: None。確定済み全親差分JSONは変更しない。
    """
    source = HERE / "第一巡の全親差分と部分返済時の二市場.json"
    data = read(source)
    refs = {r["session"]:r for r in read(OLD/"入力準備.json")["packets"]}
    cases = []
    for method, scene, symbol, parent in (
        ("W01", "2026-09-24_Night", "TOPIX", 0),
        ("W04", "2026-09-29_Night", "NK225", 2),
        ("W05", "2026-09-30_Night", "TOPIX", 0),
        ("W05", "2026-10-16_Night", "TOPIX", 2)):
        account = next(r for r in data["accounts"] if (r["method"],r["session"],r["symbol"])==(method,scene,symbol))
        packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        images = [render(account,parent,packet,cut) for cut in (True,False)]
        cases.append(dict(method=method,session=scene,symbol=symbol,parent=parent,account=account,images=images))
        print(method,scene,symbol,flush=True)
    save(HERE/"第一巡の四場具体差分と画像.json",dict(financial_replays=0,cases=cases))


if __name__=="__main__":
    main()
