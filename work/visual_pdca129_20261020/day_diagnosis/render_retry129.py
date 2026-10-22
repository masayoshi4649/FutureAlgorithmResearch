"""再参加の当時資料と勝ち・負けの保存経路を比較表示する。"""

from io import BytesIO
import json
import pickle

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np

import render_day129 as source


CASES = (
    ("2026-10-16_Day", "TOPIX", 0),
    ("2026-10-01_Day", "TOPIX", 0),
    ("2026-09-28_Day", "NK225", 1),
    ("2026-09-29_Day", "NK225", 1),
    ("2026-09-29_Day", "NK225", 0),
)


def describe(row: int, ready: dict, market: np.ndarray, history: np.ndarray,
             side: int, anchor: np.ndarray, initial_atr: float, entry_history: np.ndarray) -> dict:
    """
    機能: 当時既知の再参加条件・初回基準との差・過去範囲を抽出する。
    引数: row(int)、ready(dict)、market/history/anchor/entry_history(ndarray)、side(int)、initial_atr(float)。
    返り値: dictは事後極値を使わない観測値。
    """
    m, h = market[row], history[row]
    boundary = entry_history[3] if side > 0 else entry_history[4]
    return dict(time=source.clock(ready["time_s"][row]), row=row,
        own_price=float(m[0]), peer_price=float(m[1]),
        old_anchor_own=float(anchor[0]), old_anchor_peer=float(anchor[1]),
        own_from_old_anchor_atr=float(side*(m[0]-anchor[0])/initial_atr),
        peer_from_old_anchor_atr=float(side*(m[1]-anchor[1])/anchor[3]),
        own30_signed=float(side*m[4]), peer30_signed=float(side*m[6]),
        own20_signed=float(side*h[7]), peer20_signed=float(side*h[11]),
        own_vs_current_mean20=float(side*(m[0]-h[1])),
        initial_prior20_boundary=float(boundary),
        own_vs_initial_boundary=float(side*(m[0]-boundary)),
        own20_efficiency=float(h[5]), peer20_efficiency=float(h[12]),
        own20_high=float(h[3]), own20_low=float(h[4]), source_market=m.tolist(),
        source_history=h.tolist())


def marked_equity(orders: np.ndarray, quote: dict, size: int, symbol: str) -> np.ndarray:
    """
    機能: 保存済み注文だけから指定親群の各行清算価値を復元する。
    引数: orders(ndarray)、quote(dict)、size(int)、symbol(str)は保存約定と価格資料。
    返り値: ndarrayは手数料後円損益。新しい売買判断は行わない。
    """
    mult, rate = (1000., 418) if symbol == "TOPIX" else (10., 110)
    cash = np.zeros(size)
    held = np.zeros(size)
    fees = np.zeros(size)
    for o in orders:
        i = int(o[0])
        cash[i:] -= o[3]*o[4]*o[5]
        held[i:] += o[3]*o[4]
        fees[i:] += int(o[4])*rate//10
    good = quote["quote_valid"] & np.isfinite(quote["bid"]) & np.isfinite(quote["ask"])
    good &= (quote["bid"] > 0) & (quote["ask"] > quote["bid"])
    previous = np.maximum.accumulate(np.where(good, np.arange(size), -1))
    active = held != 0
    assert (previous[active] >= 0).all()
    marks = np.where(held > 0, quote["bid"][np.maximum(previous, 0)],
                     quote["ask"][np.maximum(previous, 0)])
    return (cash+held*marks)*mult-fees


