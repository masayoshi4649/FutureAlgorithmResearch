"""変更後の三基準と保存代表の全場収支を、短い暗色HTMLへ表示する。"""

import hashlib
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
SOURCE = HERE/'保存全候補の65比率と赤字頻度及び平均黒字補填力.json'
TITLE = '変更後65%基準の判定と全セッション損益'
VETO = 'E01_TRADE_W60_VETO_D0_P1L8'
CONFIRM = 'E01_TRADE_W60_CONFIRM_D0_P1L8'
KNOWN = 'E01_TRADE_W60_KNOWN_VETO_D0_P1L8'


def money(value: float | None) -> str:
    """
    機能: 円額を丸めて表示する。
    引数: value（float | None）元会計の円額又は未定義値。
    返り値: str。整数の円額、又は「—」。
    """
    return '—' if value is None else f'{value:,.0f}'


def percent(value: float | None) -> str:
    """
    機能: 金額割合と赤字割合を小数1桁の百分率へ変える。
    引数: value（float | None）0〜1の割合又は未定義値。
    返り値: str。百分率、又は「未定義」。
    """
    return '未定義' if value is None else f'{value*100:.1f}%'


def currency_cell(value: float, loss: bool = False) -> str:
    """
    機能: 会計の円額を正負色付きセルへ表示する。
    引数: value（float）元会計、loss（bool）正数で記録した損失か。
    返り値: str。符号を正しく保つHTMLのtd。
    """
    signed = -value if loss else value
    color = 'negative' if signed < 0 else 'positive' if signed > 0 else ''
    return f'<td class="{color}">{money(signed)}</td>'


def summary_row(symbol: str, case: dict) -> str:
    """
    機能: 金額65・赤字20・最大赤字と平均黒字の三条件を独立に表示する。
    引数: symbol（str）商品、case（dict）全場と上位3除外の保存再集計。
    返り値: str。商品ごとの指標と達否の一行HTML。
    """
    full, tail = case['full'], case['without_top3']
    markers = ['○' if value else '×' for value in full['tests'].values()]
    return (f'<tr><th>{symbol}</th><td>{percent(full["profit_share"])}</td>'
            f'<td>{percent(tail["profit_share"])}</td>'
            f'<td>{full["red"]}/{full["sessions"]}（{percent(full["red_all"])}）</td>'
            f'<td>{full["red"]}/{full["active"]}（{percent(full["red_active"])}）</td>'
            f'<td>{money(full["mean_green"])}</td><td class="negative">{money(full["worst_red"])}</td>'
            f'<td>{full["green"]}/{full["red"]}/{full["no_trade"]}</td>'
            f'<td>{" ／ ".join(markers)}</td></tr>')


def session_table(cases: dict, ids: dict) -> str:
    """
    機能: 選んだ二商品の全33場の利益・損失・差引収支と総計を表示する。
    引数: cases（dict）再集計全候補、ids（dict[str,str]）各商品の表示ID。
    返り値: str。表HTML。無取引行は実測ゼロのまま扱う。
    """
    indices = {s: {r['session']: r for r in cases[i]['symbols'][s]['rows']} for s, i in ids.items()}
    sessions = sorted(indices['TOPIX'])
    assert set(indices['NK225']) == set(sessions) and len(sessions) == 33
    rows = []
    for session in sessions:
        label = session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
        row = f'<tr><th>{label}</th>'
        for symbol in ('TOPIX', 'NK225'):
            r = indices[symbol][session]
            row += currency_cell(r['profit'])+currency_cell(r['loss'], True)+currency_cell(r['net'])
        rows.append(row+'</tr>')
    total = '<tr class="total"><th>全33場合計</th>'
    for symbol in ('TOPIX', 'NK225'):
        r = cases[ids[symbol]]['symbols'][symbol]['full']
        total += currency_cell(r['profit'])+currency_cell(r['loss'], True)+currency_cell(r['net'])
    rows.append(total+'</tr>')
    return ('<div class="scroll"><table class="sessions"><thead><tr><th rowspan="2">セッション</th>'
            '<th colspan="3">TOPIXミニ（円）</th><th colspan="3">日経マイクロ（円）</th></tr><tr>'
            '<th>利益</th><th>損失</th><th>収支</th><th>利益</th><th>損失</th><th>収支</th>'
            '</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>')


