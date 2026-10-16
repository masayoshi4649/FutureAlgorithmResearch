"""日々の赤字抑制を最優先に、短い説明と全条件の全セッション損益を表示する。"""

import argparse
from html import escape
import json
from pathlib import Path

import base


HERE = Path(__file__).resolve().parent
FOLDER = '00100_支持境界と利益追尾による毎場の損失抑制'
TITLE = '支持境界と利益追尾の説明と全セッション損益.html'
SYMBOLS = ('TOPIX', 'NK225')


def yen(value: float) -> str:
    """
    機能: 手数料後の円額を三桁区切りにする。
    引数: value(float)は円額。
    返り値: strは整数円表示。微小な計算誤差を丸める。
    """
    return '0' if abs(value) < .5 else f'{value:,.0f}'


def percent(value: float | None) -> str:
    """
    機能: 金額割合と未定義を区別して表示する。
    引数: value(float|None)は割合。
    返り値: strは百分率又は未定義記号。
    """
    return '—' if value is None else f'{value*100:.1f}%'


def money(value: float) -> str:
    """
    機能: 金額の符号と色を一致させる。
    引数: value(float)は費用後の増減。
    返り値: strは数値表示のHTML。
    """
    cls = 'positive' if value > 1e-5 else 'negative' if value < -1e-5 else 'neutral'
    return f'<span class="{cls}">{yen(value)}</span>'


def description(config: dict) -> str:
    """
    機能: 入口と出口及び同時運用の配分を簡単な日本語で説明する。
    引数: config(dict)は結果前に固定した条件。
    返り値: strは一条件の短い説明。
    """
    if config['kind'] == 'previous':
        return '旧対照。両市場の5分進行を確認して入る。1枚。'
    if config['kind'] == 'portfolio':
        top, nk = config['allocations']['TOPIX'], config['allocations']['NK225']
        entry = f'追従Cと反転Rを別々に動かす。TOPIXは{top[0]}対{top[1]}枚、日経は{nk[0]}対{nk[1]}枚'
    elif config['family'] == 'U':
        entry = '追従Cと反転Rを自動選択。方向が競合したら見送る。1枚'
    else:
        entry = ('板の活動後に新しい価格が定着した方向へ入る' if config['family'] == 'C'
                 else '板が動いても進めず、反対の価格が定着した方向へ入る')+'。1枚'
    gate = config['gate']
    if gate == 'OWN':
        entry += '。自己市場だけで判定'
    else:
        window = gate[1:].replace('T2', '')
        confirmation = '同方向を確認' if gate.startswith('P') else '反対・不明・曖昧を除外'
        if gate.endswith('T2'):
            confirmation += '、2呼値以上'
        entry += f'。相手市場の約{window}秒の気配変化で{confirmation}'
    ident = config['exit_id']
    if ident == 'O':
        exit_text = '旧出口：広い追尾と最大30分'
    elif ident.startswith('B'):
        exit_text = f'支持価格の{ident[1:]}呼値外で返済、利益は広く追尾'
    else:
        exit_text = f'支持価格の{ident[1:]}呼値外で返済、費用回収後は{ident[1:]}呼値で利益追尾'
    return entry+'。'+exit_text+'。'


