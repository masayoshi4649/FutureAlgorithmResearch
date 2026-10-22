"""第四巡の保存保有を固定し、価格基準の作成・解除と全親差分だけを診断する。"""

import hashlib
import pickle
import sys

import numpy as np
from numba import njit

from diagnose_entry130 import HERE, ROOT, OLD, PREV, read, save
from diagnose_round1_130 import stamp

sys.path.insert(0, str(PREV))
import features129

TASK = HERE.parent
EVENT_NAMES = {1: "最初の活動不適格価格を記録", 2: "不利な判断価格を拒否", 3: "元境界破綻で解除",
               4: "禁止時間で解除", 5: "終端で解除", 6: "価格基準を守って新規判断", 7: "価格記録なしで新規判断"}


@njit(cache=False)
def trace_budget(times, prices, atr, history, market, bid, ask, good, activity,
                 allowed, expected, tick, us_open, terminal, retest):
    """
    機能: 保存注文で保有・待機を固定し、非保有中の準備と判断価格の記録だけを復元する。
    引数: 原行列・allowed・expected(ndarray)、tick/us_open/terminal(float)、retest(int)は入力と保存経路。
    返り値: ndarrayは価格記録イベント。注文・約定・出口・損益は計算しない。
    """
    events = np.zeros((len(times), 16))
    ec, matched = 0, 0
    bquote, blevel, bwidth = np.full(2, np.nan), np.zeros(2), np.zeros(2)
    brow, barm = np.full(2, -1), np.full(2, -1)
    arm, began, stage, progressed, returned = 0, -1, 0, -1, -1
    level, width, extreme = 0., 0., 0.
    for i in range(len(times)):
        quiet = np.isfinite(us_open) and us_open-900. <= times[i] < us_open+900.
        ended = times[i] >= terminal
        for slot in range(2):
            side = 1 if slot == 0 else -1
            breach = np.isfinite(prices[i]) and side*(prices[i]-blevel[slot]) <= -.25*bwidth[slot]
            if np.isfinite(bquote[slot]) and (quiet or ended or breach):
                code = 5 if ended else 4 if quiet else 3
                quote = ask[i] if side > 0 else bid[i]
                events[ec] = np.array([i,code,side,quote,bquote[slot],blevel[slot],bwidth[slot],
                    brow[slot],barm[slot],began,level,width,prices[i],stage,progressed,returned])
                ec += 1
                bquote[slot], blevel[slot], bwidth[slot] = np.nan, 0., 0.
                brow[slot], barm[slot] = -1, -1
        if not allowed[i]:
            arm = 0
            continue
        if not good[i]:
            continue
        if retest == 1 and arm and np.isfinite(prices[i]) and arm*(prices[i]-level) <= -.25*width:
            arm = 0
        known = np.isfinite(prices[i]) and np.isfinite(atr[i]) and atr[i] > 0.
        known = known and np.isfinite(history[i]).all() and market[i,11] == 1.
        known = known and np.isfinite(market[i,4]) and np.isfinite(market[i,6])
        if retest == 0:
            known = known and np.isfinite(market[i,5]) and np.isfinite(market[i,7])
        if not known:
            continue
        w = max(atr[i], 4.*tick)
        quote_ok = ask[i]-bid[i] <= .25*w and max(ask[i]-prices[i], prices[i]-bid[i]) <= .5*w
        if arm and times[i]-times[began] > 1800.:
            arm = 0
        if not arm and quote_ok:
            if history[i,5] >= .35:
                if prices[i] > history[i,3] and history[i,10] > 0. and history[i,11] > 0.:
                    arm, level = 1, history[i,3]
                elif prices[i] < history[i,4] and history[i,10] < 0. and history[i,11] < 0.:
                    arm, level = -1, history[i,4]
            if arm:
                width, began, extreme = w, i, prices[i]
                stage, progressed, returned = 0, -1, -1
                if retest == 1 and arm*(prices[i]-level) >= .75*width:
                    stage, progressed = 1, i
        elif arm:
            advance = arm*(prices[i]-level)
            support = arm*market[i,4] > 0. and arm*market[i,6] > 0.
            trigger = False
            if retest == 0:
                if advance < -.25*width:
                    arm = 0
                else:
                    trigger = times[i]-times[began] >= 60. and support and advance >= .25*width
            elif advance <= -.25*width:
                arm = 0
            elif stage == 0:
                if advance >= .75*width:
                    stage, progressed = 1, i
            elif stage == 1:
                if i > progressed and advance <= .25*width:
                    stage, returned, extreme = 2, i, prices[i]
            else:
                if arm*(prices[i]-extreme) < 0.:
                    extreme = prices[i]
                trigger = i > returned and times[i]-times[began] >= 60. and support
                trigger = trigger and arm*(prices[i]-extreme) >= .25*width
            if arm and trigger:
                trigger = arm*history[i,10] > 0. and arm*history[i,11] > 0.
                if retest == 0:
                    trigger = trigger and arm*market[i,5] > .05 and arm*market[i,7] > .05
                elif np.isfinite(market[i,5]) and np.isfinite(market[i,7]):
                    if arm*market[i,5] < -.25 and arm*market[i,7] < -.25:
                        if trigger and quote_ok:
                            arm = 0
                        trigger = False
            if not (arm and trigger and quote_ok):
                continue
            # ----------------------------------------
            # 入口核と同じ候補資格の後で価格記録を確認する。損益の判断は一切行わない。
            quote = ask[i] if arm > 0 else bid[i]
            if arm*(quote-level) > 1.e9*width:
                continue
            slot = 0 if arm > 0 else 1
            if np.isfinite(bquote[slot]) and arm*(quote-bquote[slot]) > 0.:
                events[ec] = np.array([i,2,arm,quote,bquote[slot],blevel[slot],bwidth[slot],
                    brow[slot],barm[slot],began,level,width,prices[i],stage,progressed,returned])
                ec += 1
                arm = 0
                continue
            confirmed = activity[i,3] == 1. and np.isfinite(activity[i,:3]).all()
            confirmed = confirmed and arm*activity[i,0] > 0. and activity[i,1] > 0. and arm*activity[i,2] < 0.
            if not confirmed:
                if not np.isfinite(bquote[slot]):
                    bquote[slot], blevel[slot], bwidth[slot] = quote, level, width
                    brow[slot], barm[slot] = i, began
                    events[ec] = np.array([i,1,arm,quote,bquote[slot],blevel[slot],bwidth[slot],
                        brow[slot],barm[slot],began,level,width,prices[i],stage,progressed,returned])
                    ec += 1
                arm = 0
                continue
            assert matched < len(expected) and expected[matched] == i
            code = 6 if np.isfinite(bquote[slot]) else 7
            events[ec] = np.array([i,code,arm,quote,bquote[slot],blevel[slot],bwidth[slot],
                brow[slot],barm[slot],began,level,width,prices[i],stage,progressed,returned])
            ec += 1
            matched += 1
            arm = 0
    assert matched == len(expected)
    return events[:ec]


