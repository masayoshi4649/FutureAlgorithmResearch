"""登録済みの状態切替条件を全43場で同じ原行順に比較する。"""

import argparse
import os
import pickle
import numpy as np
from common131 import HERE, ROOT, BASE, PREV, read, reference, save

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
import features131
import engine131

PARAMETERS = ("selector", "width_mode", "stop", "trail_start", "trail_width",
              "per_phase", "participation_seconds", "conversion", "withdrawal")


def sources():
    """
    機能: 金融値と因果特徴に影響する実装を固定する。
    引数: なし。
    返り値: dict[str,str]は源の位置と指紋。
    """
    paths = [HERE / n for n in ("common131.py", "features131.py", "engine131.py", "run131.py")]
    paths += [PREV / n for n in ("features129.py", "common129.py")]
    paths += [BASE / n for n in ("features128.py", "common128.py")]
    return {reference(p)["path"]: reference(p)["sha256"] for p in paths}


def summarize(orders, trades, curve, ready, config):
    """
    機能: 全注文を親取引へまとめ、セッション会計と区分別損益を計算する。
    引数: orders/trades/curve(ndarray)、ready/config(dict)は結果と固定条件。
    返り値: dictは費用後の利益・損失・収支、参加数と方向内訳。
    """
    assert np.all(orders[:, 0] > orders[:, 1])
    assert np.all(orders[:, 4] == orders[:, 4].astype(np.int64))
    assert np.isclose(trades[:, 9].sum(), curve[-1, 0])
    assert curve[-1, 1] == 0
    net = trades[:, 9]
    groups = {}
    for p, name in enumerate(features131.PHASES):
        selected = trades[:, 13] == p
        groups[name] = dict(entries=int(selected.sum()), net=float(net[selected].sum()))
    direction = {}
    for side, name in ((1, "買い"), (-1, "売り")):
        selected = trades[:, 3] == side
        direction[name] = dict(entries=int(selected.sum()), net=float(net[selected].sum()))
    clock = features131.phases(ready)
    change = np.diff(np.r_[0., curve[:, 0]])
    clock_pnl = {name: float(change[clock == p].sum())
                 for p, name in enumerate(features131.PHASES)}
    assert np.isclose(sum(clock_pnl.values()), net.sum())
    return dict(method=config["id"], name=config["name"], session=ready["session"],
                kind=ready["session"].split("_")[1], symbol=ready["symbol"],
                profit=float(net[net > 0].sum()), loss=float(-net[net < 0].sum()),
                net=float(net.sum()), gross=float(trades[:, 7].sum()), fees=float(trades[:, 8].sum()),
                entries=len(trades), quantity=int(orders[orders[:, 7] == 1, 4].sum()),
                parent_wins=int((net > 0).sum()), parent_losses=int((net < 0).sum()),
                max_quantity=int(np.abs(curve[:, 1]).max()), max_drawdown=float(curve[-1, 3]),
                deadline_entries=int((trades[:, 15] == 82).sum()),
                phases=groups, phase_equity_changes=clock_pnl, direction=direction)


def main():
    """
    機能: 指紋・登録・人工監査を確認して新条件だけを再生する。
    引数: --round(str)は固定計画フォルダ。
    返り値: None。現在API・実注文は行わず、結果は新規保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = HERE / args.round
    fixed = read(folder / "固定計画.json")
    assert fixed["sources"] == sources()
    assert read(folder / "登録.json")["returncode"] == 0
    for ref in fixed["artificial"] + fixed["input_references"]:
        assert reference(ROOT / ref["path"]) == ref
    for ref in fixed["artificial"]:
        assert read(ROOT / ref["path"])["passed"]
    save(folder / "金融実行開始.json", dict(sources=fixed["sources"], real_orders=0, market_API=0))
    rows, cache = [], []
    for ref in read(BASE / "入力準備.json")["packets"]:
        packet_path = ROOT / ref["path"]
        assert reference(packet_path)["sha256"] == ref["sha256"]
        packet = pickle.loads(packet_path.read_bytes())
        inputs, markets, history, phases = features131.build(packet)
        scene = ref["session"]
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            ready, quotes = inputs[key], packet["quotes"][key]
            arrays = {}
            for c in fixed["configs"]:
                top = symbol == "TOPIX"
                parameters = np.array([c[k] for k in PARAMETERS], dtype=float)
                orders, trades, curve = engine131.simulate(
                    ready["time_s"], quotes["bid"], quotes["ask"], quotes["quote_valid"],
                    ready["atr"], history[key], markets[key], phases[key], ready["start"],
                    ready["limit"], ready["tick"], 5 if top else 10,
                    1000. if top else 10., 41.8 if top else 11., parameters)
                rows.append(summarize(orders, trades, curve, ready, c))
                for name, array in (("orders", orders), ("trades", trades), ("curve", curve)):
                    arrays[c["id"]+"__"+name] = array
            target = folder / "measurement" / (symbol+"_"+scene+".npz")
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            np.savez_compressed(target, **arrays)
            cache.append(dict(session=scene, symbol=symbol, **reference(target)))
        print(scene, len(rows), "商品場完了", flush=True)
    save(folder / "全条件の会計.json", dict(passed=True, rows=rows, cache=cache,
         configs=fixed["configs"], sources=fixed["sources"], financial_replays=len(rows)))


if __name__ == "__main__":
    main()
