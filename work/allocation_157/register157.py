"""数量配分と保有形式の比較157を、実装・人工監査の完了後に事前照合登録する。"""

import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "work/s01_156"
ID = "157_支持別の数量配分と両建ての場内リスク"


def read(path):
    """UTF-8のJSONを読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path):
    """全内容の指紋を作り相対位置とともに返す。

    引数: path(Path)。返り値: dictは相対位置・SHA256・バイト数。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": path.stat().st_size}


def save(path, value):
    """小さい証跡を日本語UTF-8で保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    """固定した仕様・人工検査・入力・実装を既存管理器で事前登録する。

    引数: なし。返り値: None。金融再生・ネットワーク取得・実注文は行わない。
    """
    receipt_path = HERE / "登録受領157.json"
    assert not receipt_path.exists()
    completion = read(BASE / "試行完了証跡156.json")
    assert completion["state"] == "正本と閲覧データの更新完了"
    specification = read(HERE / "spec157.json")
    configs = read(HERE / "configs157.json")
    plan_configs = [dict(row, control=row["control"] or "保存済みS01の同額再現（00156）") for row in configs]
    manifest = read(BASE / "inputs156.json")
    artificial = read(HERE / "人工監査確定157.json")
    assert artificial["passed"] is True
    assert len(configs) >= 10 and len(manifest["sessions"]) == 27
    assert len({row["id"] for row in configs}) == len(configs)
    files = sorted(path for path in (HERE / "engine_go").rglob("*") if path.is_file() and (path.suffix in (".go", ".toml") or path.name in ("go.mod", "go.sum")))
    files += [HERE / name for name in ("spec157.json", "spec157.md", "configs157.json", "register157.py", "execute157.py", "人工監査確定157.json", "比較元の場内赤字.json", "比較元の場内赤字.md")]
    files += [BASE / name for name in ("inputs156.json", "report156.json", "report156_all.json", "試行完了証跡156.json")]
    assert len(files) > 30
    bundle = HERE / "再生前実装157.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    inputs = [reference(BASE / "inputs156.json"), reference(BASE / "current_20261027/manifest.json")]
    plan = {
        "id": ID, "name": "S01の初回・追加・抑制・逆行追加と両建ての同額比較", "purpose": "条件比較",
        "question": "初回固定5枚を外した数量判断は、単純減枚と比べて収益を保ちながら連敗累積・利益返し・場内最悪収支を改善できるか。逆玉カバーには同じ純数量だけを持つ形式以上の利点があるか",
        "change": "独立した旧S01の親・方向通知を比較元とし、支持別初回数量、順行追加、短期反対時の抑制、逆行回復時の追加間隔と上限、場内赤字後の抑制、両建てと純数量保有を登録条件で比較。実約定と仮想判断の状態を分離。",
        "repeat_reason": "156では固定幅利益保護と再参加を3巡44条件で比較したが総合改善なし。S01場内最悪−20.3万円の大半は初回群の確定赤字累積、DD29.4万円も初回群が主因。同親追撃だけを止める修正では原因を覆えない。数量を単に半分にする算術対照と、出口対照を分けて検証する。",
        "compares_to": ["156_固定値幅の玉別利益保護と失速入口の比較", "156_第二巡_固定保護後の同親再参加", "156_第三巡_再参加玉の初期逆行制限"],
        "spec": {
            "entry": {"method": "元S01の逐次通知と当時のラージ支持。未校正スコアを成功確率としない。具体式・未知扱い・条件は固定仕様へ保存。", "conditions": plan_configs, "fixed_plan": specification},
            "management": {"method": "固定仕様に基づく数量管理。支持回復前の無条件ナンピンと、支持が崩れた元玉の無期限保持を混同しない。逆玉利益だけでなく元玉と全玉時価を計上。"},
            "exit": {"method": "元退出と各条件の利益保護・支持崩壊・玉別逆行・親/場内制限は固定仕様に従う。新共通出口の対照を設け数量変更と分離。"},
            "allocation": {"product": "NK225micro相当", "point_value": 10, "max_per_side": 100, "method": "mini10枚相当の同額上限、実所有＋新規予約。元S01対照は全注文/返済配賦を厳密10倍換算。初回は1枚にも半分にも固定しない。gross/netと両側を区別。"},
            "costs": {"fee": 0, "spread": "次正常ラージBid/Ask。mini/micro板を追加せず、実商品の約定性能を測ったものとしない。"},
            "execution": {"method": "同原行約定なし。判断後の次正常原行。対照の旧S01同額一致、H/Nの同判断系列と純数量、中値時価・BBO差を独立に確認。"},
            "data": {"sessions": [row["session"] for row in manifest["sessions"]], "input_manifests": inputs, "scope": "26完了Dayと10/27 15:20未満途中1場。全条件を公開し途中場は完了累計から除く。既知期間の開発比較。新API取得0、Night改善を証明しない。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    plan_path = HERE / "再生計画157.json"
    save(plan_path, plan)
    module_spec = importlib.util.spec_from_file_location("試行157管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("157の固定条件を照合登録します。金融再生はまだ行いません。", flush=True)
    record = manager.store_trial(plan)
    save(HERE / "事前照合157.json", record["preflight"])
    save(receipt_path, {"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(), "plan": reference(plan_path), "implementation": reference(bundle), "sources": [reference(path) for path in files], "inputs": inputs})
    print("157登録完了。指紋照合後だけ金融再生できます。", flush=True)


if __name__ == "__main__":
    main()
