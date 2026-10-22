"""固定した比較を人工検査と結び、重複確認後に登録する。"""

import argparse
import importlib
import subprocess
import sys
from common130 import HERE, ROOT, BASE, PREV, read, save, reference, sha


def main():
    """
    機能: 条件・源・入力・費用・人工証跡を固定し、実金融再生前に登録する。
    引数: --round/--runner/--configs/--reason(str)、--proof(str複数)は固定資料。
    返り値: None。照合に失敗した場合は登録済みとはしない。
    """
    parser = argparse.ArgumentParser()
    for name in ("round", "runner", "configs", "reason"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--proof", nargs="+", required=True)
    args = parser.parse_args()
    configs, reason = read(HERE / args.configs), read(HERE / args.reason)
    folder = HERE / args.round
    proofs = [reference(HERE / p) for p in args.proof]
    for ref in proofs:
        assert read(ROOT / ref["path"])["passed"]
    sources = importlib.import_module(args.runner).sources()
    inputs = [reference(BASE / "入力準備.json"), reference(HERE / args.configs),
              reference(HERE / args.reason), reference(PREV / "最終全場比較_確定.json")]
    if "diagnosis" in reason:
        assert sha(ROOT / reason["diagnosis"]["path"]) == reason["diagnosis"]["sha256"]
        inputs.append(reason["diagnosis"])
    for path in reason.get("extra_input_paths", []):
        inputs.append(reference(ROOT / path))
    fixed = dict(sources=sources, configs=configs, rationale=reason, artificial=proofs,
                 input_references=inputs, quantity=reason["quantity"],
                 execution="判断後の次正常原行BBO、全量約定代理。床の値での約定保証なし。"
                           "価格時計と受信時計を同一視しない。",
                 fees="片道TOPIXmini41.8円/NKmicro11円、実注文枚数ごと円未満切捨て。",
                 known_data="全43場既知の開発資料。夜間21場を変更、日中は保存引用。")
    save(folder / "固定計画.json", fixed)
    fixed_ref = reference(folder / "固定計画.json")
    proposal = dict(id="130_" + args.round + "_夜間損失のなぜ三段階と再改善",
        name="夜間損失のなぜ三段階からの改修 " + args.round, purpose="新仮説",
        question=reason["question"], change=reason["change"], repeat_reason=reason["repeat_reason"],
        compares_to=reason["compares_to"], evidence=[fixed_ref],
        spec=dict(entry={"固定": fixed_ref, "条件ID": [c["id"] for c in configs]},
            management={"変更": reason["change"]}, exit={"固定": fixed_ref},
            allocation={"TOPIXmini": 5, "NKmicro": 10, "追加": False, "部分返済": "固定条件参照"},
            costs={"TOPIXmini": 41.8, "NKmicro": 11, "丸め": "実注文ごと円未満切捨て"},
            execution={"説明": fixed["execution"]}, data={"input_manifests": inputs,
                "sessions": [p["session"] for p in read(BASE / "入力準備.json")["packets"]],
                "既知範囲": fixed["known_data"]},
            implementation=sources))
    save(folder / "試行計画.json", proposal)
    manager = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    for command, name in (("check", "照合.json"), ("register", "登録.json")):
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(manager),
            command, "--proposal", str(folder / "試行計画.json")], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8")
        save(folder / name, dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
        print(command, result.returncode, flush=True)
        assert result.returncode == 0, result.stderr[-2000:]


if __name__ == "__main__":
    main()
