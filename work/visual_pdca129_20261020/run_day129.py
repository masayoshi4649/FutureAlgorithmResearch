"""日中の小撤退と同じ元判断中の再参加を分離する。"""

import argparse
import os
import pickle
import sys
import numpy as np
from common129 import HERE, PREV, ROOT, read, save, sha, reference

os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_day")
sys.path.insert(0, str(PREV))
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
from adapter5 import day_filter, summarize
import day129


def sources():
    """
    機能: 日中の新核、元入口の選別、円会計と比較順位を固定する。
    引数: なし。
    返り値: dict[str,str]は数値源の相対位置と指紋。
    """
    paths = [HERE/n for n in ("common129.py", "day129.py", "run_day129.py", "analyze129.py")]
    paths += [PREV/n for n in ("adapter5.py", "bbo_order_kernel126.py", "common128.py", "analyze5.py",
                              "day_core2.py", "night5.py")]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def main():
    """
    機能: 登録済みの日中撤退・再参加を各22場の原行で運転する。
    引数: --round(str)は固定仕様の巡名。
    返り値: None。両建て・追加・場またぎ・実注文は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", default="day_round1")
    args = parser.parse_args()
    folder = HERE/args.round
    fixed = read(folder/"固定計画.json")
    assert sources() == fixed["sources"]
    assert read(folder/"登録.json")["returncode"] == 0
    for ref in fixed["artificial"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"]
        proof = read(ROOT/ref["path"])
        assert proof.get("passed", proof.get("全合格", False))
    for ref in fixed["input_references"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"]
    save(folder/"金融実行開始.json", dict(sources=fixed["sources"], API=0, real_orders=0))
    rows, cache = [], []
    for ref in read(PREV/"入力準備.json")["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Day"):
            continue
        assert sha(ROOT/ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        h = ref["features"]
        assert sha(ROOT/h["path"]) == h["sha256"]
        with np.load(ROOT/h["path"], allow_pickle=False) as data:
            for symbol in ("TOPIX", "NK225"):
                key = scene, symbol
                ready, q, market = packet["inputs"][key], packet["quotes"][key], packet["markets"][key]
                history, feed = data[symbol+"__history"], data[symbol+"__feed"]
                arrays = {}
                for config in fixed["configs"]:
                    accepted = day_filter(feed, ready, market, history, 5)
                    values = day129.simulate(ready["time_s"], ready["last"], q["bid"], q["ask"],
                        q["quote_valid"], accepted, ready["limit"], 10 if symbol == "TOPIX" else 20,
                        market, np.array([0., .5, 0., 0., .75, .5]), ready["atr"], history, 1,
                        config["withdrawal_width"], config["allow_reentry"])
                    names = ("orders", "trades", "curve", "stats", "cycles", "order_uids",
                             "execution_events", "execution_states", "actual_parents", "parent_mapping")
                    result = dict(zip(names, values))
                    assert len(values) == len(names)
                    rows.append(summarize(result, ready, config))
                    for name in ("orders", "trades", "curve", "stats", "cycles", "execution_events", "parent_mapping"):
                        arrays[config["id"]+"__"+name] = result[name]
                target = folder/"measurement"/(symbol+"_"+scene+".npz")
                target.parent.mkdir(parents=True, exist_ok=True)
                assert not target.exists()
                np.savez_compressed(target, **arrays)
                cache.append(dict(session=scene, symbol=symbol, **reference(target)))
        print(scene, "完了", len(rows), flush=True)
    save(folder/"全条件の会計.json", dict(passed=True, rows=rows, cache=cache, configs=fixed["configs"],
        sources=fixed["sources"], financial_replays=len(rows), input_manifest=reference(PREV/"入力準備.json")))


if __name__ == "__main__":
    main()
