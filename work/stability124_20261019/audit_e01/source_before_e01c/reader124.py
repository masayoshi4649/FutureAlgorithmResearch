"""完成 SHA の通知後だけ、追加二口座の保存注文を独立会計する。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import accounting_source as source


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
E01 = HERE.parent / "e01"
RESULT = E01 / "追加一場の固定少額E01二商品.json"
OLD = ROOT / "work/stability119_20261017/v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json"
OLD_SHA = "d0f1f86cb955a2da7016f0a33f6ff097eb64edb14068e8d0a0b4278aebca963b"
ACTUAL = {"TOPIX": "E01_ADAPT_G50_ADAPT75_P1", "NK225": "E01_ADAPT_G25_ADAPT100_P1"}
READS = {"新結果": 0, "新入力": 0, "新台帳": 0, "旧40保存結果": 0, "原市場": 0, "金融再生": 0, "旧入力cache": 0, "API": 0, "実注文": 0}


def write(name: str, value: dict) -> dict:
    """
    機能: 新しい独立監査資料を所有領域へ保存する。
    引数: name (str) 保存名、value (dict) 有限 JSON 資料。
    返り値: dict 保存位置と SHA256。
    """
    path = HERE / name
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def own_packet(info: dict, destination: Path, kind: str) -> dict:
    """
    機能: 明示された新保存入力または台帳だけを一読保全する。
    引数: info (dict) 位置・SHA・bytes、destination (Path) 新保全先、kind (str) input/ledger。
    返り値: dict 変更不変を確認した展開値。
    """
    path = (ROOT / info["path"]).resolve()
    source.audit.check(path.is_relative_to(E01 / "measurement" / kind), "追加口座の保存域だけ")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    source.audit.check((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "保存cache読取前後不変")
    source.audit.check(len(raw) == info["bytes"] and hashlib.sha256(raw).hexdigest() == info["SHA256"], "保存cache同bytes")
    assert not destination.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    READS["新入力" if kind == "input" else "新台帳"] += 1
    return pickle.loads(gzip.decompress(raw))


def main(expected_sha: str) -> None:
    """
    機能: 追加二口座の UID・料金・BBO・枚数・親・全行資産・flat を独立照合する。
    引数: expected_sha (str) 根が完成後に通知した正式結果 SHA256。
    返り値: None。金融規則と原市場を再実行せず、旧40場は保存 JSON 引用だけに分離する。
    """
    source.audit.check(len(expected_sha) == 64, "根の正式完成SHAが必要")
    binding = json.loads((HERE / "独立会計算術の旧人工への拘束.json").read_text(encoding="utf-8"))
    source.audit.check(binding["passed"] and hashlib.sha256((HERE / "accounting_source.py").read_bytes()).hexdigest() == binding["accounting_source_sha256"], "旧1020人工へ拘束した算術")
    owned = HERE / "owned"
    owned.mkdir(exist_ok=False)
    raw = RESULT.read_bytes()
    READS["新結果"] += 1
    source.audit.check(hashlib.sha256(raw).hexdigest() == expected_sha, "新完成結果の正式同bytes")
    (owned / "完成結果.json").write_bytes(raw)
    result = json.loads(raw)
    source.audit.check(result["passed"] and result["sessions"] == ["2026-10-19_Day"], "追加対象一場と完成合格")
    source.audit.check(result["actual_config"] == ACTUAL, "旧固定二設定を選び直さない")
    source.audit.check(result["financial_accounts"] == 2 and result["original_market_reads"] == result["old_financial_accounts"] == result["API"] == result["real_orders"] == 0, "新二会計だけ・原市場再読と旧再金融なし")
    expected_keys = {("2026-10-19_Day", symbol) for symbol in ACTUAL}
    for field in ("rows", "accounts", "cache"):
        source.audit.check(len(result[field]) == 2 and {(row["session"], row["symbol"]) for row in result[field]} == expected_keys, "追加識別の欠落重複なし:" + field)
    for relative, digest in result["sources"].items():
        path = (ROOT / relative).resolve()
        source.audit.check(path.is_relative_to(E01) and path.suffix in (".py", ".json"), "数値源は今回所有版だけ")
        source.audit.check(hashlib.sha256(path.read_bytes()).hexdigest() == digest, "数値源は正式完成時と不変")
    # ----------------------------------------
    lookup = {(row["session"], row["symbol"]): row for row in result["rows"]}
    details = {(row["session"], row["symbol"]): row for row in result["accounts"]}
    certificates = []
    for item in result["cache"]:
        scene, symbol = item["session"], item["symbol"]
        account = own_packet(item["input"], owned / "input" / symbol / (scene + ".pkl.gz"), "input")
        ledger = own_packet(item["ledger"], owned / "ledger" / symbol / (scene + ".pkl.gz"), "ledger")
        source.audit.check(account["symbol"] == symbol and ledger["key"] == (scene, symbol), "保存入出力の識別一致")
        summary = source.reconstruct(account, ledger)
        detail = details[scene, symbol]
        source.audit.check(detail["actual_config"] == ACTUAL[symbol], "詳細の旧固定ID一致")
        for field in ("summary", "parent", "actual_legs", "uid_accounts"):
            source.compare(detail[field], ledger[field], "JSONと保存台帳の完全会計:" + field)
        source.compare(detail["summary"], summary, "独立新場会計")
        source.compare(lookup[scene, symbol], {"profit": summary["利益"], "loss": summary["損失"], "net": summary["収支"], "campaigns": summary["親数"], "winning_campaigns": summary["勝ち親"], "losing_campaigns": summary["負け親"], "winning_lots": summary["勝ち枚数"], "losing_lots": summary["負け枚数"], "fees": summary["費用"], "unclosed": 0, "verified_flat": True}, "新場小結果と全注文会計")
        source.audit.check(len(detail["orders"]) == len(ledger["orders"]), "JSON全実注文数")
        for index, given in enumerate(detail["orders"]):
            order = ledger["orders"][index]
            row = int(order[0])
            source.compare(given, {"index": index, "order": order.tolist(), "uid": int(ledger["order_uids"][index]), "fee": int(ledger["order_fees"][index]), "raw_seq": int(account["record"]["seq"][row]), "price_time_s": float(account["record"]["time_s"][row]), "bid": float(account["quotes"]["bid"][row]), "ask": float(account["quotes"]["ask"][row]), "quote_valid": True}, "全実注文の原seq・時計・BBO・UID・料金")
        certificates.append({"session": scene, "symbol": symbol, "passed": True, "注文数": len(ledger["orders"]), "入力正常行数": len(account["record"]["seq"]), "summary": summary, "新実終端flat": True, "input": item["input"], "ledger": item["ledger"]})
        print(json.dumps({"完了新口座": len(certificates), "session": scene, "symbol": symbol, "検査数": source.audit.CHECKS}, ensure_ascii=False), flush=True)
    # ----------------------------------------
    # 旧40場の独立再監査とは呼ばず、同bytesの保存済み小結果として区分する。
    old_raw = OLD.read_bytes()
    READS["旧40保存結果"] += 1
    source.audit.check(hashlib.sha256(old_raw).hexdigest() == OLD_SHA, "旧40場の指定保存SHA一致")
    (owned / "旧40保存結果.json").write_bytes(old_raw)
    old = json.loads(old_raw)
    source.audit.check(old["全合格"] and len(old["sessions"]) == 40 and len(old["rows"]) == 80 and old["actual_config"] == ACTUAL, "旧40場は保存済み二商品80行だけ引用")
    source.audit.check(len({(row["session"], row["symbol"]) for row in old["rows"]}) == 80, "旧引用識別の重複なし")
    old_only = {}
    new_only = {}
    combined = {}
    for symbol in ACTUAL:
        prior = [row for row in old["rows"] if row["symbol"] == symbol]
        added = [row for row in result["rows"] if row["symbol"] == symbol]
        source.audit.check(len(prior) == 40 and len(added) == 1, "商品別の旧40引用と新1会計を分離")
        source.audit.check(all(row["actual_config"] == ACTUAL[symbol] for row in prior + added), "引用と新場の固定ID一致")
        old_only[symbol] = source.metrics(prior)
        new_only[symbol] = source.metrics(added)
        combined[symbol] = source.metrics(prior + added)
    source.audit.check(READS == {"新結果": 1, "新入力": 2, "新台帳": 2, "旧40保存結果": 1, "原市場": 0, "金融再生": 0, "旧入力cache": 0, "API": 0, "実注文": 0}, "許可済み保存資料の一読だけ")
    proof = {"passed": True, "全合格": True, "result_sha256": expected_sha, "結果SHA256": expected_sha, "監査源SHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "accounting_source_sha256": binding["accounting_source_sha256"], "検査数": source.audit.CHECKS, "counts": READS, "新独立監査口座": 2, "旧40引用のみ": {"path": OLD.relative_to(ROOT).as_posix(), "sha256": OLD_SHA, "sessions": 40, "accounts": 80, "新再監査成功へ加算": False}, "certificates": certificates, "metrics": {"旧40保存引用": old_only, "新1独立会計": new_only, "合計41の保存集計": combined}, "限界": "保存注文の会計整合だけを確認。入口/継続/出口規則や原市場を再実行せず、旧40場を新しい金融標本や独立再検証成功に数えない。実小型板・真受信順・ライブ約定を確認したものではない。"}
    print(json.dumps(write("追加二口座の全注文親UIDと全行時価の独立監査.json", proof), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        main(args.expected_sha)
    except BaseException as exc:
        write("False.json", {"passed": False, "counts": READS, "検査数": source.audit.CHECKS, "型": type(exc).__name__, "例外": str(exc)})
        raise
