"""日中の無取引・上昇場の弱さを保存原行から診断する。新金融再生は行わない。"""

import hashlib
import json
import pickle
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
READS = []
HOLIDAYS = {"2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12"}
FOCUS = {("2026-09-21_Day", "TOPIX"), ("2026-10-12_Day", "TOPIX"),
         ("2026-10-09_Day", "NK225"), ("2026-10-16_Day", "TOPIX"),
         ("2026-10-19_Day", "TOPIX")}


def read(path, expected=None):
    """
    機能: 保存資料を読み、指定があればSHA256を照合する。
    引数: path(Path又はstr)はルート相対又は絶対位置、expected(str又はNone)は指紋。
    返り値: bytesは読み取った内容。
    """
    path = ROOT / path
    value = path.read_bytes()
    digest = hashlib.sha256(value).hexdigest()
    if expected is not None:
        assert digest == expected, str(path)
    READS.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=digest))
    return value


def clock(value):
    """
    機能: 価格時計を日本時間で表示する。
    引数: value(float)はUTC秒。
    返り値: strは時分秒。
    """
    return datetime.fromtimestamp(float(value), JST).strftime("%H:%M:%S")


def phase(value, holiday):
    """
    機能: 事前公表される日本現物時刻で区分する。
    引数: value(float)はUTC秒、holiday(bool)は現物休場。
    返り値: strは区分名。休場日には現物寄り・再開を仮定しない。
    """
    if holiday:
        return "現物休場日"
    minute = datetime.fromtimestamp(float(value), JST).hour * 60 + datetime.fromtimestamp(float(value), JST).minute
    if minute < 540:
        return "現物開始前"
    if minute < 690:
        return "現物前場"
    if minute < 750:
        return "現物昼休み"
    if minute < 930:
        return "現物後場"
    return "現物終了後"


def point(ready, quote, market, history, row, peer):
    """
    機能: 原行の値と厳密過去の相手価格時計を取り出す。
    引数: ready/quote/peer(dict)、market/history(ndarray)、row(int)は当時資料。
    返り値: dictは当時値。将来値は含めない。
    """
    now = ready["time_s"][row]
    j = int(np.searchsorted(peer["time_s"], now, side="left") - 1)
    return dict(row=int(row), seq=int(ready["seq"][row]), time=clock(now),
        price=float(ready["last"][row]), bid=float(quote["bid"][row]), ask=float(quote["ask"][row]),
        atr=float(ready["atr"][row]), own30=float(market[row, 4]), peer30=float(market[row, 6]),
        market_known=bool(market[row, 11] == 1), own20=float(history[row, 7]), peer20=float(history[row, 11]),
        own20_high=float(history[row, 3]), own20_low=float(history[row, 4]),
        peer_clock=clock(peer["time_s"][j]) if j >= 0 else None,
        peer_age=float(now-peer["time_s"][j]) if j >= 0 else None,
        peer_last=float(peer["last"][j]) if j >= 0 else None,
        phase=phase(now, ready["session"][:10] in HOLIDAYS))


