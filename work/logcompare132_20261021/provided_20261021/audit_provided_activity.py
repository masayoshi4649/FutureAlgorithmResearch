"""提供された約定ログだけを読み取り、不発注理由を確定できる範囲を整理する。"""

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path


SOURCE = Path(r"C:\Users\masay\Downloads\log\dryrun")
HERE = Path(__file__).resolve().parent


def inspect_file(path):
    """
    機能: 指定提供ファイルの指紋・形式・期間を確認する。
    引数: path(Path)は指定共有領域内のファイル。
    返り値: tuple[dict,list]はファイル属性とJSON約定行。CSVは本文を二重集計しない。
    """
    payload = path.read_bytes()
    info = {"path": path.relative_to(SOURCE).as_posix(), "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in payload.decode("utf-8-sig").splitlines() if line.strip()]
        info.update(rows=len(rows), keys=list(rows[0]) if rows else [],
                    first=rows[0].get("at") if rows else None, last=rows[-1].get("at") if rows else None,
                    symbols=sorted({row.get("symbol", "") for row in rows}))
        return info, rows
    with path.open(encoding="utf-8-sig", newline="") as stream:
        table = list(csv.reader(stream))
    info.update(rows=max(0, len(table)-1), header=table[0] if table else [])
    return info, []


def summarize(rows):
    """
    機能: 約定済み記録の枚数・収支と理由表示を確認し、未約定の事情とは区別する。
    引数: rows(list[dict])は同じ商品の約定行。
    返り値: dictは記録範囲、保有残、理由コードと不明点。
    """
    holdings = {"buy": 0, "sell": 0}
    detail, wrong_labels = [], []
    for number, trade in enumerate(rows, 1):
        evidence = trade.get("evidence", {})
        envelope = evidence.get("decision", {})
        decision = envelope.get("decision", {})
        opposite = "sell" if trade["side"] == "buy" else "buy"
        if trade["trade_type"] == "new":
            holdings[trade["side"]] += trade["quantity"]
        else:
            holdings[opposite] -= trade["quantity"]
        assert min(holdings.values()) >= 0
        item = {"line": number, **{key: trade[key] for key in
            ("at", "product", "trade_type", "side", "quantity", "price", "pnl", "reason")},
            "reason_code": decision.get("reason_code"), "campaign": decision.get("campaign"),
            "algorithm": envelope.get("algorithm"), "configuration_signature": envelope.get("signature"),
            "decision_time": decision.get("time"), "source_index": decision.get("source_index"),
            "input_id": envelope.get("input_id"), "execution_input_id": evidence.get("execution_input_id"),
            "execution_quote_fresh": evidence.get("execution_quote_fresh"),
            "decision_received": envelope.get("received"), "execution_received": evidence.get("execution_received")}
        detail.append(item)
        if trade["trade_type"] == "close" and trade["reason"] == "主担当の新規":
            wrong_labels.append({"line": number, "at": trade["at"], "reason_code": decision.get("reason_code"),
                                 "correct_label": "組の損切り" if decision.get("reason_code") == 1 else "未確定"})
    return {"records": len(rows), "new_orders": sum(row["trade_type"] == "new" for row in rows),
            "last_record_at": rows[-1]["at"] if rows else None, "final_recorded_quantity": holdings,
            "gross_realized_pnl": sum(row["pnl"] for row in rows),
            "all_recorded_execution_quotes_fresh": all(row["execution_quote_fresh"] is True for row in detail),
            "wrong_reason_labels": wrong_labels, "trades": detail}


def check_csv_pairs():
    """
    機能: 全提供CSVを対応JSONLと行単位で照合し、二重集計や表示差を排除する。
    引数: なし。指定共有領域以外は読まない。
    返り値: dictは照合ファイル数と約定明細数。
    """
    total, files = 0, 0
    for path in sorted(SOURCE.rglob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        json_rows = [json.loads(line) for line in path.with_suffix(".jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        assert len(csv_rows) == len(json_rows)
        for left, right in zip(csv_rows, json_rows):
            for column, key in (("記録ID", "id"), ("セッション", "session"), ("銘柄", "symbol"),
                                ("理由", "reason"), ("担当", "owner"), ("商品", "product"), ("発注意図ID", "client_order_id")):
                assert left[column] == right[key]
            assert datetime.fromisoformat(left["約定確認時刻"]) == datetime.fromisoformat(right["at"])
            assert int(left["枚数"]) == right["quantity"]
            assert float(left["約定価格"]) == right["price"]
            assert float(left["実現損益円"]) == right["pnl"]
            assert left["区分"] == ("新規" if right["trade_type"] == "new" else "返済")
            assert left["売買"] == ("買い" if right["side"] == "buy" else "売り")
            assert json.loads(left["判断根拠JSON"]) == right["evidence"]
        total += len(json_rows)
        files += 1
    return {"passed": True, "file_pairs": files, "trade_records": total}


def main():
    """
    機能: 指定共有領域だけを監査し、追加再生なしで判定可能な点を保存する。
    引数: なし。別ディレクトリ・外部API・注文機能へ接続しない。
    返り値: None。出力は担当固有のJSONで、既存ファイルは上書きしない。
    """
    inventory, trades, events = [], {}, []
    for path in sorted(SOURCE.rglob("*")):
        if not path.is_file():
            continue
        info, rows = inspect_file(path)
        inventory.append(info)
        for row in rows:
            if "kind" in row:
                events.append(row)
            elif "trade_type" in row:
                trades.setdefault(row["symbol"], []).append(row)
    assert len(inventory) == 8
    all_trades = [row for rows in trades.values() for row in rows]
    signatures = sorted({row["evidence"]["decision"]["signature"] for row in all_trades})
    algorithms = sorted({row["evidence"]["decision"]["algorithm"] for row in all_trades})
    assert len(all_trades) == len({row["id"] for row in all_trades}) == 18
    assert len(signatures) == 1
    output = {"passed": True, "source": str(SOURCE), "inventory": inventory,
              "products": {name: summarize(rows) for name, rows in trades.items()},
              "csv_jsonl_match": check_csv_pairs(), "configuration_signatures": signatures, "algorithms": algorithms,
              "event_records": len(events), "API": 0, "financial_replays": 0,
              "requested_missing_entries": ["2026-10-21T14:34:48+09:00", "2026-10-21T15:07:33+09:00"],
              "confirmed": [
                  "marketというフォルダ名だが内容はTOPIXminiの約定記録であり、市場状態イベントではない。",
                  "両商品とも当日9約定明細、4新規。最後の記録時点で買い売り両方向の保有残はゼロ。",
                  "提供範囲にtrace.jsonl、口座照合、稼働状態、未成立判断、注文拒否、期限切れのイベントはない。",
                  "14時34分・15時07分の不発注理由を、この提供ログだけから確定することはできない。",
                  "記録された全約定のexecution_quote_freshはtrueだが、記録されていない時刻の鮮度はわからない。",
                  "返済なのに主担当の新規と表示された4明細はreason_code=1であり、日中の組の損切りに該当する。"],
              "unknown": [
                  "不足した新規時点に条件が成立したか。",
                  "成立した紙上新規を商品気配・口座鮮度等の理由で見送ったか。",
                  "通信中断・拒否・期限切れ等があったか。",
                  "当日の発注商品原板がないため、execution_input_idの約定BBO自体は未照合。"],
              "required_evidence": ["当日marketおよび商品別trace.jsonl", "当日のmarket.sqliteと商品別SQLite", "当日のconf"]}
    target = HERE / "提供約定ログの範囲と新規欠落の監査.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "output": str(target), "event_records": len(events),
                      "products": {name: {key: value[key] for key in
                          ("records", "new_orders", "final_recorded_quantity", "gross_realized_pnl", "wrong_reason_labels")}
                                   for name, value in output["products"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    main()
