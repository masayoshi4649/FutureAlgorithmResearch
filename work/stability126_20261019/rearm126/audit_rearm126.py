"""Ｇ・ＧＵの完成会計と後段通知を、売買再生せず全注文から検算する。"""

from io import BytesIO
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0,str(WORK/"audit_result126"))
from audit126 import audit_account, totals

READS = {}


def read_once(path, digest=None):
    """
    機能: 保存会計・所有入力を同じ検算中に一度だけ読み指紋を確認する。
    引数: path(Path)、digest(str|None)は保存先と期待指紋。
    返り値: bytesは固定内容。市場原本は読まない。
    """
    assert path.resolve().is_relative_to(WORK)
    key = path.relative_to(ROOT).as_posix()
    assert key not in READS
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    assert digest is None or digest == actual
    READS[key] = dict(sha256=actual,reads=1,bytes=len(raw))
    return raw


def main():
    """
    機能: 新四十四の全行会計、旧百二十引用、単一通知と累計を独立検算する。
    引数: コマンド行の完成結果ＳＨＡ２５６(str)を一つ受け取る。
    返り値: None。新金融なしで監査証拠を保存する。
    """
    assert len(sys.argv) == 2 and len(sys.argv[1]) == 64
    result = json.loads(read_once(HERE/"ＧとＧＵの全四十一場会計.json",sys.argv[1]))
    assert result["passed"] and result["new_financial_accounts"] == 44
    assert result["reused_accounts"] == 120 and result["displayed_accounts"] == 164
    rows = {(r["method"],r["session"],r["symbol"]):r for r in result["rows"]}
    assert len(rows) == 164
    material = json.loads(read_once(ROOT/result["baseline_source"]["path"],result["baseline_source"]["sha256"]))
    merged = result["unified_cache"]
    feeds = np.load(BytesIO(read_once(ROOT/merged["path"],merged["sha256"])),allow_pickle=False)
    assert len(feeds.files) == 164*3
    base_item = material["baseline_cache"]
    baseline = np.load(BytesIO(read_once(ROOT/base_item["path"],base_item["sha256"])),allow_pickle=False)
    records, curve_rows = [], 0
    for row in material["baseline"]:
        method = row["method"]
        own = method+"__"+row["symbol"]+"_"+row["session"]+"__"
        feed = ("GU_" if method.endswith("_U") else "G_")+row["symbol"]+"_"+row["session"]+"__"
        arrays = {}
        for field in ("orders","trades","cycles"):
            arrays[field] = feeds[feed+field]
            np.testing.assert_array_equal(arrays[field],baseline[own+field])
        records.append(audit_account(rows[(method,row["session"],row["symbol"])],arrays))
    baseline.close()
    caches = {r["session"]:r for r in result["cache"]}
    assert len(caches) == 11
    for item in material["additional_packets"]:
        packet = pickle.loads(read_once(ROOT/item["path"],item["sha256"]))
        scene = packet["session"]
        assert scene == item["session"]
        cache = caches[scene]
        with np.load(BytesIO(read_once(ROOT/cache["path"],cache["sha256"])),allow_pickle=False) as measured:
            for symbol in ("TOPIX","NK225"):
                ready = packet["inputs"][(scene,symbol)]
                assert ready["session"] == scene and ready["symbol"] == symbol
                price = ready["last"]
                assert len(price) == len(ready["seq"]) == len(ready["time_s"])
                assert np.all(np.diff(ready["seq"]) > 0) and np.all(np.diff(ready["time_s"]) >= 0)
                for prefix,method in (("G_","E01_G"),("GU_","E01_G_U")):
                    stem = prefix+symbol+"_"+scene+"__"
                    arrays = {field:measured[stem+field] for field in ("orders","trades","cycles","curve","stats")}
                    for field in ("orders","trades","cycles"):
                        np.testing.assert_array_equal(arrays[field],feeds[stem+field])
                    record = audit_account(rows[(method,scene,symbol)],arrays,price)
                    raw_rows = arrays["orders"][:,0].astype(int)
                    source_rows = arrays["orders"][:,1].astype(int)
                    assert np.all(ready["seq"][source_rows] < ready["seq"][raw_rows])
                    record["order_original_sequences"] = ready["seq"][raw_rows].astype(int).tolist()
                    records.append(record)
                    curve_rows += len(price)
        print(scene+" Ｇ・ＧＵと紙上通知の独立会計一致",flush=True)
    feeds.close()
    assert len(records) == 164 and sum(v["curve_audited"] for v in records) == 44
    proof = dict(passed=True,result_sha256=sys.argv[1],accounts=164,new_accounts=44,reused_accounts=120,
        full_curve_rows=curve_rows,rows=records,totals=totals(records),reads=READS,
        unified_notifications_equal=True,new_financial_replays=0,original_market_reads=0,API=0,
        limitation="実装作者による監査。独立担当の旧新純人工・旧120引用照合と併用し、新経済源とは別の前段独立算術を用いる。実市場の収益再生はしない。",
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    output = HERE/"ＧＧＵ全百六十四会計と全行時価及び紙上通知の独立監査.json"
    assert not output.exists()
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(dict(passed=True,accounts=164,full_curve_rows=curve_rows),ensure_ascii=False))


if __name__ == "__main__":
    main()
