"""00150の確定集計・原因診断を公開し、法則別の知見へ記録する。"""

import json
import os
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = "00150_D07の米国前しきい値緩和と開始前リセット"
PUBLIC = ROOT / "アルゴリズム調査" / NAME
EVIDENCE = PUBLIC / "根拠"
KNOWLEDGE = ROOT / "アルゴリズム調査/共通/知見台帳"


def money(value):
    """会計値を符号付きの万円へ整形する。

    引数: value(float)は円。返り値: strは万円単位の表示。
    """
    return f"{value / 10000:+.1f}万"


def append_once(path, marker, content):
    """既存記録を保持し、新しい法則だけ一度追記する。

    引数: path(Path)は対象、marker(str)は識別子、content(str)は本文。
    返り値: None。既に同じ識別子がある時は変更しない。
    """
    old = path.read_text(encoding="utf-8")
    if marker not in old:
        path.write_text(old.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


def publish_evidence():
    """根拠を複写し、各Markdownの相対リンクを公開先へ解決し直す。

    引数: なし。返り値: list[Path]は公開したファイル。実装・結果を変更しない。
    """
    names = [
        "engine仕様150.md", "engine追加仕様150.md", "engine_前半閾値の具体診断150.md",
        "engine_第二巡の具体診断150.md", "A01_具体的な売買比較.md", "A16_具体的な売買比較.md",
        "A01_前半の入口比較.png", "A16_前半の入口比較.png",
        "B04_具体的な売買比較.md", "B04_前半の入口比較.png",
        "data/時刻前後の診断要点150.md", "audit/東京寄付と米国寄付の比較.md",
        "audit/最終の20項目監査.md", "audit/最終会計の独立確認.json",
        "audit/第二巡の事前独立監査.md",
    ]
    pairs = {HERE / name: EVIDENCE / Path(name).name for name in names}
    for source, target in pairs.items():
        assert source.exists(), source
        if source.suffix != ".md":
            shutil.copy2(source, target)
            continue

        def rewrite(match):
            """元文書基準のリンクを公開先基準へ変換する。

            引数: match(re.Match)はMarkdownリンク。返り値: strは補正後リンク。
            """
            label, href = match.groups()
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^#", href):
                return match.group(0)
            location, separator, anchor = href.partition("#")
            actual = (source.parent / location).resolve()
            destination = pairs.get(actual, actual)
            relative = Path(os.path.relpath(destination, target.parent)).as_posix()
            return f"{label}({relative}{separator}{anchor})"

        body = re.sub(r"(!?\[[^\]]*\])\(([^)]+)\)", rewrite, source.read_text(encoding="utf-8"))
        if source.name == "engine_前半閾値の具体診断150.md":
            body = "初巡完了時の記録です。ここで挙げた次案の結果は[第二巡の診断](engine_第二巡の具体診断150.md)を参照してください。\n\n" + body
        target.write_text(body, encoding="utf-8")
    return list(pairs.values())


def findings():
    """今回確かめた法則と限界を、既存の分類へ割り当てる。

    引数: なし。返り値: list[dict]は追記先・識別子・本文。
    """
    source = f"出典：[{NAME}](../../{NAME}/README.md)。日経mini・片方向上限10枚・手数料0、既知25完了夜。"
    return [
        {"file": "入口.md", "marker": 'id="00150_効率緩和と現在方向"', "body": f'''
<a id="00150_効率緩和と現在方向"></a>

## 方向効率を緩めると準備を増やせるが、発注時の効率再確認が利益改善とは限らない

当時条件：公開済み1分末中値21点から、20分純変化の絶対値÷隣接変化の絶対値合計を算出。これは勝率でなく、一方向に残った移動の割合。売買方向は別の突破・二市場支持条件で決める。主担当通常入口を17時から許可したA00に対し、準備時の効率0.35→0.25のA01は前半25→29新規、収支−273,000→−102,000円。8夜改善・2夜悪化・15夜同じ。改善上位3夜を除く増分は−9,000円で、改善の分散安定性は未確認。

近隣0.20のB01は−172,000円、0.30のB02は−177,000円。いずれもA00より改善したが前半赤字。押戻りを浅く、再反発を小さく許すB04は38新規・16/25夜参加・前半−113,000円。新23条件は全て前半赤字で、現D07前半−2,000円を超えなかった。全夜は全条件で25/25夜参加。前半の無取引を勝ちに含めない。

A01へ発注直前の効率0.25再確認を足したB05は−141,000円。10/21の19:13:19売りを見送っても19:15:06に再度売り、同じ4万円損失。一方9/22の買い利益3.4万円と10/7の売り利益4.5万円が消え、10/1の買い損失4万円の回避だけでは補えなかった。結果を見た第二巡の開発比較であり、未見検証・方向的中率の測定ではない。{source}
''',},
        {"file": "継続.md", "marker": 'id="00150_準備と発注の再確認"', "body": f'''
<a id="00150_準備と発注の再確認"></a>

## 準備時の条件と発注時の条件を分け、見送り後の再発注まで追う

元D07主担当は効率を準備開始時だけ確認し、その後は準備寿命・境界破綻・押戻りと反発などを追う。A01の10/21売り入口の効率0.095は設定0.25未満だったが実装どおり。B05/B06は実発注直前も当時の効率を再確認し、未達行だけ発注を止め、準備は保持する条件にした。

B05は当該19:13:19の売り64,610を拒否。しかし19:15:06に効率0.404で売り64,560を行い、19:19:25の買い64,640で−40,000円。元A01も−40,000円で、対象損失の回避にはならなかった。B05は25夜中1改善・2悪化・22同額、合計−39,000円の悪化。B06も比較元B03から−76,000円悪化した。候補を一度拒否した回数を、防げた損失件数と読み替えない。

検査対象は未保有の準備・発注判断。保有後の現在効率による返済は今回未検証。準備の永久取消や新しい方向確認を足した別方式の効果も未測定。{source}
''',},
        {"file": "出口.md", "marker": 'id="00150_寄付直後の変動と静観"', "body": f'''
<a id="00150_寄付直後の変動と静観"></a>

## 米国寄付直後の変動拡大は観測できるが、前後一帯が一様に不利とは言えない

既知25夜で分末正常中値の絶対1分変化を場ごとに平均すると、US前15分15.0pt、直後15分34.8pt、次15分29.0pt。100pt以上の変化率は0.0%・5.1%・2.7%。直後と次15分の差は5.8pt、場単位の再標本化95%区間2.7〜9.1pt。US前後30分全体とその後30分は25.6/28.5pt。空分を補完せず、各原行を独立標本にしない。

対応する保存デイ25場のうち、東証現物の予定営業日21場を参考集計すると09:00直後59.9pt、次15分41.5pt。祝日取引の4場を現物寄付の実例に含めない。寄付の活発化は利幅と逆行幅の両方が拡大する観測であって、避ければ利益が増える証明ではない。

今回の全新23条件はUS15分前に全返済を判断し、次正常板で返済、未解消なら後半開始禁止。指標は保持し売買状態を初期化。後半の全注文はS04と575/575条件夜で同値、前半損益を消していない。この境界条件は各案共通で、今回その優位性を独立に再証明した結果ではない。{source}
''',},
        {"file": "売買の工夫.md", "marker": 'id="00150_参加頻度と負けの深さ"', "body": f'''
<a id="00150_参加頻度と負けの深さ"></a>

## 米国前の積極化では、赤字場数が減っても負けた場が深くなる

現在Go版D07のC00は前半16新規・6/25夜参加、全夜+1,153,000円・赤字9/25夜・平均赤字28,000円・最大53,000円。主担当効率と浅い押戻り・小さい再反発を組み合わせるB04は前半38新規・16夜参加、全夜+1,030,000円・赤字8夜・平均43,000円・最大93,000円。前半の実保有率は6.5%→17.3%。前半への参加を増やした効果は実在するが、損失の深さまで改善したとはいえない。

より広く入口・追撃・再参加・追尾を変えたA16は前半59新規、全夜赤字8夜、最大104,000円。主担当の最低経過60→20秒だけのA02はA00と全25夜の注文同値。主担当では価格の段階条件が強い制約だった。一方追加担当の連続確認30→10秒は同担当3→14新規、前半収支−1,000→−94,000円。待機時間という呼び名だけで同一の律速条件と扱わない。

B04の上昇12夜は+335,000円、下落13夜は+695,000円。双方黒字だが上昇夜の利益上位3場を除くと−96,000円で、方向による安定性の差は残る。新23条件と保存3対照を全て公開。既知期間で選んだ候補であり、実アプリの標準へ採用していない。{source}
''',},
    ]


def main():
    """確定済み26条件の資料と案内を公開する。

    引数: なし。返り値: None。金融再生は行わない。
    """
    report = json.loads((HERE / "report150.json").read_text(encoding="utf-8"))
    methods = {m["id"]: m for m in report["methods"]}
    assert len(methods) == 26
    assert report["validation"]["post_exact_to_S04_method_nights"] == 575
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    publish_evidence()
    # ----------------------------------------
    conclusion = (HERE / "公開本文150.md").read_text(encoding="utf-8")
    (PUBLIC / "README.md").write_text(conclusion, encoding="utf-8")
    for finding in findings():
        append_once(KNOWLEDGE / finding["file"], finding["marker"], finding["body"])
    # ----------------------------------------
    description = "D07の米国前だけを23条件で変更。発注前の再確認と、参加増・損失拡大を具体売買で比較。"
    latest = f"最新：[{NAME}](アルゴリズム調査/{NAME}/README.md)。{description}\n\n"
    for target, body in [(ROOT / "README.md", latest), (KNOWLEDGE / "README.md", latest.replace("アルゴリズム調査/", "../../"))]:
        old = target.read_text(encoding="utf-8")
        if NAME not in old:
            target.write_text(body + old, encoding="utf-8")
    page = ROOT / "アルゴリズム調査/index.html"
    old = page.read_text(encoding="utf-8")
    if "<!--00150開始-->" not in old:
        card = f'''\n<!--00150開始-->
<!--
00150の作業入口です。手法別の全夜間損益はExcel、結論と根拠はMarkdownへ移動します。
-->
<article class="task latest"><div class="number">作業00150・米国前23条件と保存3対照</div><h2>D07の米国前しきい値緩和と開始前リセット</h2><p>{description}</p><a class="button" href="{NAME}/D07の積極性と全夜間損益.xlsx">手法別の全25夜損益</a> <a href="{NAME}/README.md">結論と具体的な損失</a></article>
<!--00150終了-->\n'''
        assert '<main id="work-list">' in old
        page.write_text(old.replace('<main id="work-list">', '<main id="work-list">' + card, 1), encoding="utf-8")
    print("00150の資料・共通知見・案内を公開しました。")


if __name__ == "__main__":
    main()
