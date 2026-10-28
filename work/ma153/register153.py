"""移動平均の傾き比例配分を、金融再生より先に固定・照合・登録する。"""

import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIAL_ID = "153_移動平均の傾きと比例枚数の独立比較"


def reference(path):
    """根拠を内容指紋で固定する。

    引数: path(Path)は既存ファイル。返り値: dictは相対パス・SHA256・サイズ。
    """
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha, "bytes": path.stat().st_size}


def main():
    """26条件の実装・入力を固定し、既存試行へ登録する。

    引数: なし。返り値: None。金融再生は行わない。
    """
    receipt = HERE / "登録受領153.json"
    assert not receipt.exists(), "既登録の再登録は禁止"
    configs_path = HERE / "configs153.json"
    configs = json.loads(configs_path.read_text(encoding="utf-8-sig"))
    assert len(configs) == 26 and len({c["id"] for c in configs}) == 26
    manifest_path = HERE / "data/入力目録153.json"
    observation_path = HERE / "data/原板観測定義153.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = manifest["sessions"]
    complete = [s for s in scenes if not s["partial"]]
    assert len(complete) == 51 and len(scenes) == 52
    sources = sorted(p for p in (HERE / "engine_go").rglob("*")
                     if p.is_file() and (p.suffix == ".go" or p.name in ("go.mod", "go.sum")))
    sources += [configs_path, HERE / "spec153.md", HERE / "analysis_spec153.json"]
    assert (HERE / "engine_go/main.go").is_file() and (HERE / "spec153.md").is_file()
    implementation = HERE / "再生前実装153.zip"
    with zipfile.ZipFile(implementation, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(HERE).as_posix())
    inputs = [reference(manifest_path), reference(observation_path), reference(HERE / "data/観測定義補足153.json")]
    source_refs = [reference(path) for path in sources]
    # ----------------------------------------
    plan = {
        "id": TRIAL_ID,
        "name": "時間加重移動平均の傾きで1〜10枚を配分する26条件",
        "purpose": "新仮説",
        "question": "過去の傾きが強いときだけ枚数を増やし、弱ければ小さく入ると、一定枚数や初回比例固定より負けの頻度と深さを抑えられるか",
        "change": "E01/D07/P05から独立。60/180/300/600秒SMAの時間傾きで買売対称に参加し、初回比例又は10秒以上間隔の比例増減を、価格追尾・傾き反転・増勢後減速の3出口で比較する。",
        "repeat_reason": "00056のMA交差、00063の急傾斜、00118の多尺度MA、00148のOLS勢いは確認済み。傾きを枚数へ写像した効果と途中増減を独立比較していないため新条件として検証する。過去未整理条件の不存在は主張しない。",
        "compares_to": ["148_米国開始前の勢い入口と利益追跡"],
        "spec": {
            "entry": {"configurations": configs, "method": "正常ラージBBO中値の過去時間加重SMA。v=10000*(MA(t)/MA(t-L)-1)*60/L bp毎分。W/Lは60/30,180/30,300/60,600/60秒。角度既知かつ絶対値0.25以上で同方向へ新規。完了flat後10秒で再参加可。分足・ATR・未来値・場の終値方向は入力しない。"},
            "management": {"method": "初回比例は親完結まで数量固定。動的比例は約定後10秒以上・未約定なしで現在の保有方向傾きへ数量を合わせる。弱化/逆符号でも最低1枚、未知なら増減停止。全返済を数量変更より優先。親初回の判断傾き、最初の実約定建値、防御線・最高順行幅・同方向最高傾きは追加でリセットしない。"},
            "exit": {"method": "当場最初の正常中値基準12bp逆行で防御、6bp順行後3bp戻りで全返済。Tは価格のみ。Zは傾き0/反転を追加。Dは初回同方向傾き2倍到達後の最高傾き半減も追加。終場10分前に全返済。部分数量縮小はFIFO。途中場は仮精算せず実現と含みを別記。"},
            "allocation": {"products": {"NK225mini": {"cap": 10, "point_value": 100}, "TOPIXmini": {"cap": 10, "point_value": 1000}}, "method": "q=1+floor(9*clamp((保有方向v-0.25)/2.25,0,1))。新規は絶対vで同式。常に1枚/10枚の対照は180/30秒・D出口・初回固定と同一経路のみ。数量を含む予約上限10枚、同時両建てなし。"},
            "costs": {"fee": 0, "spread": "手数料は最新指定により0。判断次正常ラージ板の買Ask/売Bidを使用し、気配差は含む。mini実約定や板を食う影響は未計測。"},
            "execution": {"method": "逐次原行、次正常行で全量約定。同価格時計行も原行順を維持。有限0<bid<askを正常とし、現在値約定時刻は実受信時計ではない。最大120秒の直前正常気配保持、不正行/長欠測の未知区間を含むMAは使わない。時価損益と親・分割返済会計を独立検算。"},
            "data": {"sessions": [s["session"] for s in scenes], "input_manifests": inputs, "scope": "両市場51完了場。既知10/26ナイト21:13:52未満は別枠の途中参考。全保存資料は既知開発データ。現在API取得0。昼夜・上昇下落・US前後を分け、無取引、典型損失と上位3黒字除外を評価。"},
            "implementation": {implementation.relative_to(ROOT).as_posix(): reference(implementation)["sha256"]},
        },
    }
    plan_path = HERE / "再生計画153.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("研究153の試行管理", manager_path)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    preflight = manager.analyzer().analyze(plan, [])
    assert preflight["proposal_complete"], preflight
    focused = {"rules": {"rules": []}, "knowledge": {"findings": []}, "trials": {"trials": [plan], "repetition_audit": []}, "studies": {"studies": []}}
    manager.validate(focused, deep=True)
    print("26条件・実装・入力を固定。既試行との照合登録を開始。", flush=True)
    record = manager.store_trial(plan)
    (HERE / "事前照合153.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": TRIAL_ID, "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "plan": reference(plan_path), "implementation": reference(implementation), "inputs": inputs, "sources": source_refs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("登録完了。指紋照合後だけ金融再生可能。", flush=True)


if __name__ == "__main__":
    main()
