"""00046の補足として、悪化した約定に見られる特徴を短いHTMLにまとめる。"""

from html import escape
import json
from pathlib import Path
import shutil


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00046_E01の15秒最悪約定比較'
TITLE='悪化した約定の特徴.html'


def read(path: Path) -> dict:
    """機能: 計算済みJSONを読む。

    引数: path(Path)。返り値: 保存値(dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def cell(value: float, digits: int=0, suffix: str='') -> str:
    """機能: 検算用の原値を付けた数値セルを作る。

    引数: value(float)、digits(int)、suffix(str)。返り値: HTML(str)。
    """
    number=round(value,digits)
    return f'<td><span data-value="{number}">{number:,.{digits}f}</span>{suffix}</td>'


def build() -> Path:
    """機能: 分解・直前変動・集中度・反証をまとめた補足ページを作る。

    引数: なし。返り値: 作成HTMLのパス(Path)。売買規則は変更しない。
    """
    price=read(HERE/'価格特徴分析.json')
    reasons=read(HERE/'reason_time/集計.json')['銘柄別']
    book=read(HERE/'book/板特徴集計.json')
    cards=[]; speed=[]; decomposition=[]; concentration=[]; robustness=[]; times=[]; reason_rows=[]
    for symbol,label in [('TOPIX','TOPIXミニ'),('NK225','NK225マイクロ')]:
        value=price['summary'][symbol]
        low=value['groups']['range30']['4呼値未満']; high=value['groups']['range30']['4呼値以上']
        ratio=high['per_unit_ticks']/low['per_unit_ticks']
        cards.append(f'<article><h2>{label}</h2><strong>{ratio:.2f}<small>倍</small></strong><p>直前30秒の高安差が4呼値以上の注文は、4呼値未満より1枚当たり悪化幅が大きい。</p></article>')
        speed.append(f'<tr><th>{label}</th>'+cell(low['n'])+cell(high['n'])+cell(low['per_unit_ticks'],2)+cell(high['per_unit_ticks'],2)+cell(ratio,2,'倍')+'</tr>')
        decomposition.append(f'<tr><th>{label}</th>'+cell(value['immediate_yen'])+cell(value['following_yen'])+cell(value['adverse_yen'])+cell(100*value['following_yen']/value['adverse_yen'],1,'%')+'</tr>')
        concentration.append(f'<tr><th>{label}</th>'+cell(value['n'])+cell(100*value['adverse_rate'],1,'%')+cell(reasons[symbol]['集中度']['上位1割注文数'])+cell(100*reasons[symbol]['集中度']['上位1割集中率'],1,'%')+'</tr>')
        robustness.append(f'<tr><th>{label}</th>'+''.join(cell(v['ratio'],2,'倍') for v in value['range_robustness'].values())+'</tr>')
        times.append(f'<tr><th>{label}</th>'+''.join(cell(reasons[symbol]['昼夜別'][period]['枚数加重平均悪化幅呼値'],2) for period in ('Day','Night'))+'</tr>')
        for kind in ('追跡新規','組の損切り','追跡返済','一部利確','順行後の悪化で半減','場内返済'):
            r=reasons[symbol]['理由別'][kind]
            reason_rows.append(f'<tr><th>{label}</th><td>{escape(kind)}</td>'+cell(r['注文数'])+cell(r['悪化額円'])+cell(r['枚数加重平均悪化幅呼値'],2)+'</tr>')
    html=f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>悪化した約定の特徴｜E01</title>
<style>
:root{{color-scheme:dark;background:#0b1220;color:#dce8f6;font:16px/1.65 system-ui,sans-serif}}*{{box-sizing:border-box}}body{{max-width:1160px;margin:auto;padding:32px 22px}}a{{color:#89bfff}}h1{{font-size:1.8rem}}h2{{font-size:1.2rem;margin-top:24px}}p{{margin:.6em 0}}.muted,small{{color:#9fb2cb}}.cards{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:24px 0}}article,details,.example{{background:#142034;border:1px solid #2b415e;border-radius:10px;padding:18px}}article h2{{margin:0}}article strong{{font-size:2.2rem;color:#68dbc0}}article small{{font-size:1rem;margin-left:8px}}article p{{font-size:.9rem}}.scroll{{overflow-x:auto;max-width:100%;border:1px solid #2b415e;border-radius:8px}}table{{width:100%;border-collapse:collapse;white-space:nowrap;font-variant-numeric:tabular-nums}}th,td{{padding:10px 13px;border-bottom:1px solid #263a54;text-align:right}}th:first-child,td:first-child{{text-align:left}}thead{{background:#1c2c43}}tbody tr:nth-child(even){{background:#111d30}}summary{{cursor:pointer;font-weight:650}}details{{margin-top:16px}}.example{{border-left:4px solid #e4b15e;margin:20px 0}}.lead{{font-size:1.1rem}}footer{{margin-top:24px;font-size:.85rem}}@media(max-width:700px){{body{{padding:20px 14px}}.cards{{grid-template-columns:1fr}}h1{{font-size:1.5rem}}table{{font-size:.85rem}}}}
</style></head><body>
<!--
[コンポーネント概要]
.cards は銘柄ごとの短期変動と悪化幅の関係を示します。
.scroll は比較表だけを横にスクロールさせ、本文を画面幅に収めます。
details は時間帯・注文種別・検証範囲を必要な時だけ開く補足です。
data-value は表示数値を検算する値であり、売買や外部通信は行いません。
-->
<a href="E01の15秒最悪約定比較.html">← 理想約定との収支比較</a>
<h1>悪化した約定に、どんな特徴があったか</h1>
<p class="muted">E01・全19セッション・469注文。判断後15秒の買い最高／売り最安による悪化を分析。</p>
<p class="lead"><strong>最も共通していたのは、発注判断の直前30秒の値動きが大きい場面です。</strong></p>
<div class="cards">{''.join(cards)}</div>
<h2>1．直前30秒の値動きが大きい注文ほど、悪化幅が大きい</h2>
<p>直前30秒の高値−安値を4呼値で分けました。保存価格の4呼値はTOPIXで2.0pt、NKで40円です。</p>
<div class="scroll"><table><thead><tr><th>商品</th><th>4呼値未満の件数</th><th>4呼値以上の件数</th><th>未満の平均悪化幅</th><th>以上の平均悪化幅</th><th>倍率</th></tr></thead><tbody>{''.join(speed)}</tbody></table></div>
<p class="muted">悪化幅の単位は呼値。数量で加重した1枚・1約定当たりの平均で、悪化ゼロの注文も含みます。ラージ先物の保存価格を使い、金額はミニ／マイクロ換算です。</p>
<details><summary>特定の一日・最大損失だけの影響か</summary>
<p>前半週・後半週に分けても、最大悪化の1注文を除いても、この関係は残りました。</p>
<div class="scroll"><table><thead><tr><th>商品</th><th>09/21〜09/25</th><th>09/28〜10/02</th><th>最大1注文除外</th></tr></thead><tbody>{''.join(robustness)}</tbody></table></div>
<p>値は「4呼値以上の平均悪化幅 ÷ 4呼値未満」。ただし同じ期間の記述的な比較であり、未知期間の予測性能を検証したものではありません。</p></details>
<h2>2．悪化の大部分は、判断した後の不利な値動き</h2>
<div class="scroll"><table><thead><tr><th>商品</th><th>判断時点と理想値の差</th><th>判断後の変動分</th><th>悪化合計</th><th>判断後の割合</th></tr></thead><tbody>{''.join(decomposition)}</tbody></table></div>
<p class="muted">金額は円。判断行の観測価格を基準に分解しました。実際に通信が遅れた結果ではなく、15秒窓の最悪値を選ぶ仮定です。</p>
<div class="example"><strong>実例：10/02 15:29:59のTOPIX・ショート返済3枚</strong>
<p>理想は4,096.0で買い返済。窓内の最悪値は4,102.0で、この返済だけで<strong>18,000円悪化</strong>しました。判断直前30秒の高安差は3.5pt。返済条件成立後の急反発が効いた例です。</p></div>
<h2>3．全注文が均等に悪化するわけではない</h2>
<div class="scroll"><table><thead><tr><th>商品</th><th>注文数</th><th>悪化した注文</th><th>上位1割の件数</th><th>上位1割が占める悪化額</th></tr></thead><tbody>{''.join(concentration)}</tbody></table></div>
<p>半数以上は悪化せず、悪化額の約半分が上位1割の注文に集中しています。</p>
<details><summary>出口・夜間・板厚には共通する特徴があったか</summary>
<p><strong>追跡返済：</strong>平均悪化幅は大きめでしたが、NKでは最大1件を除くと新規より小さくなります。「追跡返済は常に悪い」とは言えません。</p>
<div class="scroll"><table><thead><tr><th>商品</th><th>注文の種類</th><th>件数</th><th>悪化額（円）</th><th>1枚平均（呼値）</th></tr></thead><tbody>{''.join(reason_rows)}</tbody></table></div>
<p><strong>昼と夜：</strong>1枚平均はTOPIXで昼が大きく、NKでは夜が大きいため、夜間全体が悪いという共通則はありません。</p>
<div class="scroll"><table><thead><tr><th>商品</th><th>デイ平均（呼値）</th><th>ナイト平均（呼値）</th></tr></thead><tbody>{''.join(times)}</tbody></table></div>
<p><strong>板：</strong>判断時点の板の厚さ・偏りには、両銘柄で共通する明瞭な関係がありませんでした。気配幅3呼値以上の例は各銘柄1件だけ。補充・取消・注文フローの時間変化は今回未検証です。</p>
<p><strong>勝ち負け：</strong>元から赤字の取引では金額上の悪化が多いものの、枚数が多い影響が大きく、1枚の往復当たりでは元黒字・元赤字の悪化幅に大きな差はありません。</p></details>
<p class="muted">ここで分かったのは約定条件への弱さです。速い場面を避ければE01全体の収益が改善するかは別の検証が必要です。未来の価格は悪化の評価だけに使い、直前特徴には入れていません。</p>
<footer><a href="特徴分析/価格特徴分析.json">価格特徴</a> ／ <a href="特徴分析/理由時間帯集計.json">理由・時間帯</a> ／ <a href="特徴分析/板特徴集計.json">板の調査</a> ／ <a href="README.md">読む順序</a></footer>
</body></html>'''
    OUT.mkdir(exist_ok=True)
    target=OUT/TITLE
    target.write_text(html,encoding='utf-8')
    data_dir=OUT/'特徴分析'; data_dir.mkdir(exist_ok=True)
    for source,name in [(HERE/'価格特徴分析.json','価格特徴分析.json'),(HERE/'reason_time/集計.json','理由時間帯集計.json'),
                        (HERE/'book/板特徴集計.json','板特徴集計.json')]:
        shutil.copyfile(source,data_dir/name)
    return target


if __name__=='__main__':
    print(build())
