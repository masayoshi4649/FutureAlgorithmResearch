"""具体的な悪化原因から分けた第二巡四案を金融再生前に登録する。"""

from datetime import datetime
import importlib.util
from pathlib import Path
import zipfile
from register159 import read, save, fingerprint

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "work/research159/round2"
ENGINE = ROOT / "work/night159/round2"
ID = "159_第二巡_未知支持の基準量と超過分の保護"


def main() -> None:
    """固定四案と独立人工監査を確認して照合・登録する。

    引数: なし。返り値: None。新しい金融再生は行わない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    receipt = HERE / "登録受領159r2.json"
    assert not receipt.exists()
    spec = read(ENGINE / "spec159r2.json")
    configs = read(ENGINE / "configs159r2.json")
    manifest = read(ENGINE / "inputs159r2.json")
    artificial = read(ENGINE / "人工検証159r2.json")
    audit_path = ROOT / "work/audit159/第二巡金融前監査159.json"
    audit = read(audit_path)
    assert artificial["returncode"] == 0 and artificial["passed"] and artificial["new_candidate_replays"] == 0 and audit["passed"]
    assert len(manifest["sessions"]) == 26 and all(s["kind"] == "Night" for s in manifest["sessions"])
    files = sorted(p for p in (ENGINE / "engine_go").rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    files += [ENGINE / name for name in ("spec159r2.json", "configs159r2.json", "inputs159r2.json", "人工検証159r2.json", "実装仕様159r2.md")]
    files += [Path(__file__), audit_path, ROOT / "work/research159/execute159r2.py", ROOT / "work/research159/report159.json", ROOT / "work/night159/diagnosis/悪化三夜と第二巡の仮説159.md"]
    bundle = HERE / "再生前実装159r2.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    # ----------------------------------------
    # 第一巡の結果を見て考えた追加開発であり、独立した未見選択とは記録しません。
    plan = {
        "id": ID, "name": "未知支持の基準量維持と超過量だけの利益保護", "purpose": "条件比較",
        "question": "支持未知による勝ちの過小配分と、支持増量後の利益返しを別条件で改善できるか",
        "change": "米国後だけ支持配分するN04に対し、未知時だけSource数量を維持。さらにSource基準残量を超える自由残量だけ40/40又は80/40で利益保護し、指定案では80pt逆行と反対支持5秒の防御を足す。",
        "repeat_reason": "第一巡の悪化最大3夜で、未知の勝ちを50から10microへ縮小した経路と、高支持の大口が急逆行又は含み益を消した経路を確認。一律の早い追尾では勝ちも消えたため、未知補完と超過分の出口だけを分離して再検証する。既知結果を見た追加開発。",
        "compares_to": ["159_支持校正と米国前後の夜間数量政策"],
        "spec": {
            "entry": {"conditions": configs, "fixed_specification": spec, "method": "前P05/後D07の源・時間枠・支持計算は第一巡と同じ。未知時の初回量だけ指定変更。"},
            "management": {"method": "旧Sourceの追加と返済は保持。源残数量、実残数量、既予約返済、保護による今回返済を分離し基準量を保護操作で過剰返済しない。後のSource部分退出まで一定基準量を保証しない。"},
            "exit": {"method": "R00元出口、R01超過自由残量だけ40pt起動/40pt戻り、R02は80/40、R03はR02と超過分80pt逆行・反対支持5秒。次板約定、当時建値床、源返済優先、境界/場末全返済。"},
            "allocation": {"method": "micro片方向100枚相当=mini10枚相当、所有と新規予約を合算。未知を弱支持と混同しない。超過量は固定仕様に定義。", "max_per_side": 100, "point_value": 10},
            "costs": {"fee": 0, "spread": "第一巡と同じ次正常ラージBBO、買Ask/売Bid。全残玉時価込み。"},
            "execution": {"method": "正常原行ごとの判断・後続原行約定。4新案104条件場とN00同値26場。同値対照を新しい成功例に数えない。"},
            "data": {"sessions": [s["session"] for s in manifest["sessions"]], "input_manifests": [fingerprint(ENGINE / "inputs159r2.json")], "scope": "第一巡と同じ26完了Night。旧25と10/26完了版は分離。APIなし、既知開発。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): fingerprint(bundle)["sha256"]},
        },
    }
    proposal = HERE / "再生計画159r2.json"
    save(proposal, plan)
    location = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    module_spec = importlib.util.spec_from_file_location("試行159第二巡管理", location)
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    checked = manager.check(plan)
    save(HERE / "事前照合159r2.json", checked)
    assert checked["proposal_complete"]
    print("第二巡四案の事前照合完了。登録します。", flush=True)
    record = manager.store_trial(plan)
    save(receipt, {"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(),
                   "plan": fingerprint(proposal), "implementation": fingerprint(bundle), "sources": [fingerprint(p) for p in files],
                   "matching_count": len(record["preflight"]["matches"]), "new_candidate_replays": 0})
    print("第二巡の固定登録完了。", flush=True)


if __name__ == "__main__":
    main()
