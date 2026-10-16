"""19条件の全32損益と赤字頻度を、短い日本語のダークHTMLへまとめる。"""

import argparse
from html import escape
import json
from pathlib import Path
import runpy


HERE = Path(__file__).resolve().parent
RESEARCH = runpy.run_path(str(HERE/'research.py'))
ROOT = RESEARCH['ROOT']
SYMBOLS = ('TOPIX', 'NK225')
FOLDER = '00099_板の定着と進行失敗の入口検証'
TITLE = '板の定着と進行失敗の説明と全セッション損益.html'


def yen(value: float) -> str:
    """
    機能: 手数料後金額を整数円で読みやすくする。
    引数: value(float)は円額。
    返り値: strは三桁区切りの金額。
    """
    return '0' if abs(value) < .5 else f'{value:,.0f}'


def percent(value: float | None) -> str:
    """
    機能: 金額割合又は無活動の未定義を表示する。
    引数: value(float|None)は0～1の割合。
    返り値: strは割合又は未定義記号。
    """
    return '—' if value is None else f'{value*100:.1f}%'


def number(value: float, suffix: str = '') -> str:
    """
    機能: 色と符号で費用後の増減を表す。
    引数: value(float)、suffix(str)は金額と単位。
    返り値: strは安全な数値表示のHTML。
    """
    color = 'positive' if value > 1e-5 else 'negative' if value < -1e-5 else 'neutral'
    return f'<span class="{color}">{yen(value)}{escape(suffix)}</span>'


def score(value: dict) -> tuple:
    """
    機能: 最大収益を使わず、悪い商品の赤字率と損失規模を優先する。
    引数: value(dict)は一条件の全32結果。
    返り値: tupleは昇順評価。活動不足は資格で別に除外する。
    """
    stable = value['stability']['全32']
    whole = value['periods']['全32']
    return (max(stable[s]['losing_active_rate'] if stable[s]['losing_active_rate'] is not None else 1. for s in SYMBOLS),
        max(stable[s]['downside_rms_units'] if stable[s]['downside_rms_units'] is not None else 1e100 for s in SYMBOLS),
        max(stable[s]['worst_session_loss_units'] for s in SYMBOLS),
        -min(whole[s]['profit_share'] if whole[s]['profit_share'] is not None else -1. for s in SYMBOLS), value['config']['id'])


def qualified(value: dict) -> bool:
    """
    機能: 活動不足又は片方の赤字を安定候補から除く。
    引数: value(dict)は一条件。
    返り値: boolは両商品の活動・黒字・損小利大を満たしたか。
    """
    for symbol in SYMBOLS:
        aggregate = value['periods']['全32'][symbol]
        if not value['stability']['全32'][symbol]['activity_adequate'] or aggregate['net'] <= 0:
            return False
        if aggregate['loss'] > 0 and (aggregate['payoff'] is None or aggregate['payoff'] <= 1):
            return False
    return True


def description(config: dict) -> str:
    """
    機能: 条件の入口思想と省略部品又は実配分を短く説明する。
    引数: config(dict)は固定条件。
    返り値: strは日本語説明。
    """
    ident = config['id']
    if config['kind'] == 'previous':
        return '旧対照。両市場の5分進行を確認して入る。1枚、増玉なし。'
    if config['kind'] == 'union':
        return '定着C1と反転R1を自動判定。同方向なら1枚、反対方向なら入らない。'
    if config['kind'] == 'portfolio':
        top, nk = config['allocations']['TOPIX'], config['allocations']['NK225']
        return f'C1とR1を別々に動かす。TOPIXは{top[0]}対{top[1]}枚、日経は{nk[0]}対{nk[1]}枚。'
    base = '活動後に新価格が維持された方向へ入る' if config['family'] == 'C' else '活動したのに進めず、反対の価格が維持された方向へ入る'
    omitted = {'PRICE': '価格だけで判定', 'VOLUME': '価格と出来高で判定', 'SUPPLY': '価格と表示数量で判定', 'OWN': '自己市場だけで判定'}
    tag = ident.split('_')[-1]
    detail = omitted.get(tag, f"価格・出来高・表示数量を確認。活動強度{config['strength']:g}倍")
    if config['use_peer']:
        detail += '、相手市場も同じ方向'
    return base+'。'+detail+'。各商品1枚。'


