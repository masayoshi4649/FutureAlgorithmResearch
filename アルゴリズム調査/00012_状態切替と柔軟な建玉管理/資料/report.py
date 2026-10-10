"""保存済みの集計を短い暗色HTMLと報告へ変換する。売買再計算や通信は行わない。"""
import argparse
import html
import json
import math
from pathlib import Path
import re
import shutil

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
FOLDER = '00012_状態切替と柔軟な建玉管理'
OUT = ROOT / 'アルゴリズム調査' / FOLDER
PAGE = '状態切替と柔軟な建玉管理.html'
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
SIGNALS = {'M1': '確定足の移動平均で続いている方向', 'M2': '板の注文フローと５分の値動きが一致する方向', 'M3': 'NK225・TOPIXの持続方向が一致する向き'}


def read(name):
    """保存済みJSONを読む。

    引数: name (str) は作業内ファイル名。返り値: JSONの値 (dict | list)。
    """
    return json.loads((WORK / name).read_text(encoding='utf-8'))


def label(session):
    """セッションの開始日と翌朝の関係を日本語で示す。

    引数: session (str) は日付と区分。返り値: 表示ラベル (str)。
    """
    date, part = session.split('_')
    day = int(date[-2:])
    return f'9/{day} 日中' if part == 'Day' else f'9/{day} 夜間 → 9/{day + 1} 朝'


def normalize(row, title):
    """集計の必要列を表示用へ変換する。

    引数: row (dict) は原集計、title (str) はラベル。返り値: 表示行 (dict)。
    """
    return dict(label=title, profit_yen=row['gross_profit_yen'], loss_yen=row['gross_loss_yen'],
                net_yen=row['net_yen'], profit_units=row['profit_units'], loss_units=row['loss_units'],
                flat_units=row['zero_units'])


def validate(configs, rows, weeks):
    """件数・金額・枚数・上限を原集計間で照合する。

    引数: configs/rows/weeks (list) は条件と集計。返り値: 照合記録 (dict)。
    """
    assert len(configs) == len({c['id'] for c in configs}) == 180
    assert len(rows) == 3600 and len(weeks) == 360
    cells = {(r['method_id'], r['symbol'], r['session']): r for r in rows}
    assert len(cells) == 3600
    week_keys = {(w['method_id'], w['symbol']) for w in weeks}
    assert len(week_keys) == 360
    assert week_keys == {(c['id'], s) for c in configs for s in ['NK225', 'TOPIX']}
    fields = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'unit_balance', 'closed_units']
    for row in rows + weeks:
        assert math.isclose(row['gross_profit_yen'] - row['gross_loss_yen'], row['net_yen'], abs_tol=.001)
        assert row['gross_loss_yen'] >= 0 and row['gross_profit_yen'] >= 0
        assert row['profit_units'] - row['loss_units'] == row['unit_balance']
        assert row['profit_units'] + row['loss_units'] + row['zero_units'] == row['closed_units']
        assert 0 <= row['max_long'] <= 100 and 0 <= row['max_short'] <= 100 and 0 <= row['max_gross'] <= 200
    for week in weeks:
        group = [cells[(week['method_id'], week['symbol'], s)] for s in SESSIONS]
        assert week['session_count'] == 10
        for key in fields:
            assert math.isclose(sum(r[key] for r in group), week[key], abs_tol=.001), (week['method_id'], key)
    return {'合格': True, '条件数': 180, '銘柄条件数': 360, 'セッション行数': 3600,
            '照合': '金額、枚数、全10区間の週合計、片側100・合計200上限', '売買再計算': False}


def describe(config):
    """手法を入口と管理の２文へまとめる。

    引数: config (dict) は条件。返り値: 短い説明 (list[str])。
    """
    direction = '同方向' if config['sign'] > 0 else '逆方向'
    target = 'その方向へ' if config['sign'] > 0 else 'その逆へ'
    return [f"{direction}：{SIGNALS[config['signal']]}を推定し、{target}0.25ATR進む逆指値で10枚開始。", config['description']]


