"""方向予測の採点を損益と混同せず、短い説明と全場の表へ公開する。"""

import html
import json
from pathlib import Path

import plan


def percentage(value: float | None) -> str:
    """
    機能: 分母を持つ率だけを百分率にする。
    引数: value(float|None) は採点率。
    返り値: str。分母0は長線で表示する。
    """
    return '—' if value is None else f'{value*100:.1f}%'


def get_cell(period: dict, rule: str, width: float, origin: str) -> dict:
    """
    機能: 事前固定の非重複・方向全体セルを取り出す。
    引数: period(dict)、rule/origin(str)、width(float)。
    返り値: dict は一意セル。成績順に手法を選ばない。
    """
    rows=[c for c in period['cells'] if c['rule']==rule and c['group']=='非重複'
        and c['direction']=='全体' and c['width_fraction']==width and c['origin']==origin]
    assert len(rows)==1
    return rows[0]


def main() -> None:
    """
    機能: 完成した非金融結果を一回読み、十八条件と全33場の採点を公開する。
    引数: なし。raw/event/APIや金融を呼ばない。
    返り値: None。暗色HTML・公開JSON・短い説明と案内を新規保存する。
    """
    result_path=plan.HERE/'measurement/方向予測の採点結果.json'
    result=plan.read(result_path)
    assert result['全合格'] and result['金融'] is False
    assert result['source_SHA256']==plan.sources()==plan.read(plan.HERE/'実測前の正式固定.json')['source_SHA256']
    assert result['counts']==dict(原NPZ=66,保存eventNPZ=66,非金融測定口座=66,新金融=0,原板=0,API=0)
    assert not plan.PUBLIC.exists()
    plan.PUBLIC.mkdir()
    public=dict(全合格=True,金融=False,結果SHA256=plan.digest(result_path),
        sessions=result['sessions'],primary=result['primary'],widths=result['widths'],rules=result['rules'],
        accounts=result['accounts'],combined=result['combined'],counts=result['counts'])
    payload=json.dumps(public,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    (plan.PUBLIC/'方向予測の公開採点.json').write_text(payload+'\n',encoding='utf-8')
    main_rows=[]
    brief=[]
    for symbol in ('TOPIX','NK225'):
        period=result['combined']['symbols'][symbol]['periods']['全33']
        for origin in ('公開mid','次行新規・費用後気配'):
            c=get_cell(period,'C',.001,origin)
            main_rows.append('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in (
                symbol,origin,c['n'],c['favorable_first'],c['adverse_first'],
                c['window_end'],c['eof'],c['price_cut'],c['entry_unavailable'],
                percentage(c['favorable_rate_resolved']),percentage(c['resolution_rate'])))+'</tr>')
            brief.append(f"- {symbol}・{origin}：候補{c['n']}、順先{c['favorable_first']}／逆先{c['adverse_first']}。解決内順先{percentage(c['favorable_rate_resolved'])}、解決率{percentage(c['resolution_rate'])}。")
    page='''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>方向予測はできているか｜00117</title><style>
:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;color:#e3ebf7;background:#0d1420}*{box-sizing:border-box}
body{margin:0;line-height:1.75}main{max-width:1450px;margin:auto;padding:32px 24px 70px}h1{font-size:clamp(25px,3vw,36px);margin:0 0 12px}h2{font-size:22px;margin:26px 0 12px}
p{max-width:1050px}.lead{border-left:4px solid #77b8fa;background:#17283b;padding:17px 20px}.muted{color:#adc0d6;font-size:14px}a{color:#8ec7ff}select{background:#192a40;color:#f1f6ff;border:1px solid #527095;padding:8px;border-radius:5px;font:inherit}label{display:inline-flex;gap:8px;align-items:center;margin:5px 14px 5px 0}.wrap{overflow:auto;border:1px solid #354761;border-radius:8px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-variant-numeric:tabular-nums}th,td{padding:9px 11px;border-bottom:1px solid #2b3e56;text-align:right}th{background:#1a2b42;color:#c9e3ff}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#121e30}details{margin-top:22px;padding:15px;border:1px solid #354761;border-radius:8px}summary{cursor:pointer;color:#b9daff;font-size:19px}#selection-status{font-weight:700;color:#c7e2ff}button:focus-visible,select:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid #efbd62;outline-offset:3px}@media(max-width:600px){main{padding:24px 14px}label{display:flex}th,td{padding:8px}.lead{padding:12px}h2{font-size:20px}}
</style></head><body>
<!--
[コンポーネント概要]
#direction-report は非金融の入口採点です。率は実取引の勝率ではありません。
#filters は保存済み十八条件・候補群・方向の切替で、未来に合わせた再学習や外部通信は行いません。
#all-sessions は固定33場の六状態を分けて表示します。0件の率は未定義として長線を表示します。
-->
<main id="direction-report"><p class="muted">作業00117 · 既知33場の非金融再点検</p><h1>利益を取れる幅の方向予測は、確立できているか</h1>
<p class="lead"><b>まだ確立できていません。</b> 一呼値の先着率約80%だけでは、損切りより先に十分な値幅を取れる確率を確認したことになりません。出口の調整より先に、予測自体を採点し直しました。</p>
<p>採点は「予想方向へ0.1%進む」と「逆へ0.1%進む」のどちらが先か。同じ波の連続シグナルを除きます。時間を決めた利確や未来を見た入口選別はしません。</p>
<h2>事前に決めた主評価：C・±0.1%・非重複</h2>
<div class="wrap"><table id="primary"><thead><tr><th>商品</th><th>起点</th><th>候補</th><th>順先</th><th>逆先</th><th>窓末未決</th><th>EOF未決</th><th>価格切断</th><th>次気配不可</th><th>解決内順先率</th><th>解決率</th></tr></thead><tbody>__MAIN__</tbody></table></div>
<p class="muted">公開mid＝判断時の中値から将来中値。次行新規・費用後気配＝次の正常板で仮に買う／売る価格から、返済側気配と往復手数料を引いた評価。後者も実約定・実決済勝率・収支ではありません。未決・切断を勝ちに含めません。</p>
<details><summary>以前の「22回／23回で0.1%順行」の意味</summary><p>既知25場の旧候補3では、日経22／23は「途中で逆行しても場末までに一度到達」。逆行0.1%より先の順行0.1%は14／23＝60.9%、TOPIXは7／19＝36.8%でした。旧候補1にはTOPIX63.2%・日経56.5%の先着もあり、方向反応が一切ないという結論ではありません。</p><p>ただし小標本・既知内の選択で、両商品共通の安定した利益を示しません。<a href="過去の到達率と先着率の確認.md">過去3候補の分子・分母と実取引への接続</a></p></details>
<h2>全33場の方向採点</h2><div id="filters">
<label>商品<select id="symbol"><option>TOPIX</option><option>NK225</option></select></label>
<label>入口<select id="rule"><option>A</option><option>B</option><option selected>C</option></select></label>
<label>幅<select id="width"><option value="0.0005">±0.05%</option><option value="0.001" selected>±0.1%</option><option value="0.002">±0.2%</option></select></label>
<label>起点<select id="origin"><option>公開mid</option><option>次行新規・費用後気配</option></select></label>
<label>群<select id="group"><option>非重複</option><option>全候補</option></select></label>
<label>方向<select id="direction"><option>全体</option><option>買い</option><option>売り</option></select></label></div>
<p id="selection-status" aria-live="polite"></p><div class="wrap"><table id="all-sessions"><thead><tr><th>セッション</th><th>候補</th><th>順先</th><th>逆先</th><th>窓末未決</th><th>EOF未決</th><th>価格切断</th><th>次気配不可</th><th>解決内順先率</th><th>解決率</th><th>常に買う</th><th>常に売る</th></tr></thead><tbody id="session-rows"></tbody><tfoot id="totals"></tfoot></table></div>
<p class="muted">常に買う／売るは、同じ候補・同じ幅の中値先着を固定方向で採点した参考。独立した取引結果ではありません。気配評価側では代数的に反転できないため表示しません。</p>
<details><summary>十八条件・前後半・昼夜の一覧</summary><div class="wrap"><table><thead><tr><th>商品</th><th>期間</th><th>入口</th><th>幅</th><th>起点</th><th>候補</th><th>順先</th><th>逆先</th><th>未決等</th><th>解決内順先率</th><th>解決率</th><th>常に買う</th><th>常に売る</th></tr></thead><tbody id="comparison"></tbody></table></div></details>
<details><summary>入口の説明と採点の限界</summary><p>A：同じ最良気配内で、累計出来高が初めて増えたときの方向代理。B：反対側の初期表示枚数相当まで累計出来高が増え、その間に反対側の表示枚数が初期値を割らない。C：Bに加え、判断方向側の表示枚数が反対側以上。</p><p>累計出来高は市場全体の値で、特定価格の消費や同一注文主の補充を証明しません。真の板受信時計も未保存です。Cは数量が保たれても勢いが続く、という仮説を試すもので、板の厚い側へ必ず進む法則ではありません。</p><p>非重複は入口別に、最大幅0.2%の二起点が解決／打切となるまで次を数えません。三幅は同じ候補を用います。観測窓内の価格連続区間で採点し、欠測・原入力末尾と正規の観測窓末を分けます。先着後の最大順行・逆行も保存しましたが事後診断です。</p><p>公開時だけ時刻資格を判定します。次気配は仮参照で、直後に静観・強制終了時刻となる旧注文の取消までは再現しません。観測窓はデイ08:45〜15:40、ナイト17:00〜05:55。33場は9/21デイ〜10/13デイの既知期間、追加2場は未使用です。</p></details>
<p><a href="方向予測の公開採点.json">公開採点JSON</a> · <a href="README.md">読む順序と証跡</a> · <a href="../index.html">作業一覧</a></p></main>
<script id="saved-data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('saved-data').textContent);
/**
 * 機能: 未定義分母を数値にせず、保存済み率を表示する。
 * @param {number|null} value - 採点率。
 * @returns {string} 百分率又は長線。
 */
function pct(value){return value===null?'—':(value*100).toFixed(1)+'%';}
/**
 * 機能: 表セルを作り、保存文字列をHTMLとして解釈しない。
 * @param {Array<string|number>} values - 列値。
 * @returns {HTMLTableRowElement} 表行。
 */
function row(values){const tr=document.createElement('tr');for(const value of values){const td=document.createElement('td');td.textContent=value;tr.append(td);}return tr;}
/**
 * 機能: 表示条件の一意セルを保存済み集計から探す。
 * @param {Array<object>} cells - 保存済みセル。
 * @returns {object} 条件に合うセル。
 */
function selected(cells){return cells.find(c=>c.rule===document.getElementById('rule').value&&c.width_fraction===Number(document.getElementById('width').value)&&c.origin===document.getElementById('origin').value&&c.group===document.getElementById('group').value&&c.direction===document.getElementById('direction').value);}
/**
 * 機能: 一セルの採点を固定順の表値へ変換する。
 * @param {object} c - 六状態と率。
 * @returns {Array<string|number>} 十二列中のラベル以外。
 */
function values(c){return [c.n,c.favorable_first,c.adverse_first,c.window_end,c.eof,c.price_cut,c.entry_unavailable,pct(c.favorable_rate_resolved),pct(c.resolution_rate),c.baseline?pct(c.baseline['常時買い'].favorable_rate_resolved):'—',c.baseline?pct(c.baseline['常時売り'].favorable_rate_resolved):'—'];}
/**
 * 機能: 外部取得や再採点をせず、全33場と保存合計の表示だけを切り替える。
 * @returns {void} 返り値なし。
 */
function render(){const symbol=document.getElementById('symbol').value;const body=document.getElementById('session-rows');body.replaceChildren();for(const session of data.sessions){const account=data.accounts.find(a=>a.symbol===symbol&&a.session===session);body.append(row([session.replace('_Day',' デイ').replace('_Night',' ナイト'),...values(selected(account.cells))]));}const total=selected(data.combined.symbols[symbol].periods['全33'].cells);document.getElementById('totals').replaceChildren(row(['合計',...values(total)]));document.getElementById('selection-status').textContent=`${symbol}／${document.getElementById('rule').value}／${document.getElementById('width').selectedOptions[0].textContent}／${document.getElementById('origin').value}：解決内順先率 ${pct(total.favorable_rate_resolved)}、解決率 ${pct(total.resolution_rate)}`;}
for(const control of document.querySelectorAll('#filters select'))control.addEventListener('change',render);
for(const symbol of ['TOPIX','NK225'])for(const [name,period] of Object.entries(data.combined.symbols[symbol].periods))for(const c of period.cells.filter(c=>c.group==='非重複'&&c.direction==='全体'))document.getElementById('comparison').append(row([symbol,name,c.rule,(c.width_fraction*100).toFixed(2)+'%',c.origin,c.n,c.favorable_first,c.adverse_first,c.n-c.resolved,pct(c.favorable_rate_resolved),pct(c.resolution_rate),c.baseline?pct(c.baseline['常時買い'].favorable_rate_resolved):'—',c.baseline?pct(c.baseline['常時売り'].favorable_rate_resolved):'—']));
render();
</script></body></html>'''
    page=page.replace('__MAIN__',''.join(main_rows)).replace('__DATA__',payload.replace('<','\\u003c'))
    (plan.PUBLIC/'方向予測はできているか.html').write_text(page,encoding='utf-8')
    legacy=plan.HERE/'legacy/過去三候補の方向予測を到達と先着に分けた確認.md'
    prose=legacy.read_text(encoding='utf-8').replace('../../../アルゴリズム調査/','../')
    prose=prose.replace('(旧三候補の方向到達と先着及び実取引の小根拠.json)',
        '(../../work/direction_review_20261016/legacy/旧三候補の方向到達と先着及び実取引の小根拠.json)')
    (plan.PUBLIC/'過去の到達率と先着率の確認.md').write_text(prose,encoding='utf-8')
    explanation='''# 方向予測の再点検

「意味のある値幅を、同幅の逆行より先に取れる」方向予測は、まだ両銘柄で確立していない。一呼値の方向反応を確認して売買化へ進んだが、実際に利益へできる幅でも予測が残るかを先に確かめる点が不十分だった。

入口の仮説を先に採点し、選択に使わない期間でも方向・場別に残ることを確かめ、その後に損切り・利益追尾へ接続する必要がある。小さい動きを大量に取って収支だけで予測力を判断する手順では、入口の問題が見えない。

## 事前主評価の実測

'''+ '\n'.join(brief)+'''

±0.1%、C、同じ波の非重複。解決率も必ず見る。未決・切断を負け又は勝ちと勝手に補完しない。次行は仮気配評価であり、実返済約定を再生した取引勝率ではない。

## 今回の到達点

合理的な方向予測があり、外れを抑え、伸びるときに追尾するという考えは妥当。ただし必要なのは、意味のある値幅と逆行の順序で裏付けた入口である。板数量の一条件だけで安定して中程度の波まで予測できるとした根拠はない。予測は不可能だと結論した検証でもない。

対象は既知33場。過去3候補は別の25場の保存結果を再確認し、未知検証へ数えない。今回も探索済み期間の再採点で、18条件の後選択や率の高い商品のみの採用によって成功とはしない。
'''
    (plan.PUBLIC/'結論と探索手順の見直し.md').write_text(explanation,encoding='utf-8')
    readme='''# 00117 方向予測の有効幅と探索方針の再点検

最初に [方向予測はできているか.html](方向予測はできているか.html) を開く。短い結論、主評価、全33場、十八条件の順で確認できる。

読む順序：

1. [結論と探索手順の見直し](結論と探索手順の見直し.md)。
2. [旧候補の到達率と先着率の区別](過去の到達率と先着率の確認.md)。
3. [今回の公開採点JSON](方向予測の公開採点.json)。

これは非金融の入口採点で、新たな損益や実決済勝率を計算したものではない。既知33場66原入力と66保存事象を各一回測定。A/B/C、±0.05/0.1/0.2%、二起点の十八条件を事前固定した。主評価はC・±0.1%・共通非重複・公開mid。後から最良条件へ主評価を変更しない。

入口時点で観測できる条件だけを使い、先着と極値だけ将来で採点する。非重複の停止は最大0.2%の二起点終端の遅い方まで。場末未決、原EOF、価格切断、次気配不可を別記。料金はTOPIXmini10枚・NK225micro20枚の注文別floor片道料を往復し、②の気配評価へだけ使用する。

保存原価格はラージ。真の板受信時計・各約定の売買方向・同じ注文主の補充は記録がなく、累計出来高の方向代理を事実の成行方向と扱わない。追加2場は未使用。

再現用固定・実装・人工と独立証跡は [専用作業域](../../work/direction_review_20261016/)。比較元00114〜00116の源と保存結果は変更していない。全場の黒字、ユーザーの損小利大目標を達成したとの報告ではない。
'''
    (plan.PUBLIC/'README.md').write_text(readme,encoding='utf-8')
    paths=[p for p in plan.PUBLIC.iterdir() if p.is_file()]
    plan.write(plan.HERE/'十八方向採点の公開射影.json',dict(全合格=True,金融=False,
        結果SHA256=plan.digest(result_path),outputs=[dict(path=p.relative_to(plan.ROOT).as_posix(),SHA256=plan.digest(p)) for p in paths]))
    print(json.dumps(dict(全合格=True,主評価=brief,公開ファイル=len(paths),新金融=0),ensure_ascii=False))


if __name__=='__main__':main()
