"""研究151の保存資料をメタデータだけで整理する。原板・足・売買経路は再生しない。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT.parent / "JP_OSE_Data"
JST = timezone(timedelta(hours=9))


def read_json(path: Path) -> dict:
    """既存の目録・証跡だけを読み取る。

    引数: path(Path)はJSON目録。
    返り値: dictは保存されたメタデータ。原板・足・会計結果本文には使用しない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def absolute(path: str) -> Path:
    """目録内の相対パスを作業ルートへ解決する。

    引数: path(str)は保存先。
    返り値: Pathは絶対パス。
    """
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def identity(path: Path) -> str:
    """Windows上の同一パスを照合するためのキーを作る。

    引数: path(Path)はファイル。
    返り値: strは大文字小文字を正規化した絶対パス。
    """
    return os.path.normcase(str(path.resolve()))


def metadata(path: Path) -> dict:
    """内容を読まずファイルの存在・サイズ・更新時刻を取得する。

    引数: path(Path)は確認対象。
    返り値: dictはファイルのメタデータ。
    """
    result = {"path": path.resolve().as_posix(), "exists": path.is_file()}
    if result["exists"]:
        stat = path.stat()
        result.update(bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return result


def compare_metadata(path: Path, before: dict) -> dict:
    """以前のサイズ・更新時刻と比較する。内容一致を新たに証明しない。

    引数: path(Path)は現在資料、before(dict)は以前の目録行。
    返り値: dictは比較結果と旧内容指紋。
    """
    current = metadata(path)
    old_bytes = before.get("bytes", before.get("current_bytes"))
    old_mtime = before.get("mtime_ns", before.get("current_mtime_ns"))
    current.update(prior_bytes=old_bytes, prior_mtime_ns=old_mtime,
                   prior_sha256=before.get("sha256", before.get("prior_sha256")),
                   metadata_unchanged=current.get("bytes") == old_bytes and current.get("mtime_ns") == old_mtime,
                   raw_content_read=False)
    return current


def fingerprint_small(path: Path) -> dict:
    """小さな目録又は既存集計の内容指紋を取得する。

    引数: path(Path)は目録・完了集計。原板や足には使用しない。
    返り値: dictは存在情報とSHA256。
    """
    result = metadata(path)
    if result["exists"]:
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> None:
    """保存セッション・既登録入力・再利用候補を整理してJSONへ保存する。

    引数: なし。
    返り値: None。原資料・台帳・既存目録は変更しない。
    """
    manifest_path = ROOT / "work/preus149/data/原資料一覧149.json"
    old_manifest = read_json(manifest_path)
    reuse150_path = ROOT / "work/preus150/data/149原資料の再利用前照合150.json"
    reuse150 = read_json(reuse150_path)
    previous = {identity(absolute(row["path"])): row for row in reuse150["records"]}
    input145_path = ROOT / "work/research145_roles/保存入力145.json"
    input145 = read_json(input145_path)
    scan145_path = absolute(input145["source_inventory"]["path"])
    scan145 = read_json(scan145_path)
    old145 = {identity(absolute(row["path"])): row for row in scan145["files"]}

    # ----------------------------------------
    # 現在保存されている先物フォルダを全列挙。ファイル本文や終端時計は新たに読まない。
    saved = []
    counts = {}
    for symbol in ("NK225", "TOPIX"):
        folders = sorted(p for p in (DATA / "future" / symbol).iterdir() if p.is_dir())
        counts[symbol] = {"all": len(folders), "Day": sum(p.name.endswith("_Day") for p in folders),
                          "Night": sum(p.name.endswith("_Night") for p in folders)}
        for folder in folders:
            row = {"symbol": symbol, "session": folder.name, "files": [], "terminal_rechecked": False}
            for name in ("book.jsonl", "candle_1min.csv", "candle_5min.csv"):
                path = folder / name
                item = metadata(path)
                prior = old145.get(identity(path))
                if prior:
                    item = compare_metadata(path, prior)
                    item["compared_to"] = "145の原資料全読照合"
                row["files"].append(item)
            row["all_three_present"] = all(f["exists"] and f["bytes"] > 0 for f in row["files"])
            saved.append(row)

    # ----------------------------------------
    # 主比較の25完了夜＋取得済み途中は、149の凍結されたScene入力をそのまま参照する。
    primary = []
    for scene in old_manifest["sessions"]:
        row = {key: scene[key] for key in ("session", "start", "us_open", "force_close", "end", "cutoff", "partial")}
        row["files"] = []
        for prior in scene["fingerprints"]:
            path = absolute(prior["path"])
            item = compare_metadata(path, previous[identity(path)])
            item["session"] = scene["session"]
            row["files"].append(item)
        primary.append(row)
    assert len(primary) == 26 and sum(not x["partial"] for x in primary) == 25
    primary_changed = [f for scene in primary for f in scene["files"] if not f["metadata_unchanged"]]

    # ----------------------------------------
    # デイ追加を別途検証する場合の既存145キャッシュと保存全注文。再生も損益集計もしない。
    days = []
    for scene in input145["sessions"]:
        if not scene["session"].endswith("_Day"):
            continue
        cache = metadata(absolute(scene["cache"]["path"]))
        cache.update(prior_sha256=scene["cache"]["sha256"], prior_bytes=scene["cache"]["bytes"],
                     size_unchanged=cache.get("bytes") == scene["cache"]["bytes"], content_reread=False)
        orders = metadata(ROOT / "work/research145_report/combined_orders" / (scene["session"] + ".npz"))
        days.append({"session": scene["session"], "cache": cache, "saved_combined_orders": orders})

    completion = read_json(ROOT / "work/preus150/試行完了証跡150.json")
    frozen_expected = {e["path"]: e for trial in completion["targets"] for e in trial["evidence"]}
    frozen = []
    for name in ("work/preus150/first_report150.json", "work/preus150/report150.json"):
        item = fingerprint_small(ROOT / name)
        item.update(prior_sha256=frozen_expected[name]["sha256"], content_matches_completed=item["sha256"] == frozen_expected[name]["sha256"],
                    financial_replay=False, parsed_for_performance=False)
        frozen.append(item)
    for name in ("work/preus150/results_go", "work/preus150/results_round2"):
        path = ROOT / name
        frozen.append({"path": path.as_posix(), "files": [metadata(p) for p in sorted(path.glob("*.json"))],
                       "financial_replay": False, "contents_read": False})

    prior_days = {x["session"] for x in days}
    extra = sorted({r["session"] for r in saved if r["session"].endswith("_Day") and r["session"] not in prior_days})
    result = {
        "created_at": datetime.now(JST).isoformat(), "purpose": "研究151の入力範囲と保存資料再利用候補の整理",
        "API_calls": 0, "financial_replays": 0, "raw_book_or_candle_content_reads": 0, "ledger_changes": 0,
        "provenance": [fingerprint_small(manifest_path), fingerprint_small(reuse150_path), fingerprint_small(input145_path), fingerprint_small(scan145_path)],
        "saved_directory_counts": counts, "saved_sessions": saved,
        "primary_source_manifest": manifest_path.relative_to(ROOT).as_posix(),
        "primary_complete_nights": 25, "primary_known_partial": 1, "primary_sessions": primary,
        "primary_raw_files": sum(len(s["files"]) for s in primary), "primary_metadata_changed": primary_changed,
        "prior_day145_candidates": days, "extra_saved_day_candidates": extra, "frozen150_accounts": frozen,
        "limitations": [
            "サイズ・更新時刻一致は以前の全読指紋照合を再利用する根拠であり、この調査で原資料の内容一致を新たに証明したものではない。",
            "10/26デイは保存フォルダと3ファイルの存在を確認しただけで、場終端の完全性は再確認していない。主比較へ自動追加しない。",
            "10/26ナイトは取得済み21:13:52排他の既知途中資料。将来の未見資料・完了セッションとして扱わない。",
            "145キャッシュは異常BBO除外済み。149/150の現Go模型とは異常BBO行の状態解除が異なるため、旧D07の会計を現Goの同一結果と扱わない。",
            "入口・出口・両建て・枚数が変わる151では、旧注文の単純差替えや損失削除で成績を合成できない。完全に同じ戦略・入力の比較対照だけ保存会計を再利用する。",
            "今回の担当作業は資料調査のみ。新金融再生や試行登録は行わない。",
        ],
    }
    (HERE / "保存資料の一覧と再利用151.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"saved": counts, "primary_files": result["primary_raw_files"], "changed_primary_metadata": len(primary_changed),
                      "day145_candidates": len(days), "extra_days": extra,
                      "frozen150_reports_unchanged": all(x.get("content_matches_completed", True) for x in frozen),
                      "financial_replays": 0, "raw_content_reads": 0}, ensure_ascii=True))


if __name__ == "__main__":
    main()
