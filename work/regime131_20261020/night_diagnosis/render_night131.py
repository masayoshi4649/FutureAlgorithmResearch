"""無取引場で観測した機会と反例を、注文ではなく価格観察として描く。"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from observe_night131 import HERE, read, save

plt.rcParams.update({"font.family":"Meiryo","font.size":10,"axes.unicode_minus":False,
    "figure.facecolor":"#101720","axes.facecolor":"#101720","text.color":"#e9eef5",
    "axes.labelcolor":"#e9eef5","xtick.color":"#becadd","ytick.color":"#becadd",
    "axes.edgecolor":"#60708b","grid.color":"#344256","legend.facecolor":"#17232f",
    "savefig.facecolor":"#101720"})


def plot(event: dict, all_events: list[dict], cut: bool) -> str:
    """
    機能: 判断前と後の観察を分離し、二市場価格・効率・公表量を図にする。
    引数: event(dict)、all_events(list[dict])、cut(bool)は基準観測・全観測・未来切断。
    返り値: strは作業域内の画像相対位置。金融結果を生成しない。
    """
    symbol,scene,i=event["symbol"],event["session"],event["index"]
    peer="TOPIX"if symbol=="NK225"else"NK225"
    d=dict(np.load(HERE/"minutes"/f"{symbol}_{scene}.npz"))
    p=dict(np.load(HERE/"minutes"/f"{peer}_{scene}.npz"))
    ids=np.arange(max(0,i-30),i+1 if cut else min(len(d["close"]),i+26))
    x=(d["time"][ids]-d["time"][i])/60.
    fig,axes=plt.subplots(4,1,figsize=(12,9),sharex=True,layout="constrained",
        gridspec_kw={"height_ratios":[3,2,1.5,1.5]})
    axes[0].plot(x,d["close"][ids],color="#59ccff",label=symbol+" 分端の正常気配中値")
    axes[1].plot(x,p["close"][ids],color="#f7b66a",label=peer+" 分端の正常気配中値")
    unit=max(.25*d["features"][i,4],2.*(10. if symbol=="NK225"else.5))
    for level in (event["price"]+unit,event["price"]-unit):
        axes[0].axhline(level,color="#9aa5b7",ls=":",lw=.8)
    markers=[e for e in all_events if e["session"]==scene and e["symbol"]==symbol and
        e["method"]==event["method"] and i<=e["index"]<=ids[-1]]
    for e in markers:
        xx=e["index"]-i
        axes[0].scatter([xx],[e["price"]],color="#eac26a",marker="^"if e["side"]>0 else"v",s=55)
        offset=-70 if e["index"]==ids[-1] else 3
        axes[0].annotate(e["time"][11:16]+" 観測", (xx,e["price"]),xytext=(offset,9),
            textcoords="offset points",fontsize=8,color="#eac26a")
    axes[2].plot(x,d["features"][ids,1],color="#59ccff",label="自己20分方向効率")
    axes[2].plot(x,p["features"][ids,1],color="#f7b66a",label="相手20分方向効率")
    axes[2].axhline(.35,color="#9aa5b7",ls="--",lw=.8)
    axes[3].plot(x,d["features"][ids,9],color="#59ccff",label="自己公表量／直前20分中央値")
    axes[3].plot(x,p["features"][ids,9],color="#f7b66a",label="相手公表量／直前20分中央値")
    for ax in axes:
        ax.axvline(0.,color="#ff8791",ls="--",lw=.8)
        ax.grid(alpha=.3)
        ax.legend(loc="best",fontsize=8)
    axes[-1].set_xlabel("観測時刻からの分。売買・約定・手数料の計算ではない")
    text="判断まで・後の値は非表示"if cut else"後の価格経路・点線は事後採点用の対称幅"
    axes[0].set_title(f'{scene} {symbol} / {event["method"]}\n{text} / 元{event["previous_method"]}はこの場で無取引')
    folder=HERE/"画像"
    folder.mkdir(exist_ok=True)
    path=folder/f'{scene}_{symbol}_{event["index"]}_{"判断まで"if cut else"後の経路"}.png'
    fig.savefig(path,dpi=120)
    plt.close(fig)
    return path.relative_to(HERE).as_posix()


def main() -> None:
    """
    機能: 同じ上昇の早い押戻りと遅い押戻り、往復仮説の反例を描く。
    引数: なし。
    返り値: None。観測図4枚と参照JSONを保存する。
    """
    data=read(HERE/"全夜間の時間帯と継続往復の観測.json")
    cases=[]
    for scene,symbol,name,index in (
        ("2026-09-22_Night","NK225","共通方向への押戻り",46),
        ("2026-09-28_Night","NK225","外抜けから帯内復帰",366)):
        e=next(r for r in data["events"]if (r["session"],r["symbol"],r["method"],r["index"])==(scene,symbol,name,index))
        images=[plot(e,data["events"],cut)for cut in (True,False)]
        cases.append(dict(event=e,images=images))
    save(HERE/"無取引場の機会と反例画像.json",dict(financial_replays=0,cases=cases))


if __name__=="__main__":
    main()