def comparison(values: dict, assessment: dict, identifiers: list[str]) -> str:
    """
    機能: 両商品別に赤字頻度、金額利益割合、損失規模と依存性を並べる。
    引数: values/assessment(dict)、identifiers(list[str])は会計と表示条件。
    返り値: strは比較表のHTML。商品間の円額は相殺しない。
    """
    rows = []
    for ident in identifiers:
        cells = [f'<th><a href="#{escape(ident)}">{escape(ident)}</a></th>']
        result = assessment['results'][ident]
        for symbol in SYMBOLS:
            total, stable = values[ident]['periods']['全32'][symbol], values[ident]['stability']['全32'][symbol]
            cells += [f'<td>{money(total["net"])}</td>',
                f'<td>{stable["losing_sessions"]}/{stable["active_sessions"]}</td>',
                f'<td>{percent(total["profit_share"])}</td>',
                f'<td>{yen(stable["worst_session_loss_yen"])}</td>',
                f'<td>{money(stable["without_best_session_net"])}</td>']
        status = '採用基準を達成' if result['adoption_achieved'] else '比較候補' if result['eligible'] else '候補資格未達'
        if ident == 'OLD_G0':
            status = '旧対照'
        cells += ['<td>'+status+'</td>']
        rows.append('<tr>'+''.join(cells)+'</tr>')
    headings = '<th>収支 円</th><th>赤字/活動</th><th>金額利益割合</th><th>最大赤字 円</th><th>最大勝ち除外 円</th>'
    return '<div class="scroll"><table class="comparison"><thead><tr><th rowspan="2">手法</th><th colspan="5">TOPIXミニ</th><th colspan="5">日経マイクロ</th><th rowspan="2">判定</th></tr><tr>'+headings*2+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def session_table(value: dict, sessions: list[str], extra_rows: list[dict]) -> str:
    """
    機能: 全セッションの相殺前利益・損失・収支と決済枚数を表示する。
    引数: value(dict)、sessions(list[str])、extra_rows(list[dict])は旧32と別確認の会計。
    返り値: strは全場表。追加場と既知32合計を混ぜず併記する。
    """
    mapping = {(row['session'], row['symbol']): row for row in value['rows']+extra_rows}
    addition = sorted({row['session'] for row in extra_rows})
    body = []
    for session in sessions+addition:
        cls = ' class="extra"' if session in addition else ''
        label = session.replace('_Day', ' デイ').replace('_Night', ' ナイト')
        if session in addition:
            label += '〔別確認〕'
        cells = [f'<th scope="row">{escape(label)}</th>']
        for symbol in SYMBOLS:
            row = mapping[session, symbol]
            cells += [f'<td>{yen(row["profit"])}</td><td>{yen(row["loss"])}</td><td>{money(row["net"])}</td>',
                f'<td>{row["winning_lots"]}/{row["losing_lots"]}/{row["flat_lots"]}</td>']
        body.append('<tr'+cls+'>'+''.join(cells)+'</tr>')
    foot = '<tr><th>既知32場合計</th>'
    for symbol in SYMBOLS:
        row = value['periods']['全32'][symbol]
        foot += f'<td>{yen(row["profit"])}</td><td>{yen(row["loss"])}</td><td>{money(row["net"])}</td><td>{row["winning_lots"]}/{row["losing_lots"]}/{row["flat_lots"]}</td>'
    foot += '</tr>'
    if addition:
        foot += '<tr><th>追加を含む合計</th>'
        for symbol in SYMBOLS:
            rows = [row for row in value['rows']+extra_rows if row['symbol'] == symbol]
            summed = {key: sum(row[key] for row in rows) for key in ('profit', 'loss', 'net', 'winning_lots', 'losing_lots', 'flat_lots')}
            foot += f'<td>{yen(summed["profit"])}</td><td>{yen(summed["loss"])}</td><td>{money(summed["net"])}</td><td>{summed["winning_lots"]}/{summed["losing_lots"]}/{summed["flat_lots"]}</td>'
        foot += '</tr>'
    headings = '<th>利益 円</th><th>損失 円</th><th>収支 円</th><th>決済枚数 勝/負/零</th>'
    return '<div class="scroll"><table class="sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr><tr>'+headings*2+'</tr></thead><tbody>'+''.join(body)+'</tbody><tfoot>'+foot+'</tfoot></table></div>'


def build(audit_path: Path, extra_path: Path | None, extra_audit_path: Path | None) -> None:
    """
    機能: 独立検算済みの会計から、公開前の短いダークHTMLを生成する。
    引数: audit_path(Path)は全32監査、extra_path/extra_audit_path(Path|None)は追加会計と独立監査。
    返り値: None。新しい下書きへ保存し、公開案内はまだ変更しない。
    """
    result = base.read(HERE/'金融全32の結果.json')
    assessment = base.read(HERE/'安定性の全121判定.json')
    audit = base.read(audit_path)
    assert result['全合格'] and audit['全合格']
    assert base.digest(HERE/'金融全32の結果.json') in json.dumps(audit, ensure_ascii=False)
    values = {}
    for ident, item in result['results'].items():
        assert base.digest(base.ROOT/item['path']) == item['SHA256']
        values[ident] = base.read(base.ROOT/item['path'])
    extra = base.read(extra_path) if extra_path else {}
    if extra_path:
        assert extra_audit_path is not None and extra['全合格']
        extra_audit = base.read(extra_audit_path)
        assert extra_audit['全合格']
        assert base.digest(extra_path) in json.dumps(extra_audit, ensure_ascii=False)
        assert set(extra['cases']) == set(values)
    additions = extra.get('cases', {})
    adopted, ranking = assessment['adoption_candidates'], assessment['ranking']
    conclusion = ('採用基準を満たした候補：'+escape('、'.join(adopted))+ '。' if adopted else
        '今回の121条件では、両銘柄で日々の損失を抑え、金額利益80%を満たす採用手法は見つかりませんでした。')
    if not adopted and ranking:
        ident = ranking[0]
        score = assessment['results'][ident]['symbols']
        conclusion += f' 共通黒字の比較候補{escape(ident)}でも、赤字はTOPIX {score["TOPIX"]["losing_sessions"]}/{score["TOPIX"]["active_sessions"]}場、日経 {score["NK225"]["losing_sessions"]}/{score["NK225"]["active_sessions"]}場です。'
    first = ranking[:5]
    selected = first or ['U_P10_T2', 'C_OWN_O', 'C_OWN_B2', 'C_OWN_T2', 'R_OWN_T2']
    for ident in ('U_P10_T2', 'P50_P10_B2', 'P50_P10_T2'):
        if ident not in selected:
            selected.append(ident)
    if 'OLD_G0' not in selected:
        selected.append('OLD_G0')
    document = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>支持境界と利益追尾の損失抑制</title><style>
