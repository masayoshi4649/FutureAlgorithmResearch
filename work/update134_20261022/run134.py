"""10月22日デイのTOPIXだけを、00132と同じ固定手法で検証する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT / "work/update132_20261021"
MANAGER = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
SCENE = "2026-10-22_Day"
sys.dont_write_bytecode = True


def read(path: Path) -> dict:
    """
    機能: 保存済みJSONを読む。
    引数: path(Path)はファイル位置。
    返り値: dictはJSONの内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: dict) -> None:
    """
    機能: 作業内へJSONを新規保存する。
    引数: path(Path)は保存位置、value(dict)は内容。
    返り値: None。既存結果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def reference(path: Path) -> dict:
    """
    機能: 入力と実装の内容指紋を取得する。
    引数: path(Path)は実在ファイル。
    返り値: dictは相対位置とSHA256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=digest)


def module(name: str, path: Path) -> object:
    """
    機能: 保存済みの処理を明示した位置から読み込む。
    引数: name(str)は登録名、path(Path)は実装位置。
    返り値: objectはモジュール。読み込みだけで金融再生はしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def prepare() -> None:
    """
    機能: 同じ入力変換を新しい一場に適用し、TOPIXだけの実行口を用意する。
    引数: なし。素材監査.jsonを使う。
    返り値: None。条件判定による金融再生は実行しない。
    """
    original = PREVIOUS / "run_selected132_v2.py"
    text = original.read_text(encoding="utf-8")
    before = 'for symbol in ("TOPIX", "NK225"):\n        key = scene, symbol'
    after = 'for symbol in ("TOPIX",):\n        key = scene, symbol'
    assert text.count(before) == 1
    changed = text.replace(before, after).replace('固定2商品の再生完了', '固定TOPIXの再生完了')
    target = HERE / "run_selected134.py"
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(changed)
    save(HERE / "接続変更.json", dict(original=reference(original), copied=reference(target),
         changes=["金融再生の対象商品をTOPIXだけに限定", "完了表示の商品数を修正"],
         numerical_change=False, financial_replays=0))
    # ----------------------------------------
    # 原データと既存結果は読み取り専用。入力変換の保存先だけ今回の領域へ変更する。
    preparation = module("prepare132_for134", PREVIOUS / "prepare_inputs132.py")
    preparation.HERE = HERE
    preparation.prepare(HERE / "inputs", (SCENE,), HERE / "素材監査.json")


def register() -> None:
    """
    機能: 既存の固定手法・新規一場・TOPIX一口座の計画を照合し登録する。
    引数: なし。非金融入力の準備完了後に実行する。
    返り値: None。注文判定と損益計算は実行しない。
    """
    driver = module("driver134", HERE / "run_selected134.py")
    manifest = HERE / "inputs/input_manifest.json"
    plan = read(PREVIOUS / "試行計画_v2.json")
    plan.update(id="134_T06固定_20261022Day_TOPIX", name="10月22日デイのTOPIX固定T06検証",
        purpose="新データ", question="現行T06・TOPIXミニ片方向上限10枚の当場損益を確認する。",
        change="00132と同じ入力変換・数値核。対象は追加2026-10-22_DayのTOPIXのみ。二市場のラージ板を判断に使う。",
        repeat_reason="ユーザーによる追加データの利益想定依頼。係数・手法の選び直しなし。",
        compares_to=["132_v2_採用条件の追加2場検証"],
        evidence=[reference(HERE / "接続変更.json"), reference(HERE / "素材監査.json"), reference(Path(__file__))],
        mode="additional", sessions=[SCENE], input_manifest=reference(manifest),
        sources=driver.source_fingerprints(), configs=driver.configurations(), selection=driver.SELECTION)
    spec = plan["spec"]
    spec["entry"] = dict(selection="Day:TOPIX T06", configs=plan["configs"]["Day:TOPIX"], 固定条件="00131採用・00132追加検証と同一。成績を見た再選択なし。")
    spec["allocation"] = dict(主担当TOPIXmini=5, 追加担当TOPIXmini=5, 片方向上限TOPIXmini=10,
        補完条件="12:30以後、主担当がまだ一度も新規していない場合だけ一場一回。")
    spec["costs"] = dict(TOPIXmini=41.8, 課金="新規・返済の注文ごとに1円未満切捨て。親全返済の純損益で利益損失を分類。手数料前も併記。")
    spec["data"] = dict(input_manifests=[reference(manifest)], sessions=[SCENE],
        対象="TOPIX一商品場を金融再生。NK225は判断データとしてのみ利用。",
        照合範囲="00131・00132の固定条件、00133の実稼働との差、分類別知見を確認。過去全試行の重複なしとはしない。")
    spec["implementation"] = plan["sources"]
    save(HERE / "試行計画.json", plan)
    for action in ("check", "register"):
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(MANAGER), action,
                                "--proposal", str(HERE / "試行計画.json")], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8")
        save(HERE / ("試行計画_" + action + ".json"), dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
        assert result.returncode == 0, result.stderr[-3000:]
        summary = json.loads(result.stdout)
        print(action, summary.get("proposal_complete", summary.get("preflight", {}).get("proposal_complete")), flush=True)


def run() -> None:
    """
    機能: 登録済みの当場TOPIX一口座だけを再生する。
    引数: なし。登録後の固定計画と指紋を検証する。
    返り値: None。API接続・実注文は行わない。
    """
    driver = module("driver134", HERE / "run_selected134.py")
    args = argparse.Namespace(manifest=HERE / "inputs/input_manifest.json", session=[SCENE],
        output=HERE / "results", plan=HERE / "試行計画.json",
        registered=HERE / "試行計画_register.json", golden=False)
    driver.execute(args)
    row = read(HERE / "results/追加セッションの会計.json")["rows"][0]
    print(json.dumps({k: row[k] for k in ("session", "symbol", "profit", "loss", "net", "gross", "fees", "entries", "max_long", "max_short")}, ensure_ascii=False), flush=True)


def main() -> None:
    """
    機能: 非金融準備・事前登録・金融実行の各段階を明示して実行する。
    引数: 起動引数(str)はprepare、register、runのいずれか。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "register", "run"))
    args = parser.parse_args()
    {"prepare": prepare, "register": register, "run": run}[args.stage]()


if __name__ == "__main__":
    main()
