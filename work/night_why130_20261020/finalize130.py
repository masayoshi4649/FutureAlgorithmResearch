"""独立監査と公開確認を経た四巡だけを試行台帳へ接続する。"""

import hashlib
import json
import subprocess
import sys
from common130 import HERE, PUBLIC, ROOT, read, reference, save


def main():
    """
    機能: 四巡の会計・監査・表示証拠を固定し、この試行の実施状態を更新する。
    引数: なし。終了確認.jsonの監査参照と公開結果を参照する。
    返り値: None。金融再生はせず、安定性未達を維持して記録する。
    """
    completion = read(HERE / "終了確認.json")
    for item in completion["audits"] + completion["reviews"]:
        path = HERE / item
        assert read(path)["passed"], item
    assert read(HERE / "表示確認/公開表示の確認.json")["passed"]
    counts = []
    for name in ("round1_final", "round2", "round3", "round4"):
        data = read(HERE / name / "全条件の会計.json")
        assert data["passed"] and data["financial_replays"] == len(data["rows"])
        assert len(data["rows"]) == 42*len(data["configs"])
        counts.append(dict(round=name, conditions=len(data["configs"]), accounts=len(data["rows"])))
    assert sum(r["conditions"] for r in counts) == 12
    assert sum(r["accounts"] for r in counts) == 504
    final = read(HERE / "最終全場比較_確定.json")
    assert final["passed"] and len(final["rows"]) == 762
    assert len({r["session"] for r in final["rows"]}) == 43
    record = dict(passed=True, achieved=False, financial_replays=0, market_API=0, real_orders=0,
                  counts=counts, total_new_conditions=12, new_financial_accounts=504,
                  reused_accounts=258, shown_accounts=762, known_sessions=43,
                  conclusion=read(HERE / "結論.json"),
                  numerical=reference(HERE / "最終全場比較_確定.json"),
                  audits=[reference(HERE / p) for p in completion["audits"]],
                  reviews=[reference(HERE / p) for p in completion["reviews"]],
                  display=reference(HERE / "表示確認/公開表示の確認.json"),
                  errata=reference(HERE / "根拠文の訂正.json"),
                  public=[reference(p) for p in sorted(PUBLIC.rglob("*")) if p.is_file()],
                  knowledge=[reference(ROOT / "アルゴリズム調査/共通/知見台帳" / n)
                             for n in ("入口.md", "継続.md", "出口.md", "売買の工夫.md")])
    save(HERE / "四巡の結論と公開記録.json", record)
    # ----------------------------------------
    # 既存台帳を退避して、今回の四件の状態・結果根拠だけを更新する。
    manager = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    path = manager.parent / "data/trials.json"
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    backup = path.parent / "history" / ("trials_" + digest + ".json")
    if not backup.exists():
        backup.write_bytes(original)
    data = json.loads(original.decode("utf-8"))
    changed = []
    for count in counts:
        name = count["round"]
        trial_id = "130_" + name + "_夜間損失のなぜ三段階と再改善"
        trial = next(r for r in data["trials"] if r["id"] == trial_id)
        assert trial["status"] == "未実行", trial
        trial["status"] = "検証完了・両銘柄の安定性未達"
        trial["result"] = record["conclusion"]["navigation"]
        trial["evidence"] += [reference(HERE / name / "全条件の会計.json"),
                              reference(HERE / "四巡の結論と公開記録.json")]
        changed.append(trial_id)
    temporary = path.with_suffix(".json.130tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    save(HERE / "試行完了の変更記録.json", dict(passed=True, achieved=False, changed=changed,
         before_sha256=digest, after=reference(path), financial_replays=0))
    for command in ("build", "verify"):
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(manager), command, "--deep"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        save(HERE / ("最終台帳_" + command + ".json"),
             dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
        print(command, result.returncode, flush=True)
        assert result.returncode == 0, result.stderr[-1500:]


if __name__ == "__main__":
    main()
