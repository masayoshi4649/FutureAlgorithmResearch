"""同じ価格時計の異なる気配と、末尾代理損益を保存資料だけで区別する。"""
from collections import Counter
from pathlib import Path
import json
import math

from diagnose162 import WORK, HERE, completion_gate, read, sha, fingerprint


def timestamp_fields(value: object, path: str = "") -> dict:
    """原JSONの時計名を持つ項目を階層ごとに取り出す。

    引数: value(object)、path(str)。返り値: dict。
    """
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{path}.{key}" if path else key
            if any(word in key.lower() for word in ("time", "date", "received", "timestamp")):
                result[name] = item
            if isinstance(item, (dict, list)):
                result.update(timestamp_fields(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(timestamp_fields(item, f"{path}[{index}]"))
    return result


def main() -> None:
    """指定2原行の全時計と、53場H01/N00の通常・末尾代理会計を保存する。

    引数: なし。返り値: None。
    """
    _, records, sources = completion_gate(WORK)
    scene = next(s for s in read(WORK / "inputs162.json")["sessions"] if s["session"] == "2026-10-23_Day")
    path = Path(scene["books"]["NK225"])
    targets = {192540: 191057, 192800: 191317}
    raw, group = {}, []
    with path.open(encoding="utf-8-sig") as stream:
        for physical, line in enumerate(stream, 1):
            value = json.loads(line)
            if physical in targets:
                raw[str(physical)] = {"physical_line": physical, "index": targets[physical],
                                      "all_timestamp_fields": timestamp_fields(value), "original": value}
            if value.get("CurrentPriceTime") == "2026-10-23T15:39:59+09:00":
                buy, sell = value.get("Buy1", {}), value.get("Sell1", {})
                bid, ask = buy.get("Price"), sell.get("Price")
                valid = all(isinstance(p, (int, float)) and math.isfinite(p) for p in (bid, ask)) and 0 < bid < ask
                group.append({"physical_line": physical, "bid": bid, "ask": ask, "valid": valid,
                              "last": value.get("CurrentPrice"), "volume": value.get("TradingVolume"),
                              "volume_time": value.get("TradingVolumeTime"), "symbol": value.get("Symbol"),
                              "bid_sign": buy.get("Sign"), "ask_sign": sell.get("Sign")})
    valid_rows = [r for r in group if r["valid"]]
    group_summary = {"rows": len(group), "normal_rows": len(valid_rows), "first_physical": group[0]["physical_line"],
                     "last_physical": group[-1]["physical_line"], "last_values": sorted({r["last"] for r in group}),
                     "volume_values": sorted({r["volume"] for r in group}),
                     "volume_times": sorted({r["volume_time"] for r in group}),
                     "symbols": sorted({r["symbol"] for r in group}),
                     "normal_bid_min": min(r["bid"] for r in valid_rows), "normal_bid_max": max(r["bid"] for r in valid_rows),
                     "normal_ask_min": min(r["ask"] for r in valid_rows), "normal_ask_max": max(r["ask"] for r in valid_rows)}
    sums, session_rows = {}, []
    for record in records:
        saved = read(Path(record["path"]))
        for case in saved["cases"]:
            if case["id"] not in ("H01", "N00"):
                continue
            account = Counter()
            for event in case["events"]:
                order = event["order"]
                if order["action"] != "close":
                    continue
                category = "terminal_proxy" if event.get("proxy") else "normal"
                account[category + "_net"] += event["gross"]
                account[category + "_count"] += 1
                account[order["role"] + "_" + category + "_net"] += event["gross"]
                account[order["role"] + "_" + category + "_count"] += 1
                account[order["reason"] + "_reason_net"] += event["gross"]
                account[order["reason"] + "_reason_count"] += 1
            assert account["terminal_proxy_net"] + account["normal_net"] == case["summary"]["realized"]
            sums.setdefault(case["id"], Counter()).update(account)
            session_rows.append({"session": saved["session"], "id": case["id"], "net": case["summary"]["realized"], **account})
    result = {"raw_source": {"path": str(path), "sha256": sha(path)}, "selected_rows": raw,
              "same_current_price_time": group_summary, "raw_group": group,
              "all_53_accounts": {k: dict(v) for k, v in sums.items()}, "session_accounts": session_rows,
              "facts": ["両原行のSymbolと限月は同一。CurrentPriceTime・TradingVolumeTime・CurrentPrice・TradingVolumeも同一。",
                        "BidTime、AskTime、Buy1.Time、Sell1.Time、独立受信時計とwrapperは両原行に存在しない。",
                        "BidPrice/AskPriceの上位字段とBuy1/Sell1は同じ意味として置換していない。研究はBuy1.Priceを買板、Sell1.Priceを売板として使用。",
                        "物理行順の気配変化は確認できるが実受信間隔と変化理由はこの原JSONだけでは識別できない。",
                        "同価格時計500円差を実時間1秒以内の変化又は引け約定値と断定しない。保存済み金融結果は変更していない。"],
              "sources": sources, "implementation": fingerprint(Path(__file__))}
    target = HERE / "価格時計と末尾精算162.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"output": fingerprint(target), "same_clock": group_summary,
                      "accounts": result["all_53_accounts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
