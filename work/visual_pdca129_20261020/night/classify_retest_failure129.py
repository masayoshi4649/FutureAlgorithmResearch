"""戻りの極値を再び破った親を保存保有区間内で分類する。新しい返済は作らない。"""

from pathlib import Path
import json
import pickle
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
OLD = ROOT/"work/daynight128_20261020"
sys.path.insert(0, str(TASK))
from features129 import prices_for
from render_night129 import read, stamp


def main() -> None:
    """
    機能: 1R保護前に再試験極値を破る事象の元勝ち・元負けを全親で数える。
    引数: なし。
    返り値: None。各親の旧成績を分類し、反実仮想の運転収支は計算しない。
    """
    data = read(HERE/"再試験入口の全親と固定線診断.json")
    refs = {r["session"]: r for r in read(OLD/"入力準備.json")["packets"]}
    rows = []
    for scene in sorted({r["session"] for r in data["rows"]}):
        packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        for kind, method in (("last","NV15"),("mid","NV17")):
            inputs = prices_for(packet, kind)
            for r in [x for x in data["rows"] if x["session"] == scene and x["method"] == method]:
                rd = inputs[scene, r["symbol"]]
                q = packet["quotes"][scene, r["symbol"]]
                side, e, x, w = (r[k] for k in ("side","entry_row","exit_row","width"))
                good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
                good &= (q["bid"] > 0.) & (q["ask"] > q["bid"])
                ids = np.flatnonzero(good & (np.arange(len(good)) >= e) & (np.arange(len(good)) <= x))
                mark = q["bid"][ids] if side > 0 else q["ask"][ids]
                movement = side*(mark-r["entry"])
                peaks = np.maximum.accumulate(np.maximum(movement, 0.))
                broken = side*(rd["last"][ids]-r["return_extreme"]) < 0.
                broken &= (peaks < w) & (ids < r["exit_row"])
                hits = ids[broken]
                hit = int(hits[0]) if len(hits) else -1
                if hit >= 0:
                    g = np.flatnonzero(good)
                    nxt = int(g[np.searchsorted(g, hit, side="right")])
                    early = nxt < x
                else:
                    nxt, early = -1, False
                rows.append(dict(method=method, session=scene, symbol=r["symbol"], number=r["number"],
                    side=side, original_net=r["net"], original_mfe=r["mfe"], width=w, original_mae=r["mae"],
                    return_extreme=r["return_extreme"], entry=r["entry"], exit=r["exit"],
                    entry_time=r["entry_time"], exit_time=r["exit_time"],
                    hit_row=hit, early=bool(early),
                    hit_time=stamp(rd["time_s"][hit]) if hit >= 0 else None,
                    hit_price=float(rd["last"][hit]) if hit >= 0 else None,
                    hit_mark=float(q["bid"][hit] if side > 0 else q["ask"][hit]) if hit >= 0 else None,
                    next_normal_time=stamp(rd["time_s"][nxt]) if nxt >= 0 else None))
    groups = []
    for method in ("NV15","NV17"):
        for symbol in ("TOPIX","NK225"):
            own = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
            selected = [r for r in own if r["early"]]
            groups.append(dict(method=method, symbol=symbol, all_parents=len(own),
                selected=len(selected), original_wins=sum(r["original_net"]>0. for r in selected),
                original_losses=sum(r["original_net"]<0. for r in selected),
                original_win_total=sum(max(0.,r["original_net"]) for r in selected),
                original_loss_total=sum(max(0.,-r["original_net"]) for r in selected),
                selected_original_net=sum(r["original_net"] for r in selected)))
    out = dict(groups=groups, rows=rows, financial_replays=0,
               limitation="保有期間を旧結果へ固定した分類。早期返済による最終収支も、次の入口への作用も未評価。")
    path = HERE/"再試験極値の破綻と勝ち反例.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    print(json.dumps(groups, ensure_ascii=False))
    print("元勝ちの反例")
    print(json.dumps(sorted([r for r in rows if r["early"] and r["original_net"]>0.],
                           key=lambda r:-r["original_net"])[:6], ensure_ascii=False))


if __name__ == "__main__":
    main()