def table_rows(value: dict, sessions: list[str]) -> str:
    """
    機能: 全場の相殺前利益・損失と決済勝敗枚数を同じ順で表示する。
    引数: value(dict)、sessions(list[str])は一条件会計と全場順序。
    返り値: strは全32行と全体合計のHTML。
    """
    rows = {(row['session'], row['symbol']): row for row in value['rows']}
    parts = []
    for session in sessions:
        cells = [f'<th scope="row">{escape(session.replace("_Day", " デイ").replace("_Night", " ナイト"))}</th>']
        for symbol in SYMBOLS:
            row = rows[session, symbol]
            cells += [f'<td>{yen(row["profit"])}</td>', f'<td>{yen(row["loss"])}</td>',
                      f'<td>{number(row["net"])}</td>', f'<td>{row["winning_lots"]}/{row["losing_lots"]}</td>']
        parts.append('<tr>'+''.join(cells)+'</tr>')
    foot = '<th>32場合計</th>'
    for symbol in SYMBOLS:
        row = value['periods']['全32'][symbol]
        foot += f'<td>{yen(row["profit"])}</td><td>{yen(row["loss"])}</td><td>{number(row["net"])}</td><td>{row["winning_lots"]}/{row["losing_lots"]}</td>'
    return '<tbody>'+''.join(parts)+'</tbody><tfoot><tr>'+foot+'</tr></tfoot>'


def build(audit_path: Path) -> None:
    """
    機能: 完了会計と独立監査を読んで、公開前HTMLと会計を保存する。
    引数: audit_path(Path)は全新台帳と集計の独立検算証跡。
    返り値: None。公開先や既存作業は変更せず、目視前の下書きを作る。
    """
    read, digest, save = (RESEARCH[name] for name in ('read', 'digest', 'save'))
    result = read(HERE/'金融全32の結果.json')
    audit = read(audit_path)
    assert result['全合格'] and audit['全合格']
    assert digest(HERE/'金融全32の結果.json') in audit['資料SHA256'].values()
    prefix_path = HERE/'engine/実金融の先頭4親と接頭不変.json'
    prefix = read(prefix_path)
    assert prefix['全合格'] and prefix['対象先頭親数'] == 4
    values = []
    for ident, item in result['results'].items():
        assert digest(ROOT/item['path']) == item['SHA256']
        value = read(ROOT/item['path'])
        assert value['config']['id'] == ident and len(value['rows']) == 64
        values.append(value)
    eligible = sorted((value for value in values if qualified(value)), key=score)
    target = [value['config']['id'] for value in eligible if all(value['periods']['全32'][s]['profit_share'] >= .8 for s in SYMBOLS)]
    conclusion = ('安定性の候補は '+escape('、'.join(value['config']['id'] for value in eligible))+ '。' if eligible else '今回の19条件では、両銘柄で日々の安定収益を支える採用候補はありません。')
    conclusion += ' 金額利益80%の両銘柄達成：'+('、'.join(target) if target else 'なし')+'。'
    summary = []
    for value in values:
        ident = value['config']['id']
        cells = [f'<th scope="row"><a href="#{escape(ident)}">{escape(ident)}</a></th>']
        for symbol in SYMBOLS:
            row, stable = value['periods']['全32'][symbol], value['stability']['全32'][symbol]
            cells += [f'<td>{number(row["net"])}</td>', f'<td>{stable["losing_sessions"]}/{stable["active_sessions"]}</td>', f'<td>{percent(row["profit_share"])}</td>']
        summary.append('<tr>'+''.join(cells)+'</tr>')
    sections = []
    for value in values:
        ident = value['config']['id']
        chunks = []
        for symbol, label in (('TOPIX', 'TOPIXミニ'), ('NK225', '日経マイクロ')):
            row, stable = value['periods']['全32'][symbol], value['stability']['全32'][symbol]
            payoff = '—' if row['payoff'] is None else f'{row["payoff"]:.2f}'
            chunks.append(f'{label}：黒字{stable["positive_sessions"]}場・赤字{stable["losing_sessions"]}場・無取引{stable["no_trade_sessions"]}場。最大赤字{yen(stable["worst_session_loss_yen"])}円、平均利益/平均損失{payoff}倍。')
        sections.append(f'<details id="{ident}"><summary>{ident} — {escape(description(value["config"]))}</summary><p>{"<br>".join(chunks)}</p><div class="scroll"><table><thead><tr><th rowspan="2">セッション</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr><tr>'+''.join('<th>利益 円</th><th>損失 円</th><th>収支 円</th><th>枚数 勝/負</th>' for _ in SYMBOLS)+'</tr></thead>'+table_rows(value, result['sessions'])+'</table></div></details>')
    document = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>板の定着と進行失敗の入口検証</title><style>
