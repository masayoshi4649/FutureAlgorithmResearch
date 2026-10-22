"""D17の保存注文と準備済み入力を、因果接頭画像と全経路画像へ描く。"""

import hashlib
import json
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/daynight128_20261020"
JST = timezone(timedelta(hours=9))
READS = []


def read_json(path: Path) -> dict:
    """
    機能: 既存JSON資料をUTF-8で読む。
    引数: path(Path)は元資料。
    返り値: dictは保存内容。
    """
    raw = path.read_bytes()
    READS.append(dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(raw).hexdigest()))
    return json.loads(raw)


def read_fixed(ref: dict) -> bytes:
    """
    機能: 指紋固定済み資料を照合して読む。
    引数: ref(dict)はpathとsha256を持つ参照。
    返り値: bytesは照合済みの元内容。
    """
    raw = (ROOT / ref["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ref["sha256"]
    READS.append(dict(path=ref["path"], sha256=ref["sha256"]))
    return raw


def clock(value: float) -> str:
    """
    機能: 価格時計を日本時間の表示へ変換する。
    引数: value(float)はUTC秒。
    返り値: strは時分秒。
    """
    return datetime.fromtimestamp(float(value), JST).strftime("%H:%M:%S")


def candles(times: np.ndarray, prices: np.ndarray, start: float) -> np.ndarray:
    """
    機能: 与えた行までのLastを1分OHLCへ集約する。
    引数: times/prices(ndarray)は同じ接頭行、start(float)は場開始UTC秒。
    返り値: ndarrayは開始からの分・始高安終・末尾原行の6列。
    """
    minute = np.floor(times/60).astype(np.int64)
    first = np.r_[0, np.flatnonzero(np.diff(minute))+1]
    end = np.r_[first[1:]-1, len(times)-1]
    return np.column_stack(((minute[first]*60-start)/60, prices[first],
        np.maximum.reduceat(prices, first), np.minimum.reduceat(prices, first),
        prices[end], end))


def draw_candles(ax, bars: np.ndarray, label: str) -> None:
    """
    機能: 暗色背景へ1分OHLCを描く。
    引数: ax(Axes)は描画先、bars(ndarray)はOHLC、label(str)は軸名。
    返り値: None。
    """
    for x, opening, high, low, close, _ in bars:
        color = "#55d7ac" if close >= opening else "#f07883"
        ax.vlines(x+.5, low, high, color=color, linewidth=.8, alpha=.8)
        if close == opening:
            ax.hlines(close, x+.17, x+.83, color=color, linewidth=1.)
        else:
            ax.add_patch(Rectangle((x+.17, min(opening, close)), .66,
                                   abs(close-opening), facecolor=color, edgecolor=color, alpha=.8))
    ax.set_ylabel(label)


def trace_parent(ready: dict, quote: dict, orders: np.ndarray, cycle: np.ndarray, events: np.ndarray) -> dict:
    """
    機能: 既存親の現金・清算時価と既存0.75R損切り境界を診断用に再構成する。
    引数: ready/quote(dict)は保存入力、orders/cycle/events(ndarray)は既存約定。
    返り値: dictは時価と停止線。注文は生成せず、保存予約値との一致を確認する。
    """
    cid, entry_row, exit_row = int(cycle[0]), int(cycle[1]), int(cycle[2])
    owned = orders[orders[:, 2] == cid]
    entry = owned[owned[:, 7] == 1][0]
    side, quantity = int(entry[3]), int(entry[4])
    indices = np.arange(entry_row, exit_row+1)
    atr0 = float(cycle[5])
    ratios = np.where(np.isfinite(ready["atr"][indices]) & (ready["atr"][indices] > 0),
                      np.maximum(.75, np.minimum(1., ready["atr"][indices]/atr0)), 1.)
    fractions = np.minimum.accumulate(ratios)
    stop_amount = -quantity*atr0*fractions
    cash = np.zeros(len(indices))
    inventory = np.zeros(len(indices))
    fees = np.zeros(len(indices))
    top = ready["symbol"] == "TOPIX"
    mult, rate = (1000., 418) if top else (10., 110)
    for order in owned:
        pos = int(order[0])-entry_row
        cash[pos:] -= order[3]*order[4]*order[5]
        inventory[pos:] += order[3]*order[4]
        fees[pos:] += int(order[4])*rate//10
    good = quote["quote_valid"] & np.isfinite(quote["bid"]) & np.isfinite(quote["ask"])
    good &= (quote["bid"] > 0) & (quote["ask"] > quote["bid"])
    last_good = np.maximum.accumulate(np.where(good, np.arange(len(good)), -1))
    assert (last_good[indices] >= 0).all()
    mark = quote["bid" if side > 0 else "ask"][last_good[indices]]
    equity = (cash+inventory*mark)*mult
    stop_price = np.full(len(indices), np.nan)
    active = inventory != 0
    stop_price[active] = (stop_amount[active]-cash[active])/inventory[active]
    for event in events[(events[:, 2] == cid) & (events[:, 1] == 9) & (events[:, 13] == 32)]:
        index = int(event[0])-entry_row
        assert np.isclose(stop_amount[index], event[7])
    return dict(cid=cid, side=side, indices=indices, equity=equity,
        net_equity=equity-fees, stop_amount=stop_amount*mult, stop_price=stop_price,
        source_row=int(entry[1]), entry_row=entry_row, exit_row=exit_row,
        quantity=quantity, entry_price=float(entry[5]), net=float(equity[-1]-fees[-1]),
        fixed_atr=atr0, maximum_gross=float(equity.max()),
        maximum_time=clock(ready["time_s"][indices[int(equity.argmax())]]),
        minimum_gross=float(equity.min()), entry_time=clock(ready["time_s"][entry_row]),
        exit_time=clock(ready["time_s"][exit_row]))


def draw_case(packet: dict, history: dict, actual: dict, scene: str, symbol: str,
              focus: int, prefix: bool, category: str, session_net: float) -> tuple:
    """
    機能: 自己・他方市場・短期支持・既存清算損益を同じ時間軸へ描く。
    引数: packet/history/actual(dict)、scene/symbol/category(str)、focus(int)、prefix(bool)、session_net(float)。
    返り値: tuple[Path, list[dict]]はPNGと親診断。接頭図には判断後の行を混ぜない。
    """
    key = scene, symbol
    peer = "NK225" if symbol == "TOPIX" else "TOPIX"
    ready, quote = packet["inputs"][key], packet["quotes"][key]
    other = packet["inputs"][scene, peer]
    market = packet["markets"][key]
    traces = [trace_parent(ready, quote, actual["orders"], c, actual["execution_events"]) for c in actual["cycles"]]
    selected = next(x for x in traces if x["cid"] == focus)
    source = selected["source_row"]
    own_end = source if prefix else len(ready["time_s"])-1
    cutoff = ready["time_s"][own_end]
    # ----------------------------------------
    # 接頭図の相手市場は、その判断時に採用済みだった相手観測時刻までに制限する。
    peer_cutoff = market[source, 8] if prefix else cutoff
    other_end = int(np.searchsorted(other["time_s"], peer_cutoff, side="right")-1)
    assert other_end >= 0
    own_bars = candles(ready["time_s"][:own_end+1], ready["last"][:own_end+1], ready["start"])
    peer_bars = candles(other["time_s"][:other_end+1], other["last"][:other_end+1], ready["start"])
    fig, axes = plt.subplots(4, 1, figsize=(17, 13), sharex=True,
        gridspec_kw=dict(height_ratios=[3.1, 2.1, 1.4, 1.8]))
    fig.patch.set_facecolor("#0d1422")
    for ax in axes:
        ax.set_facecolor("#121d2f")
        ax.grid(color="#394456", alpha=.45, linewidth=.6)
        ax.tick_params(colors="#e0e6ed", labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#465266")
        ax.yaxis.label.set_color("#e0e6ed")
    draw_candles(axes[0], own_bars, symbol+" 価格")
    draw_candles(axes[1], peer_bars, peer+" 価格")
    for ax, bars, h in ((axes[0], own_bars, history[symbol]), (axes[1], peer_bars, history[peer])):
        positions = bars[:, 5].astype(int)
        ax.plot(bars[:, 0]+.5, h[positions, 1], color="#d7c27f", lw=1., label="当時公開済み20分平均")
        ax.legend(loc="upper left", fontsize=8, facecolor="#121d2f", labelcolor="#e0e6ed")
    sampled = own_bars[:, 5].astype(int)
    xx = (ready["time_s"][sampled]-ready["start"])/60
    axes[2].step(xx, market[sampled, 4], where="post", color="#66b8ff", label="自己30秒差/ATR")
    axes[2].step(xx, market[sampled, 6], where="post", color="#efb7fc", label="他方30秒差/ATR")
    axes[2].axhline(0, color="#a0a9b8", lw=.7)
    axes[2].axhline(.05, color="#ad9d72", lw=.6, ls=":")
    axes[2].axhline(-.05, color="#ad9d72", lw=.6, ls=":")
    axes[2].set_ylabel("短期支持\n毎分末尾の表示")
    axes[2].legend(loc="upper left", ncol=2, fontsize=8, facecolor="#121d2f", labelcolor="#e0e6ed")
    selected_x = (ready["time_s"][source]-ready["start"])/60
    for ax in axes:
        ax.axvline(selected_x, color="#f6df85", lw=1., ls="--", alpha=.9)
    if prefix:
        direction = "買い" if selected["side"] > 0 else "売り"
        axes[0].scatter([selected_x], [ready["last"][source]], color="#f6df85", marker="*", s=135, zorder=9)
        axes[0].annotate("発注判断 "+clock(cutoff)+" "+direction,
            (selected_x, ready["last"][source]), xytext=(-150, 20), textcoords="offset points",
            color="#f6df85", fontsize=10, arrowprops=dict(arrowstyle="->", color="#f6df85"))
        axes[3].axis("off")
        own30, peer30 = market[source, 4], market[source, 6]
        text = (f"この図は親{focus}の発注判断まで。未来の価格・約定・損益は非表示。\n"
                f"当時の30秒差/ATR：自己 {own30:+.3f} ／ 他方 {peer30:+.3f}\n"
                f"当時の20分変化：自己 {history[symbol][source,7]:+.2f} ／ 他方 {history[symbol][source,11]:+.2f}\n"
                f"右端の1分足は判断時点で途切れた未完成足。相手は判断時に利用済みの観測まで。")
        axes[3].text(.02, .8, text, transform=axes[3].transAxes, color="#e0e6ed", va="top", fontsize=11, linespacing=1.7)
        headline = f"D17｜{scene}｜{symbol}｜親{focus}の判断直前まで"
    else:
        for trace in traces:
            owned = actual["orders"][actual["orders"][:, 2] == trace["cid"]]
            color = "#65d9b0" if trace["side"] > 0 else "#f08792"
            x = (ready["time_s"][trace["indices"]]-ready["start"])/60
            stride = np.r_[0, np.flatnonzero(np.diff(np.floor(x*4)))+1, len(x)-1]
            axes[0].plot(x[stride], trace["stop_price"][stride], color="#f4ad68", lw=.9, alpha=.9)
            axes[3].plot(x[stride], trace["equity"][stride]/1000, color=color, lw=1.0)
            axes[3].plot(x[stride], trace["stop_amount"][stride]/1000, color="#f4ad68", lw=.8, ls="--")
            for order in owned:
                t = (ready["time_s"][int(order[0])]-ready["start"])/60
                entry = order[7] == 1
                axes[0].scatter([t], [order[5]], color=color if entry else "#f4f0ca",
                    marker=("^" if order[3] > 0 else "v") if entry else "x", s=45 if entry else 30, zorder=9)
                if entry:
                    axes[0].annotate(("買" if trace["side"] > 0 else "売")+str(trace["cid"]),
                        (t, order[5]), xytext=(3, 12 if trace["side"] > 0 else -17),
                        textcoords="offset points", color=color, fontsize=9, fontweight="bold")
            endx = (ready["time_s"][trace["exit_row"]]-ready["start"])/60
            axes[3].annotate(f"{trace['cid']}:{trace['net']/1000:+.1f}千円",
                (endx, trace["equity"][-1]/1000), xytext=(2, 7), textcoords="offset points",
                fontsize=8, color="#e0e6ed")
        axes[3].axhline(0, color="#c7d0df", lw=.8)
        axes[3].set_ylabel("親の料前清算価値\n／損切り境界（千円）")
        axes[3].text(.01, .98, "緑＝買い親 ／ 赤＝売り親 ／ 橙破線＝0.75Rまでの単調縮小損切り\n末尾の数値だけは手数料後。追加半益床なし。",
            transform=axes[3].transAxes, va="top", fontsize=8, color="#cbd4df",
            bbox=dict(facecolor="#121d2f", alpha=.8, edgecolor="none"))
        headline = f"D17｜{scene}｜{symbol}｜全経路（手数料後 {session_net:+,.0f}円）"
    max_x = (cutoff-ready["start"])/60
    axes[-1].set_xlim(0, max_x+max(1., max_x*.015))
    axes[-1].xaxis.set_major_locator(MultipleLocator(15 if prefix and max_x < 150 else 30))
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda x, _: clock(ready["start"]+x*60)[:5]))
    axes[-1].set_xlabel("日本時間（保存価格時計）", color="#e0e6ed")
    fig.suptitle(headline, color="#f3f5fa", fontsize=15, y=.985)
    fig.text(.05, .012,
        "保存Lastから作成した1分OHLC／ラージ板代理の実約定位置。上段橙線は実損切り価格を再構成し予約値と照合。"
        "元影の連続トレール値は未保存のため描かず、返済は×で表示。", color="#b8c3d4", fontsize=8)
    fig.tight_layout(rect=[.02, .035, .99, .97])
    directory = HERE / "images"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{category}_{symbol}_{scene}_親{focus}_{'入口まで' if prefix else '全経路'}.png"
    path = directory/name
    fig.savefig(path, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    summaries = []
    for trace in traces:
        row = trace["source_row"]
        fields = {k: v for k, v in trace.items() if not isinstance(v, np.ndarray)}
        fields.update(source_time=clock(ready["time_s"][row]), source_market=market[row].tolist(),
            source_history=history[symbol][row].tolist())
        summaries.append(fields)
    return path, summaries


def clean(value):
    """
    機能: JSONへ保存できないNaNとNumPy数値を通常型へ変換する。
    引数: value(object)は診断値。
    返り値: objectはUTF-8 JSONに保存できる再帰構造。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main() -> None:
    """
    機能: 各商品最悪3場と買い継続の勝ち対照を保存画像へ出力する。
    引数: なし。
    返り値: None。既存00128不変、金融再生は0回。
    """
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    manifest = read_json(OLD/"入力準備.json")
    measured = read_json(OLD/"round3/全条件の会計.json")
    verified = read_json(OLD/"diagnosis_day/第三巡D17の保存注文と拒否親差の独立確認.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    caches = {(r["session"], r["symbol"]): r for r in measured["cache"]}
    cases = []
    for product in verified["products"]:
        for scene in product["worst_three"]:
            cases.append((scene["session"], product["symbol"], "赤字上位", scene["net"]))
    # ----------------------------------------
    # 同じ買い側で中期継続を得た場を、視覚的な反例として別に表示する。
    for symbol in ("TOPIX", "NK225"):
        row = next(r for r in measured["rows"] if r["method"] == "D17" and r["symbol"] == symbol and r["session"] == "2026-10-19_Day")
        cases.append(("2026-10-19_Day", symbol, "買い勝ち対照", row["net"]))
    outputs, data = [], {}
    from io import BytesIO
    for scene, symbol, category, net in cases:
        if scene not in data:
            packet = pickle.loads(read_fixed(refs[scene]))
            with np.load(BytesIO(read_fixed(refs[scene]["features"])), allow_pickle=False) as stored:
                history = {s: stored[s+"__history"].copy() for s in ("TOPIX", "NK225")}
            data[scene] = packet, history
        packet, history = data[scene]
        with np.load(BytesIO(read_fixed(caches[scene, symbol])), allow_pickle=False) as stored:
            actual = {f: stored["D17__"+f].copy() for f in ("orders", "cycles", "execution_events")}
        mult, rate = (1000., 418) if symbol == "TOPIX" else (10., 110)
        values = []
        for cycle in actual["cycles"]:
            owned = actual["orders"][actual["orders"][:, 2] == cycle[0]]
            fees = int((owned[:, 4].astype(np.int64)*rate//10).sum())
            values.append((cycle[3]*mult-fees, int(cycle[0])))
        focus = (min(values) if category == "赤字上位" else max(values))[1]
        for prefix in (True, False):
            path, parents = draw_case(packet, history, actual, scene, symbol, focus, prefix, category, net)
            outputs.append(dict(path=str(path.relative_to(ROOT)), scene=scene, symbol=symbol,
                category=category, prefix=prefix, focus_parent=focus, net=net, parents=parents))
            print(str(path), flush=True)
    proof = dict(passed=True, images=outputs, reads=READS,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0, original_market_reads=0, API=0,
        scope="保存注文と既存公開入力の可視化・会計線再構成。接頭図は判断原行まで、相手は当時採用済みの時刻まで。",
        limitation="保存価格時計は板受信時計ではない。元影の連続トレーリング線は未保存で表示しない。勝ち対照は指定した一場で全勝ちの代表性を主張しない。")
    (HERE/"描画資料と親会計.json").write_text(json.dumps(clean(proof), ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
