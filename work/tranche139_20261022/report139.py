"""全試行の結果を、短い結論と選択式の全セッション会計へまとめる。"""

import html
import json
import shutil
from common139 import HERE,PUBLIC,read,configs
from run_early139 import settings as early_settings
from run_recycle139 import settings as recycle_settings
from run_protect139_v2 import settings as protect_settings
import early_guard139_v2 as early_guard139
from summarize139 import main as summarize


def money(value):
    """
    機能: 円額に符号と桁区切りを付ける。
    引数: value(float)は円額。
    返り値: strは整数円の表示。
    """
    return f'{value:+,.0f}'


def labels():
    """
    機能: 全条件へ日本語の短い表示名と比較区分を付ける。
    引数: なし。
    返り値: dict[str,dict]は手法名、区分、条件説明。
    """
    out={}
    for group,cs in [('段階と玉別管理',configs()),('利益枚数の再追加',recycle_settings()),('追撃保護の改善',protect_settings())]:
        for c in cs:
            initial=('警戒時1枚・通常'+str(c['initial'])+'枚・強支持時'+str(c['target'])+'枚') if c['adaptive'] else str(c['initial'])+'枚'
            addition='追加なし' if not c['increments'] else '順行'+str(c['steps'])+'Rで'+str(c['increments'])+'枚ずつ追加（最後の段は残り枠を補充）'
            desc=f'初回{initial}。主担当最大{c["target"]}枚。{addition}。'
            if c['id'] not in ('B5','B2'):
                desc+=f'玉別起動{c["exit_activation"]}R、幅{c["exit_width"]}R、停止{c["stop_width"]}R。各配列の先頭は初回、以後は追加玉、末尾値を延長。起動0・停止0はその独自条件なし。'
            if c['source_style']=='独立出口':desc+='元の入口だけ利用し、独自停止・追尾・場末返済で運用。'
            else:desc+='元の親の最終返済を遵守。'
            if c.get('initial_wait'):desc+='初回玉だけ元親の途中利確を見送る。'
            if c.get('recycle_rounds'):desc+='再追加上限'+str(c['recycle_rounds'])+'回。利益を実現した追撃枚数だけが対象。'
            out[c['id']]=dict(name=c['name'],group=group,description=desc)
            if c['id']=='B2':
                out[c['id']]['name']='主担当2枚固定・補完は従来どおり'
                out[c['id']]['description']='主担当だけを2枚に減らす対照。補完担当は従来の最大5枚を維持するため、口座全体が常に2枚という意味ではない。元の入口・出口を維持。'
    japanese={'support':'二市場の短期方向一致','ema38':'二市場のEMA3・8一致','ema520':'二市場のEMA5・20一致','retest':'直近帯の突破→戻り→再進行'}
    for c in early_settings():
        desc=japanese[c['entry']['mechanism']]+f'。30秒支持{c["entry"]["threshold30"]:g}R・120秒支持{c["entry"]["threshold120"]:g}Rが両市場で15秒続けば、初回{c["management"]["initial"]}枚、最大{c["management"]["target"]}枚。'
        for base in ('','B5_','C04_'):
            name=('早期単独' if not base else base[:-1]+'＋早期')+'／'+japanese[c['entry']['mechanism']]+f'／最大{c["management"]["target"]}枚'
            out[base+c['id']]=dict(name=name,group='朝・米国前の参加',description=desc+'早期は09:50又は米国寄り15分前に返済。通常担当と保有が重なれば後の新規判断を見送る。')
    for c in early_guard139.settings():
        for base in ('','B5_','C04_'):
            out[base+c['id']]=dict(name=('早期単独' if not base else base[:-1]+'＋早期')+'／'+c['name'],group='早期の損失改善',
                description=c['name']+'。元候補'+c['source']+'の入口を使い、実決済後の早期損失だけを数える。通常担当は停止しない。管理幅だけを変更し、入口の短期支持は変更しない。')
    return out