:root{color-scheme:dark;font-family:"Yu Gothic UI","Meiryo",sans-serif;background:#0c121d;color:#e7edf7}*{box-sizing:border-box}body{margin:0;line-height:1.7}main{max-width:1240px;margin:auto;padding:28px 24px}h1{font-size:clamp(23px,4vw,32px)}h2{font-size:22px;margin-top:32px}p{max-width:1000px}a{color:#94c9ff}a:focus-visible,summary:focus-visible{outline:3px solid #e6b46b;outline-offset:3px}.lead{background:#152337;border-left:4px solid #7ab9ff;padding:16px}.muted{color:#b2c0d4}.scroll{overflow:auto;border:1px solid #34445c;border-radius:8px}table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}th,td{border-bottom:1px solid #29384e;padding:9px 12px;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1a2940}tbody tr:nth-child(even){background:#121e30}.positive{color:#78dfb2}.negative{color:#ff949e}.neutral{color:#adbed5}details{margin:14px 0;padding:14px;background:#152033;border:1px solid #32415a;border-radius:8px}summary{cursor:pointer;font-weight:600}.notes{font-size:14px}footer{padding:28px 0;color:#aabbcf}@media(max-width:540px){main{padding:20px 12px}th,td{padding:8px}}
</style></head><body><!--
[コンポーネント概要]
main は結論、全19条件の比較と全32セッション損益をまとめます。
.scroll は幅のある金額表を横に閲覧する領域です。
details は各手法の簡単な説明と全場表です。summary を押すと開閉します。
.positive、.negative、.neutral は収支の符号を示します。色だけでなく金額も表示します。
この資料は保存済み会計だけを表示し、外部通信や注文を行いません。
--><main>'''
    document += f'<h1>板の定着と進行失敗の入口検証</h1><p class="lead">{conclusion}</p>'
    document += '<p>全32セッション・19条件。最大収益より、活動場の赤字率と損失規模を優先。無取引は勝ちに含めません。安定候補の最低活動条件は、各商品16場以上・20取引以上です。R2の両商品100%は各1取引だけなので候補から除外します。</p>'
    document += '<h2>どういう手法か</h2><p><b>C：新価格の定着。</b>板の減少と出来高を確認し、価格が一段進んでも支える板が残るなら、その方向へ入ります。<br><b>R：進行失敗から反転。</b>板の減少と出来高があったのに進めず、板が補充され、反対方向の価格が維持されたら入ります。売りは買いの反対です。</p>'
    document += '<p><b>途中・出口：</b>今回の入口比較では旧対照の出口を共通使用。始値の0.1%相当で損切り、0.4%相当のトレーリング、初回約定から30分又は場末で返済。幅は呼値に切り上げます。30分は入口を比較するための上限で、将来の統合手法を時間保有へ限定する条件ではありません。</p>'
    document += '<h2>安定性の比較</h2><p class="muted">赤字/活動＝赤字セッション数/実取引セッション数。金額利益割合＝総利益/(総利益+総損失)。単一条件は各商品1枚、Pは合計TOPIX10枚・日経20枚なので、円額の大きさだけでは比較できません。</p><div class="scroll"><table><thead><tr><th rowspan="2">手法</th><th colspan="3">TOPIXミニ</th><th colspan="3">日経マイクロ</th></tr><tr>'+''.join('<th>収支 円</th><th>赤字/活動</th><th>金額利益割合</th>' for _ in SYMBOLS)+'</tr></thead><tbody>'+''.join(summary)+'</tbody></table></div>'
    document += '<h2>分かったこと</h2><p>同じ板の段階が両市場で揃う主候補U_C1R1は、各商品7/32場・受付内11発火にとどまりました。25場の無発火を「損失を減らせた成功」とは扱えません。自己市場の確認を相手も満たす条件へ変えると、C1はTOPIX474→10、日経249→10、R1は121→1、41→1へ機会が減ります。</p><p>主因は、二市場の同じ準備が重ならないことでした。受付内888エピソード中、成立22、相手の同じ準備なし822、新鮮な時計なし43、同時計後半の切捨て候補1。買い準備は339件ありましたが二市場で0件なので、今回の主候補の両方向への有効性は未確認です。</p><p>次は、自己市場の具体的な板の準備と、相手市場の一般的な方向支持を分ける案を検討します。これは未検証です。今回の不足を、板の補充そのものが無価値という結論にはしません。</p>'
    document += '<h2>各手法の全セッション損益</h2><p class="muted">手法名を押すと32場を表示します。利益・損失は各完結取引の手数料後損益を相殺前に集計。枚数は利益/損失となった決済枚数で、同時保有枚数ではありません。</p>'+''.join(sections)
    document += '<details><summary>検証条件</summary><p class="notes">既知の保存32場だけを使用し、未見成績とは主張しません。正常な判断原行から次の正常気配で買ask/売bid約定。5秒最悪約定は今回加えていません。片道手数料はTOPIXミニ41.8円、日経マイクロ11円で注文ごとに切捨て。全建玉は場内返済。板の表示減少は約定・取消を識別できず、出来高方向は代理です。真の受信時計がないため、二市場の先後は価格時計を代用しています。</p></details>'
    document += '<footer>2026-09-21 デイ～2026-10-12 ナイト。<a href="公開会計.json">全会計データ</a>・<a href="README.md">読む順序</a></footer></main></body></html>'
    preview = HERE/'report/preview_final'
    preview.mkdir(parents=True, exist_ok=True)
    assert not (preview/TITLE).exists()
    (preview/TITLE).write_text(document, encoding='utf-8')
    save(preview/'公開会計.json', dict(sessions=result['sessions'], 条件数=19, primary='U_C1R1',
        安定候補=[value['config']['id'] for value in eligible], 金額利益80両商品=target,
        条件別={value['config']['id']: value for value in values},
        financial_SHA256=digest(HERE/'金融全32の結果.json'), independent_SHA256=digest(audit_path),
        financial_prefix_SHA256=digest(prefix_path)))
    save(HERE/'report/生成結果_最終.json', dict(全合格=True, 掲載条件数=19, 掲載場数=32, 掲載会計数=1216,
        安定候補=[value['config']['id'] for value in eligible], 金額利益80両商品=target,
        HTML=str((preview/TITLE).relative_to(ROOT)), HTML_SHA256=digest(preview/TITLE),
        independent=str(audit_path.relative_to(ROOT)), independent_SHA256=digest(audit_path), 公開前=True))
    print(conclusion)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit', type=Path, required=True)
    build(parser.parse_args().audit.resolve())
