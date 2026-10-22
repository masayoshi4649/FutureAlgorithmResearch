"""旧手法と一回追加の接続を、保存市場資料を使わず独立人工で点検する。"""

import copy
from datetime import datetime
import hashlib
import json
import pickle
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import run_portfolio131 as runner
import audit_engine131 as helper
import audit_participation131 as participation_helper


def expected_ledger(orders, bid, ask, multiplier, fee):
    """
    機能: 人工注文を現金と親の残数量から独立に集計する。
    引数: orders/bid/ask(ndarray)、multiplier/fee(float)は人工約定と料金。
    返り値: dictは注文接続の比較に用いる独立会計。
    """
    n = len(bid)
    parents = {}
    cash = 0.
    gross = 0.
    paid = 0.
    count = 0
    longs, shorts, equity, realized, entries = [], [], [], [], []
    for i in range(n):
        for order in orders[orders[:, 0] == i]:
            row, source, parent, side, quantity = [int(x) for x in order[:5]]
            price, reason, new = order[5], int(order[6]), int(order[7])
            cost = quantity * int(round(fee * 10)) // 10
            paid += cost
            cash -= side * quantity * price * multiplier + cost
            if new:
                count += 1
                parents[parent] = dict(parent_id=parent, entry_row=row, exit_row=-1,
                    side=side, quantity=quantity, remaining=quantity, entry_price=price,
                    gross=0., fees=float(cost), net=0., exit_reason=0)
            else:
                p = parents[parent]
                change = p["side"] * (price - p["entry_price"]) * quantity * multiplier
                gross += change
                p["gross"] += change
                p["fees"] += cost
                p["remaining"] -= quantity
                p["exit_row"] = row
                p["exit_reason"] = reason
        long_count = sum(p["remaining"] for p in parents.values() if p["side"] == 1)
        short_count = sum(p["remaining"] for p in parents.values() if p["side"] == -1)
        close_fee = sum(p["remaining"] * int(round(fee * 10)) // 10 for p in parents.values())
        longs.append(long_count)
        shorts.append(short_count)
        equity.append(cash + (long_count * bid[i] - short_count * ask[i]) * multiplier - close_fee)
        realized.append(gross - paid)
        entries.append(count)
    for p in parents.values():
        p["net"] = p["gross"] - p["fees"]
        assert p["remaining"] == 0
    result = dict(parents=list(parents.values()), long_quantity=np.array(longs),
        short_quantity=np.array(shorts), liquidation_equity=np.array(equity),
        realized_cash=np.array(realized), entries_so_far=np.array(entries))
    peak = np.maximum.accumulate(np.maximum(equity, 0.))
    result["curve"] = np.column_stack([equity, np.array(longs) - shorts, realized,
        np.maximum.accumulate(peak - equity), np.zeros(n)])
    return result


def clock_audit():
    """
    機能: 日中予定時刻と欧米の夏時間切替日が異なる期間を照合する。
    引数: なし。
    返り値: None。
    """
    jst = ZoneInfo("Asia/Tokyo")
    for date in ("2026-10-12", "2026-10-20", "2026-10-28", "2026-11-04"):
        start = datetime.fromisoformat(date+"T08:45").replace(tzinfo=jst).timestamp()
        ready = dict(session=date+"_Day", start=start)
        helper.equal("早期45分"+date, runner.activation(ready, 0), start+2700)
        for mode, clock in ((1, "12:30"), (2, "14:00")):
            expected = datetime.fromisoformat(date+"T"+clock).replace(tzinfo=jst).timestamp()
            helper.equal("日中時刻"+date+str(mode), runner.activation(ready, mode), expected)
    for date, new_york, london in (
        ("2026-10-20", "2026-10-20T23:00", "2026-10-21T00:30"),
        ("2026-10-28", "2026-10-28T23:00", "2026-10-29T01:30"),
        ("2026-11-04", "2026-11-05T00:00", "2026-11-05T01:30"),
    ):
        opening = datetime.fromisoformat(date+"T09:30").replace(
            tzinfo=ZoneInfo("America/New_York")).timestamp()
        ready = dict(session=date+"_Night", us_open=opening, start=opening-20000)
        for mode, text in ((1, new_york), (2, london)):
            expected = datetime.fromisoformat(text).replace(tzinfo=jst).timestamp()
            helper.equal("欧米別夏時間"+date+str(mode), runner.activation(ready, mode), expected)
    try:
        runner.activation(ready, 3)
    except AssertionError:
        helper.check("不正予定拒否", True)
    else:
        raise AssertionError("不正予定が通過した")


def account_audit():
    """
    機能: 部分返済端数料金、方向別上限、相殺時価、区分合計を独立現金会計と照合する。
    引数: なし。
    返り値: None。
    """
    for symbol, qty, mult, fee in (("TOPIX", 5, 1000., 41.8), ("NK225", 10, 10., 11.)):
        bid = np.array([99., 99., 101., 103., 102., 99., 100., 101.])
        ask = bid+1
        phase = np.array([0, 1, 1, 2, 2, 3, 4, 4])
        ready = dict(session="2099-01-01_Day", symbol=symbol,
            time_s=np.arange(len(bid), dtype=float), start=0.)
        part = 2 if symbol == "TOPIX" else 4
        orders = np.array([[1, 0, 7, 1, qty, 100, 1, 1],
            [3, 2, 7, -1, part, 103, 2, 0],
            [5, 4, 7, -1, qty-part, 99, 3, 0]], dtype=float)
        ledger = expected_ledger(orders, bid, ask, mult, fee)
        co, ct = runner.standardize(dict(orders=orders, fee=fee), ledger, ready, phase)
        name = symbol+"部分返済"
        helper.equal(name+"加重返済値", ct[0, 6], 100.6)
        helper.equal(name+"親総益", ct[0, 7], (3*part-(qty-part))*mult)
        expected_fee = sum(int(int(o[4])*round(fee*10)//10) for o in orders)
        helper.equal(name+"料金", ct[0, 8], expected_fee)
        helper.equal(name+"純額", ct[0, 9], ct[0, 7]-expected_fee)
        helper.check(name+"未測定幅を作らない", np.isnan(ct[0, 10:13]).all())
        helper.equal(name+"判断約定時計", co[:, [9, 10]], orders[:, [0, 1]])
        if symbol == "TOPIX":
            helper.equal("分割料金417円", expected_fee, 417.)
            helper.equal("分割親2583円", ct[0, 9], 2583.)
        for side in (1, -1):
            extra_orders = np.array([[2, 1, 0, side, qty, ask[2] if side == 1 else bid[2], 82, 1],
                [6, 5, 0, -side, qty, bid[6] if side == 1 else ask[6], 93, 0]], dtype=float)
            eledger = expected_ledger(extra_orders, bid, ask, mult, fee)
            eo, et = runner.standardize(dict(orders=extra_orders, fee=fee), eledger, ready, phase)
            before_eo, before_et = eo.copy(), et.copy()
            config = dict(id="人工", name="人工", schedule=0)
            row, arrays = runner.combine((co, ct, ledger, "人工旧核"),
                (eo, et, eledger["curve"]), ready, phase, config)
            comparison = np.vstack([orders, extra_orders.copy()])
            comparison[len(orders):, 2] += 1000000
            comparison = comparison[np.argsort(comparison[:, 0], kind="stable")]
            independent = expected_ledger(comparison, bid, ask, mult, fee)
            label = symbol+"追加方向"+str(side)
            helper.equal(label+"全行清算", arrays["curve"][:, 0], independent["liquidation_equity"])
            helper.equal(label+"全行実現", arrays["curve"][:, 2], independent["realized_cash"])
            helper.equal(label+"全行長短別", arrays["long_quantity"], independent["long_quantity"])
            helper.equal(label+"全行短別", arrays["short_quantity"], independent["short_quantity"])
            helper.equal(label+"合計純額", row["net"], independent["liquidation_equity"][-1])
            helper.equal(label+"区分清算合計", sum(row["phase_equity_changes"].values()), row["net"])
            helper.equal(label+"入口区分合計", sum(x["net"] for x in row["phases"].values()), row["net"])
            helper.equal(label+"売買合計", sum(x["net"] for x in row["direction"].values()), row["net"])
            helper.equal(label+"担当別合計", sum(x["net"] for x in row["components"].values()), row["net"])
            helper.equal(label+"親別利益", row["profit"], sum(max(p["net"], 0) for p in independent["parents"]))
            helper.equal(label+"親別損失", row["loss"], sum(max(-p["net"], 0) for p in independent["parents"]))
            helper.check(label+"別親ID", sorted(arrays["trades"][:, 0].tolist()) == [7., 1000000.])
            helper.equal(label+"元追加注文無変更", eo, before_eo)
            helper.equal(label+"元追加親無変更", et, before_et)
            helper.equal(label+"約定昇順", arrays["orders"][:, 0], np.sort(arrays["orders"][:, 0]))
            helper.equal(label+"最大総数量", row["max_gross_quantity"], qty*2)
            if side == 1:
                helper.equal(label+"同方向上限", row["max_long"], qty*2)
            else:
                helper.equal(label+"長短相殺でも保有保持", arrays["curve"][2, 1], 0.)
                helper.equal(label+"相殺時長保有", arrays["long_quantity"][2], qty)
                helper.equal(label+"相殺時短保有", arrays["short_quantity"][2], qty)
            # ----------------------------------------
            # 相殺後の純数量だけでは上限を判定してはならない。
            invalid = copy.deepcopy(ledger)
            invalid["long_quantity"][2] = 2*qty+1
            try:
                runner.combine((co, ct, invalid, "人工旧核"), (eo, et, eledger["curve"]), ready, phase, config)
            except AssertionError:
                helper.check(label+"長側超過拒否", True)
            else:
                raise AssertionError("長側の上限超過")
            invalid = copy.deepcopy(ledger)
            invalid["short_quantity"][2] = 2*qty+1
            try:
                runner.combine((co, ct, invalid, "人工旧核"), (eo, et, eledger["curve"]), ready, phase, config)
            except AssertionError:
                helper.check(label+"短側超過拒否", True)
            else:
                raise AssertionError("短側の上限超過")


def prefix_audit():
    """
    機能: 全旧注文を円会計へ構成しても、追加判断には当行までの新規だけが渡ることを確かめる。
    引数: なし。
    返り値: None。
    """
    data = helper.tape()
    quantity = data["quantity"]
    late = np.array([[100, 99, 3, 1, quantity, data["ask"][100], 1, 1],
        [200, 199, 3, -1, quantity, data["bid"][200], 2, 0]], dtype=float)
    ledger = runner.baseline131.revalue(data["times"], data["bid"], data["ask"],
        data["qok"], late, data["multiplier"], data["fee_per_contract"])
    starts = np.diff(np.r_[0, ledger["entries_so_far"]]).astype(np.int64)
    helper.equal("旧新規差分は当行", np.flatnonzero(starts), np.array([100]))
    later = participation_helper.simulate(data, starts)
    empty = participation_helper.simulate(data)
    for i in range(3):
        helper.equal("将来の旧参加で遡及取消しない"+str(i), later[i], empty[i])
    helper.check("旧将来有りでも先行追加", later[0][0, 1] == 45)
    earlier = late.copy()
    earlier[0, :2] = [45, 44]
    early_ledger = runner.baseline131.revalue(data["times"], data["bid"], data["ask"],
        data["qok"], earlier, data["multiplier"], data["fee_per_contract"])
    early_starts = np.diff(np.r_[0, early_ledger["entries_so_far"]]).astype(np.int64)
    helper.check("旧同時参加だけ追加抑止", len(participation_helper.simulate(data, early_starts)[0]) == 0)


def connection_audit():
    """
    機能: 実mainを架空登録・架空旧注文・架空特徴へ接続し、引数・再利用・出力を照合する。
    引数: なし。
    返り値: None。実市場ファイルと金融核の実資料再生は使用しない。
    """
    target = HERE/"合算接続人工"
    target.mkdir(exist_ok=True)
    jst = ZoneInfo("Asia/Tokyo")
    scenes = ("2099-01-05_Day", "2099-01-05_Night")
    packets, tables, refs, loads, calls, outputs, saved_arrays = {}, {}, [], [], [], [], []
    configs = [dict(id=f"人工{variant}{schedule}{style}", name="人工",
        core_variant=variant, schedule=schedule, style=style)
        for variant in (0, 1) for schedule in (0, 1, 2) for style in (0, 1)]
    for scene in scenes:
        start = datetime.fromisoformat(scene[:10]+("T08:45" if scene.endswith("_Day") else "T17:00")).replace(
            tzinfo=jst).timestamp()
        opening = datetime.fromisoformat(scene[:10]+"T09:30").replace(
            tzinfo=ZoneInfo("America/New_York")).timestamp()
        packet = dict(inputs={}, quotes={})
        history, phase = {}, {}
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            times = start+np.array([0., 60., 2701., 6000., 13500., 13560., 19000., 21000., 26000., 27000.])
            packet["inputs"][key] = dict(time_s=times, atr=np.full(len(times), 4.), start=start,
                limit=start+28000., tick=.5 if symbol == "TOPIX" else 10.,
                session=scene, symbol=symbol, us_open=opening)
            packet["quotes"][key] = dict(bid=np.full(len(times), 100.),
                ask=np.full(len(times), 101.), quote_valid=np.ones(len(times), bool))
            history[key] = np.full((len(times), 15), 1.)
            phase[key] = np.arange(len(times)) % len(runner.features131.PHASES)
        path = target/(scene+".pkl")
        path.write_bytes(pickle.dumps(packet))
        ref = dict(path=path.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), session=scene)
        refs.append(ref)
        packets[scene] = packet
        tables[scene] = (packet["inputs"], {}, history, phase)
    fixed = dict(sources={}, artificial=[], input_references=[], configs=configs)
    originals = {name: getattr(runner, name) for name in ("HERE", "read", "reference", "save", "sources")}
    oldbuild, oldcore = runner.features131.build, runner.baseline131.load_core
    oldsimulate, oldsavez, oldargv = runner.participation131.simulate, np.savez_compressed, sys.argv.copy()

    def fake_read(location):
        """
        機能: 人工計画・登録・人工入力参照だけを供給する。
        引数: location(Path)は要求先。
        返り値: dictは架空資料。
        """
        name = Path(location).name
        if name == "固定計画.json": return fixed
        if name == "登録.json": return dict(returncode=0)
        if name == "入力準備.json": return dict(packets=refs)
        raise AssertionError(str(location))

    def fake_reference(location):
        """
        機能: 人工packet指紋と未保存出力の印を返す。
        引数: location(Path)は対象。
        返り値: dictは人工参照。
        """
        location = Path(location)
        for ref in refs:
            if location == ROOT/ref["path"]:
                return {k: ref[k] for k in ("path", "sha256")}
        return dict(path=location.relative_to(ROOT).as_posix(), sha256="人工")

    def fake_load(scene, symbol, variant):
        """
        機能: 原判断を再実行せず、人工の将来旧新規を供給する。
        引数: scene/symbol(str)、variant(int)は接続指定。
        返り値: dictは人工旧注文。
        """
        loads.append((scene, symbol, variant))
        qty, mult, fee = (5, 1000., 41.8) if symbol == "TOPIX" else (10, 10., 11.)
        variant_used = variant if scene.endswith("_Night") and symbol == "TOPIX" else 0
        parent = 8+variant_used
        return dict(orders=np.array([[6, 5, parent, 1, qty, 101., 1, 1],
            [8, 7, parent, -1, qty, 100., 2, 0]], dtype=float),
            multiplier=mult, fee=fee, method="旧人工"+str(variant_used),
            source=dict(path="人工源"+scene+symbol+str(variant_used), sha256="人工"),
            measurement=dict(path="人工注文"+scene+symbol+str(variant_used), sha256="人工"))

    def fake_build(packet):
        """
        機能: 人工入力のみに対応する既知特徴を返す。
        引数: packet(dict)は架空入力。
        返り値: tupleは原入力・市場・履歴・区分。
        """
        scene = next(iter(packet["inputs"]))[0]
        return tables[scene]

    def fake_simulate(*args):
        """
        機能: 実mainからの15引数を独立期待と照合し、零追加の人工口座を返す。
        引数: args(tuple)は15個の接続引数。
        返り値: tuple[ndarray,...]は注文・親・時価。
        """
        helper.check("合算接続15引数"+str(len(calls)), len(args) == 15)
        key = next(k for k, value in tables[current_scene[0]][0].items() if np.array_equal(args[0], value["time_s"]) and
            args[10] == value["tick"])
        scene, symbol = key
        previous = [x for x in calls if x[0:2] == key]
        local = len(previous)
        schedule, style = local % 6//2, local % 2
        rd = tables[scene][0][key]
        q = packets[scene]["quotes"][key]
        starts = np.zeros(len(args[0]), np.int64)
        starts[6] = 1
        expected = [rd["time_s"], q["bid"], q["ask"], q["quote_valid"], rd["atr"],
            tables[scene][2][key], tables[scene][3][key], starts,
            runner.activation(rd, schedule), rd["limit"], rd["tick"],
            5 if symbol == "TOPIX" else 10, 1000. if symbol == "TOPIX" else 10.,
            41.8 if symbol == "TOPIX" else 11., style]
        for i, value in enumerate(expected):
            helper.equal("合算引数"+str(len(calls))+"/"+str(i), args[i], value)
        calls.append((scene, symbol, schedule, style))
        return np.zeros((0, 12)), np.zeros((0, 17)), np.zeros((len(args[0]), 5))

    current_scene = [scenes[0]]

    def switching_build(packet):
        """
        機能: 人工場識別を更新して特徴を返す。
        引数: packet(dict)は架空入力。
        返り値: tupleは架空特徴。
        """
        current_scene[0] = next(iter(packet["inputs"]))[0]
        return fake_build(packet)

    try:
        runner.HERE, runner.read, runner.reference = target, fake_read, fake_reference
        runner.save = lambda p, value: outputs.append((str(p), value))
        runner.sources = lambda: {}
        runner.features131.build = switching_build
        runner.baseline131.load_core = fake_load
        runner.participation131.simulate = fake_simulate
        np.savez_compressed = lambda p, **value: saved_arrays.append((str(p), value))
        sys.argv = ["run_portfolio131.py", "--round", "架空実行"]
        runner.main()
        expected_loads = [(scenes[0], "TOPIX", 0), (scenes[0], "NK225", 0),
            (scenes[1], "TOPIX", 0), (scenes[1], "TOPIX", 1), (scenes[1], "NK225", 0)]
        helper.check("旧核二種は夜TOPだけ", loads == expected_loads)
        helper.equal("追加再利用回数", len(calls), 30)
        helper.equal("出力商品場数", len(saved_arrays), 4)
        helper.check("全条件保存列", all(len(value) == 12*10 for _, value in saved_arrays))
        final = outputs[-1][1]
        helper.equal("全会計48件", len(final["rows"]), 48)
        helper.equal("追加実行30件", final["financial_replays"], 30)
        helper.equal("設定再利用18件", final["reused_config_rows"], 18)
        helper.equal("旧核再生零", final["core_replays"], 0)
        for row in final["rows"]:
            helper.equal("出力旧純額"+row["method"]+row["symbol"]+row["session"],
                row["net"], -5418. if row["symbol"] == "TOPIX" else -320.)
            helper.equal("出力追加なし"+row["method"]+row["symbol"]+row["session"], row["deadline_entries"], 0)
    finally:
        for name, value in originals.items(): setattr(runner, name, value)
        runner.features131.build, runner.baseline131.load_core = oldbuild, oldcore
        runner.participation131.simulate, np.savez_compressed, sys.argv = oldsimulate, oldsavez, oldargv


def main():
    """
    機能: 接続の独立人工をまとめ、対象源の指紋付き証拠を保存する。
    引数: なし。
    返り値: None。実金融・実市場読込は零。
    """
    helper.CHECKS.clear()
    clock_audit()
    account_audit()
    prefix_audit()
    connection_audit()
    sources = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [WORK/name for name in ("run_portfolio131.py", "participation131.py",
            "baseline131.py", "features131.py", "common131.py")]}
    proof = dict(passed=True, checks=len(helper.CHECKS), labels=helper.CHECKS, sources=sources,
        audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0, market_data_reads=0,
        scope="架空注文の独立会計、時計、旧新規接頭、実main15引数・再利用・全出力接続。",
        limitation="保存市場資料による全セッション参加と収支は金融後の別監査。人工件数は戦略数ではない。")
    path = HERE/f"旧核一回追加接続の独立人工_{time.time_ns()}.json"
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(path.as_posix(), len(helper.CHECKS), "合格", flush=True)


if __name__ == "__main__":
    main()
