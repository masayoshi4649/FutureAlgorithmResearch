"""既知ＧとＧＵの追加十一場だけを運転し、旧三十場の通知へ連結する。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np

from adapter126 import HERE, WORK, ENGINE, catalog, play

ROOT = WORK.parents[1]
sys.path.insert(0, str(ENGINE))
import legacy126
import policy126


def read(path):
    """
    機能: 固定された小目録又は成功登録を読む。
    引数: path(Path)は保存位置。
    返り値: dictは日本語ＪＳＯＮ。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 計画・数値源・完成出力の指紋を得る。
    引数: path(Path)は検証対象。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    """
    機能: 第三段の未使用位置だけへ有限ＪＳＯＮを保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。既存の測定を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def summary(result, ready, method):
    """
    機能: 手数料零の返済脚と親組の金額を別々に集計する。
    引数: result/ready(dict)、method(str)は原Ｇの完成会計と当時入力。
    返り値: dictは商品場別の利益・損失・収支と数量。
    """
    multiplier = 1000. if ready["symbol"] == "TOPIX" else 10.
    trades, cycles, orders = (result[name] for name in ("trades", "cycles", "orders"))
    gain, parent = trades[:,10]*multiplier, cycles[:,3]*multiplier
    row = dict(method=method, session=ready["session"], symbol=ready["symbol"],
        profit=float(np.maximum(gain,0).sum()), loss=float(np.maximum(-gain,0).sum()),
        net=float(gain.sum()), fees=0., parent_profit=float(np.maximum(parent,0).sum()),
        parent_loss=float(np.maximum(-parent,0).sum()), groups=len(cycles),
        entry_orders=int((orders[:,7]==1).sum()), entry_quantity=int(orders[orders[:,7]==1,4].sum()),
        closed_quantity=int(trades[:,3].sum()), unclosed=int(result["stats"][9]),
        long_net=float(gain[trades[:,2]>0].sum()), short_net=float(gain[trades[:,2]<0].sum()),
        max_long=float(result["stats"][2]), max_short=float(result["stats"][3]),
        origin="旧Ｇ入口と通常影の追加十一場を費用零で測定")
    assert row["entry_quantity"] == row["closed_quantity"] and row["unclosed"] == 0
    assert abs(row["net"]-parent.sum()) < 1e-6
    assert abs(row["net"]-result["stats"][0]*multiplier) < 1e-6
    return row


def main():
    """
    機能: 成功登録後だけ四十四口座を計算し、全四十一場のＧ・ＧＵ通知を作る。
    引数: なし。
    返り値: None。旧百二十会計は再生しない。
    """
    fixed = read(HERE/"固定計画.json")
    registration = read(HERE/"正式登録の全出力.json")
    assert registration["終了コード"] == 0
    assert json.loads(registration["stdout"])["spec"]["implementation"] == fixed["sources"]
    for name, digest in fixed["sources"].items():
        assert sha(ROOT/name) == digest, name
    for item in fixed["bindings"]:
        assert sha(ROOT/item["path"]) == item["sha256"]
    material = read(HERE/"Ｇ再評価の非金融素材準備.json")
    prepared = read(HERE/"追加十一場のＧ入口許可の非金融準備.json")
    assert material["passed"] and prepared["passed"]
    rows = material["baseline"].copy()
    feed_arrays = {}
    baseline_cache = ROOT/material["baseline_cache"]["path"]
    payload = baseline_cache.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == material["baseline_cache"]["sha256"]
    with np.load(BytesIO(payload), allow_pickle=False) as archive:
        for row in rows:
            identifier = row["method"]
            stem = identifier+"__"+row["symbol"]+"_"+row["session"]+"__"
            feed = ("GU_" if identifier.endswith("_U") else "G_")+row["symbol"]+"_"+row["session"]+"__"
            for name in ("orders", "trades", "cycles"):
                feed_arrays[feed+name] = archive[stem+name]
            trade = feed_arrays[feed+"trades"]
            mult = 1000. if row["symbol"] == "TOPIX" else 10.
            row["long_net"] = float(trade[trade[:,2]>0,10].sum()*mult)
            row["short_net"] = float(trade[trade[:,2]<0,10].sum()*mult)
    output = HERE/"measurement"
    assert not output.exists()
    output.mkdir()
    legacy126.CACHE = str(HERE/"jit_financial_rearm")
    assert not (HERE/"jit_financial_rearm").exists()
    gate_path = ROOT/prepared["cache"]["path"]
    gate_bytes = gate_path.read_bytes()
    assert hashlib.sha256(gate_bytes).hexdigest() == prepared["cache"]["sha256"]
    caches, packet_reads, count = [], [], 0
    save(HERE/"金融開始.json", dict(registered=True, started_ns=time.time_ns(), accounts_expected=44, new_financial_accounts_completed=0,
        registered_source_sha256=sha(HERE/"正式登録の全出力.json")))
    with np.load(BytesIO(gate_bytes), allow_pickle=False) as permissions, legacy126.isolated():
        runtime = legacy126.runtime()
        for item in material["additional_packets"]:
            payload = (ROOT/item["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            packet = pickle.loads(payload)
            assert packet["session"] == item["session"]
            policy126.bind_runtime(runtime, packet["inputs"], packet["signals"])
            arrays = {}
            for symbol in ("TOPIX", "NK225"):
                key = packet["session"], symbol
                ready = packet["inputs"][key]
                feature = dict(packet["features"][key], gate=permissions[symbol+"_"+key[0]])
                for config in catalog():
                    result, settings = play(runtime, config, ready, feature)
                    row = summary(result, ready, config["id"])
                    json.dumps(settings, ensure_ascii=False, allow_nan=False)
                    row["settings"] = settings
                    rows.append(row)
                    method = "GU" if config["id"].endswith("_U") else "G"
                    stem = method+"_"+symbol+"_"+key[0]+"__"
                    for name in ("orders", "trades", "cycles", "curve", "stats"):
                        arrays[stem+name] = result[name]
                        if name in ("orders", "trades", "cycles"):
                            feed_arrays[stem+name] = result[name]
                    count += 1
            target = output/(packet["session"]+".npz")
            np.savez_compressed(target, **arrays)
            caches.append(dict(path=target.relative_to(ROOT).as_posix(),sha256=sha(target),session=packet["session"]))
            packet_reads.append(dict(path=item["path"],sha256=item["sha256"],reads=1))
            save(output/(packet["session"]+".json"),dict(new_accounts_completed=count,rows=[r for r in rows if r["session"] == packet["session"]]))
            print(packet["session"]+" Ｇ・ＧＵを保存 "+str(count)+"新口座", flush=True)
    assert count == 44 and len(rows) == 164 and len(feed_arrays) == 164*3
    feed_path = HERE/"原版GとGUの全四十一場注文.npz"
    assert not feed_path.exists()
    np.savez_compressed(feed_path, **feed_arrays)
    for name, digest in fixed["sources"].items():
        assert sha(ROOT/name) == digest
    save(HERE/"ＧとＧＵの全四十一場会計.json", dict(passed=True,rows=rows,
        unified_cache=dict(path=feed_path.relative_to(ROOT).as_posix(),sha256=sha(feed_path)),
        cache=caches, new_financial_accounts=44,reused_accounts=120,displayed_accounts=164,
        packet_reads=packet_reads,sources=fixed["sources"],specs=catalog(),sessions=material["all41"],
        baseline_source=dict(path=(HERE/"Ｇ再評価の非金融素材準備.json").relative_to(ROOT).as_posix(),sha256=sha(HERE/"Ｇ再評価の非金融素材準備.json")),
        execution="旧原版と同じ観測Last。BBO約定は後段の別検証。手数料零。",
        feed_contract="G又はGU_商品_セッション__orders/trades/cycles。cycles[:,5]が初回ATR。原版旧30は保存注文引用、追加11のみ新金融。",
        original_market_reads=0,preparation_original_csv_reads=6,API=0,real_orders=0))
    print("Ｇ・ＧＵ全164会計と全場紙上通知を保存", flush=True)


if __name__ == "__main__":
    main()
