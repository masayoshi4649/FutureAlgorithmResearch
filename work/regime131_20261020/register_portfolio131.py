"""旧核と初回追加の条件を別巡に固定する。金融実行は行わない。"""

import argparse
import importlib
import subprocess
import sys
from pathlib import Path
from common131 import HERE, ROOT, BASE, read, reference, save


TRIAL_ROOT = ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合"
ALLOCATION = {
    "旧核": {"TOPIXmini": 5, "NKmicro": 10},
    "独立初回追加": {"TOPIXmini": 5, "NKmicro": 10, "各場の最大親数": 1},
    "片方向同時保有上限": {"TOPIXmini": 10, "NKmicro": 20},
    "同時保有": "旧核の後続新規と追加親の並行保有を許す。買いと売りを別々に合算して上限検査。",
}


def resolve_input(value, prefer_here=True):
    """
    機能: 明示入力の位置をプロジェクト内の既存ファイルへ解決する。
    引数: value(str)は絶対又は相対位置、prefer_here(bool)はwork131相対を先に試す指定。
    返り値: Pathはプロジェクト内の既存ファイル。
    """
    item = Path(value)
    roots = (HERE,ROOT) if prefer_here else (ROOT,HERE)
    candidates = [item] if item.is_absolute() else [root/item for root in roots]
    for candidate in candidates:
        path = candidate.resolve()
        if path.is_file() and path.is_relative_to(ROOT):
            return path
    raise AssertionError("入力ファイルが存在しないか対象外: "+str(value))


def comparison_ids(reason):
    """
    機能: 比較元が正式な既存試行IDであることを固定計画の保存前に確認する。
    引数: reason(dict)はcompares_toを含む変更理由。
    返り値: list[str]は実台帳に存在する比較元ID。
    """
    selected = reason.get("compares_to")
    assert isinstance(selected,list) and selected and all(isinstance(x,str) for x in selected)
    document = read(TRIAL_ROOT/"data/trials.json")
    trials = document["trials"] if isinstance(document,dict) else document
    known = {row["id"] for row in trials}
    assert len(selected) == len(set(selected))
    assert set(selected).issubset(known), "比較元は正式な既存試行IDが必要: "+str(sorted(set(selected)-known))
    return selected


def prepare(args):
    """
    機能: 源・理由・旧会計・人工証拠を固定し、登録用の提案を新規保存する。
    引数: args(argparse.Namespace)は巡名・runner・条件・理由・人工・入力の明示指定。
    返り値: Pathは試行計画JSON。登録・金融再生は呼ばない。
    """
    folder = (HERE/args.round).resolve()
    assert folder.is_relative_to(HERE) and folder != HERE
    config_path = resolve_input(args.configs)
    reason_path = resolve_input(args.reason)
    configs, reason = read(config_path), read(reason_path)
    assert len(configs) == 8, "第二巡は金融前に指定した8条件を固定する"
    assert len({c["id"] for c in configs}) == len(configs)
    compare = comparison_ids(reason)
    proof_paths = [resolve_input(p) for p in args.proof]
    for path in proof_paths:
        assert read(path).get("passed") is True, path
    artificial = [reference(p) for p in proof_paths]
    # ----------------------------------------
    # 旧核・現在までの参加判定・追加核を結ぶ源はrunnerと同じ指紋で固定する。
    sources = importlib.import_module(args.runner).sources()
    assert sources
    for path,digest in sources.items():
        assert reference(ROOT/path)["sha256"] == digest
    input_paths = [BASE/"入力準備.json",config_path,reason_path,Path(__file__).resolve()]
    input_paths += [resolve_input(p,False) for p in args.input]
    input_paths += [resolve_input(p,False) for p in reason.get("extra_input_paths",[])]
    inputs, seen = [], set()
    for path in input_paths:
        ref = reference(path)
        if ref["path"] not in seen:
            inputs.append(ref)
            seen.add(ref["path"])
    quantity = reason.get("quantity",
        "旧核TOPIXミニ5枚・日経マイクロ10枚＋独立初回追加5枚・10枚を最大1親。片方向最大10枚・20枚。")
    fixed = dict(
        configs=configs,rationale=reason,sources=sources,artificial=artificial,
        input_references=inputs,quantity=quantity,allocation=ALLOCATION,
        fees="片道TOPIXmini41.8円・NKmicro11円。実注文ごと円未満切捨て。新旧の親を合算して端数変更しない。",
        execution="判断後の次正常原行ラージBBOの全量約定代理。場内全返済。現在値時計と実受信時計は異なる。",
        participation="固定した期限以後、当原行までの旧核の実新規約定数が0なら独立追加を最大1親。将来の無取引・終値・損益は不使用。",
        accounting="旧核単独・追加単独・合算を保持。原注文から円会計を再構成し、未返済料金は各親の残数量で別々に控除。",
        scope="全43場は既知開発資料。全場参加は必須だが利益安定性の証明ではない。第一巡より片方向上限が増える比較。",
    )
    save(folder/"固定計画.json",fixed)
    ref = reference(folder/"固定計画.json")
    proposal = dict(
        id="131_"+args.round+"_旧核維持と独立初回参加",
        name="旧核を維持した独立初回参加 "+args.round,
        purpose="新仮説",question=reason["question"],change=reason["change"],
        repeat_reason=reason["repeat_reason"],compares_to=compare,evidence=[ref],
        spec=dict(
            entry={"固定計画":ref,"条件":[c["id"] for c in configs],"初回参加":fixed["participation"]},
            management={"変更":reason["change"],"会計":fixed["accounting"]},
            exit={"固定計画":ref,"場内全返済":True},
            allocation=ALLOCATION,
            costs={"TOPIXmini":41.8,"NKmicro":11.,"端数":"新旧それぞれの実注文ごと円未満切捨て"},
            execution={"説明":fixed["execution"]},
            data={"input_manifests":inputs,
                  "sessions":[r["session"] for r in read(BASE/"入力準備.json")["packets"]],
                  "範囲":fixed["scope"]},
            implementation=sources,
        ),
    )
    proposal_path = folder/"試行計画.json"
    save(proposal_path,proposal)
    return proposal_path


def main():
    """
    機能: 明示CLI呼出しで固定計画を作り、必要なら重複照合・正式登録を行う。
    引数: --round/--configs/--reason(str)、--proof(str複数)、--input(str複数)、
          --runner(str既定run_portfolio131)、--prepare-only(bool)は登録をせず計画保存に限る。
    返り値: None。金融runは呼ばない。既存の計画・証拠の上書きは禁止する。
    """
    parser = argparse.ArgumentParser()
    for name in ("round","configs","reason"):
        parser.add_argument("--"+name,required=True)
    parser.add_argument("--runner",default="run_portfolio131")
    parser.add_argument("--proof",nargs="+",required=True)
    parser.add_argument("--input",nargs="*",default=[])
    parser.add_argument("--prepare-only",action="store_true")
    args = parser.parse_args()
    proposal = prepare(args)
    if args.prepare_only:
        print("固定計画のみ保存。登録・金融実行なし。",flush=True)
        return
    for command,name in (("check","照合.json"),("register","登録.json")):
        result = subprocess.run(
            [sys.executable,"-B","-X","utf8",str(TRIAL_ROOT/"manage.py"),command,"--proposal",str(proposal)],
            cwd=ROOT,capture_output=True,text=True,encoding="utf-8",
        )
        save(proposal.parent/name,dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        print(command,result.returncode,flush=True)
        assert result.returncode == 0,result.stderr[-2000:]


if __name__ == "__main__":
    main()
