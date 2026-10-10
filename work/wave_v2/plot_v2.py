"""正式採用結果の指定波と保存全セッションを日本語の図で検証する。"""

from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
import pandas as pd

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
JST=ZoneInfo("Asia/Tokyo")
COLORS={1:"#087e64",-1:"#c45438"}
REFERENCE="#f4dfa3"


def setup_style() -> None:
    """機能: 日本語フォントと印刷向け配色を設定する。

    引数: なし。返り値: なし (None)。
    """
    font_path=Path("C:/Windows/Fonts/meiryo.ttc")
    if not font_path.exists():
        raise FileNotFoundError("日本語フォントを確認できません")
    font_manager.fontManager.addfont(str(font_path))
    name=font_manager.FontProperties(fname=str(font_path)).get_name()
    plt.rcParams.update({"font.family":name,"font.size":10,"axes.unicode_minus":False,
                         "axes.spines.top":False,"axes.spines.right":False,"axes.edgecolor":"#ced6da",
                         "axes.labelcolor":"#44545c","xtick.color":"#536570","ytick.color":"#536570",
                         "figure.facecolor":"#fbfcfc","axes.facecolor":"#ffffff","savefig.facecolor":"#fbfcfc"})


def load_results() -> tuple[dict,list[dict],dict,dict]:
    """機能: 正式採用済み設定・全取引・指定波評価・保存価格を読み込む。

    引数: なし。返り値: 設定・取引・指定波・価格の対応 (tuple)。
    """
    fixed=json.loads((OUT/"固定設定.json").read_text(encoding="utf-8"))
    if fixed["config"]["family"]!=24:
        raise RuntimeError("系統24の正式採用結果が保存されるまで描画を待ってください")
    trades=json.loads((OUT/"比較_採用取引.json").read_text(encoding="utf-8"))
    for i,t in enumerate(trades,1):
        for field in ("signal_time","entry_time","exit_time"):
            t[field]=pd.Timestamp(t[field]) if t.get(field) else None
        t["id"]=i
    metrics=json.loads((OUT/"比較_採用指定波.json").read_text(encoding="utf-8"))
    targets={}
    for r in metrics:
        r["begin"],r["end"]=pd.Timestamp(r["begin"]),pd.Timestamp(r["end"])
        targets[(r["session"],r["symbol"])]=r
    data={}
    for p in (ROOT/"candle_1min").glob("*/*.csv"):
        z=pd.read_csv(p)
        z=z[z.closed.astype(str).str.lower().eq("true")].copy()
        z["time"]=pd.to_datetime(z.time)
        data[(p.stem,p.parent.name)]=z.set_index("time").sort_index()
    return fixed,trades,targets,data


def price_text(price: float,symbol: str) -> str:
    """機能: 銘柄の値刻みに応じて価格を読みやすく表示する。

    引数: price (float)、symbol (str)。返り値: 価格文字列 (str)。
    """
    return f"{price:,.0f}" if symbol=="NK225" else f"{price:,.1f}"


def is_target_trade(trade: dict,target: dict | None) -> bool:
    """機能: 指定区間と20分以上重なる正方向の取引を判定する。

    引数: trade (dict)、target (dict | None)。返り値: 強調対象か (bool)。
    """
    if target is None or trade["side"]!=target["target_side"]:
        return False
    end=trade["exit_time"] or target["end"]
    return min(end,target["end"])-max(trade["entry_time"],target["begin"])>=pd.Timedelta(minutes=20)


