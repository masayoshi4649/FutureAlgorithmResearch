"""条件付きの利益保護を、短い結論と全週・全セッションの損益に分けて報告する。"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import re

import conditional_runner as runner
import report_scheduler as old_report

HERE, ROOT = runner.HERE, runner.ROOT
TITLE = '板と両市場による条件付き追跡短縮'
NAME = '00030_' + TITLE
OUT = ROOT / 'アルゴリズム調査' / NAME
style = old_report.style
table, page, yen, number = style.table, style.page, style.yen, style.number


def mode_name(mode: str) -> str:
    """機能: 返済方式を短い日本語にする。

    引数: mode (str)。返り値: 表示名 (str)。
    """
    return next(m['name'] for m in runner.design.exit_modes() if m['id'] == mode)


def description(spec: dict) -> str:
    """機能: 手法ごとの変更点を日本語一段落で説明する。

    引数: spec (dict)。返り値: 説明 (str)。
    """
    mode = spec['exit_mode_id']
    base = '新規準備時ATRの3倍で追跡。' if mode == 'A0' else (
        '初期ATRと保有中ATRの小さい方の3倍で常に追跡。' if mode == 'MIN' else
        mode_name(mode) + '。保有方向と逆の動きを確認した行だけ、初期ATRと保有中ATRの小さい方の3倍を保護線候補に追加。')
    variant = next(v['name'] for v in runner.design.variants() if v['id'] == spec['variant_id'])
    return f"入口{spec['signal_id']}。{base}固定幅の線も更新し、確保した線は緩めません。{variant}。"


def money_tables(rows: list[dict], identifier: str) -> str:
    """機能: 両銘柄を分け、全期間・後半・各週・全セッションの損益を表示する。

    引数: rows (list[dict])、identifier (str)。返り値: HTML (str)。
    """
    body = []
    for symbol in runner.SYMBOLS:
        part = sorted([r for r in rows if r['symbol'] == symbol], key=lambda r: r['session'])
        assert len(part) == 13
        output = [style.money_row('全13', style.totals(part)),
            style.money_row('共通後半7', style.totals([r for r in part if r['session'] in runner.design.SESSIONS[6:]]))]
        output += [style.money_row(label, style.totals([r for r in part if predicate(r['session'])]))
            for label, predicate in (('9/21開始週', lambda s: s < '2026-09-28'),
                                     ('9/28開始週・途中', lambda s: s >= '2026-09-28'))]
        output += [style.money_row(r['session'], r) for r in part]
        body.append('<h3>' + symbol + '</h3>' + table(
            ['区間', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '同値枚数', '勝ち−負け枚数'],
            output, f'data-id="{identifier}" data-symbol="{symbol}"'))
    return ''.join(body)


def all_results(candidates: list[dict], policy: dict, chosen: str, preview: bool) -> None:
    """機能: 自動選択の運用と研究用840条件を分けて全損益を表示する。

    引数: candidates (list[dict])、policy (dict)、chosen (str)、preview (bool)。返り値: なし (None)。
    """
    body = [f'<p><a href="{TITLE}.html">結論へ</a></p><h1>全条件の損益</h1>',
        '<p>金額は円、数量は延べ返済枚数。勝ち枚数−負け枚数は数量差であり、損益額ではありません。</p>',
        '<details open id="policy"><summary>自動選択の運用：初期6はA0、後7は' + chosen + '</summary>',
        money_tables(policy['セッション'], 'POLICY'), '</details>',
        '<h2>研究用の固定条件840本</h2><p>下表は各方式を全13に固定適用した診断です。選択後の方式を初期6へ遡った運用成績ではありません。</p>',
        '<div class="filters"><label>入口<select id="signal-filter"><option value="">全入口</option>' + ''.join(
            '<option' + (' selected' if h == 'H019' else '') + '>' + h + '</option>' for h in runner.design.SIGNAL_IDS) + '</select></label>',
        '<label>条件<select id="role-filter"><option value="">全条件</option><option value="primary" selected>主168条件</option><option value="diagnostic">診断672条件</option></select></label><span id="visible-count"></span></div>']
    for item in candidates:
        spec, identifier = item['spec'], item['id']
        body.append(f'<details class="method" data-signal="{spec["signal_id"]}" data-role="{spec["role"]}" id="{identifier}"><summary>{identifier}：{escape(mode_name(spec["exit_mode_id"]))}</summary><p>{escape(description(spec))}</p>')
        body.append(money_tables(runner.read(HERE / 'sessions' / (identifier + '.json.gz')), identifier))
        body.append('</details>')
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示。</strong></p>')
    script = '''/**
 * 入口と主条件・診断で表示のみを絞る。
 * @param {Event|undefined} event - 選択操作。
 * @returns {undefined} 返り値なし。売買条件を変更しない。
 */
function filter(event){let n=0;document.querySelectorAll('.method').forEach(e=>{e.hidden=['signal','role'].some(k=>{const v=document.getElementById(k+'-filter').value;return v&&v!==e.dataset[k]});if(!e.hidden)n++});document.getElementById('visible-count').textContent=n+'条件を表示'}document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filter));filter();'''
    (OUT / '全条件損益.html').write_text(page('全条件の損益', body, script), encoding='utf-8')


def main_table(items: list[tuple[str, dict]], period: str) -> str:
    """機能: 方式別の金額・返済枚数・最大下落を同じ期間で比較する。

    引数: items (list[tuple[str,dict]])、period (str)。返り値: HTML表 (str)。
    """
    rows = []
    for symbol in runner.SYMBOLS:
        for label, values in items:
            r = values[period][symbol]
            rows.append([symbol, escape(label), yen(r['gross_profit_yen']), yen(-r['gross_loss_yen']),
                yen(r['net_yen']), number(r['drawdown_yen'], 0), number(r['money_ratio']),
                number(r['average_unit_payoff']), f"{r['profit_units']}/{r['loss_units']}/{r['zero_units']}"])
    return table(['銘柄', '方式', '利益 円', '損失 円', '収支 円', '最大下落 円', '利益/損失',
        '1枚平均利益/平均損失', '勝/負/同値枚'], rows, f'id="main-{period}"')


def update_index() -> None:
    """機能: 過去作業を保持し、00030の主資料へ最新リンクを追加する。

    引数: なし。返り値: なし (None)。
    """
    path = OUT.parent / 'index.html'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'<!--00030開始-->.*?<!--00030終了-->', '', source, flags=re.S)
    source = source.replace('task latest', 'task').replace(' <span class="badge">最新</span>', '')
    source = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は00030：板と両市場の悪化による追跡短縮を、同じエントリーで比較。</p>', source, count=1)
    block = f'<!--00030開始--><article class="task latest"><div class="number">作業00030 <span class="badge">最新</span></div><h2>{TITLE}</h2><p>840条件。初期6で方式を選択し、後7へ固定。</p><a class="button" href="{NAME}/{TITLE}.html">比較の結論 →</a><p><a href="{NAME}/全条件損益.html">全条件の損益</a> ／ <a href="{NAME}/５分足と売買.html">売買図</a> ／ <a href="{NAME}/README.md">資料案内</a></p></article><!--00030終了-->'
    path.write_text(source.replace('</header>', '</header>' + block, 1), encoding='utf-8')
    path = OUT.parent / 'README.md'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00030の[{TITLE}]({NAME}/{TITLE}.html)。**', source, count=1)
    source = re.sub(r'^\| `00030_.*\n', '', source, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    source = source.replace(anchor, anchor + f'\n| `{NAME}`（最新） | 条件付き追跡短縮840条件 | [第11反復]({NAME}/{TITLE}.html) | [資料案内]({NAME}/README.md) |', 1)
    path.write_text(source, encoding='utf-8')


def main() -> None:
    """機能: 独立監査後に比較、全条件損益、資料案内を作る。

    引数: --preview (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    preview = parser.parse_args().preview
    if not preview:
        guard = runner.read(HERE / '完備監査.json')
        assert guard['検証完了'] is True and guard['全条件数'] == 840 and guard['全入力数'] == 21840
        assert guard['全指定波数'] == 6720 and guard['全図示数'] == 104
        for name, expected in guard['参照資料SHA256'].items():
            path = Path(name)
            assert runner.digest(path if path.is_absolute() else ROOT / path) == expected
    OUT.mkdir(exist_ok=True)
    candidates = runner.read(HERE / '全条件の期間集計.json.gz')
    index = {r['id']: r for r in candidates}
    verdict = runner.read(HERE / '独立判定.json')
    policy = verdict['H019運用policy']
    selection = verdict['選択']
    chosen = selection['selected_exit_mode_id']
    chosen_id = selection['selected_id']
    notes = runner.read(HERE / '報告用結論.json')
    supplement = runner.read(HERE / '補助乱数診断.json')
    findings = runner.read(HERE / '同じ新規の退出差.json')
    items = [('固定幅 A0', index['H019__A0__V000']), ('常時短縮 MIN', index['H019__MIN__V000']),
        ('自動選択 ' + chosen, policy['全13と後7'])]
    body = [f'<p><a href="../index.html">作業一覧</a></p><h1>{TITLE}</h1>',
        '<p class="lead"><strong>' + escape(notes['見出し']) + '</strong></p><p>' + escape(notes['説明']) + '</p>',
        '<p class="muted">TOPIXミニ5枚／NKマイクロ10枚。片方向上限10／20枚、費用0、指定価格約定、全玉を場内返済。13セッションは全て既知データ。</p>',
        '<p><a class="button" href="全条件損益.html">週・セッションの利益／損失／枚数</a><a class="button" href="５分足と売買.html">５分足と売買位置</a></p>',
        '<h2>全13セッション</h2>', main_table(items, 'all_symbols'),
        '<p class="muted">自動選択は初期6をA0で運用し、後7だけ選択方式へ切替。最大下落は含み損益込み。1枚平均比は利益額÷勝ち枚数と損失額÷負け枚数の比。</p>',
        '<details><summary>選択後の7セッション</summary>', main_table(items, 'symbols'), '</details>',
        '<details><summary>売買ルールを短く</summary><p>公開済み1分足のEMA15/60で中期方向を判定し、他銘柄の60秒前の方向と自銘柄の直近30秒の気配変化が合うと注文を準備。0.25ATRの反発／反落で新規。</p>',
        '<p>初期損失予算は初回枚数×1ATR、2ATR順行で整数半分を利確。1.5ATR順行から残玉を3ATRで追跡します。A0は新規準備時、Atは保有中の公開済みATR。条件付き方式は逆向きの証拠がある時だけ3×min(A0,At)の線も追加し、確保した線は緩めません。</p>',
        '<p>仮想の固定A0方式が新しく注文を準備する行だけ実側も参加するため、全方式のエントリーは一致します。最長360分、返済後5分休止、場末全返済。確定5分足のTRをα=1/12で平滑し、足開始360秒後からATRを使用します。</p></details>',
        '<details><summary>なぜこの方式を選んだか</summary><p>初期6だけを使い、12入口の固定A0との差を比較。両銘柄とも収支Rの中央値が非負、最大下落差の中央値が非正の方式から、弱い銘柄の改善が最大の方式を選びました。</p>']
    scores = []
    for row in selection['全14方式']:
        scores.append([row['exit_mode_id'], escape(mode_name(row['exit_mode_id'])), '適格' if row['適格'] else '対象外',
            number(row['銘柄別']['TOPIX']['中央値純益差R']), number(row['銘柄別']['TOPIX']['中央値DD差円'], 0),
            number(row['銘柄別']['NK225']['中央値純益差R']), number(row['銘柄別']['NK225']['中央値DD差円'], 0)])
    body += [table(['方式', '条件', '初期6の判定', 'TOP収支差R', 'TOP下落差 円', 'NK収支差R', 'NK下落差 円'], scores),
        '<p>固定A0も選択肢に残します。後7の結果を見て方式・入口・乱数を差し替えません。</p></details>',
        '<details><summary>板確認に追加の価値があったか</summary><p>' + escape(notes['機序の説明']) + '</p>']
    controls = []
    for symbol in runner.SYMBOLS:
        for mode in ('A0', 'MIN', chosen):
            value = index[f'H019__{mode}__V000']['all_symbols'][symbol]['control']
            controls.append([symbol, mode, number(value['adverse_seconds'] / 60, 1),
                value['additional_advance_events'], value['earlier_exits'], value['changed_repayments'],
                yen(value['exit_difference_yen'])])
    body += [table(['銘柄', '固定条件診断', '保有逆方向 分', '追加の線更新', '早く全返済した組', '返済台帳差の組', 'A0との収支差 円'], controls),
        '<p class="muted">ここだけは選択方式を全13へ固定適用した診断。返済台帳差には返済理由だけの違いも含みます。逆方向の発生・幅が縮むこと・実注文が変わることは別です。</p></details>',
        '<details><summary>条件を試した数と、実際に作動した数</summary><p>主168条件で異なる返済台帳は' + str(findings['主条件で異なる返済台帳数']) +
        '種類、診断込み840条件では' + str(findings['全条件で異なる返済台帳数']) + '種類でした。補充後の反転2条件は、この定義では一度も発火していません。補充を読む方法一般が無効とは判定できません。</p>',
        table(['条件', '機序', '原本の非中立行数', 'TOP返済台帳差 組', 'NK返済台帳差 組'],
            [[r['方式'], escape(r['名称']), r['両銘柄全原本の非中立行数'],
              r['銘柄別H019全13']['TOPIX']['changed_repayments'], r['銘柄別H019全13']['NK225']['changed_repayments']]
             for r in findings['機序別作動量']], 'id="mechanism-activity"'), '</details>',
        '<details><summary>敵対的な検査結果</summary><p>' + escape(notes['反証の説明']) + '</p><p>' + escape(notes['感度の説明']) + '</p>',
        table(['銘柄', '入口時間尺度', '固定A0 後7収支 円', '選択方式 後7収支 円', '返済変更による差 円'],
            [[symbol, scale, yen(index[f'H019__A0__{variant}']['symbols'][symbol]['net_yen']),
              yen(index[f'H019__{chosen}__{variant}']['symbols'][symbol]['net_yen']),
              yen(index[f'H019__{chosen}__{variant}']['symbols'][symbol]['net_yen'] - index[f'H019__A0__{variant}']['symbols'][symbol]['net_yen'])]
             for symbol in runner.SYMBOLS for variant, scale in (('C080', '0.8倍'), ('C120', '1.2倍'))], 'id="clock-comparison"'),
        '<p>主168＋診断672＝840条件。未来改変・注文会計・全新規一致・全退出が影以前・指定波を独立に照合。入口の時計0.8/1.2倍、観測価格約定、方向乱数も比較しました。</p>',
        '<p>指定4波は全て初期6内。自動運用A0が保った波を、選択した返済方式の証拠に数えません。悪化条件自体の窓±20%と新方式の追加遅延は今回未検査です。</p>',
        '<p>全13は既知で、後7も真の未見ではありません。主格子の反復は再確認を含め延べ110,448条件。独立した仮説数ではありません。今回の補助乱数・反転' + str(supplement['条件数']) + '条件は別計数です。</p></details>',
        '<details><summary>選択用データの偏り</summary><p>初期6は9/21〜9/23の祝日開始セッションだけで、通常営業日のデイを含みません。後7とは板の観測頻度にも差がありました。暦が成績差の原因と断定せず、売買条件・選択を変えていません。</p><p><a href="https://www.jpx.co.jp/news/2040/20260918-01.html">JPXの祝日取引通知</a> ／ <a href="../../work/wave_v35/暦と観測量の点検.md">区間別の測定</a></p></details>',
        '<p>' + escape(notes['次の検証']) + '</p><p><a href="README.md">再現手順・監査資料</a></p>']
    if preview:
        body.insert(1, '<p><strong>独立監査中の暫定表示。</strong></p>')
    (OUT / (TITLE + '.html')).write_text(page(TITLE, body), encoding='utf-8')
    all_results(candidates, policy, chosen, preview)
    (OUT / 'README.md').write_text(f'''# {TITLE}

最初に [{TITLE}.html]({TITLE}.html) を開いてください。

読む順序:
1. [比較の結論]({TITLE}.html) — 固定幅・常時短縮・自動選択。
2. [全条件損益](全条件損益.html) — 自動運用と固定840条件の週・セッション別金額と返済枚数。
3. [５分足と売買](５分足と売買.html) — 4表示枠×26入力の104表示。重複を除く再生数は別計数。
4. [事前設計](../../work/wave_v35/conditional_design.md)・[選択固定](../../work/wave_v35/選択固定.json)。
5. [入力監査](../../work/wave_v35/input_audit.md)・[注文器監査](../../work/wave_v35/conditional_engine_audit.md)・[全数会計](../../work/wave_v35/accounting_audit.md)・[完備監査](../../work/wave_v35/完備監査.json)。
6. [独立判定](../../work/wave_v35/独立判定.json)・[補助乱数診断](../../work/wave_v35/補助乱数診断.json)。
7. [結果前の仮説批判](../../work/wave_v35/結果前の仮説批判.md)・[文献と探索範囲の見直し](../../work/wave_v35/文献と探索範囲の見直し.md)。
8. [追跡始動前の損失](../../work/wave_v35/追跡始動前の損失分解.md)・[部分調整の次仮説](../../work/wave_v35/部分調整の次仮説レビュー.md)・[暦と観測量](../../work/wave_v35/暦と観測量の点検.md)。
9. [未計測だった出来高と気配維持](../../work/wave_v35/見えない補充代理の可用性レビュー.md)・[次探索の独立批判](../../work/wave_v35/次探索の独立批判.md)。

保存処理の修正は [修正記録](../../work/wave_v35/保存形式修正の記録.json) と [初期6の840件一致](../../work/wave_v35/保存形式修正の再検算.json) に記録しました。売買条件は変更していません。会計処理の高速化は [全件の改訂証跡](../../work/wave_v35/accounting_revision.json) にまとめています。

再現: `python -X utf8 work/wave_v35/run_verified.py --workers 8`

初期6の全840再生→方式選択を固定→後7の全840再生→必要な補助診断。
原本を変更せず、既知13だけを使用。現在API・保存ライブ不使用。
金額はラージ価格をTOPIXミニ／NK225マイクロの倍率へ換算。小型板の実約定再現ではありません。
''', encoding='utf-8')
    if not preview:
        update_index()
    print('比較・全条件損益・資料案内を出力。' + ('暫定。' if preview else '正式版。'))


if __name__ == '__main__':
    main()