def main() -> None:
    """
    機能: 保存会計の再集計から主三条件・大勝ち除外・全場表を公開する。
    引数: なし。保存済み小会計を使用し、金融・原板・APIへ接続しない。
    返り値: None。HTMLと表示に使った会計JSONを保存する。
    """
    data = json.loads(SOURCE.read_text(encoding='utf-8'))
    assert data['全合格'] and not data['summary']['both_full_pass']
    cases = data['cases']
    pairs = {
        '代表': dict(label='従来の銘柄別代表', ids=dict(TOPIX=VETO, NK225=CONFIRM)),
        '共通VETO': dict(label='両銘柄共通：逆票を見送る', ids=dict(TOPIX=VETO, NK225=VETO)),
        '共通CONFIRM': dict(label='両銘柄共通：同方向票を要求する', ids=dict(TOPIX=CONFIRM, NK225=CONFIRM)),
        '共通KNOWN': dict(label='両銘柄共通：観測不足と逆票を見送る', ids=dict(TOPIX=KNOWN, NK225=KNOWN)),
    }
    options, sections = [], []
    for key, pair in pairs.items():
        options.append(f'<option value="{key}">{pair["label"]}</option>')
        summary = ''.join(summary_row(s, cases[i]['symbols'][s]) for s, i in pair['ids'].items())
        condition = '<br>'.join(f'{s}：<code>{html.escape(i)}</code>' for s, i in pair['ids'].items())
        sections.append(
            f'<section data-pair="{key}" hidden><h2>{pair["label"]}</h2><p class="note">{condition}</p>'
            '<div class="scroll"><table class="metrics"><thead><tr><th>商品</th><th>金額利益割合</th>'
            '<th>大勝ち3場除外</th><th>赤字／全場</th><th>赤字／活動場</th><th>平均黒字額</th><th>最大赤字額</th>'
            '<th>黒字／赤字／無取引</th><th>65%／20%／補填力</th></tr></thead><tbody>'+summary+'</tbody></table></div>'
            '<p>入口は元E01の方向判断と追跡新規。直近60代理秒の取引更新で採否を変え、次正常気配で建てます。'
            '途中は元の部分返済を維持。場の手数料後清算損益が利益2,500円／1,000円、又は損失20,000円／8,000円へ達すると、'
            '次正常気配で全返済してその場を終えます。</p>'
            +session_table(cases, pair['ids'])+'</section>')
    # ----------------------------------------
    # 条件変更は売買結果を変えず、平均と損失の比較を追加する。
    css = '*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui}main{max-width:1350px;padding:24px 20px;margin:auto}h1{font-size:26px}h2{font-size:20px}a{color:#8fbeff}.note{color:#aab9d0}code{overflow-wrap:anywhere}select{width:100%;padding:11px;background:#18263b;color:#dce4f2;border:1px solid #72819a;font:inherit}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:14px}table.metrics{min-width:1150px}table.sessions{min-width:780px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}th:first-child{text-align:left}thead th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{background:#1d2c43!important;font-weight:bold}section{margin-top:24px}section[hidden]{display:none}@media(max-width:600px){main{padding:16px 12px}h1{font-size:22px}}'
    script = '''/**
 * 保存会計の比較と全場表の表示を切り替える。
 * @param {string} key - 表示する比較名。
 * @returns {undefined} 表示だけを更新する。金融・通信は行わない。
 */
function showPair(key){for(const node of document.querySelectorAll('[data-pair]'))node.hidden=node.dataset.pair!==key;document.getElementById('pair').value=key;}
document.getElementById('pair').addEventListener('change',event=>showPair(event.target.value));showPair('代表');'''
    document = ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{TITLE}</title><style>{css}</style></head><body><!--\n[コンポーネント概要]\n#pair は比較条件を選びます。\n[data-pair] は選択中の代表又は共通条件を表示します。\n.metrics は三基準の達否、.sessions は全33場と合計、.scroll は表の横スクロールを管理します。\n--> <main>'
        f'<h1>{TITLE}</h1><p><b>両銘柄で目標を満たす手法は、まだありません。</b>'
        '00103の同じ33場を比較できる357条件IDを再判定しました。理想的な旧現在値約定1条件は別枠です。再集計で売買は再実行していません。</p>'
        '<p>目標は<b>金額利益割合65%以上・赤字場20%以下・最大赤字を平均黒字1場で補える</b>こと。'
        '従来代表の最大赤字は平均黒字のTOPIX4.7倍・日経4.9倍で、ここが未達です。</p>'
        '<p class="note">単独で数式を満たした例も、TOPIXは黒字2場・赤字4場・無取引27場、日経は黒字1場のみ、又は黒字3場・赤字4場・無取引26場です。'
        '大勝ち上位3場を除くと単独合格も0件でした。これらを安定利益の成功には数えません。</p>'
        '<label for="pair">比較する条件</label><select id="pair">'+''.join(options)+'</select>'+''.join(sections)
        +'<p class="note">初回TOPIXミニ5枚／日経マイクロ10枚、片方向上限10枚／20枚。手数料とラージ気配差込み、全玉場内返済。'
        '平均黒字額は黒字場の差引収支の平均。金額利益割合は各完結取引群の利益÷（利益＋損失）で、資金利回りや場割合の単純平均ではありません。'
        '無取引は黒字に数えません。比較ID・同じ会計の派生は独立した成功標本ではありません。未知確認は0です。</p>'
        '<p><a href="../../work/wave_v106/new_goal/保存全候補の65比率と赤字頻度及び平均黒字補填力.json">全候補の再判定根拠</a> · '
        '<a href="E01で残った損失と改善の具体例.md">具体的な損失箇所</a> · <a href="../調査方針.md">変更後の調査方針</a> · <a href="README.md">読む順序</a></p>'
        '</main><script>'+script+'</script></body></html>')
    payload = dict(全合格=True, pairs=pairs,
        cases={i: cases[i] for i in (VETO, CONFIRM, KNOWN)},
        全候補判定=data['summary'], 集計元=SOURCE.relative_to(ROOT).as_posix(),
        集計元SHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        新金融再生=0, HTML生成sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (PUBLIC/'65基準の公開会計.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    (PUBLIC/(TITLE+'.html')).write_text(document,encoding='utf-8',newline='\n')
    print('変更後三基準・4比較・全33場を公開。金融再生0。')


if __name__ == '__main__':
    main()