def draw_panel(fig: plt.Figure,spec: object,key: tuple[str,str],data: dict,trades: list[dict],targets: dict,detail: bool) -> None:
    """機能: 価格・指定区間・全保有区間と価格付き取引台帳を一組の領域に描く。

    引数: fig (Figure)、spec (SubplotSpec)、key (tuple)、data/targets (dict)、trades (list)、detail (bool)。
    返り値: なし (None)。
    """
    session,symbol=key
    z=data[key]
    subset=[t for t in trades if (t["session"],t["symbol"])==key]
    target=targets.get(key)
    inner=spec.subgridspec(2,1,height_ratios=[4.0,1.25 if detail else 1.55],hspace=.21)
    ax=fig.add_subplot(inner[0])
    ledger=fig.add_subplot(inner[1])
    ledger.axis("off")
    grid=pd.date_range(z.index[0],z.index[-1],freq="min")
    # １分足が存在しないところでは線も切り、観測価格を補間しない。
    close=z.close.reindex(grid)
    ax.plot(grid,close,color="#a3afb5",linewidth=1.0,zorder=2)
    ax.scatter(z.index,z.close,color="#a3afb5",s=2.2,alpha=.60,zorder=2)
    if target is not None:
        ax.axvspan(target["begin"],target["end"],facecolor=REFERENCE,alpha=.44,zorder=0)
        ax.axvline(target["begin"],color="#b8943b",linestyle=(0,(3,3)),linewidth=.8,zorder=1)
        ax.axvline(target["end"],color="#b8943b",linestyle=(0,(3,3)),linewidth=.8,zorder=1)
    # ----------------------------------------
    # 実保有中の価格を売買方向で色分けし、保有時間を下端の帯でも示す。
    for j,t in enumerate(subset):
        side=t["side"]
        end=t["exit_time"] or z.index[-1]+pd.Timedelta(minutes=1)
        mask=(grid>=t["entry_time"])&(grid<=end)
        emphasized=is_target_trade(t,target)
        color=COLORS[side]
        alpha=1 if not detail or emphasized else .45
        ax.plot(grid[mask],close[mask],color=color,linewidth=2.1 if emphasized else 1.6,alpha=alpha,zorder=3)
        ax.axvspan(t["entry_time"],end,ymin=.022,ymax=.072,color=color,alpha=.9 if emphasized else .65,zorder=4)
        ax.scatter([t["entry_time"]],[t["entry_price"]],marker="^" if side==1 else "v",s=56,color=color,edgecolor="white",linewidth=.7,zorder=6)
        if t["closed"]:
            ax.scatter([end],[t["exit_price"]],marker="s",s=31,facecolor="white",edgecolor=color,linewidth=1.5,zorder=6)
        ax.annotate(f'{t["id"]}',(t["entry_time"],t["entry_price"]),xytext=(5,9 if side==1 else -17),textcoords="offset points",color=color,fontsize=9,fontweight="bold",zorder=7)
        if detail and emphasized:
            entry_label=f'保有開始 {t["entry_time"]:%H:%M}\n{price_text(t["entry_price"],symbol)}'
            exit_label=f'返済 {end:%H:%M}\n{price_text(t["exit_price"],symbol)}' if t["closed"] else "未返済"
            left_y=.88 if side==1 else .91
            right_y=.89 if side==1 else .18
            ax.annotate(entry_label,xy=(t["entry_time"],t["entry_price"]),xycoords="data",xytext=(.24,left_y),textcoords="axes fraction",ha="left",va="top",fontsize=9,color=color,
                        bbox={"boxstyle":"round,pad=.35","fc":"white","ec":color,"alpha":.97,"lw":.6},arrowprops={"arrowstyle":"-","color":color,"lw":.7},zorder=9)
            ax.annotate(exit_label,xy=(end,t["exit_price"] if t["closed"] else z.close.iloc[-1]),xycoords="data",xytext=(.79,right_y),textcoords="axes fraction",ha="left",va="top",fontsize=9,color=color,
                        bbox={"boxstyle":"round,pad=.35","fc":"white","ec":color,"alpha":.97,"lw":.6},arrowprops={"arrowstyle":"-","color":color,"lw":.7},zorder=9)
    # ----------------------------------------
    # 日付・尺度・売買台帳はすべて日本時間で固定する。
    date=pd.Timestamp(session[:10])
    label="日中" if "Day" in session else "夜間"
    title=f"{date.month}月{date.day}日 {label}  |  {symbol}"
    if detail and target is not None:
        title+=f'　指定「{"ロング" if target["target_side"]==1 else "ショート"}」'
    ax.set_title(title,loc="left",fontsize=14,fontweight="bold",pad=13,color="#213843")
    margin=pd.Timedelta(minutes=8)
    ax.set_xlim(z.index[0]-margin,z.index[-1]+margin)
    ymin,ymax=z.low.min(),z.high.max()
    pad=max(float(ymax-ymin)*.14,10 if symbol=="NK225" else .5)
    ax.set_ylim(ymin-pad,ymax+pad)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value,pos:f"{value:,.0f}" if symbol=="NK225" else f"{value:,.1f}"))
    ax.set_ylabel("価格",fontsize=9)
    ax.grid(axis="y",color="#e6ecee",linewidth=.7,zorder=0)
    interval=1 if "Day" in session else 2
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=interval,tz=JST))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=JST))
    ax.tick_params(axis="both",labelsize=9,length=3)
    if "Night" in session:
        midnight=z.index[0].normalize()+pd.Timedelta(days=1)
        ax.axvline(midnight,color="#b9c3c7",linestyle=":",linewidth=1,zorder=0)
        ax.text(midnight,.98,"翌日",transform=ax.get_xaxis_transform(),ha="left",va="top",fontsize=8,color="#6e7c84")
    if detail and target is not None:
        ledger.text(0,1.02,f'指定 {target["begin"]:%H:%M}～{target["end"]:%H:%M}　時間捕捉 {target["correct_coverage"]:.1%}　値幅捕捉 {target["capture_ratio"]:.1%}',transform=ledger.transAxes,fontsize=9.5,color="#6d581c",va="top")
        start_y=.57
        gap=.34
    else:
        net=sum(t.get("net_points",0) or 0 for t in subset)
        ledger.text(0,1.02,f'{len(subset)}波　参考損益 {net:+,.0f}' if symbol=="NK225" else f'{len(subset)}波　参考損益 {net:+,.1f}',transform=ledger.transAxes,fontsize=9.5,color="#344b57",va="top",fontweight="bold")
        start_y=.74
        gap=.205
    for j,t in enumerate(subset):
        direction="買" if t["side"]==1 else "売"
        end_text=f'{t["exit_time"]:%H:%M} {price_text(t["exit_price"],symbol)}' if t["closed"] else "未返済"
        amount=t.get("net_points")
        profit=(f'{amount:+,.0f}' if symbol=="NK225" else f'{amount:+,.1f}') if amount is not None else "未確定"
        text=f'{t["id"]:>2}  {direction}  {t["entry_time"]:%H:%M} {price_text(t["entry_price"],symbol)}  →  {end_text}  ｜  {profit}'
        ledger.text(0,start_y-j*gap,text,transform=ledger.transAxes,fontsize=9.1,color=COLORS[t["side"]],va="top",fontweight="bold" if is_target_trade(t,target) else "normal")


