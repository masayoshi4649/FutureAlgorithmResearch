"""純保険と同判断減玉対照の差を、写像器を使わず原注文から検算する。"""

from __future__ import annotations

import numpy as np

from audit_all import read, ROOT, WORK, HERE
from independent_account import reconstruct, fee, near, save


def expected_mapping(data: dict, orders: np.ndarray, symbol: str) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """機能: 純保険の当時注文群から減玉対照と全行の理論評価差を独立算出する。

    引数: data(dict)、orders(np.ndarray9列)、symbol(str)。
    返り値: 対照注文、全行理論差、終了群の節約額(tuple)。
    """
    n = len(data["time_s"])
    point, cap = (1000., 10) if symbol == "TOPIX" else (10., 20)
    mapped, endings = [], []
    states = {}
    long_delta, short_delta, terminal_saving = np.zeros(n), np.zeros(n), np.zeros(n)
    for order in orders:
        row, side, qty, opened = int(order[0]), int(order[3]), int(order[4]), int(order[7])
        if opened:
            (long_delta if side == 1 else short_delta)[row] += qty
        else:
            (long_delta if side == -1 else short_delta)[row] -= qty
    pointer = 0
    while pointer < len(orders):
        end = pointer + 1
        row, cid = int(orders[pointer, 0]), int(orders[pointer, 2])
        while end < len(orders) and int(orders[end, 0]) == row and int(orders[end, 2]) == cid:
            end += 1
        group = orders[pointer:end]
        terminal = group[(group[:, 7] == 0) & (group[:, 8] == 0)]
        if len(terminal):
            assert len(terminal) == 1
            core = terminal[0]
            assert int(core[4]) == cap
            state = states[cid]
            covered = state["cover"]
            assert sum(int(o[4]) for o in group if int(o[8]) == 1 and int(o[7]) == 0) == covered
            remained = cap - covered
            saved_fee = sum(fee(symbol, int(o[4])) for o in group) - (fee(symbol, remained) if remained else 0)
            saved_spread = covered * (data["ask"][row] - data["bid"][row]) * point
            saving = saved_fee + saved_spread
            terminal_saving[row] += saving
            endings.append(dict(組=cid, 約定行=row, 残保険枚数=covered,
                手数料節約円=saved_fee, 気配差節約円=float(saved_spread), 理論収支差=float(saving)))
            if remained:
                other = core.copy()
                other[4] = remained
                mapped.append(other)
            state["cover"] = 0
        else:
            for order in group:
                other = order.copy()
                if int(order[8]) == 0:
                    assert int(order[7]) == 1 and int(order[4]) == cap
                    states[cid] = dict(side=int(order[3]), cover=0)
                else:
                    state = states[cid]
                    if int(order[7]) == 1:
                        state["cover"] += int(order[4])
                        other[7] = 0
                    else:
                        state["cover"] -= int(order[4])
                        other[7] = 1
                    other[8] = 0
                mapped.append(other)
        pointer = end
    long_held, short_held = np.cumsum(long_delta), np.cumsum(short_delta)
    covered = np.minimum(long_held, short_held)
    valid = np.isfinite(data["bid"]) & np.isfinite(data["ask"]) & (data["bid"] > 0) & (data["ask"] >= data["bid"])
    prior = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    spreads = np.concatenate(([0.0], data["ask"] - data["bid"]))[prior + 1]
    theory = np.cumsum(terminal_saving) + covered * spreads * point
    return np.asarray(mapped, dtype=float).reshape((-1, 9)), theory, endings


def main() -> None:
    """機能: 全48 H/N対照・2688口座の全行露出と気配料金差を独立照合する。

    引数: なし。返り値: なし(None)。
    """
    fixed = read(WORK / "事前固定.json")
    ready = read(ROOT / "work/wave_v69/prepared/inputs.pkl")
    features = read(ROOT / "work/wave_v69/prepared/features.pkl")
    records = []
    for config in fixed["条件"]:
        if not config["paired"]:
            continue
        source_id = config["source"] + "_" + config["paired_manager"]
        hedge = read(WORK / "ledgers" / (source_id + ".pkl"))
        reduced = read(WORK / "ledgers" / (config["id"] + ".pkl"))
        accounts = []
        for key in sorted(ready):
            data = dict(time_s=ready[key]["time_s"], seq=ready[key]["seq"],
                bid=features[key]["bid"], ask=features[key]["ask"])
            h, hc = reconstruct(data, dict(symbol=key[1], session=key[0], orders=hedge[key]["orders"]))
            r, rc = reconstruct(data, dict(symbol=key[1], session=key[0], orders=reduced[key]["orders"]))
            expected, theory, endings = expected_mapping(data, hedge[key]["orders"], key[1])
            np.testing.assert_array_equal(expected, reduced[key]["orders"])
            np.testing.assert_allclose(rc - hc, theory, rtol=0, atol=1.e-4)
            assert np.all(theory >= 0)
            saving = sum(e["理論収支差"] for e in endings)
            near(r["net"] - h["net"], saving, "終了群の料金・気配差だけによる差")
            accounts.append(dict(セッション=key[0], 銘柄=key[1], 両建て収支=h["net"],
                減玉対照収支=r["net"], 理論節約円=saving,
                評価差最大=float(theory.max()), 終了群=endings, 合格=True))
        records.append(dict(両建てID=source_id, 減玉ID=config["id"], 口座=accounts, 合格=True))
        print(f"純保険対照 {source_id}/{config['id']} 56口座・全行一致", flush=True)
    assert len(records) == 48
    save(HERE / "両建てと減玉対照の全行監査.json", dict(合格=True, 対照数=48,
        口座数=2688, 差の説明="同じ方向露出を作り、保険を残した場末に余分な気配差と往復料金を省く差",
        全原本行不等式="減玉対照の清算時価 >= 純両建ての清算時価", 結果=records))


if __name__ == "__main__":
    main()