def main():
    """
    機能: 集計・原因・全47場の利益損失収支を一つの暗色HTMLへ出力する。
    引数: なし。
    返り値: None。売買判断や会計値は再計算しない。
    """
    summarize();data=read(PUBLIC/'比較集計.json');conclusion=read(HERE/'報告の結論.json');names=labels();allrows=[]
    for folder in ('results','extra_results','early_results','recycle_results','protect_results','guard_results'):
        allrows.extend(read(HERE/f'{folder}/結果.json')['rows'])
    compact={key:{symbol:[] for symbol in ('NK225','TOPIX')} for key in names}
    for r in allrows:
        compact[r['method']][r['symbol']].append([r[k] for k in ('session','profit','loss','net','entries','max_per_side')])
    assert len(names)==data['methods'] and len(allrows)==data['accounts']
    for pair in compact.values():
        for rows in pair.values():rows.sort(key=lambda r:r[0]);assert len(rows)==47
    # ----------------------------------------
    # 最初に見る表は少数の対照と候補に限定し、全条件は下の選択欄に残す。
    table=[]
    for symbol in ('NK225','TOPIX'):
        for key in conclusion['main_methods']:
            s=data['summary'][symbol][key]['全47場']
            table.append(f'<tr><td>{"日経mini" if symbol=="NK225" else "TOPIXmini"}</td><td><button data-select="{key}">{key}</button></td><td>{money(s["net"])}</td><td>{s["reds"]}/47</td><td>{s["mean_loss"]:,.0f}</td><td>{s["max_loss"]:,.0f}</td><td>{money(s["top3_removed"])}</td></tr>')
    early=[]
    for symbol in ('NK225','TOPIX'):
        for key in conclusion['early_methods']:
            for period in ('デイ','ナイト'):
                s=data['summary'][symbol][key][period]
                early.append(f'<tr><td>{"日経mini" if symbol=="NK225" else "TOPIXmini"}</td><td><button data-select="{key}">{key}</button></td><td>{"朝" if period=="デイ" else "米国前"}</td><td>{money(s["net"])}</td><td>{s["reds"]}/{s["sessions"]}</td><td>{s["no_trade"]}</td></tr>')
    notes=''.join('<p>'+html.escape(v)+'</p>' for v in conclusion['notes'])
    examples=''.join('<p>'+html.escape(v)+'</p>' for v in conclusion['examples'])
    options=[]
    for group in dict.fromkeys(v['group'] for v in names.values()):
        options.append('<optgroup label="'+group+'">'+''.join(f'<option value="{key}">{key}｜{html.escape(v["name"])}</option>' for key,v in names.items() if v['group']==group)+'</optgroup>')
    payload=json.dumps(dict(rows=compact,summary=data['summary'],names=names),ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    page='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>待機時間・段階投入・玉別追尾の検証</title><style>
:root{color-scheme:dark;font-family:"Yu Gothic UI","Meiryo",sans-serif;background:#0b1220;color:#e5edf6}*{box-sizing:border-box}body{margin:0}main{max-width:1240px;margin:auto;padding:32px 22px 70px}h1{font-size:28px}h2{font-size:21px;margin-top:32px}p{line-height:1.7}.lead{font-size:18px}.muted,small{color:#b3c1d5}.panel{background:#121f31;border:1px solid #304259;border-radius:12px;padding:18px 22px;margin:18px 0}a,button{color:#9dccff}button{background:transparent;border:0;font:inherit;text-decoration:underline;cursor:pointer}.scroll{overflow:auto}table{border-collapse:collapse;min-width:800px;width:100%;font-size:14px}th,td{padding:9px 10px;text-align:right;border-bottom:1px solid #2c3d54;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#17283e}tfoot{background:#17283e;font-weight:bold}.up{color:#73dfbd}.down{color:#ff9c9f}select{max-width:100%;padding:10px;background:#1b2b43;color:#edf5ff;border:1px solid #52708f;border-radius:6px}details{margin:18px 0}summary{cursor:pointer;color:#b8d7ff}img{max-width:100%;height:auto;border-radius:8px}.extra{background:#202c3d}.tag{color:#e5c38b;font-size:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.grid{display:block}main{padding:20px 12px}h1{font-size:24px}}code{background:#1d2c42;padding:2px 5px}
</style></head><body><main>
<!--
[コンポーネント概要]
#method は比較する手法を選び、#description と #totals と #sessions を一緒に更新する。
#sessions は両商品の全47セッションを同一行で比較する。追加2場には色を付ける。
利益と損失は初回と追撃を一組にした費用後損益の正負。収支と累計は全建玉を含む。
詳細な設定・原因資料は折り畳み、最初の表示は結論と主要比較を優先する。
-->
<p class="muted">00139｜2026-09-21 デイ～2026-10-22 デイ｜47セッション｜手数料後</p>
<h1>待機時間・段階投入・玉別追尾の検証</h1>
<div class="panel"><p class="lead">__LEAD__</p>__NOTES__</div>
<p>両商品とも片方向上限10枚。日経は<strong>NK225mini</strong>、TOPIXは<strong>TOPIXmini</strong>。上限まで常に使う設定ではありません。__COUNT__条件を比較しました。</p>
<h2>主要比較</h2><div class="scroll"><table><thead><tr><th>商品</th><th>手法</th><th>累計収支・円</th><th>赤字場</th><th>平均赤字・円</th><th>最大赤字・円</th><th>上位3黒字除外・円</th></tr></thead><tbody>__TABLE__</tbody></table></div>
<p class="muted">B5＝主担当5枚、B2＝主担当のみ2枚（補完は従来の最大5枚）。C04＝時間帯と支持で初回を変え、後の玉ほど狭く追尾。PHA/CHA＝後の玉ほど早く利益保護を始める。手法IDを押すと全場を表示します。</p>
<h2>朝と米国開始前へ入るとどうなるか</h2>
<p>朝の主な待機理由は、二市場で63本の確定1分足を使うこと。公開遅延込みで最速09:50頃です。夜の主担当には米国寄り後22分の準備があります。早期用の短い判断を別に作ると、E01の日経初回は中央値で朝08:52頃・夜17:05頃まで早まりました。</p>
<p>下表は<strong>早期区間だけ</strong>の収支です。早期単独の無取引は明示し、通常担当と併用した完成候補の参加と区別します。</p>
<div class="scroll"><table><thead><tr><th>商品</th><th>早期手法</th><th>区間</th><th>収支・円</th><th>赤字場</th><th>無取引場</th></tr></thead><tbody>__EARLY__</tbody></table></div>
<h2>損失箇所を見て何を直したか</h2>__EXAMPLES__
<p>10月14日21:30の急変は、米東部08:30のCPI公表予定と時刻が一致します。毎夜同じ静観帯を設けると、当夜TOPIXの早期E01_L2は−32,828円から−6,492円へ改善。ただし、この修正だけで全体は黒字になりませんでした。ニュースが唯一の原因とは断定していません。<a href="https://www.bls.gov/schedule/2026/10_sched_list.htm">BLS公式発表予定</a>。</p>
<details><summary>価格図と売買の具体的な診断を見る</summary><p><a href="../../work/tranche139_20261022/保存結果の独立診断.md">追撃損失各3例の時刻・価格・枚数</a>／<a href="../../work/tranche139_20261022/early_diagnosis139_v2.md">早期入口の最大損失と再試行</a></p><img src="診断_2026-10-20_Day.png" alt="10月20日の往復と追撃の位置"><img src="診断_2026-10-15_Day.png" alt="10月15日の継続下落で早い保護が削る利益"></details>
<h2 id="account">各セッションの利益・損失・収支</h2>
<label for="method">手法を選択：</label><select id="method">__OPTIONS__</select>
<p id="description" class="muted"></p><div id="totals" class="panel"></div>
<div class="scroll"><table id="sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="4">NK225mini</th><th colspan="4">TOPIXmini</th></tr><tr><th>利益</th><th>損失</th><th>収支</th><th>累計</th><th>利益</th><th>損失</th><th>収支</th><th>累計</th></tr></thead><tbody></tbody><tfoot></tfoot></table></div>
<p class="muted">単位：円。初回＋追撃を一組として費用後損益を正負へ分類。返済注文単位の利益/損失とは異なります。追加2場は既知45場と別表示ですが、価格を既に参照したため完全未知の検証とは呼びません。</p>
<details><summary>検証範囲・未確認事項・再現資料</summary><p>段階投入46条件、早期参加16入口管理条件×単独/2併用＝48条件、利益枚数再追加8条件、追撃保護8条件、早期改善12条件×3＝36条件。計146条件、47場×2商品で13,724会計。一部対照を再利用し、条件間の同じ注文を独立標本として数えていません。</p>
<p>確定足と当時の相手市場の板のみを参照し、条件成立後の次正常気配で約定。気配差・飛び値と注文ごとの手数料を含みます。NKminiは1pt100円・片道38.5円/枚、TOPIXminiは1pt1,000円・片道41.8円/枚。約定価格は保存されたラージ気配による代理です。</p>
<p>Rは初回判断時に固定する値幅単位。通常は公表済みATR、早期は確定1分足の3～5本の値幅から算出し、最低幅は日経20円・TOPIX1ptです。幅2倍条件だけ管理用Rを2倍にします。</p>
<p>実mini板の全期間、未知期間の利益、Go本体で数量変化が全判断へ戻る経路は未確認。今回は因果的な元通知と、新造した早期入口に数量・出口層を接続した検証です。保有中に発生した別の入口は見送ります。アプリへの組込み前にGoで同じ注文列を再現する確認が必要です。</p>
<p>全試行は再生前に仕様とソース指紋を登録。監査で見つかった保護幅設定は金融前に修正・再登録し、旧計画は未実行で保存。APIでの現在セッション取得0、実注文0。稼働アプリとdistは変更していません。</p>
<p><a href="README.md">読む順序と再現資料</a>／<a href="比較集計.json">全条件の比較集計</a>／<a href="../../work/tranche139_20261022/独立監査概要.md">主比較・早期・追撃保護の独立監査</a>／<a href="../../work/tranche139_20261022/recycle_financial_audit139.json">再追加の独立監査</a></p></details>
<p><a href="../index.html">調査一覧へ戻る</a></p>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
/**
 * 円額を日本語表示用に整える。
 * @param {number} value - 円額。
 * @returns {string} 桁区切りした整数。
 */
function yen(value){return Math.round(value).toLocaleString('ja-JP');}
/**
 * 符号付き損益のセルを作成する。
 * @param {number} value - 円額。
 * @returns {string} HTMLの表セル。
 */
function cell(value){return '<td class="'+(value<0?'down':value>0?'up':'')+'">'+(value>0?'+':'')+yen(value)+'</td>';}
/**
 * 選択した手法の全場と既知・追加期間の集計を表示する。
 * @returns {void} 表示更新のみ。売買や会計の再計算はしない。
 */
function render(){const key=document.getElementById('method').value;document.getElementById('description').textContent=data.names[key].description;
let body='',total={NK225:[0,0,0],TOPIX:[0,0,0]};
data.rows[key].NK225.forEach((row,i)=>{const extra=row[0]>='2026-10-21_Night';body+='<tr'+(extra?' class="extra"':'')+'><td>'+row[0].replace('_Day',' デイ').replace('_Night',' ナイト')+(extra?' <span class="tag">追加</span>':'')+'</td>';['NK225','TOPIX'].forEach(s=>{const r=data.rows[key][s][i];total[s][0]+=r[1];total[s][1]+=r[2];total[s][2]+=r[3];body+='<td>'+yen(r[1])+'</td><td>'+yen(r[2])+'</td>'+cell(r[3])+cell(total[s][2]);});body+='</tr>';});
document.querySelector('#sessions tbody').innerHTML=body;let foot='<tr><td>全47場合計</td>';['NK225','TOPIX'].forEach(s=>{foot+='<td>'+yen(total[s][0])+'</td><td>'+yen(total[s][1])+'</td>'+cell(total[s][2])+cell(total[s][2]);});document.querySelector('#sessions tfoot').innerHTML=foot+'</tr>';
let info='';['NK225','TOPIX'].forEach(s=>{const a=data.summary[s][key];info+='<p><strong>'+s+'：</strong>'+['既知45場','追加2場','全47場'].map(g=>g+' '+(a[g].net>0?'+':'')+yen(a[g].net)+'円（赤字'+a[g].reds+'/'+a[g].sessions+'・無取引'+a[g].no_trade+'）').join(' ／ ')+'<br><small>全場：平均赤字'+yen(a['全47場'].mean_loss)+'円・中央赤字'+yen(a['全47場'].median_loss)+'円・最大赤字'+yen(a['全47場'].max_loss)+'円。買い収支'+yen(a['全47場'].buy)+'円／売り収支'+yen(a['全47場'].sell)+'円。実測最大片方向'+a['全47場'].max_per_side+'枚。</small></p>';});document.getElementById('totals').innerHTML=info;}
document.getElementById('method').addEventListener('change',render);
document.querySelectorAll('[data-select]').forEach(button=>button.addEventListener('click',()=>{document.getElementById('method').value=button.dataset.select;render();document.getElementById('account').scrollIntoView({behavior:'smooth'});}));
document.getElementById('method').value='__DEFAULT__';render();
</script></main></body></html>'''
    replacements={'__LEAD__':html.escape(conclusion['lead']),'__NOTES__':notes,'__COUNT__':str(len(names)),'__TABLE__':''.join(table),'__EARLY__':''.join(early),
        '__EXAMPLES__':examples,'__OPTIONS__':''.join(options),'__DATA__':payload,'__DEFAULT__':conclusion['default']}
    for k,v in replacements.items():page=page.replace(k,v)
    assert '__DATA__' not in page
    for name in ('診断_2026-10-20_Day.png','診断_2026-10-15_Day.png'):shutil.copyfile(HERE/name,PUBLIC/name)
    (PUBLIC/'段階投入と早期参加の全セッション損益.html').write_text(page,encoding='utf-8')
    print('HTML作成',len(names),'条件',len(allrows),'会計',flush=True)


if __name__=='__main__':main()
