"""保存済み金融の集計だけから、短い説明と全33場の暗色表を作成する。"""

import hashlib
from html import escape
import json

import plan


LABELS = {
    'A_ALL_TYPE0': 'A 初回活動から逆売買', 'B_NEVER_BELOW': 'B 元の数量条件から逆売買', 'C_SAME_SIDE_DEPTH': 'C 元の同方向数量条件から逆売買',
    'E1_TP2_SL2': '① 全量2Tで利確', 'E2_TP4_SL2': '② 全量4Tで利確',
    'E3_ARM3_TRAIL1': '③ 3T後に1T追尾', 'E4_HALF2_TRAIL1': '④ 2Tで半分、残り追尾'}


def reference_table(result: dict) -> tuple[str, dict]:
    """
    機能: 旧時刻での全注文反転の参考会計と、新方向で出口を再判定した結果を分ける。
    引数: result(dict) は新116の完結結果。
    返り値: tuple[str,dict] は事前主候補の比較HTMLと参考会計の指紋。
    """
    path = plan.HERE/'mirror/固定時刻で買売を反転した十二条件の参考会計.json'
    raw = path.read_bytes()
    mirror = json.loads(raw.decode('utf-8'))
    assert mirror['全合格'] is True and mirror['新金融'] == 0
    assert mirror['sessions'] == result['sessions']
    original_id = result['主候補'].replace('QREVERSE_', 'QEXEC_', 1)
    rows = []
    for symbol, label in (('TOPIX','TOPIXミニ10枚'),('NK225','日経マイクロ20枚')):
        base = mirror['aggregate'][original_id]['symbols'][symbol]
        live = result['aggregate'][result['主候補']][symbol]['全場']
        rows.append('<tr><td>'+label+'</td><td>'+format(base['元会計']['収支'],',.0f')+'</td><td>'+
            format(base['固定時刻反転']['収支'],',.0f')+'</td><td>'+format(live['aggregate']['収支'],',.0f')+
            '</td><td>'+str(live['losing_sessions'])+'/33</td></tr>')
    html = ('<h2>事前主候補C＋半分利確・追尾の反転比較</h2><div class="scroll"><table><thead><tr>'
        '<th>商品</th><th>元の収支 円</th><th>同じ時刻で全注文を反転 円</th><th>新方向で出口も再判定 円</th>'
        '<th>再判定の赤字場</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
        '<p class="muted">同じ時刻の列は、保存された新規・返済の時刻と分割枚数を保ち、各時点の逆方向の気配で再会計した参考値です。'
        '元手法の仮想運転指示を逆注文する仕組みは理論上可能ですが、独立した影モデルの再生を追加した結果ではありません。'
        '新方向で出口を再判定する列が今回の新しい実運転模型で、返済・場停止・後続の入口も変わります。</p>')
    return html, dict(path=path.relative_to(plan.ROOT).as_posix(), SHA256=hashlib.sha256(raw).hexdigest())


def main() -> None:
    """
    機能: 完成した792口座の同bytesを一回読み、全条件・全場を公開する。
    引数: なし。
    返り値: None。元NPZ・台帳・金融再生を読み直さない。
    """
    path = plan.HERE / 'finance/結果.json'
    raw = path.read_bytes()
    result = json.loads(raw.decode('utf-8'))
    assert result['全合格'] and result['counts']['新金融口座'] == 792
    assert len(result['rows']) == 792 and len(result['sessions']) == 33
    plan.PUBLIC.mkdir(parents=True, exist_ok=True)
    target = plan.PUBLIC / '売買反転した十二手法と全セッション損益.html'
    assert not target.exists()
    public = dict(全合格=True, 元結果SHA256=hashlib.sha256(raw).hexdigest(),
        主候補=result['主候補'], sessions=result['sessions'], rows=result['rows'],
        aggregate=result['aggregate'], configs=result['configs'], counts=result['counts'])
    text = json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    jp = plan.PUBLIC / '売買反転の公開会計.json'
    assert not jp.exists()
    jp.write_text(text, encoding='utf-8')
    short = []
    for config in result['configs']:
        case = config['id']
        line = dict(id=case)
        for symbol in ('TOPIX', 'NK225'):
            all_days = result['aggregate'][case][symbol]['全場']
            line[symbol] = {key: all_days[key] for key in (
                'mean_session_net_yen', 'positive_sessions', 'losing_sessions', 'no_trade_sessions',
                'mean_positive_session_net_yen', 'worst_negative_session_abs_yen', 'all_main_targets')}
            line[symbol].update(利益割合=all_days['aggregate']['利益割合'], 収支=all_days['aggregate']['収支'])
        short.append(line)
    both = sum(all(result['aggregate'][c['id']][s]['全場']['all_main_targets'] for s in ('TOPIX','NK225')) for c in result['configs'])
    main_case = result['主候補']
    main_values = {s: result['aggregate'][main_case][s]['全場'] for s in ('TOPIX','NK225')}
    conclusion = f'両銘柄の目標を同時に満たした条件は{both}／12。'
    if both == 0:
        conclusion += '売買を反転するだけでは、毎場安定した利益を確認できませんでした。'
    else:
        conclusion += '既知33場の探索結果であり、未知期間の保証ではありません。'
    template = r'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>売買を反転した結果と全セッション損益</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#10151e;color:#e4ebf4;font:16px/1.65 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:24px}h1{font-size:26px}h2{font-size:20px;margin-top:28px}a{color:#8fc7ff}p{max-width:1080px}.call{padding:16px;border-left:4px solid #e4b866;background:#1c2432}.muted{color:#b5c1d2;font-size:14px}.scroll{overflow-x:auto;border:1px solid #384459;border-radius:6px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-variant-numeric:tabular-nums;font-size:14px}th,td{padding:8px 11px;border-bottom:1px solid #334055;text-align:right}th{background:#242f41;color:#dce8fa}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#151f2c}tfoot{background:#283547;font-weight:bold}.pos{color:#79e0ac}.neg{color:#ff9eaa}select{background:#202e40;color:#fff;padding:8px;border:1px solid #71849e;font-size:16px;max-width:100%}details{margin-top:24px}summary{cursor:pointer;color:#95c9ff}.grid{display:flex;gap:14px;flex-wrap:wrap}.card{background:#1b2636;flex:1;min-width:240px;padding:16px}.card strong{font-size:23px;display:block}.small{font-size:13px}button{cursor:pointer;background:#28445d;color:#eef8ff;border:1px solid #6484a3;padding:8px}
