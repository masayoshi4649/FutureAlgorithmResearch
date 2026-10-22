"""再試験入口の保存売買と準備状態を対応させる。金融核は実行しない。"""

from pathlib import Path
import json
import pickle
import sys
import numpy as np
from numba import njit

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
OLD = ROOT/"work/daynight128_20261020"
sys.path.insert(0, str(TASK))
from features129 import build
from features129b import long_history
from render_night129 import read, stamp


@njit(cache=False)
def trace(times, price, atr, h, m, bid, ask, good, allowed, tick, expected):
    """
    機能: 保存保有区間を除き、固定線と再試験の準備状態だけを復元する。
    引数: 各原行列・allowed・expected(ndarray)、tick(float)は入力と保存判断行。
    返り値: tupleは入口対応状態と全行準備状態。発注・返済・損益計算はしない。
    """
    result = np.zeros((len(expected), 9))
    states = np.full((len(times), 8), np.nan)
    arm, stage, count, began, progress, returned = 0, 0, 0, -1, -1, -1
    level, width, extreme = 0., 0., 0.
    for i in range(len(times)):
        if not allowed[i]:
            arm = 0
            continue
        if not good[i]:
            continue
        if arm and np.isfinite(price[i]) and arm*(price[i]-level) <= -.25*width:
            arm = 0
        known = np.isfinite(price[i]) and np.isfinite(atr[i]) and atr[i] > 0.
        known = known and np.isfinite(h[i]).all() and m[i, 11] == 1.
        known = known and np.isfinite(m[i, 4]) and np.isfinite(m[i, 6])
        if not known:
            continue
        w = max(atr[i], 4.*tick)
        quote = ask[i]-bid[i] <= .25*w and max(ask[i]-price[i], price[i]-bid[i]) <= .5*w
        if arm and times[i]-times[began] > 1800.:
            arm = 0
        if not arm and quote:
            if h[i, 5] >= .35:
                if price[i] > h[i, 3] and h[i, 10] > 0. and h[i, 11] > 0.:
                    arm, level = 1, h[i, 3]
                elif price[i] < h[i, 4] and h[i, 10] < 0. and h[i, 11] < 0.:
                    arm, level = -1, h[i, 4]
            if arm:
                width, began, extreme, stage = w, i, price[i], 0
                progress, returned = -1, -1
                if arm*(price[i]-level) >= .75*width:
                    stage, progress = 1, i
        elif arm:
            advance = arm*(price[i]-level)
            trigger = False
            if advance <= -.25*width:
                arm = 0
            elif stage == 0:
                if advance >= .75*width:
                    stage, progress = 1, i
            elif stage == 1:
                if i > progress and advance <= .25*width:
                    stage, returned, extreme = 2, i, price[i]
            else:
                if arm*(price[i]-extreme) < 0.:
                    extreme = price[i]
                trigger = i > returned and times[i]-times[began] >= 60.
                trigger = trigger and arm*m[i, 4] > 0. and arm*m[i, 6] > 0.
                trigger = trigger and arm*(price[i]-extreme) >= .25*width
            if arm and trigger:
                trigger = arm*h[i, 10] > 0. and arm*h[i, 11] > 0.
            if arm and trigger and quote:
                assert count < len(expected) and expected[count] == i
                result[count] = np.array([i, began, level, width, progress, returned,
                                          extreme, arm, times[i]-times[returned]])
                count += 1
                arm = 0
        states[i] = np.array([arm, stage, level, width, began, progress, returned, extreme])
    assert count == len(expected)
    return result, states