def draw(packet: dict, histories: dict, baseline: dict, revised: dict,
         scene: str, symbol: str, shadow: int, prefix: bool) -> tuple:
    """
    機能: 初回基準と再参加時の過去範囲を両市場の価格図へ描く。
    引数: packet/histories/baseline/revised(dict)、scene/symbol(str)、shadow(int)、prefix(bool)。
    返り値: tupleは画像位置と当時観測値。
    """
    ready = packet["inputs"][scene, symbol]
    quote = packet["quotes"][scene, symbol]
    market = packet["markets"][scene, symbol]
    peer = "NK225" if symbol == "TOPIX" else "TOPIX"
    other = packet["inputs"][scene, peer]
    mapping = revised["parent_mapping"]
    links = mapping[mapping[:, 1] == shadow]
    retry = links[links[:, 2] == 1][0]
    before = baseline["orders"][baseline["orders"][:, 2] == shadow]
    after = revised["orders"][np.isin(revised["orders"][:, 2], links[:, 0])]
    initial = before[before[:, 7] == 1][0]
    source_row, original_row = int(retry[3]), int(initial[0])
    side = int(initial[3])
    old_cycle = baseline["cycles"][baseline["cycles"][:, 0] == shadow][0]
    info = describe(source_row, ready, market, histories[symbol], side, market[original_row],
                    float(old_cycle[5]), histories[symbol][int(initial[1])])
    events = revised["execution_events"]
    initial_link = links[links[:, 2] == 0][0]
    fails = events[(events[:, 2] == initial_link[0]) & (events[:, 1] == 15)]
    info["first_withdrawal"] = describe(int(fails[0, 0]), ready, market, histories[symbol], side,
        market[original_row], float(old_cycle[5]), histories[symbol][int(initial[1])])
    info["entry_time"] = source.clock(ready["time_s"][original_row])
    last = source_row if prefix else max(int(before[-1, 0]), int(after[-1, 0]))
    cutoff = ready["time_s"][last]
    peer_cut = market[source_row, 8] if prefix else cutoff
    other_last = np.searchsorted(other["time_s"], peer_cut, side="right")-1
    bars = source.candles(ready["time_s"][:last+1], ready["last"][:last+1], ready["start"])
    peer_bars = source.candles(other["time_s"][:other_last+1], other["last"][:other_last+1], ready["start"])
    fig, axes = plt.subplots(3, 1, figsize=(17, 11), sharex=True,
                             gridspec_kw=dict(height_ratios=[3, 2.4, 2]))
    fig.patch.set_facecolor("#0d1422")
    for ax in axes:
        ax.set_facecolor("#121d2f")
        ax.grid(color="#394456", alpha=.45, linewidth=.6)
        ax.tick_params(colors="#e0e6ed", labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#465266")
        ax.yaxis.label.set_color("#e0e6ed")
    source.draw_candles(axes[0], bars, symbol)
    source.draw_candles(axes[1], peer_bars, peer)
    start_x = max(0., (ready["time_s"][original_row]-ready["start"])/60-25)
    retry_x = (ready["time_s"][source_row]-ready["start"])/60
    for k, (ax, own_bars, h) in enumerate(((axes[0], bars, histories[symbol]),
                                          (axes[1], peer_bars, histories[peer]))):
        positions = own_bars[:, 5].astype(int)
        ax.plot(own_bars[:, 0]+.5, h[positions, 1], color="#d7c27f", lw=1.,
                label="当時公開済み20分平均")
        ax.axhline(market[original_row, k], color="#8ab4f8", ls="--", lw=.8,
                   label="初回実新規時の既知Last")
        ax.axvline(retry_x, color="#f6df85", ls="--", lw=1.)
        # 横軸より前の既知足を縦軸へ残さず、表示区間の当時資料だけで範囲を確定する。
        visible = own_bars[:, 0]+1. >= start_x
        levels = np.r_[own_bars[visible, 2:4].ravel(), h[positions[visible], 1],
                       market[original_row, k]]
        if k == 0:
            levels = np.r_[levels, info["initial_prior20_boundary"]]
        levels = levels[np.isfinite(levels)]
        minimum, maximum = float(levels.min()), float(levels.max())
        margin = max((maximum-minimum)*.08, .5 if k == 0 and symbol == "TOPIX" else 1.)
        ax.set_ylim(minimum-margin, maximum+margin)
        info["own_axis" if k == 0 else "peer_axis"] = dict(
            lower=minimum-margin, upper=maximum+margin,
            observed_ohlc_low=float(own_bars[visible, 3].min()),
            observed_ohlc_high=float(own_bars[visible, 2].max()),
            cutoff_row=last if k == 0 else int(other_last),
            cutoff_clock=source.clock(cutoff if k == 0 else peer_cut))
        ax.legend(loc="upper left", fontsize=8, facecolor="#121d2f", labelcolor="#e0e6ed")
    boundary = info["initial_prior20_boundary"]
    axes[0].axhline(boundary, color="#c491d8", ls=":", lw=1., label="初回判断前20分の方向側端")
    for order in after:
        if int(order[0]) > last:
            continue
        x = (ready["time_s"][int(order[0])]-ready["start"])/60
        new = order[7] == 1.
        axes[0].scatter([x], [order[5]], marker=("^" if side > 0 else "v") if new else "x",
                        color="#55d7ac" if new else "#ffba88", s=60, zorder=5)
        axes[0].annotate(("新規" if new else "返済")+str(int(order[2])),
                        (x, order[5]), xytext=(4, 12 if new else -16),
                        textcoords="offset points", color="#e0e6ed", fontsize=9)
    if prefix:
        axes[0].scatter([retry_x], [ready["last"][source_row]], marker="*", s=140, color="#f6df85", zorder=6)
        axes[2].axis("off")
        text = (f"再参加判断 {info['time']} まで。未来の約定・価格・損益なし。\n"
                f"初回基準からの元方向差：自己 {info['own_from_old_anchor_atr']:+.3f} ATR ／ "
                f"相手 {info['peer_from_old_anchor_atr']:+.3f} ATR\n"
                f"20分の元方向変化：自己 {info['own20_signed']:+.2f} ／ 相手 {info['peer20_signed']:+.2f}\n"
                f"30秒の元方向変化：自己 {info['own30_signed']:+.3f} ATR ／ 相手 {info['peer30_signed']:+.3f} ATR\n"
                f"初回前20分の方向側端からの元方向差：{info['own_vs_initial_boundary']:+.2f}")
        axes[2].text(.015, .95, text, va="top", color="#e0e6ed", fontsize=11, linespacing=1.7,
                     transform=axes[2].transAxes)
    else:
        idx = bars[:, 5].astype(int)
        x = (ready["time_s"][idx]-ready["start"])/60
        for orders, name, color in ((before, "D17 元影全体", "#8ab4f8"),
                                     (after, "DV02 初回＋再参加", "#ffba88")):
            equity = marked_equity(orders, quote, len(ready["time_s"]), symbol)
            axes[2].plot(x, equity[idx]/1000, lw=1.25, label=f"{name}：最終 {equity[-1]:+,.0f}円", color=color)
        axes[2].axhline(0, color="#a9b4c4", lw=.7)
        axes[2].set_ylabel("手数料後清算価値（千円）")
        axes[2].legend(loc="upper left", fontsize=9, facecolor="#121d2f", labelcolor="#e0e6ed")
    xmax = (cutoff-ready["start"])/60
    axes[-1].set_xlim(start_x, xmax+max(1., (xmax-start_x)*.015))
    axes[-1].xaxis.set_major_locator(MultipleLocator(5 if xmax-start_x < 60 else 30))
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda x, _: source.clock(ready["start"]+x*60)[:5]))
    axes[-1].set_xlabel("日本時間", color="#e0e6ed")
    fig.suptitle(f"DV02｜{scene}｜{symbol}｜元影{shadow}｜"+("再参加判断まで" if prefix else "元保有と再参加の経路比較"),
                 color="#f3f5fa", fontsize=15)
    fig.tight_layout(rect=[.02, .02, .99, .96])
    path = source.HERE/"images"/f"DV02再参加_{symbol}_{scene}_影{shadow}_{'入口まで' if prefix else '全経路'}.png"
    fig.savefig(path, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path, info


def main() -> None:
    """
    機能: 保存済みの再参加損失と勝ち回復対照を描画する。
    引数: なし。
    返り値: None。金融再生0回の画像と当時観測を保存する。
    """
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    manifest = source.read_json(source.OLD/"入力準備.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    old = source.read_json(source.OLD/"round3/全条件の会計.json")
    new = source.read_json(source.HERE.parent/"day_round1/全条件の会計.json")
    old_refs = {(r["session"], r["symbol"]): r for r in old["cache"]}
    new_refs = {(r["session"], r["symbol"]): r for r in new["cache"]}
    rows = []
    for scene, symbol, shadow in CASES:
        packet = pickle.loads(source.read_fixed(refs[scene]))
        with np.load(BytesIO(source.read_fixed(refs[scene]["features"])), allow_pickle=False) as stored:
            histories = {s: stored[s+"__history"] for s in ("TOPIX", "NK225")}
        with np.load(BytesIO(source.read_fixed(old_refs[scene, symbol])), allow_pickle=False) as stored:
            baseline = {f: stored["D17__"+f] for f in ("orders", "cycles")}
        with np.load(BytesIO(source.read_fixed(new_refs[scene, symbol])), allow_pickle=False) as stored:
            revised = {f: stored["DV02__"+f] for f in ("orders", "cycles", "execution_events", "parent_mapping")}
        for prefix in (True, False):
            path, info = draw(packet, histories, baseline, revised, scene, symbol, shadow, prefix)
            rows.append(dict(path=str(path.relative_to(source.ROOT)), session=scene, symbol=symbol,
                             shadow_parent=shadow, prefix=prefix, observations=info))
            print(path, flush=True)
    proof = dict(rows=rows, reads=source.READS, financial_replays=0,
                 source_sha256=source.hashlib.sha256(source.Path(__file__).read_bytes()).hexdigest(),
                 note="画像は保存会計の表示。接頭図は再参加判断時まで。勝敗を予告する区分は描かない。")
    (source.HERE/"再参加画像と当時値.json").write_text(
        json.dumps(source.clean(proof), ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