def inspect_feed(ready, quote, market, history, feed, peer):
    """
    機能: 旧候補の拒否理由と、同じ影内で資料が回復した最初の接触を分類する。
    引数: ready/quote/peer(dict)、market/history/feed(ndarray)は保存資料。
    返り値: list[dict]は候補ごとの観測分類。約定・出口・損益は新生成しない。
    """
    out = []
    good = quote["quote_valid"] & np.isfinite(quote["bid"]) & np.isfinite(quote["ask"])
    good &= (quote["bid"] > 0) & (quote["ask"] > quote["bid"])
    for order in feed[feed[:, 7] == 1]:
        row, parent, side = int(order[0]), int(order[2]), int(order[3])
        owned = feed[feed[:, 2] == parent]
        final = int(owned[-1, 0])
        candidate = point(ready, quote, market, history, row, peer)
        okay = (market[:, 11] == 1) & np.isfinite(market[:, 4]) & np.isfinite(market[:, 6])
        okay &= (side*market[:, 4] >= -.05) & (side*market[:, 6] >= -.05)
        candidate.update(parent=parent, side=side, initial_R=float(order[9]), accepted=bool(okay[row]),
            paper_exit_time=clock(ready["time_s"][final]), paper_exit_row=final,
            paper_exit_price=float(owned[-1, 5]), paper_events=[
                dict(row=int(x[0]), time=clock(ready["time_s"][int(x[0])]), side=int(x[3]),
                     quantity=int(x[4]), price=float(x[5]), entry=bool(x[7])) for x in owned])
        use = np.arange(row + 1, final)
        entry_quote = quote["ask" if side > 0 else "bid"]
        admissible = okay & good & ((quote["ask"]-quote["bid"]) <= .5*order[9])
        if not okay[row]:
            candidate["reason"] = "資料未知" if not np.isfinite(market[row, [4, 6]]).all() or market[row,11] != 1 else "明確な短期逆行"
            for name, mask in (
                ("first_recovered", admissible),
                ("first_recovered_no_worse", admissible & (side*(entry_quote-entry_quote[row]) <= 0)),
                ("first_recovered_medium_support", admissible & (side*history[:,7] > 0) & (side*history[:,11] > 0)),
            ):
                possible = use[mask[use]]
                candidate[name] = point(ready, quote, market, history, int(possible[0]), peer) if len(possible) else None
        # ----------------------------------------
        # 観測終点を元影終了に固定した事後値幅。新運転の勝敗・収支ではない。
        path = side * (ready["last"][row:final+1] - ready["last"][row])
        candidate["posthoc_original_shadow_path"] = dict(maximum=float(path.max()), minimum=float(path.min()),
            end=float(path[-1]), endpoint="元影の最終返済通知行。Last差であり約定損益ではない。")
        out.append(candidate)
    return out


def candles(times, prices, start):
    """
    機能: 指定した接頭だけを1分足へ集約する。
    引数: times/prices(ndarray)は原時計とLast、start(float)は場開始。
    返り値: ndarrayは分・始高安終の5列。
    """
    minute = np.floor(times / 60).astype(np.int64)
    begin = np.r_[0, np.flatnonzero(np.diff(minute)) + 1]
    end = np.r_[begin[1:]-1, len(times)-1]
    return np.column_stack(((minute[begin]*60-start)/60, prices[begin],
        np.maximum.reduceat(prices, begin), np.minimum.reduceat(prices, begin), prices[end]))


