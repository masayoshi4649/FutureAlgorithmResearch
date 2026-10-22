"""独立人工検査後に新しい比較だけを試行台帳へ登録する。"""

import argparse
import importlib
import subprocess
import sys
from common129 import HERE, PREV, ROOT, read, save, reference


def main():
    """
    機能: 数値源・条件・入力と独立検査を固定し、重複照合後に登録する。
    引数: --round/--runner/--configs/--reason(str)、--proof(str複数)は固定資料。
    返り値: None。登録が失敗した場合は金融再生へ進まない。
    """
    parser = argparse.ArgumentParser()
    for name in ("round", "runner", "configs", "reason"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--proof", nargs="+", required=True)
    args = parser.parse_args()
    folder = HERE/args.round
    configs, reason = read(HERE/args.configs), read(HERE/args.reason)
    proofs = [reference(HERE/p) for p in args.proof]
    for ref in proofs:
        assert read(ROOT/ref["path"])["passed"]
    source_map = importlib.import_module(args.runner).sources()
    refs = [reference(PREV/"入力準備.json"), reference(HERE/args.configs), reference(HERE/args.reason)]
    refs += [reference(ROOT/p) for p in reason.get("extra_input_paths", [])]
    fixed = dict(sources=source_map, configs=configs, artificial=proofs, input_references=refs,
        rationale=reason, known_data="全43場は既知開発資料。時系列前後半も未知外部検証ではない。",
        selection="両商品の赤字場率と最大赤字/平均黒字を主に比較し、無取引増加・上昇下落別・上位3場除外も併記。全場最良は開発上の参考。",
        execution="ラージ原行BBO代理、次正常原行、既存ATR公開時刻を維持。現在値時計と受信時計を同一視しない。",
        quantity=reason["quantity"])
    save(folder/"固定計画.json", fixed)
    fixed_ref = reference(folder/"固定計画.json")
    proposal = dict(id="129_"+args.round+"_チャートと板の失敗機構改善",
        name="チャート・板の具体的失敗を直す比較 "+args.round, purpose="新仮説",
        question=reason["question"], change=reason["change"], repeat_reason=reason["repeat_reason"],
        compares_to=reason.get("compares_to", ["128_round5_昼夜分離と損失原因による独立改善"]),
        evidence=[fixed_ref],
        spec=dict(entry={"条件ID": [c["id"] for c in configs], "固定": fixed_ref},
            management={"根拠": reason["change"]}, exit={"説明": "固定計画及び数値源。時刻終了で全返済。"},
            allocation=reason["allocation"],
            costs={"TOPIXmini片道": 41.8, "NKmicro片道": 11, "丸め": "注文単位円未満切捨て"},
            execution={"説明": fixed["execution"]},
            data={"input_manifests": refs, "sessions": [p["session"] for p in read(PREV/"入力準備.json")["packets"]],
                  "既知範囲": fixed["known_data"]}, implementation=source_map))
    save(folder/"試行計画.json", proposal)
    manager = ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    for command, name in (("check", "照合.json"), ("register", "登録.json")):
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(manager), command,
            "--proposal", str(folder/"試行計画.json")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        save(folder/name, dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
        print(command, result.returncode, flush=True)
        assert result.returncode == 0, result.stderr[-2000:]


if __name__ == "__main__":
    main()
