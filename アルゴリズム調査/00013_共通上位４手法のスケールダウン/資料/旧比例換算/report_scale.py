"""保存済みの整数枚数換算を、４手法別の短いダークHTMLへまとめる。"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
FOLDER = '00013_共通上位４手法のスケールダウン'
OUT = ROOT / 'アルゴリズム調査' / FOLDER
PAGE = '共通上位４手法のスケールダウン.html'
METHODS = ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01']


def esc(value: object) -> str:
    """文字列をHTMLの本文・属性へ安全に差し込める形にする。

    引数: value (object) は表示値。返り値: エスケープ済み文字列 (str)。
    """
    return html.escape(str(value), quote=True)


def yen(value: float, signed: bool = False) -> str:
    """円額を小数がない読みやすい表示にする。

    引数: value (float) は円額、signed (bool) は正数にも符号を付ける指定。
    返り値: 円の表示 (str)。
    """
    assert abs(value - round(value)) < .01, value
    return (f'{round(value):+,}' if signed else f'{round(value):,}') + '円'


def units(value: float, signed: bool = False) -> str:
    """整数枚数を表記する。

    引数: value (float) は枚数、signed (bool) は符号指定。返り値: 枚数の表示 (str)。
    """
    assert abs(value - round(value)) < 1e-6, value
    return (f'{round(value):+,}' if signed else f'{round(value):,}') + '枚'


def ratio(value: float | None) -> str:
    """比率を小数２桁で表示する。

    引数: value (float | None) は比率。返り値: 比率の文字列 (str)。
    """
    return '算定なし' if value is None else f'{value:.2f}'


def session_label(session: str) -> str:
    """開始日基準のセッションを日本語にする。

    引数: session (str) は日付と区分。返り値: 日本語ラベル (str)。
    """
    date, part = session.split('_')
    day = int(date[-2:])
    return f'9/{day} 日中' if part == 'Day' else f'9/{day} 夜間 → 9/{day + 1} 朝'


def text_block(value: str | list[str]) -> str:
    """単一文または複数文の説明をHTMLへ変換する。

    引数: value (str | list[str]) は説明。返り値: 本文HTML (str)。
    """
    return ' '.join(esc(item) for item in value) if isinstance(value, list) else esc(value)


def results_table(rows: list[dict], weekly: bool = False) -> str:
    """利益・損失・収支と累計枚数の表を作る。

    引数: rows (list[dict]) は集計、weekly (bool) は週合計用の指定。
    返り値: 金額と枚数を同じセルに表示する表 (str)。
    """
    parts = ['<div class="table-wrap"><table><thead><tr><th>区間</th><th>利益／利益枚数</th><th>損失／損失枚数</th><th>収支／枚数差</th></tr></thead><tbody>']
    for row in rows:
        label = '１週間合計' if weekly else session_label(row['session'])
        net_class = 'positive' if row['net_yen'] >= 0 else 'negative'
        parts.append(f'<tr><td>{esc(label)}</td><td class="positive">{yen(row["gross_profit_yen"])}<span>{units(row["profit_units"])}</span></td>'
                     f'<td class="negative">{yen(-row["gross_loss_yen"])}<span>{units(row["loss_units"])}</span></td>'
                     f'<td class="{net_class}">{yen(row["net_yen"], True)}<span>{units(row["unit_balance"], True)}</span></td></tr>')
    parts.append('</tbody></table></div>')
    return ''.join(parts)


def overview(data: dict) -> str:
    """４手法の主案による週収支を冒頭に並べる。

    引数: data (dict) は換算データ。返り値: 週一覧のHTML (str)。
    """
    parts = ['<section class="panel" id="weekly-overview"><h2>１週間の収支</h2>',
             '<p>増玉型は小さく入り、順行したときだけ上限まで増やします。固定型は最初から上限枚数で入り、その枚数を維持します。</p>',
             '<div class="table-wrap"><table><thead><tr><th>手法</th><th>TOPIXミニ</th><th>NK225マイクロ</th></tr></thead><tbody>']
    for method in data['methods']:
        parts.append(f'<tr><td><a href="#{esc(method["id"])}">{esc(method["id"])}</a><span>{esc(method["name"])}</span></td>')
        for symbol in ['TOPIX', 'NK225']:
            variant = method['variants'][symbol]
            config = variant['config']
            rule = f'{config["initial_qty"]}枚開始 → 最大{config["position_cap"]}枚' if method['id'].endswith('A03') else f'{config["initial_qty"]}枚固定'
            parts.append(f'<td class="positive summary-net">{yen(variant["week"]["net_yen"], True)}<span>{rule}</span></td>')
        parts.append('</tr>')
    parts.extend(['</tbody></table></div>',
                  '<div class="callout"><p><b>枚数配分に注意：</b>固定型は増玉型の10倍の枚数で開始します。同じATRなら初期損失予算も10倍になるため、収支額だけで優劣は決められません。<a href="#uniform-scale">全手法を同じ割合で縮めた比較</a>も末尾に掲載しています。</p></div>',
                  '<p class="note">各手法を別々に運用した場合です。４つ同時運用の合計上限ではありません。両建て・部分利確・保有中の反転は使わず、各セッション内で全玉を返済します。</p></section>'])
    return ''.join(parts)


def variant_section(method: dict, symbol: str, product: dict) -> str:
    """１手法・１銘柄の枚数規則と週・セッションの結果をまとめる。

    引数: method (dict) は手法、symbol (str) は銘柄、product (dict) は商品仕様。
    返り値: 銘柄版のHTML (str)。
    """
    variant = method['variants'][symbol]
    week, risk = variant['week'], variant['risk']
    label = 'TOPIXミニ版' if symbol == 'TOPIX' else 'NK225マイクロ版'
    style = 'topix' if symbol == 'TOPIX' else 'nk'
    parts = [f'<section class="variant {style}" data-method="{esc(method["id"])}" data-symbol="{symbol}">',
             f'<h3>{label}</h3><p>{esc(variant["quantity_rule"])}</p>',
             f'<div class="result-line"><span>週収支</span><strong class="positive">{yen(week["net_yen"], True)}</strong><span class="muted">黒字 {week["positive_sessions"]} / {week["session_count"]} セッション</span></div>',
             results_table([week], weekly=True),
             f'<div class="stats"><span>総利益／総損失 <b>{ratio(week["money_ratio"])}倍</b></span><span>１枚平均の利益／損失 <b>{ratio(week["unit_payoff"])}倍</b></span><span>最大下落 <b>{yen(week["drawdown_yen"])}</b></span></div>',
             f'<p class="note">１枚平均：利益 約{yen(round(week["avg_profit_per_unit"]))} ／ 損失 約{yen(round(week["avg_loss_per_unit"]))}。返済累計 {units(week["closed_units"])}（うち損益０は{units(week["zero_units"])}）。実績最大保有は買い{units(week["max_long"])}・売り{units(week["max_short"])}。</p>',
             f'<p class="note">開始時の損失予算：中央値 約{yen(round(risk["median_yen"]))}（約{yen(round(risk["min_yen"]))}〜{yen(round(risk["max_yen"]))}）。ATR×開始枚数×商品倍率で決まる損切り基準で、実現損失の絶対上限ではありません。</p>',
             f'<details><summary>10セッションの利益・損失・収支</summary>{results_table(variant["sessions"])}',
             '<p class="note">枚数は返済した建玉の累計。収支欄の枚数差は「利益枚数−損失枚数」で、未返済の枚数ではありません。</p></details></section>']
    return ''.join(parts)


def chapters(data: dict) -> str:
    """４手法をそれぞれ１章にし、同じ章で両銘柄版を説明する。

    引数: data (dict) は換算データ。返り値: 全章のHTML (str)。
    """
    parts = []
    for number, method in enumerate(data['methods'], 1):
        parts.extend([f'<article class="chapter" id="{esc(method["id"])}"><header class="chapter-head">',
                      f'<div class="chapter-number">第{number}章 · 前回の共通順位 {method["rank"]}位</div>',
                      f'<h2>{esc(method["name"])}</h2><div class="method-id">{esc(method["id"])}</div>',
                      f'<dl class="rules"><dt>入口</dt><dd>{text_block(method["entry"])}</dd>',
                      f'<dt>出口</dt><dd>{text_block(method["exit"])}</dd></dl></header>'])
        for symbol in ['TOPIX', 'NK225']:
            parts.append(variant_section(method, symbol, data['products'][symbol]))
        parts.append('</article>')
    return ''.join(parts)


def supplement(data: dict) -> str:
    """均一縮小と計算上の前提を折り畳んで提示する。

    引数: data (dict) は換算データ。返り値: 補足のHTML (str)。
    """
    parts = ['<section class="panel" id="uniform-scale"><h2>補足：100枚上限を同じ割合で縮める場合</h2>',
             '<p>全手法をTOPIXは元の1/10、NK225は元の1/5の枚数にすると、固定型はTOPIXミニ１枚・NK225マイクロ２枚です。固定型の収支・損失・最大下落は上の主案の1/10になり、損益比は変わりません。</p>',
             '<div class="table-wrap"><table><thead><tr><th>手法</th><th>TOPIXミニ・週収支</th><th>NK225マイクロ・週収支</th></tr></thead><tbody>']
    for method in data['methods']:
        parts.append(f'<tr><td>{esc(method["id"])}</td>')
        for symbol in ['TOPIX', 'NK225']:
            uniform = method['variants'][symbol]['uniform']
            parts.append(f'<td class="positive">{yen(uniform["week"]["net_yen"], True)}<span>{esc(uniform["quantity_rule"])}</span></td>')
        parts.append('</tr>')
    parts.extend(['</tbody></table></div><details><summary>価格条件・換算・指標の定義</summary>',
                  '<p>元の売買時刻・価格・方向を保ち、各返済の整数枚数と商品倍率を換算しました。数量以外の条件は変えていません。手法を作る前に既読だった１週間の比較であり、未知期間での成績ではありません。</p>',
                  '<p>ATRは確定した５分足のTRを係数1/12で平滑化し、初回注文を置く時点で固定。１ATR順行してからトレーリングを有効にし、増玉後も全玉合計の損失予算は開始時の値を使います。１組180分。日中15:35・夜間05:50以降の観測で返済を指示し、次の有効な原本行で全返済します。</p>',
                  '<p>利益・損失は正負それぞれの返済損益の合計。１枚平均の利益／損失は、それぞれの合計を利益枚数・損失枚数で割った値の比です。最大下落は、週を通じた含み損益込みの資産曲線の最高点からの下落幅です。</p>',
                  '<p>新規の逆指値は２分有効。開始20分後から新規を受け付け、日中15:05・夜間05:20で新規受付を終えます。全返済後は５分休止。注文設定後、次の生データ行以降で到達を判定します。M3は一方だけを売買する場合も、両銘柄のラージ板・足を観測します。</p>'])
    for symbol in ['TOPIX', 'NK225']:
        product = data['products'][symbol]
        label = 'TOPIXミニ' if symbol == 'TOPIX' else 'NK225マイクロ'
        parts.append(f'<p><a href="{esc(product["source_url"])}">{label}のJPX商品仕様</a>：１指数ポイント当たり{yen(product["multiplier"])}、呼値{product["tick"]:g}ポイント。元のラージ価格を使うため、より細かな呼値による注文の改善は加えていません。</p>')
    parts.extend(['<p>枚数と金額の比例換算なので、この前提では総利益／総損失・１枚平均の利益／損失・黒字セッション数は元の手法と一致します。証拠金に対する利回りを示した数値ではありません。</p>',
                  '<p>元台帳との独立照合に加え、上限と初期・追加枚数を変更した限定再生でも、主案・均一縮小案の160区間で約定価格・時刻・方向・理由の一致を確認しています。<a href="資料/audit_engine_replay.json">数量縮小の再生監査</a>。</p>',
                  '</details></section>'])
    return ''.join(parts)


def update_indexes() -> None:
    """共通の作業一覧を00013への案内に更新する。

    引数: なし。返り値: なし。過去の作業フォルダは変更しない。
    """
    base = OUT.parent
    path = base / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00013の[共通上位４手法のスケールダウン]({FOLDER}/{PAGE})です。TOPIXミニ最大10枚・NK225マイクロ最大20枚での週収支と各セッションの損益を確認できます。**', text, count=1)
    text = text.replace('`00012_状態切替と柔軟な建玉管理`（最新）', '`00012_状態切替と柔軟な建玉管理`')
    text = re.sub(r'^\| `00013_.*\n', '', text, flags=re.M)
    entry = f'| `{FOLDER}`（最新） | 共通４手法を整数枚数で縮小。ミニ10枚・マイクロ20枚 | [スケールダウン版]({FOLDER}/{PAGE}) | [案内と再現方法]({FOLDER}/README.md) |\n'
    text = text.replace('| --- | --- | --- | --- |\n', '| --- | --- | --- | --- |\n' + entry, 1)
    text = text.replace('`00013_内容`', '`00014_内容`')
    path.write_text(text, encoding='utf-8')

    # ----------------------------------------
    path = base / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00013開始-->.*?<!--00013終了-->', '', text, flags=re.S)
    text = text.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は共通上位４手法のスケールダウン版。TOPIXミニ最大10枚・NK225マイクロ最大20枚での週収支を確認できます。</p>', text, count=1)
    entry = f'<!--00013開始--><article class="task latest"><div class="number">作業00013 <span class="badge">最新</span></div><h2>共通上位４手法のスケールダウン</h2><p>手法ごとにTOPIXミニ版・NK225マイクロ版を掲載。整数枚数の規則と、週・各セッションの利益／損失／収支。</p><a class="button" href="{FOLDER}/{PAGE}">スケールダウン版を開く →</a><p><a href="{FOLDER}/README.md">読む順序と再現方法</a></p></article><!--00013終了-->'
    text = text.replace('</header>', '</header>' + entry, 1)
    text = re.sub(r'<footer>最新作業は.*?</footer>', '<footer>最新作業は00013です。過去資料を残し、次の別作業は00014以降へ追加します。</footer>', text, count=1)
    path.write_text(text, encoding='utf-8')


def readme() -> str:
    """最初に見る資料と再現手順を日本語で案内する。

    引数: なし。返り値: README本文 (str)。
    """
    return f'''# 00013 共通上位４手法のスケールダウン

最初に [{PAGE}]({PAGE}) を開いてください。

1. 冒頭で４手法の週収支を確認。
2. 各手法の章で、TOPIXミニ版・NK225マイクロ版の入口、出口、枚数、週損益を確認。セッション別表は折り畳みです。
3. 末尾で、全手法を同じ割合で縮めた場合の週収支と換算条件を確認。

主案は増玉型をTOPIX１枚＋１枚（最大10枚）／NK２枚＋２枚（最大20枚）、固定型をTOPIX10枚／NK20枚としています。固定型の開始時の枚数は増玉型の10倍であり、初期損失予算が異なります。

元の既読１週間の売買台帳を比例換算した試算です。ラージの信号・ATR・価格条件を維持し、mini・microの板で新しく検証した結果ではありません。費用０、セッション内全返済です。

## 資料と再現

- [スケールダウン集計](資料/スケールダウン集計.json)：４手法×２銘柄の主案・均一縮小案。
- [スケールダウン監査](資料/スケールダウン監査.json)：元台帳との照合、整数枚数、上限と比例換算の確認。
- [表示データの照合](資料/audit_report_data.json)：主案・均一縮小案の16週・160セッションと原集計の一致。
- [数量縮小の等価性](資料/audit_数量縮小の等価性.md)：同じ価格条件を保てる理由。
- [数量変更後の再生監査](資料/audit_engine_replay.json)：主案80区間＋均一縮小案80区間を数量・上限を変えて再生し、価格・時刻・方向・返済理由の一致を確認。
- [元の共通ランキング](../00012_状態切替と柔軟な建玉管理/週収支ランキングと両銘柄共通手法.html)：４手法の選定根拠。

再生成はプロジェクトルートで、次の順序で実行します。

1. `python work/wave_v18/scale_analysis.py`：元の保存済み売買台帳から整数枚数と商品倍率を換算。
2. `python work/wave_v18/report_scale.py --publish`：保存済み換算値を読み、HTMLと案内を生成。
3. `python work/wave_v18/check_scale_report.py`：表示値・行数・リンクを照合。

通信は行いません。換算・表示の生成器、テンプレートと監査コードは `資料` にも保存します。

表示はHTMLの静的検査で確認しています。ブラウザーの既存URLポリシー拒否は再試行せず、実画面は未確認です。
'''


def main() -> None:
    """保存済み換算データから別HTMLと案内を作る。

    引数: コマンド行 --publish (bool) は共通の索引更新。返り値: なし。
    """
    parser = argparse.ArgumentParser(description='整数枚数による縮小版の表示')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    data = json.loads((WORK / 'scale_data.json').read_text(encoding='utf-8'))
    assert [m['id'] for m in data['methods']] == METHODS
    nav = '<nav class="nav" aria-label="手法の章">' + ''.join(f'<a href="#{esc(m["id"])}">{i}. {esc(m["id"])}</a>' for i, m in enumerate(data['methods'], 1)) + '</nav>'
    page = (WORK / 'report_scale_template.html').read_text(encoding='utf-8')
    page = page.replace('__OVERVIEW__', overview(data)).replace('__NAV__', nav)
    page = page.replace('__CHAPTERS__', chapters(data)).replace('__SUPPLEMENT__', supplement(data))
    assert not re.search(r'__[A-Z]+__', page)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / '資料').mkdir(exist_ok=True)
    (OUT / PAGE).write_text(page, encoding='utf-8')
    (OUT / 'README.md').write_text(readme(), encoding='utf-8')
    shutil.copy2(WORK / 'scale_data.json', OUT / '資料' / 'スケールダウン集計.json')
    for filename in ['report_scale.py', 'report_scale_template.html', 'scale_analysis.py', '集計検算.json', 'audit_scale.py', 'audit_scale.json', 'audit_report_data.py', 'audit_report_data.json', 'audit_数量縮小の等価性.md', 'audit_engine_replay.py', 'audit_engine_replay.json', 'audit_engine_scaled.py']:
        shutil.copy2(WORK / filename, OUT / '資料' / filename)
    shutil.copy2(WORK / 'audit_scale.json', OUT / '資料' / 'スケールダウン監査.json')
    if args.publish:
        update_indexes()
    print(json.dumps({'作成': str(OUT / PAGE), '手法数': len(data['methods']), '銘柄版数': 8, '索引更新': args.publish}, ensure_ascii=False))


if __name__ == '__main__':
    main()
