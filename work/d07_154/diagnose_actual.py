"""現運用の約定と取得済みラージ原板の価格経路を照合する。"""
import json
from datetime import datetime
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = Path(__file__).resolve().parent
DATA = HERE / "current_20261027"


def stamp(value):
    """ISO時刻を秒へ変換する。

    引数: value(str)は日本時間付き時刻。返り値: floatはエポック秒。
    """
    return datetime.fromisoformat(value).timestamp()


def main():
    """実約定ごとの保有経路と少枚数の利益返しを記録する。

    引数: なし。返り値: なし。原約定を書換えずJSONと図を保存。
    """
    state = json.loads((DATA / "app_state.json").read_text(encoding="utf-8"))
    product = next(x for x in state["products"] if x["product"] == "NK225mini")
    snapshot = product["snapshot"]
    trades = [x for x in snapshot["recent_trades"] if x["at"].startswith("2026-10-27T") and stamp(x["at"]) >= stamp("2026-10-27T08:45:00+09:00")]
    rows = []
    total = invalid = 0
    previous = float("-inf")
    with (DATA / "NK225_book.jsonl").open(encoding="utf-8") as stream:
        for seq, line in enumerate(stream):
            total += 1
            d = json.loads(line)
            if not d.get("CurrentPriceTime"):
                invalid += 1
                continue
            t = stamp(d["CurrentPriceTime"])
            bid, ask = d["Buy1"]["Price"], d["Sell1"]["Price"]
            if t < previous or not bid or not ask or not (0 < bid < ask):
                invalid += 1
                continue
            previous = t
            rows.append((t, bid, ask, seq))
    a = np.array(rows, dtype=float)
    holdings, closed, identifiers = {}, [], 0
    for event in trades:
        owner = event["owner"]
        lots = holdings.setdefault(owner, [])
        t = stamp(event["at"])
        if event["action"] == "new":
            identifiers += 1
            lots.append({"id": identifiers, "owner": owner, "entry": event, "remaining": event["quantity"], "same_owner_add": bool(lots)})
            continue
        qty = event["quantity"]
        for lot in list(lots):
            if qty <= 0:
                break
            q = min(qty, lot["remaining"])
            e = lot["entry"]
            direction = 1 if e["side"] == "buy" else -1
            keep = (a[:, 0] >= stamp(e["at"])) & (a[:, 0] <= t)
            sub = a[keep]
            gain = direction * (sub[:, 1 if direction > 0 else 2] - e["price"])
            peak = int(np.argmax(gain))
            trough = int(np.argmin(gain))
            closed.append({"owner": owner, "id": lot["id"], "side": e["side"], "quantity": q,
                           "entry_at": e["at"], "entry_price": e["price"], "exit_at": event["at"], "exit_price": event["price"],
                           "gross_yen": direction * (event["price"] - e["price"]) * q * 100,
                           "mfe_points_large_quote_proxy": float(gain[peak]), "mfe_at": datetime.fromtimestamp(sub[peak, 0]).astimezone().isoformat(),
                           "mae_points_large_quote_proxy": float(gain[trough]), "mae_at": datetime.fromtimestamp(sub[trough, 0]).astimezone().isoformat(),
                           "exit_reason": event["reason"], "same_owner_add": lot["same_owner_add"]})
            lot["remaining"] -= q
            qty -= q
            if not lot["remaining"]:
                lots.remove(lot)
        assert qty == 0
    info = {"observed_until": snapshot["updated_at"], "raw_rows": total, "normal_price_clock_rows": len(a), "excluded_rows": invalid,
            "actual_day_net_fees_included": sum(t["pnl_yen"] for t in trades), "snapshot_day_net": snapshot["session_realized_yen"],
            "scope": "実際のmini約定。MFE/MAEはラージ返済気配代理でありminiの実表示含みではない。手動返済は履歴に無いため未補完。", "closed_slices": closed, "open_before_manual_intervention": holdings}
    (HERE / "actual_diagnostic.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    # ----------------------------------------
    plt.rcParams["font.family"] = "Yu Gothic"
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(16, 7))
    stride = max(1, len(a) // 12000)
    times = [datetime.fromtimestamp(t).astimezone() for t in a[::stride, 0]]
    ax.plot(times, a[::stride, 1:3].mean(axis=1), color="#90caf9", lw=.85, label="ラージの正常気配中値")
    colors = {"core": "#ffb74d", "addon": "#ce93d8", "episode": "#80cbc4"}
    for e in trades:
        dt = datetime.fromisoformat(e["at"])
        new = e["action"] == "new"
        ax.scatter([dt], [e["price"]], color=colors[e["owner"]], marker=("^" if e["side"] == "buy" else "v") if new else "x", s=65, zorder=5)
        if new:
            ax.annotate(f"{dt:%H:%M} {e['owner']} {e['quantity']}枚", (dt, e["price"]), xytext=(4, 16), textcoords="offset points", fontsize=9, color=colors[e["owner"]])
    ax.set_title("2026/10/27 デイ：実約定と原板の経路（12:08未満）")
    ax.set_ylabel("日経価格（pt）")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=datetime.now().astimezone().tzinfo))
    ax.grid(alpha=.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "actual_current.png", dpi=140)
    plt.close(fig)
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
