"""旧元玉出口と追加・カバーを分ける第三巡を金融再生前に固定登録する。"""

import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIRST = HERE.parent
SECOND = FIRST / "round2"
BASE = ROOT / "work/s01_156"
ID = "157_第三巡_元玉出口と追加カバーの分離"


def read(path):
    """UTF-8のJSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path):
    """根拠の内容指紋と位置を返す。

    引数: path(Path)。返り値: dictは相対位置・SHA256・サイズ。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def save(path, value):
    """小さい登録証跡を保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    """三巡目の仕様・実装・人工検査と旧結果を固定して照合登録する。

    引数: なし。返り値: None。金融再生・実注文・API再取得は行わない。
    """
    receipt = HERE / "登録受領1573.json"
    assert not receipt.exists()
    previous = read(SECOND / "金融監査1572.json")
    assert previous["passed"] and previous["case_count"] == 1080
    artificial = read(HERE / "人工監査確定1573.json")
    assert artificial["passed"] and artificial["financial_replays"] == 0
    configs = read(HERE / "configs1573.json")
    specification = read(HERE / "spec1573.json")
    manifest = read(BASE / "inputs156.json")
    assert len(configs) == 12 and len({row["id"] for row in configs}) == 12
    assert len(manifest["sessions"]) == 27
    files = sorted(path for path in (HERE / "engine_go").rglob("*") if path.is_file() and (path.suffix in (".go", ".toml") or path.name in ("go.mod", "go.sum")))
    files += [HERE / name for name in ("spec1573.json", "spec1573.md", "configs1573.json", "register1573.py", "execute1573.py", "人工監査確定1573.json")]
    files += [SECOND / name for name in ("report1572.json", "金融監査1572.json", "金融実行1572.json", "spec1572.json", "spec1572.md", "configs1572.json", "支持と元S01損益の関係1572.json")]
    files += [FIRST / name for name in ("report157.json", "金融監査157.json", "spec157.json", "spec157.md")]
    files += [BASE / name for name in ("inputs156.json", "report156_all.json", "試行完了証跡156.json")]
    bundle = HERE / "再生前実装1573.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    inputs = [reference(BASE / "inputs156.json"), reference(BASE / "current_20261027/manifest.json")]
    fixed = [dict(row, control=row.get("control") or "第二巡J02の同値確認") for row in configs]
    plan = {
        "id": ID, "name": "元玉の旧出口を維持した追加・カバー・支持崩壊の分離", "purpose": "条件比較",
        "question": "第二巡で大幅悪化した新共通出口を元玉から外した時、独自順行追加・逆玉利確・逆行回復追加が場内の赤字累積を改善するか",
        "change": "元S01出口と数量管理を独立に切替可能とする。J02同値対照に対し順行追加、支持によるカバー、カバー玉だけの40pt起動40pt追尾、逆行20/40/60pt後20pt回復、累計25/50micro、両側/純量、場赤字抑制、支持崩壊返済を12条件で分離。元玉の新80pt停止・40pt追尾・親8万円停止は使わない。",
        "repeat_reason": "第二巡で新共通出口だけのV_C01が旧S01+193.5万円から−43.4万円となり、旧出口の支持配分J02は+176万円。新出口下の追加/カバーの赤字だけでは、それら一般の無効性を判定できないため出口交絡を外す。支持の尺度/重み/既存価格閾値は選び直さない。",
        "compares_to": ["157_第二巡_観測間隔と少量参加の数量配分", "157_支持別の数量配分と両建ての場内リスク"],
        "spec": {
            "entry": {"method": "第二巡のSource初回と観測定義を維持。最低10micro＋線形支持量、未知は最低量。支持を勝率とは呼ばない。", "conditions": fixed, "fixed_plan": specification},
            "management": {"method": "旧元玉出口と独自数量管理を分離。初回固定係数でSource追加を写し、独自追加/新カバーは当時既知の支持で判断。詳細は固定仕様。"},
            "exit": {"method": "元玉は旧Source出口。指定案のみ逆玉の利益追尾、又は長短支持崩壊で親全返済。元価格損切りを無断で除去しない。場末全返済は共通。"},
            "allocation": {"method": "micro100枚相当=mini10枚相当／片方向、実所有と新規予約を合計。初回最低量10に加算する支持数量、逆行追加累計25/50。親内相殺と両側実保有を同Canonical判断で比較。", "max_per_side": 100, "point_value": 10},
            "costs": {"fee": 0, "spread": "判断後の次正常ラージBBO。買Ask・売Bid、全残玉時価を含む。実microの気配性能を再現しない。"},
            "execution": {"method": "同原行約定なし。未来のSource終了は読まない。正常原行ごとの約定前後に全玉時価を確認し、場内最悪・最大DDを記録。旧結果再現は新成功例に数えない。"},
            "data": {"sessions": [row["session"] for row in manifest["sessions"]], "input_manifests": inputs, "scope": "26完了Dayと10/27途中1場。途中は累計から除く。既知期間の開発比較。API再取得なし、Night改善未検証。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    proposal = HERE / "再生計画1573.json"
    save(proposal, plan)
    module_spec = importlib.util.spec_from_file_location("試行157第三巡管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("第三巡12条件の事前照合登録を開始。金融再生は未実行です。", flush=True)
    record = manager.store_trial(plan)
    save(HERE / "事前照合1573.json", record["preflight"])
    save(receipt, {"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(), "plan": reference(proposal), "implementation": reference(bundle), "sources": [reference(path) for path in files], "inputs": inputs})
    print("第三巡登録完了。指紋照合後だけ金融再生できます。", flush=True)


if __name__ == "__main__":
    main()
