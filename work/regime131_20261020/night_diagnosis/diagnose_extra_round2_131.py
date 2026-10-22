"""第二巡の追加親だけを、保護未起動損失と途中押戻りの勝ち反例へ分解する。"""

from datetime import datetime
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]


def read(path):
    """
    機能: 変更しない保存JSONを読む。
    引数: path(Path)は資料位置。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def when(value):
    """
    機能: 原時計を日本時刻へ表示変換する。
    引数: value(float)はＵＮＩＸ秒。
    返り値: strは秒付き日本時刻。
    """
    return datetime.fromtimestamp(value, ZoneInfo("Asia/Tokyo")).isoformat()


def aggregate(rows):
    """
    機能: 元の追加親の件数と既存損益を集計する。
    引数: rows(list[dict])は同条件の元親。
    返り値: dictは件数・損益・保有分数。
    """
    return dict(parents=len(rows), wins=sum(r["net"] > 0 for r in rows),
                losses=sum(r["net"] < 0 for r in rows),
                net=sum(r["net"] for r in rows),
                profit=sum(max(0, r["net"]) for r in rows),
                loss=-sum(min(0, r["net"]) for r in rows),
                median_minutes=float(np.median([r["seconds"]/60 for r in rows])) if rows else None)


def main():
    """
    機能: 全688会計の追加親を分類し、元勝ちの途中押戻りを観測する。
    引数: なし。
    返り値: None。新しい退出条件の注文生成・損益再生は行わない。
    """
    completed = read(TASK / "round2/全条件の会計.json")
    refs = read(ROOT / "work/daynight128_20261020/入力準備.json")["packets"]
    parents = []
    for ref in refs:
        scene = ref["session"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            ready, q = packet["inputs"][(scene, symbol)], packet["quotes"][(scene, symbol)]
            times, bid, ask = ready["time_s"], q["bid"], q["ask"]
            good = q["quote_valid"] & np.isfinite(bid) & np.isfinite(ask) & (ask > bid) & (bid > 0.)
            with np.load(TASK / "round2/measurement" / (symbol+"_"+scene+".npz")) as saved:
                for config in completed["configs"]:
                    method = config["id"]
                    trades, orders = saved[method+"__extra_trades"], saved[method+"__extra_orders"]
                    for tr in trades:
                        a, b, side = int(tr[1]), int(tr[2]), int(tr[3])
                        width = tr[10]
                        validrows = np.arange(a, b+1)[good[a:b+1]]
                        movement = side*(np.where(side > 0, bid[validrows], ask[validrows])-tr[5])
                        maxima = np.maximum.accumulate(np.maximum(movement, 0.))
                        peak_index = int(np.argmax(movement))
                        ratio = tr[11]/width
                        category = ("未順行" if ratio <= 0 else "0〜0.75R未満" if ratio < .75 else
                                    "0.75〜1R未満" if ratio < 1 else "1〜1.25R未満" if ratio < 1.25 else
                                    "1.25〜1.5R未満" if ratio < 1.5 else "1.5R以上")
                        counter = {}
                        for threshold in (.75, 1., 1.25):
                            # 元の最高順行へ達する前だけを観測し、最終追尾返済を反例と混同しない。
                            selected = (maxima[:peak_index] >= threshold*width)
                            observations = np.flatnonzero(selected)
                            if len(observations):
                                drawbacks = (maxima-movement)[observations]/width
                                where = observations[int(np.argmax(drawbacks))]
                                counter[str(threshold)] = dict(
                                    max_drawback_R=float(drawbacks.max()), row=int(validrows[where]),
                                    time=when(times[validrows[where]]),
                                    prior_best_R=float(maxima[where]/width),
                                    current_gain_R=float(movement[where]/width),
                                    later_best_R=float(movement[peak_index]/width),
                                    later_best_time=when(times[validrows[peak_index]]))
                            else:
                                counter[str(threshold)] = None
                        opening = orders[orders[:, 7] == 1][0]
                        r = dict(method=method, symbol=symbol, session=scene,
                                 kind=scene.split("_")[1], parent=int(tr[0]), side=side,
                                 entryrow=a, exitrow=b, decisionrow=int(opening[1]),
                                 entrytime=when(times[a]), exittime=when(times[b]),
                                 entry=float(tr[5]), exit=float(tr[6]), quantity=int(tr[4]),
                                 gross=float(tr[7]), fee=float(tr[8]), net=float(tr[9]),
                                 width=float(width), mfe=float(tr[11]), mae=float(tr[12]),
                                 mfe_R=float(ratio), mae_R=float(tr[12]/width),
                                 category=category, seconds=float(times[b]-times[a]),
                                 peak_time=when(times[validrows[peak_index]]),
                                 original_winner_pullbacks=counter)
                        parents.append(r)
    groups = []
    for method in [c["id"] for c in completed["configs"]]:
        for symbol in ("TOPIX", "NK225"):
            for kind in ("Day", "Night"):
                selected = [r for r in parents if r["method"] == method and r["symbol"] == symbol and r["kind"] == kind]
                grouping = {name: aggregate([r for r in selected if r["category"] == name])
                            for name in ("未順行", "0〜0.75R未満", "0.75〜1R未満",
                                         "1〜1.25R未満", "1.25〜1.5R未満", "1.5R以上")}
                total = aggregate(selected)
                expected = sum(r["components"]["追加"]["net"] for r in completed["rows"]
                               if r["method"] == method and r["symbol"] == symbol and r["kind"] == kind)
                assert total["net"] == expected
                counters = {}
                for threshold in (.75, 1., 1.25):
                    for pullback in (.5, .75):
                        candidates = [r for r in selected if r["net"] > 0 and
                                      r["original_winner_pullbacks"][str(threshold)] is not None and
                                      r["original_winner_pullbacks"][str(threshold)]["max_drawback_R"] >= pullback]
                        counters[str(threshold)+"起動後"+str(pullback)+"R戻し"] = aggregate(candidates)
                groups.append(dict(method=method, symbol=symbol, kind=kind, all=total,
                                   mfe_groups=grouping, original_winner_counterexamples=counters))
    unique = {(r["symbol"], r["session"], r["entryrow"], r["exitrow"], r["side"]) for r in parents}
    output = dict(financial_replays=0, account_count=len(completed["rows"]),
                  parent_records=len(parents), unique_entry_exit_paths=len(unique),
                  note="条件間で同じ入口経路は重複する。各分類の分母は同じ手法・商品・昼夜の元追加親数。候補退出を実行した成績ではない。",
                  groups=groups, parents=parents)
    target = HERE / "第二巡の全追加親と保護未起動損失.json"
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(target.as_posix(), "追加親記録", len(parents), "独自経路", len(unique), flush=True)


if __name__ == "__main__":
    main()
