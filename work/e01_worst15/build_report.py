"""E01の判断後15秒最悪約定を、短い比較表と暗色の単独HTMLにまとめる。"""

from collections import defaultdict
from datetime import date
from html import escape
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
OUT = ROOT / "アルゴリズム調査" / "00046_E01の15秒最悪約定比較"
TITLE = "E01の15秒最悪約定比較.html"
SYMBOLS = ("TOPIX", "NK225")
LABELS = {"TOPIX": "TOPIXミニ", "NK225": "NK225マイクロ"}


def number(value, signed=False, decimals=0):
    """機能: 表の数値を桁区切りし、必要に応じて符号を付ける。

    引数: value(float|int)は数値、signed(bool)は符号表示、decimals(int)は小数桁。
    返り値: 整形した文字列(str)。
    """
    return f"{value:+,.{decimals}f}" if signed else f"{value:,.{decimals}f}"


def cell(value, signed=False, decimals=0, tag="td", classes=""):
    """機能: 検証可能な数値属性を付けたHTML要素を作る。

    引数: value(float|int)、signed(bool)、decimals(int)、tag(str)、classes(str)。
    返り値: 数値を表示するHTML文字列(str)。
    """
    value = round(value, decimals)
    tone = " positive" if signed and value > 0 else " negative" if signed and value < 0 else ""
    return f'<{tag} class="num {classes}{tone}" data-value="{value}">{number(value, signed, decimals)}</{tag}>'


def session_label(session):
    """機能: 保存用セッション識別子を短い日本語の日付・区分にする。

    引数: session(str)は日付とDayまたはNightを含む識別子。
    返り値: 日本語の表示名(str)。
    """
    day, kind = session.split("_")
    return f'{day[5:].replace("-", "/")} {"デイ" if kind == "Day" else "ナイト"}'


def aggregate(rows):
    """機能: セッションの金額・決済枚数を銘柄ごとに合計する。

    引数: rows(list[dict])は集計対象のセッション・銘柄行。
    返り値: 銘柄別の合計辞書(dict[str, dict])。
    """
    result = {}
    for symbol in SYMBOLS:
        selected = [row for row in rows if row["symbol"] == symbol]
        item = {mode: {key: sum(row[mode][key] for row in selected)
                      for key in ("profit", "loss", "net", "win_units", "loss_units", "flat_units")}
                for mode in ("ideal", "worst")}
        for key in ("adverse_yen", "entry_adverse_yen", "exit_adverse_yen"):
            item[key] = sum(row[key] for row in selected)
        result[symbol] = item
    return result


def period_rows(data):
    """機能: 19セッション、週小計、全期間合計を時系列に並べる。

    引数: data(dict)は計算結果全体。
    返り値: 表示名・種別・銘柄別数値を持つ行一覧(list[tuple])。
    """
    grouped = defaultdict(list)
    for row in data["sessions"]:
        grouped[row["session"]].append(row)
    weeks = defaultdict(list)
    for session in sorted(grouped):
        day = date.fromisoformat(session.split("_")[0])
        weeks[day.isocalendar()[:2]].append(session)
    result = []
    for sessions in weeks.values():
        for session in sessions:
            result.append((session_label(session), "session", aggregate(grouped[session])))
        week_rows = [row for session in sessions for row in grouped[session]]
        label = f'{sessions[0][5:10].replace("-", "/")}〜{sessions[-1][5:10].replace("-", "/")} 計'
        result.append((label, "subtotal", aggregate(week_rows)))
    result.append(("全19セッション 計", "grand-total", aggregate(data["sessions"])))
    return result