def make_figure(fixed: dict,trades: list[dict],targets: dict,data: dict,detail: bool) -> Path:
    """機能: ２日４波または全３セッションの比較図を保存する。

    引数: fixed/targets/data (dict)、trades (list)、detail (bool)。返り値: 保存画像のパス (Path)。
    """
    sessions=["2026-09-21_Day","2026-09-22_Day"] if detail else ["2026-09-21_Day","2026-09-21_Night","2026-09-22_Day"]
    fig=plt.figure(figsize=(19,13 if detail else 17),dpi=160)
    spec=fig.add_gridspec(len(sessions),2,left=.055,right=.985,top=.83,bottom=.045,hspace=.32,wspace=.16)
    title="指定された４つの継続波を、同じ条件で捉える" if detail else f"保存３セッションの全仮想取引 ─ 利益・損失を含む{len(trades)}波"
    fig.text(.055,.969,title,fontsize=22,fontweight="bold",color="#203946",va="top")
    fig.text(.055,.925,f'採用：{fixed["name"]}　｜　日本時間・仮想保有開始／返済を表示',fontsize=11.5,color="#4b606b",va="top")
    handles=[Patch(facecolor=REFERENCE,alpha=.6,label="利用者指定の波の区間"),Line2D([0],[0],color=COLORS[1],lw=3,label="仮想保有：ロング"),Line2D([0],[0],color=COLORS[-1],lw=3,label="仮想保有：ショート"),
             Line2D([0],[0],color="#a3afb5",lw=1,label="１分終値（未観測分は線を切る）"),Line2D([0],[0],marker="s",markerfacecolor="white",markeredgecolor="#566971",linestyle="None",label="返済価格")]
    fig.legend(handles=handles,loc="upper left",bbox_to_anchor=(.052,.900),ncol=5,frameon=False,fontsize=10,columnspacing=1.6,handlelength=2.1)
    for row,ses in enumerate(sessions):
        for col,sym in enumerate(("NK225","TOPIX")):
            draw_panel(fig,spec[row,col],(ses,sym),data,trades,targets,detail)
    fig.text(.055,.018,"保存データ内の開発結果。台帳は仮想保有開始時刻・価格 → 返済時刻・価格。損益は往復２ティック控除後の各銘柄の価格差。",fontsize=9,color="#5d707a",va="bottom")
    path=OUT/("図_指定４波.png" if detail else "図_保存全セッション.png")
    fig.savefig(path,dpi=160)
    plt.close(fig)
    return path


def main() -> None:
    """機能: 正式採用結果の２枚の図を作る。

    引数: なし。返り値: なし (None)。
    """
    setup_style()
    fixed,trades,targets,data=load_results()
    for detail in (True,False):
        print(make_figure(fixed,trades,targets,data,detail))


if __name__=="__main__":
    main()
