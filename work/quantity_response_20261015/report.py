"""完了した非金融測定の小集計を、価格応答と損益を分けて公開する。"""

import hashlib
import html
import json

import plan


LABELS = dict(type0_all='最初の活動代理・全件', type1_all='初期数量相当の公表活動へ到達・全件',
              type1_decreased='到達時の反対数量が初期より減少',
              type1_maintained='到達時の反対数量が初期以上',
              type1_never_below='初期以上群のうち途中も初期を割らず',
              type1_recovered='初期以上群のうち一度減って回復')

# ----------------------------------------


def percent(value: float | None) -> str:
    """
    機能: 未定義を0にせず、先着率を表示する。
    引数: value(float|None) は解決例の同方向率。
    返り値: str は小数一桁の百分率又は未定義。
    """
    return '未定義' if value is None else f'{value * 100:.1f}%'


def cell(group: dict) -> str:
    """
    機能: 解決例の分子分母と打切全件を同じセルに表示する。
    引数: group(dict) は測定群の小集計。
    返り値: str はHTML。順行1Tを利益と表現しない。
    """
    return (f"<b>{percent(group['rate'])}</b> {group['plus']:,}/{group['resolved']:,}"
            f"<small>全{group['n']:,}・価格不明{group['unknown']:,}・窓終了{group['window_end']:,}・保存末尾{group['eof']:,}</small>")


def comparisons(saved: dict, symbol: str) -> dict:
    """
    機能: 数量二群の場別差を、両群に解決例がある場だけで比較する。
    引数: saved(dict)、symbol(str) は保存結果と商品。
    返り値: dict は比較可能場数と差の符号。独立性や因果の証明にしない。
    """
    paired = []
    for row in saved['rows']:
        if row['symbol'] != symbol:
            continue
        a = row['groups']['type1_decreased']['rate']
        b = row['groups']['type1_maintained']['rate']
        if a is not None and b is not None:
            paired.append(a - b)
    return dict(比較可能場=len(paired), 減少群が高い=sum(value > 0 for value in paired),
                同率=sum(value == 0 for value in paired), 維持群が高い=sum(value < 0 for value in paired))


