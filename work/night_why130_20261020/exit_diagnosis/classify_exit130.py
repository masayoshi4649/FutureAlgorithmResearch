"""夜間の保存親を、保護起動前の反転と停止後の回復・損失拡大に分ける。"""

import hashlib
import json
from pathlib import Path
import pickle
from datetime import datetime, timedelta, timezone

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
OLD = ROOT/"work/daynight128_20261020"
PREV = ROOT/"work/visual_pdca129_20261020"
JST = timezone(timedelta(hours=9))
READS = []


def read(path: Path):
    """
    機能: 保存JSONの内容と指紋を取得する。
    引数: path(Path)は既存資料位置。
    返り値: objectは保存内容。
    """
    raw = path.read_bytes()
    READS.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(raw).hexdigest()))
    return json.loads(raw)


def verified(ref: dict) -> Path:
    """
    機能: 保存資料を既存SHA256と照合する。
    引数: ref(dict)はpathとsha256。
    返り値: Pathは照合済み位置。
    """
    path = ROOT/ref["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
    READS.append(dict(path=ref["path"], sha256=ref["sha256"]))
    return path


def clock(value: float) -> str:
    """
    機能: 原価格時計を日本時間で表示する。
    引数: value(float)はUTC秒。
    返り値: strは年月日時分秒。
    """
    return datetime.fromtimestamp(float(value), JST).strftime("%Y-%m-%d %H:%M:%S")


def contact(rows: np.ndarray, values: np.ndarray, threshold: float, above: bool,
            times: np.ndarray, width: float) -> dict | None:
    """
    機能: 同じ観測範囲で価格障壁への最初の接触を記録する。
    引数: rows/values/times(ndarray)、threshold/width(float)、above(bool)は経路と障壁。
    返り値: dict又はNoneは接触原行・時計・幅。売買指示ではない。
    """
    hits = np.flatnonzero(values >= threshold if above else values <= threshold)
    if not len(hits):
        return None
    at = int(hits[0])
    row = int(rows[at])
    return dict(row=row, time=clock(times[row]), points=float(values[at]), R=float(values[at]/width))


def path_class(rows: np.ndarray, movements: np.ndarray, times: np.ndarray, width: float) -> dict:
    """
    機能: 保存出口後の回復と損失拡大を同じ経路の先着事象として分類する。
    引数: rows/movements/times(ndarray)、width(float)は正常気配経路と元初期幅。
    返り値: dictは接触時刻、先着、最大順逆行。新しい損益は計算しない。
    """
    events = {}
    for value in (0., .5, 1.):
        events["回復"+str(value)] = contact(rows, movements, value*width, True, times, width)
    for value in (1.5, 2.):
        events["拡大"+str(value)] = contact(rows, movements, -value*width, False, times, width)
    race = {}
    for up in (0., .5, 1.):
        for down in (1.5, 2.):
            a, b = events["回復"+str(up)], events["拡大"+str(down)]
            result = "どちらも未接触"
            if a and (not b or a["row"] < b["row"]):
                result = "回復が先"
            elif b:
                result = "拡大が先"
            race[f"{up}/{down}"] = result
    return dict(rows=len(rows), begin=clock(times[int(rows[0])]) if len(rows) else None,
        end=clock(times[int(rows[-1])]) if len(rows) else None, contacts=events, race=race,
        maximum_R=float(np.max(movements)/width) if len(rows) else None,
        minimum_R=float(np.min(movements)/width) if len(rows) else None,
        largest_price_clock_gap=float(np.max(np.diff(times[rows]), initial=0)) if len(rows) else None)


def classify(method: str, scene: str, symbol: str, packet: dict, orders: np.ndarray,
             trades: np.ndarray, reference_only: bool = False) -> list:
    """
    機能: 元親の保有中と返済後を原行で追い、失敗と勝ちの反例を同条件で記録する。
    引数: method/scene/symbol(str)、packet(dict)、orders/trades(ndarray)、reference_only(bool)。
    返り値: list[dict]は親ごとの接触・先着分類。元入口出口を改変しない。
    """
    ready, quote = packet["inputs"][scene, symbol], packet["quotes"][scene, symbol]
    times, bid, ask = ready["time_s"], quote["bid"], quote["ask"]
    good = quote["quote_valid"] & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.) & (bid < ask)
    rows = np.flatnonzero(good)
    tick = ready["tick"]
    records = []
    for cid, trade in enumerate(trades):
        if reference_only and not (scene == "2026-09-30_Night" and symbol == "NK225" and cid == 0):
            continue
        own = orders[orders[:, 2] == cid]
        entry_order, exit_order = own[own[:, 7] == 1], own[own[:, 7] == 0]
        assert len(entry_order) == len(exit_order) == 1
        first, last = int(trade[0]), int(trade[1])
        direction, entry, width = int(trade[2]), float(trade[4]), float(trade[11])
        mark = bid if direction > 0 else ask
        held = rows[(rows >= first) & (rows <= last)]
        movement = direction*(mark[held]-entry)
        peak = np.maximum.accumulate(np.maximum(movement, 0.))
        assert np.isclose(max(float(np.max(movement)), 0.), trade[9])
        assert np.isclose(min(float(np.min(movement)), 0.), trade[10])
        peak_at = int(np.argmax(movement))
        prior_ranges = {}
        for minutes in (2, 5, 10, 20):
            before = rows[(rows <= first) & (times[rows] >= times[first]-60.*minutes)]
            prior_ranges[str(minutes)] = dict(
                minimum=float(np.min(mark[before])), maximum=float(np.max(mark[before])),
                range_points=float(np.max(mark[before])-np.min(mark[before])),
                range_R=float((np.max(mark[before])-np.min(mark[before]))/width))
        contacts = {str(r): contact(held, movement, r*width, True, times, width)
                    for r in (.25, .5, .75, 1.)}
        exit_decision = int(exit_order[0, 1])
        # ----------------------------------------
        # 根拠確認用の二つの条件。旧出口前の接触を数え、新しい注文・収支は作らない。
        mechanisms = {}
        trigger_masks = {
            "起動前から最高順行引く1R": (peak > 0.) & (peak < width) & (movement <= peak-width),
            "0.5R後0.25R押返し半分": (peak >= .5*width) & (movement <= peak-.25*width),
        }
        for name, mask in trigger_masks.items():
            positions = np.flatnonzero(mask & (held < exit_decision))
            event = None
            if len(positions):
                at = int(positions[0])
                row = int(held[at])
                following = int(rows[np.searchsorted(rows, row, side="right")])
                event = dict(row=row, time=clock(times[row]), mark=float(mark[row]),
                    movement_R=float(movement[at]/width), peak_R=float(peak[at]/width),
                    next_normal_row=following, next_normal_time=clock(times[following]),
                    next_normal_mark=float(mark[following]),
                    next_normal_movement_R=float(direction*(mark[following]-entry)/width),
                    original_exit_minus_contact_points=float(direction*(trade[5]-mark[row])),
                    original_exit_minus_next_points=float(direction*(trade[5]-mark[following])),
                    original_winner=bool(trade[8] > 0.),
                    original_net=float(trade[8]),
                    original_later_peak_R=float(np.max(movement[at:])/width),
                    measurement_only=True)
            mechanisms[name] = event
        future_entries = orders[(orders[:, 7] == 1) & (orders[:, 1] > last)]
        next_decision = int(future_entries[0, 1]) if len(future_entries) else len(times)
        session_rows = rows[(rows > last) & (times[rows] <= ready["limit"])]
        next_rows = session_rows[session_rows < next_decision]
        # ----------------------------------------
        # 起動の呼値切捨て案が元保有内で新たに触る箇所だけを分類する。注文は作らない。
        rounded = max(tick, np.floor(width/tick+1e-10)*tick)
        early_region = (peak >= rounded) & (peak < width)
        floor_touch = early_region & (movement <= peak-.75*width)
        hits = np.flatnonzero(floor_touch)
        rounded_event = None
        if len(hits):
            at = int(hits[0])
            row = int(held[at])
            rounded_event = dict(row=row, time=clock(times[row]), mark=float(mark[row]),
                movement_R=float(movement[at]/width), peak_R=float(peak[at]/width),
                floor_R=float((peak[at]-.75*width)/width),
                remaining_old_peak_R=float(np.max(movement[at:])/width),
                original_winner=bool(trade[8] > 0.),
                original_exit_unit_minus_contact=float(direction*(trade[5]-mark[row])))
        records.append(dict(method=method, session=scene, symbol=symbol, parent=cid,
            reference_only=reference_only, side="買い" if direction > 0 else "売り",
            direction=direction, quantity=int(trade[3]), entry_row=first, exit_row=last,
            entry_decision_row=int(entry_order[0, 1]), exit_decision_row=int(exit_order[0, 1]),
            entry_time=clock(times[first]), exit_time=clock(times[last]),
            entry=entry, exit=float(trade[5]), net=float(trade[8]), width=width, tick=float(tick),
            exit_reason=int(trade[12]), peak=float(trade[9]), peak_R=float(trade[9]/width),
            first_observed_maximum_time=clock(times[int(held[peak_at])]),
            first_observed_maximum_price=float(mark[int(held[peak_at])]),
            pre_entry_liquidation_quote_ranges=prior_ranges,
            adverse=float(trade[10]), adverse_R=float(trade[10]/width),
            activation_contacts=contacts, activation_not_reached=bool(trade[9] < width),
            nearest_activation_price=entry+direction*np.ceil(width/tick-1e-10)*tick,
            rounded_activation_points=float(rounded),
            rounded_activation_potential_early_exit=rounded_event,
            proposed_mechanism_contacts=mechanisms,
            before_next_original_entry=path_class(next_rows, direction*(mark[next_rows]-entry), times, width),
            through_session_end=path_class(session_rows, direction*(mark[session_rows]-entry), times, width),
            next_original_entry_decision=clock(times[next_decision]) if next_decision < len(times) else None))
    return records


