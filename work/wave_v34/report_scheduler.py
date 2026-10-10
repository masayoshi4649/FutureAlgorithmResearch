"""仮想建玉の制御効果を短い比較と全損益へ分けて報告する。"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import re
import sys

import numpy as np
import scheduler_runner as runner

sys.path.insert(0, str(runner.OLD))
import report_atr as style

HERE, ROOT = runner.HERE, runner.ROOT
NAME = '00029_仮想建玉による再エントリー制御'
TITLE = '仮想建玉による再エントリー制御'
OUT = ROOT / 'アルゴリズム調査' / NAME
table, page, yen, number = style.table, style.page, style.yen, style.number
SYMBOLS = ('TOPIX', 'NK225')
MAIN_IDS = ('H019__A0__NORMAL__V000', 'H019__AT__NORMAL__V000', 'H019__AT__SHADOW__V000')


def label(spec: dict) -> str:
    """機能: ATR方式と再新規方式を短く区別する。

    引数: spec (dict)。返り値: 表示名 (str)。
    """
    return ('固定幅' if spec['atr_mode_id'] == 'A0' else '更新幅') + ('＋再新規制御' if spec['gated'] else '＋通常新規')


def description(spec: dict) -> str:
    """機能: 条件の変更点を日本語で説明する。

    引数: spec (dict)。返り値: 説明 (str)。
    """
    return style.description(spec) + ('仮想の固定幅方式が新しい注文を準備した行だけ実側も参加。既設注文は通常どおり継続。' if spec['gated'] else '返済後5分の休止が終われば通常どおり次の新規を準備。')


def all_results(candidates: list[dict], preview: bool) -> None:
    """機能: 全192条件の金額・返済枚数を週とセッション別に表示する。

    引数: candidates (list[dict])、preview (bool)。返り値: なし (None)。
    """
    body = ['<p><a href="' + TITLE + '.html">比較の結論</a></p><h1>全192条件の損益</h1>',
        '<p>TOPIXミニ／NKマイクロ換算。金額は円、枚数は延べ返済枚数。勝ち枚数−負け枚数は数量の差で、収支額ではありません。</p>',
        '<div class="filters"><label>入口<select id="signal-filter"><option value="">全入口</option>' + ''.join('<option' + (' selected' if h == 'H019' else '') + '>' + h + '</option>' for h in runner.design.SIGNAL_IDS) + '</select></label>',
        '<label>比較<select id="role-filter"><option value="">全条件</option><option value="primary" selected>主48条件</option><option value="diagnostic">診断144条件</option></select></label><span id="visible-count"></span></div>']
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示です。</strong></p>')
    headers = ['区間', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '同値枚数', '勝ち−負け枚数']
    for item in candidates:
        spec, identifier = item['spec'], item['id']
        opened = ' open' if identifier == MAIN_IDS[2] else ''
        body.append(f'<details class="method" data-signal="{spec["signal_id"]}" data-role="{spec["role"]}" id="{identifier}"{opened}><summary>{identifier}：{label(spec)}</summary><p>{description(spec)}</p>')
        raw = runner.read(HERE / 'sessions' / (identifier + '.json.gz'))
        for symbol in SYMBOLS:
            part = [r for r in raw if r['symbol'] == symbol]
            rows = [style.money_row('全13', item['all_symbols'][symbol]), style.money_row('共通後半7', item['symbols'][symbol])]
            for week_label, predicate in (('9/21開始週', lambda s: s < '2026-09-28'), ('9/28開始週・途中', lambda s: s >= '2026-09-28')):
                rows.append(style.money_row(week_label, style.totals([r for r in part if predicate(r['session'])])))
            rows += [style.money_row(r['session'], r) for r in sorted(part, key=lambda r: r['session'])]
            body.append('<h3>' + symbol + '</h3>' + table(headers, rows, f'data-id="{identifier}" data-symbol="{symbol}"'))
        body.append('</details>')
    script = '''/**
 * 入口と主条件・診断の表示を絞る。
 * @param {Event|undefined} event - 表示選択の操作。
 * @returns {undefined} 返り値なし。売買や計算条件は変更しない。
 */
function filter(event){let n=0;document.querySelectorAll('.method').forEach(e=>{e.hidden=['signal','role'].some(k=>{const v=document.getElementById(k+'-filter').value;return v&&v!==e.dataset[k]});if(!e.hidden)n++});document.getElementById('visible-count').textContent=n+'条件を表示'}document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filter));filter();'''
    (OUT / '全条件損益.html').write_text(page('全192条件の損益', body, script), encoding='utf-8')


def primary_table(items: list[dict], period: str) -> str:
    """機能: 主要3方式の金額・枚数・リスクを同じ区間で比較する。

    引数: items (list[dict])、period (str)。返り値: HTML表 (str)。
    """
    rows = []
    for symbol in SYMBOLS:
        for item in items:
            r = item[period][symbol]
            rows.append([symbol, label(item['spec']), yen(r['gross_profit_yen']), yen(-r['gross_loss_yen']),
                yen(r['net_yen']), number(r['drawdown_yen'], 0), number(r['money_ratio']),
                number(r['average_unit_payoff']), f"{r['profit_units']}/{r['loss_units']}/{r['zero_units']}"])
    return table(['銘柄', '方式', '利益 円', '損失 円', '収支 円', '最大下落 円', '利益/損失', '1枚平均利益/平均損失', '勝/負/同値枚'], rows, f'id="main-{period}"')


def update_index() -> None:
    """機能: 過去作業を保持し最新の00029へのリンクを追加する。

    引数: なし。返り値: なし (None)。
    """
    path = OUT.parent / 'index.html'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'<!--00029開始-->.*?<!--00029終了-->', '', source, flags=re.S)
    source = source.replace('task latest', 'task').replace(' <span class="badge">最新</span>', '')
    source = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は00029：仮想建玉で再エントリーを制御し、退出と入り直しを分けて比較。</p>', source, count=1)
    block = f'<!--00029開始--><article class="task latest"><div class="number">作業00029 <span class="badge">最新</span></div><h2>{TITLE}</h2><p>48主条件と144診断。元の固定幅、更新幅、更新幅＋再新規制御を比較。</p><a class="button" href="{NAME}/{TITLE}.html">比較の結論 →</a><p><a href="{NAME}/全条件損益.html">全192条件の損益</a> ／ <a href="{NAME}/README.md">資料案内</a></p></article><!--00029終了-->'
    path.write_text(source.replace('</header>', '</header>' + block, 1), encoding='utf-8')
    path = OUT.parent / 'README.md'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00029の[{TITLE}]({NAME}/{TITLE}.html)。**', source, count=1)
    source = re.sub(r'^\| `00029_.*\n', '', source, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    source = source.replace(anchor, anchor + f'\n| `{NAME}`（最新） | 仮想建玉の新規制御192条件 | [第10反復]({NAME}/{TITLE}.html) | [資料案内]({NAME}/README.md) |', 1)
    path.write_text(source, encoding='utf-8')


def main() -> None:
    """機能: 独立監査の完了後に正式な比較と全損益を出力する。

    引数: --preview (bool) は暫定表示専用。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    preview = parser.parse_args().preview
    OUT.mkdir(exist_ok=True)
    if not preview:
        guard = runner.read(HERE / '完備監査.json')
        assert guard['検証完了'] is True and guard['全条件数'] == 192 and guard['全入力数'] == 4992
        assert guard['全指定波数'] == 1536 and guard['全図示数'] == 78
        assert guard['ガード実装SHA256'] == runner.digest(HERE / 'completion_guard.py')
        assert guard['ガード固定SHA256'] == runner.digest(HERE / 'completion_guard_fixed.json')
        for name, expected in guard['参照資料SHA256'].items():
            path = Path(name)
            assert runner.digest(path if path.is_absolute() else ROOT / path) == expected
    candidates = runner.read(HERE / '全条件の期間集計.json.gz')
    by_id = {r['id']: r for r in candidates}
    items = [by_id[i] for i in MAIN_IDS]
    verdict = runner.read(HERE / '報告用結論.json')
    body = ['<p><a href="../index.html">作業一覧</a></p><h1>' + TITLE + '</h1>',
        '<p class="lead"><strong>' + escape(verdict['見出し']) + '</strong></p><p>' + escape(verdict['説明']) + '</p>',
        '<p class="muted">TOPIXミニ5枚／NKマイクロ10枚、片方向上限10／20枚。費用0・指定価格約定・全玉場内返済。13セッションは全て既知データです。</p>',
        '<p><a class="button" href="全条件損益.html">各週・各セッションの利益／損失／枚数</a><a class="button" href="５分足と売買.html">５分足と売買位置</a></p>',
        '<h2>H019の全13セッション</h2>', primary_table(items, 'all_symbols'),
        '<p class="muted">最大下落は含み損益込み。1枚平均利益/平均損失＝（利益額÷利益枚数）÷（損失額÷損失枚数）。</p>',
        '<details><summary>共通後半7セッションでも比較</summary>' + primary_table(items, 'symbols') + '</details>',
        '<details><summary>今回の手法を短く説明</summary><p>固定ATR方式を仮想運転し続けます。仮想側が新しい注文を準備した瞬間だけ、実側にも新規参加を許可します。実玉は最新の公開済みATRに応じて退出し、その後は次の仮想側の準備まで待ちます。AtがA0を超えると固定幅より退出が遅くなる場合もあります。</p><p>仮想側が途中で利益を伸ばし続けている場合、実側は入り直せません。実側がまだ保有中／返済後5分の休止中なら、その機会は見送り、後から追い付きません。</p><p>入口H019は公開済み1分足EMA15/60、他銘柄60秒前の同方向、自銘柄の気配中間値30秒変化を確認し、0.25ATRの反発／反落追跡で新規。初期損失予算は初回枚数×1A0、2A0で整数半分利確、1.5A0から残玉を3A0または3Atで追跡。最長360分、場末全返済。A0は新規準備時の値です。</p><p>ATRは確定5分足のTRをα=1/12で指数平滑（3本から計算）し、足開始＋360秒で利用。初期予算・利確・追跡開始条件はA0のまま、追跡線は緩めません。</p></details>',
        '<details><summary>入り直しの抑制と利益返却</summary><p>' + escape(verdict['新規制御の説明']) + '</p>']
    rows = []
    for symbol in SYMBOLS:
        for item in items:
            r = item['all_symbols'][symbol]
            g, loss = r['gate'], r['retracement']['all']
            rows.append([symbol, label(item['spec']), g['actual_opening_orders'], g['shadow_opening_orders'],
                g['skipped_holding'], g['skipped_cooldown'], number(loss['mean_yen'], 0),
                number(loss['mean_r']), number(loss['sum_yen'], 0), str(item['wave_passes']) + '/8'])
    body += [table(['銘柄', '方式', '実新規', '仮想新規', '保有中の見送り準備', '休止中の見送り準備', 'ピーク悪化平均 円', '同 R', '同 合計 円', '指定波'], rows),
        '<p class="muted">準備と約定の件数は異なります。通常新規の見送り欄は仮に影の準備と対応させた値です。ピーク悪化は各組の実現＋含み最高値から全返済までの低下で、利益未経験の損失組も含みます。1R＝初回枚数×A0×円倍率。指定波は正方向ネット保有合計20分の目安。</p><p>' + escape(verdict['銘柄差の説明']) + '</p><p><a href="../../work/wave_v34/共通新規の返済分解.md">新規と返済の対応分解</a>。結果後の会計分解であり、未知相場で同じ差が出ることを証明しません。</p></details>',
        '<details><summary>12種類の入口でも同じ効果か</summary><p>更新幅＋制御と、更新幅＋通常新規の対応比較です。結果の良い入口への候補差替えはしていません。</p>']
    rows = []
    for period, period_label in (('all_symbols', '全13'), ('symbols', '後7')):
        for symbol in SYMBOLS:
            differences = np.array([[by_id[h + '__AT__SHADOW__V000'][period][symbol][f] - by_id[h + '__AT__NORMAL__V000'][period][symbol][f]
                                     for f in ('net_yen', 'drawdown_yen')] for h in runner.design.SIGNAL_IDS])
            counts = []
            for col, sign in ((0, 1), (1, -1)):
                v = differences[:, col] * sign
                counts.append(f'{sum(v > 1e-6)}/{sum(v < -1e-6)}/{sum(abs(v) <= 1e-6)}')
            rows.append([period_label, symbol, yen(float(np.median(differences[:, 0]))), counts[0],
                         number(float(np.median(differences[:, 1])), 0), counts[1]])
    body += [table(['区間', '銘柄', '収支差中央値 円', '収支 改善/悪化/同値', '最大下落差中央値 円', '下落 改善/悪化/同値'], rows),
        '<p>' + escape(verdict['頑健性の説明']) + '</p></details>',
        '<details><summary>反証と判定</summary><p>' + escape(verdict['反証の説明']) + '</p><p>通常96条件は前回と一致し、固定幅の制御48条件は通常固定幅と一致することを要求。未来の価格・方向を変更し、仮想側から再生成して過去の注文が変わらないことを検査します。板更新の同値時刻は原本行順で扱い、実際の受信遅延を復元したという意味ではありません。</p><p>今回192条件の内訳は、旧96の再現、恒等対照48、新しい制御48（主12／診断36）。再確認を含む10反復で延べ109,608条件であり、独立した109,608の仮説や未知相場を意味しません。既知データへの適応と選択の偏りは残り、将来収益を確定したものではありません。</p></details>',
        '<p>' + escape(verdict['次の検証']) + ' <a href="../../work/wave_v34/文献と次の退出仮説.md">文献と反証案</a></p>',
        '<p><a href="README.md">再現手順・監査資料</a></p>']
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示です。</strong></p>')
    (OUT / (TITLE + '.html')).write_text(page(TITLE, body), encoding='utf-8')
    all_results(candidates, preview)
    (OUT / 'README.md').write_text(f'''# {TITLE}

最初に [{TITLE}.html]({TITLE}.html) を開いてください。

読む順序:
1. [比較の結論]({TITLE}.html) — H019の3方式。
2. [全条件損益](全条件損益.html) — 全192条件、銘柄別の週・セッション損益と決済枚数。
3. [５分足と売買](５分足と売買.html) — 3方式×26入力の78図。
4. [事前設計](../../work/wave_v34/scheduler_design.md) — 何を変え、何を採用基準にしたか。
5. [入力監査](../../work/wave_v34/input_audit.md)・[注文器](../../work/wave_v34/scheduler_engine_audit.md)・[全数会計](../../work/wave_v34/accounting_audit.md)・[完備監査](../../work/wave_v34/完備監査.json)。
6. [文献と次の退出仮説](../../work/wave_v34/文献と次の退出仮説.md) — 今回の成果と次の未検証仮説を区別。

再現: `python -X utf8 work/wave_v34/run_verified.py --workers 8`

原本フォルダを変更せず、既知13セッションだけを使用。現在API・保存ライブの再利用なし。
費用0、指定価格約定。診断として全観測価格約定も別条件で報告します。
''', encoding='utf-8')
    if not preview:
        update_index()
    print('比較・全192条件・資料案内を出力。' + ('暫定。' if preview else '正式版。'))


if __name__ == '__main__':
    main()