def summary_card(symbol, total):
    """機能: 銘柄別の理想収支・最悪収支・悪化額を最上部にまとめる。

    引数: symbol(str)は銘柄、total(dict)は当該銘柄の全期間合計。
    返り値: 要約カードのHTML文字列(str)。
    """
    sizing = "初回5枚・片方向上限10枚" if symbol == "TOPIX" else "初回10枚・片方向上限20枚"
    keep = total["net_retained_percent"]
    return f'''<article class="summary-card">
      <h2>{LABELS[symbol]}<span>{sizing}</span></h2>
      <div class="net-comparison"><div><small>理想約定の収支</small>{cell(total['ideal']['net'], True, tag='strong')}<small>円</small></div>
      <span class="arrow" aria-hidden="true">→</span>
      <div><small>15秒内の最悪約定の収支</small>{cell(total['worst']['net'], True, tag='strong')}<small>円</small></div></div>
      <div class="adverse"><span>悪化額</span><span>{cell(total['adverse_yen'], tag='b')} 円</span></div>
      <p class="card-foot">理想収支の {keep:.1f}% が残る · 黒字セッション {total['ideal']['win_sessions']}/19 → {total['worst']['win_sessions']}/19</p>
    </article>'''


def comparison_table(periods):
    """機能: 両銘柄のセッション別・週別・全期間の収支差を横並びにする。

    引数: periods(list[tuple])は集計済み表示行。
    返り値: 比較表のHTML文字列(str)。
    """
    rows = []
    for label, kind, totals in periods:
        cells = f'<th scope="row">{escape(label)}</th>'
        for symbol in SYMBOLS:
            item = totals[symbol]
            cells += cell(item["ideal"]["net"], True)
            cells += cell(item["worst"]["net"], True)
            cells += cell(-item["adverse_yen"], True, classes="difference")
        rows.append(f'<tr class="{kind}">{cells}</tr>')
    return '''<div class="table-scroll" tabindex="0" aria-label="横スクロールできるセッション収支比較表"><table id="session-comparison">
    <thead><tr><th rowspan="2" scope="col">セッション</th><th colspan="3" scope="colgroup">TOPIXミニ</th><th colspan="3" scope="colgroup">NK225マイクロ</th></tr>
    <tr><th scope="col">理想</th><th scope="col">15秒最悪</th><th scope="col">差</th><th scope="col">理想</th><th scope="col">15秒最悪</th><th scope="col">差</th></tr></thead>
    <tbody>''' + "".join(rows) + "</tbody></table></div>"


def symbol_details(symbol, data, periods):
    """機能: 銘柄別の総利益・総損失・枚数・入口と返済の悪化額を表示する。

    引数: symbol(str)は銘柄、data(dict)は計算結果、periods(list[tuple])は期間行。
    返り値: 折りたたみ内訳のHTML文字列(str)。
    """
    total = data["totals"][symbol]
    metric_rows = []
    for label, key, decimals in (("利益の合計（円）", "profit", 0), ("損失の合計（円・絶対額）", "loss", 0),
                                ("勝ち決済枚数", "win_units", 0), ("負け決済枚数", "loss_units", 0),
                                ("同値決済枚数", "flat_units", 0), ("利益合計 ÷ 損失合計", "profit_factor", 2),
                                ("勝ち1枚の平均利益 ÷ 負け1枚の平均損失", "unit_payoff", 2)):
        metric_rows.append(f'<tr><th scope="row">{label}</th>' + cell(total["ideal"][key], decimals=decimals) + cell(total["worst"][key], decimals=decimals) + "</tr>")
    detail_rows = []
    for label, kind, totals in periods:
        cells = f'<th scope="row">{escape(label)}</th>'
        for mode in ("ideal", "worst"):
            for key in ("profit", "loss", "win_units", "loss_units", "flat_units"):
                cells += cell(totals[symbol][mode][key])
        detail_rows.append(f'<tr class="{kind}">{cells}</tr>')
    header = '<th scope="col">利益（円）</th><th scope="col">損失（円）</th><th scope="col">勝ち枚数</th><th scope="col">負け枚数</th><th scope="col">同値枚数</th>'
    return f'''<details class="symbol-detail" id="detail-{symbol}"><summary>{LABELS[symbol]}：利益・損失・枚数の内訳</summary>
      <div class="detail-body"><p>悪化額の内訳：<b>入口 {number(total['entry_adverse_yen'])} 円</b> ／ <b>返済 {number(total['exit_adverse_yen'])} 円</b>（全 {total['order_count']} 注文）。</p>
      <div class="table-scroll" tabindex="0"><table class="metrics"><thead><tr><th scope="col">全期間</th><th scope="col">理想</th><th scope="col">15秒最悪</th></tr></thead><tbody>{''.join(metric_rows)}</tbody></table></div>
      <p class="muted">枚数は決済分の累計です。同じ保有枠での再エントリーを含みます。損失は絶対額で表示しています。</p>
      <div class="table-scroll" tabindex="0"><table class="detail-table"><thead><tr><th rowspan="2" scope="col">セッション</th><th colspan="5" scope="colgroup">理想</th><th colspan="5" scope="colgroup">15秒最悪</th></tr><tr>{header}{header}</tr></thead><tbody>{''.join(detail_rows)}</tbody></table></div>
      </div></details>'''


