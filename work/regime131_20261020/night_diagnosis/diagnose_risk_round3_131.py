"""第三巡の追加親から初期尺度と固定枚数の損失集中を診断する。"""

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
    機能: 変更しない保存JSONを読み込む。
    引数: path(Path)は資料位置。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def when(value):
    """
    機能: 原時計を日本時刻へ変換する。
    引数: value(float)はＵＮＩＸ秒。
    返り値: strは秒付き時刻。
    """
    return datetime.fromtimestamp(value, ZoneInfo("Asia/Tokyo")).isoformat()


def aggregate(rows):
    """
    機能: 元追加親の初期リスク・利益依存・負け深さを集計する。
    引数: rows(list[dict])は同じ条件と商品の保存親。
    返り値: dictは元の収支とリスク分布。新数量の収支は計算しない。
    """
    wins = [r["net"] for r in rows if r["net"] > 0]
    losses = [r["net"] for r in rows if r["net"] < 0]
    upper = sorted(wins, reverse=True)[:3]
    net = sum(r["net"] for r in rows)
    return dict(parents=len(rows), wins=len(wins), losses=len(losses), net=net,
                profit=sum(wins), loss=-sum(losses), maximum_loss=-min(losses) if losses else 0.,
                average_winning_parent=float(np.mean(wins)) if wins else None,
                top3_winning_sum=sum(upper), excluding_top3_wins_net=net-sum(upper),
                minimum_R_ticks=min((r["R_ticks"] for r in rows), default=None),
                maximum_R_ticks=max((r["R_ticks"] for r in rows), default=None),
                median_R_ticks=float(np.median([r["R_ticks"] for r in rows])) if rows else None,
                risk_yen_range=[min((r["initial_risk_yen"] for r in rows), default=None),
                                max((r["initial_risk_yen"] for r in rows), default=None)])


def main():
    """
    機能: 全第三巡追加親へ当時Rから決まる枚数案を付け、元の勝敗を分類する。
    引数: なし。
    返り値: None。新注文や変更後損益を作らず、診断JSONを新規保存する。
    """
    complete = read(TASK / "round3/全条件の会計.json")
    refs = read(ROOT / "work/daynight128_20261020/入力準備.json")["packets"]
    parents = []
    for ref in refs:
        scene = ref["session"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            ready = packet["inputs"][(scene, symbol)]
            top = symbol == "TOPIX"
            mult, baseqty = (1000., 5) if top else (10., 10)
            tick = ready["tick"]
            with np.load(TASK / "round3/measurement" / (symbol+"_"+scene+".npz")) as saved:
                for config in complete["configs"]:
                    mid = config["id"]
                    for tr in saved[mid+"__extra_trades"]:
                        a, b = int(tr[1]), int(tr[2])
                        risk = tr[10]
                        quantity = {str(span): int(min(baseqty, max(1, np.floor(baseqty*span*tick/risk))))
                                    for span in (8, 12, 16, 24)}
                        parents.append(dict(method=mid, symbol=symbol, session=scene, kind=scene.split("_")[1],
                                            entrytime=when(ready["time_s"][a]), exittime=when(ready["time_s"][b]),
                                            entryrow=a, exitrow=b, side=int(tr[3]), quantity=int(tr[4]),
                                            entry=float(tr[5]), exit=float(tr[6]), gross=float(tr[7]),
                                            fee=float(tr[8]), net=float(tr[9]), R=float(risk),
                                            R_ticks=float(risk/tick), tick=float(tick),
                                            mfe=float(tr[11]), mae=float(tr[12]), mfe_R=float(tr[11]/risk),
                                            initial_risk_yen=float(risk*baseqty*mult),
                                            proposed_quantity=quantity,
                                            minimum_one_exceeds_budget={
                                                str(span): bool(quantity[str(span)]*risk > baseqty*span*tick)
                                                for span in (8, 12, 16, 24)}))
    groups = []
    for method in [c["id"] for c in complete["configs"]]:
        for symbol in ("TOPIX", "NK225"):
            for kind in ("Day", "Night"):
                selected = [r for r in parents if r["method"] == method and r["symbol"] == symbol and r["kind"] == kind]
                old = aggregate(selected)
                expected = sum(r["components"]["追加"]["net"] for r in complete["rows"]
                               if r["method"] == method and r["symbol"] == symbol and r["kind"] == kind)
                assert old["net"] == expected
                plans = {}
                for span in ("8", "12", "16", "24"):
                    reduced = [r for r in selected if r["proposed_quantity"][span] < r["quantity"]]
                    plans[span] = dict(reduced_original_parents=aggregate(reduced),
                                       reduced_original_winners=aggregate([r for r in reduced if r["net"] > 0]),
                                       reduced_original_losers=aggregate([r for r in reduced if r["net"] < 0]),
                                       remaining_quantity_range=[min((r["proposed_quantity"][span] for r in selected), default=None),
                                                                 max((r["proposed_quantity"][span] for r in selected), default=None)],
                                       minimum_one_budget_exceptions=sum(r["minimum_one_exceeds_budget"][span] for r in selected))
                groups.append(dict(method=method, symbol=symbol, kind=kind, original=old,
                                   plans_classifying_original_results=plans,
                                   largest_original_losses=sorted([r for r in selected if r["net"] < 0],
                                                                  key=lambda r: r["net"])[:3],
                                   largest_original_wins=sorted([r for r in selected if r["net"] > 0],
                                                                key=lambda r: r["net"], reverse=True)[:3]))
    target = HERE / "第三巡追加の初期リスクと枚数案の全親診断_確定.json"
    assert not target.exists()
    target.write_text(json.dumps(dict(financial_replays=0, parents=parents, groups=groups,
        note="新数量は当時Rからの式の説明に限る。分類内の損益は元の固定枚数による保存結果であり、新規模の実成績ではない。"),
        ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(target.as_posix(), "全追加親", len(parents), flush=True)


if __name__ == "__main__":
    main()