def config_details(config):
    """管理ルールの設定値を日本語で展開する。

    引数: config (dict) は条件。返り値: 条件の説明 (str)。
    """
    trail = 'なし' if config['main_trail'] is None else f"{config['main_trail']:g}ATR"
    return '\n'.join([
        '主方向は２回の確認後に更新。弱まるだけでは反転せず、反対方向の確認を待つ。',
        'ATRは確定５分足のTRを係数1/12で平滑化（最少３本、下限２呼値）し、１組の初回注文時点で固定する。',
        '開始20分後から終了30分前まで新規受付。逆指値の有効期間２分、全返済後は５分休止。',
        f"１組の損失予算：初期{config['initial_qty']}枚 × {config['stop_atr']:g}ATR。主玉追跡：{trail}（１ATR順行後に有効）。",
        f"追加幅：{config['add_step']:g}ATR、基準追加枚数：{config['add_qty']}枚。カバー：主玉の{config['hedge_ratio']:g}倍、戻り{config['hedge_trigger']:g}ATRで開始。",
        f"カバー追跡：{config['cover_trail']:g}ATR。組利益の保護率：{config['lock_fraction']:.0%}。時間制限：{config['timeout_min']:g}分。",
        '未使用の追加・カバー設定は発注されない。判断反転でも、それまでの損失・建値は引き継ぐ。',
        '含み損も含めて全玉を管理し、最終的に全玉返済。利益玉だけを残して評価する集計ではない。',
        '注文は前行から有効な条件を使う。新しく決めた条件は次の原本行以降に適用。',
        '詳細パラメータ：' + json.dumps(config, ensure_ascii=False, separators=(',', ':')),
    ])


def amount(value):
    """基準円額を短い万円表記にする。

    引数: value (float) は円。返り値: 万円文字列 (str)。
    """
    return f'{value / 10000:+,.2f}'.rstrip('0').rstrip('.') + '万円'


def markdown_table(rows):
    """利益・損失・収支を枚数付きのMarkdown表へする。

    引数: rows (list[dict]) は正規化行。返り値: 表 (str)。
    """
    lines = ['| 区間 | 利益／枚数 | 損失／枚数 | 差引／枚数差 |', '| --- | ---: | ---: | ---: |']
    for r in rows:
        lines.append(f"| {r['label']} | {amount(r['profit_yen'])}／{r['profit_units']:,}枚 | {amount(-r['loss_yen'])}／{r['loss_units']:,}枚 | {amount(r['net_yen'])}／{r['profit_units']-r['loss_units']:+,}枚 |")
    return '\n'.join(lines)


def folded_details(walk, complete):
    """初期非表示の選択説明・時間順比較・監査案内を作る。

    引数: walk (list) は時間順比較、complete (dict) は完了記録。返り値: HTML (str)。
    """
    lines = ['<h2>比較と集計</h2><p>３つの主方向 × 正逆２方向 × 30の建玉管理＝180条件。表示初期値は先頭９区間で選んだ手法です。１枚ごとの平均勝ち負けと、全玉を閉じるまでの１組の勝ち負けは別に集計します。枚数の勝率を合格条件にはしていません。</p>',
             '<p>Nightは開始日です。9/25夜間は9/26朝までを含みます。約定は観測間の指定水準到達順で１件ずつ判定し、費用を０と仮定します。実mini・microの価格、流動性、約定は再現していません。</p>',
             '<h2>過去だけで選び直した時間順比較</h2><p>先頭３区間から９区間まで、その時点の過去成績で選び、次の１区間を合計。固定10枚の同じ主方向との比較です。ただし手法設計時には全区間が既読です。</p>',
             '<div class="table-wrap"><table><thead><tr><th>銘柄</th><th>選び直しの収支</th><th>固定10枚の収支</th></tr></thead><tbody>']
    for symbol in ['NK225', 'TOPIX']:
        rows = [r for r in walk if r['symbol'] == symbol]
        lines.append(f'<tr><td>{symbol}</td><td>{amount(sum(r["result"]["net_yen"] for r in rows))}</td><td>{amount(sum(r["baseline"]["net_yen"] for r in rows))}</td></tr>')
    lines.extend(['</tbody></table></div><p class="note">この時間順比較表のみ１倍の基準円額を固定表示します。</p>',
                  f'<h2>監査と原集計</h2><p>全{complete["セッションセル数"]:,}セルでセッション内返済。探索全体の最大保有は買い{complete["最大買い"]}枚・売り{complete["最大売り"]}枚。現在API取得０回。</p>',
                  '<p>表示の値は保存済み集計だけから読み込みます。ブラウザーのURLポリシーにより実画面の確認は行わず、JavaScriptの表示内容と行数をローカルで静的確認しています。</p>',
                  '<p><a href="資料/集計の独立監査.json">3,600セルの集計監査</a> · <a href="資料/エンジン独立監査.json">原本全行の会計監査</a> · <a href="資料/主方向信号の因果性監査.json">未来打切り監査</a> · <a href="資料/表示静的検査.json">表示の静的検査</a></p>',
                  '<p><a href="検証結果.md">初期表示２方式の一覧</a> · <a href="README.md">資料と再現手順</a> · <a href="資料/全条件一覧.json">全180条件</a> · <a href="資料/セッション集計.csv">セッション集計</a> · <a href="資料/週合計.csv">週合計</a> · <a href="資料/時間順比較.json">時間順明細</a></p>'])
    return ''.join(lines)