def method_notes(data):
    """機能: 比較条件と例外を短い折りたたみ説明にまとめる。

    引数: data(dict)は計算条件と注文別結果。
    返り値: 条件説明のHTML文字列(str)。
    """
    improved = [(row, order) for row in data["sessions"] for order in row["orders"] if order["adverse_yen"] < 0]
    notes = []
    for row, order in improved:
        action = "買い" if order["side"] > 0 else "売り"
        notes.append(f'{session_label(row["session"])}の{LABELS[row["symbol"]]}、{order["decision_jst"][11:19]}の{action}{order["quantity"]}枚は、理想価格{order["ideal_price"]:g}に対し窓内最悪価格が{order["worst_price"]:g}となり、{number(-order["adverse_yen"])}円改善しました。')
    return f'''<details class="method-notes"><summary>比較条件・解釈</summary><div class="detail-body">
      <ul><li>基準は00044のE01・全19セッションです。実運転ログとの比較ではありません。</li>
      <li>新規・返済とも、条件成立・発注判断から15秒後までの保存板 <code>CurrentPrice</code> を対象に、買いは最高値、売りは最安値を採用します。待機注文を置いた時刻は起点にしません。</li>
      <li>判断の時刻・方向・枚数は固定しています。悪化した建値に合わせて出口条件や後続の売買を計算し直す、運用全体の再試験ではありません。</li>
      <li>起点と15秒の長さは保存データの市場時刻によります。実際の通信・受信遅延は測定していません。15秒後までの価格は約定評価だけに使い、売買判断には使いません。</li>
      <li>手数料は含めず、板の数量による未約定や部分約定もモデル化していません。すべて場内で返済する元の売買列を使っています。</li></ul>
      <p>{' '.join(notes)} これは元の条件価格と観測価格が異なるためです。指定の「窓内最悪値」をそのまま使い、改善をゼロに切り上げていません。</p>
      <p class="muted">保存済みデータのみで計算。現在セッションAPI取得：{data['live_api_calls']}回。全{data['audit']['order_count']}注文で15秒窓の終端までデータ期間があり、最悪約定時刻の前後逆転はありません。</p>
      </div></details>'''


