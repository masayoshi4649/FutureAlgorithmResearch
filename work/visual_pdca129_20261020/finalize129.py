"""九巡の実施証拠と、未達の安定性を試行台帳へ接続する。"""

import hashlib
import json
import subprocess
import sys
from common129 import HERE, PUBLIC, ROOT, read, reference, save


AUDITS = {
    "round1": "audit/round1_全注文と全行会計の独立照合.json",
    "round2": "audit/round2_全注文と全行会計の独立照合.json",
    "round3": "audit/round3_全注文と全行会計の独立照合.json",
    "round4": "night/夜間第四巡の保存全行会計と親別照合_1792491715879348100.json",
    "round5": "night_quantity_diagnosis/数量変更の独立会計と追加単価診断.json",
    "round6": "night/夜間第六巡の保存全行会計と親別照合_1792492874954329300.json",
    "round7": "audit/round7_全注文と全行会計の独立照合.json",
    "day_round1": "night/日中第一巡の保存全行会計と親別照合_1792490493137855600.json",
    "day_round2": "audit/day_round2_全注文と全行会計の独立照合.json",
}


def audited_accounts(proof):
    """
    機能: 独立監査の形式差を吸収し、照合済み口座数を返す。
    引数: proof(dict)は保存監査結果。
    返り値: intは口座数。未合格の監査は拒否する。
    """
    assert proof["passed"]
    if "accounts" in proof:
        return proof["accounts"]
    if "account_count" in proof:
        return proof["account_count"]
    return len(proof["rows"])


def main():
    """
    機能: 九巡の結果と公開物を接続し、該当試行だけを実施済みにする。
    引数: なし。固定済み結果・独立監査・公開確認を読む。
    返り値: None。安定性達成はfalseのまま明記し、金融再生は行わない。
    """
    counts = []
    for name, path in AUDITS.items():
        data = read(HERE / name / "全条件の会計.json")
        assert data["passed"] and len(data["rows"]) == audited_accounts(read(HERE / path))
        counts.append(dict(round=name, conditions=len(data["configs"]), accounts=len(data["rows"]),
                           financial_replays=data["financial_replays"]))
    assert sum(r["conditions"] for r in counts) == 33
    assert sum(r["financial_replays"] for r in counts) == 1402
    for path in ["表示確認_最終/公開表示の確認.json", "表示確認_最終/実表示幅と描画の確認.json",
                 "audit/最終案内と九巡分母の独立照合.json", "audit/日中持続確認と数量追加の公開前照合.json"]:
        assert read(HERE / path)["passed"], path
    result = read(HERE / "最終全場比較_確定.json")
    assert result["passed"] and len(result["rows"]) == 1530
    public_files = [reference(p) for p in sorted(PUBLIC.rglob("*")) if p.is_file()]
    knowledge = [reference(ROOT / "アルゴリズム調査/共通/知見台帳" / name)
                 for name in ("入口.md", "継続.md", "出口.md", "売買の工夫.md")]
    save(HERE / "採用候補と公開記録.json", dict(
        passed=True, achieved=False, financial_replays=0, API=0, live_app_changes=0,
        counts=counts, total_new_conditions=33, total_financial_accounts=1402,
        reused_baseline_accounts=128, published_accounts=1530, known_sessions=43,
        decision={
            "日中": "TOPIX120秒DV07・日経60秒DV05は改善候補。銘柄別は既知資料での参考選択。共通120秒DV07は日経総収支を5500円減らす。",
            "夜間": "両銘柄共通の採用は保留。中値の準備破棄NV25は日経の2敗を除くが8/21無取引、上位3黒字場除外は140円。TOPIXは改善せず。",
            "未解決": "日中赤字6/22場とTOPIX上昇場の偏り。夜間は小波の再進行と継続方向の区別、確認待ちで失う勝ち。",
        },
        numerical=reference(HERE / "最終全場比較_確定.json"),
        public=public_files, knowledge=knowledge,
        audits=[reference(HERE / p) for p in AUDITS.values()],
        public_reviews=[
            reference(HERE / "audit/日中持続確認と数量追加の公開前照合.json"),
            reference(HERE / "audit/最終案内と九巡分母の独立照合.json"),
            reference(HERE / "audit/公開結論と次仮説の敵対的レビュー_1792494117659011100.json"),
        ],
        display=[reference(HERE / "表示確認_最終/公開表示の確認.json"),
                 reference(HERE / "表示確認_最終/実表示幅と描画の確認.json")],
        limitation="全43場は既知開発。次正常原行ラージ気配代理。現在値時計は実受信時計ではない。"))
    # ----------------------------------------
    # 台帳の過去記録は保持し、この九巡だけの実施状態を更新する。
    manager = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    path = manager.parent / "data/trials.json"
    original = path.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()
    history = path.parent / "history" / ("trials_" + original_hash + ".json")
    if not history.exists():
        history.write_bytes(original)
    table = json.loads(original.decode("utf-8"))
    changed = []
    for name, audit in AUDITS.items():
        trial_id = "129_" + name + "_チャートと板の失敗機構改善"
        row = next(r for r in table["trials"] if r["id"] == trial_id)
        assert row["status"] == "未実行", row["status"]
        row["status"] = "検証完了・全体の安定性未達"
        row["result"] = (
            "具体時刻・画像・反例から九巡33条件を検証。日中の持続確認は一部損失を縮小。"
            "夜間の準備破棄は日経2敗を避けたが、両銘柄共通の安定性は未達。00129参照。"
        )
        row["evidence"] += [reference(HERE / name / "全条件の会計.json"),
                            reference(HERE / audit), reference(HERE / "採用候補と公開記録.json")]
        changed.append(trial_id)
    temporary = path.with_suffix(".json.129tmp")
    temporary.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    save(HERE / "試行完了の変更記録.json", dict(
        passed=True, achieved=False, changed=changed, before_sha256=original_hash,
        after=reference(path), financial_replays=0, counts=counts))
    for command in ("build", "verify"):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(manager), command, "--deep"],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        save(HERE / ("最終台帳_" + command + ".json"), dict(returncode=process.returncode,
             stdout=process.stdout, stderr=process.stderr))
        print(command, process.returncode, flush=True)
        assert process.returncode == 0, process.stderr[-2000:]


if __name__ == "__main__":
    main()
