"""今回残す比較基準と、現在ナイトの入力停止を、短い二つの暗色レポートへ保存する。"""

import hashlib
import html
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
SUMMARY = '今回の結論と残す候補'
CURRENT = '現在ナイト一回照合の入力検査'
STYLE = '''body{margin:0;background:#0b1120;color:#e5edf9;font:16px/1.7 system-ui,sans-serif}main{max-width:1260px;margin:auto;padding:30px 22px}h1{font-size:26px}h2{font-size:20px;margin-top:28px}p{max-width:1000px}a{color:#85bdff}strong{color:#f6d383}.table-wrap{overflow-x:auto;max-width:100%;border:1px solid #344154;border-radius:10px}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{padding:10px 12px;text-align:right;border-bottom:1px solid #344154}th{background:#182337;color:#b7c9df}th:first-child,td:first-child{text-align:left}small{color:#a9b9ce}code{overflow-wrap:anywhere;white-space:normal}li{margin:8px 0}.note{background:#182337;padding:14px 18px;border-radius:10px}@media(max-width:600px){main{padding:18px 12px}h1{font-size:23px}body{font-size:15px}}'''


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 保存済み小JSONを一読取し、公開表示の出典指紋を記録する。
    引数: path(Path)は会計・取得manifest・非金融診断。
    返り値: tuple[dict,str]は内容とSHA256。原板、台帳、金融、APIは利用しない。
    """
    saved = path.read_bytes()
    return json.loads(saved), hashlib.sha256(saved).hexdigest()


def money(value: float) -> str:
    """
    機能: 円額を符号と桁区切り付きで表示する。
    引数: value(float)は保存済み円額。
    返り値: strは整数表示。未知値を数値へ補完しない。
    """
    return f'{value:+,.0f}'


def page(title: str, body: str) -> str:
    """
    機能: 短い研究レポートを共通のダークテーマで包む。
    引数: title(str)は表題、body(str)は生成済み本文HTML。
    返り値: strは日本語UTF-8の完全HTML。外部通信や売買を含まない。
    """
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{STYLE}</style></head><body>
<!--
[コンポーネント概要]
main は結論と保存根拠の表示領域です。金融処理・外部通信は行いません。
.table-wrap は表だけの横スクロール領域です。狭い画面で本文が横へ溢れることを防ぎます。
#summary は既知33場の商品別比較基準、#current は現在取得の入力検査を表示します。
未知の損益は未測定と記し、利益0又は無取引へ置き換えません。
--><main><h1>{title}</h1>{body}</main></body></html>'''


def main() -> None:
    """
    機能: 既知の代表二条件と現在入力不適合を分け、会計と短い二表示を保存する。
    引数: なし。すべて完成済みの小資料を用いる。
    返り値: None。全33表は既存HTMLへリンクし、新金融又は現在損益を算出しない。
    """
    source = PUBLIC / 'E01取引更新と損失予算の公開会計.json'
    historical, history_sha = read(source)
    capture_path = HERE / 'current_capture/取得完了.json'
    diagnosis_path = HERE / 'current_capture/価格時計逆行による入力停止の非金融診断.json'
    capture, capture_sha = read(capture_path)
    diagnosis, diagnosis_sha = read(diagnosis_path)
    assert len(historical['sessions']) == 33 and capture['全合格'] and diagnosis['診断完了']
    rows = []
    for symbol, identifier, label in (
            ('TOPIX', 'E01_TRADE_W60_VETO_D0_P1L8', 'TOPIX・逆票見送り'),
            ('NK225', 'E01_TRADE_W60_CONFIRM_D0_P1L8', '日経・肯定票要求')):
        value = historical['cases'][identifier]['summary'][symbol]
        assert abs(value['profit'] - value['loss'] - value['net']) < 1e-6
        rows.append(dict(symbol=symbol, id=identifier, label=label, **value))
    cells = ''.join(f'''<tr><td>{r['label']}</td><td>{r['profit']:,.0f}</td><td>{r['loss']:,.0f}</td><td>{money(r['net'])}</td><td>{r['positive']}/{r['negative']}/{r['no_trade']}</td><td>{100*r['profit_share']:.1f}%</td><td>{money(r['top3_excluded'])}</td><td>{money(r['worst'])}</td></tr>''' for r in rows)
    conclusion = f'''<p><strong>両銘柄で毎セッション利益を積み重ね、金額利益80%を満たす手法は未発見です。</strong>今回の比較では、次の2条件を今後の比較基準として残します。</p>
<p><small>既知33場：9月21日デイ～10月13日デイ。初回TOPIXミニ5枚・日経マイクロ10枚、上限10枚・20枚。手数料とラージ気配差込み、場内返済。利益・損失は決済取引の相殺前合計、黒字場数はセッション単位です。</small></p>
<div class="table-wrap"><table id="summary"><thead><tr><th>候補</th><th>利益（円）</th><th>損失（円）</th><th>収支（円）</th><th>黒字/赤字/無取引場</th><th>金額利益割合</th><th>上位3利益場を除外</th><th>最悪場</th></tr></thead><tbody>{cells}</tbody></table></div>
<p>大勝ち3場を除いても黒字なのは残す理由です。ただし商品ごとに入口が異なり、同じ33場から選んだ結果です。日経の8無取引場を勝ちには数えていません。</p>
<p><small>金額利益80%は総利益÷（総利益＋総損失）で、利益／損失4倍に相当します。代表2条件は平均利益が平均損失を下回り、金額ベースの損小利大も未達です。</small></p>
<h2>手法を簡単に言うと</h2><p>E01の方向・押し戻り条件が成立したら、直近60秒の出来高と現在値の更新を直前の売買気配に照らします。TOPIXは強い逆方向の更新があれば見送り、日経は同方向の更新を確認できた場合だけ入ります。入口2条件を除く処理は共通です。</p>
<p><small>60秒の窓は現在値時計による代理です。保存されていない板受信時刻や、真の買い・売り約定数量を復元した結果ではありません。</small></p>
<p>場内の手数料後清算利益がTOPIX2,500円・日経1,000円、又は損失が20,000円・8,000円に達したら、次の正常気配で残玉を返済してその場を終えます。それ以外は元E01の途中判断と追跡返済を維持します。各閾値は初回枚数×観測1／8呼値×円倍率。観測1呼値はTOPIX0.5pt・日経10円です。</p>
<h2>損失を潰しきれなかった理由</h2><ol><li><b>損切りを狭めると、回復した取引まで切る。</b>8→4呼値にすると元の勝ちがTOPIX6取引・日経7取引で負けに変わり、両代表が赤字になりました。逆方向の更新を追加しても解消しませんでした。</li><li><b>早い利確は、負けだけでなく利益幅も削る。</b>日経代表は+23,280円→+280円。減少23,000円のうち、利確判断後の気配悪化は3,000円で、これだけが原因ではありません。</li><li><b>勝率が高くても、1敗が重い。</b>常設利確の別条件は日経24勝1敗でも、利益18,720円・損失16,220円。10月8日11:37の買いを12:16に損切りした1敗が約21勝分を消しました。</li></ol>
<p class="note">現在ナイトは一回だけ取得しましたが、価格時刻の日付が逆行して固定入力検査が停止しました。<strong>未知セッションの成績は未測定です。</strong>原板の並べ替え・日付補完・再取得はしていません。</p>
<p><a href="E01の取引更新と損失幅の改善及び全セッション損益.html">全33セッションの利益・損失・収支と枚数</a>　<a href="E01で残った損失と改善の具体例.md">何時のどの値動きで損失を生んだか</a>　<a href="{CURRENT}.html">現在ナイトの入力検査</a></p>
<p><a href="README.md">各比較の読む順序</a>　<a href="../共通/知見台帳/README.md">法則ごとの知見</a></p>'''
    current_rows = []
    for symbol in ('TOPIX', 'NK225'):
        value = diagnosis['商品別'][symbol]
        fetched = capture['symbols'][symbol]
        first = value['最初12逆行例'][0]
        current_rows.append(dict(symbol=symbol, count=value['全行数'], reversals=value['直前行からの価格時計逆行'],
                                 older=value['過去最大価格時計より古い行'], missing=value['時計欠測'],
                                 as_of=fetched['snapshot']['as-of'], first=first))
    current_cells = ''.join(f'''<tr><td>{r['symbol']}</td><td>{r['count']:,}</td><td>{r['reversals']}</td><td>{r['older']}</td><td>{r['missing']}</td><td>{html.escape(r['as_of'])}</td></tr>''' for r in current_rows)
    examples = ''.join(f'''<li>{r['symbol']}：原連番{r['first']['直前']['原連番0起点']:,}の{html.escape(r['first']['直前']['価格時刻'])}から、次行{r['first']['逆行行']['原連番0起点']:,}では{html.escape(r['first']['逆行行']['価格時刻'])}へ戻りました。</li>''' for r in current_rows)
    current_body = f'''<p><strong>取得は成功、損益は未測定です。</strong>2026-10-13ナイトの板を、10月14日05:22～05:23に両銘柄各一回だけ取得しました。現在セッションの再取得・実注文はありません。</p>
<div class="table-wrap"><table id="current"><thead><tr><th>銘柄</th><th>保存行数</th><th>直前時計への逆行</th><th>過去最大時計より古い行</th><th>時計欠測</th><th>取得固定上限</th></tr></thead><tbody>{current_cells}</tbody></table></div>
<h2>停止した具体箇所</h2><ul>{examples}</ul>
<p>保存原行は進んでいる一方、午前4時の一部現在値時計が前日の日付になります。受信時計は保存されておらず、現在値時計を板の受信時計として扱うこともできません。</p>
<p>事前固定した往復単独・追従単独・自動選択の3条件は、単調な価格時計を要求する入力検査で停止しました。<b>無取引、利益0、赤字という結果ではありません。</b>E01新候補の未知成績も未測定です。並べ替え、日付の推定補完、エラー後の条件変更は行っていません。</p>
<p class="note">取得時点では場が未完了でした。将来この板を検証に使う場合も、価格時計の扱いと受信順を先に定義し、今回の未測定を成功例へ置き換えないようにします。</p>
<p><a href="../../work/wave_v106/current_capture/取得完了.json">一回取得の証跡</a>　<a href="../../work/wave_v106/current_capture/価格時計逆行による入力停止の非金融診断.json">具体的な逆行行と原本指紋</a>　<a href="../../work/wave_v106/current_session/現ナイト入力準備False.json">入力停止</a>　<a href="{SUMMARY}.html">過去33場の結論</a></p>'''
    for title, body in ((SUMMARY, conclusion), (CURRENT, current_body)):
        (PUBLIC / (title + '.html')).write_text(page(title, body), encoding='utf8', newline='\n')
    account = dict(rows=rows, current=current_rows, 既知場数=33, 現在金融='未測定', 新金融再生=0, API取得=0,
                   sources={source.relative_to(ROOT).as_posix():history_sha,
                            capture_path.relative_to(ROOT).as_posix():capture_sha,
                            diagnosis_path.relative_to(ROOT).as_posix():diagnosis_sha})
    (PUBLIC / '今回の結論の表示根拠.json').write_text(json.dumps(account, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    print('短い結論と現在入力検査の2表示を保存。金融0。')


if __name__ == '__main__':
    main()
