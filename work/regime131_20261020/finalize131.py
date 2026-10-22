"""四巡の保存結果と独立確認を台帳へ接続する。金融再生は行わない。"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote

from common131 import HERE, PUBLIC, ROOT, read, reference, save


def check_links(path):
    """
    機能: 今回の公開Markdownの相対リンクが実在するかを調べる。
    引数: path(Path)はUTF-8の説明資料。
    返り値: intは確認リンク数。URLと見出しだけのリンクは対象外。
    """
    count = 0
    for raw in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if raw.startswith(("https://", "http://", "#")):
            continue
        target = (path.parent / unquote(raw.split("#")[0])).resolve()
        assert target.is_relative_to(ROOT) and target.is_file(), (path, raw)
        count += 1
    return count


def main():
    """
    機能: 公開数値・独立会計・表示検査を固定し、登録済み四試行の状態を更新する。
    引数: --display(str)は確定した独立HTML表示確認JSONのHEREからの相対位置。
    返り値: None。試行台帳の対象四行と証拠を更新し、全体を深い検査にかける。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--display", required=True)
    args = parser.parse_args()
    display = (HERE / args.display).resolve()
    assert display.is_relative_to(HERE)
    evidence_names = [
        "night_diagnosis/独立全原行会計_round1_final_1792502168351370000.json",
        "night_diagnosis/合算注文の独立全原行会計_round2_1792503526031527300.json",
        "night_diagnosis/合算注文の独立全原行会計_round3_1792504191162186800.json",
        "night_diagnosis/リスク配分注文の独立全原行会計_round4_1792505466117458000.json",
        "audit/第一巡比較の独立再集計と選別批判_1792502598656265400.json",
        "audit/round3_候補比較と追加寄与の独立再集計_1792504230554973500.json",
        "audit/第四巡の赤字規模と失う利益の独立比較_1792505422642686900.json",
        "audit/公開候補86行と最新価値観の独立レビュー_1792505609429913700.json",
        "day_diagnosis/共通知見統合と内部リンク確認_1792505181135181000.json",
        "day_diagnosis/第二三四巡知見の統合と分母照合_1792505699918114100.json",
        "round4/枚数変更と失う利益の対応.json",
    ]
    proof_paths = [HERE / name for name in evidence_names] + [display]
    for path in proof_paths:
        assert read(path).get("passed") is True, path
    counts = []
    for name in ("round1_final", "round2", "round3", "round4"):
        data = read(HERE / name / "全条件の会計.json")
        assert data["passed"] and len(data["rows"]) == 86 * len(data["configs"])
        assert data["financial_replays"] + data.get("reused_config_rows", 0) == len(data["rows"])
        counts.append(dict(
            round=name, conditions=len(data["configs"]), accounts=len(data["rows"]),
            financial_replays=data["financial_replays"],
            reused=data.get("reused_config_rows", 0),
            trial_id=read(HERE / name / "試行計画.json")["id"],
        ))
    assert sum(r["conditions"] for r in counts) == 36
    assert sum(r["financial_replays"] for r in counts) == 2836
    assert sum(r["accounts"] for r in counts) == 3096
    combined = read(HERE / "公開候補の43場統合.json")
    assert combined["passed"] and len(combined["rows"]) == 86
    assert all(r["entries"] > 0 for r in combined["rows"])
    assert all(s["全体"]["without_top3"] > 0 for s in combined["summary"].values())
    checked_links = check_links(PUBLIC / "README.md")
    # ----------------------------------------
    # 公開資料・正本知見・監査への参照を保存し、安定性の証明と比較の完了を区別する。
    record = dict(
        passed=True, comparison_completed=True, stable_all_regimes_proven=False,
        required_participation_met=True, financial_replays=0,
        market_API=0, real_orders=0, counts=counts, known_sessions=43,
        new_conditions=36, new_financial_replays=2836,
        identical_reused_accounts=260, saved_accounts=3096, displayed_accounts=3858,
        conclusion=read(HERE / "公開結論.json"),
        numerical=reference(HERE / "公開候補の43場統合.json"),
        evidence=[reference(path) for path in proof_paths],
        public=[reference(p) for p in sorted(PUBLIC.rglob("*")) if p.is_file()],
        public_readme_link_checks=checked_links,
        knowledge=[reference(ROOT / "アルゴリズム調査/共通/知見台帳" / name)
                   for name in ("入口.md", "継続.md", "出口.md", "売買の工夫.md")],
        policy=reference(ROOT / "アルゴリズム調査/調査方針.md"),
    )
    record_path = HERE / "四巡の結論と公開記録.json"
    save(record_path, record)
    # ----------------------------------------
    # 大きな既存台帳はバイト列を重複保持せず退避し、対象四行だけを変更する。
    manager = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    ledger = manager.parent / "data/trials.json"
    assert ledger.resolve().is_relative_to(ROOT)
    with ledger.open("rb") as stream:
        before = hashlib.file_digest(stream, "sha256").hexdigest()
    backup = ledger.parent / "history" / ("trials_" + before + ".json")
    backup.parent.mkdir(exist_ok=True)
    if not backup.exists():
        shutil.copyfile(ledger, backup)
    with ledger.open(encoding="utf-8") as stream:
        document = json.load(stream)
    descriptions = {
        "round1_final": "十二条件・両商品とも累計赤字。時計や過去効率だけで頻繁な追随回帰を切り替える方式は採らない。",
        "round2": "旧核を保ち未参加時のみ一回追加。全場参加を達成したが、日経夜間の追加単独で損失が残る。",
        "round3": "追加入口を維持し保護開始と追尾幅を比較。日経夜間の追加分を改善、広い初期幅の固定枚数が課題。",
        "round4": "追加数量だけを初期停止幅に反比例。公開候補は日中T06・夜間TOPIX T04／日経U06。全場参加・上位3黒字除外後黒字、上昇場と夜間後半への偏りは残る。",
    }
    changed = []
    for count in counts:
        trial = next(r for r in document["trials"] if r["id"] == count["trial_id"])
        assert trial["status"] == "未実行", (trial["id"], trial["status"])
        trial["status"] = "検証完了・既知資料内比較・区分別安定性の弱点あり"
        trial["result"] = descriptions[count["round"]]
        trial["evidence"] += [reference(HERE / count["round"] / "全条件の会計.json"),
                              reference(record_path)]
        changed.append(trial["id"])
    temporary = ledger.with_suffix(".json.131tmp")
    assert not temporary.exists()
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    temporary.replace(ledger)
    del document
    save(HERE / "試行完了の変更記録.json", dict(
        passed=True, before_sha256=before, after=reference(ledger),
        changed=changed, financial_replays=0,
    ))
    print("四巡の状態と公開証拠を台帳へ保存", flush=True)
    for command in ("build", "verify"):
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(manager), command, "--deep"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        save(HERE / ("最終台帳_" + command + ".json"), dict(
            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
        ))
        print(command, result.returncode, flush=True)
        assert result.returncode == 0, result.stderr[-2000:]


if __name__ == "__main__":
    main()
