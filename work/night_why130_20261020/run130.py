"""三段階分析から固定した夜間の改修を、原行順で実行する。"""

import argparse
import os
import pickle
import sys
import numpy as np
from common130 import HERE, ROOT, PREV, BASE, read, save, reference, sha

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit_financial")
sys.path.insert(0, str(PREV))
sys.path.insert(0, str(BASE))
import numba
import features129
import night_exit130

numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
PARAMETERS = ("mode", "stop", "trail_start", "trail_width", "phase", "cooldown",
              "entry_bounce", "opening_buffer", "minimum_efficiency", "band_distance",
              "entry_confirm", "exit_mode", "rearm", "maximum_extension")


def sources():
    """
    機能: 数値に影響する実装源を指紋で固定する。
    引数: なし。
    返り値: dict[str,str]は相対位置と内容指紋。
    """
    paths = [HERE / n for n in ("common130.py", "run130.py", "night_exit130.py", "analyze130.py")]
    paths += [PREV / n for n in ("features129.py", "common129.py")]
    paths += [BASE / n for n in ("features128.py", "common128.py")]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def summarize(orders, trades, curve, ready, config):
    """
    機能: 部分返済を同一親へ合算し、費用後の全場会計を作る。
    引数: orders/trades/curve(ndarray)、ready/config(dict)は保存注文と条件。
    返り値: dictは新規親単位の利益・損失・収支。
    """
    assert np.all(orders[:, 0] > orders[:, 1])
    assert np.array_equal(orders[:, 4], orders[:, 4].astype(np.int64))
    opened = orders[:, 7] == 1
    parent_ids = orders[opened, 2].astype(np.int64)
    assert len(set(parent_ids)) == len(parent_ids)
    net = []
    for parent in parent_ids:
        rows = orders[:, 2] == parent
        enters = rows & opened
        exits = rows & ~opened
        assert orders[enters, 4].sum() == orders[exits, 4].sum()
        net.append(float(trades[trades[:, 14] == parent, 8].sum()))
    net = np.array(net)
    assert curve[-1, 1] == 0
    assert np.isclose(net.sum(), curve[-1, 0])
    assert np.isclose(trades[:, 7].sum(), curve[-1, 2])
    return dict(method=config["id"], name=config["name"], kind="Night", session=ready["session"],
                symbol=ready["symbol"], profit=float(net[net > 0].sum()), loss=float(-net[net < 0].sum()),
                net=float(net.sum()), gross=float(trades[:, 6].sum()), fees=float(trades[:, 7].sum()),
                entries=int(opened.sum()), quantity=int(orders[opened, 4].sum()),
                parent_wins=int((net > 0).sum()), parent_losses=int((net < 0).sum()),
                max_quantity=int(np.abs(curve[:, 1]).max()), partial_exits=int((orders[:, 6] == 76).sum()),
                accounting="部分返済と残玉の全費用を合算した完結親")


def main():
    """
    機能: 人工検査と登録が通った条件だけを全21夜間で再生する。
    引数: --round(str)は固定条件・証跡を置いたフォルダ。
    返り値: None。旧結果上書き・現在API接続・実注文は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = HERE / args.round
    fixed = read(folder / "固定計画.json")
    assert fixed["sources"] == sources()
    assert read(folder / "登録.json")["returncode"] == 0
    for ref in fixed["artificial"] + fixed["input_references"]:
        assert sha(ROOT / ref["path"]) == ref["sha256"], ref
    for ref in fixed["artificial"]:
        assert read(ROOT / ref["path"])["passed"]
    save(folder / "金融実行開始.json", dict(sources=fixed["sources"], API=0, real_orders=0))
    rows, cache = [], []
    for ref in read(BASE / "入力準備.json")["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        assert sha(ROOT / ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        arrays = {s: {} for s in ("TOPIX", "NK225")}
        for price_source in sorted({c["price_source"] for c in fixed["configs"]}):
            inputs, markets, history, _ = features129.build(packet, price_source, 0.)
            for config in fixed["configs"]:
                if config["price_source"] != price_source:
                    continue
                parameters = np.array([config[n] for n in PARAMETERS], dtype=float)
                for symbol in ("TOPIX", "NK225"):
                    ready = inputs[scene, symbol]
                    quotes = packet["quotes"][scene, symbol]
                    top = symbol == "TOPIX"
                    orders, trades, curve = night_exit130.simulate(
                        ready["time_s"], ready["last"], quotes["bid"], quotes["ask"], quotes["quote_valid"],
                        ready["atr"], history[scene, symbol], markets[scene, symbol],
                        ready["start"], ready["limit"], ready["us_open"], ready["tick"],
                        5 if top else 10, 1000. if top else 10., 418 if top else 110,
                        parameters, config["retest_mode"], config["exit_style"])
                    rows.append(summarize(orders, trades, curve, ready, config))
                    for name, value in (("orders", orders), ("trades", trades), ("curve", curve)):
                        arrays[symbol][config["id"] + "__" + name] = value
            del inputs, markets, history
        for symbol, values in arrays.items():
            target = folder / "measurement" / (symbol + "_" + scene + ".npz")
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            np.savez_compressed(target, **values)
            cache.append(dict(session=scene, symbol=symbol, **reference(target)))
        print(scene, len(rows), "商品場完了", flush=True)
    save(folder / "全条件の会計.json", dict(passed=True, rows=rows, cache=cache, configs=fixed["configs"],
         financial_replays=len(rows), sources=fixed["sources"], input_manifest=reference(BASE / "入力準備.json")))


if __name__ == "__main__":
    main()
