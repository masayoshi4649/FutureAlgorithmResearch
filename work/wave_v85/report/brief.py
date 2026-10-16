"""安定性についての結論と全セッション損益だけを短い画面へまとめる。"""
from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00081_E01原版と知見統合改修の再検証'
MAIN = 'E01原版と改修の説明と全セッション損益.html'
CHOSEN = 'E01_G_U'
SYMBOLS = ('TOPIX', 'NK225')


def read(path):
    """
    機能: 保存済みの日本語JSONを読み取る。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def money(value):
    """
    機能: 円単位の数値を符号と色を付けたHTMLへ変換する。
    引数: value(float又はint)。
    返り値: str。HTMLの数値要素。
    """
    rounded = int(round(value))
    color = 'gain' if rounded > 0 else ('loss' if rounded < 0 else 'neutral')
    text = f'{rounded:+,}円' if rounded else '0円'
    return f'<span class="{color}">{text}</span>'


def stability(result, symbol):
    """
    機能: セッション単位と同日名のデイ・ナイト合算を分けて集計する。
    引数: result(dict)、symbol(str)。
    返り値: dict。既存損益を再計算せず集約した安定性情報。
    """
    rows = [r for r in result['rows'] if r['symbol'] == symbol]
    totals = result['periods']['全30'][symbol]
    days = defaultdict(float)
    for row in rows:
        days[row['session'].split('_')[0]] += row['net']
        assert abs(row['campaign_profit'] - row['campaign_loss'] - row['net']) < 1e-5
    assert len(rows) == 30 and len(days) == 15
    assert abs(sum(days.values()) - totals['net']) < 1e-5
    return dict(net=totals['net'], max_drawdown=totals['max_drawdown'],
        profit=totals['campaign_profit'], loss=totals['campaign_loss'],
        positive_sessions=sum(r['net'] > 0 for r in rows),
        positive_days=sum(v > 0 for v in days.values()),
        ratio=totals['net']/totals['max_drawdown'],
        session_count=len(rows), day_count=len(days))


def main():
    """
    機能: 全25条件の安定性順位を照合し、結論中心の短いHTMLを生成する。
    引数: なし。build.pyが生成した描画資料.jsonを参照する。
    返り値: None。主HTMLと表示根拠を同じ作業に保存する。
    """
    data = read(HERE / '描画資料.json')
    chosen = data['results']['observed'][CHOSEN]
    stats = {s: stability(chosen, s) for s in SYMBOLS}
    rank_proof = {}
    sources = {}
    for model in ('observed', 'specified'):
        records = data['results'][model]
        assert len(records) == 25
        rank_proof[model] = {}
        for identifier, result in records.items():
            path = WORK / model / 'results' / (identifier + '.json')
            assert result == read(path)
            sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        for symbol in SYMBOLS:
            scores = {identifier: stability(result, symbol)['ratio'] for identifier, result in records.items()}
            best = max(scores.values())
            assert abs(scores[CHOSEN]-best) < 1e-10
            rank_proof[model][symbol] = dict(最高値=best,
                同率候補=[identifier for identifier, score in scores.items() if abs(score-best) < 1e-10])
    # ----------------------------------------
    # 商品間の金額を足さず、それぞれの収益と落込みを並べる。
    metrics = [
        ('合計収支', [money(stats[s]['net']) for s in SYMBOLS]),
        ('黒字セッション', [f'{stats[s]["positive_sessions"]} / 30' for s in SYMBOLS]),
        ('黒字日（デイ＋ナイト）', [f'{stats[s]["positive_days"]} / 15' for s in SYMBOLS]),
        ('最大の資産下落', [money(-stats[s]['max_drawdown']) for s in SYMBOLS]),
    ]
    summary_rows = ''.join('<tr><th>'+label+'</th>'+''.join('<td>'+cell+'</td>' for cell in values)+'</tr>' for label, values in metrics)
    lookup = {(r['session'], r['symbol']): r for r in chosen['rows']}
    session_rows = []
    for session in data['fixed']['全30']:
        cells = []
        for symbol in SYMBOLS:
            row = lookup[session, symbol]
            cells.extend(money(v) for v in (row['campaign_profit'], -row['campaign_loss'], row['net']))
        label = html.escape(session.replace('_Day', ' デイ').replace('_Night', ' ナイト'))
        session_rows.append('<tr><th>'+label+'</th>'+''.join('<td>'+cell+'</td>' for cell in cells)+'</tr>')
    total_cells = [money(v) for s in SYMBOLS for v in (stats[s]['profit'], -stats[s]['loss'], stats[s]['net'])]
    session_rows.append('<tr class="total"><th>全30 合計</th>'+''.join('<td>'+cell+'</td>' for cell in total_cells)+'</tr>')
    document = '''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>結論：安定性で選ぶE01</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#10151e;color:#e8edf5;font:16px/1.7 system-ui,"Yu Gothic UI",Meiryo,sans-serif}main{max-width:1050px;margin:auto;padding:28px 24px 60px}h1{font-size:clamp(23px,4vw,32px);line-height:1.4;margin:8px 0 16px}h2{font-size:20px;margin:0 0 12px}p{margin:10px 0}.label,.note{color:#b6c3d3;font-size:13px}.answer{border-left:4px solid #86b9ff;padding-left:16px;font-size:19px}.panel{background:#19212d;border:1px solid #344254;border-radius:10px;padding:18px;margin:22px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:10px;border-bottom:1px solid #344254;text-align:right;white-space:nowrap}th:first-child{text-align:left}thead th{color:#cbdcf2}tbody th{font-weight:500}.gain{color:#72dbb0}.loss{color:#ff939e}.total{background:#243247;font-weight:700}.all-sessions{font-size:13px;min-width:850px}a{color:#86b9ff}summary{cursor:pointer;font-weight:650}details[open] summary{margin-bottom:14px}.caution{color:#f0cb82}footer{font-size:13px;color:#b6c3d3;margin-top:24px}@media(max-width:600px){main{padding:20px 12px 40px}.panel{padding:12px}.answer{font-size:17px}th,td{padding:8px;font-size:13px}}
</style></head><body><main>
<!--
[コンポーネント概要]
#conclusion は1候補と選定基準を最初に示す。
#summary は銘柄別の収支、黒字回数、累積資産の最大下落を示す。
#sessions は必要なときだけ開く全30セッションの損益表。
価格条件・約定仮定の切替と全候補の情報は別の詳細ページへ分離する。
-->
<div class="label">00081 · 全30セッションの検証結果</div>
<h1 id="conclusion">安定性で一つ選ぶなら E01_G_U</h1>
<p class="answer"><strong>両市場の方向を再確認して入り、米国市場の開始前後は休むE01です。</strong></p>
<p>日経とTOPIXの方向が揃っているかを新規待機中にも確認。利益はトレーリングで伸ばし、米国現物開始の前後15分は返済して静観します。</p>
<p><strong>収支に対する累積下落の小ささでは、両銘柄とも25条件中で最良でした。</strong><br>
<span class="note">銘柄ごとに「純収支÷最大下落」で比較。黒字日数が最も多いという意味ではありません。</span></p>
<section class="panel" id="summary"><h2>E01_G_U の結果</h2>
<div class="scroll"><table><thead><tr><th>指標</th><th>TOPIXミニ</th><th>日経マイクロ</th></tr></thead><tbody>__SUMMARY__</tbody></table></div>
<p class="note">手数料後・観測現在値での仮想約定。初回5枚／10枚、追加なし、場内返済。2026/09/21デイ〜10/09ナイト。</p>
<p class="note">最大下落＝累積資産の高値から、その後の安値までの最大減少額。1日は同じ日付のデイ＋ナイトで集計。</p>
</section>
<p class="caution"><strong>「毎日安定して稼げた」とまでは言えません。</strong> 赤字日も残っており、今回の候補の中で収益と落込みのバランスが最も良かった、という結論です。</p>
<details class="panel" id="sessions"><summary>全30セッションの利益・損失・収支を開く</summary>
<p class="note">初回新規から全返済までを1組として集計。部分利確後の残玉の損失も含めます。</p>
<div class="scroll"><table class="all-sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="3">TOPIXミニ</th><th colspan="3">日経マイクロ</th></tr><tr><th>利益</th><th>損失</th><th>収支</th><th>利益</th><th>損失</th><th>収支</th></tr></thead><tbody>__SESSIONS__</tbody></table></div></details>
<footer>他の候補・条件は <a href="検証詳細.html">検証詳細</a> ／ <a href="全25条件の比較.html">全25条件</a>。<br>保存済みデータでの比較であり、将来の安定性を確認した結果ではありません。</footer>
</main></body></html>'''.replace('__SUMMARY__', summary_rows).replace('__SESSIONS__', '\n'.join(session_rows))
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / MAIN).write_text(document, encoding='utf-8')
    proof = dict(全合格=True, 選定基準='商品別の純収支÷全原板時価での最大下落。既知25条件の比較。',
        選定=CHOSEN, 順位照合=rank_proof, 表示値=stats, 入力SHA256=sources,
        公開SHA256=hashlib.sha256(document.encode('utf-8')).hexdigest(), 全セッション行数=30,
        制約='黒字日数最多や毎日黒字を意味しない。日計は同日名のDayとNight。')
    (HERE / '簡潔版の数値検査.json').write_text(json.dumps(proof, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
