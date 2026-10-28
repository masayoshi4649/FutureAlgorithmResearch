"""数量配分と保有形式の比較157を、実装・人工監査の完了後に事前照合登録する。"""

import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = HERE.parent
BASE = ROOT / "work/s01_156"
ID = "157_第二巡_観測間隔と少量参加の数量配分"


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
    receipt_path = HERE / "登録受領1572.json"
    assert not receipt_path.exists()
    completion = read(BASE / "試行完了証跡156.json")
    assert completion["state"] == "正本と閲覧データの更新完了"
    prior_audit = read(PREVIOUS / "金融監査157.json")
    assert prior_audit["passed"] and prior_audit["case_count"] == 621
    specification = read(HERE / "spec1572.json")
    configs = read(HERE / "configs1572.json")
    plan_configs = [dict(row, control=row["control"] or "保存済みS01の同額再現（00156）") for row in configs]
    manifest = read(BASE / "inputs156.json")
    artificial = read(HERE / "人工監査確定1572.json")
    assert artificial["passed"] is True
    assert len(configs) == 40 and len(manifest["sessions"]) == 27
    assert len({row["id"] for row in configs}) == len(configs)
    files = sorted(path for path in (HERE / "engine_go").rglob("*") if path.is_file() and (path.suffix in (".go", ".toml") or path.name in ("go.mod", "go.sum")))
    files += [HERE / name for name in ("spec1572.json", "spec1572.md", "configs1572.json", "register1572.py", "execute1572.py", "人工監査確定1572.json", "支持識別の集計定義1572.json")]
    files += [BASE / name for name in ("inputs156.json", "report156.json", "report156_all.json", "試行完了証跡156.json")]
    files += [PREVIOUS / name for name in ("report157.json", "金融監査157.json", "金融実行157.json", "spec157.json", "spec157.md", "configs157.json", "支持未知の原行診断157.json", "比較元の場内赤字.json")]
    assert len(files) > 30
    bundle = HERE / "再生前実装1572.zip"
    assert not bundle.exists()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    inputs = [reference(BASE / "inputs156.json"), reference(BASE / "current_20261027/manifest.json")]
    plan = {
        "id": ID, "name": "実観測間隔での支持と小数量参加による配分の再比較", "purpose": "条件比較",
        "question": "短期窓端への厳密な時刻一致要求を実観測間隔の速度換算へ直し、補助欠測と自己方向不明を分けると、数量政策を十分な参加で比較できるか。弱い支持で見送る方式より小数量で参加する配分は有利か",
        "change": "元23政策は観測定義だけを置換、C00は保存同額対照。さらにSource全初回を採用する最低5/10/20micro＋支持比例の配分、旧/新出口、順行・逆行回復・カバー・場内抑制、固定10micro2対照を追加し40条件。具体差は固定仕様へ保存。",
        "repeat_reason": "初巡は完了155初回中145が指標未知で不採用、26場中22無取引。原行診断で窓端2秒制限が未知83件を占め、自己120/300区間の一時異常等45、相手9、現在OFI8だった。採用4場の黒字を安定性としない。支持値を勝ちへ合わせて下げず、実観測間隔・価格差に不要な途中全正常条件・補助欠測の扱いを分離する。Sourceの予測へ最小量で参加する方式と全役割固定量を純対照化し、初回数量という元の問いへ戻す。",
        "compares_to": ["157_支持別の数量配分と両建ての場内リスク", "156_固定値幅の玉別利益保護と失速入口の比較"],
        "spec": {
            "entry": {"method": "元S01の逐次通知を維持。短期5/15秒相当は許容15秒内の正常過去端から実経過で換算、長期120/300は両端の価格比。補助未知は0寄与とフラグ、重みを再正規化しない。最低量参加では支持未知でも元Source有効判断に最低量で従う。閾値選抜案と区別。", "conditions": plan_configs, "fixed_plan": specification},
            "management": {"method": "固定仕様に基づく数量管理。支持回復前の無条件ナンピンと、支持が崩れた元玉の無期限保持を混同しない。逆玉利益だけでなく元玉と全玉時価を計上。"},
            "exit": {"method": "元退出と各条件の利益保護・支持崩壊・玉別逆行・親/場内制限は固定仕様に従う。新共通出口の対照を設け数量変更と分離。"},
            "allocation": {"product": "NK225micro相当", "point_value": 10, "max_per_side": 100, "method": "mini10枚相当の同額上限、実所有＋新規予約。元S01対照は全注文/返済配賦を厳密10倍換算。初回は1枚にも半分にも固定しない。gross/netと両側を区別。"},
            "costs": {"fee": 0, "spread": "次正常ラージBid/Ask。mini/micro板を追加せず、実商品の約定性能を測ったものとしない。"},
            "execution": {"method": "同原行約定なし。判断後の次正常原行。対照の旧S01同額一致、H/Nの同判断系列と純数量、中値時価・BBO差を独立に確認。"},
            "data": {"sessions": [row["session"] for row in manifest["sessions"]], "input_manifests": inputs, "scope": "26完了Dayと10/27 15:20未満途中1場。全条件を公開し途中場は完了累計から除く。既知期間の開発比較。新API取得0、Night改善を証明しない。"},
            "implementation": {bundle.relative_to(ROOT).as_posix(): reference(bundle)["sha256"]}
        }
    }
    plan_path = HERE / "再生計画1572.json"
    save(plan_path, plan)
    module_spec = importlib.util.spec_from_file_location("試行157管理", ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    manager.validate({"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}, deep=True)
    print("157第二巡の固定40条件を照合登録します。金融再生はまだ行いません。", flush=True)
    record = manager.store_trial(plan)
    save(HERE / "事前照合1572.json", record["preflight"])
    save(receipt_path, {"id": ID, "registered": True, "returncode": 0, "created_at": datetime.now().astimezone().isoformat(), "plan": reference(plan_path), "implementation": reference(bundle), "sources": [reference(path) for path in files], "inputs": inputs})
    print("157第二巡登録完了。指紋照合後だけ金融再生できます。", flush=True)


if __name__ == "__main__":
    main()
