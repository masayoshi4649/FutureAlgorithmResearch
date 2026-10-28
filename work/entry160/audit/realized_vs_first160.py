"""元初回の黒字と先着分類を、保有中・全返済後に分解する保存値監査。"""
from collections import Counter, defaultdict
from pathlib import Path
import json
import hashlib

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "work/entry160/audit"


def read(path: Path) -> dict:
    """保存値を読み取る。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    """全初回の元収支と保有終点を読み、50逆行先着の位置を分ける。

    引数: なし。返り値: None。新しい売買・価格ラベルは生成しない。
    """
    label_path = ROOT / "work/entry160/先着の全件160.json"
    source_paths = {label_path}
    labels = read(label_path)["rows"]
    day_path = ROOT / "work/score159/初回玉と支持の対応159.json"
    night_path = ROOT / "work/score159/夜間初回玉と支持の対応159.json"
    source_paths.update([day_path, night_path])
    prior = {(r["session"], r["initial_id"]): r for path in (day_path, night_path) for r in read(path)["rows"]}
    cache, out = {}, []
    for row in labels:
        path = ROOT / row["source"]
        source_paths.add(path)
        if path not in cache:
            cache[path] = read(path)
        source = cache[path]
        if "lots" in source:
            lot = next(x for x in source["lots"] if x["id"] == row["initial_id"])
            net = lot["net"]
            closes = lot["closes"]
            close_rows = [(x["index"], x["time"], x["quantity"], x["net"]) for x in closes]
            quantity = lot["quantity"]
        else:
            phase = next(s for s in source["sources"] if s["Phase"] == row["phase"])
            lot = phase["Lots"][row["initial_id"]]
            net, quantity = lot["Gross"], lot["Quantity"]
            close_rows = []
            for event in phase["Events"]:
                sig = event["Signal"]
                if sig["action"] != "close":
                    continue
                for target in sig["targets"]:
                    if target["id"] == row["initial_id"]:
                        gross = lot["Side"]*target["quantity"]*(event["Price"]-lot["Entry"])*100
                        close_rows.append((event["FillIndex"], event["FillTime"], target["quantity"], gross))
        assert sum(x[2] for x in close_rows) == quantity
        assert sum(x[3] for x in close_rows) == net
        key = (row["session"], row["initial_id"])
        if key in prior:
            assert prior[key]["initial_net"] == net
        else:
            assert row["session"] == "2026-10-27_Day"
        first_close, last_close = min(x[0] for x in close_rows), max(x[0] for x in close_rows)
        hit = row["primary"]["hit_index"]
        relation = "対象外"
        if net > 0 and row["primary"]["status"] == "50逆行先着":
            if hit <= first_close:
                relation = "最初の返済以前に50逆行先着"
            elif hit <= last_close:
                relation = "部分返済後かつ全返済以前に50逆行先着"
            else:
                relation = "全返済後に50逆行先着"
        out.append({"session": row["session"], "phase": row["phase"], "owner": row["owner"], "parent": row["parent"], "initial_id": row["initial_id"], "initial_net": net,
                    "status": row["primary"]["status"], "hit_index": hit, "hit_time": row["primary"]["hit_time"], "first_close_index": first_close, "last_close_index": last_close,
                    "first_close_time": min(x[1] for x in close_rows), "last_close_time": max(x[1] for x in close_rows), "relation": relation})
    groups = {}
    for name in ("全体", "日中", "前半", "後半"):
        selected = out if name == "全体" else [x for x in out if x["phase"] == name]
        wins = [x for x in selected if x["initial_net"] > 0]
        adverse = [x for x in wins if x["status"] == "50逆行先着"]
        counts = dict(Counter(x["relation"] for x in adverse))
        groups[name] = {"entries": len(selected), "original_profitable_initials": len(wins), "profitable_but_50_first": len(adverse), "relation_counts": counts,
                        "50_first_while_any_initial_quantity_remained": sum(x["hit_index"] <= x["last_close_index"] for x in adverse),
                        "50_first_after_initial_fully_closed": sum(x["hit_index"] > x["last_close_index"] for x in adverse)}
    assert groups["全体"]["original_profitable_initials"] == 177 and groups["全体"]["profitable_but_50_first"] == 89
    refs = [{"path": p.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(source_paths)]
    value = {"passed": True, "new_financial_replays": 0, "definition": "主ラベルは場末まで、元初回純損益は全返済合計。50逆行のhit_indexと初回玉の最初/最後の実返済indexで区別。同一返済行での到達は返済前評価なので保有中へ含める。", "limitation": "保有中の逆行を通って最終純益でも、部分利確の利益が残った例を含み得るため、すべて回復して利確したとは断定しない。", "groups": groups, "rows": out, "sources": refs}
    (HERE / "元黒字と50逆行先着の位置160.json").write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(groups, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
