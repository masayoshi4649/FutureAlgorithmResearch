"""旧核の独立口座を残し、予定時刻まで未参加の場合だけ一親を補う。"""

import argparse
from datetime import datetime, time
import os
import pickle
import numpy as np
from common131 import HERE, ROOT, BASE, PREV, read, reference, save

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
import features131
import participation_risk131
import baseline131


def sources():
    """
    機能: 第二区分の金融判断・旧注文接続・因果特徴の実装指紋を固定する。
    引数: なし。
    返り値: dict[str,str]は源の位置と指紋。
    """
    paths = [HERE / n for n in ("common131.py", "features131.py",
             "participation_risk131.py", "baseline131.py", "run_risk131.py")]
    paths += [PREV / n for n in ("features129.py", "common129.py")]
    paths += [BASE / n for n in ("features128.py", "common128.py")]
    return {reference(p)["path"]: reference(p)["sha256"] for p in paths}


def activation(ready, schedule):
    """
    機能: 保存場の日付と既知の市場時計から一回追加の開始時刻を決める。
    引数: ready(dict)は原入力、schedule(int)は0早期・1中盤・2後半。
    返り値: floatは開始時刻。祝日12時30分は現物再開を意味しない。
    """
    assert schedule in (0, 1, 2)
    if schedule == 0:
        return float(ready["start"])+2700.
    date = datetime.fromisoformat(ready["session"].split("_")[0]).date()
    if ready["session"].endswith("_Day"):
        clock = time(12, 30) if schedule == 1 else time(14)
        return datetime.combine(date, clock, features131.JST).timestamp()
    if schedule == 1:
        return float(ready["us_open"])+1800.
    return datetime.combine(date, time(16, 30), features131.LONDON).timestamp()


def standardize(core, ledger, ready, phase):
    """
    機能: 旧注文を共通列に移し、部分返済を親会計へ集約する。
    引数: core/ledger/ready(dict)、phase(ndarray)は保存注文・円会計・原入力・区分。
    返り値: tuple[ndarray,ndarray]は12列注文・17列親。親の返済値は枚数加重平均。
            未測定の旧親R・MFE・MAEはNaNとし、架空の値を作らない。
    """
    old = core["orders"]
    orders = np.zeros((len(old), 12))
    orders[:, :8] = old
    if len(old):
        rows, source = old[:, 0].astype(int), old[:, 1].astype(int)
        orders[:, 8] = old[:, 4].astype(int)*int(round(core["fee"]*10))//10
        orders[:, 9] = ready["time_s"][rows]
        orders[:, 10] = ready["time_s"][source]
        orders[:, 11] = phase[rows]
    trades = np.zeros((len(ledger["parents"]), 17))
    for j, p in enumerate(ledger["parents"]):
        closes = old[(old[:, 2] == p["parent_id"]) & (old[:, 7] == 0)]
        opened = old[(old[:, 2] == p["parent_id"]) & (old[:, 7] == 1)]
        exit_price = float(np.sum(closes[:, 4]*closes[:, 5])/p["quantity"])
        trades[j] = [p["parent_id"], p["entry_row"], p["exit_row"], p["side"],
            p["quantity"], p["entry_price"], exit_price, p["gross"], p["fees"], p["net"],
            np.nan, np.nan, np.nan, phase[p["entry_row"]], -1, opened[0, 6], p["exit_reason"]]
    return orders, trades


def combine(core, extra, ready, phase, config):
    """
    機能: 旧核と一回追加の独立会計を合算し、方向別同時保有上限を検査する。
    引数: core(tuple)は注文・親・円会計、extra(tuple)は注文・親・曲線、
          ready/config(dict)、phase(ndarray)は原入力・条件・時計区分。
    返り値: tuple[dict,dict[str,ndarray]]は全場会計と保存配列。
    """
    co, ct, ledger, method = core
    eo, et, ec = extra
    eo, et = eo.copy(), et.copy()
    eo[:, 2] += 1000000
    et[:, 0] += 1000000
    orders = np.concatenate([co, eo])
    orders = orders[np.argsort(orders[:, 0], kind="stable")]
    trades = np.concatenate([ct, et])
    longs = ledger["long_quantity"]+np.maximum(ec[:, 1], 0)
    shorts = ledger["short_quantity"]+np.maximum(-ec[:, 1], 0)
    cap = 10 if ready["symbol"] == "TOPIX" else 20
    assert max(longs.max(), shorts.max()) <= cap
    assert longs[-1] == shorts[-1] == 0
    equity = ledger["liquidation_equity"]+ec[:, 0]
    realized = ledger["realized_cash"]+ec[:, 2]
    peak = np.maximum.accumulate(np.maximum(equity, 0.))
    dd = np.maximum.accumulate(peak-equity)
    curve = np.column_stack([equity, longs-shorts, realized, dd, np.zeros(len(equity))])
    nets = trades[:, 9]
    assert np.isclose(nets.sum(), equity[-1])
    assert np.isclose(trades[:, 8].sum(), orders[:, 8].sum())
    assert np.all(orders[:, 0] > orders[:, 1])
    groups = {name: dict(entries=int((trades[:, 13] == p).sum()),
              net=float(nets[trades[:, 13] == p].sum()))
              for p, name in enumerate(features131.PHASES)}
    directions = {name: dict(entries=int((trades[:, 3] == side).sum()),
                   net=float(nets[trades[:, 3] == side].sum()))
                   for side, name in ((1, "買い"), (-1, "売り"))}
    delta = np.diff(np.r_[0., equity])
    clock_pnl = {name: float(delta[phase == p].sum())
                 for p, name in enumerate(features131.PHASES)}
    assert np.isclose(sum(clock_pnl.values()), nets.sum())
    parts = {}
    for name, ts in (("旧核", ct), ("追加", et)):
        ns = ts[:, 9]
        parts[name] = dict(entries=len(ts), profit=float(ns[ns > 0].sum()),
            loss=float(-ns[ns < 0].sum()), net=float(ns.sum()),
            gross=float(ts[:, 7].sum()), fees=float(ts[:, 8].sum()))
    row = dict(method=config["id"], name=config["name"], session=ready["session"],
        kind=ready["session"].split("_")[1], symbol=ready["symbol"], core_method=method,
        profit=float(nets[nets > 0].sum()), loss=float(-nets[nets < 0].sum()),
        net=float(nets.sum()), gross=float(trades[:, 7].sum()), fees=float(trades[:, 8].sum()),
        entries=len(trades), quantity=int(orders[orders[:, 7] == 1, 4].sum()),
        parent_wins=int((nets > 0).sum()), parent_losses=int((nets < 0).sum()),
        max_quantity=int(max(longs.max(), shorts.max())), max_long=int(longs.max()),
        max_short=int(shorts.max()), max_gross_quantity=int((longs+shorts).max()),
        max_drawdown=float(dd[-1]), deadline_entries=len(et), phases=groups,
        phase_equity_changes=clock_pnl, direction=directions, components=parts,
        activation_time=activation(ready, config["schedule"]))
    arrays = dict(orders=orders, trades=trades, curve=curve,
        long_quantity=longs, short_quantity=shorts, core_orders=co, core_trades=ct,
        extra_orders=eo, extra_trades=et, extra_curve=ec)
    return row, arrays


