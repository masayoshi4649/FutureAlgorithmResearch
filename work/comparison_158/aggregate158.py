"""保存会計を同じ26デイへ限定して比較する。売買の再実行は行わない。"""

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import statistics

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCES = {
    "154": ROOT / "work/d07_154/report154.json",
    "154r2": ROOT / "work/d07_154/report154_round2.json",
    "156": ROOT / "work/s01_156/report156_all.json",
    "157": ROOT / "work/allocation_157/report157_all.json",
}


def load(path: Path) -> dict:
    """機能: UTF-8の保存JSONを読む。
    引数: path (Path) は読取対象。
    返り値: dict は保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    """機能: 内容指紋を求める。
    引数: path (Path) は対象ファイル。
    返り値: str はSHA-256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method(data: dict, mid: str) -> dict:
    """機能: 一意の手法を取り出す。
    引数: data (dict) は保存報告、mid (str) は手法ID。
    返り値: dict は対応する手法。
    """
    found = [m for m in data["methods"] if m["id"] == mid]
    assert len(found) == 1, mid
    return found[0]


def days(value: dict) -> dict:
    """機能: 完了デイ26場を取り出す。
    引数: value (dict) は手法別会計。
    返り値: dict はセッションをキーとする会計行。
    """
    found = [r for r in value["rows"] if r["session"].endswith("_Day") and not r.get("partial", False)]
    assert len(found) == 26 and len({r["session"] for r in found}) == 26
    assert all(r["remaining_qty"] == 0 and r["open_parent_realized"] == 0 for r in found)
    return {r["session"]: r for r in found}


def summary(rows: list[dict]) -> dict:
    """機能: 当場収支と完結親損益から比較値を算出する。
    引数: rows (list[dict]) は完了場会計。
    返り値: dict は累計、赤字頻度・深さ、場内リスク。
    """
    profits = sum(r["profit"] for r in rows)
    losses = sum(r["loss"] for r in rows)
    net = sum(r["net"] for r in rows)
    negatives = [-r["net"] for r in rows if r["net"] < 0]
    winners = sorted((r["net"] for r in rows if r["net"] > 0), reverse=True)
    assert profits - losses == net
    return {
        "sessions": len(rows), "profit": profits, "loss": losses, "net": net,
        "wins": sum(r["net"] > 0 for r in rows), "losses": len(negatives),
        "zero": sum(r["net"] == 0 for r in rows),
        "no_trade": sum(r["entries"] == 0 for r in rows),
        "entries": sum(r["entries"] for r in rows),
        "avgloss": statistics.mean(negatives) if negatives else 0,
        "medianloss": statistics.median(negatives) if negatives else 0,
        "maxloss": max(negatives, default=0), "ex3": net - sum(winners[:3]),
        "min_equity": min(r["intraday_risk"]["min_equity"] for r in rows),
        "max_drawdown": max(r["intraday_risk"]["max_drawdown"] for r in rows),
    }


