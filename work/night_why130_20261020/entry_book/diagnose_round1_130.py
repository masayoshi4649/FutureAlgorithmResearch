"""第一巡の保存親と元親を対応させ、早期返済後の新規を分離する。"""

import pickle
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from diagnose_entry130 import HERE, ROOT, OLD, PREV, read, save
sys.path.insert(0, str(PREV))
sys.path.insert(0, str(OLD))
import features129

TASK = HERE.parent
JST = timezone(timedelta(hours=9))


def stamp(value: float) -> str:
    """
    機能: 価格時計を日本時刻へ変換する。
    引数: value(float)は秒。
    返り値: strは日本時刻。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def collect(method: str, scene: str, symbol: str, rd: dict, market: np.ndarray) -> list[dict]:
    """
    機能: 保存された部分返済を親へまとめる。
    引数: method/scene/symbol(str)、rd(dict)、market(ndarray)は対象と当時特徴。
    返り値: list[dict]は入口・各返済・親損益・返済判断時の二市場変化。
    """
    folder = TASK / "round1_final" if method.startswith("W") else PREV / ("round1" if method == "NV01" else "round7")
    with np.load(folder / "measurement" / f"{symbol}_{scene}.npz") as saved:
        orders, trades = saved[method + "__orders"], saved[method + "__trades"]
    out = []
    for order in orders[orders[:, 7] == 1.]:
        parent = int(order[2])
        closes = orders[(orders[:, 2] == parent) & (orders[:, 7] == 0.)]
        owned = trades[trades[:, 14] == parent] if trades.shape[1] > 14 else trades[trades[:, 0] == order[0]]
        assert len(closes) == len(owned)
        exits = []
        for c, tr in zip(closes, owned):
            d, f = int(c[1]), int(c[0])
            exits.append(dict(decision_row=d, fill_row=f, decision_time=stamp(rd["time_s"][d]),
                fill_time=stamp(rd["time_s"][f]), quantity=int(c[4]), price=float(c[5]), reason=int(c[6]),
                own30=float(order[3] * market[d, 4]), own120=float(order[3] * market[d, 5]),
                peer30=float(order[3] * market[d, 6]), peer120=float(order[3] * market[d, 7]),
                known=bool(market[d, 11] == 1.), net=float(tr[8]), gross=float(tr[6]), fee=float(tr[7]),
                mfe=float(tr[9]), mae=float(tr[10])))
        out.append(dict(method=method, session=scene, symbol=symbol, parent=parent,
            entry_row=int(order[0]), decision_row=int(order[1]), side=int(order[3]), quantity=int(order[4]),
            entry=float(order[5]), entry_time=stamp(rd["time_s"][int(order[0])]),
            decision_time=stamp(rd["time_s"][int(order[1])]), width=float(owned[0, 11]),
            exit_row=int(closes[-1, 0]), exit_time=stamp(rd["time_s"][int(closes[-1, 0])]),
            net=float(owned[:, 8].sum()), mfe=float(owned[:, 9].max()), exits=exits))
    return out


def main() -> None:
    """
    機能: 全六条件を元保存親と照合し、損失機構の分母を保存する。
    引数: なし。
    返り値: None。金融核の再実行は行わない。
    """
    refs = [r for r in read(OLD / "入力準備.json")["packets"] if r["session"].endswith("_Night")]
    records, accounts, partials = [], [], []
    for ref in refs:
        scene = ref["session"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        bymethod = {}
        for kind, methods in (("last", ("NV01", "W01", "W02", "W03")), ("mid", ("NV25", "W04", "W05", "W06"))):
            inputs, markets, _, _ = features129.build(packet, kind)
            for symbol in ("TOPIX", "NK225"):
                for method in methods:
                    items = collect(method, scene, symbol, inputs[scene, symbol], markets[scene, symbol])
                    records.extend(items)
                    bymethod[method, symbol] = items
                base = methods[0]
                baseline = bymethod[base, symbol]
                for method in methods[1:]:
                    current = bymethod[method, symbol]
                    pairs, matched = [], set()
                    for new in current:
                        exact = next((r for r in baseline if (r["entry_row"], r["side"], r["entry"]) ==
                                      (new["entry_row"], new["side"], new["entry"])), None)
                        if exact:
                            matched.add(exact["parent"])
                            kind = "同じ新規親の出口変更"
                        else:
                            kind = "入口経路変更で発生した新規親"
                        containing = [r["parent"] for r in baseline if r["decision_row"] < new["decision_row"] <= r["exit_row"]]
                        pair = dict(kind=kind, old=exact, new=new,
                            during_old_parent=containing,
                            delta=new["net"] - (exact["net"] if exact else 0.))
                        pairs.append(pair)
                        if method in ("W02", "W05") and exact:
                            for event in new["exits"]:
                                if event["reason"] == 76:
                                    partials.append(dict(method=method, base=base, session=scene, symbol=symbol,
                                        parent=new["parent"], entry_time=new["entry_time"], old_net=exact["net"],
                                        new_net=new["net"], delta=new["net"] - exact["net"],
                                        same_final_exit=new["exit_row"] == exact["exit_row"], event=event))
                    for old in baseline:
                        if old["parent"] not in matched:
                            pairs.append(dict(kind="元親が成立しなくなった", old=old, new=None,
                                during_old_parent=[], delta=-old["net"]))
                    delta = sum(r["net"] for r in current) - sum(r["net"] for r in baseline)
                    assert np.isclose(sum(p["delta"] for p in pairs), delta)
                    accounts.append(dict(method=method, base=base, session=scene, symbol=symbol,
                        old_net=sum(r["net"] for r in baseline), new_net=sum(r["net"] for r in current),
                        delta=delta, pairs=pairs))
        print(scene, "保存親の差分照合", flush=True)
    groups = []
    for method in ("W02", "W05"):
        for symbol in ("TOPIX", "NK225"):
            population = [r for r in partials if r["method"] == method and r["symbol"] == symbol]
            for condition in ("全部分返済", "二市場30秒が共に逆", "二市場120秒が共に逆", "二市場120秒が共に強逆"):
                selected = population
                if condition != "全部分返済":
                    keys = ("own30", "peer30") if "30秒" in condition else ("own120", "peer120")
                    threshold = -.25 if "強逆" in condition else 0.
                    selected = [r for r in population if r["event"]["known"]
                                and all(r["event"][k] < threshold for k in keys)]
                groups.append(dict(method=method, symbol=symbol, condition=condition, denominator=len(population),
                    count=len(selected), saved=sum(r["delta"] > 0 for r in selected),
                    hurt=sum(r["delta"] < 0 for r in selected), delta=sum(r["delta"] for r in selected),
                    ids=[f'{r["session"]}/{r["parent"]}' for r in selected]))
    target = HERE / "第一巡の全親差分と部分返済時の二市場.json"
    save(target, dict(passed=True, financial_replays=0, parents=records, accounts=accounts,
        partials=partials, groups=groups,
        note="部分返済時の条件は保存親固定の説明分類。追加条件の金融結果ではない。"))
    print(groups)


if __name__ == "__main__":
    main()
