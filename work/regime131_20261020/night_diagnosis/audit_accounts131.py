"""保存注文だけから現金・建玉・全原行清算価値を再計算する独立会計監査。"""

import argparse
from datetime import datetime, time
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time as clock
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
BASE = ROOT / "work/daynight128_20261020"
PHASES = (
    "日本現物寄付前", "日本現物前場", "日本現物昼休み", "日本現物後場",
    "日本現物引け注文時間以降", "日本現物休場の先物日中",
    "欧州取引中・米国朝前", "米国8時30分以降・寄付前",
    "米国現物寄付後30分", "欧米現物の重複時間", "欧州引け後の米国時間",
    "米国現物引け前1時間", "米国現物終了後",
)
HOLIDAYS = {"2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12"}


def read(path):
    """
    機能: 確定済みの日本語資料を読み込む。
    引数: path(Path)は入力ファイル。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path):
    """
    機能: 入力・監査源の位置と内容指紋を記録する。
    引数: path(Path)はプロジェクト内のファイル。
    返り値: dict[str,str]は相対位置とＳＨＡ２５６。
    """
    return {"path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def require(condition, label):
    """
    機能: 監査条件が不成立なら具体的な項目名で停止する。
    引数: condition(bool)は検査結果、label(str)は検査項目。
    返り値: None。不成立時はAssertionErrorを送出する。
    """
    if not bool(condition):
        raise AssertionError(label)


def equal(actual, expected, label):
    """
    機能: 金額・価格配列を絶対誤差一百万分の一以内で照合する。
    引数: actual/expected(ndarray又はfloat)、label(str)は検査対象。
    返り値: floatは最大絶対差。
    """
    a, e = np.asarray(actual), np.asarray(expected)
    require(a.shape == e.shape, label + "の形")
    require(np.isfinite(a).all() and np.isfinite(e).all(), label + "の有限性")
    gap = float(np.max(np.abs(a-e))) if a.size else 0.
    require(gap <= 1e-6, label + "の差=" + str(gap))
    return gap


def independent_phases(ready):
    """
    機能: 価格を使わず日本・米国・欧州の現物時刻区分を再構成する。
    引数: ready(dict)は保存セッション時刻・原行時計。
    返り値: ndarray[int64]は13区分番号。
    """
    datestr = ready["session"].split("_")[0]
    day = datetime.fromisoformat(datestr).date()
    times = ready["time_s"]
    if ready["session"].endswith("_Day"):
        if datestr in HOLIDAYS:
            return np.full(len(times), 5, dtype=np.int64)
        midnight = datetime.combine(day, time(), ZoneInfo("Asia/Tokyo")).timestamp()
        boundaries = midnight + 60.*np.array([540., 690., 750., 925.])
        return np.searchsorted(boundaries, times, side="right").astype(np.int64)
    opening = datetime.combine(day, time(9, 30), ZoneInfo("America/New_York")).timestamp()
    equal(float(ready["us_open"]), opening, "米国寄付時刻と夏時間")
    europe = datetime.combine(day, time(16, 30), ZoneInfo("Europe/London")).timestamp()
    boundaries = np.array([opening-3600., opening, opening+1800., europe,
                           opening+19800., opening+23400.])
    require(np.all(np.diff(boundaries) > 0.), "夜間区分境界の順序")
    return np.searchsorted(boundaries, times, side="right").astype(np.int64)+6


def independent_states(history, atr, phase, selector):
    """
    機能: 観測資料既知行の状態番号だけを別式で再構成する。
    引数: history/atr/phase(ndarray)、selector(int)は確定条件番号。
    返り値: ndarray[int64]は未知0、追随1、回帰2。
    """
    known = np.isfinite(history).all(axis=1) & np.isfinite(atr) & (atr > 0.)
    active = np.isin(phase, (1, 3, 8, 9, 10, 11))
    trend = np.ones(len(atr), dtype=bool)
    if selector == 1:
        trend[:] = False
    elif selector == 2:
        trend = active
    elif selector >= 3:
        threshold = np.full(len(atr), .35)
        if selector == 4:
            threshold = np.where(active, .25, .45)
        trend = (history[:, 5] >= threshold) & (history[:, 7]*history[:, 11] > 0.)
    return np.where(known, np.where(trend, 1, 2), 0).astype(np.int64)


def audit_account(orders, trades, curve, ready, quotes, history, phase, config, row):
    """
    機能: 保存注文から会計を独立再構成し、約定・親・区分・参加を照合する。
    引数: orders/trades/curve/history/phase(ndarray)、ready/quotes/config/row(dict)
          は保存入力・結果・集計値。売買核は呼ばない。
    返り値: dictは会計一致数、実参加、期限参加と全原行誤差。
    """
    times = ready["time_s"]
    bid, ask = quotes["bid"], quotes["ask"]
    n = len(times)
    good = quotes["quote_valid"] & np.isfinite(bid) & np.isfinite(ask)
    good &= (ask > bid) & (bid > 0.)
    goodrows = np.flatnonzero(good)
    top = ready["symbol"] == "TOPIX"
    quantity, multiplier, fee = (5, 1000., 209) if top else (10, 10., 110)
    require(orders.shape == (2*len(trades), 12), "注文列数と完結親数")
    require(trades.ndim == 2 and trades.shape[1] == 17, "親17列")
    require(curve.shape == (n, 5), "全原行の曲線5列")
    require(np.isfinite(orders).all() and np.isfinite(trades).all(), "注文と親の有限性")
    require(np.isfinite(times).all() and np.all(np.diff(times) >= 0.), "原時計順")
    integers = (0, 1, 2, 3, 4, 6, 7, 8, 11)
    equal(orders[:, integers], orders[:, integers].astype(np.int64), "注文整数項目")
    fillrows, decisions = orders[:, 0].astype(int), orders[:, 1].astype(int)
    require(np.all((0 <= decisions) & (decisions < fillrows) & (fillrows < n)), "判断の次行以降")
    require(np.all(np.diff(fillrows) > 0), "実注文の原行順と同一行重複なし")
    equal(orders[:, 4], np.full(len(orders), quantity), "注文ごとの枚数")
    equal(orders[:, 8], np.full(len(orders), fee), "注文ごとの切捨て手数料")
    require(np.isin(orders[:, 3], (-1, 1)).all(), "注文売買方向")
    equal(orders[:, 7], np.tile((1., 0.), len(trades)), "新規と全返済の交互")
    equal(orders[:, 2], np.repeat(np.arange(len(trades)), 2), "親の連番")
    equal(orders[:, 9], times[fillrows], "約定時計")
    equal(orders[:, 10], times[decisions], "判断時計")
    equal(orders[:, 11], phase[fillrows], "約定時の時間区分")
    next_positions = np.searchsorted(goodrows, decisions, side="right")
    require(np.all(next_positions < len(goodrows)), "後続正常気配の存在")
    equal(fillrows, goodrows[next_positions], "判断後最初の正常気配")
    expected_fill = np.where(orders[:, 3] > 0, ask[fillrows], bid[fillrows])
    equal(orders[:, 5], expected_fill, "売り気配で買い・買い気配で売り")
    openmask = orders[:, 7] == 1
    require(np.all(times[fillrows[openmask]] < ready["limit"]), "終端後の新規なし")
    require(np.all(times[decisions[openmask]] < ready["limit"]-600.), "終端10分前以降の新判断なし")
    require(np.isin(orders[openmask, 6], (80, 81, 82)).all(), "新規理由")
    require(np.isin(orders[~openmask, 6], (32, 70, 71, 75, 93)).all(), "返済理由")
    terminal = (~openmask) & (orders[:, 6] == 93)
    require(np.all(times[decisions[terminal]] >= ready["limit"]), "場内返済の終端判断")
    openings, closings = orders[::2], orders[1::2]
    if len(trades) > 1:
        require(np.all(openings[1:, 10]-closings[:-1, 9] >= 300.), "返済後5分の新規待機")
    blocks = np.cumsum(np.r_[True, phase[1:] != phase[:-1]])-1
    if len(openings):
        counts = np.bincount(blocks[openings[:, 0].astype(int)])
        require(int(counts.max()) <= config["per_phase"], "連続時間区分ごとの参加上限")
    # ----------------------------------------
    # 注文の増減だけを全原行へ展開し、既存曲線を計算には使わない。
    cash_change = np.zeros(n)
    position_change = np.zeros(n)
    entryprice = np.zeros(n)
    computed_net = np.empty(len(trades))
    for parent, (opening, closing, trade) in enumerate(zip(openings, closings, trades)):
        a, b = int(opening[0]), int(closing[0])
        side = int(opening[3])
        gross = side*(closing[5]-opening[5])*quantity*multiplier
        net = gross-2*fee
        computed_net[parent] = net
        expected = np.array([parent, a, b, side, quantity, opening[5], closing[5],
                             gross, 2*fee, net])
        equal(trade[:10], expected, "親"+str(parent)+"の価格・枚数・現金会計")
        equal(closing[3], -side, "親"+str(parent)+"の返済方向")
        equal(trade[13], phase[a], "親"+str(parent)+"の新規時区分")
        equal(trade[15:17], [opening[6], closing[6]], "親"+str(parent)+"の新規返済理由")
        require(trade[10] >= 4*ready["tick"], "親の初期尺度下限")
        require(trade[11] >= 0. and trade[12] <= 0., "親の最大順行逆行の符号")
        require(trade[14] in (1., 2.), "親の最終手法番号")
        if not config["conversion"] and opening[6] in (80, 82):
            equal(trade[14], 1., "追随親の最終手法")
        if not config["conversion"] and opening[6] == 81:
            equal(trade[14], 2., "回帰親の最終手法")
        cash_change[a] -= fee
        cash_change[b] += gross-fee
        position_change[a] += side*quantity
        position_change[b] -= side*quantity
        entryprice[a:b] = opening[5]
    cash = np.cumsum(cash_change)
    position = np.cumsum(position_change)
    require(np.all(np.abs(position) <= quantity), "全原行の保有上限")
    require(position[-1] == 0., "最終全返済")
    lastgood = np.maximum.accumulate(np.where(good, np.arange(n), -1))
    heldrows = np.flatnonzero(position)
    require(np.all(lastgood[heldrows] >= 0), "保有時の清算気配が既知")
    liquidation = np.zeros(n)
    mark = np.where(position[heldrows] > 0., bid[lastgood[heldrows]], ask[lastgood[heldrows]])
    liquidation[heldrows] = position[heldrows]*(mark-entryprice[heldrows])*multiplier-fee
    equity = cash+liquidation
    peak = np.maximum.accumulate(np.maximum(equity, 0.))
    drawdown = np.maximum.accumulate(peak-equity)
    expected_curve = np.column_stack((equity, position, cash, drawdown,
                                      independent_states(history, ready["atr"], phase, config["selector"])))
    curve_error = equal(curve, expected_curve, "全原行の現金・保有・清算価値・下落幅・観測状態")
    # ----------------------------------------
    # 期限参加は適時価格を別計算し、無取引を会計正常と混同しない。
    deadline = openings[openings[:, 6] == 82]
    require(len(deadline) <= 1, "初回期限参加は一回以下")
    for order in deadline:
        i = int(order[1])
        require(order[2] == 0., "期限参加は最初の親")
        require(times[i] >= ready["start"]+config["participation_seconds"], "初回期限の経過")
        require(np.isfinite(history[i]).all() and ready["atr"][i] > 0., "期限時の資料既知")
        h = history[i]
        expected_direction = np.sign(np.sign(h[7])+np.sign(h[11])+.5*(np.sign(h[6])+np.sign(h[10])))
        if expected_direction == 0:
            expected_direction = np.sign(h[7])
        if expected_direction == 0:
            expected_direction = np.sign((bid[i]+ask[i])*.5-h[8])
        equal(order[3], expected_direction, "期限参加の当時二市場方向")
        risk = max(ready["atr"][i], 4*ready["tick"])
        if config["width_mode"]:
            risk = max(risk, .5*(h[3]-h[4]))
        equal(trades[0, 10], risk, "期限参加の当時初期尺度")
        require(ask[i]-bid[i] <= .5*risk, "期限参加の気配幅")
    # ----------------------------------------
    # 新規時区分へ親を帰属する集計と、観測時区分へ値洗い増減を帰属する集計を区別する。
    expected_summary = {
        "profit": computed_net[computed_net > 0].sum(),
        "loss": -computed_net[computed_net < 0].sum(), "net": computed_net.sum(),
        "gross": trades[:, 7].sum(), "fees": 2*fee*len(trades),
        "entries": len(trades), "quantity": quantity*len(trades),
        "parent_wins": (computed_net > 0).sum(), "parent_losses": (computed_net < 0).sum(),
        "max_quantity": np.abs(position).max(), "max_drawdown": drawdown[-1],
        "deadline_entries": len(deadline),
    }
    for name, value in expected_summary.items():
        equal(row[name], value, "公開集計:"+name)
    require(row["method"] == config["id"] and row["session"] == ready["session"]
            and row["symbol"] == ready["symbol"], "集計の識別子")
    changes = np.diff(np.r_[0., equity])
    for number, name in enumerate(PHASES):
        selected = trades[:, 13] == number
        equal(row["phases"][name]["entries"], selected.sum(), "入口区分件数:"+name)
        equal(row["phases"][name]["net"], computed_net[selected].sum(), "入口区分金額:"+name)
        equal(row["phase_equity_changes"][name], changes[phase == number].sum(), "観測区分金額:"+name)
    for side, name in ((1, "買い"), (-1, "売り")):
        selected = trades[:, 3] == side
        equal(row["direction"][name]["entries"], selected.sum(), "方向別件数:"+name)
        equal(row["direction"][name]["net"], computed_net[selected].sum(), "方向別金額:"+name)
    equal(computed_net.sum(), equity[-1], "最終親収支と清算価値")
    return dict(method=config["id"], session=ready["session"], symbol=ready["symbol"],
                source_rows=n, orders=len(orders), parents=len(trades), net=float(computed_net.sum()),
                entered=bool(len(trades)), deadline_entries=len(deadline),
                first_entry_seconds=float(openings[0, 9]-ready["start"]) if len(openings) else None,
                maximum_curve_error=curve_error)


def main():
    """
    機能: 完了済み一巡の保存口座を読み、金融再生ゼロで独立監査する。
    引数: --round(str)は完了済み結果フォルダ。
    返り値: None。新しい時刻付き監査証拠を保存し、不一致なら終了コード1。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = TASK / args.round
    require(folder.resolve().is_relative_to(TASK.resolve()), "結果位置が今回作業内")
    completed_path = folder / "全条件の会計.json"
    require(completed_path.exists(), "全条件完了前には実値を監査しない")
    completed = read(completed_path)
    require(completed["passed"], "金融処理が完了済み")
    fixed = read(folder / "固定計画.json")
    require(completed["configs"] == fixed["configs"], "登録条件と実行条件")
    require(completed["sources"] == fixed["sources"], "登録源と実行源")
    for path, digest in completed["sources"].items():
        require(reference(ROOT / path)["sha256"] == digest, "凍結源:"+path)
    manifest_path = BASE / "入力準備.json"
    packet_refs = read(manifest_path)["packets"]
    cache = {(r["session"], r["symbol"]): r for r in completed["cache"]}
    rows = {(r["session"], r["symbol"], r["method"]): r for r in completed["rows"]}
    require(len(rows) == len(completed["rows"]), "集計の重複なし")
    require(len(cache) == len(packet_refs)*2, "全商品場の保存結果が存在")
    require(len(rows) == len(cache)*len(completed["configs"]), "全条件の集計行数")
    sys.path.insert(0, str(TASK))
    import features131
    require("engine131" not in sys.modules, "金融核を読み込んでいない")
    results, errors, inputs = [], [], []
    for packet_ref in packet_refs:
        packet_path = ROOT / packet_ref["path"]
        require(reference(packet_path)["sha256"] == packet_ref["sha256"], "原入力指紋")
        inputs.append(packet_ref)
        packet = pickle.loads(packet_path.read_bytes())
        prepared, markets, histories, declared_phases = features131.build(packet)
        del markets
        scene = packet_ref["session"]
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            ready, quotes = prepared[key], packet["quotes"][key]
            phase = independent_phases(ready)
            equal(declared_phases[key], phase, "時間区分の独立算出:"+scene+symbol)
            ref = cache[key]
            npz_path = ROOT / ref["path"]
            require(reference(npz_path)["sha256"] == ref["sha256"], "保存結果指紋")
            with np.load(npz_path) as arrays:
                for config in completed["configs"]:
                    mid = config["id"]
                    try:
                        result = audit_account(arrays[mid+"__orders"], arrays[mid+"__trades"],
                                               arrays[mid+"__curve"], ready, quotes, histories[key],
                                               phase, config, rows[(scene, symbol, mid)])
                        results.append(result)
                    except (AssertionError, IndexError, KeyError, ValueError) as exc:
                        errors.append(dict(session=scene, symbol=symbol, method=mid,
                                           error=str(exc)))
            print(scene, symbol, len(results), "会計照合済み", "不一致", len(errors), flush=True)
    require("engine131" not in sys.modules, "監査完了まで金融核を読み込んでいない")
    missing = [r for r in results if not r["entered"]]
    output = {
        "passed": not errors and len(results) == len(rows),
        "accounting_passed": not errors and len(results) == len(rows),
        "all_accounts_entered": not missing and not errors,
        "financial_replays": 0, "real_orders": 0, "market_API": 0,
        "scope": "保存注文の現金・全原行値洗い・次正常気配・親・枚数・費用・時間帰属・期限参加。金融経路は再実行しない。",
        "limitations": "利益優位性・実受信時計・ミニ実板約定は本監査の検証対象ではない。無取引は会計合否と別の目標未達。",
        "sources": completed["sources"], "checker": reference(Path(__file__).resolve()),
        "completed": reference(completed_path), "manifest": reference(manifest_path),
        "input_packets": inputs, "accounts": len(results), "expected_accounts": len(rows),
        "source_rows_checked": sum(r["source_rows"] for r in results),
        "orders_checked": sum(r["orders"] for r in results),
        "parents_checked": sum(r["parents"] for r in results),
        "maximum_curve_error": max((r["maximum_curve_error"] for r in results), default=0.),
        "zero_entry_accounts": missing, "errors": errors, "rows": results,
    }
    target = HERE / ("独立全原行会計_"+args.round+"_"+str(clock.time_ns())+".json")
    require(not target.exists(), "監査証拠を上書きしない")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n",
                      encoding="utf-8")
    print(target.as_posix(), "合格", output["passed"], "全場参加", output["all_accounts_entered"],
          "金融再生", 0, flush=True)
    if not output["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