def main() -> None:
    """機能: 保存会計の橋渡しと指紋を検査し、比較JSONを保存する。
    引数: なし。
    返り値: None。金融再生・現在API取得は行わない。
    """
    source_hashes = {key: sha(path) for key, path in SOURCES.items()}
    data = {key: load(path) for key, path in SOURCES.items()}
    base = days(method(data["154"], "D07"))
    old_s01 = days(method(data["154r2"], "S01"))
    newer_s01 = days(method(data["156"], "S01"))
    micro_s01 = days(method(data["157"], "C00"))
    bridge_checks = []
    for label, other in [("00154 S01→00156 S01", newer_s01), ("00154 S01→00157 C00", micro_s01)]:
        assert old_s01.keys() == other.keys() == base.keys()
        for session in base:
            for key in ["profit", "loss", "net", "entries", "parents", "remaining_qty", "direction"]:
                assert old_s01[session][key] == other[session][key], (label, session, key)
        bridge_checks.append({"comparison": label, "sessions": 26, "fields": 7, "passed": True})
    # ----------------------------------------
    # 原データを再取得せず、登録済み入力目録の場・内容指紋が一致するか調べる。
    input154 = ROOT / "work/d07_154/inputs154.json"
    input156 = ROOT / "work/s01_156/inputs156.json"
    scenes154 = {s["session"]: s for s in load(input154)["sessions"] if s["session"] in base}
    scenes156 = {s["session"]: s for s in load(input156)["sessions"] if s["session"] in base}
    assert scenes154 == scenes156 and len(scenes154) == 26
    risk_path = HERE / "D07の場内リスク定義統一158.json"
    if not risk_path.exists():
        raise FileNotFoundError("独立担当のD07全原板・逐次約定リスクを待ちます: " + str(risk_path))
    risk_data = load(risk_path)
    risk_rows = {r["session"]: r["intraday_risk"] for r in risk_data["rows"]}
    assert set(risk_rows) == set(base)
    configs = [
        ("D07", "154", "D07", "研究00154の現行Go基準"),
        ("S01", "154r2", "S01", "別入口の親利益保護と再参加抑止"),
        ("J02", "157", "J02", "S01の初回を最低10microと支持で配分"),
        ("O01", "157", "O01", "J02に40pt順行後の追加を加える"),
        ("O05", "157", "O05", "O01に逆玉の利益追尾と逆行回復追加"),
        ("F05", "156", "F05", "S01の玉別利益を20pt追尾で保護"),
    ]
    methods = []
    for mid, source, source_id, description in configs:
        original = method(data[source], source_id)
        original_rows = days(original)
        assert original_rows.keys() == base.keys()
        rows, cumulative = [], 0
        for session in sorted(base):
            rr = original_rows[session]
            risk = risk_rows[session] if mid == "D07" else (newer_s01[session]["intraday_risk"] if mid == "S01" else rr["intraday_risk"])
            assert rr["profit"] - rr["loss"] == rr["net"]
            cumulative += rr["net"]
            rows.append({
                "session": session, "kind": "Day", "direction": rr["direction"],
                "profit": rr["profit"], "loss": rr["loss"], "net": rr["net"],
                "cumulative": cumulative, "entries": rr["entries"],
                "intraday_risk": risk, "vs_d07": rr["net"] - base[session]["net"],
            })
        methods.append({"id": mid, "description": description, "source": str(SOURCES[source]),
                        "source_id": source_id, "config": original.get("config"), "rows": rows,
                        "summary": summary(rows)})
    for m in methods:
        m["summary"]["vs_d07"] = m["summary"]["net"] - methods[0]["summary"]["net"]
    out = {
        "created_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "definition": {"financial_replays": 0, "API_calls": 0, "scope": "保存済み同一26完了Dayのみ。Nightと10/27途中を除く。",
                       "account": "完結親の全返済純額を正負分類。上位3除外は手法ごとの黒字上位3場。",
                       "product": "日経mini片側10枚相当。数量配分案はmicro片側100枚相当。", "fees": 0,
                       "fill": "判断後の次正常ラージBBO。買Ask・売Bid。", "D07": "00154の現行Go模型。旧00145の保存模型とは区別。",
                       "risk": "全正常ラージ原行、約定前・同原行の各約定後、初期0、全実玉を返済側評価。",
                       "evidence": "保存結果の再集計・同値確認。新たな有効性の証拠や未見テストではない。"},
        "methods": methods,
        "audit": {"bridges": bridge_checks, "scene_identity": {"passed": True, "sessions": 26, "fingerprinted_files": 156,
                    "input154_sha256": sha(input154), "input156_sha256": sha(input156)},
                  "D07_risk_source": str(risk_path), "D07_risk_sha256": sha(risk_path),
                  "source_sha256": {str(SOURCES[k]): v for k, v in source_hashes.items()}},
    }
    assert all(source_hashes[k] == sha(p) for k, p in SOURCES.items())
    HERE.mkdir(exist_ok=True)
    (HERE / "report158.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "methods": len(methods), "sessions_each": 26,
                      "financial_replays": 0, "source_unchanged": True,
                      "summary": [{"id": m["id"], **m["summary"]} for m in methods]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