def picture(packet, hist, scene, symbol, feed_info, actual, cutoff=None):
    """
    機能: 両市場の1分足、保存候補・実売買を画像にする。
    引数: packet/hist(dict)、scene/symbol(str)、feed_info(list)、actual(dict)、cutoff(int又はNone)。
    返り値: strはPNG相対位置。接頭画像の縦軸・横軸も接頭資料のみから決める。
    """
    own = packet["inputs"][scene, symbol]
    other = "NK225" if symbol == "TOPIX" else "TOPIX"
    now = own["time_s"][cutoff] if cutoff is not None else own["time_s"][-1]
    fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True,
        gridspec_kw=dict(height_ratios=[3, 2.4, 1.4]))
    fig.patch.set_facecolor("#0d1422")
    for ax in axes:
        ax.set_facecolor("#121d2f")
        ax.tick_params(colors="#e0e6ed")
        ax.yaxis.label.set_color("#e0e6ed")
        ax.grid(color="#394456", alpha=.5)
        for spine in ax.spines.values():
            spine.set_color("#465266")
    for ax, product in zip(axes[:2], (symbol, other)):
        ready = packet["inputs"][scene, product]
        count = np.searchsorted(ready["time_s"], now, side="right" if product == symbol else "left")
        if product == symbol and cutoff is not None:
            count = cutoff + 1
        bars = candles(ready["time_s"][:count], ready["last"][:count], own["start"])
        for x, opening, high, low, close in bars:
            color = "#55d7ac" if close >= opening else "#f07883"
            ax.vlines(x+.5, low, high, color=color, lw=.8)
            ax.add_patch(Rectangle((x+.18, min(opening, close)), .64, max(abs(close-opening), .01),
                                  facecolor=color, edgecolor=color, alpha=.85))
        # ----------------------------------------
        # 開場15分範囲は、9時以後にだけ過去の値から表示する。
        t = ready["time_s"][:count]
        if now >= own["start"]+900:
            early = ready["last"][:count][t < own["start"]+900]
            if len(early):
                ax.hlines([early.max(), early.min()], 15, (now-own["start"])/60,
                          color="#d7c27f", ls=":", lw=.8, label="開場15分の高安")
        ax.set_ylabel(product+" Last")
    for event in feed_info:
        if own["time_s"][event["row"]] > now:
            continue
        x = (own["time_s"][event["row"]]-own["start"])/60
        axes[0].scatter(x, event["price"], marker="^" if event["side"]>0 else "v", s=65,
            facecolors="none", edgecolors="#f7c95f", lw=1.6, zorder=5)
        axes[0].annotate(("採用" if event["accepted"] else "拒否")+event["time"],
            (x, event["price"]), xytext=(4, 13), textcoords="offset points", color="#f7c95f", fontsize=8)
    for order in actual.get("orders", []):
        row = int(order[0])
        if own["time_s"][row] > now:
            continue
        x = (own["time_s"][row]-own["start"])/60
        axes[0].scatter(x, order[5], marker="o" if order[7] else "x",
            color="#79aaff" if order[3]>0 else "#ed9be7", s=42, zorder=6)
    market = packet["markets"][scene, symbol]
    count = cutoff+1 if cutoff is not None else len(own["time_s"])
    sample = np.r_[0, np.flatnonzero(np.diff(np.floor(own["time_s"][:count]/60)))+1]
    x = (own["time_s"][sample]-own["start"])/60
    axes[2].step(x, market[sample,4], where="post", color="#79aaff", label="自己30秒/ATR")
    axes[2].step(x, market[sample,6], where="post", color="#ed9be7", label="相手30秒/ATR")
    axes[2].axhline(0, color="#b8c4d5", lw=.7)
    axes[2].set_ylabel("短期差（欠測は線の空白）")
    axes[2].legend(facecolor="#121d2f", labelcolor="#e0e6ed")
    for line in (15, 165, 225, 405):
        if line < (now-own["start"])/60:
            for ax in axes:
                ax.axvline(line, color="#6c758a", ls="--", lw=.6)
    axes[-1].set_xlim(0, (now-own["start"])/60+1)
    axes[-1].xaxis.set_major_locator(MultipleLocator(30))
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda value, _: clock(own["start"]+value*60)[:5]))
    suffix = "全経路" if cutoff is None else "判断まで_"+clock(now).replace(":", "")
    fig.suptitle(scene+" "+symbol+" "+suffix+"  黄色=旧候補 / 青紫=既存実売買\n"+
        ("現物休場日" if scene[:10] in HOLIDAYS else "通常日")+
        " ／ 後日の高安は入口条件に使用しない", color="#e0e6ed", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, .945))
    target = HERE/"画像"/(scene+"_"+symbol+"_"+suffix+".png")
    target.parent.mkdir(exist_ok=True)
    fig.savefig(target, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    return target.relative_to(ROOT).as_posix()


def clean(value):
    """
    機能: NumPy値と非有限値をJSONの保存形式へ変換する。
    引数: value(object)は元値。
    返り値: objectはJSON互換値。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main():
    """
    機能: 全22日中の旧候補・既存実親を分類し、無取引と上昇日を描画する。
    引数: なし。
    返り値: None。金融再生・現在取得・旧資料変更は行わない。
    """
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    manifest = json.loads(read("work/daynight128_20261020/入力準備.json"))
    accounting = json.loads(read("work/visual_pdca129_20261020/day_round2/全条件の会計.json"))
    caches = {(r["session"],r["symbol"]):r for r in accounting["cache"]}
    scenes, all_parents, images = [], [], []
    for ref in manifest["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Day"):
            continue
        packet = pickle.loads(read(ref["path"], ref["sha256"]))
        with np.load(BytesIO(read(ref["features"]["path"], ref["features"]["sha256"]))) as saved:
            hist = {s:saved[s+"__history"].copy() for s in ("TOPIX","NK225")}
            feeds = {s:saved[s+"__feed"].copy() for s in ("TOPIX","NK225")}
        for symbol, method in (("TOPIX","DV07"), ("NK225","DV05")):
            key = scene,symbol
            ready, quote, market = packet["inputs"][key],packet["quotes"][key],packet["markets"][key]
            peer = packet["inputs"][scene,"NK225" if symbol=="TOPIX" else "TOPIX"]
            candidates = inspect_feed(ready,quote,market,hist[symbol],feeds[symbol],peer)
            cache = caches[key]
            with np.load(BytesIO(read(cache["path"], cache["sha256"]))) as saved:
                actual = {f:saved[method+"__"+f].copy() for f in ("orders","cycles")}
            parents = []
            for cycle in actual["cycles"]:
                owned = actual["orders"][actual["orders"][:,2] == cycle[0]]
                entry = owned[owned[:,7] == 1][0]
                row,side = int(entry[0]), int(entry[3])
                mult,fee = (1000.,418) if symbol=="TOPIX" else (10.,110)
                net = float(cycle[3]*mult - (owned[:,4].astype(int)*fee//10).sum())
                value = point(ready,quote,market,hist[symbol],int(entry[1]),peer)
                value.update(scene=scene,symbol=symbol,method=method,parent=int(cycle[0]),side=side,
                    actual_entry_time=clock(ready["time_s"][row]),entry_price=float(entry[5]),
                    exit_time=clock(ready["time_s"][int(owned[-1,0])]),net=net,
                    session_rise=bool(ready["last"][-1] > ready["last"][0]))
                parents.append(value)
                all_parents.append(value)
            finite = (market[:,11] == 1) & np.isfinite(market[:,4]) & np.isfinite(market[:,6])
            minute_end = np.r_[np.flatnonzero(np.diff(np.floor(ready["time_s"]/60))),len(ready["time_s"])-1]
            scenes.append(dict(scene=scene,symbol=symbol,method=method,holiday=scene[:10] in HOLIDAYS,
                opening=float(ready["last"][0]),closing=float(ready["last"][-1]),
                minimum=float(ready["last"].min()),maximum=float(ready["last"].max()),
                total_net=sum(v["net"] for v in parents),entries=len(parents),
                known_minute_samples=int(finite[minute_end].sum()),minute_samples=len(minute_end),
                candidates=candidates,parents=parents))
            if key in FOCUS:
                images.append(picture(packet,hist,scene,symbol,candidates,actual))
                focus = candidates[0]["row"] if not parents else min(parents,key=lambda v:v["net"])["row"]
                if scene == "2026-10-19_Day" and parents:
                    focus = max(parents,key=lambda v:v["net"])["row"]
                images.append(picture(packet,hist,scene,symbol,candidates,actual,focus))
        print(scene+" 観測分類完了",flush=True)
    output = dict(passed=True,financial_replays=0,scope="旧保存注文の分類、原行の接触時刻・値幅・チャートのみ。新手法の収支ではない。",
        scenes=scenes,parents=all_parents,images=images,reads=READS,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        holidays=dict(dates=sorted(HOLIDAYS),source="JPX事前告知を別担当が確認。現物休場だが先物祝日取引。"))
    (HERE/"無取引と上昇日弱さの保存観測.json").write_text(json.dumps(clean(output),ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("保存完了。金融再生0。",flush=True)


if __name__ == "__main__":
    main()
