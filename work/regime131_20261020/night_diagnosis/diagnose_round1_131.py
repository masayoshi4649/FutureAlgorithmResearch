"""第一巡の保存親を、入口・順行・反復・気配負担に分けて診断する。"""

from datetime import datetime
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
BASE = ROOT / "work/daynight128_20261020"
sys.path.insert(0, str(TASK))
import features131


def read(path):
    """
    機能: 凍結済みのJSONを読み込む。
    引数: path(Path)は入力位置。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def when(value):
    """
    機能: 原行時計を秒付き日本時刻にする。
    引数: value(float)はＵＮＩＸ秒。
    返り値: strは日本時刻。
    """
    return datetime.fromtimestamp(value, ZoneInfo("Asia/Tokyo")).isoformat()


def clean(value):
    """
    機能: 未知の特徴を零にせず空値として保存する。
    引数: value(float)は特徴。
    返り値: float又はNone。
    """
    return float(value) if np.isfinite(value) else None


def aggregate(rows):
    """
    機能: 保存親の損益と損失機構を集計する。
    引数: rows(list[dict])は親診断。
    返り値: dictは件数・利益・損失と順行幅。
    """
    return dict(parents=len(rows), wins=sum(r["net"] > 0 for r in rows),
                losses=sum(r["net"] < 0 for r in rows),
                profit=sum(max(0, r["net"]) for r in rows),
                loss=-sum(min(0, r["net"]) for r in rows),
                net=sum(r["net"] for r in rows), gross=sum(r["gross"] for r in rows),
                fees=sum(r["fee"] for r in rows),
                quote_cost=sum(r["spread_cost"] for r in rows),
                pending_adverse_cost=sum(r["pending_cost"] for r in rows),
                median_mfe_R=float(np.median([r["mfe_R"] for r in rows])) if rows else None,
                median_seconds=float(np.median([r["seconds"] for r in rows])) if rows else None)


def main():
    """
    機能: 全21夜間を診断し、各商品・手法の赤字上位三場と親を保存する。
    引数: なし。
    返り値: None。金融核の呼出し・旧資料変更は行わない。
    """
    result = read(TASK / "round1_final/全条件の会計.json")
    refs = read(BASE / "入力準備.json")["packets"]
    methods = ("R01", "R05", "R09")
    parents = []
    for ref in refs:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        inputs, markets, history, phases = features131.build(packet)
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            ready, q, h, m = inputs[key], packet["quotes"][key], history[key], markets[key]
            t, bid, ask = ready["time_s"], q["bid"], q["ask"]
            mid = (bid+ask)*.5
            good = q["quote_valid"] & np.isfinite(bid) & np.isfinite(ask) & (ask > bid) & (bid > 0)
            saved = np.load(TASK / "round1_final/measurement" / (symbol+"_"+scene+".npz"))
            for method in methods:
                trades, orders = saved[method+"__trades"], saved[method+"__orders"]
                previous = None
                for tr, op, ex in zip(trades, orders[::2], orders[1::2]):
                    a, b, ad, bd = int(tr[1]), int(tr[2]), int(op[1]), int(ex[1])
                    side, qty, risk = int(tr[3]), tr[4], tr[10]
                    mult = 1000. if symbol == "TOPIX" else 10.
                    opening_quote = ask[ad] if side > 0 else bid[ad]
                    exit_quote = bid[bd] if side > 0 else ask[bd]
                    pending_cost = side*((tr[5]-opening_quote)-(tr[6]-exit_quote))*qty*mult
                    spread_cost = .5*((ask[a]-bid[a])+(ask[b]-bid[b]))*qty*mult
                    movement = side*(np.where(side > 0, bid[a:b+1], ask[a:b+1])-tr[5])
                    movement = movement[good[a:b+1]]
                    actual_mfe, actual_mae = max(0., movement.max()), min(0., movement.min())
                    r = dict(method=method, session=scene, symbol=symbol, parent=int(tr[0]),
                             entryrow=a, exitrow=b, decisionrow=ad, exitdecisionrow=bd,
                             side=side, entrytime=when(t[a]), exittime=when(t[b]),
                             decisiontime=when(t[ad]), exitdecisiontime=when(t[bd]),
                             entry=float(tr[5]), exit=float(tr[6]), quantity=int(qty),
                             gross=float(tr[7]), fee=float(tr[8]), net=float(tr[9]),
                             width=float(risk), mfe=float(tr[11]), mae=float(tr[12]),
                             full_path_mfe=float(actual_mfe), full_path_mae=float(actual_mae),
                             mfe_R=float(tr[11]/risk), mae_R=float(tr[12]/risk),
                             seconds=float(t[b]-t[a]), entry_reason=int(tr[15]),
                             exit_reason=int(tr[16]), phase=features131.PHASES[int(tr[13])],
                             spread_cost=float(spread_cost), pending_cost=float(pending_cost),
                             entry_wait=float(t[a]-t[ad]), exit_wait=float(t[b]-t[bd]),
                             entry_spread_R=float((ask[a]-bid[a])/risk),
                             own5=clean(side*h[ad,6]), own20=clean(side*h[ad,7]),
                             peer5=clean(side*h[ad,10]), peer20=clean(side*h[ad,11]),
                             efficiency=clean(h[ad,5]),
                             own120=clean(side*m[ad,5]), peer120=clean(side*m[ad,7]),
                             progress_class="未順行" if tr[11] <= 0 else
                             ("順行0.25R未満" if tr[11] < .25*risk else
                              ("順行0.25〜1R未満" if tr[11] < risk else "順行1R以上")),
                             previous_same_side=False, reentry_beyond_previous_best=False,
                             previous_parent=None, previous_net=None, previous_exit_gap=None)
                    if previous is not None:
                        r["previous_parent"] = previous["parent"]
                        r["previous_net"] = previous["net"]
                        r["previous_exit_gap"] = float(t[a]-t[previous["exitrow"]])
                        r["previous_same_side"] = side == previous["side"]
                        if r["previous_same_side"]:
                            previous_best = previous["entry"]+side*previous["full_path_mfe"]
                            r["reentry_beyond_previous_best"] = bool(side*(tr[5]-previous_best) >= 0)
                    parents.append(r)
                    previous = r
            saved.close()
        print(scene, len(parents), "保存親診断", flush=True)
    groups, worst = [], []
    for method in methods:
        for symbol in ("TOPIX", "NK225"):
            selected = [r for r in parents if r["method"] == method and r["symbol"] == symbol]
            grouping = {}
            for field in ("entry_reason", "exit_reason", "phase", "progress_class",
                          "previous_same_side", "reentry_beyond_previous_best"):
                grouping[field] = {str(value): aggregate([r for r in selected if r[field] == value])
                                   for value in sorted({r[field] for r in selected}, key=str)}
            groups.append(dict(method=method, symbol=symbol, all=aggregate(selected), groups=grouping))
            summary = sorted([r for r in result["rows"] if r["method"] == method and
                              r["symbol"] == symbol and r["kind"] == "Night"], key=lambda r: r["net"])[:3]
            for row in summary:
                sceneparents = [r for r in selected if r["session"] == row["session"]]
                assert sum(r["net"] for r in sceneparents) == row["net"]
                worst.append(dict(method=method, symbol=symbol, session=row["session"],
                                  net=row["net"], parents=sceneparents))
    output = dict(financial_replays=0, source="round1_finalの凍結注文・親・当時入力",
                  limitations="親の最大順行は発注待ち中を除く核記録と、全保有原行を含む観測を併記。気配負担は仮想費用診断であり約定改善を保証しない。",
                  methods=list(methods), groups=groups, worst=worst, parents=parents)
    path = HERE / "第一巡の夜間入口と順行反復の全親診断.json"
    assert not path.exists()
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(path.as_posix(), flush=True)


if __name__ == "__main__":
    main()
