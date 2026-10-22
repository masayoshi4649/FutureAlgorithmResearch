"""今回の接続を非金融で確認し、金融実行器が要求する全源の継承証拠を保存する。"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
UPDATE = HERE.parent
TASK = UPDATE.parent
ROOT = TASK.parents[1]
CHECKS = []
sys.dont_write_bytecode = True


def sha(path: Path) -> str:
    """
    機能: 小証拠又はソースの指紋を求める。
    引数: path(Path)は対象の位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 所有域内の小証拠JSONを読む。
    引数: path(Path)はJSONの位置。
    返り値: dictは保存内容。
    """
    assert path.resolve().is_relative_to(ROOT / "work")
    return json.loads(path.read_text(encoding="utf-8"))


def check(name: str, passed: bool) -> None:
    """
    機能: 接続に関する非金融条件の合否を記録する。
    引数: name(str)、passed(bool)は条件名と結果。
    返り値: None。不合格なら停止する。
    """
    assert bool(passed), name
    CHECKS.append(dict(name=name, passed=True))


def main() -> None:
    """
    機能: 数値核コピー・公開八条件・実行境界を確認し最終人工継承資料を作る。
    引数: なし。
    返り値: None。実市場入力本文、金融再生、ネットワークは利用しない。
    """
    target = HERE / "新所有核と八公開選択の人工継承最終確認.json"
    assert not target.exists()
    initial_path = HERE / "旧最終人工と現数値核の同bytes継承.json"
    input_path = HERE / "追加二場の入力と時計及び場内終端の独立監査.json"
    initial, input_proof = read(initial_path), read(input_path)
    check("旧数値核の人工継承合格", initial["passed"])
    check("追加入力独立監査合格", input_proof["passed"] and len(input_proof["accounts"]) == 4)
    for name, digest in initial["sources"].items():
        check("旧数値源不変_" + name, sha(ROOT / name) == digest)
    copy_path = UPDATE / "数値源の同bytes接続.json"
    copied = read(copy_path)
    check("数値源コピー合格", copied["passed"] and not copied["numerical_change"])
    check("旧116Pythonと小設定3を同bytes継承", len(copied["files"]) == 119 and
          sum(item["path"].endswith(".py") for item in copied["files"]) == 116)
    copied_map = {}
    for item in copied["files"]:
        source, destination = ROOT / item["source"], ROOT / item["path"]
        check("コピー域_" + item["path"], source.resolve().is_relative_to(TASK / "engine") and
              destination.resolve().is_relative_to(UPDATE / "engine"))
        check("旧新源同bytes_" + item["path"], sha(source) == item["sha256"] == sha(destination))
        copied_map[item["path"]] = item["sha256"]
    runner = UPDATE / "run_update126.py"
    runner_hash = sha(runner)
    tree = ast.parse(runner.read_text(encoding="utf-8"))
    top_calls = [node for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    check("接続moduleのimport時金融なし", not top_calls)
    spec = importlib.util.spec_from_file_location("update126_audit_connection", runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = module.source_map()
    for name, digest in copied_map.items():
        check("金融source_mapが全所有源を拘束_" + name, current[name] == digest)
    extras = {name: digest for name, digest in current.items() if name not in copied_map}
    expected_extras = {runner.relative_to(ROOT).as_posix()} | {
        (TASK / relative).relative_to(ROOT).as_posix() for relative in
        ("design/catalog126.py", "rearm126/adapter126.py", "gated_bbo126/catalog126g.py", "gated_bbo126/feed_filter126.py")}
    check("金融実行源は旧119と接続5のみ", set(extras) == expected_extras and len(current) == 124)
    for name, digest in extras.items():
        if name != runner.relative_to(ROOT).as_posix():
            check("外部4源は旧最終人工と同bytes_" + name, initial["sources"][name] == digest)
    configs = module.configurations()
    original = next(item for item in read(TASK / "固定計画.json")["specs"] if item["id"] == "E01")
    gated = {item["id"]: item for item in read(TASK / "gated_bbo126/固定計画.json")["specs"]}
    rearm = read(TASK / "rearm126/固定計画.json")["specs"]
    expected_paper = [original] + rearm
    gated["E01"] = dict(original, paper_source="E01", policy_id="E01", quote_gate_enabled=False)
    expected_bbo = [gated[name] for name in ("GU_Q", "G_Q", "E01", "G_E01", "GU_E01")]
    check("Last公開三選択は旧登録と完全同一", configs["paper"] == expected_paper)
    check("BBO公開五選択は旧登録と完全同一", configs["bbo"] == expected_bbo)
    check("追加二場だけに固定", module.SESSIONS == ("2026-10-19_Night", "2026-10-20_Day"))
    check("実行器も静的源mapも不変", module.source_map() == current and sha(runner) == runner_hash)
    reviewed = [
        "金融guardが成功登録implementation、source_map全源、入力目録指紋、人工継承全源、旧結果指紋を実行前に要求する。",
        "既存条件カタログからLast3とBBO5だけを取り、成績を読む条件選択や閾値追加を行わない。",
        "金融executeは新二場のpacket各一読だけを実行し、旧41場は保存結果指紋の確認に限る。",
        "通常影・出口影は旧関数へ委譲し、Qは公開通知行だけで採否を固定し次約定行を採否へ使用しない。",
        "GとGU紙上同値引用は商品場ごとに静観active・force・not_beforeの全配列一致を要求する。",
        "BBO同値引用のmemoは商品場ごとに初期化され、同入力の全feed・数値方策のeconomic_key完全一致だけを引用する。",
        "source126.ROOTとadapter126.ENGINE及びimport探索順を新所有核へ注入し、数値ファイル本文を変更しない。",
        "全返済・建玉上限・返済脚損益と親組損益・stats損益の一致を結果保存前に要求する。",
        "金融出力は新規領域へ保存し、既存measurementや開始証拠がある場合は再実行を拒否する。",
    ]
    result = dict(passed=True, sources=current, checks=CHECKS,
        source_proof=dict(path=initial_path.relative_to(ROOT).as_posix(), sha256=sha(initial_path)),
        input_proof=dict(path=input_path.relative_to(ROOT).as_posix(), sha256=sha(input_path)),
        copy_proof=dict(path=copy_path.relative_to(ROOT).as_posix(), sha256=sha(copy_path)),
        configurations=configs, static_independent_review=reviewed,
        scope="既存人工を同bytes数値核へ適用し新接続を独立レビュー。入力監査は別証拠。市場での有効性や金融後のFIFO会計検算はこの証拠の対象外。",
        original_market_reads=0, saved_market_body_reads=0, financial_replays=0,
        API=0, real_orders=0, producer_sha256=sha(Path(__file__)))
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, sources=len(current), checks=len(CHECKS),
                         output=target.relative_to(ROOT).as_posix(), sha256=sha(target)), ensure_ascii=False))


if __name__ == "__main__":
    main()
