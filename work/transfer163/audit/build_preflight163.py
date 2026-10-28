"""00163の固定源・人工検査・入力分割を金融前の監査証跡へまとめる。"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def read(path: Path):
    """小さい監査資料を読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path: Path) -> dict:
    """相対パスと現在の内容指紋を返す。

    引数: path(Path)。返り値: dict[str,str]。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    """人工合格と源不変を確認し、初回preflightだけを新規保存する。

    引数: なし。返り値: None。金融実行・登録・巨大正本読取はしない。
    """
    target = HERE / "preflight163.json"
    assert not target.exists(), "確定済みの監査証跡を上書きしません"
    independent = read(HERE / "独立人工検査163.json")
    assert independent["passed"] and independent["source_unchanged"]
    assert independent["financial_runs"] == independent["existing_fixture_runs"] == 0
    for row in independent["sources"]:
        assert fingerprint(ROOT / row["path"])["sha256"] == row["sha256"], row["path"]
    control = read(HERE / "制御人工163.json")
    assert control.get("passed") is True
    joined = read(HERE / "Go制御結合163.json")
    assert joined.get("passed") is True

    # ----------------------------------------
    # 数量条件、未来情報を除いた入力項目、時系列の場数を別に確認する。
    expected = {"B00", "C50", "D40", "D80", "G40", "G80", "R40", "R80", "E40", "E80"}
    configs = read(WORK / "engine/configs163.json")
    assert len(configs) == 10 and {x["id"] for x in configs} == expected
    manifest = read(WORK / "inputs163.json")
    scenes = manifest["sessions"]
    assert len(scenes) == 53 and len({s["session"] for s in scenes}) == 53
    assert [s["start"] for s in scenes] == sorted(s["start"] for s in scenes)
    counts = {split: sum(s["split"] == split for s in scenes) for split in ("train", "validation", "test")}
    assert counts == {"train": 30, "validation": 10, "test": 13}
    assert {kind: sum(s["kind"] == kind for s in scenes) for kind in ("Day", "Night")} == {"Day": 27, "Night": 26}
    allowed = {"session", "kind", "start", "us_open", "force_close", "end", "cutoff", "partial", "books", "candles", "fingerprints", "split"}
    for scene in scenes:
        assert set(scene) == allowed
        assert scene["end"] - scene["force_close"] == 600 and not scene["partial"]
        files = set(scene["books"].values())
        files |= {p for group in scene["candles"].values() for p in group.values()}
        assert len(files) == len(scene["fingerprints"]) == 6
        assert files == {x["path"] for x in scene["fingerprints"]}
    assert not list((WORK / "results").glob("*/*.json")), "金融前に相場成果が存在します"

    files = [p for p in (WORK / "engine").rglob("*") if p.is_file() and (p.suffix in {".go", ".toml", ".json", ".md"} or p.name in {"go.mod", "go.sum"})]
    files += [WORK / name for name in ("計画163.md", "inputs163.json", "prepare163.py", "register163.py", "allow163.py", "freeze163.py", "complete163.py", "test_control163.py")]
    files += [HERE / name for name in ("independent163_test.go", "人工予約補助163.go", "run_independent163.py", "build_preflight163.py", "独立人工検査163.json", "制御人工163.json", "Go制御結合163.json", "初巡10案の監査観点163.md")]
    files.append(ROOT / independent["log"])
    output = {
        "passed": True,
        "created_at": dt.datetime.now().astimezone().isoformat(),
        "scope": "固定10案の金融前独立監査。人工入力のみであり収益性の検査ではない。",
        "new_candidate_financial_replays": 0,
        "existing_fixture_replays": 0,
        "sources": [fingerprint(p) for p in sorted(set(files))],
        "artificial_tests": independent["passed_tests"],
        "control_tests": control,
        "source_bridge": "初回のみ隔離helperで通常予約へ人工投入。S01/P05/D07各買売で本体OnFill/OnOrderDone、通常返済、P05親補完、全10政策へ接続しB00元同額とC50半額を確認。入口確度の測定ではない。",
        "resolved": [
            "実玉0後の同campaign新SourceIDを永久終了扱いしない。終了済みSourceID自体は復元しない。",
            "capacityの0切下げ値で超過を検査せず、保有と新規予約を直接計数する。",
            "原資料六ファイルのパス集合と内容SHAを場の読取前後で検査する。",
        ],
        "checked": [
            "元初回・追加・返済のB00同額/C50厳密半量、現在SourceID残数以内の復元",
            "元返済優先、静観/終了、減量/復元各1回、縮小時源追加、同親再開",
            "親初回約定中値固定、実減量後極値、円/実時間換算、過去端1秒の既知/未知",
            "次正常原行・異常BBO・同秒後続、買売鏡像、各側100と予約、全玉時価",
            "前40場の昼夜別選択凍結、後13場を全10で確認、F00は固定昼夜の場行のみ連結",
            "段階許可/登録/源SHA/原資料SHAの不一致を拒否、Source本体への実損益逆流なし",
        ],
        "limits": [
            "全53場は既知開発資料。後13場を完全未見の外部実証とは呼ばない。",
            "価格時計は受信時計ではない。保存原行の順序と実際の到着間隔を同一視しない。",
            "Sourceの15:35/05:50判断と次気配を維持し、00162の場末6分代理へ変更しない。",
            "1秒端点資格による不発を方向支持の欠如や予測精度の改善としない。",
            "micro100相当による半量の整数処理。mini整数での端数丸め効果は別途未測定。",
        ],
        "input_counts": counts,
    }
    with target.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "sources": len(output["sources"]), "artificial_tests": len(output["artificial_tests"]), "path": target.relative_to(ROOT).as_posix(), "sha256": fingerprint(target)["sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
