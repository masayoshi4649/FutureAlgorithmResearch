"""確定源と金融0の人工証跡を照合して事前監査を保存する。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "work/research164"
AUDIT = HERE / "audit"


def sha(path: Path) -> str:
    """ファイルの内容指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path: Path) -> dict:
    """根拠の相対パスと内容指紋を作る。

    引数: path(Path)。返り値: dict。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path))


def main() -> None:
    """人工検査時の源との一致を条件に事前監査を一度だけ保存する。

    引数: なし。返り値: None。売買再生・登録・APIは実行しない。
    """
    result = json.loads((AUDIT / "最終人工独立検査164.json").read_text(encoding="utf-8"))
    assert result["passed"] and result["source_unchanged"] and result["financial_replays"] == 0
    for item in result["sources"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    assert not list((HERE / "results").glob("*/*.json"))
    assert not (HERE / "登録受領164.json").exists()
    engine = [p for p in (HERE / "engine").rglob("*") if p.is_file() and p.suffix in {".go", ".mod", ".sum", ".toml", ".json"} and "testdata" not in p.parts]
    files = engine + [HERE / name for name in ("inputs164.json", "計画164.md", "control164.py", "prepare164.py", "test_control164.py")]
    files += [p for folder in ("day_design", "night_design") for p in (HERE / folder).glob("*") if p.suffix in {".md", ".json"}]
    files += [AUDIT / name for name in ("independent164_test.go", "run_independent164.py", "finalize_preflight164.py")]
    configs = json.loads((HERE / "engine/configs164.json").read_text(encoding="utf-8"))
    assert len(configs) == 20 and len({x["id"] for x in configs}) == 20
    definition = json.loads((HERE / "day_design/spec_day164.json").read_text(encoding="utf-8"))
    for item in definition["sources"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    value = dict(passed=True, created_at=datetime.now().astimezone().isoformat(), financial_runs=0,
        new_financial_replays=0, registered=False, sources=[record(p) for p in sorted(set(files))],
        methods=20, scopes={s:sum(c["scope"] == s for c in configs) for s in ("Day", "PreUS", "PostUS")},
        synthetic_tests=dict(go=result["test_count"], independent_go=len(result["independent_tests"]), python_control=4,
            connection_scenes=40, connection_cases=400, connection_is_synthetic=True),
        evidence=[record(AUDIT / name) for name in ("最終人工独立検査164.json", "日中正本源差分164.json", "入力目録の独立確認164.json", "既知証拠と四不満の監査設計164.md")],
        checked=[
            "日中00は00157第二巡J02のstep157を直接使用。65旧依存のうち64不変、mainは型メタと実行入口分離のみ",
            "Actual所有IDと実建値で利益床を判断しCanonical同量同期。異なる元部分返済配賦後も二重返済・再新規なし",
            "Source終了・待機取消・生存SourceID配賦、半量0注文禁止、追加だけ停止、買売鏡像と予約込み片方向上限",
            "夜のRは注文判断時固定、返済予約を危険予算から控除しない。利益床0でも次正常板の損失を計上",
            "夜の新規と再armは各価格時計最初の正常板。未知を弱さへ代入しない。退出は全正常原行",
            "夜の長窓は正常観測標本、異常と空白を品質別記。短窓端点1秒、日中端点15秒を混同しない",
            "夜P05/D07は前後別所有状態、全通知・数量十倍・Targets・判断約定原行・価格・収支を本実行時も照合",
            "Go実生成JSONを制御器へ接続し全条件構造・場時計・原ファイル差替え拒否を確認",
            "20固定ID、前40の3区分別選択、確認14の許可とSHA、各場6原資料の実行前後指紋ゲートを読取確認"
        ],
        limitations=[
            "金融成績は未計測。人工の合格は利益・四不満改善・実運用約定を保証しない",
            "旧53場は既知開発。追加10月27日夜も1場の確認であり長期未見保証ではない",
            "価格時計は受信時計ではなく同時計内の大きな気配変化があり得る。ラージBBO代理でmicro実執行を保証しない",
            "全54原資料の最新内容SHA再照合は金融driverの実行前後ゲートで行う。今回目録監査は旧53定義不変と追加1場6原資料の読取照合",
            "日中短窓は端点15秒許容、夜は1秒許容という異なる定義。夜の標本ERは完全連続価格経路ではない",
            "追加の失敗例原板会計、全場D00/旧J02同値とP/U00/旧源同値、全原板時価の独立検算は金融完了後に実施"
        ])
    path = AUDIT / "preflight164.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=True, sources=len(value["sources"]), sha256=sha(path), financial_runs=0), ensure_ascii=False))


if __name__ == "__main__":
    main()
