"""Ｇ再評価に不足する六一分足と旧百二十保存会計を金融なしで束ねる。"""

import hashlib
from io import BytesIO
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
READS = []


def read_json(path):
    """
    機能: 既存の目録・公開会計と指紋だけを読む。
    引数: path(Path)はメタデータ保存先。
    返り値: dictは日本語ＪＳＯＮの内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def material(path, expected, kind):
    """
    機能: 許可された原足又は保存会計を一度読んで同じｂｙｔｅｓで検証する。
    引数: path(Path)、expected(str)、kind(str)は目録資格。
    返り値: bytesは固定指紋と一致した所有用コピー内容。
    """
    relative = path.relative_to(ROOT).as_posix()
    assert relative not in {v["path"] for v in READS}
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == expected, (relative, digest, expected)
    READS.append(dict(path=relative, sha256=digest, reads=1, bytes=len(payload), kind=kind))
    return payload


def main():
    """
    機能: 追加十一場の二十二一分足と旧Ｇ・ＧＵ百二十会計を所有化する。
    引数: なし。
    返り値: None。新たな売買再生・ＡＰＩ取得は行わない。
    """
    output = HERE/"Ｇ再評価の非金融素材準備.json"
    assert not output.exists()
    previous = read_json(ROOT/"work/wave_v106/e01_reference/prepared/入力準備の完了.json")
    first = {name:digest for name,digest in previous["原本SHA256"].items() if name.startswith("candle_1min/")}
    assert len(first) == 6
    latest = read_json(WORK/"input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json")
    consumer = HERE/"consumer"
    candle_rows = []
    for name, digest in sorted(first.items()):
        raw = material(ROOT/name, digest, "不足三場の原一分足一読")
        target = consumer/name
        assert not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        candle_rows.append(dict(path=target.relative_to(ROOT).as_posix(), sha256=digest, source=name))
    for item in latest["owned_consumer_candles"]:
        origin = ROOT/item["path"]
        raw = material(origin, item["sha256"], "追加八場の所有済一分足再利用")
        relative = origin.relative_to(WORK/"input_audit/attempt2/consumer126")
        target = consumer/relative
        assert not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        candle_rows.append(dict(path=target.relative_to(ROOT).as_posix(), sha256=item["sha256"], source=item["path"]))
    assert len(candle_rows) == 22
    saved = read_json(ROOT/"アルゴリズム調査/00081_E01原版と知見統合改修の再検証/公開会計.json")
    arrays, rows = {}, []
    for identifier in ("E01_G", "E01_G_U"):
        metadata = saved["観測現在値"][identifier]
        path = ROOT/"work/wave_v85/observed/ledgers"/(identifier+".pkl")
        records = pickle.loads(material(path, metadata["ledger_SHA256"], "旧三十場のＧ又はＧＵ保存会計"))
        expected = {(r["session"],r["symbol"]):r for r in metadata["rows"]}
        assert len(records) == len(expected) == 60
        for (scene, symbol), record in sorted(records.items()):
            multiplier = 1000. if symbol == "TOPIX" else 10.
            orders, trades, cycles = (np.asarray(record[name]) for name in ("orders", "trades", "cycles"))
            gains, parent = trades[:,10]*multiplier, cycles[:,3]*multiplier
            assert abs(gains.sum()-expected[(scene,symbol)]["gross"]) < 1e-6
            assert abs(gains.sum()-parent.sum()) < 1e-6
            assert expected[(scene,symbol)]["residual_long"] == expected[(scene,symbol)]["residual_short"] == 0
            assert orders[orders[:,7]==1,4].sum() == trades[:,3].sum()
            rows.append(dict(method=identifier, session=scene, symbol=symbol,
                profit=float(np.maximum(gains,0).sum()), loss=float(np.maximum(-gains,0).sum()),
                net=float(gains.sum()), fees=0., entry_orders=int((orders[:,7]==1).sum()),
                entry_quantity=int(orders[orders[:,7]==1,4].sum()), closed_quantity=int(trades[:,3].sum()),
                groups=len(cycles), parent_profit=float(np.maximum(parent,0).sum()),
                parent_loss=float(np.maximum(-parent,0).sum()), unclosed=0,
                origin="旧三十場の同じ実注文・数量・返済を手数料除外で引用"))
            prefix = identifier+"__"+symbol+"_"+scene+"__"
            for name in ("orders", "trades", "cycles", "stats"):
                arrays[prefix+name] = np.asarray(record[name])
    cache = HERE/"旧ＧとＧＵの三十場保存注文と返済.npz"
    assert not cache.exists()
    np.savez_compressed(cache, **arrays)
    extra = [p for p in latest["packets"] if p["session"] not in saved["全30"]]
    assert len(extra) == 11
    proof = dict(passed=True, csv=candle_rows, consumer=consumer.relative_to(ROOT).as_posix(),
        baseline=rows, baseline_cache=dict(path=cache.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(cache.read_bytes()).hexdigest()),
        additional_packets=extra, old30=saved["全30"], all41=latest["sessions"], read_log=READS,
        original_csv_reads=6, original_book_reads=0, owned_csv_reads=16,
        old_account_files_read=2, reused_accounts=120, new_financial_accounts=0, API=0,
        contract="旧30は保存gross注文引用、新11のG/GUだけ44新金融を予定。ready/signals/ATRは既存準備を維持。")
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, original_csv_reads=6, owned_csv_reads=16, reused_accounts=120, financial=0), ensure_ascii=False))


if __name__ == "__main__":
    main()
