"""保存された停止判断時に、相手市場まで同じ失敗だったかを分類する。"""

from datetime import datetime, timedelta, timezone
import pickle
import numpy as np
from common129 import HERE, PREV, ROOT, read, save, reference

JST = timezone(timedelta(hours=9))


def main():
    """
    機能: 旧N36の全完結親を、実新規から停止判断までの相手変化で分類する。
    引数: なし。
    返り値: None。新しい停止価格・取引・損益は生成しない。
    """
    rows = []
    for ref in read(PREV/"入力準備.json")["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            ready, market = packet["inputs"][scene, symbol], packet["markets"][scene, symbol]
            path = PREV/"round5/measurement"/f"{symbol}_{scene}.npz"
            with np.load(path, allow_pickle=False) as data:
                orders, trades = data["N36__orders"], data["N36__trades"]
            for parent, trade in enumerate(trades):
                e, x, side = int(trade[0]), int(trade[1]), int(trade[2])
                exits = orders[(orders[:, 2] == parent) & (orders[:, 7] == 0.)]
                assert len(exits) == 1
                d = int(exits[0, 1])
                known = market[e, 11] == 1. and market[d, 11] == 1.
                known = known and np.isfinite(market[e, [1, 3]]).all() and market[e, 3] > 0.
                change = side*(market[d, 1]-market[e, 1])/market[e, 3] if known else None
                rows.append(dict(session=scene, symbol=symbol, parent=parent, side=side,
                    entry_time=datetime.fromtimestamp(ready["time_s"][e], JST).isoformat(),
                    exit_decision_time=datetime.fromtimestamp(ready["time_s"][d], JST).isoformat(),
                    entry=float(trade[4]), exit=float(trade[5]), net=float(trade[8]),
                    mfe=float(trade[9]), mae=float(trade[10]), width=float(trade[11]), reason=int(trade[12]),
                    peer_change_R=float(change) if change is not None and np.isfinite(change) else None,
                    independent_failure=bool(change is not None and change >= 0.),
                    strong_common_failure=bool(change is not None and change <= -.25)))
    groups = []
    for symbol in ("TOPIX", "NK225"):
        for name, selector in (
            ("全親", lambda r: True),
            ("初期停止かつ相手支持保持", lambda r: r["reason"] == 32 and r["independent_failure"]),
            ("初期停止かつ相手も0.25幅逆行", lambda r: r["reason"] == 32 and r["strong_common_failure"]),
            ("その他の初期停止", lambda r: r["reason"] == 32 and not r["independent_failure"] and not r["strong_common_failure"])):
            group = [r for r in rows if r["symbol"] == symbol and selector(r)]
            groups.append(dict(symbol=symbol, group=name, parents=len(group),
                wins=sum(r["net"] > 0 for r in group), losses=sum(r["net"] < 0 for r in group),
                net=sum(r["net"] for r in group)))
    save(HERE/"停止時の相手支持と共通失敗の保存分類.json", dict(financial_replays=0, rows=rows, groups=groups,
        source=reference(PREV/"round5/全条件の会計.json"),
        scope="既存取引の停止判断までだけを分類。停止を遅らせた場合の損益や回復率ではない。"))
    for row in groups:
        print(row, flush=True)


if __name__ == "__main__":
    main()
