"""方向情報の鮮度を、元の利益と参加開始の差から簡潔に報告する。"""

from __future__ import annotations

import gzip
from hashlib import sha256
from html import escape
import importlib.util
import json
from pathlib import Path
import re

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '00026_方向情報の鮮度と保有継続'
TITLE = '方向情報の鮮度と保有継続'
OUT = ROOT / 'アルゴリズム調査' / NAME
SYMBOLS = ('TOPIX', 'NK225')

_spec = importlib.util.spec_from_file_location('freshness_display_helpers', HERE.parent / 'wave_v30/report_round6.py')
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)
money, table, sums, result_row = helpers.money, helpers.table, helpers.sums, helpers.result_row


def read(path: Path, default: object = None) -> object:
    """機能: この診断の保存済み資料を読み込む。

    引数: path (Path)、default (object)。返り値: 内容 (object)。現在保存物を拒否する。
    """
    assert 'live' not in path.parts
    if not path.exists():
        return default
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def ratio(value: float | None) -> str:
    """機能: 算定できない比率を0とせず、横線で表示する。

    引数: value (float|None)。返り値: 表示文字列 (str)。
    """
    return '—' if value is None else f'{value:.2f}'


def verified_completion(guard: dict) -> bool:
    """機能: 完了表示を、全件数・監査実装・参照資料の一致に限定する。

    引数: guard (dict)。返り値: 全照合済みならTrue (bool)。
    """
    if not guard:
        return False
    assert guard['診断完了'] is True
    assert [guard[k] for k in ('全条件数', '全入力数', '指定波区間数')] == [420, 10920, 3360]
    assert guard['方向保存180ファイルの構造監査指紋一致'] is True
    assert all(guard[k] is False for k in ('新候補選抜', '成績選別', '現在データ使用'))
    assert guard['API取得数'] == 0
    for name, key in (('completion_guard.py', 'ガード実装SHA256'), ('completion_guard_fixed.json', 'ガード固定SHA256')):
        assert sha256((HERE / name).read_bytes()).hexdigest() == guard[key]
    for name, expected in guard['参照資料SHA256'].items():
        assert sha256(Path(name).read_bytes()).hexdigest() == expected
    return True


def paired(candidates: list[dict]) -> list[dict]:
    """機能: 元の全84内で対応を固定し、6種類の差を銘柄別に集計する。

    引数: candidates (list[dict])。返り値: 全7管理別の全12入口中央値 (list[dict])。
    """
    by_id = {c['id']: c for c in candidates}
    output = []
    pairs = [('V030', 'V000'), ('V060', 'V000'), ('W030', 'V000'), ('W060', 'V000'), ('V030', 'W030'), ('V060', 'W060')]
    for manager in [f'L{i:03d}' for i in range(7)]:
        for left, right in pairs:
            for symbol in SYMBOLS:
                values = []
                for i in range(3, 92, 8):
                    a, b = [by_id[f'H{i:03d}__{manager}__{v}']['symbols'][symbol] for v in (left, right)]
                    values.append({k: a[k] - b[k] for k in ('net_yen', 'drawdown_yen', 'closed_units', 'long_unit_minutes', 'short_unit_minutes', 'opening_orders')})
                    values[-1]['unit_minutes'] = values[-1]['long_unit_minutes'] + values[-1]['short_unit_minutes']
                output.append({'manager': manager, 'contrast': left + '−' + right, 'symbol': symbol,
                               **{k: float(np.median([v[k] for v in values])) for k in values[0]},
                               'net_better_count': sum(v['net_yen'] > 0 for v in values), 'count': 12})
    return output


