"""固定した72候補の全保存場について、選択前の構造・会計・品質を監査します。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


OWN_DIR = Path(__file__).resolve().parent
ROOT = OWN_DIR.parent.parent
STUDY = ROOT / "アルゴリズム調査" / "00170_複数時間足のテクニカルと指標出口"
EXPECTED_CONFIGS = 72
EXPECTED_FILES = 114
TOLERANCE = 0.00001
NS_SECOND = 1_000_000_000


class Audit:
    """
    失敗総数と小容量の失敗見本だけを保持する監査器です。
    """

    def __init__(self) -> None:
        """
        機能: 検査数と失敗記録を初期化します。
        引数: なし。
        返り値: None。
        """
        self.checks = 0
        self.failures = 0
        self.examples: list[str] = []

    def check(self, condition: bool, label: str) -> None:
        """
        機能: 条件を検査し、失敗見本を最大40件だけ記録します。
        引数: condition は bool 型、label は str 型の検査名です。
        返り値: None。
        """
        self.checks += 1
        if not condition:
            self.failures += 1
            if len(self.examples) < 40:
                self.examples.append(label)

    def number(self, value: object, label: str, integer: bool = False) -> float | int:
        """
        機能: 欠測・真偽値・非有限値を実際の0と区別して拒否します。
        引数: value は object 型、label は str 型、integer は bool 型です。
        返り値: float または int 型の検証済み数値。異常時は例外を送出します。
        """
        valid = not isinstance(value, bool) and isinstance(value, (int, float))
        valid = valid and math.isfinite(value)
        valid = valid and (not integer or isinstance(value, int))
        self.check(valid, f"数値欠測又は型不正: {label}")
        if not valid:
            raise ValueError(f"数値欠測又は型不正: {label}")
        return value

    def near(self, actual: float, expected: float, label: str) -> None:
        """
        機能: 会計の丸め誤差だけを許容して数値を照合します。
        引数: actual と expected は float 型、label は str 型です。
        返り値: None。
        """
        self.check(abs(actual - expected) <= TOLERANCE, f"会計不一致: {label}")


def load_json(path: Path) -> tuple[dict, str]:
    """
    機能: 一度読み取ったJSON本文と同じ本文のSHA256を取得します。
    引数: path は Path 型の入力ファイルです。
    返り値: tuple[dict, str] 型のJSON辞書とSHA256です。
    """
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSONの根が辞書ではありません: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def scene_key(row: dict) -> tuple[str, str]:
    """
    機能: 銘柄と予定場名の一意キーを作ります。
    引数: row は dict 型の入力行です。
    返り値: tuple[str, str] 型の銘柄と場名です。
    """
    return row["symbol"], row["session"]


def normalized_path(value: str) -> str:
    """
    機能: Windowsの区切りと大文字小文字を正規化して原板パスを比較します。
    引数: value は str 型のパスです。
    返り値: str 型の比較用パスです。原板の内容は読みません。
    """
    return os.path.normcase(os.path.normpath(value))


def audit_session(a: dict, manifest: dict, checker: Audit) -> dict:
    """
    機能: 原行監査と凍結目録の対応を検査し、品質の記述統計を作ります。
    引数: a と manifest は dict 型、checker は Audit 型です。
    返り値: dict 型の1場分の品質情報です。品質を収支による採否へ使いません。
    """
    label = "/".join(scene_key(a))
    counters = (
        "rows", "bytes", "invalid_json_rows", "missing_clock_rows", "invalid_clock_rows",
        "outside_rows", "in_session_rows", "duplicate_clock_rows", "reversed_clock_rows",
        "null_volume_rows", "null_volume_time_rows", "missing_last_rows", "normal_quote_rows",
        "locked_quote_rows", "crossed_quote_rows", "missing_quote_rows", "reversed_name_matches",
    )
    for field in counters:
        checker.check(checker.number(a.get(field), f"{label}/{field}", True) >= 0, f"負の原行件数: {label}/{field}")
    checker.check(normalized_path(a["path"]) == normalized_path(manifest["path"]), f"原板パス不一致: {label}")
    checker.check(a["bytes"] == manifest["bytes"], f"原板サイズ不一致: {label}")
    digest = a.get("sha256", "")
    checker.check(isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), f"原板SHA256不正: {label}")
    checker.check(isinstance(a.get("complete"), bool), f"終端確認の真偽値不正: {label}")
    checker.check(a["rows"] == sum(a[f] for f in ("invalid_json_rows", "missing_clock_rows", "invalid_clock_rows", "outside_rows", "in_session_rows")), f"全原行内訳不一致: {label}")
    checker.check(a["in_session_rows"] == sum(a[f] for f in ("normal_quote_rows", "locked_quote_rows", "crossed_quote_rows", "missing_quote_rows")), f"気配内訳不一致: {label}")
    for field in ("null_volume_rows", "null_volume_time_rows"):
        checker.check(a[field] <= a["rows"], f"全原行超過: {label}/{field}")
    start = checker.number(a.get("start_ns"), f"{label}/start_ns", True)
    end = checker.number(a.get("end_ns"), f"{label}/end_ns", True)
    checker.check(start < end, f"予定境界不正: {label}")
    for field in ("first_time_ns", "last_time_ns"):
        clock = checker.number(a.get(field), f"{label}/{field}", True)
        checker.check(clock == 0 or start <= clock <= end, f"場外の観測時計: {label}/{field}")
    close_line = checker.number(a.get("close_proxy_line"), f"{label}/close_proxy_line", True)
    checker.check(a["complete"] == (close_line > 0), f"終端Last判定不一致: {label}")
    checker.check(0 <= close_line <= a["rows"], f"終端Last原行不正: {label}")
    if close_line:
        checker.check(end - 360 * NS_SECOND <= a["close_proxy_time_ns"] <= end and a["close_proxy_price"] > 0, f"終端Lastの時計又は価格不正: {label}")
    quote_line = checker.number(a.get("close_quote_line"), f"{label}/close_quote_line", True)
    checker.check(0 <= quote_line <= a["rows"], f"終端正常気配原行不正: {label}")
    if quote_line:
        checker.check(end - 360 * NS_SECOND <= a["close_quote_time_ns"] <= end and 0 < a["close_quote_bid"] < a["close_quote_ask"], f"終端正常気配不正: {label}")
    gap = checker.number(a.get("maximum_clock_gap_seconds"), f"{label}/最大価格時計間隔")
    checker.check(gap >= 0, f"負の価格時計間隔: {label}")
    delay = max(0, (a["first_time_ns"] - start) / NS_SECOND) if a["first_time_ns"] else None
    return {
        "symbol": a["symbol"], "session": a["session"], "終端確認": a["complete"],
        "原行数": a["rows"], "場内原行数": a["in_session_rows"], "開始観測遅延秒": delay,
        "最大価格時計間隔秒": gap, "同時計行": a["duplicate_clock_rows"], "逆時計行": a["reversed_clock_rows"],
        "価格時計欠測行": a["missing_clock_rows"], "出来高欠測行": a["null_volume_rows"],
        "出来高時計欠測行": a["null_volume_time_rows"], "異常JSON行": a["invalid_json_rows"],
        "同値気配行": a["locked_quote_rows"], "交差気配行": a["crossed_quote_rows"],
        "気配欠測行": a["missing_quote_rows"], "終端正常気配なし": a["complete"] and quote_line == 0,
    }


def audit_result(row: dict, audit: dict, checker: Audit) -> None:
    """
    機能: 候補1件1場のID、固定数量、全玉会計、終端確認場の残玉を検査します。
    引数: row と audit は dict 型、checker は Audit 型です。
    返り値: None。未完場の含みを健全な0へ置き換えません。
    """
    label = f"{row['config_id']}/{row['symbol']}/{row['session']}"
    checker.check(row["method_id"] == f"{row['symbol']}_T170_{row['config_id']}", f"実手法ID不一致: {label}")
    for field in ("complete", "unfilled_at_end", "proxy_close"):
        checker.check(isinstance(row.get(field), bool), f"真偽値不正: {label}/{field}")
    checker.check(row["complete"] == audit["complete"], f"監査と結果の終端確認不一致: {label}")
    money = ("gross_profit_yen", "gross_loss_yen", "realized_yen", "unrealized_yen", "final_equity_yen", "long_profit_yen", "long_loss_yen", "short_profit_yen", "short_loss_yen", "min_equity_yen", "max_drawdown_yen", "total_episode_hold_seconds")
    for field in money:
        checker.number(row.get(field), f"{label}/{field}")
    for field in ("gross_profit_yen", "gross_loss_yen", "long_profit_yen", "long_loss_yen", "short_profit_yen", "short_loss_yen", "max_drawdown_yen", "total_episode_hold_seconds"):
        checker.check(row[field] >= 0, f"負にできない項目が負数: {label}/{field}")
    checker.check(row["min_equity_yen"] <= TOLERANCE, f"初期0を含む最小時価が正数: {label}")
    for field in ("episodes", "wins", "losses", "fills", "entry_count", "new_qty", "closed_qty", "long_episodes", "short_episodes", "positive_then_negative", "initial_negative", "recovered_positive"):
        checker.check(checker.number(row.get(field), f"{label}/{field}", True) >= 0, f"負の回数又は枚数: {label}/{field}")
    position = row.get("final_position")
    if not isinstance(position, dict):
        raise ValueError(f"最終保有がありません: {label}")
    qty = checker.number(position.get("Qty", position.get("qty")), f"{label}/最終枚数", True)
    side = checker.number(position.get("Side", position.get("side")), f"{label}/最終方向", True)
    checker.check(qty in (0, 10) and side in (-1, 0, 1) and (qty == 0) == (side == 0), f"固定10枚・片方向保有違反: {label}")
    checker.check(row["new_qty"] == row["entry_count"] * 10 and row["closed_qty"] % 10 == 0, f"固定10枚の新規返済数量不一致: {label}")
    checker.check(row["new_qty"] - row["closed_qty"] == qty, f"新規返済数量と残玉不一致: {label}")
    checker.check(row["entry_count"] == row["episodes"] + (1 if qty else 0), f"新規と閉鎖エピソード数不一致: {label}")
    checker.check(row["fills"] == row["entry_count"] + row["closed_qty"] // 10, f"新規返済約定片数不一致: {label}")
    checker.check(row["long_episodes"] + row["short_episodes"] == row["episodes"], f"買売エピソード数不一致: {label}")
    checker.check(row["wins"] + row["losses"] <= row["episodes"], f"勝敗数超過: {label}")
    checker.check(row["recovered_positive"] <= row["initial_negative"] <= row["episodes"] and row["positive_then_negative"] <= row["episodes"], f"正益診断件数超過: {label}")
    checker.near(row["gross_profit_yen"] - row["gross_loss_yen"], row["realized_yen"], f"{label}/利益−損失")
    checker.near(row["realized_yen"] + row["unrealized_yen"], row["final_equity_yen"], f"{label}/確定＋全残玉含み")
    checker.near(row["long_profit_yen"] + row["short_profit_yen"], row["gross_profit_yen"], f"{label}/買売利益内訳")
    checker.near(row["long_loss_yen"] + row["short_loss_yen"], row["gross_loss_yen"], f"{label}/買売損失内訳")
    if row["complete"]:
        checker.check(qty == 0, f"終端確認場に未返済玉: {label}")
        checker.near(row["unrealized_yen"], 0, f"{label}/終端確認場の含み")
    if row["proxy_close"]:
        checker.check(row["complete"] and audit["close_quote_line"] > 0 and row["closed_qty"] >= 10, f"最終正常気配代理の条件不一致: {label}")
    first_ns = checker.number(row.get("first_entry_time_ns"), f"{label}/初回新規時計", True)
    first_line = checker.number(row.get("first_entry_line"), f"{label}/初回新規原行", True)
    if row["entry_count"]:
        checker.check(audit["start_ns"] <= first_ns <= audit["end_ns"] and 1 <= first_line <= audit["rows"], f"初回新規の時計又は原行不正: {label}")
    else:
        checker.check(first_ns == 0 and first_line == 0, f"無新規場に初回新規記録: {label}")


def inspect(source: dict, manifest: dict, plan: dict, manifest_sha: str, checker: Audit) -> dict:
    """
    機能: 凍結目録と全72候補の直積を照合し、小容量の根拠を集約します。
    引数: source、manifest、plan は dict 型、manifest_sha は str 型、checker は Audit 型です。
    返り値: dict 型の構造・品質集計です。候補の選択や順位変更は行いません。
    """
    for field in ("results", "configs", "audits"):
        if not isinstance(source.get(field), list):
            raise ValueError(f"結果JSONに配列がありません: {field}")
    files = manifest["files"]
    configs = source["configs"]
    audits = source["audits"]
    rows = source["results"]
    ids = [c["id"] for c in configs]
    checker.check(len(ids) == EXPECTED_CONFIGS and len(set(ids)) == EXPECTED_CONFIGS, "重複のない72候補ではありません")
    checker.check(len(files) == EXPECTED_FILES, "凍結原板が114件ではありません")
    checker.check(manifest_sha == plan["manifest_sha256"], "目録SHA256が凍結計画と不一致")
    frozen_configs = plan["spec"]["entry"]["candidates"]
    checker.check({c["id"]: c for c in configs} == {c["id"]: c for c in frozen_configs}, "候補定義が凍結計画と不一致")
    file_map = {scene_key(a): a for a in files}
    audit_map = {scene_key(a): a for a in audits}
    checker.check(len(file_map) == len(files), "目録に同じ場の重複があります")
    checker.check(len(audit_map) == len(audits), "原板監査に同じ場の重複があります")
    checker.check(set(file_map) == set(audit_map), "監査と目録の銘柄・場集合が不一致")
    checker.check({key[0] for key in file_map} == {"NK225", "TOPIX"}, "目録銘柄が日経・TOPIXの2種ではありません")
    quality = [audit_session(audit_map[k], file_map[k], checker) for k in sorted(set(file_map) & set(audit_map))]
    expected = {(candidate, symbol, session) for candidate in ids for symbol, session in file_map}
    actual = [(r["config_id"], r["symbol"], r["session"]) for r in rows]
    checker.check(len(actual) == EXPECTED_CONFIGS * EXPECTED_FILES, "結果件数が72×114=8208件ではありません")
    checker.check(len(set(actual)) == len(actual), "候補・銘柄・場の結果が重複しています")
    checker.check(set(actual) == expected, "全72候補×全114場の直積が不一致")
    groups: dict[str, Counter] = {}
    for row in rows:
        k = scene_key(row)
        if k not in audit_map:
            continue
        audit_result(row, audit_map[k], checker)
        group = f"{row['symbol']}/{row['session'].rsplit('_', 1)[-1]}"
        counts = groups.setdefault(group, Counter())
        counts["結果件数"] += 1
        counts["終端確認場結果数" if row["complete"] else "未完場結果数"] += 1
        counts["最終未約定判断数"] += int(row["unfilled_at_end"])
        counts["最終正常気配代理数"] += int(row["proxy_close"])
        counts["未完保有あり結果数"] += int(not row["complete"] and row["final_position"].get("Qty", row["final_position"].get("qty", 0)) > 0)
    return {
        "候補数": len(ids), "凍結原板数": len(files), "監査場数": len(audits), "結果件数": len(rows),
        "終端確認場数": sum(bool(a["complete"]) for a in audits),
        "未完場": ["/".join(scene_key(a)) for a in audits if not a["complete"]],
        "昼夜別件数": {k: dict(v) for k, v in sorted(groups.items())},
        "品質概況": {
            "開始観測が60秒超遅い場数": sum(q["開始観測遅延秒"] is not None and q["開始観測遅延秒"] > 60 for q in quality),
            "開始観測が6分超遅い場数": sum(q["開始観測遅延秒"] is not None and q["開始観測遅延秒"] > 360 for q in quality),
            "価格時計間隔60秒超の場数": sum(q["最大価格時計間隔秒"] > 60 for q in quality),
            "逆時計を含む場数": sum(q["逆時計行"] > 0 for q in quality),
            "出来高時計欠測を含む場数": sum(q["出来高時計欠測行"] > 0 for q in quality),
            "異常JSON総行数": sum(q["異常JSON行"] for q in quality),
        },
        "場別品質": quality,
    }


def main() -> int:
    """
    機能: 実結果を監査し、選択前の根拠を結果監査JSONへ保存します。
    引数: なし。CLIで入力・目録・凍結計画・保存先の Path 型指定を受け取ります。
    返り値: int 型の終了状態。成功0、失敗1です。金融シミュレーションは実行しません。
    """
    parser = argparse.ArgumentParser(description="固定候補の構造・会計・原板品質だけを監査します。")
    parser.add_argument("--input", type=Path, default=OWN_DIR / "summary.json")
    parser.add_argument("--manifest", type=Path, default=STUDY / "入力目録.json")
    parser.add_argument("--plan", type=Path, default=STUDY / "計画.json")
    parser.add_argument("--output", type=Path, default=STUDY / "結果監査.json")
    args = parser.parse_args()
    checker = Audit()
    evidence: dict = {
        "監査日時": datetime.now().astimezone().isoformat(),
        "方針": "構造・会計・品質だけを検査。損益に応じた候補変更・再選択・金融再実行はしない。",
        "判定範囲": "終端確認は終了前6分の有効Last観測。開始・中間の欠測は別品質として記録。約定片の原行照合は詳細資料で別途行う。",
        "時計の限界": "CurrentPriceTimeは価格時計であり受信時計ではない。同時計反復は原行順を保持し、最大間隔は価格時計の観測差である。",
        "固定数量の前提": "72候補は新規・返済とも10枚全量。未完場の全残玉と含みは保持し、閉鎖場ランキングへ加算しない。",
    }
    try:
        source, source_sha = load_json(args.input)
        manifest, manifest_sha = load_json(args.manifest)
        plan, plan_sha = load_json(args.plan)
        evidence["入力指紋"] = {"集計": source_sha, "目録": manifest_sha, "計画": plan_sha}
        evidence["試行ID"] = plan["trial_id"]
        evidence.update(inspect(source, manifest, plan, manifest_sha, checker))
    except (OSError, ValueError, KeyError, TypeError) as error:
        checker.check(False, f"監査を継続できません: {error}")
    evidence.update(判定="合格" if checker.failures == 0 else "不合格", 検査数=checker.checks, 不一致数=checker.failures, 不一致見本=checker.examples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"保存先": str(args.output), "判定": evidence["判定"], "検査数": checker.checks, "不一致数": checker.failures}, ensure_ascii=False))
    return 0 if checker.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