:root{color-scheme:dark;font-family:"Yu Gothic UI","Meiryo",sans-serif;background:#0c121d;color:#e7edf7}*{box-sizing:border-box}body{margin:0;line-height:1.7}main{max-width:1320px;margin:auto;padding:24px}h1{font-size:clamp(22px,4vw,32px)}h2{font-size:21px;margin-top:30px}a{color:#9acaff}.lead{background:#152337;border-left:4px solid #8abfff;padding:15px}.muted{color:#b4c3d9}.scroll{overflow:auto;border:1px solid #34445c;border-radius:8px}table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}th,td{padding:8px 11px;border-bottom:1px solid #304058;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1b2a41}tbody tr:nth-child(even){background:#142034}.extra{outline:1px solid #b98c44}.positive{color:#78dfb2}.negative{color:#ff949e}.neutral{color:#adbed5}details{margin:12px 0;padding:12px;background:#152033;border:1px solid #32415a;border-radius:8px}summary{cursor:pointer;font-weight:600;overflow-wrap:anywhere}a:focus-visible,summary:focus-visible{outline:3px solid #e6b46b;outline-offset:3px}footer{padding:24px 0;color:#aabbcf}@media(max-width:540px){main{padding:16px 10px}th,td{padding:7px 9px}}
</style></head><body><!--
[コンポーネント概要]
main は結論、毎場安定性の比較、手法の短い説明と全場損益をまとめます。
.scroll は幅のある比較表と全セッション表を横に閲覧する領域です。
details と summary は全121手法を一つずつ開くための説明領域です。
.positive、.negative、.neutral は収支の符号を表し、金額も併記します。
.extra は条件を変更せずに後から別検証した追加セッションを表します。
この資料は保存済みの会計だけを表示し、外部通信や注文を行いません。
--><main>'''
    document += '<h1>支持境界と利益追尾による損失抑制</h1><p class="lead">'+conclusion+'</p>'
    document += '<p><b>優先順位：</b>赤字セッションの頻度 → 損失規模 → 大勝ちを除いても残る利益。最大収益を順位に使いません。無取引は勝ちに数えません。</p>'
    document += '<h2>何を変えたか</h2><p><b>入口：</b>自己の板が準備を整えた時、相手市場の気配方向を確認。両市場に同じ板パターンが同時発生することまでは要求しません。<br><b>途中：</b>入口の根拠だった価格を固定し、その価格を破れば撤退。<br><b>出口：</b>Bは広い利益追尾、Tは費用回収後に2又は4呼値の利益追尾。B/Tは固定保有時間を設けず、場内で全返済します。</p>'
    document += '<p>追従Cと反転Rを別々に動かす配分も比較。TOPIXは2対8・5対5・8対2枚、日経は4対16・10対10・16対4枚です。両建ての含み損も全手数料も計算に含めます。</p>'
    document += '<h2>候補・主・配分・旧対照の比較</h2>'
    document += '<p class="muted">赤字/活動＝赤字場数/実取引場数。金額利益割合＝総利益/(総利益+総損失)。最大勝ち除外は、各商品の最大利益セッションを1つだけ除いた収支です。単一は1枚、配分型は合計TOPIX10枚・日経20枚です。</p>'
    document += comparison(values, assessment, selected)
    if additions:
        check_id = ranking[0] if ranking else assessment['primary']
        checked = {row['symbol']: row for row in additions[check_id]['rows']}
        document += '<p><b>追加の10月13日デイ：</b>条件を変更せず別確認した'+escape(check_id)+'は、TOPIX '+money(checked['TOPIX']['net'])+'円・日経 '+money(checked['NK225']['net'])+'円。従来32場の順位を追加日に合わせて選び直していません。各手法の表に追加分と33場合計を掲載しました。</p>'
    document += '<p>候補資格：各商品で16/32場以上・20完結取引以上、合計黒字、平均利益/平均損失が1超。採用基準はさらに両商品で金額利益80%、旧対照より赤字率・下方偏差・最大赤字が非悪化、最大勝ち除外後も黒字です。</p>'
    document += '<h2>損失が減らなかった理由</h2><p>同じ入口のC_OWNで広い追尾B2を狭い追尾T2へ変えると、TOPIXの取引は243→436回。平均の利益は18,501→1,177円、平均の損失は1,938→1,896円でした。損失幅はほぼ同じなのに、勝ちを小さくし、再参加を増やしています。T2の損失はTOPIX291件中287件・日経151件中149件が利益追尾の発動前でした。</p>'
    document += '<p>名目「2呼値の追尾」と、入口から初期停止線までの距離は別です。この距離の中央値は両銘柄4呼値。次は初期の実リスクと利益追尾幅を独立に扱い、入口の優位性も確認する必要があります。</p>'
    document += '<h2>各手法の全セッション損益</h2><p class="muted">手法名を押して全場を表示。利益・損失は取引ごとの手数料後金額を相殺前に集計。枚数は利益/損失/零になった決済枚数で、同時保有枚数ではありません。</p>'
    order = list(dict.fromkeys([assessment['primary'], *ranking, *values]))
    for ident in order:
        value, verdict = values[ident], assessment['results'][ident]
        details = []
        for symbol, label in (('TOPIX', 'TOPIXミニ'), ('NK225', '日経マイクロ')):
            total, stable = value['periods']['全32'][symbol], value['stability']['全32'][symbol]
            ratio = '—' if total['payoff'] is None else f'{total["payoff"]:.2f}'
            details.append(f'{label}：黒字{stable["positive_sessions"]}・赤字{stable["losing_sessions"]}・無取引{stable["no_trade_sessions"]}場。平均利益/平均損失 {ratio}倍。')
        reasons = ('採用基準を達成。' if verdict['adoption_achieved'] else
            '両銘柄で合計黒字。ただし毎場の安定性と利益80%の採用基準は未達。' if verdict['eligible'] else
            '両銘柄共通の採用基準は未達。')
        document += f'<details id="{escape(ident)}"><summary>{escape(ident)}</summary><p>{escape(description(value["config"]))}</p><p>{"<br>".join(details)}</p><p class="muted">{escape(reasons)}</p>'
        document += session_table(value, result['sessions'], additions.get(ident, {}).get('rows', []))+'</details>'
    document += '<details><summary>約定・手数料・検証範囲</summary><p>ラージの板を参照し、その次の正常気配でミニ・マイクロも同じ価格で仮想約定。買いはask・売りはbid。停止線の価格で確実に返済できるとは仮定しません。片道1枚料はTOPIXミニ41.8円・日経マイクロ11円、注文合計の1円未満を切り捨て。5秒最悪約定の追加悪化は今回含めません。全建玉を場内で返済します。</p><p>既知の32場で121条件を比較した結果であり、将来の利益の証明ではありません。表示数量の減少から約定と取消を識別できず、出来高方向も代理です。受信時刻がなく、二市場の先後には価格時刻を代用しています。比較用の配置予算による損失単位は、同じ実リスクを意味しません。従来検証と同じ開始・返済境界を使い、デイは15:34、ナイトは翌5:49に全返済判断します。</p></details>'
    document += '''<footer><a href="公開会計.json">全会計</a>・<a href="README.md">読む順序</a></footer></main><script>
/**
 * 比較表から選んだ手法の全場表を開きます。
 *
 * @function reveal
 * 引数: なし。現在のページ内参照を使用します。
 * @returns {void} 返り値はありません。対象の説明領域を開きます。
 */
function reveal(){const id=decodeURIComponent(location.hash.slice(1));const target=document.getElementById(id);if(target instanceof HTMLDetailsElement){target.open=true;target.scrollIntoView({block:'start'});}}
window.addEventListener('hashchange',reveal);reveal();
</script></body></html>'''
    target = HERE/'report/preview'
    assert not target.exists()
    target.mkdir(parents=True)
    (target/TITLE).write_text(document, encoding='utf-8')
    public = dict(sessions=result['sessions'], values=values, assessment=assessment, extra=extra,
        extra_audit_SHA256=base.digest(extra_audit_path) if extra_audit_path else None,
        formal_result_SHA256=base.digest(HERE/'金融全32の結果.json'), audit_SHA256=base.digest(audit_path))
    (target/'公開会計.json').write_text(json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    proof = dict(全合格=True, folder=FOLDER, title=TITLE, preview=str((target/TITLE).relative_to(base.ROOT)),
        HTML_SHA256=base.digest(target/TITLE), 会計SHA256=base.digest(target/'公開会計.json'), 条件数=121,
        financial_result_SHA256=base.digest(HERE/'金融全32の結果.json'), audit_SHA256=base.digest(audit_path))
    (HERE/'report/生成結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('121手法の全場表を公開前HTMLへ保存。', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--extra', type=Path)
    parser.add_argument('--extra-audit', type=Path)
    args = parser.parse_args()
    build(args.audit, args.extra, args.extra_audit)
