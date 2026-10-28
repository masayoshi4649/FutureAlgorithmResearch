"""金融前の読取監査と人工検査の根拠をまとめる。金融再生は実行しない。"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/audit159"


def evidence(path: Path) -> dict:
    """検査対象の位置と内容指紋を返す。

    引数: path(Path)。返り値: dictはファイル位置・バイト数・SHA256。
    """
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main() -> None:
    """最新版の一致を確認し金融前監査を確定する。

    引数: なし。返り値: None。候補源・原資料・試行台帳は変更しない。
    """
    independent = json.loads((WORK / "独立人工検査159.json").read_text(encoding="utf-8"))
    shared = json.loads((ROOT / "work/night159/人工検証159.json").read_text(encoding="utf-8"))
    assert independent["passed"] and independent["source_unchanged"]
    for row in independent["source_fingerprints"]:
        assert evidence(ROOT / row["path"])["sha256"] == row["sha256"], row["path"]
    evidence_paths = [WORK / "独立人工検査159.json", WORK / "inputs159.json", WORK / "保存網羅性159.json", WORK / "関連試行の索引159.json", ROOT / "work/night159/人工検証159.json", ROOT / "work/night159/spec159.json", ROOT / "work/night159/configs159.json", ROOT / "work/night159/実装仕様159.md"]
    report = {"passed": True, "created_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(),
        "scope": "研究00159の固定12条件・26Nightと追加1Day（Dayは基準と支持量の2条件）の金融前確認。収益性の実証ではない。",
        "new_candidate_financial_replays": 0, "audit_agent_existing_fixture_replays": 0,
        "implementation_agent_existing_fixture_replays": shared["existing_fixture_replays"],
        "implementation_agent_existing_suites_not_passed": shared["existing_suites_not_passed"],
        "dedicated_artificial_tests": {"shared_count": 9, "independent_count": 7, "total_passed": len(independent["passed_tests"]), "tests": independent["passed_tests"], "source_still_matches": True},
        "resolved_findings": [
            {"issue": "P05返済通知のCampaignが0へ落ちる", "resolution": "元Source通知は維持し、政策通知だけTargetsから元親を補完。異親又は所有不明は明示停止。"},
            {"issue": "5秒/15秒変化を同じ速度単位として比較", "resolution": "3×Own5と0.5×Own15で比較し、一定速度の誤減量を修正。"},
            {"issue": "前半逆行時計の観測間隔を共通時計で上書き", "resolution": "専用Guard時計で未知・異常板・5秒超間隔をリセット。"},
            {"issue": "後続Source追加の採否が集計件数だけ", "resolution": "requestsへSourceID/元親/時刻・原行/支持/希望量/採用量/理由を保存。"}
        ],
        "checked": ["全正常ラージ板の買Bid・売Ask時価、全owner同時合算、初期0を含む最小・最大下落", "約定前と各約定直後の逐次評価、同秒別原行の次約定、保有数量×秒", "P05の仮想源と実玉は別、政策の保護損益を元Sourceへ注入しない", "US−15分のP05返済、異常板で待機、実Source残玉と予約0後だけUS＋15分以降にD07生成", "後半のFeaturesは保持・Portfolioは新規・Session.StartはNightStart（現App仕様）", "追加DayはS01のみ、N00/N02二条件、Nightと別集計", "所有＋新規予約の片側100、同原行希望の比例配分、返済予定を空き扱いしない", "N09/10は後半だけ、建値床でも次板飛び越し赤字を保存", "支持の同秒相手板は参照しない、未知は最低10、支持を成功確率と呼ばない"],
        "limits": ["保存板の価格時計は受信時計ではない。データの遅延・実際の約定量を保証しない。", "正常終端が終了前6分に届く資格と、Day15:35/Night05:50の返済判断は別。", "新完了10/26Nightと10/27Dayは途中の既知部分を含み、丸ごと未見の外部評価ではない。", "現AppのP05→D07を再生する基準であり、00151の保存前後合算又は旧00145の基準と同一としない。", "実装担当の既存e01固定fixture4例再現は候補の収益性根拠から除外する。"],
        "evidence": [evidence(p) for p in evidence_paths], "source_fingerprints": independent["source_fingerprints"]}
    target = WORK / "金融前監査159.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "tests": len(independent["passed_tests"]), **evidence(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