STYLE = '''
:root{color-scheme:dark;font-family:"Yu Gothic UI","Meiryo",system-ui,sans-serif;background:#0a111c;color:#e9eef6;font-size:15px;line-height:1.65}
*{box-sizing:border-box}body{margin:0}main{max-width:1220px;margin:0 auto;padding:40px 28px 60px}a{color:#83bcff;text-underline-offset:3px}p{margin:10px 0}h1{font-size:clamp(23px,3.1vw,34px);line-height:1.3;margin:12px 0}h2{font-size:21px;margin:0}.eyebrow{color:#9cadc4;font-size:13px;letter-spacing:.04em}.subtitle,.muted,.card-foot{color:#a6b6cc}.lead{font-size:18px;margin:20px 0 6px}.scope{color:#c1ccdb;font-size:14px;margin:0 0 24px}.summary-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.summary-card{border:1px solid #2c405c;border-top:3px solid #77aefa;border-radius:10px;padding:22px;background:#121e30}.summary-card h2 span{display:block;font-size:12px;font-weight:400;color:#a6b6cc;margin-top:2px}.net-comparison{display:grid;grid-template-columns:1fr 25px 1fr;gap:8px;align-items:center;margin:22px 0 16px}.net-comparison small{display:block;color:#acbdd4;font-size:12px}.net-comparison strong{display:inline;font-size:clamp(24px,2.6vw,34px);letter-spacing:-.03em}.net-comparison strong+small{display:inline;margin-left:5px}.arrow{color:#7792b5;font-size:24px}.num{font-variant-numeric:tabular-nums;white-space:nowrap}.positive{color:#70e0b8}.negative{color:#ff9aab}.adverse{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #304159;padding-top:12px;color:#ffd39c}.adverse b{font-size:22px}.card-foot{font-size:12px;margin:8px 0 0}.section-title{margin-top:32px;display:flex;align-items:baseline;justify-content:space-between;gap:12px}.section-title p{color:#a6b6cc;font-size:12px;margin:8px 0}.table-scroll{max-width:100%;overflow-x:auto;border:1px solid #293b53;border-radius:7px;margin:10px 0 18px;outline-offset:4px}table{width:100%;border-collapse:separate;border-spacing:0;font-size:13px;background:#101a2a}th,td{padding:9px 14px;border-bottom:1px solid #26354a;text-align:right;white-space:nowrap}th:first-child{text-align:left}thead th{background:#19283d;color:#cdd8e8;font-weight:600}thead tr:first-child th:not(:first-child){text-align:center}thead tr:first-child th:nth-child(2){border-right:1px solid #42546e}tbody th{font-weight:400;color:#cad5e5;background:#101a2a}tbody tr:nth-child(even) td,tbody tr:nth-child(even) th{background:#121f31}#session-comparison th:first-child{position:sticky;left:0;z-index:1}#session-comparison td:nth-child(4){border-right:1px solid #42546e}#session-comparison td.difference{background:#251d2a}.subtotal td,.subtotal th{background:#202c40!important;border-top:1px solid #46546b;font-weight:600}.grand-total td,.grand-total th{background:#203d47!important;border-top:2px solid #689bab;font-weight:700}.grand-total td{font-size:14px}tbody tr:last-child>*{border-bottom:0}details{border:1px solid #293b53;border-radius:8px;background:#101a2a;margin:12px 0}summary{cursor:pointer;padding:15px 18px;color:#dce7f5;font-weight:600}summary:hover{background:#1a2b40}details[open] summary{border-bottom:1px solid #293b53}.detail-body{padding:8px 18px 16px;font-size:14px}.metrics{max-width:760px}.detail-table{font-size:12px}.detail-table th,.detail-table td{padding:8px 11px}.detail-body ul{padding-left:21px}.detail-body li{margin:9px 0}.method-notes p{font-size:13px;color:#b3c2d7}code{font-family:ui-monospace,monospace;background:#223146;border-radius:3px;padding:1px 4px}footer{border-top:1px solid #293b53;padding-top:18px;margin-top:26px;color:#91a4bd;font-size:12px}.footer-links{display:flex;flex-wrap:wrap;gap:18px}
@media(max-width:760px){main{padding:24px 14px 42px}.summary-grid{grid-template-columns:1fr}.summary-card{padding:18px}.net-comparison strong{font-size:29px}.lead{font-size:16px}.section-title{display:block}.section-title h2{font-size:19px}th,td{padding:9px 11px}#session-comparison{min-width:775px}.detail-body{padding:6px 12px 12px}.metrics{min-width:520px}.scope{font-size:13px}.card-foot{font-size:12px}}
'''