def decode_events(values: np.ndarray, rd: dict) -> list[dict]:
    """
    機能: 非金融の価格記録配列へ原行・価格時計・日本語理由を付ける。
    引数: values(ndarray)、rd(dict)はイベント列と自己入力。
    返り値: list[dict]は欠測を維持した公開可能な観測記録。
    """
    out = []
    for v in values:
        row, code, side = int(v[0]), int(v[1]), int(v[2])
        budget_row, budget_arm = int(v[7]), int(v[8])
        out.append(dict(row=row,time=stamp(rd["time_s"][row]),code=code,reason=EVENT_NAMES[code],side=side,
            decision_quote=float(v[3]),budget_quote=float(v[4]),budget_level=float(v[5]),budget_width=float(v[6]),
            budget_row=budget_row,budget_time=stamp(rd["time_s"][budget_row]) if budget_row>=0 else None,
            budget_arm_row=budget_arm,budget_arm_time=stamp(rd["time_s"][budget_arm]) if budget_arm>=0 else None,
            arm_row=int(v[9]),arm_time=stamp(rd["time_s"][int(v[9])]) if v[9]>=0 else None,
            arm_level=float(v[10]),arm_width=float(v[11]),observed_price=float(v[12]),stage=int(v[13]),
            progress_row=int(v[14]),return_row=int(v[15])))
    return out


