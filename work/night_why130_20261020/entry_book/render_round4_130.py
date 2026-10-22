"""保存された価格基準と見送り位置を、失った勝ち・除いた負けの双方で描く。"""

import pickle

import matplotlib.pyplot as plt
import numpy as np

from render_entry130 import PUBLIC
from diagnose_entry130 import HERE, ROOT, OLD, read, save

IMAGES = PUBLIC / "画像/第四巡差分"


def render(account: dict, pair: dict, packet: dict, cut: bool) -> str:
    """
    機能: 記録価格と元突破線・解除境界を、実際に見送った判断位置まで又はその後まで描く。
    引数: account/pair/packet(dict)、cut(bool)は比較・消えた親・入力・未来切断。
    返り値: strは公開域内のPNG相対位置。売買は生成しない。
    """
    old = pair["old"]
    event = next(e for e in pair["event_at_old_decision"] if e["code"] == 2)
    symbol,scene = account["symbol"],account["session"]
    rd,q = packet["inputs"][scene,symbol],packet["quotes"][scene,symbol]
    ts = rd["time_s"]
    focus = ts[event["row"]]
    left = ts[event["budget_row"]]-120.
    right = focus if cut else ts[old["exit_row"]]+120.
    ids = np.flatnonzero((ts>=left)&(ts<=right))
    if cut:
        ids = ids[ids<=event["row"]]
    good = q["quote_valid"] & (q["bid"]>0.) & (q["ask"]>q["bid"])
    fig,axes = plt.subplots(2,1,figsize=(13,7),sharex=True,layout="constrained",
        gridspec_kw={"height_ratios":[3,2]})
    x = (ts[ids]-focus)/60.
    mid = np.where(good,(q["bid"]+q["ask"])/2.,np.nan)
    axes[0].plot(x,rd["last"][ids],color="#8998ab",lw=.8,label="最終約定値")
    axes[0].plot(x,mid[ids],color="#57c8ff",lw=1.,label="正常気配中値")
    axes[0].fill_between(x,q["bid"][ids],q["ask"][ids],where=good[ids],color="#57c8ff",alpha=.12)
    start = (ts[event["budget_row"]]-focus)/60.
    finish = 0.
    for price,color,label in (
        (event["budget_quote"],"#efbe63","最初に見送った判断気配"),
        (event["budget_level"],"#8dca8c","その時の固定突破線"),
        (event["budget_level"]-.25*event["side"]*event["budget_width"],"#d29bea","価格記録が解除される境界")):
        axes[0].plot([start,finish],[price,price],ls="--",color=color,label=label)
    axes[0].scatter([start],[event["budget_quote"]],color="#efbe63",s=65,marker="o")
    axes[0].annotate("価格記録 "+event["budget_time"][11:19],(start,event["budget_quote"]),
        xytext=(4,7),textcoords="offset points",fontsize=8,color="#efbe63")
    axes[0].scatter([0.],[event["decision_quote"]],color="#ff8791",s=80,marker="x",label="新方式は見送り")
    if not cut:
        axes[0].scatter([(ts[old["exit_row"]]-focus)/60.],[old["exit"]],color="#d2e1ef",s=60,marker="x")
        axes[0].annotate("元方式の返済",((ts[old["exit_row"]]-focus)/60.,old["exit"]),
            xytext=(4,7),textcoords="offset points",fontsize=8,color="#d2e1ef")
    peer = "TOPIX" if symbol=="NK225" else "NK225"
    pr,pq = packet["inputs"][scene,peer],packet["quotes"][scene,peer]
    pi = np.flatnonzero((pr["time_s"]>=left)&(pr["time_s"]<=right))
    if cut:
        pi = pi[pr["time_s"][pi]<focus]
    pg = pq["quote_valid"][pi] & (pq["ask"][pi]>pq["bid"][pi])
    axes[1].plot((pr["time_s"][pi]-focus)/60.,
        np.where(pg,(pq["ask"][pi]+pq["bid"][pi])/2.,np.nan),color="#f6b66b",label=peer+"気配中値")
    for ax in axes:
        ax.axvline(0.,color="#ff8791",ls="--")
        ax.grid(alpha=.3)
        ax.legend(loc="best",fontsize=8)
    axes[0].set_ylabel(symbol)
    axes[1].set_ylabel(peer)
    axes[1].set_xlabel("不利な価格として見送った判断からの価格時計分")
    detail = event["time"][11:19]+" の判断まで（後続行・結果は非表示）" if cut else (
        f'元の親 {old["net"]:+,.0f}円を見送り / 場全体 {account["old_net"]:+,.0f} → {account["new_net"]:+,.0f}円')
    axes[0].set_title(f'{scene} {symbol} {account["base"]} → {account["method"]}\n{detail}')
    IMAGES.mkdir(parents=True,exist_ok=True)
    path = IMAGES/f'{account["method"]}_{scene}_{symbol}_{"判断まで" if cut else "後の経路"}.png'
    fig.savefig(path,dpi=120)
    plt.close(fig)
    return path.relative_to(PUBLIC).as_posix()


def main() -> None:
    """
    機能: 狙った損失を防いだ例と、数時間前の価格制限で勝ちを失った例を描く。
    引数: なし。
    返り値: None。確定JSONを変更せず別の画像参照JSONを保存する。
    """
    data=read(HERE/"第四巡の価格記録と全親差分.json")
    refs={r["session"]:r for r in read(OLD/"入力準備.json")["packets"]}
    cases=[]
    for method,scene,symbol in (("W12","2026-10-14_Night","NK225"),("W12","2026-10-16_Night","NK225")):
        account=next(a for a in data["accounts"] if (a["method"],a["session"],a["symbol"])==(method,scene,symbol))
        pair=next(p for p in account["pairs"] if p["kind"]=="元の親が消えた")
        packet=pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        images=[render(account,pair,packet,cut) for cut in (True,False)]
        cases.append(dict(method=method,session=scene,symbol=symbol,pair=pair,images=images))
    save(HERE/"第四巡の価格基準と見送り図.json",dict(financial_replays=0,cases=cases))


if __name__=="__main__":
    main()