</style></head><body><main>
<p class="muted">作業00116・既知33セッション／TOPIXミニ上限10枚・日経マイクロ上限20枚</p>
<h1>全部赤字だった手法を、売買反転すれば勝てるか</h1>
<p class="call">__CONCLUSION__</p>
<p>元の3入口の審査はそのままに、実際の新規方向だけ買い↔売りを交換。4つの出口・トレーリング・場損益停止を、新しい建玉の損益で再判定しました。手数料・枚数・約定の遅れ方は元と同じです。</p>
<p class="muted">売買を反転しても、買いはask・売りはbidです。気配差と手数料は残ります。T＝ラージ観測の1呼値（TOPIX 0.5pt・日経10円）。</p>
__REFERENCE__
<div class="grid" id="cards"></div>
<h2>全33セッションの利益・損失・収支</h2>
<p><label for="case">手法：</label><select id="case"></select> <button id="reset">事前の主候補へ</button></p>
<p id="choice" class="muted"></p>
<div class="scroll"><table id="sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="5">TOPIXミニ10枚</th><th colspan="5">日経マイクロ20枚</th></tr><tr><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>利益枚</th><th>損失枚</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>利益枚</th><th>損失枚</th></tr></thead><tbody></tbody><tfoot></tfoot></table></div>
<p class="muted">金額は全返済した一組の収支を正負へ分け、両建てや分割返済で損失を隠しません。枚数は各返済脚の手数料後の正負です。利益枚−損失枚は金額収支を表しません。無取引は勝ちに含めません。</p>
<h2>12条件の比較</h2><div class="scroll"><table id="comparison"><thead><tr><th>入口／出口</th><th>TOPIX 平均円／場</th><th>利益割合</th><th>赤字場</th><th>日経 平均円／場</th><th>利益割合</th><th>赤字場</th></tr></thead><tbody></tbody></table></div>
<details><summary>条件と確認範囲</summary><p>出口①＝2Tで全利確・2T損切り。②＝4Tで全利確・2T損切り。③＝3T順行後に1T追尾、初期損切り2T。④＝2Tで半分返済、残りを1T追尾、初期損切り2T。全て実際の新規価格を基準に判定し、返済判断後の次の執行可能な原行で約定。線の値段どおりに約定する保証はありません。</p><p>Day09:15・Night17:05から新規、米国通常寄付前後15分は静観、場内で返済。場純損益の損失停止は初期名目額の0.125%、利益停止は0.375%。開始時の初回有効価格から固定し、将来の高安は使いません。各実注文ごとにTOPIX 41.8円／枚・日経11円／枚を1円未満切捨てで課金します。</p><p>目標：利益金額割合65%以上、赤字場20%以下、最大赤字が平均黒字場以下、TOPIX全場平均＋10万円。日経の最低金額は未指定。追加2場、実ミニ・マイクロ板、約定待ち順、実遅延は未測定。自身の原行順と価格時計による再生で、真の受信時計を証明していません。</p><p><a href="手法の簡単な説明.md">手法の説明</a> · <a href="反転しても残った損失の具体例.md">負けた板の時刻と原因</a> · <a href="売買反転の公開会計.json">公開会計</a> · <a href="README.md">再現資料と確認範囲</a></p></details>
<p class="muted small">原入力66・保存公開66を各1読、12条件×33場×2商品＝792口座。未来の先着結果はアルゴリズムに渡していません。全て同じ既知期間であり、792口座を独立した標本とは数えません。</p>
</main><script>
const D=__DATA__,L=__LABELS__,PRIMARY=D.主候補;
/**
 * 機能: 金額を日本語の三桁区切りで表示する。
 * @param {number|null} n - 金額又は未知。
 * @returns {string} 表示文字列。
 */
