"""追加二場を既公開の八選択へ固定条件で適用する計画を事前照合・登録する。"""

import json
from pathlib import Path
import subprocess
import sys

from run_update126 import HERE, ROOT, SESSIONS, configurations, read, save, sha, source_map


TRIAL = "126_追加二場を八公開選択へ条件不変で適用_20261020"
MANAGER = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"


def reference(path: Path) -> dict:
    """
    機能: 源・準備・監査資料の位置と内容指紋を結び付ける。
    引数: path(Path)は確定済み資料。
    返り値: dictは相対位置とＳＨＡ２５６。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path))


def main() -> None:
    """
    機能: 数値条件を変更せず追加二場だけを新データ試行として金融前に登録する。
    引数: なし。
    返り値: None。旧会計の再生・注文実行・現在ＡＰＩ取得を行わない。
    """
    manifest_path = HERE / "追加二場の非金融入力準備.json"
    artificial_path = HERE / "audit/新所有核と八公開選択の人工継承最終確認.json"
    input_audit = HERE / "audit/追加二場の入力と時計及び場内終端の独立監査.json"
    manifest, artificial, audited = map(read, (manifest_path, artificial_path, input_audit))
    assert manifest["passed"] and manifest["sessions"] == list(SESSIONS)
    assert artificial["passed"] and audited["passed"]
    sources = source_map()
    assert artificial["sources"] == sources
    for name, value in manifest["sources"].items():
        assert sha(ROOT / name) == value
        assert name not in sources or sources[name] == value
        sources[name] = value
    sources[Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    prior = HERE.parent / "最終統合の価格モデル別比較と公開会計.json"
    assert read(prior)["passed"] and len(read(prior)["sessions"]) == 41
    fixed = dict(sources=sources, input_manifest=reference(manifest_path),
                 artificial=reference(artificial_path), input_audit=reference(input_audit),
                 prior_results=[reference(prior)], specs=configurations(),
                 evidence=[reference(HERE / "終了済み追加二場の取得.json"),
                           reference(HERE / "数値源の同bytes接続.json"), reference(input_audit)],
                 conditions_changed=False, previous_sessions_replayed=0,
                 selection="旧41場で決めた第一候補GU_Q・次善G_Qを維持。追加成績で閾値を選び直さない。")
    save(HERE / "固定計画.json", fixed)
    proposal = dict(id=TRIAL, name="Ｅ０１改修の公開八選択へ追加二場を条件不変で適用", purpose="新データ",
        question="既公開の第一候補ＧＵ＿Ｑ・次善Ｇ＿Ｑと比較元は、追加二場でどの損益となるか。",
        change="2026年10月19日ナイトと20日デイだけを追加。元41場は保存結果を引用し、数値条件・数量・手数料・約定模型は変更しない。",
        repeat_reason="ユーザーが追加二場で既存ＨＴＭＬの更新を依頼。日経の不足生板は既存取得ツールの共有保存元の終了済みファイルを専用領域へ取得。過去同一入力の金融再生はしない。",
        compares_to=["126_GGU低R利益床と公開気配予算の五十三対照"],
        evidence=[fixed["input_manifest"], fixed["artificial"], fixed["input_audit"], *fixed["prior_results"]],
        spec=dict(entry="原Ｅ０１の元十列・二市場方向と短期支持。Ｇは既知の両市場開始条件再確認、Ｕは既知の米国開始前後15分静観、Ｑは通知公開時の固定初回ＡＴＲ半分の気配予算。",
            management=dict(configs=fixed["specs"], selection=fixed["selection"], changes=False),
            exit="元Ｅ０１の通常影と出口影・半量利確・悪化半減・段階トレーリング・最大360分を維持。次正常原行ＢＢＯは実建値予算と全返済を元数値核で再判定。",
            allocation="ＴＯＰＩＸミニ初回5枚・片方向上限10枚。日経マイクロ初回10枚・上限20枚。追加・復元なし。",
            costs="手数料0円。主表示はラージ板代理の次正常原行ＢＢＯ、買ask・売bid。参考Last三選択を別表示。",
            execution="旧数値核を完全同bytes複写して使用。紙上通知3種と実気配5種を分離。同一商品場の同一通知・数値方策だけ保存引用し、引用と新金融の件数を分ける。全玉場内返済。",
            data=dict(input_manifests=[fixed["input_manifest"]], sessions=list(SESSIONS),
                original_market_writes=0, historical_source="ローカル追加足とＴＯＰＩＸ板、共有保存元の終了済み日経板。現在ＡＰＩ取得なし。",
                previous_results=fixed["prior_results"], previous_sessions_replayed=0),
            implementation=sources))
    save(HERE / "試行計画.json", proposal)
    trials = MANAGER.parent / "data/trials.json"
    (HERE / "登録前の試行台帳.json").write_bytes(trials.read_bytes())
    for command, name in (("check", "事前照合の全出力.json"), ("register", "正式登録の全出力.json")):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(MANAGER), command,
            "--proposal", str(HERE / "試行計画.json")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        save(HERE / name, dict(終了コード=process.returncode, stdout=process.stdout, stderr=process.stderr))
        print(command, process.returncode, flush=True)
        assert process.returncode == 0, process.stderr[-1200:]


if __name__ == "__main__":
    main()
