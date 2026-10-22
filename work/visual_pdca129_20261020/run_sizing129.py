"""既知の夜間判断列を維持し、減量と利益床内の追加を分離する。"""

import argparse
import os
import pickle
import sys
import numpy as np
from common129 import HERE, PREV, ROOT, read, save, sha, reference

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit_sizing")
sys.path.insert(0, str(PREV))
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
import sizing129

BASES = {"N36": PREV / "round5/全条件の会計.json",
         "NV02": HERE / "round1/全条件の会計.json"}


def sources():
    """
    機能: 数量核と保存判断を読む接続源の指紋を作る。
    引数: なし。
    返り値: dict[str,str]は固定する相対パスとSHA256。
    """
    paths = [HERE / p for p in ("common129.py", "sizing129.py", "run_sizing129.py", "analyze129.py")]
    paths += [PREV / p for p in ("common128.py", "analyze5.py")]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def summary(orders, parents, curve, ready, config):
    """
    機能: 全返済と数量上限を確認して、完結親の費用後会計を集計する。
    引数: orders/parents/curve(ndarray)、ready/config(dict)は保存用結果と条件。
    返り値: dictは一商品一場の実際に動かした数量と利益・損失・収支。
    """
    top = ready["symbol"] == "TOPIX"
    limit = 5 if top else 10
    assert np.all(orders[:, 0] > orders[:, 1])
    assert np.all(orders[:, 4] == orders[:, 4].astype(np.int64))
    enter = orders[:, 7] == 1
    assert orders[enter, 4].sum() == orders[~enter, 4].sum()
    assert np.all(parents[:, 14] == 0)
    assert curve[-1, 1] == 0
    assert np.max(np.abs(curve[:, 1])) <= limit
    net = parents[:, 10]
    assert np.isclose(net.sum(), curve[-1, 0])
    return dict(method=config["id"], name=config["name"], kind="Night", session=ready["session"],
        symbol=ready["symbol"], profit=float(net[net > 0].sum()), loss=float(-net[net < 0].sum()),
        net=float(net.sum()), gross=float(parents[:, 8].sum()), fees=float(parents[:, 9].sum()),
        entries=len(parents), entry_orders=int(enter.sum()), quantity=int(orders[enter, 4].sum()),
        parent_wins=int((net > 0).sum()), parent_losses=int((net < 0).sum()),
        max_quantity=int(np.max(np.abs(curve[:, 1]))), additions=int(parents[:, 12].sum()))


def main():
    """
    機能: 登録済みの減量対照・段階追加を同じ原行と固定判断列で運転する。
    引数: --round(str)は固定計画のディレクトリ。
    返り値: None。旧判断の再生成や実注文はせず、実数量の会計だけを新規保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", default="round5")
    args = parser.parse_args()
    folder = HERE / args.round
    fixed = read(folder / "固定計画.json")
    assert sources() == fixed["sources"]
    assert read(folder / "登録.json")["returncode"] == 0
    for proof in fixed["artificial"]:
        assert sha(ROOT / proof["path"]) == proof["sha256"]
        assert read(ROOT / proof["path"])["passed"]
    for ref in fixed["input_references"]:
        assert sha(ROOT / ref["path"]) == ref["sha256"]
    base = {method: read(path) for method, path in BASES.items()}
    base_refs = {method: {(r["session"], r["symbol"]): r for r in result["cache"]}
                 for method, result in base.items()}
    save(folder / "金融実行開始.json", dict(sources=fixed["sources"], API=0, real_orders=0))
    rows, cache = [], []
    for ref in read(PREV / "入力準備.json")["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        assert sha(ROOT / ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            ready, q = packet["inputs"][scene, symbol], packet["quotes"][scene, symbol]
            top = symbol == "TOPIX"
            arrays, signals = {}, {}
            for method in BASES:
                saved = base_refs[method][scene, symbol]
                assert sha(ROOT / saved["path"]) == saved["sha256"]
                with np.load(ROOT / saved["path"], allow_pickle=False) as data:
                    signals[method] = data[method + "__orders"].copy(), data[method + "__trades"].copy()
            for config in fixed["configs"]:
                base_orders, base_trades = signals[config["base_method"]]
                orders, parents, curve, events = sizing129.simulate(
                    ready["time_s"], q["bid"], q["ask"], q["quote_valid"],
                    base_orders, base_trades, ready["tick"],
                    2 if top else 4, 5 if top else 10, 1 if top else 2,
                    1000. if top else 10., 418 if top else 110, config["addition_mode"])
                rows.append(summary(orders, parents, curve, ready, config))
                for name, value in (("orders", orders), ("parents", parents), ("curve", curve), ("events", events)):
                    arrays[config["id"] + "__" + name] = value
            target = folder / "measurement" / (symbol + "_" + scene + ".npz")
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            np.savez_compressed(target, **arrays)
            cache.append(dict(session=scene, symbol=symbol, **reference(target)))
        print(scene, "完了", len(rows), flush=True)
    save(folder / "全条件の会計.json", dict(passed=True, rows=rows, cache=cache,
         configs=fixed["configs"], sources=fixed["sources"], financial_replays=len(rows),
         input_manifest=reference(PREV / "入力準備.json"), base_references=[reference(p) for p in BASES.values()]))


if __name__ == "__main__":
    main()
