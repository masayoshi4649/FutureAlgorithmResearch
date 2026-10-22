"""昼夜の保存会計比較を短い暗色レポートと共通知見へ記録する。"""

import hashlib
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = "00127_昼夜別損益と夜間不調の検証"
PUBLIC = ROOT / "アルゴリズム調査" / NAME
TITLE = "昼夜別の損益と検証方針"


def money(value: float) -> str:
    """
    機能: 円額を符号と桁区切り付きで表示する。
    引数: value(float)は損益の円額。
    返り値: strは表示文字列。
    """
    return f"{value:+,.0f}"


def main() -> None:
    """
    機能: 独立再集計と一致した昼夜差を公開し、未検証の夜用手法を分けて記録する。
    引数: なし。
    返り値: None。原売買・価格模型・既存レポートの会計を変更しない。
    """
    result_path = HERE / "昼夜と方向及び前後半の保存会計再集計_最終.json"
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["passed"] and data["financial_replays"] == 0
    assert not PUBLIC.exists()
    PUBLIC.mkdir()
    index = {(r["method"], r["symbol"], r["kind"]): r for r in data["summary"]}
    rows, direction_rows = [], []
    for symbol, label in (("TOPIX", "TOPIXミニ5枚"), ("NK225", "日経マイクロ10枚")):
        for kind, kind_label in (("Day", "日中"), ("Night", "夜間")):
            row = index["GU_Q", symbol, kind]
            style = "positive" if row["net"] > 0 else "negative"
            rows.append(f'<tr><td>{label}</td><td>{kind_label} {row["sessions"]}場</td><td class="{style}">{money(row["net"])}</td>'
                f'<td>{money(row["average"])}</td><td>{row["black"]}／{row["red"]}</td>'
                f'<td>{money(row["median"])}</td><td>{row["win_loss_ratio"]:.2f}倍</td></tr>')
        regimes = {r["regime"]: r for r in index["GU_Q", symbol, "Day"]["regimes"]}
        direction_rows.append(f'<tr><td>{label}</td><td>{money(regimes["上昇"]["net"])}（{regimes["上昇"]["sessions"]}場）</td>'
                              f'<td>{money(regimes["下落"]["net"])}（{regimes["下落"]["sessions"]}場）</td></tr>')
    report = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>昼夜別の損益と検証方針</title><style>
:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#10151e;color:#e5eaf2}*{box-sizing:border-box}body{max-width:1150px;margin:auto;padding:30px 22px 50px}h1{font-size:24px}h2{font-size:18px;margin-top:28px}p{line-height:1.8;font-size:14px;color:#c3cede}strong{color:#eef4ff}.scroll{overflow:auto;border:1px solid #38485d;border-radius:7px;margin:16px 0}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap;font-variant-numeric:tabular-nums}th,td{padding:13px 12px;border-bottom:1px solid #2c394d;text-align:right}th{background:#1d2b40}td:first-child,th:first-child{text-align:left}tbody tr:nth-child(even){background:#172133}.positive{color:#6ee0b2}.negative{color:#ff9eaa}a{color:#9ac7ff}.note{font-size:12px;color:#a9b8cc}
</style>
<!--
[コンポーネント概要]
#summary は同じ保存売買を昼夜に分けた手数料後会計です。
#direction は日中の上昇・下落別成績です。分類は採点専用で入口には使いません。
表示時に売買判断や条件選択はせず、確定した再集計だけを表示します。
-->
<h1>日中は黒字、夜間は赤字</h1>
<p>GU_Q・全43場。提示された立会手数料を新規・返済の双方から差し引いた収支です。実保有はTOPIXミニ5枚・日経マイクロ10枚。条件変更・売買再生なし。</p>
<div class="scroll"><table id="summary"><thead><tr><th>商品・数量</th><th>区分</th><th>累計収支</th><th>1場平均</th><th>黒字／赤字場</th><th>中央値</th><th>平均黒字÷平均赤字</th></tr></thead><tbody>__SUMMARY__</tbody></table></div>
<p class="note">金額は円。「平均黒字÷平均赤字」は、黒字セッションの平均収支を赤字セッションの平均損失額で割った値です。</p>
<p><strong>昼夜を分けて研究する判断は妥当です。</strong> 夜間は手数料前でもTOPIX −231,000円・日経 −107,200円。米国寄付き前後の静観を外したG_Qでは、夜間の手数料後損失が −394,960円・−148,060円へ増えます。日中のGU_QとG_Qは同じ売買・同じ成績です。</p>
<h2>日中にも残る弱点</h2>
<div class="scroll"><table id="direction"><thead><tr><th>商品・数量</th><th>上昇した日中</th><th>下落した日中</th></tr></thead><tbody>__DIRECTION__</tbody></table></div>
<p>日中の黒字上位3場を除いても、TOPIX ＋138,125円・日経 ＋5,800円。ただし利益は下落日に偏ります。TOPIXの日中後半11場は5勝6敗・中央値 −2,334円でした。</p>
<p><strong>次の検証は「日中の既存型」と「夜間の別設定・別手法」を分離します。</strong> 夜間用の有効な別手法は今回まだ検証していません。昼夜の区分は既知データを見て選んだため、今後はこの区分を固定して追加場で確認します。</p>
<p class="note">上昇・下落は旧観測窓の最初と最後のLastによる事後分類。取引の方向選択に将来情報を使用しません。ラージBBO代理の成績です。</p>
<p><a href="README.md">出典と読む順序</a> ／ <a href="../00126_E01の損失抑制と方向偏りの再検証/E01改修のセッション損益.html">元の全43セッション損益（手数料なし）</a></p></html>'''
    target = PUBLIC / (TITLE + ".html")
    target.write_text(report.replace("__SUMMARY__", "".join(rows)).replace("__DIRECTION__", "".join(direction_rows)), encoding="utf-8")
    (PUBLIC / "README.md").write_text("# 昼夜別損益と夜間不調の検証\n\n"
        f"最初に見るファイルは [{TITLE}]({TITLE}.html) です。読む順序はHTML、[保存会計の再集計](../../work/daynight127_20261020/昼夜と方向及び前後半の保存会計再集計_最終.json)、[元調査](../00126_E01の損失抑制と方向偏りの再検証/README.md)です。\n\n"
        "レビュアーの昼夜差の指摘を、既存43場のGU_Q・G_Qの注文別手数料差引会計で検証しました。新しい金融再生・原本読取・API接続は0です。"
        "二担当の独立集計で昼夜収支、黒赤場数、中央値、上位3黒字除外、前後半、週別を確認しました。日中の両候補44商品場は手法名以外の保存会計が完全一致します。\n\n"
        "結論は、E01改修を日中候補として扱い、夜間の別設定・別手法を分離して検証すること。日中にも下落方向への収益偏りがあり、毎場安定の確立とは呼びません。夜間で成功する別手法は今回未検証です。\n\n"
        "初回再集計では、黒字がない小区分でも最高収支の場を除外していました。最終版は黒字がなければ除外しない定義に統一。主要な全昼夜の比較値は変わらず、修正前資料も保存しています。\n", encoding="utf-8")
    synopsis = "GU_Q手数料後：日中22場はTOPIX+445,287円・日経+162,180円、夜間21場は−290,701円・−138,000円。日中にも下落日への利益偏りが残る。"
    modifications = []
    for name, link in (("README.md", f"アルゴリズム調査/{NAME}/{TITLE}.html"),
                       ("アルゴリズム調査/README.md", f"{NAME}/{TITLE}.html"),
                       ("アルゴリズム調査/共通/知見台帳/README.md", f"../../{NAME}/{TITLE}.html")):
        path = ROOT / name
        old = path.read_bytes()
        backup = HERE / "更新前" / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(old)
        text = old.decode("utf-8")
        head, rest = text.split("\n", 1)
        text = head + f"\n\n<!--00127案内-->\n最新：[00127：昼夜別損益]({link})。{synopsis}\n<!--00127案内終了-->\n" + rest
        path.write_text(text, encoding="utf-8")
        modifications.append(name)
    index_path = ROOT / "アルゴリズム調査/index.html"
    original = index_path.read_bytes()
    (HERE / "更新前/アルゴリズム調査/index.html").write_bytes(original)
    text = original.decode("utf-8")
    marker = '<main id="work-list">'
    assert text.count(marker) == 1
    card = f'\n<!--00127開始--><article class="task latest"><div class="number">作業00127・昼夜を分けた確認</div><h2>日中は黒字、夜間は赤字</h2><p>{html.escape(synopsis)}</p><a class="button" href="{NAME}/{TITLE}.html">昼夜別の損益</a> <a href="{NAME}/README.md">出典</a></article><!--00127終了-->'
    index_path.write_text(text.replace(marker, marker + card), encoding="utf-8")
    ledger = ROOT / "アルゴリズム調査/共通/知見台帳/売買の工夫.md"
    original = ledger.read_bytes()
    (HERE / "更新前/売買の工夫.md").write_bytes(original)
    text = original.decode("utf-8")
    anchor = '<a id="00127_昼夜の独立評価"></a>'
    assert anchor not in text
    text += (f"\n\n{anchor}\n\n## E01改修の収益は昼夜で逆になり、日中にも方向差が残る\n\n"
        f"**出典：** [{NAME}](../../{NAME}/README.md)、元会計は [00126_E01の損失抑制と方向偏りの再検証](../../00126_E01の損失抑制と方向偏りの再検証/README.md)。\n\n"
        "**当時判定できる条件：** session末尾のDay／Nightで分離する。場内全返済の同じ保存売買を再集計し、場末の値動きを事前選択には使わない。TOPIXミニ5枚・日経マイクロ10枚、提示立会手数料を新規返済双方へ課金。\n\n"
        "**分母・実測：** GU_Qの日中は両商品各22場、黒字13/22・14/22、費用後収支+445,287円・+162,180円。夜間は各21場、黒字10/21・10/21、−290,701円・−138,000円。夜間は費用前でも−231,000円・−107,200円。平均黒字場÷平均赤字場は日中1.63倍・1.13倍、夜間0.55倍・0.58倍。日中のGU_QとG_Qの44商品場会計は同一。\n\n"
        "**依存と限界：** 日中上位3黒字場除外で+138,125円・+5,800円。上昇日中の収支はTOPIX12場+25,720円・日経11場−1,300円、下落は10場+419,567円・11場+163,480円。TOPIX後半11場は5黒6赤・中央値−2,334円。全43場を見た後の区分であり、日中の将来安定や夜用別手法の成功を証明しない。方向は旧観測窓の先頭末尾Lastによる事後採点。\n\n"
        "**使い方：** 次の研究を日中型と夜間型に分ける。米国開始回避だけで夜間が黒字化したとは扱わず、夜用の別設定と別機構は未検証として切り分ける。今回の再集計を新市場の独立試行や新しい金融再生へ数えない。\n\n"
        "**根拠：** [昼夜・方向・前後半・週別の保存会計](../../../work/daynight127_20261020/昼夜と方向及び前後半の保存会計再集計_最終.json)。\n")
    ledger.write_text(text, encoding="utf-8")
    policy = ROOT / "アルゴリズム調査/調査方針.md"
    old = policy.read_bytes()
    (HERE / "更新前/調査方針.md").write_bytes(old)
    policy.write_text(old.decode("utf-8") + "\n\n<!--00127昼夜比較-->\n2026年10月20日、レビュアー指摘を受け既存43場を昼夜別・提示手数料後で再集計。日中のE01改修と夜間を別枠として検証する。日中の下落日への利益偏りも残し、夜用の別設定・別機構は未検証として扱う。現在アプリの自動運用や既存会計は変更しない。\n<!--00127昼夜比較終了-->\n", encoding="utf-8")
    (HERE / "公開記録.json").write_text(json.dumps(dict(passed=True, public=target.relative_to(ROOT).as_posix(),
        report_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(), financial_replays=0,
        public_readme=PUBLIC.joinpath("README.md").relative_to(ROOT).as_posix(), navigation=modifications),
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("昼夜別の短いレポート、案内、共通知見を保存", flush=True)


if __name__ == "__main__":
    main()