def main() -> None:
    """
    機能: NV25/NV01/N36全親と指定NV15反例を保存入力で分類してJSONへまとめる。
    引数: なし。
    返り値: None。新金融再生・注文生成・実APIを行わない。
    """
    bases = {
        "N36": read(OLD/"round5/全条件の会計.json"),
        "NV01": read(PREV/"round1/全条件の会計.json"),
        "NV25": read(PREV/"round7/全条件の会計.json"),
        "NV15": read(PREV/"round4/全条件の会計.json")}
    refs = {m: {(r["session"], r["symbol"]): r for r in d["cache"]} for m, d in bases.items()}
    manifest = read(OLD/"入力準備.json")
    records = []
    for ref in manifest["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        packet = pickle.loads(verified(ref).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            for method in bases:
                special = method == "NV15"
                if special and (scene != "2026-09-30_Night" or symbol != "NK225"):
                    continue
                with np.load(verified(refs[method][scene, symbol]), allow_pickle=False) as data:
                    records.extend(classify(method, scene, symbol, packet,
                        data[method+"__orders"], data[method+"__trades"], special))
    summaries = []
    for method in ("N36", "NV01", "NV25"):
        for symbol in ("TOPIX", "NK225"):
            own = [r for r in records if r["method"] == method and r["symbol"] == symbol]
            losses = [r for r in own if r["net"] < 0.]
            early = [r for r in own if r["rounded_activation_potential_early_exit"]]
            stopped = [r for r in losses if r["exit_reason"] == 32]
            mechanisms = {}
            for name in ("起動前から最高順行引く1R", "0.5R後0.25R押返し半分"):
                touched = [r for r in own if r["proposed_mechanism_contacts"][name]]
                winners = [r for r in touched if r["net"] > 0.]
                losers = [r for r in touched if r["net"] < 0.]
                mechanisms[name] = dict(touched=len(touched), touched_original_winners=len(winners),
                    touched_original_losers=len(losers),
                    original_wins_later_exit_better_than_contact=sum(r["proposed_mechanism_contacts"][name]["original_exit_minus_next_points"] > 0 for r in winners),
                    original_wins_later_exit_worse_than_contact=sum(r["proposed_mechanism_contacts"][name]["original_exit_minus_next_points"] < 0 for r in winners),
                    original_losers_contact_already_negative=sum(r["proposed_mechanism_contacts"][name]["next_normal_movement_R"] < 0 for r in losers))
            race = {}
            for horizon in ("before_next_original_entry", "through_session_end"):
                race[horizon] = {}
                for barrier in ("0.0/1.5", "0.0/2.0", "0.5/1.5", "0.5/2.0", "1.0/1.5", "1.0/2.0"):
                    race[horizon][barrier] = {label: sum(r[horizon]["race"][barrier] == label for r in losses)
                        for label in ("回復が先", "拡大が先", "どちらも未接触")}
            stop_race = {}
            for horizon in ("before_next_original_entry", "through_session_end"):
                stop_race[horizon] = {}
                for barrier in ("0.0/1.5", "0.0/2.0", "1.0/1.5", "1.0/2.0"):
                    stop_race[horizon][barrier] = {label: sum(r[horizon]["race"][barrier] == label for r in stopped)
                        for label in ("回復が先", "拡大が先", "どちらも未接触")}
            summaries.append(dict(method=method, symbol=symbol, parents=len(own), losses=len(losses),
                loss_net=sum(r["net"] for r in losses),
                loss_peak_R_groups={label: sum(lower <= r["peak_R"] < upper for r in losses)
                    for label, lower, upper in (("0", 0., 1e-10), ("0より大0.5未満", 1e-10, .5),
                        ("0.5以上0.75未満", .5, .75), ("0.75以上1未満", .75, 1.), ("1以上", 1., np.inf))},
                all_losses_before_activation=all(r["activation_not_reached"] for r in losses),
                exit_reasons={str(code): sum(r["exit_reason"] == code for r in losses)
                    for code in sorted({r["exit_reason"] for r in losses})},
                rounded_early_exit_count=len(early),
                rounded_early_loss_count=sum(r["net"] < 0 for r in early),
                rounded_early_win_count=sum(r["net"] > 0 for r in early),
                proposed_mechanisms=mechanisms,
                initial_stop_parent_count=len(stopped),
                initial_stop_after_exit_races=stop_race,
                after_exit_races=race))
    result = dict(passed=True, summaries=summaries, rows=records, inputs=READS,
        financial_replays=0, API=0,
        scope="主対象NV25/NV01/N36の全保存親。NV15の9月30日NK1親は別の指定反例。",
        endpoint="返済後～次の元新規判断直前を主範囲、同じ場末までを別列。気配不明行は接触に使わない。",
        limitation="接触・先着の観測であり、出口改修の運転損益ではない。停止を広げた場合に変わる後続判断は未計測。",
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target = HERE/"夜間全親の保護未達と停止後の先着分類.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