def build():
    """機能: 計算結果JSONから単独HTMLと読む順序付きREADMEを生成する。

    引数: なし。
    返り値: 生成HTMLのファイルパス(Path)。
    """
    data = json.loads((OUT / "計算結果.json").read_text(encoding="utf-8"))
    periods = period_rows(data)
    topix_drop = 100 - data["totals"]["TOPIX"]["net_retained_percent"]
    nk_drop = 100 - data["totals"]["NK225"]["net_retained_percent"]
    document = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>E01｜15秒最悪約定と理想約定の比較</title><style>{STYLE}</style></head><body>
    <!--
    [コンポーネント概要]
    .summary-grid は両銘柄の全期間収支と悪化額を表示する要約領域です。
    #session-comparison はセッション・週・全期間の収支比較表です。
    .table-scroll は狭い画面で表だけを横スクロールさせ、本文の幅を保持します。
    .symbol-detail は利益・損失・決済枚数を銘柄別に開閉する詳細領域です。
    .method-notes は計算条件と例外を開閉する説明領域です。
    [data-value] は表示値の照合に使う丸め後の数値で、表示単位は表見出しに示します。
    .positive と .negative は暗色背景でも読める損益の正負の文字色です。
    -->
    <main><header><div class="eyebrow">00046 · E01 約定条件の検証</div><h1>発注判断後15秒、最悪の価格で約定したら</h1>
      <p class="subtitle">2026/09/21 デイ〜10/02 デイ · 全19セッション · 00044のE01と比較</p>
      <p class="lead">両銘柄とも黒字は残りますが、収支はTOPIXで <b>{topix_drop:.1f}%</b>、NKで <b>{nk_drop:.1f}%</b> 減少します。</p>
      <p class="scope">条件成立・発注判断から15秒以内の「買い＝最高値、売り＝最安値」。<br>売買判断と枚数を固定した比較です。悪化した建値から出口条件を計算し直す再運転ではありません。</p></header>
    <section class="summary-grid" aria-label="銘柄別の全期間収支">{''.join(summary_card(symbol, data['totals'][symbol]) for symbol in SYMBOLS)}</section>
    <section aria-labelledby="session-title"><div class="section-title"><h2 id="session-title">セッションごとの収支</h2><p>単位：円 ／ 差＝15秒最悪 − 理想</p></div>{comparison_table(periods)}</section>
    {''.join(symbol_details(symbol, data, periods) for symbol in SYMBOLS)}
    {method_notes(data)}
    <footer><div class="footer-links"><a href="計算結果.json">注文ごとの計算結果（JSON）</a><a href="検証記録.json">独立検算の記録</a><a href="発注判断時刻の監査.json">発注判断時刻の監査</a><a href="README.md">資料の読む順序・再計算</a><a href="../00044_新候補2手法と基準の説明と損益/新候補2手法の説明と損益.html">比較元の00044</a><a href="../index.html">調査一覧</a></div><p>手数料なし。損益はTOPIXミニ1pt＝1,000円、NK225マイクロ1円＝10円で換算。銘柄間の利益額の大きさだけで優劣を比較していません。</p></footer>
    </main></body></html>'''
    target = OUT / TITLE
    target.write_text(document, encoding="utf-8")

    # ----------------------------------------
    # 読む順序と再生成手順を同じ作業フォルダへ保存する。
    readme = f'''# E01の15秒最悪約定比較

最初に [{TITLE}]({TITLE}) を開いてください。

## 読む順序

1. HTML上部：銘柄別の全期間収支と悪化額。
2. セッション表：19セッション・週小計・全期間合計。
3. 銘柄別の折りたたみ：利益・損失・決済枚数と入口／返済の悪化額。
4. [計算結果.json](計算結果.json)：判断時刻、15秒窓、注文別の理想価格・最悪価格と集計。
5. [検証記録.json](検証記録.json)・[発注判断時刻の監査.json](発注判断時刻の監査.json)：独立検算と15秒の起点の検証。

## 比較の意味

00044のE01の全19セッションを対象に、条件成立・発注判断から15秒以内の保存板CurrentPriceで、買いは最高値、売りは最安値を使います。TOPIXミニは初回5枚・片方向上限10枚、NK225マイクロは初回10枚・片方向上限20枚です。

売買判断の時刻・方向・枚数を固定した価格の感度検証です。悪化した建値から出口条件を再計算する再運転ではありません。実運転ログとの比較でもありません。未来の価格は約定評価だけに使用し、判断には使いません。市場時刻を用い、実際の受信遅延は測定していません。手数料は含みません。

## 全期間の結果

| 銘柄 | 理想の収支 | 15秒最悪の収支 | 悪化額 |
|---|---:|---:|---:|
| TOPIXミニ | {number(data['totals']['TOPIX']['ideal']['net'], True)}円 | {number(data['totals']['TOPIX']['worst']['net'], True)}円 | {number(data['totals']['TOPIX']['adverse_yen'])}円 |
| NK225マイクロ | {number(data['totals']['NK225']['ideal']['net'], True)}円 | {number(data['totals']['NK225']['worst']['net'], True)}円 | {number(data['totals']['NK225']['adverse_yen'])}円 |

## 再生成