def main() -> None:
    """
    機能: 保存済み結果を一読し、全33場の数量別価格応答を暗色HTMLとMDへ出す。
    引数: なし。
    返り値: None。入力NPZ・金融・APIは読まず、新しい測定を実行しない。
    """
    public = plan.PUBLIC
    title = public / '表示数量を観測した後の方向応答.html'
    target = public / '数量後の価格応答の公開集計.json'
    assert not title.exists() and not target.exists()
    purpose = plan.HERE / '公開の一読目的.json'
    plan.write(purpose, dict(保存測定結果=1, 元NPZ=0, 金融=0, 新測定=0, API=0))
    source = plan.HERE / 'measurement/数量応答の結果.json'
    raw = source.read_bytes()
    saved = json.loads(raw.decode('utf-8'))
    assert saved['全合格'] and saved['金融'] is False and len(saved['rows']) == 66
    assert saved['counts']['NPZ本文'] == 66 and saved['counts']['新金融'] == 0
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    pieces = ['<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>表示数量の後の価格応答</title><style>html{color-scheme:dark}body{background:#0d1421;color:#e5eaf3;font:16px/1.65 system-ui;margin:0}main{max-width:1280px;margin:auto;padding:22px}a{color:#8fc4ff}h1{font-size:1.7rem}h2{font-size:1.25rem}p{max-width:80em}.note,section{background:#172237;border:1px solid #35435a;border-radius:9px;padding:16px;margin:18px 0}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #35435a;padding:10px;text-align:left;vertical-align:top}th{background:#26344c;white-space:nowrap}small{display:block;color:#b1bed4;font-size:12px}b{color:#acd5ff}.warn{color:#ffcf8f}details{margin:18px 0}summary{cursor:pointer}td:first-child{white-space:nowrap}@media(max-width:600px){main{padding:12px}table{min-width:840px}h1{font-size:1.4rem}}</style><main>',
        '<h1>板の表示数量を観測した後、どちらへ先に動いたか</h1>',
        '<p class="note"><b>これは売買成績ではありません。</b>同じ両気配で、公表出来高が初期の反対数量以上へ増えた瞬間を一回だけ取り、その後の両気配±1観測呼値の先着を測りました。全33場。利益・費用回収・真の補充は未測定です。</p>',
        '<p>「初期以上」は一度減って戻った場合も含みます。公表出来高は全価格の合計で、同じ価格で食われた数量ではありません。最初の正増時のLast位置を買い／売りの代理方向として固定しています。</p>']
    for symbol, japanese in (('TOPIX', 'TOPIX'), ('NK225', '日経225')):
        total = saved['totals'][symbol]['all']['groups']
        comparison = comparisons(saved, symbol)
        a, b = total['type1_decreased'], total['type1_maintained']
        delta = None if a['rate'] is None or b['rate'] is None else (a['rate'] - b['rate']) * 100
        pieces.append(f'<section><h2>{japanese}</h2>')
        pieces.append(f"<p>減少群の同方向先着率 − 初期以上群：<b>{'未定義' if delta is None else f'{delta:+.2f}ポイント'}</b>。比較可能{comparison['比較可能場']}場のうち、減少群が高かったのは{comparison['減少群が高い']}場。</p>")
        pieces.append('<div class="scroll"><table><thead><tr><th>観測群</th><th>同方向1Tの先着率</th></tr></thead><tbody>')
        for name, label in LABELS.items():
            pieces.append(f'<tr><td>{label}</td><td>{cell(total[name])}</td></tr>')
        pieces.append('</tbody></table></div></section>')
    pieces.append('<h2>全33場</h2><p>各セルは「同方向先着数／解決した二先着の合計」。価格不明・窓終了・保存末尾は成功にも失敗にも入れず、件数を併記しています。</p><div class="scroll"><table><thead><tr><th>セッション</th><th>TOPIX・数量減少</th><th>TOPIX・初期以上</th><th>日経・数量減少</th><th>日経・初期以上</th></tr></thead><tbody>')
    rows = {(row['session'], row['symbol']): row for row in saved['rows']}
    for session in saved['sessions']:
        parts = [f"<tr><td>{html.escape(session.replace('_Day', ' デイ').replace('_Night', ' ナイト'))}</td>"]
        for symbol in ('TOPIX', 'NK225'):
            for name in ('type1_decreased', 'type1_maintained'):
                parts.append('<td>' + cell(rows[(session, symbol)]['groups'][name]) + '</td>')
        pieces.append(''.join(parts) + '</tr>')
    pieces.append('</tbody></table></div><details><summary>昼夜別と解釈の範囲</summary><div class="scroll"><table><thead><tr><th>商品・時間帯</th><th>数量減少</th><th>初期以上</th></tr></thead><tbody>')
    for symbol in ('TOPIX', 'NK225'):
        for period in ('Day', 'Night'):
            total = saved['totals'][symbol][period]['groups']
            pieces.append(f'<tr><td>{symbol} {period}</td><td>{cell(total["type1_decreased"])}</td><td>{cell(total["type1_maintained"])}</td></tr>')
    pieces.append('</tbody></table></div><p>同じepisodeの初回活動と数量到達は同じBBOで、その間に1T先着はありません。両方達成したepisodeでは結果も同じです。待ったから同じ未来結果が改善したという意味ではなく、数量到達まで価格が変わらなかった集合を選んでいます。</p><p>同じ場の観測は独立ではありません。初期数量、活動量、spread等の交絡もあり、群差を補充の因果効果とは断定しません。1TはTOPIX0.5pt・日経10円のラージ観測幅。ミニ／マイクロの実気配・手数料後黒字とは別です。</p><p>旧保存の観測窓はデイ08:45～15:40、ナイト17:00～翌05:55。窓終了は実セッション収録の完備や返済注文の結果を意味しません。追加2場、テクニカル水準、相手市場の板は今回未測定です。</p></details>')
    pieces.append('<p><a href="README.md">根拠と読む順序</a> ／ <a href="../00113_現在の注文活動と再進行から波の中間に参加/現在の活動と再進行から参加する手法と全セッション損益.html">直前の金融成績</a></p></main></html>')
    title.write_text('\n'.join(pieces), encoding='utf-8')
    proof = dict(全合格=True, 元測定SHA256=digest, 公開集計SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
                 HTML_SHA256=hashlib.sha256(title.read_bytes()).hexdigest(), 入力NPZ=0, 新測定=0, 新金融=0,
                 群差={symbol: comparisons(saved, symbol) for symbol in ('TOPIX', 'NK225')})
    plan.write(plan.HERE / '全三十三場の公開射影.json', proof)
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
