"""原版旧三十場は引用し、新十一場と十五改修だけを一度ずつ金融再生する。"""

import hashlib
import json
import pickle
import sys
import time
import numpy as np
from common126 import ROOT, HERE, sha, read, save

sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE / "engine"))
sys.path.insert(0, str(HERE / "design"))
import legacy126 as legacy
import policy126 as policy
from catalog126 import catalog


def normalize(result: dict, ready: dict, method: str, scene: str) -> dict:
    """
    機能: 返済脚会計を旧三十場の保存引用と同一列へ正規化する。
    引数: result/ready(dict)は会計と入力、method/scene(str)は条件と場。
    返り値: dictは費用なしの場会計。売買方向別の収支も別記する。
    """
    row = policy.normalized_summary(result, ready)
    mult = 1000. if ready["symbol"] == "TOPIX" else 10.
    trades = result["trades"]
    row.update(method=method, session=scene, model="observed",
        entry_orders=row.pop("entries"), entry_quantity=row.pop("new_lots"),
        closed_quantity=row.pop("settled_lots"), groups=row.pop("campaigns"),
        winning_quantity=row.pop("winning_lots"), losing_quantity=row.pop("losing_lots"),
        parent_wins=row.pop("winning_campaigns"), parent_losses=row.pop("losing_campaigns"),
        max_long=float(result["stats"][2]), max_short=float(result["stats"][3]),
        long_net=float(trades[trades[:, 2] == 1., 10].sum()*mult),
        short_net=float(trades[trades[:, 2] == -1., 10].sum()*mult),
        origin="今回の所有源と原版入力による金融再生")
    assert row["entry_quantity"] == row["closed_quantity"]
    cap = 10 if ready["symbol"] == "TOPIX" else 20
    assert row["max_long"] <= cap and row["max_short"] <= cap
    assert abs(row["long_net"]+row["short_net"]-row["net"]) < 1e-5
    return row


def execute() -> None:
    """
    機能: 登録・人工・入力指紋を拘束し、既存会計を重複再生せず比較する。
    引数: なし。
    返り値: None。全条件の場会計、注文、返済、時価曲線と機構事象を保存する。
    """
    fixed = read(HERE / "固定計画_確定書式.json")
    registered = read(HERE / "正式登録_確定書式の全出力.json")
    assert registered["終了コード"] == 0
    assert json.loads(registered["stdout"])["spec"]["implementation"] == fixed["sources"]
    for relative, expected in fixed["sources"].items():
        assert sha(ROOT / relative) == expected, relative
    for item in fixed["bindings"]:
        assert sha(ROOT / item["path"]) == item["sha256"], item["path"]
    manifest = read(ROOT / fixed["input"]["path"])
    assert manifest["passed"] and len(manifest["packets"]) == 41
    baseline = read(HERE / "baseline/原版旧三十場の費用なし保存引用.json")
    rows = baseline["rows"].copy()
    reused = {(r["session"], r["symbol"]) for r in rows}
    assert len(reused) == 60
    with np.load(ROOT / baseline["cache"]["path"], allow_pickle=False) as old_arrays:
        for row in rows:
            prefix = row["symbol"]+"_"+row["session"]
            trades = old_arrays[prefix+"__trades"]
            mult = 1000. if row["symbol"] == "TOPIX" else 10.
            row.update(long_net=float(trades[trades[:, 2] == 1., 10].sum()*mult),
                       short_net=float(trades[trades[:, 2] == -1., 10].sum()*mult))
    out = HERE / "measurement"
    assert not out.exists()
    out.mkdir()
    legacy.CACHE = str(HERE / "jit_financial126")
    assert not (HERE / "jit_financial126").exists()
    caches, input_reads, metadata = [], [], []
    new_accounts = 0
    with legacy.isolated(discover=False):
        runtime = legacy.runtime()
        for item in manifest["packets"]:
            started = time.time()
            payload = (ROOT / item["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            packet = pickle.loads(payload)
            scene = packet["session"]
            assert scene == item["session"]
            policy.bind_runtime(runtime, packet["inputs"], packet["signals"])
            input_reads.append(dict(path=item["path"], sha256=item["sha256"], reads=1))
            for symbol in ("TOPIX", "NK225"):
                key = scene, symbol
                ready = packet["inputs"][key]
                feature, market = packet["features"][key], packet["markets"][key]
                arrays = {}
                first, last = float(ready["last"][0]), float(ready["last"][-1])
                change = last/first-1.
                direction = "上昇" if change > 0. else "下落" if change < 0. else "同値"
                meta = dict(session=scene, symbol=symbol, first=first, last=last,
                    return_fraction=change, regime=direction,
                    strong_regime=direction if abs(change) >= .0025 else "小変動",
                    first_time=float(ready["time_s"][0]), last_time=float(ready["time_s"][-1]))
                metadata.append(meta)
                for config in catalog():
                    method = config["id"]
                    if method == "E01" and key in reused:
                        continue
                    result, settings = policy.play(runtime, config, ready, feature, market)
                    for name in ("orders", "trades", "cycles", "curve", "stats", "policy_events126"):
                        assert np.isfinite(result[name]).all(), (scene, symbol, method, name)
                        arrays[method+"__"+name] = result[name]
                    row = normalize(result, ready, method, scene)
                    row["settings"] = settings
                    rows.append(row)
                    new_accounts += 1
                target = out / (symbol+"_"+scene+".npz")
                np.savez_compressed(target, **arrays)
                caches.append(dict(session=scene, symbol=symbol,
                    path=target.relative_to(ROOT).as_posix(), sha256=sha(target)))
            save(out / (scene+".json"), dict(rows=[r for r in rows if r["session"] == scene],
                completed_new_accounts=new_accounts, seconds=time.time()-started))
            print(scene+" 十六条件を保存・旧原版は引用 "+str(new_accounts)+" 新口座", flush=True)
    assert new_accounts == 1252 and len(rows) == 1312 and len(caches) == 82
    assert len({(r["method"], r["session"], r["symbol"]) for r in rows}) == len(rows)
    for relative, expected in fixed["sources"].items():
        assert sha(ROOT / relative) == expected, relative
    save(HERE / "原版と十五改修の全四十一場会計.json", dict(passed=True,
        rows=rows, cache=caches, metadata=metadata, sessions=manifest["sessions"],
        specs=catalog(), sources=fixed["sources"], input_reads=input_reads,
        baseline=dict(path="work/stability126_20261019/baseline/原版旧三十場の費用なし保存引用.json",
                      sha256=sha(HERE / "baseline/原版旧三十場の費用なし保存引用.json")),
        new_financial_accounts=new_accounts, reused_accounts=60, displayed_accounts=len(rows),
        original_market_reads=0, API=0, real_orders=0,
        execution="原版の観測Last約定。BBO売買気配での新規・返済価格とは異なる。実ミニ/マイクロ約定保証ではない。",
        accounting="手数料0。利益と損失は返済脚の正負。組の正負はparent列。全場内返済。",
        classification="場初から保存窓末へのLast符号、強い上下感度は絶対変化0.25%以上。分類は採点のみ。全41場は既知開発。"))


if __name__ == "__main__":
    execute()