def update_indexes():
    """作業一覧の最新入口を00012へ更新する。

    引数: なし。返り値: なし。既存の個別作業ファイルは変更しない。
    """
    base = OUT.parent
    path = base / 'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*', f'**最新は00012の[状態切替と柔軟な建玉管理]({FOLDER}/{PAGE})です。手法を選び、週と各セッションの利益・損失・収支を金額と枚数で確認できます。**', text, count=1)
    text = text.replace('`00011_一週間データでの再検証`（最新）', '`00011_一週間データでの再検証`')
    text = re.sub(r'^\| `00012_.*\n', '', text, flags=re.M)
    entry = f'| `{FOLDER}`（最新） | 状態切替・増玉・カバー・反転の180条件 | [手法別の損益]({FOLDER}/{PAGE}) | [結果]({FOLDER}/検証結果.md)・[案内]({FOLDER}/README.md) |\n'
    text = text.replace('| --- | --- | --- | --- |\n', '| --- | --- | --- | --- |\n' + entry)
    text = text.replace('`00012_内容`', '`00013_内容`')
    path.write_text(text, encoding='utf-8')
    path = base / 'index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00012開始-->.*?<!--00012終了-->', '', text, flags=re.S)
    text = text.replace('class="task latest"', 'class="task"').replace(' <span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新は180条件の建玉管理の比較。手法を選び、週と各セッションの利益・損失・収支を確認できます。</p>', text, count=1)
    entry = f'<!--00012開始--><article class="task latest"><div class="number">作業00012 <span class="badge">最新</span></div><h2>状態切替と柔軟な建玉管理</h2><p>増玉・カバー・反転など180条件。手法の短い説明と、金額・枚数の週合計とセッション別損益。</p><a class="button" href="{FOLDER}/{PAGE}">手法別の損益を開く →</a><p><a href="{FOLDER}/検証結果.md">検証結果</a> · <a href="{FOLDER}/README.md">読む順序</a></p></article><!--00012終了-->'
    text = text.replace('</header>', '</header>' + entry, 1)
    text = re.sub(r'<footer>最新作業は.*?</footer>', '<footer>最新作業は00012です。過去資料を残し、次の別作業は00013以降へ追加します。</footer>', text, count=1)
    path.write_text(text, encoding='utf-8')


