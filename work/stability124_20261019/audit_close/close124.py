"""00124の固定源・試行終了系列・成果と案内参照を独立点検する。"""

import hashlib
import html.parser
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse


HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
ROOT = HERE.parents[2]
NAME = "00124_追加セッションと日経オプションの検証"
PUBLIC = ROOT / "アルゴリズム調査" / NAME
MANAGER = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
TRIALS = MANAGER.parent / "data/trials.json"
IDS = ("124_追加一場の凍結評価と前完了場IV固定十二条件", "124b_追加CSVの排他的終端を維持した少額E01再接続", "124c_人工と金融のキャッシュを分離した少額E01追加検証")
CHECKS = []
HASH_CACHE = {}


def read(path: Path) -> dict:
    """
    機能: 明示資料だけを UTF-8 JSON として読む。
    引数: path (Path) 読取位置。
    返り値: dict 保存資料。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    """
    機能: 市場原本を除く固定資料の SHA256 を得る。
    引数: path (Path) 固定源または成果位置。
    返り値: str 同一プロセス内で共有する SHA256。
    """
    path = path.resolve()
    assert not any(path.is_relative_to(ROOT / folder) for folder in ("book", "candle_1min", "candle_5min")), "原市場は読まない"
    if path not in HASH_CACHE:
        with path.open("rb") as handle:
            HASH_CACHE[path] = hashlib.file_digest(handle, "sha256").hexdigest()
    return HASH_CACHE[path]


def save(name: str, value: dict) -> dict:
    """
    機能: 新規監査資料だけを監査所有領域へ保存する。
    引数: name (str) 保存名、value (dict) 有限資料。
    返り値: dict 保存位置と SHA256。
    """
    path = HERE / name
    assert not path.exists()
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}


def check(condition: bool, note: str, **details: object) -> None:
    """
    機能: 独立の整合条件と詳細を記録し、不一致時は停止する。
    引数: condition (bool) 一致、note (str) 検査名、details (dict) 詳細。
    返り値: None。
    """
    CHECKS.append({"passed": bool(condition), "check": note, **details})
    assert condition, note


def reference(info: dict, label: str) -> None:
    """
    機能: 根拠位置と正式 SHA を照合する。
    引数: info (dict) path/sha256、label (str) 検査名。
    返り値: None。
    """
    path = ROOT / info["path"]
    check(path.is_file(), label + "の参照先実在", path=info["path"])
    check(digest(path) == info["sha256"], label + "の正式SHA一致", **info)


def command(deep: bool) -> dict:
    """
    機能: 試行管理の読取専用 verify を実行して全出力を保存する。
    引数: deep (bool) 指紋検証の有無。
    返り値: dict 終了コードと出力。金融再生しない。
    """
    args = [sys.executable, "-B", "-X", "utf8", str(MANAGER), "verify"]
    if deep:
        args.append("--deep")
    start = time.perf_counter()
    process = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    result = {"終了コード": process.returncode, "args": args, "seconds": time.perf_counter() - start, "stdout": process.stdout, "stderr": process.stderr, "金融再生": 0}
    save("台帳verify_" + ("deep" if deep else "通常") + "全出力.json", result)
    check(process.returncode == 0, "台帳verify " + ("deep" if deep else "通常"), 終了コード=process.returncode)
    return result


def local_links(path: Path, text: str, markdown: bool = True) -> list[dict]:
    """
    機能: 相対リンクの参照先実在を検査する。
    引数: path (Path) 文書、text (str) 内容、markdown (bool) Markdown か HTML。
    返り値: list[dict] 確認したリンク。
    """
    links = re.findall(r"\]\(([^)]+)\)", text) if markdown else re.findall(r'(?:href|src)=["\']([^"\']+)["\']', text)
    result = []
    for link in links:
        link = link.strip().strip("<>")
        parsed = urllib.parse.urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (path.parent / urllib.parse.unquote(parsed.path)).resolve()
        check(target.exists(), "案内リンクの参照先実在", source=path.relative_to(ROOT).as_posix(), link=link)
        result.append({"link": link, "target": target.relative_to(ROOT).as_posix()})
    return result


def main() -> None:
    """
    機能: 00124完成後の台帳・固定・結果・HTML・案内だけを点検する。
    引数: なし。
    返り値: None。00125、方針、公開文書、試行台帳を変更しない。
    """
    save("準備時の資料探索記録.json", {"passed": True, "探索中の不存在": "work/stability124_20261019/grid/実行開始.json", "処置": "正式入力でない想定名の探索をやめ、固定計画・実際の完成結果と実行系列を確認する。金融再生はしない。", "資料欠落とは判定しない": True})
    registry_bytes = TRIALS.read_bytes()
    registry = json.loads(registry_bytes)
    before_registry_sha = hashlib.sha256(registry_bytes).hexdigest()
    normal = command(False)
    # ----------------------------------------
    # deep が原市場を読む計画でないことをメタデータだけで事前確認する。
    groups = []
    for filename, group in (("rules.json", "rules"), ("knowledge.json", "findings"), ("studies.json", "studies")):
        groups.append(read(MANAGER.parent / "data" / filename)[group])
    groups.extend([registry["trials"], registry["repetition_audit"]])
    protected_refs = []
    for rows in groups:
        for row in rows:
            references = list(row.get("evidence", []))
            references.extend(item["source"] for item in row.get("measurements", []) if item.get("source"))
            if row.get("spec"):
                references.extend(row["spec"]["data"]["input_manifests"])
                references.extend({"path": name, "sha256": sha} for name, sha in row["spec"]["implementation"].items())
            for info in references:
                if info.get("sha256") and info["path"].replace("\\", "/").split("/")[0] in ("book", "candle_1min", "candle_5min"):
                    protected_refs.append(info["path"])
    check(not protected_refs, "全体deepの参照に元市場原本なし", 原市場指紋参照数=len(protected_refs))
    deep = command(True)
    # ----------------------------------------
    selected = {row["id"]: row for row in registry["trials"] if row["id"] in IDS}
    check(set(selected) == set(IDS), "124終了系列3試行が実在")
    summaries = []
    fixed_names = ("固定計画.json", "固定計画_E01b.json", "固定計画_E01c.json")
    proposal_names = ("試行計画.json", "試行計画_E01b.json", "試行計画_E01c.json")
    for trial_id, fixed_name, proposal_name in zip(IDS, fixed_names, proposal_names):
        fixed = read(OWNER / fixed_name)
        proposal = read(OWNER / proposal_name)
        row = selected[trial_id]
        check(proposal["id"] == row["id"] and proposal["spec"] == row["spec"], "終了時の登録specは当初計画と同一", trial=trial_id)
        check(proposal["spec"]["implementation"] == fixed["sources"], "計画と固定源の完全一致", trial=trial_id, sources=len(fixed["sources"]))
        for path, sha in fixed["sources"].items():
            check(digest(ROOT / path) == sha, "凍結源不変", trial=trial_id, path=path)
        for key, info in fixed.items():
            if isinstance(info, dict) and "path" in info and "sha256" in info:
                reference(info, "固定依存:" + key)
        if "completed_registered_sources" in row:
            check(row["completed_registered_sources"] == fixed["sources"], "終了後に登録源を差し替えていない", trial=trial_id)
        summaries.append({"id": trial_id, "status": row["status"], "replacement_trial": row.get("replacement_trial"), "completion_accounting": row["completion_accounting"], "fixed": {"path": (OWNER / fixed_name).relative_to(ROOT).as_posix(), "sha256": digest(OWNER / fixed_name)}, "proposal": {"path": (OWNER / proposal_name).relative_to(ROOT).as_posix(), "sha256": digest(OWNER / proposal_name)}})
    check(selected[IDS[0]]["replacement_trial"] == IDS[1] and selected[IDS[1]]["replacement_trial"] == IDS[2], "CSV停止から環境停止・隔離成功の系列")
    check(selected[IDS[0]]["completion_accounting"]["financial_accounts"] == 190 and selected[IDS[0]]["completion_accounting"]["e01_financial_accounts"] == 0, "初回の格子190とE01停止0を分離")
    check(selected[IDS[1]]["completion_accounting"]["financial_accounts"] == 0, "中間停止は金融0")
    check(selected[IDS[2]]["completion_accounting"]["financial_accounts"] == 2, "最終新E01だけ2会計")
    for trial_id in IDS:
        row = selected[trial_id]
        reference(row["completed_result"], "終了結果:" + trial_id)
        for info in row.get("completed_audits", []):
            reference(info, "終了独立監査:" + trial_id)
    # ----------------------------------------
    frozen_ref = read(PUBLIC / "再現用参照.json")
    for name, info in frozen_ref.items():
        if isinstance(info, dict) and "path" in info:
            reference(info, "公開再現参照:" + name)
    generation = read(OWNER / "publisher/正式表示の生成証跡.json")
    check(generation["passed"], "独立監査後の表示生成が成功")
    reference(generation["report"], "正式HTML")
    for info in generation["sources"]:
        reference(info, "表示生成の固定入力")
    check(digest(OWNER / "publisher/render124.py") == generation["renderer_sha256"], "表示源不変")
    html_path = ROOT / generation["report"]["path"]
    html_sha = digest(html_path)
    closed = read(OWNER / "案内と法則別知見及び試行終了.json")
    visual = read(OWNER / "visual/実描画確認.json")
    check(closed["passed"] and closed["report_sha256"] == html_sha and closed["financial_replay"] == 0, "終了記録のHTMLと金融0一致")
    check(visual["passed"] and visual["root_viewed"] and visual["html_sha256"] == html_sha, "実描画と正式HTMLのSHA一致")
    # ----------------------------------------
    links = []
    for path in (PUBLIC / "README.md", OWNER / "README.md"):
        links.append({"source": path.relative_to(ROOT).as_posix(), "links": local_links(path, path.read_text(encoding="utf-8"))})
    for path in (ROOT / "README.md", ROOT / "アルゴリズム調査/README.md"):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"<!--00124案内-->(.*?)<!--00124案内終了-->", text, re.S)
        check(match is not None, "00124のREADME入口が存在", path=path.relative_to(ROOT).as_posix())
        links.append({"source": path.relative_to(ROOT).as_posix(), "links": local_links(path, match.group(1))})
    index_path = ROOT / "アルゴリズム調査/index.html"
    index_text = index_path.read_text(encoding="utf-8")
    match = re.search(r"<!--00124開始-->(.*?)<!--00124終了-->", index_text, re.S)
    check(match is not None, "00124の目次入口が存在")
    links.append({"source": index_path.relative_to(ROOT).as_posix(), "links": local_links(index_path, match.group(1), markdown=False)})
    links.append({"source": html_path.relative_to(ROOT).as_posix(), "links": local_links(html_path, html_path.read_text(encoding="utf-8"), markdown=False)})
    check(hashlib.sha256(TRIALS.read_bytes()).hexdigest() == before_registry_sha, "監査中に台帳不変・書換0")
    final = {"passed": True, "全合格": True, "checks": len(CHECKS), "台帳verify通常": json.loads(normal["stdout"]), "台帳verifyDeep": json.loads(deep["stdout"]), "終了系列": summaries, "report_sha256": html_sha, "参照先": links, "検査詳細": CHECKS, "source_sha256": digest(Path(__file__)), "financial_replay": 0, "original_market_reads": 0, "old_financial_cache_reads": 0, "API": 0, "実注文": 0, "変更": "audit_close配下の新規監査資料だけ。00125・方針・root文書・試行正本は無変更。", "限界": "保存資料と正式指紋・終了系列の整合性監査。金融ルールや市場を再生した新しい有効性証拠ではない。"}
    print(json.dumps(save("最終整合性.json", final), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        save("途中失敗.json", {"passed": False, "型": type(exc).__name__, "理由": str(exc), "checks": CHECKS, "金融再生": 0, "原市場": 0})
        raise