def record(method: str, scene: str, symbol: str, number: int, tr: np.ndarray,
           order: np.ndarray, ready: dict, q: dict, market: np.ndarray,
           history: np.ndarray, context: np.ndarray, state: np.ndarray | None) -> dict:
    """
    機能: 保存一親の時刻・利益返しと入口以前の観測量を整理する。
    引数: 識別子(str/int)、tr/order/market/history/context(ndarray)、ready/q(dict)、state(ndarray|None)。
    返り値: dictは保存取引と、因果的に公開された入口資料。
    """
    e, x, side, qty = map(int, tr[:4])
    d = int(order[1])
    times = ready["time_s"]
    w = float(tr[11])
    h, m, c = history[d], market[d], context[d]
    output = dict(method=method, session=scene, symbol=symbol, number=number,
        decision_row=d, entry_row=e, exit_row=x, side=side,
        direction="買い" if side > 0 else "売り", quantity=qty,
        decision_time=stamp(times[d]), entry_time=stamp(times[e]), exit_time=stamp(times[x]),
        entry=float(tr[4]), exit=float(tr[5]), gross=float(tr[6]), fee=float(tr[7]),
        net=float(tr[8]), mfe=float(tr[9]), mae=float(tr[10]), width=w, reason=int(tr[12]),
        hold_seconds=float(times[x]-times[e]), activation=1., trail=.75,
        observable=dict(own30=float(side*m[4]), own120=float(side*m[5]),
            peer30=float(side*m[6]), peer120=float(side*m[7]),
            own5=float(side*h[6]/m[2]), own20=float(side*h[7]/m[2]),
            peer5=float(side*h[10]/m[3]), peer20=float(side*h[11]/m[3]),
            own60=float(side*c[0]/m[2]), peer60=float(side*c[3]/m[3]),
            er20=float(h[5]), spread_r=float((q["ask"][d]-q["bid"][d])/w),
            fill_adverse=float(side*(tr[4]-ready["last"][d]))))
    if state is not None:
        _, a, level, width, progress, returned, extreme, _, return_seconds = state
        a, progress, returned = int(a), int(progress), int(returned)
        ownmid = (q["bid"]+q["ask"])*.5
        p = ready["last"]
        peak = side*(np.nanmax(p[a:d+1]) if side > 0 else -np.nanmin(p[a:d+1]))
        peak_price = float(np.nanmax(p[a:d+1]) if side > 0 else np.nanmin(p[a:d+1]))
        output.update(arm_row=a, arm_time=stamp(times[a]), boundary=float(level),
            progress_row=progress, progress_time=stamp(times[progress]),
            return_row=returned, return_time=stamp(times[returned]), return_extreme=float(extreme))
        output["observable"].update(
            wait_seconds=float(times[d]-times[a]), after_return_seconds=float(return_seconds),
            boundary_distance=float(side*(tr[4]-level)/w),
            actual_rebound_r=float(side*(ready["last"][d]-extreme)/w),
            first_reach_r=float(side*(ready["last"][progress]-level)/w),
            return_dist_r=float(side*(extreme-level)/w),
            from_prior_peak_r=float(side*(peak_price-tr[4])/w),
            prior_peak=float(peak_price), mid_last_difference=float(ownmid[d]-p[d]))
        assert np.isclose(width, w)
    return output