def main():
    """保存済み集計からHTML・短い報告・再現資料を出力する。

    引数: コマンド行 --publish (bool) は索引更新。返り値: なし。
    """
    parser = argparse.ArgumentParser(description='保存済み結果の短い表示を生成')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    configs, rows, weeks = read('全条件一覧.json'), read('セッション集計.json'), read('週合計.json')
    settings, complete, walk = read('表示設定.json'), read('探索完了記録.json'), read('時間順比較.json')
    audit = validate(configs, rows, weeks)
    assert complete['全セル返済'] and complete['入力コード不変'] and complete['現在API取得回数'] == 0
    cells = {(r['method_id'], r['symbol'], r['session']): r for r in rows}
    payload = {'methods': [], 'results': {}, 'defaults': settings['default']}
    for c in configs:
        payload['methods'].append(dict(id=c['id'], name=c['name'], description=describe(c), details=config_details(c), symbols=['NK225', 'TOPIX']))
    for w in weeks:
        payload['results'][w['method_id']+'|'+w['symbol']] = dict(
            weekly=normalize(w, '週合計'), sessions=[normalize(cells[(w['method_id'], w['symbol'], s)], label(s)) for s in SESSIONS],
            max_long=w['max_long'], max_short=w['max_short'], max_gross=w['max_gross'], drawdown_yen=w['drawdown_yen'],
            avg_profit_per_unit=w['avg_profit_per_unit'] or 0, avg_loss_per_unit=w['avg_loss_per_unit'] or 0,
            unit_payoff_text=f"{w['unit_payoff']:.2f}" if w['unit_payoff'] is not None else '算定なし',
            cycle_payoff_text=f"{w['cycle_payoff']:.2f}" if w['cycle_payoff'] is not None else '算定なし')
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    page = (WORK / 'report_template.html').read_text(encoding='utf-8').replace('__PAYLOAD__', data).replace('__DETAILS__', folded_details(walk, complete))
    (OUT / PAGE).write_text(page, encoding='utf-8')
    text = ['# 状態切替と柔軟な建玉管理', '', f'全180条件は[HTML]({PAGE})で切り替えます。以下は初期表示２方式です。金額はラージ価格倍率の参考円、枚数は仮想単位。', '']
    for symbol in ['NK225', 'TOPIX']:
        method = next(m for m in payload['methods'] if m['id'] == settings['default'][symbol])
        result = payload['results'][method['id']+'|'+symbol]
        text += [f"## {symbol}：{method['id']} ／ {method['name']}", '', ' '.join(method['description']), '', markdown_table([result['weekly']] + result['sessions']), '', f"同値返済は{result['weekly']['flat_units']:,}枚。最大保有は買い{result['max_long']}・売り{result['max_short']}・合計{result['max_gross']}枚。", '']
    text += ['この週の価格を既に調査した後で180条件を設計した比較で、未読検証ではありません。費用０・指定価格約定・セッション内返済。差引枚数は利益枚数−損失枚数で、最終建玉は０です。']
    (OUT / '検証結果.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    readme = f'''# 00012 状態切替と柔軟な建玉管理

最初に [{PAGE}]({PAGE}) を開いてください。

1. HTMLで銘柄と手法を選択。説明２行、週合計、10セッションの金額・枚数を表示します。
2. [検証結果.md](検証結果.md) は初期表示２方式だけの一覧です。
3. 条件・時間順比較・監査はHTMLの「条件・集計方法・監査」を開きます。原集計は [資料](資料/) です。

３信号 × 正逆２方向 × 30管理＝180条件。初期表示は先頭９区間で選んだ方式ですが、週の価格は手法設計前に既読です。換算倍率は円額だけの仮定で、実mini・micro板の検証ではありません。

## 再現

プロジェクトルートで `python work/wave_v17/report.py --publish` を実行すると、保存済みJSONだけから報告・索引を更新します。`node work/wave_v17/check_report.js` で表示値・行数・換算を確認します。売買再計算やAPI取得は行いません。

売買再現の本体は `research.py`、条件は `catalog.py`、主方向は `signals.py`、建玉管理は `engine.py`。データ参照先はソースの定義を使用し、過去の作業・原本を編集しません。`全返済と組.pkl` 等の大きい再生台帳は `work/wave_v17` に置き、資料には集計とソースを保存します。

ブラウザー表示は既存のURLポリシー拒否により未確認です。迂回・再試行せず、HTML・JavaScriptのローカル静的検査を行います。
'''
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    (WORK / '報告集計照合.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    target = OUT / '資料'
    target.mkdir(exist_ok=True)
    for file in WORK.iterdir():
        if file.is_file() and file.suffix in ['.py', '.md', '.json', '.csv', '.html', '.js'] and file.name != '表示構文確認.js':
            shutil.copy2(file, target / file.name)
    if args.publish:
        update_indexes()
    print(json.dumps({'HTML': str(OUT / PAGE), **audit}, ensure_ascii=False))


if __name__ == '__main__':
    main()
