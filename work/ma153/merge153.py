"""独立再会計済みの二巡を、xlsx用の小さい表示データへ統合する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    """固定結果を読み込み、元ファイル指紋を併せて返す。

    引数: path(Path)。返り値: tupleはJSON値と出典辞書。
    """
    data = path.read_bytes()
    return json.loads(data), {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    """金融再生をせず、表示に必要な全34条件の51場会計をまとめる。

    引数: なし。返り値: None。元の二巡の結果は書き換えない。
    """
    first, first_ref = read(HERE / "report153.json")
    second, second_ref = read(HERE / "round2/report153r2.json")
    order = [f"R{i:02d}" for i in range(1, 9)] + [f"M{i:02d}" for i in range(1, 25)] + ["F01", "F10"]
    methods = []
    for value in first["methods"] + second["methods"]:
        assert len(value["rows"]) == 51
        method = {key: value[key] for key in ("symbol", "id", "config", "description", "summary", "day", "night", "up", "down")}
        method["rows"] = [{key: item for key, item in row.items() if key not in ("worst_parents", "exit_reasons", "us_by_close_time", "pending")} for row in value["rows"]]
        assert abs(sum(row["net"] for row in method["rows"])-method["summary"]["net"]) < 1e-6
        methods.append(method)
    methods.sort(key=lambda m: (0 if m["symbol"] == "NK225" else 1, order.index(m["id"])))
    assert len(methods) == 68 and len({(m["symbol"], m["id"]) for m in methods}) == 68
    partial = [{key: row[key] for key in ("symbol", "id", "profit", "loss", "net", "unrealized", "equity", "entries", "remaining_qty")} for row in first["partial"] + second["partial"]]
    partial.sort(key=lambda m: (0 if m["symbol"] == "NK225" else 1, order.index(m["id"])))
    assert len(partial) == 68
    output = {"created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(), "sources": [first_ref, second_ref],
              "scope": "第一巡26・第二巡8条件、両商品各51完了場。途中1場は別。元会計からの表示用再集計のみ。",
              "methods": methods, "partial": partial}
    (HERE / "report153_combined.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"methods": len(methods), "complete_rows": sum(len(m["rows"]) for m in methods), "partial_rows": len(partial)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
