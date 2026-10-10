"""機械的な手法選択の結果を、短い結論と全条件の損益表で報告する。"""

from __future__ import annotations

import gzip
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '00027_順張りと反転の機械的選択'
TITLE = '順張りと反転の機械的選択'
OUT = ROOT / 'アルゴリズム調査' / NAME
SYMBOLS = ('TOPIX', 'NK225')


def read(path: Path, default: object = None) -> object:
    """機能: この調査の保存結果だけを読み込む。

    引数: path (Path)、default (object)。返り値: JSON内容 (object)。
    """
    assert 'live' not in path.parts
    if not path.exists():
        return default
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def money(value: float) -> str:
    """機能: 円額の正負を暗色背景で区別する。

    引数: value (float)。返り値: 表示HTML (str)。
    """
    return f'<span class="{"good" if value > 0 else "bad" if value < 0 else "muted"}">{value:+,.0f}</span>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    """機能: 横に長い表をスクロール可能な枠へ入れる。

    引数: headers (list[str])、rows (list[list[str]])。返り値: HTML (str)。
    """
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + h + '</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + str(v) + '</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def totals(rows: list[dict]) -> dict:
    """機能: 金額と決済枚数を同じ銘柄の中で合算する。

    引数: rows (list[dict])。返り値: 合計 (dict)。
    """
    return {key: sum(row[key] for row in rows) for key in ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')}


def result_row(label: str, row: dict) -> list:
    """機能: 利益・損失・収支と勝ち負け枚数を一行へ整形する。

    引数: label (str)、row (dict)。返り値: 表の一行 (list)。
    """
    return [label, money(row['gross_profit_yen']), money(-row['gross_loss_yen']), money(row['net_yen']),
            row['profit_units'], row['loss_units'], row['zero_units'], row['profit_units'] - row['loss_units']]


def description(spec: dict) -> str:
    """機能: 各方式が何を見て入口を選ぶかを短く説明する。

    引数: spec (dict)。返り値: 日本語説明 (str)。
    """
    if spec['selector_kind'] == 'fixed':
        return '中期方向と両市場の方向一致を確認するTだけで売買。' if spec['fixed_request'] == 1 else '両市場の短期価格反転を確認するRだけで売買。'
    if spec['random_seed'] is not None:
        return '方向予測はT/Rのまま、どちらを使うかだけを固定乱数で選ぶ反証。良い乱数は採用しません。'
    if spec['source_override']:
        return 'Aの切替・取消判断は動かしますが、売買方向の入口源は常に' + ('T' if spec['source_override'] == 1 else 'R') + '。待機と再準備だけの効果を見る対照です。'
    if spec['selector_kind'] == 'A':
        text = f"過去{spec['er_window']}本の価格が滑らかに進む時はT、往復が多い時はR。両市場の一致を30分ごとに2回確認して切替を要求します。"
    else:
        text = f"直前{spec['history_window']}完了セッションの成績を両銘柄で比較。別方式のスコアが現在より{spec['score_gap']:.2f}超高い時だけ、次セッションの入口を切り替えます。"
    if spec['delay_seconds']:
        text += f" 入口と要求を{spec['delay_seconds']}秒遅延した反証です。"
    if spec['fill_model'] == 'observed':
        text += ' 全約定を条件成立時の観測価格へ変えた反証です。'
    return text


def update_index(done: bool) -> None:
    """機能: 作業一覧の最新リンクを今回の成果へ更新する。

    引数: done (bool)。返り値: なし (None)。過去フォルダは編集しない。
    """
    parent = OUT.parent
    path = parent / 'index.html'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'<!--00027開始-->.*?<!--00027終了-->', '', source, flags=re.S)
    source = source.replace('task latest', 'task').replace(' <span class="badge">最新</span>', '')
    label = '選択器148条件の検証結果' if done else '機械的選択器を実装・検証中'
    source = re.sub(r'<p class="lead">.*?</p>', f'<p class="lead">最新は00027（{label}）。現在データの再取得は行っていません。</p>', source, count=1)
    block = f'<!--00027開始--><article class="task latest"><div class="number">作業00027 <span class="badge">最新</span></div><h2>{TITLE}</h2><p>固定T/R・状態選択・過去成績選択と、取消効果の対照を同じ枚数・出口で比較。</p><a class="button" href="{NAME}/{TITLE}.html">{label} →</a><p><a href="{NAME}/README.md">資料案内</a></p></article><!--00027終了-->'
    path.write_text(source.replace('</header>', '</header>' + block, 1), encoding='utf-8')
    path = parent / 'README.md'
    source = path.read_text(encoding='utf-8')
    source = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00027の[{TITLE}]({NAME}/{TITLE}.html)（{label}）。**', source, count=1)
    source = re.sub(r'^\| `00027_.*\n', '', source, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    source = source.replace(anchor, anchor + f'\n| `{NAME}`（最新） | T/R選択と注文取消148比較 | [第8反復]({NAME}/{TITLE}.html) | [資料案内]({NAME}/README.md) |', 1)
    path.write_text(source, encoding='utf-8')


def main() -> None:
    """機能: 主6方式の要点と、全148の週・セッション別損益を出力する。

    引数: なし。返り値: なし (None)。監査完了前は結論を確定しない。
    """
    OUT.mkdir(exist_ok=True)
    fixed = read(HERE / '探索条件の固定.json', {})
    candidates = read(HERE / '全条件の期間集計.json.gz', [])
    judged = read(HERE / '選択の判定.json', {})
    waves = read(HERE / 'episode_audit.json', {})
    wave_by_id = {}
    for row in waves.get('結果', []):
        wave_by_id.setdefault(row['method'], []).append(row)
    guard = read(HERE / '検証完備の監査.json', {})
    done = guard.get('検証完了') is True
    if done:
        assert guard['全条件数'] == 148 and guard['全入力数'] == 3848
        assert guard['全指定波数'] == 1184 and guard['全図示数'] == 156
        assert guard['ガード実装SHA256'] == sha256((HERE / 'completion_guard.py').read_bytes()).hexdigest()
        assert guard['ガード固定SHA256'] == sha256((HERE / 'completion_guard_fixed.json').read_bytes()).hexdigest()
        for name, expected in guard['参照資料SHA256'].items():
            assert sha256(Path(name).read_bytes()).hexdigest() == expected
    body = [f'<p><a href="../index.html">作業一覧</a></p><h1>{TITLE}</h1>']
    body.append('<p class="lead">手法を切り替えることで、固定運用より安定するか。</p>')
    if not done:
        body.append(f'<p class="status">実装・検証中。主再生 {len(candidates)}/148条件。独立監査完了前の数値は暫定です。</p>')
    else:
        body.append('<p><strong>今回の切替で、固定順張りH019を入れ替える根拠は得られませんでした。</strong>Aは最大下落を減らしましたが、NKの収支は122,000円→52,000円へ減少。Bは反転方式を一度も選ばず、固定順張りと同じ結果です。固定H019の黒字が崩れたという意味ではありません。</p>')
    body.append('<p><strong>Tは中期方向への順張り、Rは短期価格反転。</strong>入口だけを選び、枚数と返済方法は共通にしました。Aは両市場の値動き、Bは過去の完了セッションの成績から選択します。</p>')
    body.append('<p class="muted">TOPIXミニ5枚／NKマイクロ10枚、片方向上限10／20枚。費用0・指定価格約定・全玉場内返済。主比較は共通の後半7セッション。全13は既知データの再現で、未知検証ではありません。</p>')
    if (OUT / '５分足と売買.html').exists():
        body.append('<p><a class="button" href="５分足と売買.html">主6方式の５分足・売買・選択</a></p>')
    body.append('<details><summary>共通の入口注文・返済と、切替の扱い</summary><p>0.25ATRの反発／反落追跡で新規。初期1ATR相当の損切り、2ATRで整数半分を利確。1.5ATR順行後は3ATR幅で追跡し、最長360分。全返済後は5分休止します。</p><p>保有中は元の玉と出口を維持します。フラット時に手法を切り替え、未約定注文があれば取消確認後に準備し直します。切替で含み損・建値・休止時間をリセットしません。両市場へ同じ要求を出しても、実適用時刻は保有状態により異なります。</p></details>')
    body.append('<details><summary>TとRの入口条件</summary><p><strong>T（H019）</strong>：確定1分足のEMA15とEMA60の差が0.15ATR超、EMA60の3本変化も同方向に0.02ATR超なら主方向を設定し、両線の上下関係が逆になるまで維持します。相手銘柄の60秒前の主方向も一致し、自市場の最良売買気配の中間価格が30秒前より同方向へ0.05ATR超動いた時に入口を許します。</p><p><strong>R（価格P02）</strong>：両市場それぞれで、中間価格の60秒変化と30秒変化が逆符号になり、両市場の30秒方向が一致した時、その方向に入口を許します。符号の判定幅は0.03ATR。板数量やOFIで方向を決める方式ではありません。</p><p>入口の支持は最大120秒、未約定追跡は最長5分。足は確定後に公開遅延を加え、ATRは公開済み5分足12期間の平滑値を新規準備時に固定します。Rをレンジで選ぶ根拠は、今回検証した仮説です。</p></details>')
    if candidates:
        by_id = {row['id']: row for row in candidates}
        primary = [by_id[f'S{i:03d}'] for i in range(6)]
        for field, label in (('symbols', '共通の後半7セッション'), ('all_symbols', '全13セッションの再現')):
            if field == 'all_symbols':
                body.append('<details><summary>全13セッションの参考成績</summary>')
            body.append('<h2>' + label + '</h2>')
            rows = []
            for item in primary:
                for symbol in SYMBOLS:
                    s = item[field][symbol]
                    rows.append([item['id'], symbol, money(s['gross_profit_yen']), money(-s['gross_loss_yen']), money(s['net_yen']),
                                 f"{s['drawdown_yen']:,.0f}", f"{s['profit_units']}/{s['loss_units']}/{s['zero_units']}"])
            body.append(table(['方式', '銘柄', '利益 円', '損失 円', '収支 円', '最大下落 円', '勝/負/同値枚'], rows))
            if field == 'all_symbols':
                body.append('</details>')
        if waves:
            body.append('<details><summary>指定した4つの波への参加</summary><p>両銘柄の計8区間で、正方向に合計20分以上ネット保有できたかを確認。利益の有無とは別の目安です。対象の波はすべて初期6セッションにあり、後半7の評価実績へ混ぜません。</p>' + table(['方式', '20分目安の達成'], [[r['method'], f"{r['目安達成区間数']}/8"] for r in waves['方法別要約'] if '__' not in r['method']]) + '<p>Aは9/22ナイト深夜のTOPIX上昇区間で、買いネット保有0分・売り27.4分、区間時価損益−20,000円でした。短い窓の往復判定と両市場確認によってRを維持し、長い上昇へのT参加を遮りました。<a href="../../work/wave_v32/S002_W04_TOPIXの未参加理由.md">判断時刻と注文の追跡</a>。</p></details>')
        body.append('<details><summary>どの枝を使い、何が利益・損失を生んだか</summary>')
        rows = []
        for item in primary:
            for symbol in SYMBOLS:
                s = item['symbols'][symbol]['selection']
                rows.append([item['id'], symbol, s['branch_opening_orders']['T'], s['branch_opening_orders']['R'],
                             money(s['branch_net_yen']['T']), money(s['branch_net_yen']['R']),
                             s['within_session_applied_switches'], s['between_session_applied_switches'], s['event_counts']['取消要求']])
        body.append(table(['方式', '銘柄', 'T新規', 'R新規', 'T由来収支 円', 'R由来収支 円', '場内適用切替', '場初ID変化', '切替取消'], rows))
        body.append('<p>枝の損益は実際に新規注文を作った入口へ帰属します。場初ID変化には初期6→評価7番目の境界を含み、Aの毎場初Tへの初期化を予測成功と数えません。</p></details>')
        if judged:
            body.append('<details><summary>事前の目安・固定運用・乱数対照との比較</summary>')
            for row in judged['主判定']:
                problems = row['最低目安未達'] + row['選択の稼働不足']
                problems += [symbol + '：T比の収支75%・最大下落80%目標未達' for symbol in row['T比の工学目標未達銘柄']]
                problems += ['両市場の収支・最大下落で対照が同等以上：' + x for x in row['両市場で支配する対照']]
                problems += ['対照と収支・最大下落が同一：' + x for x in row['4値が同一の対照']]
                random = row['乱数対照']
                body.append('<h3>' + row['id'] + '</h3><p>' + ('固定した一次目安を充足。反証・未知データでの確認は別です。' if not problems else '／'.join(escape(x) for x in problems)) + f"</p><p>弱い銘柄側の収支÷最大下落で、この方式以上の乱数対照は{random['主以上の対照数']}/64。正式なp値ではなく、良いseedは採用しません。</p>")
            body.append('<p>収支75%・最大下落80%は「選択を追加する価値」の工学目標です。未達でも、黒字の固定手法まで無意味とは判断しません。</p></details>')
            body.append('<details><summary>窓・遅延・約定を変えた14反証も確認</summary><p>各反証を元のA/Bと同じ後半7セッションで再生しました。最良の変更へ採用設定を差し替えません。乱数128条件も、下の手法別表へ全件掲載しています。</p>')
            variations = [r for r in candidates if r['spec']['role'] == 'adversarial' and r['spec']['random_seed'] is None]
            body.append(table(['反証ID', '変更', 'TOP収支 円', 'TOP最大下落 円', 'NK収支 円', 'NK最大下落 円'],
                              [[r['id'], escape(r['spec']['name'].split('／')[-1]), money(r['symbols']['TOPIX']['net_yen']),
                                f"{r['symbols']['TOPIX']['drawdown_yen']:,.0f}", money(r['symbols']['NK225']['net_yen']),
                                f"{r['symbols']['NK225']['drawdown_yen']:,.0f}"] for r in variations]))
            body.append('<p>AのNKは最大1勝ち組を除くと−1,000円。黒字を確認できても、一勝への依存は残りました。Bの窓・切替差の近傍もTのままで、選択機能の有効性を確かめた結果にはなっていません。</p></details>')
            history = read(HERE / 'requests/S003.json.gz', [])
            decisions = [r for r in history if r.get('scores')]
            body.append('<details><summary>Bが切り替わらなかった理由</summary><p>下表は各セッション開始前の過去6区間だけのスコアです。7回ともRがTを下回っており、切替差0.25だけが原因ではありません。両銘柄で弱い方を評価するため、TOPIXだけの大きな利益で選択は決まりません。</p>' + table(['次に売買する区間', 'Tのスコア', 'Rのスコア', '選択'],
                        [[r['session'].replace('_Day', ' 昼').replace('_Night', ' 夜'), f"{r['scores']['T']:.3f}", f"{r['scores']['R']:.3f}", 'T' if r['request'] == 1 else 'R'] for r in decisions]) + '</details>')
        body.append('<h2>手法別の週・セッション損益</h2><p>勝ち・負けは決済枚数。枚数差は保有残ではありません。</p><div class="controls"><label>表示<select id="role-filter"><option value="primary">主6方式</option><option value="adversarial">反証142条件</option><option value="">すべて</option></select></label><label>基準<select id="base-filter"><option value="">すべて</option>' + ''.join(f'<option value="S{i:03d}">S{i:03d}</option>' for i in range(6)) + '</select></label></div><p id="visible-count"></p>')
        for item in sorted(candidates, key=lambda x: x['id']):
            spec, identifier = item['spec'], item['id']
            rows = read(HERE / 'sessions' / (identifier + '.json.gz'))
            body.append(f'<details class="method" id="{identifier}" data-role="{spec["role"]}" data-base="{spec["base_selector"]}"><summary>{identifier}：{escape(spec["name"])}</summary><p>{escape(description(spec))}</p>')
            for symbol in SYMBOLS:
                own = sorted([r for r in rows if r['symbol'] == symbol], key=lambda r: r['session'])
                groups = [('共通評価7セッション', [r for r in own if r['session'] in fixed['共通評価7セッション']]),
                          ('全13セッション', own), ('9/21〜25（10セッション）', [r for r in own if r['session'][:10] < '2026-09-28']),
                          ('9/28〜29（3セッション）', [r for r in own if r['session'][:10] >= '2026-09-28'])]
                body.append('<h3>' + symbol + '</h3>' + table(['期間', '利益 円', '損失 円', '収支 円', '勝ち枚', '負け枚', '同値枚', '枚数差'],
                            [result_row(label, totals(part)) for label, part in groups] + [result_row(r['session'].replace('_Day', ' 昼').replace('_Night', ' 夜'), r) for r in own]))
            if identifier in wave_by_id:
                wave_rows = sorted(wave_by_id[identifier], key=lambda r: (r['wave'], r['symbol']))
                assert len(wave_rows) == 8
                body.append('<details class="wave"><summary>指定波の保有時間・時価損益</summary><p>初期6セッション内の参考です。時価損益差は波の両端の含み損益を含みます。</p>' + table(['波', '銘柄', '正方向 分', '逆方向 分', '20分目安', '時価損益差 円'],
                            [[r['波名'], r['symbol'], f"{r['正方向ネット保有分']:.1f}", f"{r['逆方向ネット保有分']:.1f}", '達成' if r['正方向ネット20分目安達成'] else '未達', money(r['時価損益差円'])] for r in wave_rows]) + '</details>')
            body.append('</details>')
    body.append('<details><summary>資料と検証範囲</summary><p>148は同じ既知相場への主6方式と142反証です。新しい148市場や独立した148仮説を観測した意味ではありません。短期反転Rが低い効率比の相場に適するかも、今回確かめる仮説です。</p><p>ラージ先物の保存価格を小口商品へ換算しています。未記録の受信遅延やミニ／マイクロ固有の板は再現していません。現在セッションのAPI・保存物は使いません。</p><p><a href="README.md">読む順序・再現資料</a></p></details>')
    css = ':root{color-scheme:dark;background:#0b121e;color:#e4edf8;font-family:"Yu Gothic UI",Meiryo,sans-serif}body{max-width:1300px;margin:auto;padding:30px 20px;line-height:1.75}h1{font-size:29px}h2{font-size:23px;margin-top:30px}h3{font-size:18px}.lead{font-size:21px;color:#b9d8ff}a{color:#8ec9ff}.good{color:#76e0b6}.bad{color:#ff9ca9}.muted{color:#a8bacf}.status{color:#f2cf8b}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{padding:7px 10px;border-bottom:1px solid #2d4059;text-align:right}th{background:#192a40;color:#bfd3eb}th:first-child,td:first-child{text-align:left}details{background:#111d2e;border:1px solid #30445e;border-radius:9px;margin:16px 0;padding:14px}summary{cursor:pointer;font-weight:bold}select{display:block;font:inherit;background:#15263d;color:#e4edf8;padding:5px;max-width:100%}.controls{display:flex;gap:16px;flex-wrap:wrap}.method[hidden]{display:none}.button{display:inline-block;padding:9px 15px;background:#205a91;border-radius:7px}'
    script = '''/**
 * 表示対象だけを絞る。
 * @param {Event|undefined} event - 選択操作。
 * @returns {undefined} 返り値なし。売買や通信は行わない。
 */
function filterMethods(event){if(!document.getElementById('role-filter'))return;let n=0;document.querySelectorAll('.method').forEach(e=>{e.hidden=['role','base'].some(k=>{let v=document.getElementById(k+'-filter').value;return v&&e.dataset[k]!==v;});if(!e.hidden)n++;});document.getElementById('visible-count').textContent=n+'条件を表示';}document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filterMethods));filterMethods();'''
    document = '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + TITLE + '</title><style>' + css + '</style><body><!--\n[コンポーネント概要]\n.controls は主比較と反証の表示を選びます。.method は同じ方式の全セッション・週・枚数を表示します。\n数値は保存した全玉損益から作り、選択操作は検証対象や注文を変更しません。\n-->' + ''.join(body) + '<script>' + script + '</script></body></html>'
    (OUT / (TITLE + '.html')).write_text(document, encoding='utf-8')
    (OUT / 'README.md').write_text(f'''# 作業00027：{TITLE}

最初は [{TITLE}]({TITLE}.html) を開いてください。

読む順序：
1. 主6方式の共通後半7セッション比較。
2. 枝別の参加・損益と、各手法の週別・全セッション別の金額／決済枚数。
3. [５分足と売買](５分足と売買.html)。主6方式の要求／適用／実入口源と全売買を表示。
4. 事前の目安と、142反証の全結果。指定4波は各手法の末尾。
5. [結果前の固定設計](../../work/wave_v32/selection_fixed.md)、[選択の因果監査](../../work/wave_v32/selector_signal_audit.md)、[独立会計](../../work/wave_v32/selector_accounting_audit.md)、[所有者の監査](../../work/wave_v32/selection_ownership_audit.json)、[全件完備監査](../../work/wave_v32/検証完備の監査.json)。

現在は{'監査完了' if done else '実装・検証中'}。T/R自体も既知期間を見て選んだ比較部品なので、過去だけで選択を計算しても真の未知検証ではありません。費用0・指定価格約定を主比較とし、全玉を同セッションで返済します。

再現は `python -X utf8 work/wave_v32/run_verified.py --workers 8`。固定資料と損益前の構造監査を確認してから、固定T/Rの影口座・全148条件を再計算します。過去結果のキャッシュや現在APIは使いません。

[深夜上昇の取りこぼしの記録](../../work/wave_v32/S002_W04_TOPIXの未参加理由.md)は、既知の波での説明用分析です。数値条件の再調整には使っていません。
''', encoding='utf-8')
    update_index(done)
    print(json.dumps({'監査完了': done, '条件数': len(candidates), '表数': document.count('<table>')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
