"""第二巡の確定源と人工検査を照合し、金融0の事前証跡だけを保存する。"""
from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "work/research164"
HERE = WORK / "r2"
AUDIT = HERE / "audit"


def read(path):
    """UTF-8の保存JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """全バイトから指紋を算出する。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path):
    """根拠の相対パスと内容指紋を記録する。

    引数: path(Path)。返り値: dict。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path))


def main():
    """最終人工と第一巡不変を確認して新規証跡を保存する。

    引数: なし。返り値: None。登録・市場再生・APIは実行しない。
    """
    result = read(AUDIT / "最終人工独立検査164r2.json")
    assert result["passed"] and result["source_unchanged"] and result["financial_replays"] == 0
    for item in result["sources"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    prior = read(WORK / "登録受領164.json")
    for item in prior["sources"]:
        assert sha(ROOT / item["path"]) == item["sha256"], "第一巡登録源の変更"
    assert not (HERE / "登録受領164r2.json").exists()
    assert not list((HERE / "results").glob("*/*.json"))
    previous_scenes = read(WORK / "inputs164.json")["sessions"]
    current_scenes = read(HERE / "inputs164r2.json")["sessions"]
    assert len(previous_scenes) == len(current_scenes) == 54
    for before, after in zip(previous_scenes, current_scenes):
        assert {k:v for k,v in before.items() if k != "previously_used"} == {k:v for k,v in after.items() if k != "previously_used"}
        assert after["previously_used"] is True, "第二巡の追加夜も既知資料"
    assert read(HERE / "inputs164r2.json")["known_after_first_round"]
    configs = read(HERE / "engine/configs164r2.json")
    ids = {c["id"] for c in configs}
    old_ids = {c["id"] for c in read(WORK / "engine/configs164.json")}
    assert len(configs) == len(ids) == 12 and not (ids & old_ids)
    assert {s:sum(c["scope"] == s for c in configs) for s in ("Day", "PreUS", "PostUS")} == {"Day":4, "PreUS":4, "PostUS":4}
    for item in read(HERE / "day_design/spec_day164r2.json")["sources"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    files = [p for p in (HERE / "engine").rglob("*") if p.is_file() and p.suffix in {".go", ".mod", ".sum", ".toml", ".json"} and "testdata" not in p.parts]
    files += [HERE / name for name in ("inputs164r2.json", "計画164r2.md", "control164r2.py", "prepare164r2.py", "test_control164r2.py")]
    files += [p for folder in ("day_design", "night_design") for p in (HERE / folder).glob("*") if p.suffix in {".md", ".json"}]
    files += [AUDIT / name for name in ("independent164r2_test.go", "run_independent164r2.py", "finalize_preflight164r2.py")]
    # ----------------------------------------
    # 第一巡の固定候補を前40場の選択へ再利用する制御依存も凍結します。
    files += [WORK / name for name in ("control164.py", "登録受領164.json", "再生全完了164.json", "results/train_validation/再生完了164_train_validation.json")]
    value = dict(passed=True, created_at=datetime.now().astimezone().isoformat(), financial_runs=0,
        new_financial_replays=0, registered=False, methods=12, scopes={"Day":4,"PreUS":4,"PostUS":4},
        first_round_sources_unchanged=True, first_round_source_count=len(prior["sources"]),
        known_development=True, independent_unseen=False,
        sources=[record(p) for p in sorted(set(files))],
        evidence=[record(AUDIT / "最終人工独立検査164r2.json"),record(AUDIT / "r2_quantity_bound.json")],
        synthetic_tests=dict(go=result["test_count"], independent_go=len(result["independent_tests"]), python_control=4,
            connection_scenes=40, connection_cases=240, connection_is_synthetic=True),
        checked=[
            "日中4・夜前4・夜後4は新ID。第一巡20定義・源・会計を変更せず再利用",
            "日中Q0と元初回量の固定、現在支持とSource残/peakによる解除上限、以後係数の上限を買売・待機中増減で確認",
            "未知短期を失速へ転用せず、Source終了・取消後同親追加で実玉を復活させない",
            "夜の元Source部分返済を現在実残量へ比例配賦し、同原行の後順新玉へ残玉資格を先渡ししない",
            "Actual実建値と所有IDで床を判定し、次正常気配が床を飛び越えた損失をそのまま計上",
            "30秒ちょうどの再加速は解除可、超過取消。元Source影会計の更新と候補実玉を分離",
            "予約込み方向別上限、元返済優先、全完済、P/U実保有非重複は登録後の全保存会計でも検査",
            "新Go出力を前40の人工240条件場へ接続し、同ID条件・場時計・原資料差替えを拒否",
            "第一巡前40と第二巡前40だけで区分別選択。確認14は全て既知追加開発で、独立未見検証と呼ばない"
        ],
        limitations=[
            "金融結果は未計測。人工の成功は収益性、四不満改善、実注文の約定を保証しない",
            "原板は価格時計であり受信時計ではない。ラージBBO代理とmicro実約定は同一ではない",
            "短期5/15秒は実経過速度・端点最大15秒許容。未知・欠測と真の失速を区別",
            "元手法との全通知同値、原板全行の場内最小・最大下落、P/U実約定非重複は金融完了後に別証跡へ"
        ])
    path = AUDIT / "preflight164r2.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=True, sources=len(value["sources"]), sha256=sha(path), financial_runs=0), ensure_ascii=False))


if __name__ == "__main__":
    main()
