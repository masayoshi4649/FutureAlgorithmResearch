"""既知Ｇ・ＧＵの追加だけを、独立人工の後に第三段として登録する。"""

import argparse
from pathlib import Path
import subprocess
import sys

from adapter126 import HERE, WORK, ENGINE, catalog
from run_rearm126 import ROOT, read, save, sha

sys.path.insert(0, str(ENGINE))
from source126 import sources

MANAGER = ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
TRIAL = "126G_既知EMA入口再確認と米国開始静観の追加十一場"


def main(artificial):
    """
    機能: 旧源と最終人工・保存入力を固定し、四十四新会計だけを登録する。
    引数: artificial(Path)は独立したＧ・ＧＵ人工の成功証拠。
    返り値: None。登録成功しても金融実行器は起動しない。
    """
    proof = read(artificial)
    assert proof.get("passed", proof.get("全合格", False))
    material = read(HERE/"Ｇ再評価の非金融素材準備.json")
    gates = read(HERE/"追加十一場のＧ入口許可の非金融準備.json")
    assert material["passed"] and gates["passed"]
    source_map = {name:digest for name,digest in sources().items() if "/bbo_next/" not in name}
    for name in ("adapter126.py", "prepare_rearm126.py", "prepare_gates126.py", "run_rearm126.py", "register_rearm126.py"):
        path = HERE/name
        source_map[path.relative_to(ROOT).as_posix()] = sha(path)
    binding_paths = [artificial, HERE/"Ｇ再評価の非金融素材準備.json",
        HERE/"追加十一場のＧ入口許可の非金融準備.json",
        ROOT/gates["cache"]["path"],ROOT/material["baseline_cache"]["path"]]
    bindings = [dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)) for p in binding_paths]
    fixed = dict(sources=source_map,bindings=bindings,specs=catalog(),
        counts=dict(new_financial_accounts=44,reused_accounts=120,displayed_accounts=164),
        input=dict(path=bindings[1]["path"],sha256=bindings[1]["sha256"]),
        scope="旧Ｇ及びＧＵだけを追加十一場へ延長。新しい閾値・数量変更・時刻拡張なし。",
        fee_difference="旧playのlosspar生成直後へlosspar[12]=0を一文追加。他の同bytes原数値式を維持。旧30は当時実注文のgross引用。",
        output="ＧとＧＵの全四十一場会計.json164行、原版GとGUの全四十一場注文.npzで旧120＋新44通知を一元化。")
    save(HERE/"固定計画.json",fixed)
    proposal = dict(id=TRIAL,name="既知の両市場開始条件再確認と米国開始静観を最新十一場へ延長",purpose="条件比較",
        question="原版の古い維持方向へ入り直す問題を、既知の厳密開始条件再確認及び事前予定静観で改善できるか。",
        change="旧00081のＧ及びＧＵを同じ閾値で追加十一場へ適用。旧三十場百二十保存会計は引用だけとし、追加四十四を測定。",
        repeat_reason="原版十五改修後も損失が残り、既知Ｇの旧三十場では原版より粗収支が良かったため新十一場で確認。旧結果の再生はしない。全四十一場は既知開発で未見検証と呼ばない。",
        compares_to=["126_原版E01の二市場利益保護と損失後再参加及び場損失の十六対照"],evidence=bindings,
        spec=dict(entry=dict(規則="旧ＧのEMA15/60差/ATR×方向>0.15、EMA60の三本差/ATR×方向>0.02を自己と追加六十秒遅延相手の両方へ要求し、元十列の先頭stateだけをmaskする。確定一分足は開始百二十秒後に公開。"),
            management=dict(規則="原版の通常影と出口影、元の部分利確と一度の悪化半減を維持。通常影終了後五分の再参加。ＧＵだけ旧米国寄付き前後十五分を静観。"),
            exit=dict(規則="出口影の初期損失0.75ATR、二ATR部分利確、一・五ATRから三ATR追尾、三ATR後0.75ATR、三百六十分期限と場内返済を維持。"),
            allocation=dict(規則="TOPIXmini初回五枚、NK225micro初回十枚、片方向上限十枚・二十枚。追加と復元なし。無取引を勝ちに含めない。"),
            costs=dict(規則="最新指定の手数料零を制御変数へも明示。旧三十場は当時実注文のgrossを引用し料金込み記録を上書きしない。"),
            execution=dict(規則="旧観測Last約定を維持し、前行注文を優先する。BBO執行は後段の別会計。G/GU全四十一場の紙上通知を保存する。"),
            data=dict(input_manifests=[bindings[1],bindings[2]],sessions=material["all41"],
                規則="金融で新しく読むのは追加十一場packetと保存gate。事前準備だけ不足六原CSVを旧106SHA一致で各一読複写、後十六所有CSVを再利用。生板原本は読まない。"),
            implementation=source_map))
    save(HERE/"試行計画.json",proposal)
    for command, name in (("check","事前照合の全出力.json"),("register","正式登録の全出力.json")):
        proc = subprocess.run([sys.executable,"-B","-X","utf8",str(MANAGER),command,"--proposal",str(HERE/"試行計画.json")],
            cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        save(HERE/name,dict(終了コード=proc.returncode,stdout=proc.stdout,stderr=proc.stderr))
        print(command,proc.returncode,flush=True)
        assert proc.returncode == 0, proc.stderr[-1200:]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artificial",type=Path,required=True)
    args = parser.parse_args()
    main(args.artificial.resolve())
