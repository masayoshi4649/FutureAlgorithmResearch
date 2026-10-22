"""昼夜の事前固定と既存試行の照合。金融実行は別コマンド。"""

import argparse
import importlib
import subprocess
import sys

from common128 import HERE, ROOT, OLD, read, save, reference
from catalog128 import catalog
from run128 import sources


def main():
    """
    機能: 条件・入力・人工証拠を固定し、重複照合と正式登録を行う。
    引数: --proof(str複数)は独立人工証拠、--round(str)は巡名。
    返り値: None。照合不成立時に金融へ進めない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof",nargs="+",required=True)
    parser.add_argument("--round",default="round1")
    parser.add_argument("--configs")
    parser.add_argument("--runner",default="run128")
    args = parser.parse_args()
    folder = HERE/args.round
    proofs = [reference(HERE/p) for p in args.proof]
    for p in proofs:
        proof = read(ROOT/p["path"])
        assert proof.get("passed",proof.get("全合格",False))
    configs = catalog() if not args.configs else read(HERE/args.configs)
    refs = [reference(HERE/"入力準備.json"),reference(OLD/"gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json"),
        reference(OLD/"update_20261020/追加二場の八公開選択会計.json")]
    if args.round != "round1":
        preceding = "round"+str(int(args.round[5:])-1)
        rationale = {"round2":"第二巡の変更根拠.json","round3":"第三巡の変更根拠.json",
            "round4":"第四巡の変更根拠.json","round5":"第五巡の変更根拠.json"}[args.round]
        refs += [reference(HERE/preceding/"全条件の会計.json"),reference(HERE/rationale),
                 reference(HERE/args.configs)]
    source_map=importlib.import_module(args.runner).sources()
    fixed = dict(sources=source_map,configs=configs,artificial=proofs,input_references=refs,
        selection="日中22場の前半11、夜間21場の前半10で固定選択。両商品黒字を優先し、次に両商品で低い方の黒字場率、高い方の最大赤字/平均黒字の小ささ、低い方の金額利益割合。後半で選び直さない。全場最良は開発上の参考と明記。",
        accounting="親完結の手数料後正負。初回TOPIXmini最大5枚/NKmicro最大10枚、第三巡は弱支持時2/4枚・3/6枚も比較。追加なし、場内返済",
        known_data="全43場は過去研究に使用済み。前後半は固定条件の時系列点検で、未知OOSではない。",
        duplicate_review=["00126のGQ入口・二市場反対の利益床・初回固定R停止",
            "00127の昼夜再集計","00060のレンジ拒否","00099の進行失敗入口","00119の順逆と時刻回避"],
        difference=("日中は発注行再確認・縮小だけの実損切り・20分中期失敗床。夜間は当場20分の固定帯、抜け失敗、定着、押し戻りを独立状態機械にし米開始前後で事前分岐。旧同じ売買は引用。"
            if args.round=="round1" else
            "第四巡の自己相手中期一致は日経を悪化させた。失効群の分類に基づき、自己中期の条件を足さず、準備時に要求した相手5分/20分支持だけを発注時に再確認する。各基準の出口は変更しない。"
            if args.round=="round5" else
            "夜間N16・N23・N24の出口を各々固定し、発注時の自己及び相手5分/20分方向再確認だけを追加。以前のN17/18は出口も同時変更していたため、未分離だった入口の単独効果を測る。"
            if args.round=="round4" else
            "第二巡の具体的損失診断後、日中は短期の静止と逆行を分ける入口・弱支持時の枚数縮小。夜は1R順行後の保護開始を主比較し、突破線からの距離制限は不支持仮説の反証対照。"
            if args.round=="round3" else
            "第一巡の具体的損失診断後、日中は自己・相手20分逆行だけの利益保護と縮小下限。夜は発注時120秒支持と5/20分再確認、2分出口撤去又は突破線退出、同方向失敗建値の更新待ちを単独・統合比較。"),
        unreviewed="過去全探索が完全に正規化されているとは主張しない。関連研究と法則を確認した範囲。")
    save(folder/"固定計画.json",fixed)
    fixed_ref = reference(folder/"固定計画.json")
    proposal = dict(id="128_"+args.round+"_昼夜分離と損失原因による独立改善",
        name="日中改修と夜間新造・"+args.round,purpose="新仮説",
        question="日中の尺度収縮と古い方向、夜の米国開始前後の構造差へ対処すると、両商品で負け場と損失を減らせるか",
        change=fixed["difference"],repeat_reason="既存保存会計にない固定帯状態機械と、日中の発注時再確認・尺度単調縮小を比較する。",
        compares_to=(["126_追加二場を八公開選択へ条件不変で適用_20261020"] if args.round=="round1"
                     else ["128_"+preceding+"_昼夜分離と損失原因による独立改善"]),
        evidence=[fixed_ref],
        spec=dict(entry={"固定計画":fixed_ref,"条件ID":[c["id"] for c in configs]},
            management={"根拠":fixed["difference"]},exit={"説明":"予定末尾全返済、次正常原行、動的保護と初期損切りは固定計画を参照"},
            allocation={"TOPIXmini初回":5,"NKmicro初回":10,"TOPIXmini上限":10,"NKmicro上限":20,"追加":False},
            costs={"TOPIXmini片道":41.8,"NKmicro片道":11,"丸め":"一注文円未満切捨て"},
            execution={"価格":"ラージ代理BBO、次正常原行、未来気配で取消しない","方向":"上下対称"},
            data={"input_manifests":refs,"sessions":[p["session"] for p in read(HERE/"入力準備.json")["packets"]],
                  "期間":"既知43場、Day22・Night21","前後半":fixed["selection"]},
            implementation=fixed["sources"]))
    save(folder/"試行計画.json",proposal)
    manager = ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    for command,name in (("check","照合.json"),("register","登録.json")):
        p = subprocess.run([sys.executable,"-B","-X","utf8",str(manager),command,"--proposal",
            str(folder/"試行計画.json")],cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        save(folder/name,dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
        print(command,p.returncode,flush=True)
        assert p.returncode == 0,p.stderr[-1500:]


if __name__ == "__main__":
    main()
