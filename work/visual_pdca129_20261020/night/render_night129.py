"""保存夜間売買を原行由来の一分足へ描画する。新しい金融運転は行わない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np
from numba import njit
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/daynight128_20261020"
PUBLIC = ROOT / "アルゴリズム調査/00129_チャートと板からの失敗機構再検証"
IMAGES = PUBLIC / "画像/夜間"
JST = timezone(timedelta(hours=9))
plt.rcParams.update({"font.family": "Meiryo", "font.size": 10, "axes.unicode_minus": False,
    "figure.facecolor": "#101720", "axes.facecolor": "#101720", "text.color": "#e9eef5",
    "axes.labelcolor": "#e9eef5", "xtick.color": "#b9c5d7", "ytick.color": "#b9c5d7",
    "axes.edgecolor": "#62728c", "grid.color": "#344256", "legend.facecolor": "#182433",
    "legend.edgecolor": "#62728c", "savefig.facecolor": "#101720"})
COLORS = {"NK225": "#53b6ff", "TOPIX": "#ffb45a"}


@njit(cache=False)
def trace(times, price, atr, history, market, bid, ask, qok, allowed, tick, expected, maximum, confirm):
    """
    機能: 保存保有区間を固定し、準備開始と固定突破線だけを復元する。
    引数: 原行列・allowed・expected(ndarray)、tick/maximum(float)、confirm(int)。
    返り値: ndarrayは判断行・準備行・固定境界・幅。注文や損益は作らない。
    """
    out = np.zeros((len(expected), 4))
    count, arm, began = 0, 0, -1
    level, width = 0., 0.
    for i in range(len(times)):
        if not allowed[i]:
            continue
        known = np.isfinite(price[i]) and np.isfinite(atr[i]) and atr[i] > 0.
        known = known and np.isfinite(history[i]).all() and market[i, 11] == 1.
        known = known and np.isfinite(market[i, 4:8]).all()
        if not known:
            continue
        if not (qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]):
            continue
        w = max(atr[i], 4*tick)
        quote_ok = ask[i]-bid[i] <= .25*w and max(ask[i]-price[i], price[i]-bid[i]) <= .5*w
        if arm and times[i]-times[began] > 1800.:
            arm = 0
        if not arm and quote_ok:
            if history[i, 5] >= .35:
                if price[i] > history[i, 3] and history[i, 10] > 0. and history[i, 11] > 0.:
                    arm, level = 1, history[i, 3]
                elif price[i] < history[i, 4] and history[i, 10] < 0. and history[i, 11] < 0.:
                    arm, level = -1, history[i, 4]
            if arm:
                width, began = w, i
        elif arm:
            if arm*(price[i]-level) < -.25*width:
                arm = 0
            else:
                support = arm*market[i, 4] > 0. and arm*market[i, 6] > 0.
                trigger = times[i]-times[began] >= 60. and support and arm*(price[i]-level) >= .25*width
                trigger = trigger and arm*market[i, 5] > .05 and arm*market[i, 7] > .05
                if confirm == 3:
                    trigger = trigger and arm*history[i, 10] > 0. and arm*history[i, 11] > 0.
                quote = ask[i] if arm > 0 else bid[i]
                trigger = trigger and arm*(quote-level) <= maximum*width
                if trigger and quote_ok:
                    assert count < len(expected) and expected[count] == i
                    out[count] = np.array([i, began, level, width])
                    arm, count = 0, count+1
    assert count == len(expected)
    return out


def read(path: Path) -> dict:
    """
    機能: 保存された日本語ＪＳＯＮを読む。
    引数: path(Path)は資料位置。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stamp(value: float) -> str:
    """
    機能: 原資料の価格時計を日本時刻で示す。
    引数: value(float)はＵｎｉｘ秒。
    返り値: strは日本時刻。実受信時計ではない。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def ohlc(ready: dict, maximum_row: int | None = None) -> pd.DataFrame:
    """
    機能: 表示対象の原行だけから一分ＯＨＬＣを作る。
    引数: ready(dict)、maximum_row(int|None)は原行と表示上限。
    返り値: DataFrameは一分足。入口切断では当分の未完足も切断原行までだけを使う。
    """
    end = len(ready["last"]) if maximum_row is None else maximum_row+1
    series = pd.Series(ready["last"][:end], index=pd.to_datetime(ready["time_s"][:end], unit="s", utc=True))
    bars = series.resample("1min").ohlc().dropna()
    bars["unix"] = bars.index.as_unit("ns").asi8 / 1e9
    assert len(bars) and abs(float(bars["unix"].iloc[-1])-float(ready["time_s"][end-1])) < 60.
    return bars


def collect() -> tuple:
    """
    機能: 保存全二十一夜間のＮ３６・Ｎ２７の注文と準備を対応させる。
    引数: なし。
    返り値: tupleは診断行・入力参照・保存会計。金融核は呼ばない。
    """
    manifest = read(OLD/"入力準備.json")
    references = {r["session"]: r for r in manifest["packets"] if r["session"].endswith("_Night")}
    results = {m: read(OLD/folder/"全条件の会計.json") for m, folder in (("N36", "round5"), ("N27", "round3"))}
    rows = []
    for scene, ref in references.items():
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        with np.load(ROOT/ref["features"]["path"], allow_pickle=False) as hs:
            for symbol in ("NK225", "TOPIX"):
                ready, q, market = (packet[k][scene, symbol] for k in ("inputs", "quotes", "markets"))
                history = hs[symbol+"__history"]
                times, price = ready["time_s"], ready["last"]
                for method, folder, maximum, confirm in (("N36", "round5", 1.e9, 3), ("N27", "round3", 1.5, 1)):
                    with np.load(OLD/folder/"measurement"/f"{symbol}_{scene}.npz", allow_pickle=False) as a:
                        orders, trades = a[method+"__orders"], a[method+"__trades"]
                    entries = orders[orders[:, 7] == 1.]
                    allowed = (times >= ready["us_open"]+1320.) & (times < ready["limit"])
                    for order, trade in zip(entries, trades):
                        next_ready = np.searchsorted(times, times[int(trade[1])]+300., side="left")
                        allowed[int(order[1])+1:next_ready] = False
                    states = trace(times, price, ready["atr"], history, market, q["bid"], q["ask"],
                                   q["quote_valid"], allowed, ready["tick"], entries[:, 1].astype(np.int64),
                                   maximum, confirm)
                    assert len(states) == len(trades)
                    for n, (trade, state) in enumerate(zip(trades, states)):
                        e, x, side, qty = map(int, trade[:4])
                        d, arm = map(int, state[:2])
                        boundary, width = state[2:]
                        h, m = history[d], market[d]
                        prior = max(0, int(np.searchsorted(times, times[d]-3600., side="left")))
                        local = price[prior:d+1]
                        c = np.nanmax(local)-np.nanmin(local)
                        scale = ready["atr"][d]
                        row = dict(method=method, session=scene, symbol=symbol, number=n+1,
                            decision_row=d, arm_row=arm, entry_row=e, exit_row=x,
                            arm_time=stamp(times[arm]), decision_time=stamp(times[d]),
                            entry_time=stamp(times[e]), exit_time=stamp(times[x]),
                            direction="買い" if side > 0 else "売り", side=side, quantity=qty,
                            entry=float(trade[4]), exit=float(trade[5]), gross=float(trade[6]),
                            fee=float(trade[7]), net=float(trade[8]), mfe=float(trade[9]),
                            mae=float(trade[10]), width=float(width), reason=int(trade[12]),
                            boundary=float(boundary), activation=1. if method=="N36" else 1.5,
                            trail=.75 if method=="N36" else 1.,
                            observable=dict(own5=float(side*h[6]/scale), own20=float(side*h[7]/scale),
                                peer5=float(side*h[10]/m[3]), peer20=float(side*h[11]/m[3]),
                                own120=float(side*m[5]), peer120=float(side*m[7]),
                                er20=float(h[5]), wait_seconds=float(times[d]-times[arm]),
                                boundary_distance=float(side*((q["ask"][d] if side>0 else q["bid"][d])-boundary)/width),
                                sixty_change=float(side*(price[d]-price[prior])/scale),
                                sixty_location=float((price[d]-np.nanmin(local))/c) if c else .5,
                                spread_r=float((q["ask"][d]-q["bid"][d])/width)))
                        assert np.isclose(width, trade[11])
                        rows.append(row)
        print(scene, "保存準備照合", flush=True)
    return rows, references, results


def candle(ax, bars: pd.DataFrame, start: float, left: float, right: float) -> None:
    """
    機能: 原行由来の一分足を暗色背景へ描く。
    引数: ax(Axes)、bars(DataFrame)、start/left/right(float)は軸・足・時刻。
    返り値: None。赤緑識別と小実体の可視性を保つ。
    """
    b = bars[(bars["unix"] >= left-60.) & (bars["unix"] <= right)]
    for t, op, hi, lo, cl in zip(b["unix"], b["open"], b["high"], b["low"], b["close"]):
        x = (t-start)/60.
        color = "#53d8b1" if cl >= op else "#ed7387"
        ax.vlines(x, lo, hi, color=color, linewidth=.8)
        ax.add_patch(Rectangle((x-.32, min(op, cl)), .64, max(abs(cl-op), .015*(hi-lo)),
                               facecolor=color, edgecolor=color, linewidth=.5))
        if cl == op:
            ax.hlines(cl, x-.32, x+.32, color=color, linewidth=.9)
    if len(b):
        span = max(float(b["high"].max()-b["low"].min()), .1)
        ax.set_ylim(float(b["low"].min())-.12*span, float(b["high"].max())+.18*span)


def draw(scene: str, packet: dict, history: dict, rows: list, path: Path,
         focus: dict | None = None, cut: bool = False, control: bool = False) -> None:
    """
    機能: 両市場の一分足・保存注文・公開変化を全場又は局所図へ描画する。
    引数: scene(str)、packet/history(dict)、rows(list)、path(Path)、focus(dict|None)、cut/control(bool)。
    返り値: None。切断図は判断行以前の原行だけで足・軸・注記を作る。
    """
    symbol = focus["symbol"] if focus else "NK225"
    other = "TOPIX" if symbol == "NK225" else "NK225"
    ready = packet["inputs"][scene, symbol]
    times, start = ready["time_s"], ready["start"]
    left, right = start, ready["limit"]
    if focus:
        d, e, x = (focus[k] for k in ("decision_row", "entry_row", "exit_row"))
        left = max(start, times[d]-2700.)
        right = times[d] if cut else min(ready["limit"], max(times[x]+900., times[d]+2700.))
    fig, axes = plt.subplots(4, 1, figsize=(18, 13), sharex=True, gridspec_kw={"height_ratios": [3, 3, 1.5, 1.5]})
    for ax, sy in zip(axes[:2], (symbol, other)):
        rd = packet["inputs"][scene, sy]
        cutrow = (focus["decision_row"] if sy == symbol else int(np.searchsorted(rd["time_s"], right, side="left"))-1) if cut else None
        bars = ohlc(rd, cutrow)
        candle(ax, bars, start, left, right)
        q = packet["quotes"][scene, sy]
        qi = np.flatnonzero((rd["time_s"] >= left) & (rd["time_s"] <= right))
        if cut:
            qi = qi[qi <= cutrow]
        valid = q["quote_valid"][qi] & (q["bid"][qi] > 0.) & (q["ask"][qi] > q["bid"][qi])
        valid &= np.isfinite(q["bid"][qi]) & np.isfinite(q["ask"][qi])
        bid = np.where(valid, q["bid"][qi], np.nan)
        ask = np.where(valid, q["ask"][qi], np.nan)
        qx = (rd["time_s"][qi]-start)/60.
        ax.fill_between(qx, bid, ask, color="#bec5d3", alpha=.14, step="post", label="正常買気配〜売気配")
        ax.plot(qx, (bid+ask)/2., color="#e1e5ed", alpha=.85, linewidth=.7,
                drawstyle="steps-post", label="正常気配の中心")
        if valid.any():
            lower, upper = ax.get_ylim()
            lower, upper = min(lower, float(np.nanmin(bid))), max(upper, float(np.nanmax(ask)))
            margin = (upper-lower)*.03
            ax.set_ylim(lower-margin, upper+margin)
        ax.set_ylabel(sy+" ラージ価格")
        active = [r for r in rows if r["session"] == scene and r["symbol"] == sy]
        for tr in active:
            if cut:
                continue
            en, ex = tr["entry_row"], tr["exit_row"]
            et, xt = rd["time_s"][en], rd["time_s"][ex]
            if xt < left or et > right:
                continue
            primary = tr["method"] == "N36"
            color = "#49d7ff" if primary else "#be91f5"
            ax.plot([(et-start)/60., (xt-start)/60.], [tr["entry"], tr["exit"]],
                    color=color, linewidth=1.2 if primary else .7, alpha=.85 if primary else .5,
                    linestyle="-" if primary else ":")
            ax.scatter((et-start)/60., tr["entry"], marker="^" if tr["side"]>0 else "v",
                       s=65 if primary else 34, facecolor=color, edgecolor="#101720", zorder=5)
            ax.scatter((xt-start)/60., tr["exit"], marker="x", s=40 if primary else 24, color=color, zorder=5)
            if primary:
                ax.text((et-start)/60., tr["entry"], f" {tr['number']} {tr['direction']}",
                        color=color, fontsize=8, clip_on=True)
                ax.text((xt-start)/60., tr["exit"], f" {tr['net']:+,.0f}円",
                        color=color, fontsize=8, clip_on=True)
        if focus and sy == symbol:
            arm_t = times[focus["arm_row"]]
            point_t = times[focus["decision_row"]] if cut else times[focus["entry_row"]]
            q = packet["quotes"][scene, sy]
            anchor = (q["ask"][d] if focus["side"] > 0 else q["bid"][d]) if cut else focus["entry"]
            until = right if cut else min(right, times[focus["exit_row"]])
            lo, hi = (max(left, arm_t)-start)/60., (until-start)/60.
            ax.hlines(focus["boundary"], lo, hi, color="#f0ca57", linewidth=1.5, label="準備時の固定突破線")
            ax.hlines(anchor-focus["side"]*focus["width"], (point_t-start)/60.-(.5 if cut else 0), hi,
                      color="#ff667f", linestyle="--", label="初期停止線")
            ax.hlines(anchor+focus["side"]*focus["activation"]*focus["width"], lo, hi,
                      color="#56df9a", linestyle="--", label="保護開始線")
            if not cut:
                valid = q["quote_valid"][e:x+1]
                mark = q["bid"][e:x+1] if focus["side"]>0 else q["ask"][e:x+1]
                move = np.where(valid, focus["side"]*(mark-anchor), -np.inf)
                peak = np.maximum.accumulate(np.maximum(move, 0.))
                floor = np.where(peak >= focus["activation"]*focus["width"],
                                 np.maximum(-focus["width"], peak-focus["trail"]*focus["width"]), -focus["width"])
                ax.plot((times[e:x+1]-start)/60., anchor+focus["side"]*floor,
                        color="#f5a2e5", linewidth=1.1, label="当時までの清算気配で作る停止線")
            else:
                ax.scatter((point_t-start)/60., ready["last"][d], marker="o", color="#ffffff", s=50, zorder=8)
                ax.text((point_t-start)/60., ready["last"][d], " 発注判断\n（約定は未観測）", ha="right", fontsize=9)
            lower, upper = ax.get_ylim()
            levels = [focus["boundary"], anchor-focus["side"]*focus["width"],
                      anchor+focus["side"]*focus["activation"]*focus["width"]]
            lower, upper = min(lower, min(levels)), max(upper, max(levels))
            margin = (upper-lower)*.04
            ax.set_ylim(lower-margin, upper+margin)
        ax.legend(loc="upper left", fontsize=8)
    # ----------------------------------------
    # 指標は公開済み列のまま描く。足の見かけの変化から未来方向を補完しない。
    m = packet["markets"][scene, symbol]
    h = history[symbol+"__history"]
    ids = np.flatnonzero((times >= left) & (times <= right))
    if cut:
        ids = ids[ids <= focus["decision_row"]]
    ids = ids[np.r_[True, np.diff(np.floor(times[ids]/5.)) > 0]] if len(ids) else ids
    for col, label, sy, style in ((4,"自己30秒",symbol,":"),(5,"自己120秒",symbol,"-"),
                                (6,"相手30秒",other,":"),(7,"相手120秒",other,"-")):
        axes[2].plot((times[ids]-start)/60., m[ids, col], color=COLORS[sy], linestyle=style, linewidth=1., label=label)
    for col, denominator, label, sy, style in ((6,2,"自己5分",symbol,":"),(7,2,"自己20分",symbol,"-"),
                                             (10,3,"相手5分",other,":"),(11,3,"相手20分",other,"-")):
        ratio = np.divide(h[ids,col],m[ids,denominator],out=np.full(len(ids),np.nan),where=m[ids,denominator]>0)
        axes[3].plot((times[ids]-start)/60., ratio, color=COLORS[sy], linestyle=style, linewidth=1., label=label)
    for ax in axes[2:]:
        ax.axhline(0., color="#adb9cb", linewidth=.7)
        ax.set_ylabel("変化／ATR")
        ax.legend(loc="upper left", ncol=4, fontsize=8)
    for ax in axes:
        ax.grid(alpha=.4)
        ax.set_xlim((left-start)/60., (right-start)/60.+(.4 if cut else 0))
        if focus:
            ax.axvline((times[focus["decision_row"]]-start)/60., color="#ffffff", linestyle=":", linewidth=.8)
            if not cut:
                ax.axvline((times[focus["exit_row"]]-start)/60., color="#ed7387", linestyle=":", linewidth=.8)
        if left < ready["us_open"] < right:
            ax.axvline((ready["us_open"]-start)/60., color="#f0ca57", linestyle="--", linewidth=.8)
    axes[-1].xaxis.set_major_locator(MultipleLocator(60 if not focus else 10 if (right-left)<7200 else 20))
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda value, _: datetime.fromtimestamp(start+value*60., JST).strftime("%H:%M")))
    axes[-1].set_xlabel("日本時間（ナイトは日付を跨ぐ）")
    subject = "全場：N36＝水色／N27＝紫、▲買い・▼売り・×返済"
    if focus:
        subject = f"{symbol} {focus['method']} {focus['number']}番 {focus['direction']}　" + ("発注判断まで／当分足も判断行で切断" if cut else f"{focus['entry_time'][11:19]} → {focus['exit_time'][11:19]}　{focus['net']:+,.0f}円")
        if control and not cut:
            subject = "似た入口の勝ち対照　" + subject
    fig.suptitle(scene+"　"+subject, fontsize=15, y=.985)
    foot = "保存済み取引の描画。ラージ気配をミニ5枚／マイクロ10枚へ換算・手数料後。原時計は価格時刻で実受信時刻ではない。"
    if cut:
        foot += " 停止・開始線は判断時気配起点の予定水準。約定値・返済・成績は表示しない。"
    else:
        foot += " 足は観測Lastから再集計した事後表示。下段だけ当時の遅延公開指標。"
    fig.text(.015,.012,foot,fontsize=9,color="#b9c5d7")
    fig.tight_layout(rect=(0,.035,1,.965))
    fig.savefig(path,dpi=150)
    plt.close(fig)


def main() -> None:
    """
    機能: 夜間最悪場と入口までの図、類似した勝ち対照を新領域へ保存する。
    引数: なし。
    返り値: None。金融源と既存成果物は変更しない。
    """
    IMAGES.mkdir(parents=True,exist_ok=True)
    rows, refs, results = collect()
    selections = {}
    for sy in ("NK225","TOPIX"):
        candidates=[r for r in results["N36"]["rows"] if r["method"]=="N36" and r["symbol"]==sy]
        selections[sy] = sorted(candidates,key=lambda r:r["net"])[:3]
    scenes = sorted({r["session"] for choices in selections.values() for r in choices})
    targets=[]
    for sy, choices in selections.items():
        for s in choices:
            losses=sorted([r for r in rows if r["method"]=="N36" and r["symbol"]==sy and r["session"]==s["session"] and r["net"]<0],key=lambda r:r["net"])
            targets.extend(losses[:2 if sy=="NK225" else 1])
    # ----------------------------------------
    # 対照は同商品・同方向の勝ちから入口以前の数値の近さだけで選ぶ。収益最大順では選ばない。
    controls=[]
    fields=("own5","own20","peer5","peer20","er20","boundary_distance","sixty_change","spread_r")
    for base in (targets[0],next(r for r in targets if r["symbol"]=="TOPIX")):
        eligible=[r for r in rows if r["method"]=="N36" and r["symbol"]==base["symbol"] and r["side"]==base["side"] and r["net"]>0]
        data=np.array([[r["observable"][k] for k in fields] for r in eligible])
        scale=np.maximum(np.nanstd(data,axis=0),.1)
        origin=np.array([base["observable"][k] for k in fields])
        distance=np.sum(((data-origin)/scale)**2,axis=1)
        chosen=dict(eligible[int(np.argmin(distance))])
        chosen["control_for"]=dict(session=base["session"],symbol=base["symbol"],number=base["number"])
        chosen["similarity_fields"]=list(fields)
        controls.append(chosen)
    targets.extend(controls)
    special=dict(next(r for r in rows if r["method"]=="N27" and r["symbol"]=="NK225" and
                      r["session"]=="2026-10-08_Night" and r["number"]==5))
    special["special"]="板再評価"
    targets.append(special)
    all_scenes=sorted(set(scenes)|{r["session"] for r in targets})
    images=[]
    for scene in all_scenes:
        ref=refs[scene]
        packet=pickle.loads((ROOT/ref["path"]).read_bytes())
        with np.load(ROOT/ref["features"]["path"],allow_pickle=False) as hs:
            if scene in scenes:
                path=IMAGES/f"{scene}_全場比較.png"
                draw(scene,packet,hs,rows,path)
                images.append(dict(path=path.relative_to(ROOT).as_posix(),kind="全場",session=scene))
                print("画像",path,flush=True)
            for target in [r for r in targets if r["session"]==scene]:
                control="control_for" in target
                tag=target.get("special","勝ち対照" if control else "負け")
                for cut in (False,True):
                    path=IMAGES/f"{scene}_{target['symbol']}_{target['number']:02d}_{tag}_{'入口まで' if cut else '局所'}.png"
                    draw(scene,packet,hs,rows,path,target,cut,control)
                    images.append(dict(path=path.relative_to(ROOT).as_posix(),kind="入口まで" if cut else "局所",
                                       session=scene,symbol=target["symbol"],number=target["number"],control=control))
                    print("画像",path,flush=True)
    output=dict(passed=True,rows=rows,selection=selections,targets=targets,images=images,
                scope="保存全夜間から各商品N36最悪三場と同時刻両市場を描画。金融核の実行なし。",
                financial_replays=0,API=0,source_manifest=str((OLD/"入力準備.json").relative_to(ROOT)),
                producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/"夜間図の索引と全入口の当時特徴.json").write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