def main():
    """
    機能: 事前登録と人工監査を確認し、全43場の追加担当と合算を保存する。
    引数: --round(str)は未実行の固定計画フォルダ。
    返り値: None。旧核判断は再実行せず、完全同じ追加条件も場内で再利用する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = HERE / args.round
    fixed = read(folder / "固定計画.json")
    assert fixed["sources"] == sources()
    assert read(folder / "登録.json")["returncode"] == 0
    for ref in fixed["artificial"]+fixed["input_references"]:
        assert reference(ROOT/ref["path"]) == ref
    for ref in fixed["artificial"]:
        assert read(ROOT/ref["path"])["passed"]
    save(folder / "金融実行開始.json", dict(sources=fixed["sources"], real_orders=0, market_API=0))
    results, cache, source_refs, executions = [], [], {}, 0
    for ref in read(BASE/"入力準備.json")["packets"]:
        path = ROOT/ref["path"]
        assert reference(path)["sha256"] == ref["sha256"]
        packet = pickle.loads(path.read_bytes())
        inputs, _, history, phases = features131.build(packet)
        scene = ref["session"]
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            ready, q = inputs[key], packet["quotes"][key]
            arrays, cores, extras = {}, {}, {}
            for config in fixed["configs"]:
                variant = config["core_variant"]
                core_key = variant if symbol == "TOPIX" and scene.endswith("_Night") else 0
                if core_key not in cores:
                    saved = baseline131.load_core(scene, symbol, variant)
                    ledger = baseline131.revalue(ready["time_s"], q["bid"], q["ask"],
                        q["quote_valid"], saved["orders"], saved["multiplier"], saved["fee"])
                    co, ct = standardize(saved, ledger, ready, phases[key])
                    cores[core_key] = (co, ct, ledger, saved["method"])
                    for source in ("source", "measurement"):
                        item = saved[source]
                        source_refs[item["path"]] = item["sha256"]
                core = cores[core_key]
                extra_key = (core_key, config["schedule"], config["style"], config["trail_start"], config["trail_width"], config["budget_ticks"])
                if extra_key not in extras:
                    ledger = core[2]
                    starts = np.diff(np.r_[0, ledger["entries_so_far"]]).astype(np.int64)
                    top = symbol == "TOPIX"
                    extras[extra_key] = participation_risk131.simulate(
                        ready["time_s"], q["bid"], q["ask"], q["quote_valid"], ready["atr"],
                        history[key], phases[key], starts, activation(ready, config["schedule"]),
                        ready["limit"], ready["tick"], 5 if top else 10,
                        1000. if top else 10., 41.8 if top else 11., config["style"], config["trail_start"], config["trail_width"], config["budget_ticks"])
                    executions += 1
                row, saved_arrays = combine(core, extras[extra_key], ready, phases[key], config)
                results.append(row)
                for name, array in saved_arrays.items():
                    arrays[config["id"]+"__"+name] = array
            target = folder/"measurement"/(symbol+"_"+scene+".npz")
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            np.savez_compressed(target, **arrays)
            cache.append(dict(session=scene, symbol=symbol, **reference(target)))
        print(scene, len(results), "商品場完了", flush=True)
    save(folder/"全条件の会計.json", dict(passed=True, rows=results, cache=cache,
        configs=fixed["configs"], sources=fixed["sources"], saved_core_sources=source_refs,
        financial_replays=executions, reused_config_rows=len(results)-executions,
        core_replays=0, note="追加分だけを新再生。合算上限は片方向TOPIXミニ10枚・日経マイクロ20枚。"))


if __name__ == "__main__":
    main()
