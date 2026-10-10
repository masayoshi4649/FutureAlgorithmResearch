"""片方向の同時保有上限を守った枚数配分比較を、４手法別のダークHTMLへまとめる。"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
SEARCH = WORK / 'allocation'
FOLDER = '00013_共通上位４手法のスケールダウン'
OUT = ROOT / 'アルゴリズム調査' / FOLDER
PAGE = '共通上位４手法のスケールダウン.html'
METHODS = ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01']


def esc(value: object) -> str:
    """表示値をHTMLの本文・属性へ安全に差し込める形にする。

    引数: value (object) は表示値。返り値: エスケープ済み文字列 (str)。
    """
    return html.escape(str(value), quote=True)


def yen(value: float, signed: bool = False) -> str:
    """整数の円額をカンマ付き表示にする。

    引数: value (float) は円額、signed (bool) は正数の符号指定。返り値: 円表示 (str)。
    """
    assert abs(value - round(value)) < .01, value
    return (f'{round(value):+,}' if signed else f'{round(value):,}') + '円'


def units(value: float, signed: bool = False) -> str:
    """整数枚数を表示する。

    引数: value (float) は枚数、signed (bool) は符号指定。返り値: 枚数表示 (str)。
    """
    assert abs(value - round(value)) < 1e-6, value
    return (f'{round(value):+,}' if signed else f'{round(value):,}') + '枚'


def ratio(value: float | None) -> str:
    """比率を小数２桁にする。

    引数: value (float | None) は比率。返り値: 比率表示 (str)。
    """
    return '算定なし' if value is None else f'{value:.2f}'


def color(value: float) -> str:
    """損益符号に応じた表示クラスを選ぶ。

    引数: value (float) は損益。返り値: CSSクラス名 (str)。
    """
    return 'positive' if value >= 0 else 'negative'


def session_label(session: str) -> str:
    """開始日基準のセッションを日本語にする。

    引数: session (str) は日付と区分。返り値: 日本語ラベル (str)。
    """
    date, part = session.split('_')
    day = int(date[-2:])
    return f'9/{day} 日中' if part == 'Day' else f'9/{day} 夜間 → 9/{day + 1} 朝'


def allocation_rule(choice: dict) -> str:
    """初回・追加枚数を同時保有上限と区別して短く表示する。

    引数: choice (dict) は配分結果。返り値: 配分の短い説明 (str)。
    """
    config = choice['config']
    extra = f'追加{config["add_qty"]}枚' if config['add_qty'] else '追加なし'
    return f'初回{config["initial_qty"]}枚・{extra}'


def same_allocation(first: dict, second: dict) -> bool:
    """候補と週収支最大の配分が同じか確認する。

    引数: first/second (dict) は配分結果。返り値: 同一配分ならTrue (bool)。
    """
    return all(first['config'][key] == second['config'][key] for key in ['initial_qty', 'add_qty', 'position_cap'])


def position_example(choice: dict) -> str:
    """順行時の保有推移と最後の追加枚数を上限内で示す。

    引数: choice (dict) は配分。返り値: 同時保有の推移例 (str)。
    """
    config = choice['config']
    initial, additional, cap = [config[key] for key in ['initial_qty', 'add_qty', 'position_cap']]
    if not additional:
        return '追加せず、初回枚数のまま返済します。'
    path = [initial]
    while path[-1] < cap:
        path.append(min(cap, path[-1] + additional))
    text = '0.5ATR順行ごとに追加。保有の推移例：' + ' → '.join(str(value) for value in path) + '枚。'
    if len(path) > 1 and path[-1] - path[-2] < additional:
        text += f'最後は残り枠の{path[-1] - path[-2]}枚だけ追加します。'
    return text


def results_table(rows: list[dict], weekly: bool = False) -> str:
    """金額と累計返済枚数を明確に分けた損益表を作る。

    引数: rows (list[dict]) は集計、weekly (bool) は週表の指定。返り値: HTML (str)。
    """
    parts = ['<div class="table-wrap"><table><thead><tr><th>区間</th><th>利益／累計返済枚数</th><th>損失／累計返済枚数</th><th>収支／累計枚数差</th></tr></thead><tbody>']
    for row in rows:
        label = '１週間合計' if weekly else session_label(row['session'])
        parts.append(f'<tr><td>{esc(label)}</td><td class="positive">{yen(row["gross_profit_yen"])}<span>累計返済 {units(row["profit_units"])}</span></td>'
                     f'<td class="negative">{yen(-row["gross_loss_yen"])}<span>累計返済 {units(row["loss_units"])}</span></td>'
                     f'<td class="{color(row["net_yen"])}">{yen(row["net_yen"], True)}<span>累計枚数差 {units(row["unit_balance"], True)}</span></td></tr>')
    parts.append('</tbody></table></div>')
    return ''.join(parts)


def overview(data: dict) -> str:
    """候補配分と最大収支の配分を冒頭の一覧にする。

    引数: data (dict) は再生集計。返り値: 週一覧のHTML (str)。
    """
    parts = ['<section class="panel" id="weekly-overview"><h2>配分別の週収支</h2>',
             f'<p>単純な比例換算ではなく、{data["metadata"]["candidate_count"]}配分を同時保有上限付きで再生。「損小利大候補」はこの週の損益比と黒字区間数で選びます。「週収支最大」はこの１週間の収支額が最大だった配分です。</p>',
             '<div class="table-wrap"><table><thead><tr><th>手法</th><th>TOPIXミニ<br>片方向上限10枚</th><th>NK225マイクロ<br>片方向上限20枚</th></tr></thead><tbody>']
    for method in data['methods']:
        parts.append(f'<tr><td><a href="#{esc(method["id"])}">{esc(method["id"])}</a><span>{esc(method["name"])}</span></td>')
        for symbol in ['TOPIX', 'NK225']:
            variant = method['variants'][symbol]
            selected, largest = variant['selected'], variant['max_net']
            selected_label = '参考' if method['id'] == 'M3_逆_A03' and symbol == 'NK225' else '候補'
            parts.append(f'<td><div class="{color(selected["week"]["net_yen"])} summary-net" data-summary="selected">{selected_label} {yen(selected["week"]["net_yen"], True)}</div><span>{allocation_rule(selected)}</span>')
            parts.append(f'<div class="maximum-result" data-summary="max_net">最大 {yen(largest["week"]["net_yen"], True)}</div><span>{allocation_rule(largest)}</span></td>')
        parts.append('</tr>')
    parts.extend(['</tbody></table></div>',
                  '<p class="note">固定型は枚数を変えても損益比が変わらないため、１枚を代表にします。１枚が最適という意味ではなく、初回から上限まで持つ必要もありません。初回枚数で損失予算も変わるため、収支だけでなく実績最大保有・最大下落も確認してください。</p></section>'])
    return ''.join(parts)


def allocation_section(choice: dict, label: str, key: str) -> str:
    """１配分の同時保有・週損益・累計返済とセッション明細を表示する。

    引数: choice (dict) は配分、label (str) は見出し、key (str) は識別子。
    返り値: 配分説明のHTML (str)。
    """
    week, risk = choice['week'], choice['risk']
    parts = [f'<section class="allocation" data-choice="{key}"><h4>{label}</h4>',
             f'<p class="allocation-rule"><strong>{esc(allocation_rule(choice))}</strong>。{esc(position_example(choice))}</p>',
             f'<p class="position-limit">実績の同時保有最大：買い {units(week["max_long"])} ／ 売り {units(week["max_short"])}</p>',
             f'<div class="result-line"><span>週収支</span><strong class="{color(week["net_yen"])}">{yen(week["net_yen"], True)}</strong><span class="muted">黒字 {week["positive_sessions"]} / {week["session_count"]} セッション</span></div>',
             results_table([week], weekly=True),
             f'<div class="stats"><span>総利益／総損失 <b>{ratio(week["money_ratio"])}倍</b></span><span>１枚平均の利益／損失 <b>{ratio(week["unit_payoff"])}倍</b></span><span>最大下落 <b>{yen(week["drawdown_yen"])}</b></span></div>',
             f'<p class="note">１枚平均：利益 約{yen(round(week["avg_profit_per_unit"]))} ／ 損失 約{yen(round(week["avg_loss_per_unit"]))}。全返済累計 {units(week["closed_units"])}（うち損益０は{units(week["zero_units"])}）。</p>',
             f'<p class="note">初回の損失予算：中央値 約{yen(round(risk["median_yen"]))}。初回枚数×１ATR×商品倍率の損切り基準で、実現損失の絶対上限ではありません。</p>']
    if week['method_id'].endswith('A03') and not choice['config']['add_qty']:
        parts.append('<p class="note">追加０枚のため、この配分は固定型A00と同じ売買経路になります。</p>')
    if key == 'selected' and not choice.get('selection', {}).get('eligible', True):
        parts.append('<p class="note">安定性の選択条件を全て満たす配分はなく、この配分は参考表示です。</p>')
    parts.extend([f'<details class="sessions"><summary>10セッションの利益・損失・収支</summary>{results_table(choice["sessions"])}',
                  '<p class="note">累計返済枚数は売買の繰返しを合計した値です。同時保有枚数ではありません。累計枚数差は「利益返済枚数−損失返済枚数」です。</p></details></section>'])
    return ''.join(parts)


def variant_section(method: dict, symbol: str) -> str:
    """１銘柄の２配分を短く比較する。

    引数: method (dict) は手法、symbol (str) は銘柄。返り値: 銘柄版のHTML (str)。
    """
    variant = method['variants'][symbol]
    selected, largest = variant['selected'], variant['max_net']
    label = 'TOPIXミニ版' if symbol == 'TOPIX' else 'NK225マイクロ版'
    style = 'topix' if symbol == 'TOPIX' else 'nk'
    cap = selected['config']['position_cap']
    reference = method['id'] == 'M3_逆_A03' and symbol == 'NK225'
    selected_label = '損益比上位の参考配分（１枚差に敏感）' if reference else '損小利大候補の配分'
    parts = [f'<section class="variant {style}" data-method="{esc(method["id"])}" data-symbol="{symbol}">',
             f'<h3>{label}</h3><p class="position-limit">同時保有上限：買い {units(cap)} ／ 売り {units(cap)}</p>',
             allocation_section(selected, selected_label, 'selected')]
    if reference:
        values = ' ／ '.join(f'追加{row["add_qty"]}枚：{yen(row["net_yen"], True)}' for row in variant['neighbors'])
        parts.append(f'<div class="callout sensitivity"><p><b>初回１枚で追加枚数だけを変えた週収支</b><br>{esc(values)}<br>追加16→17枚で赤字へ変わります。条件を通過した配分でも、将来の安定性を示すものではありません。</p></div>')
    if method['id'] == 'M3_逆_A03' and symbol == 'TOPIX':
        parts.append('<details class="topix-neighbors"><summary>近い配分も、この週は黒字</summary><div class="table-wrap"><table><thead><tr><th>初回・追加</th><th>週収支</th></tr></thead><tbody>')
        for row in variant['neighbors']:
            parts.append(f'<tr><td>初回{row["initial_qty"]}枚・追加{row["add_qty"]}枚</td><td>{yen(row["net_yen"], True)}</td></tr>')
        parts.append('</tbody></table></div><p class="note">近傍の配分が黒字でも、未知期間の安定性を保証するものではありません。</p></details>')
    if same_allocation(selected, largest):
        parts.append('<p class="maximum-result" data-same-allocation="true">週収支最大も同じ配分です。</p>')
    else:
        parts.append(f'<details class="max-choice"><summary>週収支最大：{esc(allocation_rule(largest))} ／ {yen(largest["week"]["net_yen"], True)}</summary>')
        parts.append(allocation_section(largest, '週収支最大の配分', 'max_net'))
        parts.append('</details>')
    parts.append('</section>')
    return ''.join(parts)


def chapters(data: dict) -> str:
    """４手法を章にし、各章で両銘柄の配分を説明する。

    引数: data (dict) は再生集計。返り値: 全章のHTML (str)。
    """
    parts = []
    for number, method in enumerate(data['methods'], 1):
        parts.extend([f'<article class="chapter" id="{esc(method["id"])}"><header class="chapter-head">',
                      f'<div class="chapter-number">第{number}章 · 元の共通順位 {method["rank"]}位</div>',
                      f'<h2>{esc(method["name"])}</h2><div class="method-id">{esc(method["id"])}</div>',
                      f'<dl class="rules"><dt>入口</dt><dd>{esc(method["entry"])}</dd><dt>出口</dt><dd>{esc(method["exit"])}</dd></dl></header>'])
        parts.extend(variant_section(method, symbol) for symbol in ['TOPIX', 'NK225'])
        parts.append('</article>')
    return ''.join(parts)


def supplement(data: dict) -> str:
    """選択条件と観測・注文条件を短い補足にする。

    引数: data (dict) は再生集計。返り値: 補足HTML (str)。
    """
    parts = ['<section class="panel"><h2>比較の条件</h2><details><summary>配分の選び方・計算上の前提</summary>',
             '<p>損小利大候補は、週黒字、総利益／総損失と１枚平均の利益／損失がともに１超、黒字６／10区間以上、最大利益の１区間を除いても黒字の配分を対象にします。その中で２つの損益比の小さい方を優先し、同点なら収支／最大下落、小さい初回枚数、小さい追加枚数の順で選びます。固定型は比率が変わらないため１枚を代表にします。</p>',
             '<p>初回・追加枚数と同時保有上限を変えて保存済みデータを再生しています。新配分の結果は、旧結果の単純な比例換算ではありません。同じ既読１週間の探索なので、未知の週での検証とは区別してください。</p>',
             '<p>同時保有は未返済の買い・売りを別々に数えます。追加時は上限までの残り枚数を超えません。４手法とも両建て・部分利確・保有中の反転はなく、各セッション内で全玉返済します。</p>',
             '<p>ラージの信号・ATR・価格を観測し、mini・microも同じ価格で約定する仮定です。M3は片方だけを売買する場合も両銘柄を観測します。ATRは確定５分足のTRを係数1/12で平滑化し、初回注文時に固定。１ATR順行後にトレーリングを有効にし、増玉後も組全体の損失予算は初回の値を維持します。</p>',
             '<p>新規の逆指値は２分有効。開始20分後から新規受付し、日中15:05・夜間05:20で締切。全返済後は５分休止。１組180分。日中15:35・夜間05:50以降に返済を指示し、次の有効な原本行で全返済します。</p>',
             '<p>利益・損失は正負それぞれの返済損益の合計。１枚平均は各合計を利益返済枚数・損失返済枚数で割った値です。最大下落は週を通じた含み損益込みの最高点からの下落幅。累計枚数差は保有残高ではなく、全セッションの未返済残は０です。</p>']
    for symbol in ['TOPIX', 'NK225']:
        product = data['products'][symbol]
        parts.append(f'<p><a href="{esc(product["source_url"])}">{esc(product["name"])}のJPX仕様</a>：１指数ポイント当たり{yen(product["multiplier"])}、呼値{product["tick"]:g}ポイント。元の価格刻みは維持し、細かい呼値への再最適化は行っていません。</p>')
    parts.extend(['<p>旧ページの比例換算は、配分を固定した旧前提の参考として<a href="資料/旧比例換算/スケールダウン集計.json">旧集計</a>に保存しています。このページの配分探索結果とは混ぜていません。</p>',
                  '</details></section>'])
    return ''.join(parts)


def update_indexes() -> None:
    """共通一覧を同時保有上限内の配分比較に更新する。

    引数: なし。返り値: なし。過去の作業フォルダは変更しない。
    """
    base = OUT.parent
    path = base / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00013の[共通上位４手法のスケールダウン]({FOLDER}/{PAGE})です。片方向の同時保有上限をTOPIXミニ10枚・NK225マイクロ20枚とし、初回・追加枚数を比較しました。**', text, count=1)
    text = re.sub(r'^\| `00013_.*\n', '', text, flags=re.M)
    entry = f'| `{FOLDER}`（最新） | 同時保有上限内で初回・追加枚数を比較。候補と週収支最大 | [スケールダウン版]({FOLDER}/{PAGE}) | [案内と再現方法]({FOLDER}/README.md) |\n'
    text = text.replace('| --- | --- | --- | --- |\n', '| --- | --- | --- | --- |\n' + entry, 1)
    path.write_text(text, encoding='utf-8')

    # ----------------------------------------
    path = base / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00013開始-->.*?<!--00013終了-->', '', text, flags=re.S)
    text = text.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は共通４手法の枚数配分比較。片方向の同時保有をTOPIXミニ10枚・NK225マイクロ20枚に制限しています。</p>', text, count=1)
    entry = f'<!--00013開始--><article class="task latest"><div class="number">作業00013 <span class="badge">最新</span></div><h2>共通上位４手法のスケールダウン</h2><p>同時保有上限内で初回・追加枚数を比較。手法別にTOPIX版・NK版の損小利大候補と週収支最大を掲載。</p><a class="button" href="{FOLDER}/{PAGE}">配分比較を開く →</a><p><a href="{FOLDER}/README.md">読む順序と再現方法</a></p></article><!--00013終了-->'
    text = text.replace('</header>', '</header>' + entry, 1)
    path.write_text(text, encoding='utf-8')


def readme() -> str:
    """読む順序と同時保有・累計返済の違いを案内する。

    引数: なし。返り値: README本文 (str)。
    """
    return f'''# 00013 共通上位４手法のスケールダウン

最初に [{PAGE}]({PAGE}) を開いてください。

1. 冒頭で、TOPIXミニ片方向10枚・NK225マイクロ片方向20枚の**同時保有上限**と配分別週収支を確認。
2. 各手法の章で、両銘柄の初回・追加枚数、実績最大保有、損小利大候補の損益を確認。週収支最大の配分と10セッション明細は折り畳みです。
3. 末尾で候補の選択条件と再生の前提を確認。

上限は未返済の買い・売りごとに適用します。この４手法は両建てしません。１枚を建てて返す売買を20回繰り返した場合、同時保有は１枚、累計返済は20枚です。固定型は初回から上限枚数を持つ必要はなく、１枚を候補の代表として上限枚数時の結果と併記します。

初回・追加枚数を変えて同じ既読１週間を再生した結果です。ラージの信号・ATR・価格を使用し、mini・micro自体の板や未知の週による検証ではありません。費用０、指定価格約定、セッション内全返済です。旧比例換算は [旧前提の参考集計](資料/旧比例換算/スケールダウン集計.json) として残しています。

## 資料と再現

- [配分比較集計](資料/配分比較集計.json)：４手法×２銘柄の候補配分・週収支最大配分。
- [配分比較監査](資料/配分比較監査.json)：元台帳・整数枚数・片方向上限・集計の独立照合。
- [表示静的検査](資料/表示静的検査.json)：HTMLの表示値・行数・リンク。
- [元の共通ランキング](../00012_状態切替と柔軟な建玉管理/週収支ランキングと両銘柄共通手法.html)：４手法の選定元。

再生成はプロジェクトルートで次の順序です。表示だけ更新する場合は２から実行します。

1. `python work/wave_v18/allocation/search_allocation.py`：保存済み原本で初回・追加配分を再生し、候補を選択。
2. `python work/wave_v18/report_scale.py --publish`：`allocation_report_data.json` の確定集計からHTMLと案内を生成。
3. `python work/wave_v18/check_scale_report.py`：表示値とリンクを照合。

配分比較の生成・監査コードは `資料/配分比較` に保存しています。表示生成は通信・売買再計算を行いません。

表示は静的検査で確認しています。ブラウザーの既存URLポリシー拒否を再試行せず、実画面は未確認です。
'''


def main() -> None:
    """確定した配分再生集計からHTMLと資料案内を生成する。

    引数: コマンド行 --publish (bool) は共通索引の更新指定。返り値: なし。
    """
    parser = argparse.ArgumentParser(description='片方向の同時保有上限内で配分を比較した結果を表示')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    data_path = SEARCH / 'allocation_report_data.json'
    data = json.loads(data_path.read_text(encoding='utf-8'))
    assert [m['id'] for m in data['methods']] == METHODS
    all_weeks = json.loads((SEARCH / '全配分の週合計.json').read_text(encoding='utf-8'))
    first = data['methods'][0]
    first['variants']['NK225']['neighbors'] = sorted([row for row in all_weeks if row['method_id'] == first['id'] and row['symbol'] == 'NK225' and row['initial_qty'] == 1 and row['add_qty'] in [15, 16, 17]], key=lambda row: row['add_qty'])
    assert len(first['variants']['NK225']['neighbors']) == 3
    nearby_topix = {(6, 3), (7, 2), (7, 3), (8, 2)}
    first['variants']['TOPIX']['neighbors'] = sorted([row for row in all_weeks if row['method_id'] == first['id'] and row['symbol'] == 'TOPIX' and (row['initial_qty'], row['add_qty']) in nearby_topix], key=lambda row: (row['initial_qty'], row['add_qty']))
    assert len(first['variants']['TOPIX']['neighbors']) == 4
    nav = '<nav class="nav" aria-label="手法の章">' + ''.join(f'<a href="#{esc(m["id"])}">{i}. {esc(m["id"])}</a>' for i, m in enumerate(data['methods'], 1)) + '</nav>'
    page = (WORK / 'report_scale_template.html').read_text(encoding='utf-8')
    page = page.replace('__OVERVIEW__', overview(data)).replace('__NAV__', nav)
    page = page.replace('__CHAPTERS__', chapters(data)).replace('__SUPPLEMENT__', supplement(data))
    assert not re.search(r'__[A-Z]+__', page)
    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = OUT / '資料'
    artifacts.mkdir(exist_ok=True)
    (OUT / PAGE).write_text(page, encoding='utf-8')
    (OUT / 'README.md').write_text(readme(), encoding='utf-8')
    shutil.copy2(data_path, artifacts / '配分比較集計.json')
    shutil.copy2(SEARCH / 'audit_allocation.json', artifacts / '配分比較監査.json')
    for filename in ['report_scale.py', 'report_scale_template.html']:
        shutil.copy2(WORK / filename, artifacts / filename)
    archive = artifacts / '配分比較'
    archive.mkdir(exist_ok=True)
    for path in SEARCH.iterdir():
        if path.is_file() and path.suffix in {'.json', '.py', '.md', '.csv'}:
            shutil.copy2(path, archive / path.name)
    if args.publish:
        update_indexes()
    print(json.dumps({'作成': str(OUT / PAGE), '手法数': 4, '銘柄版数': 8, '索引更新': args.publish}, ensure_ascii=False))


if __name__ == '__main__':
    main()
