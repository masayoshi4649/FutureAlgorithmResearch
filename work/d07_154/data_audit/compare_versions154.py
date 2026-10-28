"""旧145と現Go D07の保存会計・共通原行だけを照合する。売買再生なし。"""

from __future__ import annotations

import json
import pickle
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "work/d07_154"
OUT = WORK / "data_audit"
OWNERS = {"基本CG": "core", "追加担当A": "addon", "別入口CS": "episode"}


def read(path: Path) -> dict:
    """小型の保存JSONを読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def at(value: float) -> str:
    """UNIX秒を日本時間へ直す。

    引数: value(float)。返り値: str。
    """
    return datetime.fromtimestamp(value, timezone(timedelta(hours=9))).isoformat()


def main() -> None:
    """50保存場について、担当別差と原行の一致・追加異常行を確認する。

    引数: なし。返り値: None。金融判断や注文は新しく作らない。
    """
    old = read(OUT / "保存D07の利益返しと追加玉154.json")
    report = read(WORK / "report154.json")
    manifest = read(WORK / "inputs154.json")
    scenes = {s["session"]: s for s in manifest["sessions"]}
    per_scene, detail = [], []
    focus = {"2026-10-20_Night", "2026-10-06_Day", "2026-10-01_Day"}
    for old_row in report["old145_comparison"]["rows"]:
        scene = old_row["session"]
        prior = [p for p in old["parents"] if p["session"] == scene]
        current = read(OUT / "cases" / scene / "D07.json")
        source = read(WORK / "results_go" / f"{scene}_D07.json")
        source = next(c for c in source["cases"] if c["config"]["id"] == "D07")
        with (ROOT / "work/research145_engine/cache" / f"{scene}.pkl").open("rb") as stream:
            _, data, _, _, _ = pickle.load(stream)
        ready, quotes = data["ready"], data["quotes"]
        with np.load(OUT / "quote_cache" / f"{scene}.npz") as packed:
            q = {k: packed[k] for k in packed.files}
        old_lines = np.asarray(ready["seq"], dtype=np.int64) + 1
        indices = np.searchsorted(q["line"], old_lines)
        assert np.all(indices < len(q["line"])) and np.array_equal(q["line"][indices], old_lines)
        errors = {}
        for label, old_values, current_values in (("時計", ready["time_s"], q["time"][indices]),
                ("Last", ready["last"], q["last"][indices]), ("bid", quotes["bid"], q["bid"][indices]),
                ("ask", quotes["ask"], q["ask"][indices])):
            errors[label] = float(np.max(np.abs(np.asarray(old_values) - current_values)))
            assert errors[label] < 0.00001
        added = ~np.isin(q["line"], old_lines)
        added_normal = int(np.count_nonzero(added & q["valid"]))
        extra_normal_indices = np.flatnonzero(added & q["valid"])
        last_fill_time = max((e["fill"]["Time"] for e in source.get("events") or []), default=scenes[scene]["start"])
        features_equal = checked = 0
        feature_differences = []
        for sid, observation in (source.get("decision_evidence") or {}).items():
            index = observation["Index"]
            raw_line = int(q["line"][index])
            pos = np.searchsorted(old_lines, raw_line)
            if pos == len(old_lines) or old_lines[pos] != raw_line:
                continue
            values = np.array(observation["Research"]["Values"], float)
            known = np.array(observation["Research"]["Known"], bool)
            values[~known] = np.nan
            old_values = np.asarray(data["features"])[pos, :30]
            both = np.isfinite(old_values) & np.isfinite(values)
            diff = np.isfinite(old_values) != np.isfinite(values)
            diff[both] |= np.abs(old_values[both] - values[both]) > 1e-7
            checked += 1
            features_equal += not diff[:24].any()
            if diff[:24].any():
                feature_differences.append({"signal": sid, "raw_line": raw_line, "time": at(observation["Time"]),
                    "columns": [int(k) for k in np.flatnonzero(diff[:24])],
                    "old": [float(v) if np.isfinite(v) else None for v in old_values[:24]],
                    "current": [float(v) if np.isfinite(v) else None for v in values[:24]]})
        by_owner = {}
        for old_owner, owner in OWNERS.items():
            op, np_ = [p for p in prior if p["owner"] == old_owner], [p for p in current["parents"] if p["owner"] == owner]
            old_orders = sorted([(e["decision_raw_line"], e["fill_raw_line"], e["side"], e["quantity"], e["price"], e["new"])
                                 for p in op for e in p["orders"]])
            new_orders = sorted([(e["decision"]["raw_line"], e["fill"]["raw_line"], e["side"], e["quantity"], e["price"], e["action"] == "new")
                                 for p in np_ for e in p["events"]])
            by_owner[owner] = {"old_net": sum(p["net"] for p in op), "new_net": sum(p["net"] for p in np_),
                               "old_parents": len(op), "new_parents": len(np_), "orders_identical": old_orders == new_orders}
            by_owner[owner]["difference"] = by_owner[owner]["new_net"] - by_owner[owner]["old_net"]
        row = {**old_row, "kind": scenes[scene]["kind"], "owners": by_owner, "old_rows": len(old_lines), "current_rows": len(q["line"]),
               "added_rows": int(added.sum()), "added_normal_rows": added_normal, "added_abnormal_rows": int(np.count_nonzero(added & ~q["valid"])),
               "added_normal_times": sorted({at(q["time"][i]) for i in extra_normal_indices}),
               "added_normal_all_after_final_fill": bool(np.all(q["time"][extra_normal_indices] > last_fill_time)),
               "common_price_max_difference": errors, "old_force_close": at(ready["limit"]), "current_force_close": at(scenes[scene]["force_close"]),
               "force_close_identical": ready["limit"] == scenes[scene]["force_close"],
               "decision_feature24_checked": checked, "decision_feature24_identical": int(features_equal), "feature_differences": feature_differences}
        per_scene.append(row)
        if scene in focus:
            olds = [{"owner": OWNERS[p["owner"]], "side": p["side"], "quantity": p["initial_quantity"], "net": p["net"],
                     "entry": p["entry"], "exit": p["exit"]} for p in prior]
            news = [{k: p[k] for k in ("owner", "side", "initial_quantity", "net", "entry", "decision", "exit")} for p in current["parents"]]
            windows = []
            for p in olds:
                raw_line = p["entry"]["decision_raw_line"]
                if any(n["owner"] == p["owner"] and n["side"] == p["side"] and n["decision"]["raw_line"] == raw_line for n in news):
                    continue
                index = int(np.searchsorted(q["line"], raw_line))
                before = np.flatnonzero(added & ~q["valid"] & (q["time"] >= q["time"][index] - 600) & (q["time"] <= q["time"][index]))
                windows.append({"old_only_entry": p, "preceding_10min_abnormal_quotes": [{"raw_line": int(q["line"][i]),
                    "time": at(q["time"][i]), "bid": float(q["bid"][i]), "ask": float(q["ask"][i])} for i in before]})
            detail.append({"session": scene, "row": row, "old_parents": olds, "current_parents": news, "old_only_entry_windows": windows})
    result = {"financial_replays": 0, "sessions": len(per_scene), "rows": per_scene, "focus": detail,
        "all_common_raw_prices_identical": True,
        "all_force_close_identical": all(r["force_close_identical"] for r in per_scene),
        "all_added_rows_abnormal": all(r["added_normal_rows"] == 0 for r in per_scene),
        "added_abnormal_rows": sum(r["added_abnormal_rows"] for r in per_scene),
        "added_normal_rows": sum(r["added_normal_rows"] for r in per_scene),
        "added_normal_all_after_final_fill": all(r["added_normal_all_after_final_fill"] for r in per_scene),
        "decision_feature24_checked": sum(r["decision_feature24_checked"] for r in per_scene),
        "decision_feature24_identical": sum(r["decision_feature24_identical"] for r in per_scene),
        "owner_totals": {o: {"old_net": sum(r["owners"][o]["old_net"] for r in per_scene),
                             "new_net": sum(r["owners"][o]["new_net"] for r in per_scene),
                             "difference": sum(r["owners"][o]["difference"] for r in per_scene),
                             "identical_order_sessions": sum(r["owners"][o]["orders_identical"] for r in per_scene)}
                         for o in OWNERS.values()},
        "limits": "共通原行の価格と現Goの実判断行の24特徴だけを照合。旧モデルにしかない準備と全状態遷移を金融再生し直してはいない。差額を異常板だけに一意配賦しない。"}
    (OUT / "旧145と現Goの差の再照合154.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("sessions", "all_force_close_identical", "all_added_rows_abnormal", "added_abnormal_rows",
          "decision_feature24_checked", "decision_feature24_identical", "owner_totals")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
