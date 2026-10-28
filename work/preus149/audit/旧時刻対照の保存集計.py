"""00128の保存会計だけを再集計し、時刻対照の出典と設定差を保存する。"""

from pathlib import Path
import hashlib
import json


def main():
    """保存会計を集計する。

    引数: なし。
    返り値: None。出典指紋・設定差・集計を同じ監査フォルダへ保存する。
    金融再生・価格原データの読取り・外部通信は行わない。
    """
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    source = root / "work/daynight128_20261020/round1"
    plan_path = source / "固定計画.json"
    rows_path = source / "全条件の会計.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows = json.loads(rows_path.read_text(encoding="utf-8"))["rows"]
    configs = {c["id"]: c for c in plan["configs"]}
    result = {
        "新金融再生数": 0,
        "会計": "当時の枚数・片道手数料込み。日経マイクロ10枚、TOPIXミニ5枚。",
        "比較範囲": "既知21夜。異なる将来の独立21夜ではない。",
        "出典": [
            {"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (plan_path, rows_path, source.parent / "night128.py", source.parent / "build_round2.py")
        ],
        "設定差": [],
        "保存会計集計": [],
    }

    # ----------------------------------------
    # IDと説明以外は時間phaseだけが異なることを検査する。
    for all_night, after_us in (("N03", "N10"), ("N05", "N11")):
        a, b = configs[all_night], configs[after_us]
        changes = {
            k: [a.get(k), b.get(k)]
            for k in sorted(set(a) | set(b))
            if a.get(k) != b.get(k) and k not in ("id", "name")
        }
        assert changes == {"phase": [0, 1]}, changes
        result["設定差"].append({"全夜": all_night, "米国後限定": after_us, "差": changes})

    # ----------------------------------------
    # 約定列を再生せず、保存された場別収支と参加数を合算する。
    for method in ("N03", "N10", "N05", "N11", "N12"):
        for symbol in ("NK225", "TOPIX"):
            selected = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
            assert len(selected) == 21
            result["保存会計集計"].append({
                "手法": method,
                "商品": symbol,
                "場数": len(selected),
                "利益": round(sum(r["profit"] for r in selected), 2),
                "損失": round(sum(r["loss"] for r in selected), 2),
                "収支": round(sum(r["net"] for r in selected), 2),
                "赤字場": sum(r["net"] < 0 for r in selected),
                "新規回数": sum(r["entries"] for r in selected),
                "場別保存値": selected,
            })
    target = here / "旧時刻対照の保存集計.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("保存会計10組を検査。金融再生0回。")


if __name__ == "__main__":
    main()