def update_index(done: bool) -> None:
    """機能: 新しい番号の報告を作業一覧の先頭に登録する。

    引数: done (bool)。返り値: なし (None)。過去の作業内容は変更しない。
    """
    parent = OUT.parent
    path = parent / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00026開始-->.*?<!--00026終了-->', '', text, flags=re.S)
    text = text.replace('task latest', 'task').replace(' <span class="badge">最新</span>', '')
    label = '全420条件の診断結果' if done else '方向情報の鮮度を診断中'
    text = re.sub(r'<p class="lead">.*?</p>', f'<p class="lead">最新は00026（{label}）。現在データの追加取得は行っていません。</p>', text, count=1)
    block = f'<!--00026開始--><article class="task latest"><div class="number">作業00026 <span class="badge">最新</span></div><h2>{TITLE}</h2><p>30分・60分古い方向と、開始を待つだけの対照。全84手法×5変形を比較。</p><a class="button" href="{NAME}/{TITLE}.html">{label} →</a><p><a href="{NAME}/README.md">資料案内</a></p></article><!--00026終了-->'
    path.write_text(text.replace('</header>', '</header>' + block, 1), encoding='utf-8')
    path = parent / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00026の[{TITLE}]({NAME}/{TITLE}.html)（{label}）。**', text, count=1)
    text = re.sub(r'^\| `00026_.*\n', '', text, flags=re.M).replace('`（最新）', '`')
    anchor = '| --- | --- | --- | --- |'
    text = text.replace(anchor, anchor + f'\n| `{NAME}`（最新） | 元84手法の鮮度・開始遅れ420対照 | [第7反復]({NAME}/{TITLE}.html) | [資料案内]({NAME}/README.md) |', 1)
    path.write_text(text, encoding='utf-8')


