"""先着率の確定結果を知見と調査一覧へ結び付ける。"""

from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "アルゴリズム調査"
NAME = "00160_日経の100円順行と50円逆行の先着"


def append(path: Path, text: str) -> None:
    """既存知見を保持したまま00160の測定を追加する。

    引数: path(Path)、text(str)。返り値: None。
    """
    old = path.read_text(encoding="utf-8-sig")
    assert "00160_" not in old
    path.write_text(old.rstrip()+"\n\n"+text.strip()+"\n", encoding="utf-8")


def main() -> None:
    """監査合格を必須にして、入口・出口の知見と案内を更新する。

    引数: なし。返り値: None。金融再生は行わない。
    """
    audit = json.loads((ROOT / "work/entry160/audit/audit160.json").read_text(encoding="utf-8"))
    assert audit["passed"] and audit["initial_entries"] == 304 and audit["label_checks"] == 912
    source = f"出典：[00160_日経の100円順行と50円逆行の先着](../../{NAME}/README.md)。"
    append(RESEARCH / "共通/知見台帳/入口.md", f'''<a id="00160_100円順行と50円逆行の先着を測る"></a>
## 初回後の100円順行と50円逆行の先着は約30%だった

{source}

2026/9/21〜10/27Day・53完了場の現行系統304初回。元のS01（日中166）、P05（夜前32）、D07（夜後106）の入口を変更せず、新規は次正常ラージAsk/Bid、評価は返済側Bid/Askで固定建値から＋100円と−50円の最初の原行を比較。50円ちょうどの逆行も失敗。元出口・米国切替後も同じ場の最終正常板まで追い、時間固定の保有は課さない。

日中48/166＝28.9%、夜前9/32＝28.1%、夜後35/106＝33.0%、全体92/304＝30.3%。212件は逆行先着、未到達0。元の支持帯別では高支持ほど単調に改善する関係は確認できず、小標本の100%を採用根拠にしない。入口価格もその後もLastだけの補助は122/304＝40.1%で、気配差込みと混ぜない。

これは保存観測上の先着率。初回から最初の到達まで不正気配行を跨ぐ111件、価格時計15秒超空白を跨ぐ146件があり、観測間の連続経路は保証できない。既知期間・数量無加重。全過去手法の最大能力や、100/50出口へ変更した戦略の損益ではない。J02型の同じ初回は重複標本に数えない。''')
    append(RESEARCH / "共通/知見台帳/出口.md", f'''<a id="00160_決済黒字と固定逆行幅を守る成功は違う"></a>
## 決済で黒字でも100円順行より先に50円逆行していた

{source}

日経53場304初回のうち、元初回玉の全返済が合計黒字は177件。100円順行より50円逆行が先だったのはそのうち89件。79件は最初の返済より前に50円以上逆行しており、元出口では最終的に黒字へ回復した。残る10件は元の全返済後に50円逆行が先着した仮想継続の値動きなので、実保有中の逆行に含めない。

早期利確・途中の逆行許容を含む決済勝率を、固定＋100/−50の入口成功確率へ置き換えない。元の出口を変えず事後採点した測定であり、出口変更後の再エントリー系列・数量配分・全体収支は未測定。''')
    for path, prefix in [(RESEARCH / "README.md", ""), (RESEARCH / "共通/知見台帳/README.md", "../../")]:
        original = path.read_text(encoding="utf-8-sig")
        assert NAME not in original
        text = f"最新：[00160 日経の100円順行と50円逆行の先着]({prefix}{NAME}/README.md)。現行系統304初回を原板順に採点。気配差込み92/304＝30.3%、Lastだけ122/304＝40.1%。決済勝率・最大順行との違いを整理しました。\n\n"
        path.write_text(text+original.replace("最新：", "前段：", 1), encoding="utf-8")
    path = RESEARCH / "index.html"
    original = path.read_text(encoding="utf-8-sig")
    assert NAME not in original
    article = f'''\n<!--
[コンポーネント概要]
作業00160の固定幅先着の測定へ案内します。
売買条件を変更せず、初回の入口確率だけを原板の発生順で測ったMarkdownです。
-->
<article class="task latest"><div class="number">作業00160・入口の先着確率</div><h2>50円逆行する前に100円順行したか</h2><p>日経304初回を原板順に追跡。気配差込みの先着率は30.3%。決済勝率と混同せず、昼夜別に示します。</p><a class="button" href="{NAME}/README.md">先着率と測定条件</a></article>
'''
    path.write_text(original.replace('<main id="work-list">', '<main id="work-list">'+article, 1), encoding="utf-8")
    paths = [RESEARCH / NAME / "README.md", ROOT / "work/entry160/inputs160.json", ROOT / "work/entry160/先着の全件160.json",
             ROOT / "work/entry160/先着の集計160.json", ROOT / "work/entry160/audit/audit160.json",
             ROOT / "work/entry160/audit/元黒字と50逆行先着の位置160.json"]
    evidence = []
    for item in paths:
        with item.open("rb") as stream:
            evidence.append({"path": item.relative_to(ROOT).as_posix(), "sha256": hashlib.file_digest(stream, "sha256").hexdigest()})
    result = {"passed": True, "financial_replays": 0, "reason": "保存入口の採点。新規条件・数量・出口の再生成なし。", "evidence": evidence}
    (ROOT / "work/entry160/完了証跡160.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("入口の先着確率と決済勝率の区別を保存しました。")


if __name__ == "__main__":
    main()