プロジェクトルートで `python -X utf8 work/e01_worst15/build_report.py` を実行すると、計算済みJSONからHTMLとこのREADMEを再生成します。計算コードは `work/e01_worst15/analyze.py` です。元の00044や売買規則は変更していません。

表示検証は `python -X utf8 work/e01_worst15/build_report.py --verify`。検証用複製、数値・横幅の検査結果、広い画面／狭い画面の画像を `work/e01_worst15` に保存します。
'''
    if (OUT / '悪化した約定の特徴.html').exists():
        readme = readme.replace('## 比較の意味', '## 悪化部分の補足\n\n[悪化した約定の特徴](悪化した約定の特徴.html)：直前30秒の値動き・出口・昼夜・板の関係を比較しています。\n\n## 比較の意味')
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    return target


PROBE = '''<script>
/**
 * 機能: 表示数値、セッション行、横幅、未定義値を検査する。
 * @param {boolean} openDetails - 銘柄別の詳細を開くか。
 * @returns {object} 返り値は検査結果。
 */
function verifyDisplay(openDetails) {
  if (openDetails) document.querySelectorAll('details').forEach(item => item.open = true);
  let count = 0;
  for (const item of document.querySelectorAll('[data-value]')) {
    const displayed = Number(item.textContent.replaceAll(',', ''));
    const expected = Number(item.dataset.value);
    if (!Number.isFinite(expected) || displayed !== expected) throw Error('数値表示の不一致');
    count += 1;
  }
  const rows = document.querySelectorAll('#session-comparison tbody tr.session').length;
  if (rows !== 19) throw Error('セッション数の不一致');
  if (document.documentElement.scrollWidth > innerWidth + 2) throw Error('本文の横はみ出し');
  if (/undefined|NaN/.test(document.body.innerText)) throw Error('未定義値');
  return {全合格:true,表示数値:count,セッション数:rows,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.documentElement).backgroundColor};
}
try { document.body.dataset.check = JSON.stringify(verifyDisplay(@@OPEN@@)); }
catch (error) { document.body.dataset.check = JSON.stringify({全合格:false,理由:String(error)}); }
</script>'''


def verify(target):
    """機能: 広い画面と狭い画面でHTMLを描画し、数値と横幅を検査する。

    引数: target(Path)は公開用HTMLのファイルパス。
    返り値: 検査結果の辞書(dict)。
    """
    from bs4 import BeautifulSoup

    source = target.read_text(encoding="utf-8")
    results = []
    browser = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    for name, width, height, opened in (("比較全体", 1420, 1850, False), ("比較狭い画面", 520, 2050, False), ("比較詳細", 1420, 2600, True)):
        sample = WORK / f"{name}.html"
        picture = WORK / f"{name}.png"
        probe = PROBE.replace("@@OPEN@@", str(opened).lower())
        sample.write_text(source.replace("</body>", probe + "</body>"), encoding="utf-8")
        command = [str(browser), "--headless=new", "--disable-gpu", "--no-first-run", "--disable-background-networking",
                   "--disable-component-update", "--disable-sync", "--run-all-compositor-stages-before-draw",
                   "--disable-features=PaintHolding", "--proxy-server=http://127.0.0.1:9",
                   f"--window-size={width},{height}", "--virtual-time-budget=1200",
                   "--user-data-dir=" + str(WORK / ("visual_" + hashlib.sha256(name.encode()).hexdigest()[:8])),
                   "--screenshot=" + str(picture), "--dump-dom", sample.as_uri()]
        result = subprocess.run(command, capture_output=True, timeout=50,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0 and picture.exists() and picture.stat().st_size > 10000
        soup = BeautifulSoup(result.stdout.decode("utf-8", errors="replace"), "html.parser")
        proof = json.loads(soup.body["data-check"])
        assert proof["全合格"], proof
        results.append({"名前": name, "画像": str(picture), **proof})
    evidence = {"全合格": True, "HTML_SHA256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "目視確認済": False, "結果": results}
    (WORK / "表示確認.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence


if __name__ == "__main__":
    import sys

    output = build()
    print(output)
    if "--verify" in sys.argv:
        result = verify(output)
        print(f"全3画面・{result['結果'][0]['表示数値']}数値・19セッションの表示検査合格")