def main() -> None:
    """機能: 診断の要点と全420の週・セッション別損益を生成する。

    引数: なし。返り値: なし (None)。遅延条件の順位付けや採用を行わない。
    """
    OUT.mkdir(exist_ok=True)
    fixed = read(HERE / '探索条件の固定.json')
    candidates = read(HERE / '全条件の期間集計.json.gz', [])
    guard = read(HERE / '診断完備の監査.json', {})
    complete = verified_completion(guard)
    waves = read(HERE / 'episode_audit.json', {})
    participation = read(HERE / 'participation.json', {})
    wave_by_id = {}
    for row in waves.get('結果', []):
        wave_by_id.setdefault(row['method'], []).append(row)
    body = [f'<p><a href="../index.html">作業一覧</a></p><h1>{TITLE}</h1>']
    body.append('<p class="lead">直近の方向情報は利益に必要か。30分・60分古い判断と比べました。</p>' if complete else f'<p class="lead">検証中：保存済み {len(candidates)}/420条件。会計・先読み・指定波の確認後に結論を確定します。</p>')
    if complete:
        body.append('<p><strong>H019の利益は、方向信号と参加開始の時刻に大きく依存しました。</strong>30分古い信号では収支がTOPIX +521,000円→+125,000円、NK +257,500円→−27,000円。ただし、他の入口まで一律に「新しいほど良い」とは言えません。今回も元の候補を維持し、最良の遅延条件への変更は行いません。</p>')
    body.append('<p>Vは方向情報を古くする対照、Wは同じ遅延信号が初めて出るまで待ち、その後は現在の情報を使う対照です。<strong>価格・ATR・枚数・返済方法は変えません。</strong>遅延しても、新規の追跡注文は現在価格を見ます。最良の遅延を新候補へ採用する調査ではありません。</p>')
    body.append('<p class="muted">既知13セッション。費用0・指定価格約定、TOPIXミニ5枚／NKマイクロ10枚で開始、片方向上限10／20枚。全玉場内返済。現在API・保存済み現在データは使いません。</p>')
    if (OUT / '５分足と売買.html').exists():
        body.append('<p><a class="button" href="５分足と売買.html">H019の全35条件：５分足と売買</a></p>')
    body.append('<details><summary>5つの対照と、機械的な入口・返済</summary>' + table(['対照', '何を変えるか'], [[v['id'], escape(v['name'])] for v in fixed['variants']]) + '<p>元の入口は、中期の自市場方向・60秒遅延した相手方向の一致・短期価格の順行を確認します。新規は0.25ATRの反発／反落追跡、初期1ATR相当で損切り、2ATRで半分を整数切捨て利確、1.5ATR順行後3ATR幅で追跡。最長360分、返済後5分休止。ATRは公開済み5分足の12期間平滑で、注文準備時に固定します。</p>' + table(['管理', '追加の方向撤回'], [[m['id'], escape(m['name'])] for m in fixed['managers']]) + '<p>WとVは、解放後の実際の初回約定・方向・保有時間・再新規まで同じではありません。V−Wを情報鮮度だけの純粋な効果とは断定しません。</p></details>')
    comparisons = paired(candidates) if len(candidates) == 420 else []
    if candidates:
        by_id = {c['id']: c for c in candidates}
        body.append('<h2>固定参考H019：価格ストップ＋追跡返済</h2><p>前回からの同じ基準L000を5通りで比較。数値は13セッション合計です。</p>')
        reference_rows = []
        for variant in fixed['variants']:
            for symbol in SYMBOLS:
                s = by_id[f"H019__L000__{variant['id']}"]['symbols'][symbol]
                reference_rows.append([variant['id'], symbol, money(s['gross_profit_yen']), money(-s['gross_loss_yen']), money(s['net_yen']), f"{s['drawdown_yen']:,.0f}",
                                       f"{s['profit_units']}/{s['loss_units']}/{s['zero_units']}", f"{s['opening_orders']:,}", f"{s['long_unit_minutes']+s['short_unit_minutes']:,.0f}"])
        body.append(table(['対照', '銘柄', '利益 円', '損失 円', '収支 円', '最大下落 円', '勝/負/同値枚', '新規数', '保有枚数×分'], reference_rows))
        body.append('<details><summary>H019の入口と、待機だけでも損益が変わる理由</summary><p>確定した1分足のEMA15/60を使用。両線の差が0.15ATRを超え、EMA60の3本変化も0.02ATRを超える方向を採用します。方向は両線の上下関係が逆になるまで維持。相手銘柄の60秒前の方向も一致し、自市場の最良売買気配の中間価格が30秒前より同方向へ0.05ATR超進んだら、追跡新規を準備します。未確定の足は使いません。</p><p>W060のTOPIXでは保有量が22,076→18,555枚分へ減っても、新規数は50→83回、損失は494,500→963,000円へ増加しました。開始を遅らせると、取引を逃すだけでなく、その後の損切り・再新規の経路も変わります。</p><p><a href="../../work/wave_v31/h019_participation_note.md">セッション別の差と解釈</a>（結果を見た後の説明用分析。採用条件には使用しません）。</p></details>')
        body.append('<h2>価格管理の全12入口でも比較</h2><p>各欄は同じ入口の差を取った中央値。収支差はプラス、最大下落差はマイナスが改善です。</p>')
        body.append(table(['対照差', '銘柄', '収支差 円', '最大下落差 円', '新規数差', '保有枚数×分の差'], [[r['contrast'], r['symbol'], money(r['net_yen']), f"{r['drawdown_yen']:+,.0f}", f"{r['opening_orders']:+,.0f}", f"{r['unit_minutes']:+,.0f}"] for r in comparisons if r['manager'] == 'L000']))
        if participation:
            weights = [r for r in participation['等重み集計'] if r['manager'] == 'L000']
            body.append('<details><summary>近縁の入口を5思想へまとめても確認</summary><p>EMAの近い4設定を別々の証拠と数えず、思想内の差を平均し、5思想の中央値も確認しました。入口の数え方で差の符号が変わります。12入口は独立した12市場ではありません。</p>' + table(['対照差', '銘柄', '12入口の収支差 円', '5思想の収支差 円'], [[r['comparison'], r['symbol'], money(r['全12入口の中央値']['収支差円']), money(r['5思想等重みの中央値']['収支差円'])] for r in weights]) + '</details>')
        body.append('<details><summary>方向撤回を加えた6管理の対応差も開く</summary>' + table(['管理', '対照差', '銘柄', '収支差 円', '最大下落差 円', '収支改善数'], [[r['manager'], r['contrast'], r['symbol'], money(r['net_yen']), f"{r['drawdown_yen']:+,.0f}", f"{r['net_better_count']}/12"] for r in comparisons if r['manager'] != 'L000']) + '</details>')
        body.append('<h2>全手法の週別・セッション別損益</h2><p>勝ち・負けは決済枚数。枚数差は保有残ではありません。表示だけを絞り、検証対象は全420条件です。</p><div class="controls">')
        for key, label, rows, default in [('signal', '入口', fixed['signals'], 'H019'), ('manager', '管理', fixed['managers'], 'L000'), ('variant', '対照', fixed['variants'], '')]:
            body.append(f'<label>{label}<select id="{key}-filter"><option value="">すべて</option>' + ''.join(f'<option value="{r["id"]}"' + (' selected' if r['id'] == default else '') + f'>{r["id"]} {escape(r["name"])}</option>' for r in rows) + '</select></label>')
        body.append('</div><p id="visible-count"></p>')
        checked = []
        for spec in fixed['signals']:
            sessions = {x['id']: x['rows'] for x in read(HERE / 'sessions' / (spec['id'] + '.json.gz'))}
            for manager in fixed['managers']:
                for variant in fixed['variants']:
                    identifier = '__'.join((spec['id'], manager['id'], variant['id']))
                    candidate = by_id[identifier]
                    body.append(f'<details class="method" id="{identifier}" data-signal="{spec["id"]}" data-manager="{manager["id"]}" data-variant="{variant["id"]}"><summary>{identifier}：{escape(variant["name"])}</summary><p>{escape(spec["name"])}／{escape(manager["name"])}</p>')
                    for symbol in SYMBOLS:
                        rows = sorted([r for r in sessions[identifier] if r['symbol'] == symbol], key=lambda r: r['session'])
                        assert len(rows) == 13
                        total = sums(rows)
                        for k, v in total.items():
                            assert abs(v - candidate['symbols'][symbol][k]) < .01
                        weeks = [('全13セッション', total), ('9/21〜25（10セッション）', sums([r for r in rows if r['session'][:10] < '2026-09-28'])),
                                 ('9/28〜29（3セッション）', sums([r for r in rows if r['session'][:10] >= '2026-09-28']))]
                        body.append(f'<h3>{symbol}</h3>' + table(['期間', '利益 円', '損失 円', '収支 円', '勝ち枚', '負け枚', '同値枚', '枚数差'],
                                                               [result_row(label, r) for label, r in weeks] + [result_row(r['session'].replace('_Day', ' 昼').replace('_Night', ' 夜'), r) for r in rows]))
                        s = candidate['symbols'][symbol]
                        body.append(f'<p>利益÷損失 {ratio(s["money_ratio"])}、1枚平均の勝ち÷負け {ratio(s["average_unit_payoff"])}。含み損込み最大下落 {s["drawdown_yen"]:,.0f}円。最大2勝ちセッション除外後 {s["two_sessions_removed_net"]:+,.0f}円。</p>')
                        checked.append({'id': identifier, 'symbol': symbol, **total})
                    if identifier in wave_by_id:
                        wave_rows = sorted(wave_by_id[identifier], key=lambda r: (r['wave'], r['symbol']))
                        assert len(wave_rows) == 8
                        body.append('<details class="wave"><summary>指定した4つの波・両銘柄の保有と損益</summary><p>正方向に合計20分以上ネット保有できたかを確認。利益の有無とは分けて評価します。時価損益差は波の両端の含み損益を含み、決済益だけではありません。</p>' + table(['波', '銘柄', '正方向 分', '逆方向 分', '20分目安', '時価損益差 円'], [[r['波名'], r['symbol'], f"{r['正方向ネット保有分']:.1f}", f"{r['逆方向ネット保有分']:.1f}", '達成' if r['正方向ネット20分目安達成'] else '未達', money(r['時価損益差円'])] for r in wave_rows]) + '</details>')
                    body.append('</details>')
        (OUT / '表示数値の検査.json').write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding='utf-8')
    body.append('<details><summary>意味と限界・再現資料</summary><p>元84を含む420は同じ相場への補助対照です。新しい420の市場を観測したわけではありません。元の研究候補・過去の反証結果は維持し、遅延した値を新しい最適設定へ採用しません。30／60分の対照は実際の通信遅延の再現ではなく、信号が古くなった場合の診断です。</p><p>L000では入口だけ、他の6管理では入口と保有撤回の方向を遅らせています。古い方向と現在の方向が同じ時間もあり、古くして黒字を保っても予測が無意味とは言えません。</p><p>保存された行順で未来を使わないことを検査しましたが、実際の受信時刻は保存されていません。ラージ先物の価格をミニ／マイクロへ換算した結果で、商品ごとの板・約定は未再現です。未知セッションの安定利益を証明した結果ではありません。</p><p><a href="README.md">読む順序・再現資料</a> · <a href="../../work/wave_v31/freshness_diagnostic_design.md">結果前に固定した検査の意味</a></p></details>')
    if complete:
        body.append('<p class="muted">全420条件・10,920入力の独立会計と、3,360波・910チャートを照合済み。先読み検査、元84条件の再現、参照ファイルの指紋も一致しました。</p>')
    css = ':root{color-scheme:dark;background:#0b121e;color:#e4edf8;font-family:"Yu Gothic UI",Meiryo,sans-serif}body{max-width:1300px;margin:auto;padding:30px 20px;line-height:1.75}h1{font-size:29px}h2{font-size:23px;margin-top:30px}h3{font-size:18px}.lead{font-size:21px;color:#b9d8ff}a{color:#8ec9ff}.good{color:#76e0b6}.bad{color:#ff9ca9}.muted{color:#a8bacf}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{padding:7px 10px;border-bottom:1px solid #2d4059;text-align:right}th{background:#192a40;color:#bfd3eb}th:first-child,td:first-child{text-align:left}details{background:#111d2e;border:1px solid #30445e;border-radius:9px;margin:16px 0;padding:14px}summary{cursor:pointer;font-weight:bold}select{display:block;font:inherit;background:#15263d;color:#e4edf8;padding:5px;max-width:100%}.controls{display:flex;gap:16px;flex-wrap:wrap}.controls label{max-width:100%}.method[hidden]{display:none}.button{display:inline-block;padding:9px 15px;background:#205a91;border-radius:7px}'
    script = '''/**
 * 全420条件から表示だけを絞る。
 * @param {Event|undefined} event - 選択操作。
 * @returns {undefined} 返り値なし。売買・通信は行わない。
 */
function filterMethods(event){const keys=['signal','manager','variant'];if(!document.getElementById('signal-filter'))return;let count=0;document.querySelectorAll('.method').forEach(e=>{e.hidden=keys.some(k=>{const v=document.getElementById(k+'-filter').value;return v&&e.dataset[k]!==v;});if(!e.hidden)count++;});document.getElementById('visible-count').textContent=count+'条件を表示';}
document.querySelectorAll('select').forEach(e=>e.addEventListener('change',filterMethods));filterMethods();'''
    html = '<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + TITLE + '</title><style>' + css + '</style><body><!--\n[コンポーネント概要]\n.controls は入口・管理・鮮度条件の表示選択です。.method は週・全セッションの全玉損益を示します。\n表示値は保存済み集計と一致確認し、外部通信や注文は行いません。\n-->' + ''.join(body) + '<script>' + script + '</script></body></html>'
    (OUT / (TITLE + '.html')).write_text(html, encoding='utf-8')
    (OUT / '表示データ.json').write_text(json.dumps({'診断完了': complete, '全条件': len(candidates), '対応比較': comparisons,
                                                    '表数': html.count('<table>'), '新候補選抜': False, '現在データ使用': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'README.md').write_text(f'''# 作業00026：{TITLE}

最初は [{TITLE}]({TITLE}.html) を開いてください。

読む順序：
1. 固定参考H019と、価格管理の全12入口の比較。
2. 入口・管理・対照を選び、全420の週別／13セッション別の利益・損失・収支と決済枚数。
3. 各手法末尾の「指定した4つの波」で、保有時間と含み損益込みの結果。
4. [５分足と売買](５分足と売買.html)。成績で絞らずH019全7管理×5対照を図示。
5. [結果前の設計](../../work/wave_v31/freshness_diagnostic_design.md)、[因果監査](../../work/wave_v31/lag_causality_audit.md)、[独立会計](../../work/wave_v31/lag_accounting_audit.md)、[波・参加量監査](../../work/wave_v31/episode_audit.md)、[全件完備監査](../../work/wave_v31/診断完備の監査.json)。

これは既知13セッションの鮮度診断で、新候補の選抜ではありません。元84を含む420条件。Vは方向の遅延、Wは同じ遅延入口が初めて出るまでの開始待ち。解放後の参加量は同じではありません。費用0・指定価格約定・全玉場内返済。

再現は `python -X utf8 work/wave_v31/run_verified.py` から開始します。固定元・損益前因果検査を照合して実行し、既存結果のcacheを使わず全420を再計算します。現在API及び以前の現在保存物は参照しません。

今回の結論：H019は方向情報・開始時刻への依存が大きく、待機で保有量を減らしても損切りが増える例がありました。ただし全12入口／5思想での差は揃わず、最新情報の普遍的な優位性や未知データでの安定性までは証明していません。採用設定の変更はありません。
''', encoding='utf-8')
    update_index(complete)
    print(json.dumps({'診断完了': complete, '全条件': len(candidates), '表数': html.count('<table>')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
