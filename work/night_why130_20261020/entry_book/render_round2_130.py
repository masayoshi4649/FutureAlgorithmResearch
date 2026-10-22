"""入口確認による見送り後の経路変化を、保存注文と観測入力だけで描く。"""

import pickle
import sys

import matplotlib.pyplot as plt
import numpy as np

from render_entry130 import PUBLIC
from diagnose_entry130 import HERE, ROOT, OLD, PREV, read, save

sys.path.insert(0, str(PREV))
import features129

IMAGES = PUBLIC / "画像/第二巡差分"


def render(account: dict, parent: int, packet: dict, cut: bool) -> str:
    """
    機能: 見送った元の入口と後の新入口を、気配・二市場・原板活動と重ねる。
    引数: account(dict)、parent(int)、packet(dict)、cut(bool)は会計・対象親・入力・判断切断。
    返り値: strは公開域内のPNG相対位置。注文核は実行しない。
    """
    scene, symbol, method = account["session"], account["symbol"], account["method"]
    pair = next(p for p in account["pairs"] if p["new"] and p["new"]["parent"] == parent)
    new, old = pair["new"], pair["previous_same_side_old"]
    assert old is not None and pair["kind"] == "新しい入口経路の親"
    kind = "last" if account["base"] == "NV01" else "mid"
    _, markets, _, _ = features129.build(packet, kind)
    rd, q = packet["inputs"][scene, symbol], packet["quotes"][scene, symbol]
    ts, m = rd["time_s"], markets[scene, symbol]
    activity = dict(np.load(HERE.parent / "prepared" / f"{symbol}_{scene}.npz"))["activity"]
    decision, side = new["decision_row"], new["side"]
    focus = ts[decision]
    left = ts[old["entry_row"]] - 300.
    right = focus if cut else max(ts[new["exit_row"]], ts[old["exit_row"]]) + 180.
    ids = np.flatnonzero((ts >= left) & (ts <= right))
    if cut:
        ids = ids[ids <= decision]
    good = q["quote_valid"] & (q["bid"] > 0.) & (q["ask"] > q["bid"])
    mid = np.where(good, (q["bid"] + q["ask"]) / 2., np.nan)
    x = (ts[ids] - focus) / 60.
    fig, axes = plt.subplots(5, 1, figsize=(13, 12), sharex=True, layout="constrained",
        gridspec_kw={"height_ratios": [3, 2, 1.6, 1.6, 1.6]})
    axes[0].plot(x, rd["last"][ids], color="#929cae", lw=.8, label="最終約定値")
    axes[0].plot(x, mid[ids], color="#57c8ff", lw=1., label="正常気配中値")
    axes[0].fill_between(x, q["bid"][ids], q["ask"][ids], where=good[ids],
        color="#57c8ff", alpha=.12, label="売買気配の間")
    for r, color, label in ((old, "#e2bd64", "旧"), (new, "#ff8791", "新")):
        held = ids[(ids >= r["entry_row"]) & (ids <= r["exit_row"]) & good[ids]]
        if len(held):
            liquid = q["bid"][held] if side > 0 else q["ask"][held]
            peak = np.maximum.accumulate(np.maximum(side * (liquid - r["entry"]), 0.))
            floor = np.maximum(-r["width"], np.where(peak >= r["width"],
                peak - .75*r["width"], -r["width"]))
            axes[0].plot((ts[held]-focus)/60., r["entry"]+side*floor, color=color,
                ls="--", lw=.9, label=label+"の初期損切り・追尾")
        for row, price, tag in ((r["entry_row"],r["entry"],"新規"), (r["exit_row"],r["exit"],"返済")):
            if cut and row > decision:
                continue
            if ts[row] < left or ts[row] > right:
                continue
            marker = ("^" if side > 0 else "v") if tag == "新規" else "x"
            axes[0].scatter([(ts[row]-focus)/60.], [price], color=color, s=60, marker=marker, zorder=5)
            axes[0].annotate(f"{label}{tag} {price:g}", ((ts[row]-focus)/60.,price),
                xytext=(3, 9 if label=="旧" else -17), textcoords="offset points",
                color=color, fontsize=8)
    if cut:
        axes[0].scatter([0.], [mid[decision]], color="#ff8791", s=75,
            marker="^" if side > 0 else "v", label="新方式の発注判断")
    axes[0].set_ylabel(symbol)
    # ----------------------------------------
    # 相手市場も価格時計が判断時刻と同じ又はそれ以後の行は、判断図では隠す。
    peer = "TOPIX" if symbol == "NK225" else "NK225"
    pr, pq = packet["inputs"][scene, peer], packet["quotes"][scene, peer]
    pi = np.flatnonzero((pr["time_s"] >= left) & (pr["time_s"] <= right))
    if cut:
        pi = pi[pr["time_s"][pi] < focus]
    pg = pq["quote_valid"][pi] & (pq["ask"][pi] > pq["bid"][pi])
    axes[1].plot((pr["time_s"][pi]-focus)/60.,
        np.where(pg,(pq["bid"][pi]+pq["ask"][pi])/2.,np.nan),
        color="#f6b66b", label=peer+"正常気配中値")
    axes[1].set_ylabel("相手市場")
    axes[2].plot(x, side*activity[ids,0], color="#57c8ff", label="方向×気配中値差")
    axes[2].set_ylabel("気配中値の変化\n新規方向が＋")
    axes[3].plot(x, side*activity[ids,2], color="#d99cf2", label="方向×符号付き量代理")
    axes[3].plot(x, activity[ids,1], color="#929cae", lw=.6, alpha=.6, label="公表量正増分")
    axes[3].set_ylabel("量代理\n逆向きなら−")
    for column, color, label in ((4,"#57c8ff","自己"),(6,"#f6b66b","相手")):
        axes[4].plot(x, side*m[ids,column], color=color, label=label+"30秒方向／ATR")
    axes[4].set_ylabel("二市場の短期方向\n新規方向が＋")
    for ax in axes:
        ax.axvline(0., color="#ff8791", ls="--", lw=.8)
        ax.grid(alpha=.3)
        ax.legend(loc="best", fontsize=8)
    for ax in axes[2:]:
        ax.axhline(0., color="#8996aa", ls="--", lw=.8)
    axes[4].set_xlabel("新方式の新規判断からの価格時計分（原板活動の実区間は30秒超〜60秒）")
    detail = new["decision_time"][11:19]+" の判断まで（後続行と損益は非表示）" if cut else (
        f'旧親 {old["net"]:+,.0f}円 → 別の新親 {new["net"]:+,.0f}円 / '
        f'場全体 {account["old_net"]:+,.0f} → {account["new_net"]:+,.0f}円')
    axes[0].set_title(f'{scene} {symbol} {account["base"]} → {method}\n{detail}')
    IMAGES.mkdir(parents=True, exist_ok=True)
    path = IMAGES / f'{method}_{scene}_{symbol}_親{parent+1}_{"判断まで" if cut else "後の経路"}.png'
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path.relative_to(PUBLIC).as_posix()


def main() -> None:
    """
    機能: 新しい入口が損失になった三例について、判断前図と後の経路を保存する。
    引数: なし。
    返り値: None。確定済み全親差分JSONには追記しない。
    """
    data = read(HERE/"第二巡の入口見送り後の全親差分.json")
    refs = {r["session"]:r for r in read(OLD/"入力準備.json")["packets"]}
    cases = []
    for method, scene, symbol, parent in (
        ("W08","2026-10-14_Night","NK225",0),
        ("W07","2026-10-19_Night","TOPIX",1),
        ("W07","2026-10-01_Night","NK225",0)):
        account = next(a for a in data["accounts"] if (a["method"],a["session"],a["symbol"]) ==
            (method,scene,symbol))
        packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        images = [render(account,parent,packet,cut) for cut in (True,False)]
        cases.append(dict(method=method,session=scene,symbol=symbol,parent=parent,
            account=account,images=images))
        print(method,scene,symbol,flush=True)
    save(HERE/"第二巡の三場具体差分と画像.json",dict(financial_replays=0,cases=cases))


if __name__ == "__main__":
    main()