def main() -> None:
    """
    機能: 完成済み第四巡の全親・価格記録を元の第二巡と対応させる。
    引数: なし。
    返り値: None。保存保有を固定した診断であり、新たな金融運転ではない。
    """
    accounts = read(TASK/"round4/全条件の会計.json")
    assert accounts["passed"]
    olddata = read(HERE/"第二巡の入口見送り後の全親差分.json")
    oldrecords = {(r["method"],r["session"],r["symbol"]):[] for r in olddata["records"]}
    for r in olddata["records"]:
        oldrecords[r["method"],r["session"],r["symbol"]].append(r)
    expected_net = {(r["method"],r["session"],r["symbol"]):r["net"] for r in accounts["rows"]}
    refs = [r for r in read(OLD/"入力準備.json")["packets"] if r["session"].endswith("_Night")]
    comparison, events, allrecords = [], [], []
    for ref in refs:
        scene = ref["session"]
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        for method,base,kind,retest in (("W11","W07","last",0),("W12","W08","mid",1)):
            inputs, markets, history, _ = features129.build(packet,kind)
            for symbol in ("TOPIX","NK225"):
                key = scene,symbol
                rd,q,m,h = inputs[key],packet["quotes"][key],markets[key],history[key]
                ts = rd["time_s"]
                with np.load(TASK/"round4/measurement"/f"{symbol}_{scene}.npz") as z:
                    orders,trades = z[method+"__orders"],z[method+"__trades"]
                openings = orders[orders[:,7]==1.]
                good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
                good &= (q["bid"]>0.) & (q["ask"]>q["bid"])
                allowed = (ts>=rd["start"]) & (ts>=rd["us_open"]+1320.) & (ts<rd["limit"])
                for opening in openings:
                    parent = int(opening[2])
                    owned = trades[trades[:,14]==parent]
                    assert len(owned)==1
                    end = np.searchsorted(ts,ts[int(owned[0,1])]+300.,side="left")
                    allowed[int(opening[1])+1:end] = False
                with np.load(TASK/"prepared"/f"{symbol}_{scene}.npz") as z:
                    activity = z["activity"]
                values = trace_budget(ts,rd["last"],rd["atr"],h,m,q["bid"],q["ask"],good,activity,
                    allowed,openings[:,1].astype(np.int64),rd["tick"],rd["us_open"],rd["limit"],retest)
                decoded = decode_events(values,rd)
                events.extend(dict(method=method,session=scene,symbol=symbol,**e) for e in decoded)
                records = []
                for opening in openings:
                    parent,d,e = int(opening[2]),int(opening[1]),int(opening[0])
                    tr = trades[trades[:,14]==parent][0]
                    close = orders[(orders[:,2]==parent)&(orders[:,7]==0.)]
                    assert len(close)==1
                    accepted = next(v for v in decoded if v["row"]==d and v["code"] in (6,7))
                    assert accepted["side"]==opening[3]
                    if accepted["code"]==6:
                        assert accepted["side"]*(accepted["decision_quote"]-accepted["budget_quote"])<=0.
                    r = dict(method=method,session=scene,symbol=symbol,parent=parent,decision_row=d,entry_row=e,
                        decision_time=stamp(ts[d]),entry_time=stamp(ts[e]),side=int(opening[3]),quantity=int(opening[4]),
                        entry=float(opening[5]),exit_decision_row=int(close[0,1]),exit_row=int(tr[1]),
                        exit_time=stamp(ts[int(tr[1])]),exit=float(tr[5]),gross=float(tr[6]),fee=float(tr[7]),
                        net=float(tr[8]),mfe=float(tr[9]),mae=float(tr[10]),width=float(tr[11]),reason=int(tr[12]),
                        budget_observation=accepted,
                        execution_move=float(opening[3]*(opening[5]-accepted["decision_quote"])))
                    records.append(r)
                assert sum(r["net"] for r in records)==expected_net[method,scene,symbol]
                previous = oldrecords.get((base,scene,symbol),[])
                matched,pairs = set(),[]
                for r in records:
                    old = next((p for p in previous if p["entry_row"]==r["entry_row"] and p["side"]==r["side"]),None)
                    pair_kind = "新しく生じた親"
                    if old:
                        matched.add(old["parent"])
                        same = all(old[k]==r[k] for k in ("entry","exit_row","exit","net","mfe","mae","width"))
                        pair_kind = "同一親を維持" if same else "同一入口で保有経路が変化"
                    pairs.append(dict(kind=pair_kind,old=old,new=r,
                        delta=r["net"]-(old["net"] if old else 0.)))
                for old in previous:
                    if old["parent"] not in matched:
                        relevant = [v for v in decoded if v["side"]==old["side"] and v["row"]<=old["decision_row"]]
                        exact = [v for v in relevant if v["row"]==old["decision_row"]]
                        pairs.append(dict(kind="元の親が消えた",old=old,new=None,delta=-old["net"],
                            event_at_old_decision=exact,previous_events=relevant[-3:]))
                net,oldnet = sum(r["net"] for r in records),sum(r["net"] for r in previous)
                assert sum(p["delta"] for p in pairs)==net-oldnet
                comparison.append(dict(method=method,base=base,session=scene,symbol=symbol,
                    old_net=oldnet,new_net=net,delta=net-oldnet,pairs=pairs,
                    event_counts={name:sum(e["code"]==code for e in decoded)for code,name in EVENT_NAMES.items()}))
                allrecords.extend(records)
        print(scene,"価格記録と保存新規判断を照合",flush=True)
    groups = []
    for method in ("W11","W12"):
        for symbol in ("TOPIX","NK225"):
            selected=[a for a in comparison if a["method"]==method and a["symbol"]==symbol]
            pairs=[p for a in selected for p in a["pairs"]]
            gone=[p["old"] for p in pairs if p["kind"]=="元の親が消えた"]
            fresh=[p["new"] for p in pairs if p["kind"]=="新しく生じた親"]
            groups.append(dict(method=method,symbol=symbol,old_net=sum(a["old_net"] for a in selected),
                new_net=sum(a["new_net"] for a in selected),kept=sum(p["kind"]=="同一親を維持" for p in pairs),
                same_entry_changed=sum(p["kind"]=="同一入口で保有経路が変化"for p in pairs),
                same_entry_changed_delta=sum(p["delta"]for p in pairs if p["kind"]=="同一入口で保有経路が変化"),
                removed_wins=sum(r["net"]>0 for r in gone),removed_profit=sum(max(r["net"],0.)for r in gone),
                removed_losses=sum(r["net"]<0 for r in gone),removed_loss=sum(min(r["net"],0.)for r in gone),
                fresh=len(fresh),fresh_net=sum(r["net"]for r in fresh)))
    source=TASK/"night_budget130.py"
    save(HERE/"第四巡の価格記録と全親差分.json",dict(passed=True,financial_replays=0,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),accounts=comparison,events=events,
        records=allrecords,groups=groups,
        observation_only="保存親の保有・返済後待機区間を固定。非保有中の準備・価格記録だけを独立復元し、全新規判断原行と一致を要求。注文核は未実行。",
        execution_limit="判断BBOが保存基準内でも、次正常原行の約定BBOが不利になる可能性は残る。"))
    print(groups)


if __name__=="__main__":
    main()
