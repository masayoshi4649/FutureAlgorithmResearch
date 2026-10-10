"""保有中ATRの比較を短い結論、全損益、再現資料へ分けて表示する。"""

from __future__ import annotations

from html import escape
import argparse
import json
from pathlib import Path
import re

import numpy as np

import atr_runner as runner

HERE, ROOT = runner.HERE, runner.ROOT
NAME = '00028_保有中ATRによる追跡幅更新'
OUT = ROOT / 'アルゴリズム調査' / NAME
TITLE = '保有中ATRによる追跡幅更新'
SYMBOLS = ('TOPIX', 'NK225')
CSS = ''':root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0b1320;color:#e1ecfa}body{max-width:1280px;margin:auto;padding:26px 20px;line-height:1.75}h1{font-size:28px}h2{font-size:22px;margin-top:28px}h3{font-size:18px}a{color:#91ccff}.good{color:#70dfb2}.bad{color:#ff99a7}.muted{color:#adc0d6}.lead{font-size:19px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{border-bottom:1px solid #2c425d;padding:7px 10px;text-align:right}th{background:#1a2b42;color:#c0d9f5}th:first-child,td:first-child{text-align:left}details{padding:14px;margin:14px 0;border:1px solid #334a66;border-radius:8px;background:#111e30}summary{cursor:pointer;font-weight:bold}.button{display:inline-block;padding:9px 14px;background:#225d92;border-radius:6px;margin:5px 10px 5px 0}.filters{display:flex;gap:16px;flex-wrap:wrap}select{font:inherit;color:#e1ecfa;background:#15273d;padding:5px}.method[hidden]{display:none}code{color:#c8dbfa}'''


def yen(value: float) -> str:
    """機能: 円の正負を色と符号の両方で示す。

    引数: value (float)。返り値: HTML文字列 (str)。
    """
    return f'<span class="{"good" if value > 0 else "bad" if value < 0 else "muted"}">{value:+,.0f}</span>'


def number(value: float | None, digits: int = 2) -> str:
    """機能: 未計測値とゼロを混同しない数字表示を作る。

    引数: value (float|None)、digits (int)。返り値: 表示 (str)。
    """
    return '—' if value is None else f'{value:,.{digits}f}'


