"""原版保持と独立人工を確認し、十六条件を金融前に固定登録する。"""

from pathlib import Path
import argparse
import subprocess
import sys
from common126 import ROOT, HERE, TRIAL, sha, read, save

sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE / "engine"))
sys.path.insert(0, str(HERE / "design"))
from source126 import sources
from catalog126 import catalog, specification

MANAGER = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"


def main(artificial: Path) -> None:
    """
    機能: 未使用部品の不変性を含む独立人工・入力・元会計を固定して登録する。
    引数: artificial(Path)は独立した純人工の最終合格証跡。
    返り値: None。金融結果を見る前に比較方法と選定順序を記録する。
    """
    proof = read(artificial)
    assert proof.get("passed", proof.get("全合格", False)), "最終人工が未合格です"
    manifest = HERE / "input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json"
    inputs = read(manifest)
    assert inputs["passed"] and len(inputs["packets"]) == 41
    source_map = {name: value for name, value in sources().items() if "/bbo_next/" not in name}
    for path in [HERE / name for name in ("common126.py", "run126.py", "register126.py", "baseline126.py", "analyze126.py")]:
        source_map[path.relative_to(ROOT).as_posix()] = sha(path)
    source_map[(HERE / "design/catalog126.py").relative_to(ROOT).as_posix()] = sha(HERE / "design/catalog126.py")
    binding_paths = [artificial, manifest,
        HERE / "input_audit/元E01の足公開と共同時計及び終端の独立人工.json",
        HERE / "design/原版E01の十六条件と単因子対照.json",
        HERE / "baseline/原版旧三十場の費用なし保存引用.json",
        HERE / "baseline/原版旧三十場の保存注文と返済.npz",
        HERE / "audit_artificial/相手厳密過去と窓端の独立純人工監査.json",
        HERE / "audit_artificial/通常影と出口影を区別した五分待機の最終純人工監査.json"]
    bindings = [dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p)) for p in binding_paths]
    selection = dict(比較単位="ＴＯＰＩＸミニ・日経マイクロを別々に評価。円合算順位で片側不調を隠さない。",
        優先順=["各商品各場の通常数量新規と全返済を満たす", "両商品のうち多い方の赤字場数を減らす", "最大赤字の通常黒字平均に対する倍率を小さくする", "両商品で中央値と上位三場利益除外後の収支が正", "上昇・下落区分の双方で収支と中央値を改善する"],
        利益規模="純収支/(上限枚数×円倍率)を場初価格で割った値を平均し、既存の０・五％目標も別確認。達成していなければ合格としない。",
        分類="先頭・末尾の保存Lastの符号。固定感度として絶対変動０・二五％以上を強い上下、それ以外を小変動。分類を取引には使わない。",
        既知範囲="全四十一場は既知開発。未見検証ではない。単一の最適選択を将来の安定性証明としない。")
    fixed = dict(sources=source_map, bindings=bindings, input=bindings[1],
        specs=catalog(), specification=specification(), selection=selection,
        counts=dict(new_financial_accounts=1252, reused_original_accounts=60, display_accounts=1312),
        separate_BBO="別実装・別人工・別登録。今回は原版の観測Last約定を維持した機構の比較であり、気配差を含んだ実約定成績とは呼ばない。",
        prepare_source_difference="素材準備後にpolicyのFIXED/INPUTS接続をbind_runtimeへ関数抽出。数値条件と保存特徴は不変。最終人工は抽出後の源を拘束する。")
    save(HERE / "固定計画.json", fixed)
    proposal = dict(id=TRIAL, name="原版Ｅ０１の損失後根拠更新と条件付き利益保護及び場予算", purpose="条件比較",
        question="原版Ｅ０１の数量と通常影を維持した上で、両市場悪化時だけの利益保護、損切り後の新進行、場全体の損失制限は両商品・両方向の赤字を減らすか。",
        change="旧三十場原版の同一保存結果を再利用し、新十一場の原版と十五改修を全四十一場で比較。mask0。無条件の狭い追尾、直ちに再参加、増玉は持ち込まない。",
        repeat_reason="ユーザーの原版Ｅ０１を基礎にした明示指定。既存の少額Ｅ０１やＧ／Ｕと混同しない。０００８１の無条件半分保全、０００８２の狭い追尾と早期再参加、００１２５の毎場強制参加と追加の失敗を踏まえ、新しい条件付き三部品を単独と統合で反証する。過去全試行の完全な重複不在は宣言しない。",
        compares_to=["125_通常数量で毎場参加する三家族と純方向の持替え"], evidence=bindings,
        spec=dict(entry="原版E01のEMA15/60維持方向と両市場一致、短期支持、初回固定ATR四分の一追跡。旧条件を変更しない。損失後の同方向だけ新anchor進行を指定する。",
            management=dict(specs=catalog(), theory=specification(), selection=selection),
            exit="原版の半量利確、悪化半減、出口影０・７５ATR、段階追尾、最大３６０分、場末終了。追加条件は利益床と場予算の次有効観測返済。",
            allocation="TOPIXミニ初回５・片方向上限１０、日経マイクロ初回１０・上限２０。追加及び復元なし。未参加を勝ちとしない。",
            costs="手数料０。今回は観測Last約定、BBO気配差は未反映。旧料金込み値は変更せず返済脚grossを引用する。",
            execution="原版Last価格の影と実枠を維持。新設利益床と場予算は次有効観測以降、相手は自己より厳密過去１５秒以内。原版の従前予約を現在判定で遡及取消しない。",
            data=dict(input_manifests=[bindings[1]], sessions=inputs["sessions"], original_market_reads=0,
                reuse="旧３０原版６０会計の売買と粗損益を完成台帳から引用。新１２５２会計だけ再生。旧３３入力信号を保持、追加８信号を所有足から原式で作成。"),
            implementation=source_map))
    save(HERE / "試行計画.json", proposal)
    for command, name in (("check", "事前照合の全出力.json"), ("register", "正式登録の全出力.json")):
        proc = subprocess.run([sys.executable, "-B", "-X", "utf8", str(MANAGER), command,
            "--proposal", str(HERE / "試行計画.json")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        save(HERE / name, dict(終了コード=proc.returncode, stdout=proc.stdout, stderr=proc.stderr))
        print(command, proc.returncode, flush=True)
        assert proc.returncode == 0, proc.stderr[-1200:]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artificial", type=Path, required=True)
    args = parser.parse_args()
    main(args.artificial.resolve())