function yen(n){return n===null?'—':Math.round(n).toLocaleString('ja-JP');}
/**
 * 機能: 割合を百分率へ変換する。
 * @param {number|null} n - 割合又は分母なし。
 * @returns {string} 表示文字列。
 */
function pct(n){return n===null?'—':(100*n).toFixed(1)+'%';}
/**
 * 機能: 正負に応じた表示色を返す。
 * @param {number} n - 収支。
 * @returns {string} 色class。
 */
function color(n){return n>0?'pos':n<0?'neg':'';}
/**
 * 機能: 手法の入口と出口を平易な名前へ変換する。
 * @param {object} c - 固定条件。
 * @returns {string} 表示名。
 */
function name(c){return L[c.entry_id]+' ／ '+L[c.exit_id];}
/**
 * 機能: 選択した手法の全33場・合計・安定性を表示する。
 * @param {string} id - 手法ID。
 * @returns {void} 表を更新する。
 */
function draw(id){
 const conf=D.configs.find(c=>c.id===id),rr=D.rows.filter(r=>r.case===id),a=D.aggregate[id];
 document.getElementById('choice').textContent=id+(id===PRIMARY?'（金融結果を見る前に決めた主候補）':'（同じ期間の比較条件）');
 let body='',total=[0,0,0,0,0,0,0,0,0,0];
 D.sessions.forEach(s=>{let cells=[];['TOPIX','NK225'].forEach(sym=>{let r=rr.find(r=>r.session===s&&r.symbol===sym);cells.push(r.利益,r.損失,r.収支,r.勝ち枚数,r.負け枚数);});cells.forEach((v,i)=>total[i]+=v);body+='<tr><td>'+s.replace('_Day',' デイ').replace('_Night',' ナイト')+'</td>'+cells.map((v,i)=>'<td class="'+((i===2||i===7)?color(v):'')+'">'+yen(v)+'</td>').join('')+'</tr>';});
 document.querySelector('#sessions tbody').innerHTML=body;document.querySelector('#sessions tfoot').innerHTML='<tr><td>全33場合計</td>'+total.map((v,i)=>'<td class="'+((i===2||i===7)?color(v):'')+'">'+yen(v)+'</td>').join('')+'</tr>';
 document.getElementById('cards').innerHTML=['TOPIX','NK225'].map(sym=>{let m=a[sym].全場;return '<div class="card">'+(sym==='TOPIX'?'TOPIXミニ10枚':'日経マイクロ20枚')+'<strong class="'+color(m.mean_session_net_yen)+'">平均 '+yen(m.mean_session_net_yen)+'円／場</strong>利益割合 '+pct(m.aggregate.利益割合)+' ／ 赤字 '+m.losing_sessions+'/33場<br>平均黒字 '+yen(m.mean_positive_session_net_yen)+'円 ／ 最大赤字 '+yen(m.worst_negative_session_abs_yen)+'円<br><span class="small">上位3黒字場を除く平均 '+yen(a[sym].上位3黒字場除外.mean_session_net_yen)+'円</span></div>';}).join('');
}
// ----------------------------------------
const select=document.getElementById('case');D.configs.forEach(c=>{let o=document.createElement('option');o.value=c.id;o.textContent=name(c);select.appendChild(o);});select.value=PRIMARY;select.addEventListener('change',()=>draw(select.value));document.getElementById('reset').addEventListener('click',()=>{select.value=PRIMARY;draw(PRIMARY);});
document.querySelector('#comparison tbody').innerHTML=D.configs.map(c=>{let a=D.aggregate[c.id];return '<tr><td>'+name(c)+'</td>'+['TOPIX','NK225'].map(sym=>{let m=a[sym].全場;return '<td class="'+color(m.mean_session_net_yen)+'">'+yen(m.mean_session_net_yen)+'</td><td>'+pct(m.aggregate.利益割合)+'</td><td>'+m.losing_sessions+'/33</td>';}).join('')+'</tr>';}).join('');draw(PRIMARY);
</script></body></html>'''
    script_data = json.dumps(public, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<','\\u003c')
    reference, reference_info = reference_table(result)
    html = template.replace('__CONCLUSION__', escape(conclusion)).replace('__REFERENCE__', reference).replace('__DATA__', script_data).replace('__LABELS__', json.dumps(LABELS,ensure_ascii=False))
    target.write_text(html, encoding='utf-8')
    plan.write(plan.HERE / '全十二条件と全三十三場の公開射影.json', dict(全合格=True, 結果SHA256=hashlib.sha256(raw).hexdigest(),
        HTML=dict(path=target.relative_to(plan.ROOT).as_posix(),SHA256=plan.digest(target)),
        公開会計=dict(path=jp.relative_to(plan.ROOT).as_posix(),SHA256=plan.digest(jp)),
        同時主目標合格=both, main=main_values, conditions=short, 固定時刻の参考会計=reference_info, 金融再生=0, 結果JSON一読=1, 原NPZ=0))
    print(json.dumps(dict(全合格=True, 同時主目標合格=both, conditions=short),ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
