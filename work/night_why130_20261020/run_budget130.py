"""活動待ちの判断価格予算を追加した固定条件だけを再生する。"""

import argparse
import os
import pickle
import sys
import numpy as np

from common130 import HERE, ROOT, PREV, BASE, read, save, reference, sha
import run130
import night_budget130

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit_budget_financial")
import numba

numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
PARAMETERS = run130.PARAMETERS
ACTIVITY_MANIFEST = HERE / "原板活動の非金融準備.json"
summarize = run130.summarize


def sources():
    """
    機能: 旧会計・特徴生成と新活動核を含む依存源の指紋を固定する。
    引数: なし。
    返り値: dict[str,str]は相対位置と内容指紋。
    """
    result = run130.sources()
    for name in ("run_budget130.py", "night_budget130.py", "activity130.py"):
        path = HERE / name
        result[path.relative_to(ROOT).as_posix()] = sha(path)
    return result


def load_activity(packet, packet_ref, entries):
    """
    機能: 活動特徴の指紋と自己原行・時計を入力packetへ厳密照合する。
    引数: packet/packet_ref(dict)、entries(dict[tuple,dict])は固定入力と活動一覧。
    返り値: dict[str,ndarray]はTOPIX及びNK225の4列活動。金融核は呼ばない。
    """
    scene = packet_ref["session"]
    result = {}
    for symbol in ("TOPIX", "NK225"):
        entry = entries[scene, symbol]
        assert entry["packet"] == packet_ref
        output = entry["output"]
        path = ROOT / output["path"]
        assert sha(path) == output["sha256"], output
        ready = packet["inputs"][scene, symbol]
        quotes = packet["quotes"][scene, symbol]
        with np.load(path, allow_pickle=False) as saved:
            for key in ("seq", "time_s"):
                assert np.array_equal(saved[key], ready[key]), (scene, symbol, key)
                if key in quotes:
                    assert np.array_equal(saved[key], quotes[key]), (scene, symbol, "気配", key)
            values = saved["activity"].copy()
        assert values.shape == (len(ready["time_s"]), 4)
        assert entry["rows"] == len(values)
        known = values[:, 3] == 1.
        assert np.all((values[:, 3] == 0.) | known)
        assert np.isfinite(values[known, :3]).all()
        assert np.all(values[known, 1] >= 0.)
        assert np.all(np.abs(values[known, 2]) <= values[known, 1])
        assert entry["known"] == int(known.sum())
        result[symbol] = values
    return result


def validate_manifest(fixed, packet_refs, expected_products=42):
    """
    機能: 金融開始前に全活動の出典・42商品場・原行時計を検査する。
    引数: fixed(dict)、packet_refs(list[dict])、expected_products(int)は固定計画と期待件数。
    返り値: tuple[dict,dict]は活動のキー索引と非金融照合結果。
    """
    manifest_ref = reference(ACTIVITY_MANIFEST)
    assert manifest_ref in fixed["input_references"], "活動準備JSONの指紋が固定計画にありません"
    manifest = read(ACTIVITY_MANIFEST)
    assert manifest["passed"] and manifest["financial_replays"] == 0
    assert manifest["source"] == reference(HERE / "activity130.py")
    entries = {(r["session"], r["symbol"]): r for r in manifest["inputs"]}
    expected = {(r["session"], s) for r in packet_refs for s in ("TOPIX", "NK225")}
    assert len(entries) == len(manifest["inputs"]) == expected_products
    assert set(entries) == expected
    rows = 0
    for ref in packet_refs:
        assert sha(ROOT / ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        values = load_activity(packet, ref, entries)
        rows += sum(len(value) for value in values.values())
    proof = dict(passed=True, products=len(entries), rows=rows,
                 activity_manifest=manifest_ref, financial_replays=0, API=0)
    return entries, proof


def main():
    """
    機能: 人工監査・登録・全原行対応が通った条件だけを夜間で再生する。
    引数: --round(str)は固定条件と登録証跡の保存フォルダ。
    返り値: None。旧源・旧会計の変更、現在API取得、実注文は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    folder = (HERE / args.round).resolve()
    assert folder.is_relative_to(HERE)
    fixed = read(folder / "固定計画.json")
    assert fixed["sources"] == sources()
    assert read(folder / "登録.json")["returncode"] == 0
    for ref in fixed["artificial"] + fixed["input_references"]:
        assert sha(ROOT / ref["path"]) == ref["sha256"], ref
    for ref in fixed["artificial"]:
        assert read(ROOT / ref["path"])["passed"]
    configs = fixed["configs"]
    assert len({c["id"] for c in configs}) == len(configs)
    for config in configs:
        assert config["kind"] == "Night"
        assert config["activity_mode"] in (0, 1)
        assert config["budget_mode"] in (0, 1)
        assert config["budget_mode"] == 0 or config["activity_mode"] == 1
        assert config["price_source"] in ("last", "mid")
        assert config["peer_delay"] == 0.
    packet_refs = [r for r in read(BASE / "入力準備.json")["packets"] if r["session"].endswith("_Night")]
    activities, proof = validate_manifest(fixed, packet_refs)
    save(folder / "活動原行の接続確認.json", proof)
    save(folder / "金融実行開始.json", dict(sources=fixed["sources"], API=0, real_orders=0))
    rows, cache = [], []
    for ref in packet_refs:
        scene = ref["session"]
        assert sha(ROOT / ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        activity = load_activity(packet, ref, activities)
        arrays = {s: {} for s in ("TOPIX", "NK225")}
        for price_source in sorted({c["price_source"] for c in configs}):
            inputs, markets, history, _ = run130.features129.build(packet, price_source, 0.)
            for config in configs:
                if config["price_source"] != price_source:
                    continue
                parameters = np.array([config[n] for n in PARAMETERS], dtype=float)
                for symbol in ("TOPIX", "NK225"):
                    ready = inputs[scene, symbol]
                    original = packet["inputs"][scene, symbol]
                    assert np.array_equal(ready["time_s"], original["time_s"])
                    assert np.array_equal(ready["seq"], original["seq"])
                    quotes = packet["quotes"][scene, symbol]
                    top = symbol == "TOPIX"
                    orders, trades, curve = night_budget130.simulate(
                        ready["time_s"], ready["last"], quotes["bid"], quotes["ask"], quotes["quote_valid"],
                        ready["atr"], history[scene, symbol], markets[scene, symbol],
                        ready["start"], ready["limit"], ready["us_open"], ready["tick"],
                        5 if top else 10, 1000. if top else 10., 418 if top else 110,
                        parameters, config["retest_mode"], config["exit_style"],
                        activity[symbol], config["activity_mode"], config["budget_mode"])
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
    save(folder / "全条件の会計.json", dict(passed=True, rows=rows, cache=cache, configs=configs,
         financial_replays=len(rows), sources=fixed["sources"], input_manifest=reference(BASE / "入力準備.json"),
         activity_manifest=reference(ACTIVITY_MANIFEST)))


if __name__ == "__main__":
    main()
