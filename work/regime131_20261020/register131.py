"""新しい条件と根拠を、金融再生前に共通の試行台帳へ登録する。"""

import argparse
import importlib
import subprocess
import sys
from common131 import HERE, ROOT, BASE, LAST, read, reference, save


def main():
    """
    機能: 条件・源・原資料・人工監査を固定し、重複照合して登録する。
    引数: --round/--runner/--configs/--reason(str)、--proof(str複数)は保存資料。
    返り値: None。照合失敗時は金融再生へ進まない。
    """
    parser = argparse.ArgumentParser()
    for name in ("round", "runner", "configs", "reason"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--proof", nargs="+", required=True)
    args = parser.parse_args()
    folder = HERE / args.round
    configs, reason = read(HERE / args.configs), read(HERE / args.reason)
    artificial = [reference(HERE / p) for p in args.proof]
    for ref in artificial:
        assert read(ROOT / ref["path"])["passed"]
    source = importlib.import_module(args.runner).sources()
    inputs = [reference(BASE / "入力準備.json"), reference(HERE / args.configs),
              reference(HERE / args.reason), reference(LAST / "最終全場比較_確定.json")]
    for path in reason.get("extra_input_paths", []):
        inputs.append(reference(ROOT / path))
    fixed = dict(configs=configs, rationale=reason, sources=source, artificial=artificial,
                 input_references=inputs, quantity=reason["quantity"],
                 fees="片道TOPIXmini41.8円・NKmicro11円。注文ごと円未満切捨て。",
                 execution="判断後の次正常原行ラージBBOの全量約定代理。場内全返済。現在値時計と受信時計は異なる。",
                 scope="43場すべて既知開発資料。無取引は勝ちでなく参加必須条件の未達。")
    save(folder / "固定計画.json", fixed)
    ref = reference(folder / "固定計画.json")
    proposal = dict(id="131_"+args.round+"_時間帯と値動き状態を切り替える全場参加",
        name="時間帯と値動き状態を切り替える全場参加 "+args.round,
        purpose="新仮説", question=reason["question"], change=reason["change"],
        repeat_reason=reason["repeat_reason"], compares_to=reason["compares_to"], evidence=[ref],
        spec=dict(entry={"固定計画":ref,"条件":[c["id"] for c in configs]},
            management={"変更":reason["change"]}, exit={"固定計画":ref},
            allocation={"TOPIXmini":5,"NKmicro":10,"追加":False},
            costs={"TOPIXmini":41.8,"NKmicro":11,"端数":"実注文ごと切捨て"},
            execution={"説明":fixed["execution"]},
            data={"input_manifests":inputs,
                  "sessions":[r["session"] for r in read(BASE / "入力準備.json")["packets"]],
                  "範囲":fixed["scope"]}, implementation=source))
    save(folder / "試行計画.json", proposal)
    manager = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    for command, name in (("check","照合.json"),("register","登録.json")):
        result = subprocess.run([sys.executable,"-B","-X","utf8",str(manager),command,
            "--proposal",str(folder / "試行計画.json")],cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        save(folder / name,dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        print(command,result.returncode,flush=True)
        assert result.returncode == 0,result.stderr[-2000:]


if __name__ == "__main__":
    main()