def main() -> None:
    """
    機能: 全保存親と復元準備を照合し、最悪場・勝ち対照・旧勝ちの欠落を列挙する。
    引数: なし。
    返り値: None。新たな売買条件は実行しない。
    """
    refs = {r["session"]: r for r in read(OLD/"入力準備.json")["packets"] if r["session"].endswith("_Night")}
    account = read(TASK/"round4/全条件の会計.json")["rows"]
    rows, missing = [], []
    for scene, ref in refs.items():
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        prepared = {kind: build(packet, kind) for kind in ("last", "mid")}
        contexts = {kind: long_history(prepared[kind][0]) for kind in prepared}
        for symbol in ("TOPIX", "NK225"):
            q = packet["quotes"][scene, symbol]
            good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
            good &= (q["bid"] > 0.) & (q["ask"] > q["bid"])
            for method, kind in (("NV15", "last"), ("NV17", "mid")):
                inp, markets, hs, _ = prepared[kind]
                ready, market, h = inp[scene, symbol], markets[scene, symbol], hs[scene, symbol]
                ts = ready["time_s"]
                with np.load(TASK/"round4/measurement"/f"{symbol}_{scene}.npz") as a:
                    orders, trades = a[method+"__orders"], a[method+"__trades"]
                entries = orders[orders[:, 7] == 1.]
                allowed = (ts >= ready["us_open"]+1320.) & (ts < ready["limit"])
                for order, tr in zip(entries, trades):
                    end = np.searchsorted(ts, ts[int(tr[1])]+300., side="left")
                    allowed[int(order[1])+1:end] = False
                states, allstates = trace(ts, ready["last"], ready["atr"], h, market,
                    q["bid"], q["ask"], good, allowed, ready["tick"], entries[:, 1].astype(np.int64))
                for n, (tr, order, state) in enumerate(zip(trades, entries, states), 1):
                    rows.append(record(method, scene, symbol, n, tr, order, ready, q,
                                       market, h, contexts[kind][scene, symbol], state))
                # ----------------------------------------
                # 旧勝ち保有区間との同方向重なりがない親を記録。損益差額の原因分解ではない。
                for oldmethod, folder in (("N36", OLD/"round5"), ("NV02", TASK/"round1")):
                    with np.load(folder/"measurement"/f"{symbol}_{scene}.npz") as a:
                        oo, ot = a[oldmethod+"__orders"], a[oldmethod+"__trades"]
                    oe = oo[oo[:, 7] == 1.]
                    for n, (tr, order) in enumerate(zip(ot, oe), 1):
                        if tr[8] <= 0.:
                            continue
                        overlap = (trades[:, 2] == tr[2]) & (trades[:, 0] <= tr[1]) & (trades[:, 1] >= tr[0])
                        if overlap.any():
                            continue
                        d = int(order[1])
                        state = allstates[d]
                        missing.append(dict(new_method=method, baseline=oldmethod, session=scene,
                            symbol=symbol, number=n, side=int(tr[2]), entry=float(tr[4]),
                            exit=float(tr[5]), entry_time=stamp(ts[int(tr[0])]),
                            exit_time=stamp(ts[int(tr[1])]), net=float(tr[8]),
                            decision_time=stamp(ts[d]), prepared_state=state.tolist(),
                            new_eligible=bool(allowed[d]), old_net_is_not_new_net_delta=True))
        print(scene, "保存入口の固定線と再試験を照合", flush=True)
    selections = []
    groups = []
    for method in ("NV15", "NV17"):
        for symbol in ("TOPIX", "NK225"):
            r = [x for x in rows if x["method"] == method and x["symbol"] == symbol]
            sessions = [x for x in account if x["method"] == method and x["symbol"] == symbol]
            worst = sorted(sessions, key=lambda x: x["net"])[:2]
            losses = [x for x in r if x["net"] < 0.]
            wins = [x for x in r if x["net"] > 0.]
            for scene in worst:
                candidates = sorted([x for x in r if x["session"] == scene["session"]], key=lambda x: x["net"])
                selections.append(dict(kind="赤字上位場の最大損失", session_net=scene["net"], trade=candidates[0]))
            selections.append(dict(kind="最大勝ち対照", trade=max(wins, key=lambda x: x["net"])))
            groups.append(dict(method=method, symbol=symbol, parents=len(r), wins=len(wins), losses=len(losses),
                loss_without_1R=sum(x["mfe"] < x["width"] for x in losses),
                win_without_1R=sum(x["mfe"] < x["width"] for x in wins),
                opposite_own120=dict(count=sum(x["observable"]["own120"] <= .05 for x in r),
                    net=sum(x["net"] for x in r if x["observable"]["own120"] <= .05)),
                opposite_own5=dict(count=sum(x["observable"]["own5"] <= 0. for x in r),
                    net=sum(x["net"] for x in r if x["observable"]["own5"] <= 0.))))
    out = dict(financial_replays=0, API=0, rows=rows, lost_old_winners=missing,
               selections=selections, groups=groups,
               limitation="旧勝ちは新親との同方向保有区間の重なりなしで分類。除去した金額と運転差額は一致しない。")
    path = HERE/"再試験入口の全親と固定線診断.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=True)+"\n", encoding="utf8")
    print(json.dumps(dict(path=str(path), parents=len(rows), groups=groups,
        selections=[dict(kind=x["kind"], **{k:x["trade"][k] for k in ("method","symbol","session","number","entry_time","exit_time","net","mfe","width","observable")}) for x in selections]), ensure_ascii=False))


if __name__ == "__main__":
    main()
