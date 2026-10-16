"""狭い出口と再参加の結論を短い暗色画面と折り畳み損益表で公開する。"""

import hashlib
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
FOLDER = '00082_E01の狭幅トレールと再エントリー'
PUBLIC = ROOT / 'アルゴリズム調査' / FOLDER
MAIN = '狭いトレールと再エントリーの結果.html'
SYMBOLS = ('TOPIX', 'NK225')
LABELS = {'TOPIX': 'TOPIXミニ', 'NK225': '日経マイクロ'}
BASE = 'E01_G_U'


def read(path):
    """
    機能: 生成済み集計を読み取る。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def money(value):
    """
    機能: 円単位の数値を色と符号を付けて表示する。
    引数: value(float)。
    返り値: str のHTML。
    """
    n = round(value)
    color = 'gain' if n > 0 else 'loss' if n < 0 else 'neutral'
    return f'<span class="{color}">{n:+,}円</span>' if n else '0円'


def percent(value):
    """
    機能: 未定義率を区別して百分率へ変換する。
    引数: value(float又はNone)。
    返り値: str。
    """
    return '未定義' if value is None else f'{value*100:.1f}%'


def table(heads, rows, class_name=''):
    """
    機能: 横にスクロールできる静的な表を生成する。
    引数: heads(list[str])、rows(list[list[str]])、class_name(str)。
    返り値: str のHTML。
    """
    header = ''.join('<th>'+h+'</th>' for h in heads)
    body = ''.join('<tr>'+''.join(('<th>' if i == 0 else '<td>')+v+('</th>' if i == 0 else '</td>')
                                for i, v in enumerate(row))+'</tr>' for row in rows)
    return f'<div class="scroll"><table class="{class_name}"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def explain(config):
    """
    機能: パラメータ表を読まなくても分かる出口と再参加の説明を返す。
    引数: config(dict)。
    返り値: str。
    """
    exits = dict(T0='元の広いトレールを維持します。',
        T1='1ATR進んだら、最高値・最安値から1ATR戻ったところで降ります。大きく伸びた後は0.75ATRへ狭めます。',
        T2='0.75ATR進んだら、0.5ATRの戻りで降ります。',
        T3='1ATR進んだら幅1.5ATRで追跡し、1.5ATR進んだ時点で幅0.5ATRへ狭めます。',
        T4='1ATR進んだら幅1.5ATRで追跡し、短期の逆行が確認できたら幅0.5ATRへ狭めます。')
    clock = '元の内部追跡の終了を待って再準備します。' if config['clock_id'] == 'S' else {
        'A5': '全返済後5分で、新しいエントリーを準備できます。',
        'A1': '全返済後1分で、新しいエントリーを準備できます。',
        'A0': '全返済後の次の観測から、新しいエントリーを準備できます。',
        'P1': '手数料後黒字で全返済した場合だけ、1分後に再準備できます。赤字・ゼロ終了は元の内部追跡終了後5分を待ちます。',
        'P0': '手数料後黒字で全返済した場合だけ、次の観測から再準備できます。赤字・ゼロ終了は元の内部追跡終了後5分を待ちます。'}[config['clock_id']]
    return exits[config['exit_id']] + clock + '再参加にも両市場の方向確認と反発・反落確認が必要です。'


def validate_result(result):
    """
    機能: 公開する全場と合計の主会計が一致することを確認する。
    引数: result(dict)。
    返り値: None。
    """
    assert len(result['rows']) == 60
    for row in result['rows']:
        assert abs(row['campaign_profit']-row['campaign_loss']-row['net']) < 1e-6
        assert abs(row['gross']-row['fees']-row['net']) < 1e-6
        assert row['residual_long'] == row['residual_short'] == 0
        assert row['new_lots'] == row['exit_lots']
    for symbol in SYMBOLS:
        subset = [r for r in result['rows'] if r['symbol'] == symbol]
        assert len(subset) == 30
        total = result['periods']['全30'][symbol]
        for field in ('campaign_profit', 'campaign_loss', 'net', 'fees', 'campaigns', 'new_lots'):
            assert abs(sum(r[field] for r in subset)-total[field]) < 1e-6


def main():
    """
    機能: 結論と必要最小限の比較を先頭に置き、全場と全条件を折り畳む。
    引数: なし。
    返り値: None。数値照合記録、HTML、案内を生成する。
    """
    fixed = read(WORK / '事前固定.json')
    analysis = read(WORK / 'analysis/比較結果.json')
    extra_path = WORK / 'phase2/事前固定.json'
    extra = read(extra_path) if extra_path.exists() else None
    all_configs = fixed['catalog'] + (extra['catalog'] if extra else [])
    locations = {c['id']: WORK for c in fixed['catalog']}
    if extra:
        locations.update({c['id']: WORK / 'phase2' for c in extra['catalog']})
    results = {m: {c['id']: read(locations[c['id']] / m / 'results' / (c['id']+'.json')) for c in all_configs}
               for m in fixed['models']}
    for values in results.values():
        for value in values.values():
            validate_result(value)
    configs = {c['id']: c for c in all_configs}
    best = analysis['観測価格参考首位']
    displayed = analysis['詳細表示']
    comparison = analysis['比較']['observed']
    improved = [r['id'] for r in comparison if r['両商品四指標改善']]
    custom = read(HERE / '短い結論.json')
    title, lead, comment = custom['見出し'], custom['結論'], custom['注意']
    selected = custom.get('比較候補', best)
    assert selected in configs
    displayed = list(dict.fromkeys([BASE, selected] + displayed))
    # ----------------------------------------
    # 先頭は基準と比較候補の数値だけに絞る。
    values = [(identifier, s, results['observed'][identifier]['periods']['全30'][s])
              for s in SYMBOLS for identifier in (BASE, selected)]
    metric_rows = [
        ['収支']+[money(v['net']) for _, _, v in values],
        ['利益 / 損失']+[money(v['campaign_profit'])+' / '+money(-v['campaign_loss']) for _, _, v in values],
        ['金額利益割合']+[percent(v['campaign_profit_share']) for _, _, v in values],
        ['黒字セッション']+[str(v['positive_sessions'])+' / 30' for _, _, v in values],
        ['最大下落']+[money(-v['max_drawdown']) for _, _, v in values],
        ['新規から全返済までの回数']+[str(v['campaigns'])+'回' for _, _, v in values],
        ['手数料（収支に計上済み）']+[money(-v['fees']) for _, _, v in values],
    ]
    heads = ['指標']+[LABELS[s]+'<br>'+('基準' if i == BASE else html.escape(i)) for i, s, _ in values]
    summary = table(heads, metric_rows)
    case_rows = []
    for identifier in dict.fromkeys([BASE, selected]):
        target = {r['symbol']: r for r in results['observed'][identifier]['rows'] if r['session'] == '2026-09-24_Night'}
        case_rows.append([identifier]+[money(target[s]['net']) for s in SYMBOLS])
    case_table = table(['手法', '9/24ナイト TOPIX', '9/24ナイト 日経'], case_rows)
    frequency_ids = [('T2_S', '従来の再参加待ち'), ('T2_A1', '全返済後1分で再準備')]
    if extra:
        frequency_ids += [('T2_P1', '利確後だけ1分で再準備'), ('T2_P0', '利確後だけ次の観測で再準備')]
    frequency_rows = []
    for identifier, label in frequency_ids:
        period = results['observed'][identifier]['periods']['全30']
        frequency_rows.append([html.escape(label)+'<br><span class="note">'+identifier+'</span>']+
            [money(period[s]['net'])+'<br><span class="note">'+str(period[s]['campaigns'])+'回</span>' for s in SYMBOLS])
    frequency_table = table(['再参加方法（全て幅0.5ATR）', 'TOPIX 収支・回数', '日経 収支・回数'], frequency_rows)
    blocks = []
    for identifier in displayed:
        result = results['observed'][identifier]
        by_key = {(r['session'], r['symbol']): r for r in result['rows']}
        rows = []
        for name in fixed['全30']:
            cells = [name.replace('_Day', ' デイ').replace('_Night', ' ナイト')]
            for s in SYMBOLS:
                r = by_key[name, s]
                cells += [money(r['campaign_profit']), money(-r['campaign_loss']), money(r['net'])]
            rows.append(cells)
        total = result['periods']['全30']
        rows.append(['全30合計']+[money(n) for s in SYMBOLS for n in
                    (total[s]['campaign_profit'], -total[s]['campaign_loss'], total[s]['net'])])
        heads = ['セッション', 'TOPIX 利益', 'TOPIX 損失', 'TOPIX 収支', '日経 利益', '日経 損失', '日経 収支']
        blocks.append('<details><summary>'+identifier+'：全30セッションの損益</summary><p class="note">'+
                      html.escape(explain(configs[identifier]))+'</p>'+table(heads, rows, 'sessions')+'</details>')
    all_blocks = []
    for model, model_label in [('observed', '観測現在値で約定'), ('specified', '指定線約定の感度確認')]:
        for s in SYMBOLS:
            rows = []
            for item in analysis['比較'][model]:
                v = item['商品別'][s]
                rows.append([item['id'], html.escape(configs[item['id']]['name']), money(v['net']),
                    percent(v['campaign_profit_share']), f'{v["positive_sessions"]}/30',
                    money(-v['max_drawdown']), str(v['campaigns']), money(-v['fees'])])
            all_blocks.append('<h3>'+model_label+'・'+LABELS[s]+'</h3>'+table(
                ['手法', '変更', '収支', '利益割合', '黒字場', '最大下落', '回数', '手数料'], rows))
    document = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>狭いトレールと再エントリーの結果</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#10151e;color:#e7edf6;font:16px/1.7 system-ui,"Yu Gothic UI",Meiryo,sans-serif}main{max-width:1160px;margin:auto;padding:28px 22px 60px}h1{font-size:29px;line-height:1.45}h2{font-size:20px}h3{font-size:17px}.lead{border-left:4px solid #81b6ff;padding-left:16px;font-size:19px}.note{font-size:13px;color:#b7c6d8}.caution{color:#f4ce83}section,details{background:#18222f;border:1px solid #344459;border-radius:10px;padding:17px;margin:20px 0}summary{cursor:pointer;font-weight:650}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th,td{padding:9px;border-bottom:1px solid #344459;text-align:right;white-space:nowrap}th:first-child{text-align:left}tbody th{font-weight:500}.gain{color:#75ddb5}.loss{color:#ff99a4}a{color:#87bdff}.sessions{font-size:13px}details[open] summary{margin-bottom:14px}@media(max-width:650px){main{padding:16px 12px 40px}h1{font-size:23px}.lead{font-size:17px}section,details{padding:12px}}
</style></head><body><main>
<!--
[コンポーネント概要]
#conclusion は狭い出口と再参加を試した結論を示す。
#comparison は同じ商品内の基準と比較候補の料金後成績を示す。
#case は問題になった9月24日ナイトの収支を比較する。
#frequency は同じ狭幅で再参加条件だけを変えた結果を示す。
#sessions は必要なときだけ開く全セッション損益。
#all は全条件・二つの約定仮定の全成績。外部通信は行わない。
-->
<p class="note">00082 · E01_G_Uの出口と再参加を__COUNT__条件で比較</p>
<h1 id="conclusion">__TITLE__</h1><p class="lead">__LEAD__</p>
<p>__EXPLAIN__</p><p class="caution">__COMMENT__</p>
<section id="comparison"><h2>基準との比較</h2>__SUMMARY__
<p class="note">2026/09/21デイ〜10/09ナイト、全30場。手数料後・観測現在値での仮想約定。TOPIXミニ5枚／日経マイクロ10枚で新規、追加なし。全て場内返済。米国現物開始前後15分は静観。</p>
<p class="note">利益・損失は新規から全返済までを1組として集計。金額利益割合＝利益÷（利益＋損失）。最大下落は保有中の評価損益も含む資産の減少。</p></section>
<section id="case"><h2>問題になった9月24日ナイト</h2>__CASE__<p class="note">__CASE_NOTE__</p></section>
<section id="frequency"><h2>利確後に早く入り直すとどうなるか</h2>__FREQUENCY__<p class="note">__FREQUENCY_NOTE__</p></section>
<div id="sessions">__SESSIONS__</div>
<details id="all"><summary>全__COUNT__条件と指定線約定の成績を開く</summary>
<p class="note">入口条件は共通。待ち時間を短縮しても、自動的にすぐ再建てするのではなく、新しい準備と反発・反落確認を要求します。参考順は両商品それぞれの収支÷最大下落の小さい方。商品間の金額は合算しません。</p>__ALL__</details>
<footer class="note">保存済みの既知データによる比較です。後半も未見検証ではありません。ラージの保存価格を小型商品の倍率で評価し、売買気配差・小型商品の約定差・固定5秒遅延は含めていません。<br><a href="README.md">読む順序と再現方法</a> ／ <a href="公開会計.json">全条件の会計</a></footer>
</main></body></html>'''
    replacements = dict(COUNT=str(len(configs)), TITLE=html.escape(title), LEAD=html.escape(lead), EXPLAIN=html.escape(selected+'：'+explain(configs[selected])),
        COMMENT=html.escape(comment), SUMMARY=summary, CASE=case_table, CASE_NOTE=html.escape(custom['夜間の説明']),
        FREQUENCY=frequency_table, FREQUENCY_NOTE=html.escape(custom['再参加の説明']),
        SESSIONS=''.join(blocks), ALL=''.join(all_blocks))
    for key, value in replacements.items():
        document = document.replace('__'+key+'__', value)
    assert '__TITLE__' not in document
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / MAIN).write_text(document, encoding='utf-8')
    accounting = dict(主約定='observed', 比較候補=selected, 比較結果=analysis,
        各結果={m: {i: dict(config=v['config'], rows=v['rows'], periods=v['periods']) for i, v in values.items()}
               for m, values in results.items()}, 仕様=fixed['specification'],
               追加検証=extra.get('specification', extra.get('仕様')) if extra else None)
    (PUBLIC / '公開会計.json').write_text(json.dumps(accounting, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')
    (PUBLIC / 'README.md').write_text(f'''# 狭いトレールと再エントリーの比較

最初に [{MAIN}]({MAIN}) を開いてください。結論と基準比較を先頭に置き、全30場と全{len(configs)}条件は折り畳みで掲載しています。

1. 主HTMLの結論と比較表。
2. 必要なら全30セッション損益・全{len(configs)}条件を開く。
3. 数値の再利用は [公開会計.json](公開会計.json)。実装と再現資料は `../../work/wave_v86`。

既存00081の戦略と結果は変更していません。現在セッション取得・実注文は行っていません。

再現コマンド（プロジェクトルート）:

```text
python -X utf8 work/wave_v86/research.py --run
python -X utf8 work/wave_v86/phase2/research.py --run
python -X utf8 work/wave_v86/analysis/analyze.py
python -X utf8 work/wave_v86/report/build.py
```
''', encoding='utf-8')
    proof = dict(全合格=True, 条件数=len(configs), 約定仮定数=2, 口座数=120*len(configs), 詳細表示=displayed,
        比較候補=selected, 両商品四指標改善=improved,
        公開SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PUBLIC.iterdir() if p.is_file()})
    (HERE / '表示照合.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(PUBLIC / MAIN)


if __name__ == '__main__':
    main()
