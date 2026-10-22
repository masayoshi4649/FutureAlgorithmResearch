"""観測価格の変更を同じ夜間注文機構で分離検証する。"""

import argparse
import os
import pickle
import sys
import numpy as np
from common129 import HERE, PREV, ROOT, read, save, sha, reference

os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_financial")
sys.path.insert(0, str(PREV))
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
import night_retest129c
from features129 import build

PARAMETERS = ("mode", "stop", "trail_start", "trail_width", "phase", "cooldown",
              "entry_bounce", "opening_buffer", "minimum_efficiency", "band_distance",
              "entry_confirm", "exit_mode", "rearm", "maximum_extension")


def sources():
    """
    機能: 注文生成に関係する旧核と新接続源を固定する。
    引数: なし。
    返り値: dict[str,str]は相対位置と指紋。
    """
    paths = [HERE/n for n in ("common129.py", "features129.py", "run_retest129c.py", "analyze129.py", "night_retest129c.py")]
    paths += [PREV/n for n in ("features128.py", "common128.py", "analyze5.py")]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def summary(orders, trades, curve, ready, config):
    """
    機能: 全返済・整数枚数・次行約定を確認して親単位会計を作る。
    引数: orders/trades/curve(ndarray)、ready/config(dict)は完成会計と条件。
    返り値: dictは一場一商品の手数料後利益・損失・収支。
    """
    qty = orders[:, 4].astype(np.int64)
    assert np.array_equal(qty, orders[:, 4])
    enter = orders[:, 7] == 1.
    assert qty[enter].sum() == qty[~enter].sum()
    assert np.all(orders[:, 0] > orders[:, 1])
    net = trades[:, 8]
    assert curve[-1, 1] == 0.
    assert np.isclose(net.sum(), curve[-1, 0])
    return dict(method=config["id"], name=config["name"], kind="Night", session=ready["session"],
                symbol=ready["symbol"], profit=float(net[net > 0.].sum()),
                loss=float(-net[net < 0.].sum()), net=float(net.sum()), gross=float(trades[:, 6].sum()),
                fees=float(trades[:, 7].sum()), entries=int(enter.sum()), quantity=int(qty[enter].sum()),
                parent_wins=int((net > 0).sum()), parent_losses=int((net < 0).sum()),
                max_quantity=int(qty[enter].max()) if enter.any() else 0)


def main():
    """
    機能: 登録済み条件を同一既知場で再生し、注文と全行会計を保存する。
    引数: --round(str)は固定計画の所在。
    返り値: None。保存済み資料の上書き、現在ＡＰＩ取得、実注文は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", default="round7")
    args = parser.parse_args()
    folder = HERE/args.round
    fixed = read(folder/"固定計画.json")
    assert sources() == fixed["sources"]
    assert read(folder/"登録.json")["returncode"] == 0
    for proof in fixed["artificial"]:
        assert sha(ROOT/proof["path"]) == proof["sha256"]
        assert read(ROOT/proof["path"])["passed"]
    for ref in fixed["input_references"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"]
    save(folder/"金融実行開始.json", dict(sources=fixed["sources"], API=0, real_orders=0))
    manifest = read(PREV/"入力準備.json")
    rows, cache = [], []
    for ref in manifest["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        assert sha(ROOT/ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        arrays = {symbol: {} for symbol in ("TOPIX", "NK225")}
        for config in fixed["configs"]:
            inputs, markets, history, context = build(packet, config["price_source"], config["peer_delay"])
            params = np.array([config[n] for n in PARAMETERS], dtype=float)
            for symbol in ("TOPIX", "NK225"):
                key = scene, symbol
                ready, q = inputs[key], packet["quotes"][key]
                top = symbol == "TOPIX"
                orders, trades, curve = night_retest129c.simulate(ready["time_s"], ready["last"],
                    q["bid"], q["ask"], q["quote_valid"], ready["atr"], history[key], markets[key],
                    ready["start"], ready["limit"], ready["us_open"], ready["tick"],
                    5 if top else 10, 1000. if top else 10., 418 if top else 110, params, config["retest_mode"])
                rows.append(summary(orders, trades, curve, ready, config))
                for name, value in (("orders", orders), ("trades", trades), ("curve", curve)):
                    arrays[symbol][config["id"]+"__"+name] = value
            del inputs, markets, history, context
        for symbol, values in arrays.items():
            target = folder/"measurement"/(symbol+"_"+scene+".npz")
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            np.savez_compressed(target, **values)
            cache.append(dict(session=scene, symbol=symbol, **reference(target)))
        print(scene, "完了", len(rows), flush=True)
    save(folder/"全条件の会計.json", dict(passed=True, rows=rows, cache=cache, configs=fixed["configs"],
        sources=fixed["sources"], financial_replays=len(rows), input_manifest=reference(PREV/"入力準備.json")))


if __name__ == "__main__":
    main()
