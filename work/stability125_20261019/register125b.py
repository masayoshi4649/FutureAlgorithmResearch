"""最低参加を持つ三家族の比較を金融再生前に固定し、重複を照合する。"""

from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
from prepare125 import ROOT,HERE
from run125b import read,save,sha
from catalog125 import specifications

TRIAL="125_通常数量で毎場参加する三家族と純方向の持替え"
MANAGER=ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"


def main(artificial: Path,input_audit: Path,zero_fee_audit: Path) -> None:
    """
    機能: 人工合格・入力と実装指紋を固定し、登録を済ませる。
    引数: artificial/input_audit(Path)は独立人工及び入力監査の証跡。
    返り値: None。金融は登録後の別工程に限定する。
    """
    assert read(artificial)["passed"] and read(input_audit)["passed"] and read(zero_fee_audit)["passed"]
    sources={p.relative_to(ROOT).as_posix():sha(p) for p in [HERE/name for name in ("engine125.py","catalog125.py","prepare125.py","run125b.py","register125b.py")]}
    inputs=HERE/"保存済み気配と先行確定足の八十二入力.json"
    bindings=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),artificial=True) for p in (artificial,input_audit,zero_fee_audit)]
    bindings.append(dict(path=inputs.relative_to(ROOT).as_posix(),sha256=sha(inputs)))
    fixed=dict(sources=sources,bindings=bindings,inputs=bindings[-1],specs=specifications())
    save(HERE/"固定計画_確定条件.json",fixed)
    proposal=dict(id=TRIAL,name="毎場の通常数量参加と三家族の純方向管理",purpose="条件比較",
        question="無取引で安定させた少額型と、両上限を貯めた両建て型を離れ、通常枚数で毎場参加し方向撤回と利益追尾を両商品に適用した場合の費用後損益はどうなるか。",
        change="全41場の既知開発。価格正常気配だけから確定分を再構成し、相手は一分厳密先行。ATRを使わず過去15個の分差分位尺度。三家族×四設定、半容量初回・条件順行追加・反対は旧玉返済後。30分未参加時の通常数量入口を別理由にする。",
        repeat_reason="新しい最低参加と経済的利益目標への仕様変更。旧E01完成会計、IV幅比較、格子NET/FLIPの同じ会計を再実行しない。初回登録はdata.input_manifestsキー欠落によりdeep validateで保存前停止、金融0。その固定資料を残し、登録書式修正と最新ユーザーのfee0/率定義を本接続へ明示した。純方向持替えと確定足尺度自体の既出を認め、今回の複合12仕様は未測定として登録。過去未整理分に重複なしとは宣言しない。",
        compares_to=["119_全玉清算教師と異なる戦略から場内安定黒字を探す","119c_小試行と当初リスクを増やさない順行追加の対照","120b_段階追尾の建玉保存反例を修正した境界検査付き再測定","124c_人工と金融のキャッシュを分離した少額E01追加検証"],
        evidence=bindings[:3],
        spec=dict(entry=dict(家族="A共通進行の押戻り再進行、B動く極値から反発/反落、C往復と追従の当時切替。詳細は凍結catalogとengine。",最低参加="各場開始30分まで通常新規なしなら場初観測値対現在値の符号で通常半容量。日定義の回答前に厳しい各場条件を比較する。欠測や注文未約定を実参加へ数えない。"),
            management=dict(仕様=specifications(),尺度="w=max(8観測呼値,過去15本の|一分差|75%点*3)。初回固定、停止線を不利へ拡大しない。",共通="上下鏡像・含み損全計上・反転は旧全返済後。根拠更新は分足公開時だけ、停止/利益追尾は毎原行。"),
            exit=dict(通常="新規は引け30分前で停止、引け6分前から返済予約。次正常原行で約定。途中は価格仮説撤回/初期逆指値/利益追尾。",代理="通常返済の次行が得られず残った場合、引け前6分以内最終BBOを専用proxy_flagで記録。窓不足は未返済を保存し、成功やnet0としない。"),
            allocation=dict(初回="TOPIX5mini、NK10micro。追加あり条件は順行一単位で残半容量を一度。",上限="TOPIX10mini、NK20micro。両建て貯留なし。",目標="各銘柄各セッション最低1回。利益幅=net/(上限枚数*倍率)、目標=場初採用価格*.005。全41場の価格比平均0.5%以上を別商品で評価。数量を増やしただけの達成としない。中央値・赤字場・最悪・上位3除外も表示。"),
            costs=dict(料金="2026-10-19の最新ユーザー指定に従い両商品とも手数料0。旧手数料込み結果と混同しない。",その他="気配差を収支に含む。5秒最悪悪化は入れず基礎モデルを先に検証。"),
            execution=dict(新規返済="判断rowより厳密に後の最初正常BBO。買ask・売bid。同clockでも後rowなら別観測として保持。",品質="初回/追加は判断と次行の双方でspread<=0.5w（fee=0）を要求。次行不成立は取消し、返済へは品質gateを置かない。期限参加も広気配は迂回しない。",限界="ラージ価格代理。実小型板/待ち順位/実受信時刻はない。相手足は公開時刻を一分遅らせて接続し、真の全市場受信順の証明とはしない。"),
            data=dict(input_manifests=[fixed["inputs"]],sessions=read(inputs)["sessions"],既知="全41場は既知開発、新未見holdout0。原本追加読取0、所有済み82気配の再利用。",options="124で検証した前場IV結果を保存。時計のない場中IV/Greeksを新しい秒特徴へ補完しない。"),implementation=sources))
    save(HERE/"試行計画_確定条件.json",proposal)
    for command,name in (("check","事前照合_確定条件の全出力.json"),("register","正式登録_確定条件の全出力.json")):
        proc=subprocess.run([sys.executable,"-B","-X","utf8",str(MANAGER),command,"--proposal",str(HERE/"試行計画_確定条件.json")],cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        save(HERE/name,dict(終了コード=proc.returncode,stdout=proc.stdout,stderr=proc.stderr))
        print(command,proc.returncode,flush=True);assert proc.returncode==0,proc.stderr[-1000:]


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--artificial",type=Path,required=True);parser.add_argument("--input-audit",type=Path,required=True);parser.add_argument("--zero-fee-audit",type=Path,required=True)
    args=parser.parse_args();main(args.artificial.resolve(),args.input_audit.resolve(),args.zero_fee_audit.resolve())