def table(headers: list[str], rows: list[list], attrs: str = '') -> str:
    """機能: 横長の比較表を暗色のスクロール枠で囲む。

    引数: headers (list[str])、rows (list[list])、attrs (str)。返り値: HTML (str)。
    """
    return '<div class="scroll"><table ' + attrs + '><thead><tr>' + ''.join('<th>' + h + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + str(v) + '</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def page(title: str, body: list[str], script: str = '') -> str:
    """機能: 日本語・ダークテーマの単独HTMLを組み立てる。

    引数: title (str)、body (list[str])、script (str)。返り値: HTML (str)。
    """
    return '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + title + '</title><style>' + CSS + '</style><body><!--\n[コンポーネント概要]\n比較表は既知保存データの全玉計測を表示します。.methodは手法別の週・セッション損益です。\n表示の選択は売買条件や採否に影響しません。\n-->' + ''.join(body) + '<script>' + script + '</script></body></html>'


def totals(rows: list[dict]) -> dict:
    """機能: 同銘柄の利益・損失・返済枚数だけを合算する。

    引数: rows (list[dict])。返り値: 集計 (dict)。
    """
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
    return {field: sum(r[field] for r in rows) for field in fields}


def money_row(label: str, item: dict) -> list:
    """機能: 金額損小利大と勝ち負け枚数を同じ行に示す。

    引数: label (str)、item (dict)。返り値: 表行 (list)。
    """
    return [label, yen(item['gross_profit_yen']), yen(-item['gross_loss_yen']), yen(item['net_yen']),
            item['profit_units'], item['loss_units'], item['zero_units'], item['profit_units'] - item['loss_units']]


def description(spec: dict) -> str:
    """機能: 何を固定し何を変えたかを一文で説明する。

    引数: spec (dict)。返り値: 日本語 (str)。
    """
    base = '幅を新規準備時のATRの3倍に固定。' if spec['atr_mode'] == 'initial' else '保有中の公開済みATRの3倍へ追跡幅を更新。既設の返済線は緩めません。'
    variants = {'V000': '主比較。', 'V015': '入口方向だけ15秒遅らせる診断。',
                'O000': '全約定を条件成立時の観測価格とする診断。', 'L300': '追跡ATRだけ5分古くする診断。入口と初期ATRは変えません。'}
    return base + variants[spec['variant_id']]


def all_results(candidates: list[dict], fixed: dict, preview: bool = False) -> None:
    """機能: 全96条件の金額・枚数を週別と各セッション別に漏れなく表示する。

    引数: candidates (list[dict])、fixed (dict)、preview (bool)。返り値: なし (None)。
    """
    body = ['<p><a href="' + TITLE + '.html">比較の結論へ</a></p><h1>全96条件の損益</h1>',
            '<p>TOPIXミニ／NKマイクロ換算。利益・損失は返済脚ごと、枚数は延べ返済枚数です。勝ち枚数−負け枚数は数量の差で、損益額ではありません。</p>',
            '<div class="filters"><label>入口<select id="signal-filter"><option value="">全入口</option>' + ''.join('<option' + (' selected' if h == 'H019' else '') + '>' + h + '</option>' for h in sorted({r['spec']['signal_id'] for r in candidates})) + '</select></label>',
            '<label>比較<select id="role-filter"><option value="">全条件</option><option value="primary" selected>主24条件</option><option value="diagnostic">診断72条件</option></select></label><span id="visible-count"></span></div>']
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示です。全検査の完了後に正式版へ更新します。</strong></p>')
    headers = ['区間', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '同値枚数', '勝ち−負け枚数']
    for item in candidates:
        spec, identifier = item['spec'], item['id']
        opened = ' open' if identifier == 'H019__A0__V000' else ''
        body.append(f'<details class="method" data-signal="{spec["signal_id"]}" data-role="{spec["role"]}" id="{identifier}"{opened}><summary>{identifier}：' + ('固定ATR' if spec['atr_mode'] == 'initial' else '保有中ATR') + '</summary><p>' + description(spec) + '</p>')
        raw = runner.read(HERE / 'sessions' / (identifier + '.json.gz'))
        for symbol in SYMBOLS:
            part = [r for r in raw if r['symbol'] == symbol]
            rows = [money_row('共通後半7', item['symbols'][symbol]), money_row('全13', item['all_symbols'][symbol])]
            for label, predicate in (('9/21開始週', lambda s: s < '2026-09-28'), ('9/28開始週・途中', lambda s: s >= '2026-09-28')):
                rows.append(money_row(label, totals([r for r in part if predicate(r['session'])])))
            rows += [money_row(r['session'], r) for r in sorted(part, key=lambda r: r['session'])]
            body.append('<h3>' + symbol + '</h3>' + table(headers, rows, f'data-id="{identifier}" data-symbol="{symbol}"'))
        body.append('</details>')
    script = '''/**
 * 表示する入口と主条件・診断を絞る。
 * @param {Event|undefined} event - 表示選択の操作。
 * @returns {undefined} 返り値なし。計算条件と売買は変更しない。
 */
function filter(event){let n=0;document.querySelectorAll('.method').forEach(e=>{e.hidden=['signal','role'].some(k=>{const v=document.getElementById(k+'-filter').value;return v&&v!==e.dataset[k]});if(!e.hidden)n++});document.getElementById('visible-count').textContent=n+'条件を表示'}document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filter));filter();'''
    (OUT / '全条件損益.html').write_text(page('全96条件の損益', body, script), encoding='utf-8')


def update_index() -> None:
    """機能: 過去作業を残し、最新作業の入口を更新する。

    引数: なし。返り値: なし (None)。
    """
    path = OUT.parent / 'index.html'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'<!--00028開始-->.*?<!--00028終了-->', '', source, flags=re.S)
    source = source.replace('task latest', 'task').replace(' <span class="badge">最新</span>', '')
    source = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は00028：保有中ATRの更新を同じ入口・枚数で比較。現在セッションの再取得はありません。</p>', source, count=1)
    block = f'<!--00028開始--><article class="task latest"><div class="number">作業00028 <span class="badge">最新</span></div><h2>{TITLE}</h2><p>主24条件と診断72条件。利益返却と波の途中退出を両方確認。</p><a class="button" href="{NAME}/{TITLE}.html">比較の結論 →</a><p><a href="{NAME}/全条件損益.html">全96条件の損益</a> ／ <a href="{NAME}/README.md">資料案内</a></p></article><!--00028終了-->'
    path.write_text(source.replace('</header>', '</header>' + block, 1), encoding='utf-8')
    path = OUT.parent / 'README.md'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00028の[{TITLE}]({NAME}/{TITLE}.html)。**', source, count=1)
    source = re.sub(r'^\| `00028_.*\n', '', source, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    source = source.replace(anchor, anchor + f'\n| `{NAME}`（最新） | 固定/現在ATRの対応比較96条件 | [第9反復]({NAME}/{TITLE}.html) | [資料案内]({NAME}/README.md) |', 1)
    path.write_text(source, encoding='utf-8')


def main() -> None:
    """機能: 全検査の完了を確認した結果だけを正式な比較として出力する。

    引数: --preview (bool) は暫定表示専用。返り値: なし (None)。
    """
    OUT.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    preview = parser.parse_args().preview
    fixed = runner.read(HERE / '探索条件の固定.json')
    candidates = runner.read(HERE / '全条件の期間集計.json.gz')
    if not preview:
        guard = runner.read(HERE / '完備監査.json')
        assert guard['検証完了'] is True and guard['全条件数'] == 96 and guard['全入力数'] == 2496
        assert guard['全指定波数'] == 768 and guard['全図示数'] == 52
        assert guard['ガード実装SHA256'] == runner.digest(HERE / 'completion_guard.py')
        assert guard['ガード固定SHA256'] == runner.digest(HERE / 'completion_guard_fixed.json')
        for name, expected in guard['参照資料SHA256'].items():
            path = Path(name)
            assert runner.digest(path if path.is_absolute() else ROOT / path) == expected
    by_id = {row['id']: row for row in candidates}
    h019 = [by_id['H019__' + mode + '__V000'] for mode in ('A0', 'AT')]
    interpretation = runner.read(HERE / '報告用結論.json')
    body = ['<p><a href="../index.html">作業一覧</a></p><h1>' + TITLE + '</h1>',
            '<p class="lead"><strong>' + escape(interpretation['見出し']) + '</strong></p>',
            '<p>' + escape(interpretation['説明']) + '</p>',
            '<p class="muted">TOPIXミニ5枚／NKマイクロ10枚、片方向上限10／20枚。費用0、指定価格約定、全玉場内返済。全13セッションは既知データ。後半7も未知検証ではありません。</p>',
            '<p><a class="button" href="全条件損益.html">全96条件・各週・各セッションの損益</a><a class="button" href="５分足と売買.html">H019の５分足と売買</a></p>',
            '<h2>既存H019の固定幅と更新幅</h2>']
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示です。全検査の完了後に正式版へ更新します。</strong></p>')
    rows = []
    for period, label in (('all_symbols', '全13'), ('symbols', '共通後半7')):
        for item in h019:
            for symbol in SYMBOLS:
                r = item[period][symbol]
                rows.append([label, symbol, '固定' if item['spec']['atr_mode'] == 'initial' else '更新',
                             yen(r['gross_profit_yen']), yen(-r['gross_loss_yen']), yen(r['net_yen']),
                             number(r['drawdown_yen'], 0), number(r['money_ratio']), number(r['average_unit_payoff']),
                             f"{r['profit_units']}/{r['loss_units']}/{r['zero_units']}"])
    body.append(table(['区間', '銘柄', '追跡幅', '利益 円', '損失 円', '収支 円', '最大下落 円', '利益/損失', '平均勝ち枚/負け枚', '勝/負/同値枚'], rows, 'id="main-comparison"'))
    body.append('<p>平均勝ち枚/負け枚は「利益額÷利益枚数」を「損失額÷損失枚数」で割った比率です。最大下落は含み損益を含みます。</p>')
    body.append('<details><summary>機械的な入口と出口</summary><p>H019：公開済み1分足のEMA15/60で主方向を判定し、相手銘柄の60秒前の主方向と一致、自銘柄の気配中間値の30秒変化も同方向なら新規を許可。0.25ATRの反発／反落追跡で入ります。</p><p>新規準備時のATRをA0とし、初期損失予算は枚数×1A0。2A0順行で整数半分を利確し、1.5A0順行後の残玉を追跡します。固定幅は3A0、更新幅は保有中に公開済みの3At。既設線は緩めず、更新は次の原本行から有効です。最長360分、全返済後5分休止、場末は全返済。</p><p>ATRは確定5分足12本の平滑値。足開始＋360秒で解放した値だけを使用し、未確定足は使いません。初期予算・追跡開始・部分利確には更新ATRを使いません。</p></details>')
    body.append('<details><summary>利益返却と早期退出のトレードオフ</summary><p>' + escape(interpretation['返却の説明']) + '</p>')
    rows = []
    for item in h019:
        for symbol in SYMBOLS:
            a = item['all_symbols'][symbol]
            r = a['retracement']['all']
            p = a['retracement']['positive_peak']
            rows.append([symbol, '固定' if item['spec']['atr_mode'] == 'initial' else '更新', r['cycles'],
                         number(r['sum_yen'], 0), number(r['mean_yen'], 0), number(r['median_yen'], 0),
                         number(r['mean_r']), number(r['median_r']), number(p['sum_yen'], 0),
                         number(a['retracement']['holding_minutes']), item['wave_passes']])
    body.append(table(['銘柄', '幅', '取引組数', 'ピーク悪化合計 円', '平均 円', '中央値 円', '平均 R', '中央値 R', '利益経験組の返却 円', '組保有合計 分', '指定波/8'], rows))
    body.append('<p class="muted">ピーク悪化は各組の実現＋含み損益の最高点から全返済までの低下。利益未経験の損失組も含めます。「利益経験組」列だけは一度でもプラスになった組を抽出。1Rはその組の初回枚数×A0×円倍率。早期退出で取引数も変わるため合計だけで判断しません。指定波は正方向ネット保有の合計20分を目安とし、利益保証ではありません。</p></details>')
    body.append('<details><summary>なぜTOPIXが悪化したか</summary><p>9/25は、固定幅なら同じロングを継続して＋90,000円。更新幅では先に＋42,000円で退出し、その後の5回が全て損切りで−95,000円、セッション計−53,000円になりました。9/29も新規1回→5回、＋25,000円→−31,500円です。</p><p>全13を厳密に同じ新規約定で照合すると、TOPIXの収支低下538,000円のうち、一致する41組の返済差が194,000円、異なる新規経路の差が344,000円でした。後者は新規時刻も変わるので、再新規を禁止した場合の効果そのものではありません。</p><p><a href="../../work/wave_v33/新規経路の事後分解.md">新規経路の全分解と時系列</a>。出口の変更と再新規の増加を分離する次の検証に使います。<a href="../../work/wave_v33/文献からの再新規設計.md">文献と次の仮説</a>も、今回の実証結果と区別して記録しました。</p></details>')
    body.append('<details><summary>全12入口の対応比較</summary><p>更新−固定の差。新たな最良入口へ採用候補を差し替えていません。</p>')
    overview = []
    signals = sorted({r['spec']['signal_id'] for r in candidates})
    for period, label in (('all_symbols', '全13'), ('symbols', '共通後半7')):
        for symbol in SYMBOLS:
            differences = []
            for signal in signals:
                x, y = [by_id[signal + '__' + mode + '__V000'][period][symbol] for mode in ('A0', 'AT')]
                differences.append([y['net_yen'] - x['net_yen'], y['drawdown_yen'] - x['drawdown_yen'],
                                    y['retracement']['all']['mean_r'] - x['retracement']['all']['mean_r']])
            values = np.asarray(differences)
            counts = []
            for col, sign in ((0, 1), (1, -1), (2, -1)):
                v = values[:, col] * sign
                counts.append(f'{sum(v > 1e-6)}/{sum(v < -1e-6)}/{sum(abs(v) <= 1e-6)}')
            overview.append([label, symbol, yen(float(np.median(values[:, 0]))), counts[0],
                             number(float(np.median(values[:, 1])), 0), counts[1],
                             number(float(np.median(values[:, 2]))), counts[2]])
    body.append(table(['区間', '銘柄', '収支差中央値 円', '収支 改善/悪化/同値', '最大下落差中央値 円',
                       '最大下落 改善/悪化/同値', '平均悪化差中央値 R', 'ピーク悪化 改善/悪化/同値'], overview))
    body.append('<p>以下は全13セッションの各対応組です。後半7と全週・全セッションの各値は全条件損益へ掲載しています。</p>')
    rows = []
    for signal in sorted({r['spec']['signal_id'] for r in candidates}):
        a, b = [by_id[signal + '__' + mode + '__V000'] for mode in ('A0', 'AT')]
        for symbol in SYMBOLS:
            x, y = a['all_symbols'][symbol], b['all_symbols'][symbol]
            rows.append([signal, symbol, yen(x['net_yen']), yen(y['net_yen']), yen(y['net_yen'] - x['net_yen']),
                         number(x['drawdown_yen'], 0), number(y['drawdown_yen'], 0),
                         number(y['retracement']['all']['mean_r'] - x['retracement']['all']['mean_r']),
                         f"{a['wave_passes']}→{b['wave_passes']}"])
    body.append(table(['入口', '銘柄', '固定収支 円', '更新収支 円', '収支差 円', '固定最大下落', '更新最大下落', '平均ピーク悪化差 R', '指定波/8'], rows) + '</details>')
    body.append('<details><summary>敵対検証と限界</summary><p>' + escape(interpretation['反証の説明']) + '</p><p>24主条件に対して、入口15秒遅延・観測価格約定・追跡ATRの5分遅延の72診断を全て保存。診断の最良値を採用しません。未来切断・未来改変・上下反射・独立全玉会計を照合しました。</p><p>固定H019自体も大量探索で選ばれています。既知データで黒字でも、未知期間の期待値が証明されたとは扱いません。原本はラージ先物で、小口商品へ価格倍率を換算。CurrentPriceTimeは受信時刻ではなく、同値時刻の原本順を用います。</p><p><a href="README.md">設計・全会計・再現資料</a></p></details>')
    history = [
        ('00020_大量探索と反証の反復', '発見と反証.html', 36668, '板・価格・注文管理の広い組合せ'),
        ('00021_時間窓への依存を減らす再探索', '再探索と反証.html', 19776, '時間窓依存と波の検知'),
        ('00022_中期方向と板の入口を分離', '中期方向と入口の検証.html', 19776, '中期方向と短期入口の分離'),
        ('00023_保有撤回と損失上限の再設計', '保有撤回と損失上限.html', 27648, '保有撤回・連敗・損失予算'),
        ('00024_部分利確と最高利益の保護', '部分利確と利益保護.html', 4800, '部分利確と含み益の保護'),
        ('00025_相手不一致と保有撤回の分離', '相手不一致と保有撤回.html', 84, '相手と自己の方向を分けて撤回'),
        ('00026_方向情報の鮮度と保有継続', '方向情報の鮮度と保有継続.html', 420, '方向の鮮度と開始待ちの分離'),
        ('00027_順張りと反転の機械的選択', '順張りと反転の機械的選択.html', 148, '状態・過去成績による自動選択'),
        (NAME, TITLE + '.html', 96, '保有中ATRと固定ATRの対応比較')]
    body.append('<details><summary>ここまでの9反復・延べ109,416条件</summary><p>同じ条件の再確認も含む延べ数です。独立した109,416の市場・仮説という意味ではありません。発見後の反証と改良を順に保存しています。</p>' + table(['作業', '主格子と診断の延べ条件', '確認した考え方'],
        [[f'<a href="../{folder}/{filename}">{folder[:5]}</a>', f'{count:,}', purpose] for folder, filename, count, purpose in history]) +
        '<p><a href="../../work/wave_v32/探索全体の達成範囲.md">既存H019が通った検査と残る弱点</a>：最大2勝ち除外・指定波・方向反転・無関係方向の対照、時計依存と大量探索の限界を区別しています。</p></details>')
    (OUT / (TITLE + '.html')).write_text(page(TITLE, body), encoding='utf-8')
    all_results(candidates, fixed, preview)
    (OUT / 'README.md').write_text(f'''# 作業00028：{TITLE}

最初は [{TITLE}]({TITLE}.html) を開いてください。

{'独立監査中の暫定表示です。' if preview else '全件監査完了。'}

読む順序：
1. 主候補H019の固定幅／保有中ATR幅の比較。
2. [全96条件の損益](全条件損益.html)：銘柄別の週・各セッションの金額／決済枚数。
3. [５分足と売買](５分足と売買.html)：H019固定／更新の全26入力ずつ。
4. [固定設計](../../work/wave_v33/design_fixed.md)、[入力の因果監査](../../work/wave_v33/input_audit.md)、[独立会計](../../work/wave_v33/accounting_audit.md)、[完備監査](../../work/wave_v33/完備監査.json)。
5. [今回の結論と次の検証](../../work/wave_v33/反復結果と次の検証.md)、[再新規制御の設計レビュー](../../work/wave_v33/次反復の再新規制御レビュー.md)。次案の成績はまだ検証していません。

主24条件、診断72条件。12入口をすべて対応比較し、採否対象は事前のH019更新幅だけ。診断最良への差替なし。旧作業・原本・現在保存データは変更していません。

再現は `python -X utf8 work/wave_v33/run_verified.py --workers 8`。事前固定・起動前監査が一致する場合だけ全96を再計算します。現在API・保存ライブは使用しません。
''', encoding='utf-8')
    if not preview:
        update_index()
    print(json.dumps({'主条件': 24, '診断': 72, '全損益表': 192, '全損益行': 3264}, ensure_ascii=False))


if __name__ == '__main__':
    main()
