"""固定資料と独立人工検査を確認してから昼夜の条件群を運転する。"""

import argparse
import hashlib
import pickle
from copy import deepcopy
import os
from pathlib import Path

import numpy as np
os.environ["NUMBA_CACHE_DIR"] = str(Path(__file__).resolve().parent/"jit_financial")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]

from common128 import HERE, ROOT, OLD, read, save, sha, reference
from adapter3 import play_day, play_night, summarize, day_filter, resize_feed


def sources():
    """
    機能: 今回使用する数値源と接続源を列挙する。
    引数: なし。
    返り値: dict[str,str]は保存位置と内容指紋。
    """
    names = ("common128.py","features128.py","catalog128.py","adapter3.py",
             "day_core2.py","bbo_order_kernel126.py","night3.py","run4.py")
    return {str((HERE/name).relative_to(ROOT)).replace("\\","/"):sha(HERE/name) for name in names}


def main():
    """
    機能: 一度だけ登録済み条件を再生し、各原行会計と全商品場損益を保存する。
    引数: --round(str)は固定された巡の識別。
    返り値: None。旧入力と完成会計を変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", default="round4")
    args = parser.parse_args()
    folder = HERE/args.round
    fixed = read(folder/"固定計画.json")
    registered = read(folder/"登録.json")
    assert registered["returncode"] == 0
    assert sources() == fixed["sources"]
    for proof in fixed["artificial"]:
        assert sha(ROOT/proof["path"]) == proof["sha256"]
        checked = read(ROOT/proof["path"])
        assert checked.get("passed",checked.get("全合格",False))
    for ref in fixed["input_references"]:
        assert sha(ROOT/ref["path"]) == ref["sha256"]
    manifest = read(HERE/"入力準備.json")
    old = read(OLD/"gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json")
    new = read(OLD/"update_20261020/追加二場の八公開選択会計.json")
    baseline = {(x["session"],x["symbol"]):x for x in old["cache"]}
    baseline.update({(x["session"],x["symbol"]):x for x in new["cache"] if x["model"] == "next_normal_bbo"})
    preceding = read(HERE/"round2/全条件の会計.json")
    preceding_cache = {(x["session"],x["symbol"]):x for x in preceding["cache"]}
    save(folder/"金融実行開始.json",dict(sources=fixed["sources"],registered=reference(folder/"登録.json"),
        account_count=sum(2*sum(c["kind"]==p["session"].split("_")[-1] for c in fixed["configs"]) for p in manifest["packets"]),
        API=0,real_orders=0))
    rows, caches = [], []
    financial, aliases = 0, 0
    for ref in manifest["packets"]:
        scene = ref["session"]
        specs = [c for c in fixed["configs"] if c["kind"] == scene.split("_")[-1]]
        if not specs:
            continue
        assert sha(ROOT/ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        h = ref["features"]
        assert sha(ROOT/h["path"]) == h["sha256"]
        with np.load(ROOT/h["path"],allow_pickle=False) as features:
            for symbol in ("TOPIX","NK225"):
                key = scene,symbol
                ready,quotes,market = packet["inputs"][key],packet["quotes"][key],packet["markets"][key]
                history = features[symbol+"__history"]
                memo = {}
                if scene.endswith("_Day"):
                    feed = features[symbol+"__feed"]
                    bref = baseline[key]
                    assert sha(ROOT/bref["path"]) == bref["sha256"]
                    with np.load(ROOT/bref["path"],allow_pickle=False) as archive:
                        base = {k:archive["G_Q__"+k] for k in ("orders","trades","cycles","stats")}
                    signature = hashlib.sha256(feed.tobytes()+b"0").hexdigest()
                    memo[signature] = dict(result=base,origin="00126の同一条件を保存引用",canonical="G_Q")
                    for previous in preceding["configs"]:
                        if previous["kind"] != "Day":
                            continue
                        previous_feed = day_filter(feed,ready,market,history,previous["entry_filter"])
                        signature = hashlib.sha256(previous_feed.tobytes()+str((previous["exit_rule"],
                            previous["risk_floor"],previous["protect_start"])).encode()).hexdigest()
                        memo[signature] = dict(saved=preceding_cache[key],
                            origin="第二巡の同一通知・同一核設定を保存引用",canonical=previous["id"])
                arrays = {}
                for config in specs:
                    method = config["id"]
                    signature = None
                    if config["engine"] == "day":
                        selected = day_filter(feed,ready,market,history,config["entry_filter"])
                        selected = resize_feed(selected,market,config["weak_fraction"])
                        signature = hashlib.sha256(selected.tobytes()+str((config["exit_rule"],config["risk_floor"],config["protect_start"])).encode()).hexdigest()
                    if signature in memo:
                        found = memo[signature]
                        if "result" in found:
                            result = found["result"]
                        else:
                            saved = found["saved"]
                            assert sha(ROOT/saved["path"]) == saved["sha256"]
                            prefix = found["canonical"]+"__"
                            with np.load(ROOT/saved["path"],allow_pickle=False) as archive:
                                result = {k[len(prefix):]:archive[k] for k in archive.files if k.startswith(prefix)}
                            found["result"] = result
                        origin,canonical = found["origin"],found["canonical"]
                        aliases += 1
                    else:
                        result = (play_day(config,ready,quotes,market,history,feed) if config["engine"]=="day"
                                  else play_night(config,ready,quotes,market,history))
                        origin,canonical = "新金融再生",method
                        financial += 1
                        if signature:
                            memo[signature] = dict(result=result,origin="今回の同一条件を引用",canonical=method)
                    row = summarize(result,ready,config)
                    row.update(origin=origin,canonical=canonical)
                    rows.append(row)
                    for name in ("orders","trades","cycles","curve","stats","execution_events"):
                        if name in result:
                            arrays[method+"__"+name] = result[name]
                target = folder/"measurement"/(symbol+"_"+scene+".npz")
                target.parent.mkdir(parents=True,exist_ok=True)
                assert not target.exists()
                np.savez_compressed(target,**arrays)
                caches.append(dict(session=scene,symbol=symbol,**reference(target)))
                del arrays,memo
        print(scene, "完了",len(rows),flush=True)
    save(folder/"全条件の会計.json",dict(passed=True,rows=rows,cache=caches,
        financial_replays=financial,aliases=aliases,configs=fixed["configs"],sources=fixed["sources"],
        input_manifest=reference(HERE/"入力準備.json"),fees="新規返済とも片道TOPIXmini41.8円・NKmicro11円、注文別円未満切捨て",
        prices="ラージ気配代理・次正常原行成行。実ミニ等の板や実受信順の再現ではない。"))


if __name__ == "__main__":
    main()
