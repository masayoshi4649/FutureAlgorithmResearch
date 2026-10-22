"""固定結果JSONから短い説明と全984場レコードを含むHTMLを生成する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import html
import json
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PUBLIC=ROOT/'アルゴリズム調査/00125_毎日参加と両銘柄の利益率改善'
TARGET=PUBLIC/'毎日参加する三系統と全セッション損益.html'
DEFAULT_GOAL='目標：各セッションで両商品それぞれ通常数量を1回以上新規し、平均で場始価格の0.5%以上の獲得幅。手数料0、売買気配差は反映。'
FAMILY_TEXT={
    'A':'両市場の強い進行を確認し、押し戻り後の再進行で建て、支持破れか利益追尾で降ります。',
    'B':'安値からの反発で買い、高値からの反落で売り、逆向きへ動けば旧玉を返して持ち替えます。',
    'C':'進行が強ければ追従、往復なら帯の端から中心への戻りを狙い、その時点の状態で切り替えます。',
}


def sha(payload: bytes) -> str:
    """
    機能: 入力と生成物の指紋を求める。
    引数: payload(bytes)は内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def totals(rows: list[dict]) -> dict:
    """
    機能: 固定全41場を分母に損益・活動・枚数を再集計する。
    引数: rows(list[dict])は同一商品・同一条件の41保存小会計。
    返り値: dictは円額・件数と、上限数量換算の獲得幅を場始価格で割った比率。
    """
    assert len(rows)==41
    measured=[r for r in rows if r.get('net') is not None]
    active=[r for r in measured if r['entry_quantity']>0]
    positive=[r for r in measured if r['net']>0]
    red=[r for r in measured if r['net']<0]
    excluded={r['session'] for r in sorted(positive,key=lambda r:(-r['net'],r['session']))[:3]}
    normalized=[r['net']/r['rate_components']['capacity_notional'] for r in measured]
    def width(row: dict) -> float:
        """
        機能: 円収支を固定上限数量の価格幅へ換算する。
        引数: row(dict)は倍率と上限数量を含む名目額成分を持つ小会計。
        返り値: floatは価格のポイント又は円の獲得幅。
        """
        components=row['rate_components']
        return row['net']/(components['capacity_notional']/components['reference_price'])
    all_participation=sum(r['entry_quantity']>=(5 if r['symbol']=='TOPIX' else 10) and
        r.get('summary',{}).get('unclosed_quantity',0)==0 for r in measured)
    remaining=[r for r in measured if r['session'] not in excluded]
    mean_price_pct=sum(normalized)*100/41
    return dict(sessions=41,measured=len(measured),missing=41-len(measured),active=len(active),inactive=len(measured)-len(active),
        profit=sum(r['profit'] for r in measured),loss=sum(r['loss'] for r in measured),net=sum(r['net'] for r in measured),
        mean=sum(r['net'] for r in measured)/41,median=statistics.median(r['net'] for r in measured) if measured else None,
        black=len(positive),red=len(red),zero=sum(r['net']==0 for r in measured),
        active_zero=sum(r['net']==0 and r['entry_quantity']>0 for r in measured),
        worst=min([0]+[r['net'] for r in measured]),net_without_top3=sum(r['net'] for r in measured if r['session'] not in excluded),
        entry_quantity=sum(r['entry_quantity'] for r in measured),win_quantity=sum(r['win_quantity'] for r in measured),
        loss_quantity=sum(r['loss_quantity'] for r in measured),forced_groups=sum(r['forced_groups'] for r in measured),
        signal_groups=sum(r['signal_groups'] for r in measured),normal_groups=sum(r['normal_groups'] for r in measured),
        proxy_groups=sum(r['proxy_groups'] for r in measured),fees=sum(r['fees'] for r in measured),
        mean_width=sum(width(r) for r in measured)/41,mean_price_pct=mean_price_pct,
        median_price_pct=statistics.median(normalized)*100 if normalized else None,
        participation=all_participation,goal_pass=len(measured)==41 and all_participation==41 and mean_price_pct>=.5,
        without_top3_mean_price_pct=sum(r['net']/r['rate_components']['capacity_notional'] for r in remaining)*100/len(remaining) if remaining else None,
        without_top3_mean_width=sum(width(r) for r in remaining)/len(remaining) if remaining else None,
        without_top3_sessions=len(remaining),
        rank_normalized_median=statistics.median(normalized) if normalized else float('-inf'),
        rank_normalized_net=sum(normalized))


def make_data(result: dict,diagnosis: dict | None) -> dict:
    """
    機能: 全件埋込を保持し、家族ごとの比較代表を固定順位で選ぶ。
    引数: result(dict)は完成結果、diagnosis(dict|None)は任意の短診断。
    返り値: dictは表示用データ。相手商品の損失を合算で隠さない。
    """
    assert result['passed'] and len(result['rows'])==984 and len(result['specs'])==12 and len(result['sessions'])==41
    assert len({(r['symbol'],r['session'],r['method']) for r in result['rows']})==984
    grouped=defaultdict(list)
    for row in result['rows']:
        assert row['symbol'] in ('TOPIX','NK225') and row['rate_components']['capacity_notional']>0
        assert row['fees']==0,'手数料ゼロの今回結果だけを掲載する'
        grouped[row['method'],row['symbol']].append(row)
    metrics={s['id']:{symbol:totals(grouped[s['id'],symbol]) for symbol in ('TOPIX','NK225')} for s in result['specs']}

    # ----------------------------------------
    # 多い方の赤字場数→低い方の正規化中央値→正規化合計。比較順位だけに使う。
    def rank(method: str) -> tuple:
        """
        機能: 両商品のうち弱い側を優先する事前指定順位を返す。
        引数: method(str)は固定条件ID。
        返り値: tupleは小さいほど上位の順位キー。
        """
        pair=metrics[method]
        return (max(pair[s]['red'] for s in pair),-min(pair[s]['rank_normalized_median'] for s in pair),
                -sum(pair[s]['rank_normalized_net'] for s in pair),method)
    picks={family:min((s['id'] for s in result['specs'] if s['family']==family),key=rank) for family in ('A','B','C')}
    return dict(specs=result['specs'],sessions=result['sessions'],rows=result['rows'],metrics=metrics,family_picks=picks,
        family_text=FAMILY_TEXT,diagnosis=diagnosis or {},records=984,
        ranking='各家族内で、両商品の多い方の赤字場数が少ない順→低い方の価格比中央値が高い順→価格比合計が高い順。価格比は、円収支÷（固定上限枚数×倍率）で得た獲得幅を場始価格で割ったもの。',
        goal_methods={symbol:[s['id'] for s in result['specs'] if metrics[s['id']][symbol]['goal_pass']] for symbol in ('TOPIX','NK225')},
        joint_goal_methods=[s['id'] for s in result['specs'] if all(metrics[s['id']][symbol]['goal_pass'] for symbol in ('TOPIX','NK225'))])


def build_html(data: dict,goal_note: str) -> str:
    """
    機能: 全41場の選択表と984行JSONを含む外部接続不要の暗色HTMLを組み立てる。
    引数: data(dict)は固定表示値、goal_note(str)は根の目標定義に関する表示文。
    返り値: strは自己完結HTML。
    """
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
    return '''<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>毎日参加する三系統と全セッション損益</title>
<style>
:root{color-scheme:dark;--bg:#10151e;--panel:#192231;--line:#334158;--text:#edf2f9;--muted:#acbdd3;--green:#75e4b0;--red:#ff969c;--blue:#9bc7ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 system-ui,"Yu Gothic",sans-serif}
main{max-width:1420px;margin:auto;padding:28px 24px 55px}h1{font-size:26px;margin:0 0 10px}h2{font-size:19px;margin:28px 0 10px}
p{margin:8px 0}.muted,small{color:var(--muted)}.notice{padding:13px 16px;border-left:4px solid var(--blue);background:#1b2a40;margin:16px 0}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.card{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:15px}.card strong{font-size:19px}
.card p{margin:5px 0}.card button{margin-top:9px}.scroll{width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;white-space:nowrap;font-size:14px}th,td{padding:9px 11px;border-bottom:1px solid #2b384b;text-align:right}
th{background:#202d40;color:#c8d9f1;font-weight:600}th:first-child,td:first-child{text-align:left}tbody tr:nth-child(even){background:#151f2d}tbody tr:hover{background:#26384f}
tbody tr.selected{outline:2px solid #779fcf;outline-offset:-2px}tfoot{font-weight:700;background:#1e2e43}.pos{color:var(--green)}.neg{color:var(--red)}.zero{color:var(--muted)}
button,select{font:inherit;color:var(--text);background:#26384f;border:1px solid #5a7497;border-radius:5px;padding:7px 11px}button{cursor:pointer}button:hover{background:#355174}
label{display:inline-flex;gap:9px;align-items:center;margin:0 17px 8px 0}.controls{margin:14px 0 8px}select{max-width:100%}.nowrap{white-space:nowrap}.summary-line{font-weight:600;margin:10px 0}
details{background:#192332;border:1px solid var(--line);border-radius:7px;padding:9px 13px;margin:9px 0}summary{cursor:pointer}details p{white-space:pre-wrap}.foot{margin-top:19px;font-size:13px;color:var(--muted)}
@media(max-width:850px){main{padding:18px 12px 35px}h1{font-size:22px}.cards{grid-template-columns:1fr}table{font-size:13px}th,td{padding:8px}label{display:flex}select{flex:1;min-width:0}}
</style>
<!--
[コンポーネント概要]
#family-cards は三家族の短い説明と既知選択の比較代表を表示します。
#summary-body は全十二条件を両商品で対比する一覧です。
#method と #symbol は当該方法・商品の全四十一場表を切り替えます。
#session-body と #session-total は費用後損益と数量、根拠・期限、通常・代理を表示します。
#diagnosis は親調査の保存診断だけを表示します。未提供時は未掲載と記します。
#report-data は全九百八十四場レコードの唯一の埋込データです。外部通信を行いません。
-->
<main><h1>毎日参加する三系統と全セッション損益</h1>
<p class="muted">3家族 × 4条件。TOPIXミニ初回5枚・上限10枚／日経マイクロ初回10枚・上限20枚。手数料0・売買気配差込み。</p>
<div class="notice">'''+html.escape(goal_note)+'''</div>
<p id="goal-outcome" class="summary-line"></p>
<p class="muted">価格比＝〔収支÷（上限枚数×倍率）〕÷場始値。場始値は当場最初の採用Last。TOPIXが4000なら0.5%は20pt、日経が65000なら325円です。各場の価格比を41場で単純平均し、数量だけ増やした見かけの合格を避けます。</p>
<p>通常の入口がなければ開始30分後から期限参加。広い気配では待機し、未参加を勝ちに数えません。保有時間で利確せず、撤回・利益追尾・場末返済で終えます。</p>
<h2>各家族の比較代表</h2><p class="muted">既知41場を見て各家族から1条件を選択。将来の最良手法や目標達成を示す選抜ではありません。</p>
<div class="cards" id="family-cards"></div>
<h2>全12条件の比較</h2><p class="muted">平均は損失・無取引を含む41場。平均欄の下段は価格比。黒／赤／零／無は黒字場／赤字場／取引あり収支0／無取引場です。</p>
<div class="scroll"><table><thead><tr><th>方法</th><th>TOPIX 合計</th><th>平均円／価格比</th><th>中央値</th><th>黒／赤／零／無</th><th>日経 合計</th><th>平均円／価格比</th><th>中央値</th><th>黒／赤／零／無</th></tr></thead><tbody id="summary-body"></tbody></table></div>
<h2>全セッションの利益・損失・収支</h2>
<div class="controls"><label>方法<select id="method"></select></label><label>商品<select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">日経マイクロ</option></select></label></div>
<p id="method-description" class="muted"></p><p id="selected-summary" class="summary-line"></p>
<div class="scroll"><table><thead><tr><th>セッション</th><th>利益</th><th>損失</th><th>収支</th><th>獲得幅／価格比</th><th>勝／負 枚数</th><th>新規 枚数</th><th>根拠／期限 群</th><th>通常／代理 群</th><th>最大買／売 枚数</th></tr></thead><tbody id="session-body"></tbody><tfoot id="session-total"></tfoot></table></div>
<p class="muted">「群」は初回・追加から全返済まで。勝負枚数は各群の最終保有枚数をその収支の符号で分類。全玉の損失を含みます。通常は引け6分前から返済を予約。代理は通常の次行がない場合に、6分窓内の最終BBOで別精算します。</p>
<h2>具体的な損失箇所</h2>
<div id="diagnosis-conclusion"><p>C00の負け群はTOPIX187群中120群、日経203群中129群が一度は含み益。そのうち119・128群は追尾開始の1wに届く前に反転しました。一度も黒字にならない負けも67・74群あり、今回の経路では出口だけで黒字化できない負けも残ります。</p>
<p>手数料は0で、売買気配差の負担と方向判断の失敗が残ります。買売を逆にした事後参考も24商品条件すべて累計赤字でした。ただし元の返済時刻を借りた対照であり、実際に動かす反転戦略の成績ではありません。</p></div>
<div id="diagnosis"></div>
<details><summary>比較代表の選び方と適用範囲</summary><p id="ranking-note"></p><p>全41場は既知データ内の開発比較です。相手の足は公開時刻が1分以上先行し、年齢120秒以内のものだけを使います。実ミニ・マイクロ板、真の二市場受信順、自己注文の待ち順位は未観測です。</p></details>
<p class="foot" id="record-count"></p><p class="foot">平均0.5%と全41場の通常数量参加を商品別に判定します。以前の金額利益65%・赤字20%は今回の合格条件へ追加していません。</p>
</main><script id="report-data" type="application/json">'''+payload+'''</script><script>
'use strict';
const DATA=JSON.parse(document.getElementById('report-data').textContent);
const nf=new Intl.NumberFormat('ja-JP',{maximumFractionDigits:0});

/**
 * 機能: HTMLへ埋める文字列の特殊記号を無害化します。
 * @param {unknown} value - 保存文字列。
 * @returns {string} エスケープした文字列。
 */
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

/**
 * 機能: 円額の符号と桁を統一します。
 * @param {number|null} value - 費用後円額。
 * @returns {string} 円額又は未測定。
 */
function money(value){return value===null||value===undefined?'未測定':(value>0?'+':'')+nf.format(value===0?0:value)+'円';}

/**
 * 機能: 損益の表示色を選びます。
 * @param {number|null} value - 費用後円額。
 * @returns {string} 表示クラス。
 */
function tone(value){return value>0?'pos':value<0?'neg':'zero';}

/**
 * 機能: 収支セルを生成します。
 * @param {number|null} value - 円額。
 * @returns {string} 表のセルHTML。
 */
function yenCell(value){return '<td class="'+tone(value)+'">'+money(value)+'</td>';}

/**
 * 機能: 価格比をパーセント表記にします。
 * @param {number|null} value - パーセント単位の数値。
 * @returns {string} 符号付き価格比。
 */
function pct(value){return value===null||value===undefined?'未測定':(value>0?'+':'')+value.toFixed(3)+'%';}

/**
 * 機能: 平均円と平均価格比を同じセルへ表示します。
 * @param {object} m - 41場の固定集計。
 * @returns {string} 表のセルHTML。
 */
function averageCell(m){return '<td class="'+tone(m.mean)+'">'+money(m.mean)+'<br><small>'+pct(m.mean_price_pct)+'</small></td>';}

/**
 * 機能: セッション名を短い日本語にします。
 * @param {string} value - 保存セッション名。
 * @returns {string} 日本語の場名。
 */
function scene(value){return value.replace('_Day',' デイ').replace('_Night',' ナイト');}

/**
 * 機能: 一覧とカードから同じ全場表へ移動します。
 * @param {string} method - 固定方法ID。
 * @returns {void} 返り値はありません。
 */
function selectMethod(method){document.getElementById('method').value=method;renderSessions();}

/**
 * 機能: 三家族の説明と各比較代表を表示します。
 * @returns {void} 返り値はありません。
 */
function renderCards(){
  document.getElementById('family-cards').innerHTML=['A','B','C'].map(f=>{
    const id=DATA.family_picks[f],pair=DATA.metrics[id],t=pair.TOPIX,n=pair.NK225;
    return '<article class="card"><strong>'+f+'：'+esc(id)+'</strong><p>'+esc(DATA.family_text[f])+'</p>'+
      '<p>TOPIX平均 <span class="'+tone(t.mean)+'">'+money(t.mean)+'</span>（'+pct(t.mean_price_pct)+'）／赤字 '+t.red+'/41場</p>'+
      '<p>日経平均 <span class="'+tone(n.mean)+'">'+money(n.mean)+'</span>（'+pct(n.mean_price_pct)+'）／赤字 '+n.red+'/41場</p>'+
      '<button type="button" data-method="'+id+'">この方法の全場を見る</button></article>';
  }).join('');
  document.querySelectorAll('[data-method]').forEach(button=>button.addEventListener('click',()=>selectMethod(button.dataset.method)));
}

/**
 * 機能: 全十二条件の両商品比較と方法選択肢を表示します。
 * @returns {void} 返り値はありません。
 */
function renderSummary(){
  document.getElementById('method').innerHTML=DATA.specs.map(s=>'<option value="'+esc(s.id)+'">'+esc(s.id+' '+s.name)+'</option>').join('');
  document.getElementById('summary-body').innerHTML=DATA.specs.map(s=>{
    const t=DATA.metrics[s.id].TOPIX,n=DATA.metrics[s.id].NK225;
    return '<tr data-summary-method="'+s.id+'"><td><button type="button" data-open="'+s.id+'">'+s.id+'</button></td>'+
      yenCell(t.net)+averageCell(t)+yenCell(t.median)+'<td>'+t.black+'／'+t.red+'／'+t.active_zero+'／'+t.inactive+'</td>'+
      yenCell(n.net)+averageCell(n)+yenCell(n.median)+'<td>'+n.black+'／'+n.red+'／'+n.active_zero+'／'+n.inactive+'</td></tr>';
  }).join('');
  document.querySelectorAll('[data-open]').forEach(button=>button.addEventListener('click',()=>selectMethod(button.dataset.open)));
}

/**
 * 機能: 親調査の具体的損失を商品・方法に合わせて表示します。
 * @param {string} method - 選択方法。
 * @param {string} symbol - 選択商品。
 * @returns {void} 返り値はありません。
 */
function renderDiagnosis(method,symbol){
  const input=DATA.diagnosis.items||[];
  const matching=input.filter(r=>r.symbol===symbol&&(!r.method||r.method===method));
  const shared=matching.length===0;
  const items=(shared?input.filter(r=>r.symbol===symbol):matching).slice(0,3);
  const note=shared&&items.length?'<p class="muted">共通の損失診断：以下の対象方法は '+esc(items[0].method)+'。現在選択した '+esc(method)+' の売買とは区別します。</p>':'';
  document.getElementById('diagnosis').innerHTML=items.length?note+items.map(r=>'<details><summary>'+esc(r.method?r.method+'：':'')+esc(r.session?scene(r.session):'セッション不明')+' '+esc(r.title||'実注文の損失')+
    (r.net===undefined?'':' '+money(r.net))+'</summary><p>'+esc(r.text||r.reason||'')+'</p></details>').join(''):
    '<p class="muted">この条件の具体診断は未掲載です。全場損益と欠測・代理の区別は上表に収録しています。</p>';
}

/**
 * 機能: 選択した商品・方法の全四十一場と合計を表示します。
 * @returns {void} 返り値はありません。
 */
function renderSessions(){
  const method=document.getElementById('method').value,symbol=document.getElementById('symbol').value;
  const spec=DATA.specs.find(s=>s.id===method),m=DATA.metrics[method][symbol];
  const rows=DATA.rows.filter(r=>r.method===method&&r.symbol===symbol).sort((a,b)=>a.session.localeCompare(b.session));
  document.getElementById('method-description').textContent=spec.name+'。初期損切り '+spec.stop_w+'w／追尾開始 '+spec.trail_start_w+'w／追尾幅 '+spec.trail_w+'w／追加'+(spec.add_enabled?'あり':'なし')+'／相手確認'+(spec.peer_required?'あり':'なし')+'。';
  document.getElementById('selected-summary').innerHTML='合計 <span class="'+tone(m.net)+'">'+money(m.net)+'</span>　平均 '+money(m.mean)+'（'+pct(m.mean_price_pct)+'／'+m.mean_width.toFixed(2)+(symbol==='TOPIX'?'pt':'円')+'）　中央値 '+money(m.median)+'　黒字'+m.black+'／赤字'+m.red+'／収支0 '+m.active_zero+'／無取引'+m.inactive+'／未測定'+m.missing+
    '<br>通常数量参加 '+m.participation+'/41場。平均0.5%＋全場参加：'+(m.goal_pass?'達成':'未達')+'。上位3黒字を除く平均価格比 '+pct(m.without_top3_mean_price_pct)+'、収支 '+money(m.net_without_top3)+'。';
  document.getElementById('session-body').innerHTML=rows.map(r=>'<tr><td>'+esc(scene(r.session))+'</td><td class="pos">'+money(r.profit)+'</td><td class="neg">'+money(-r.loss)+'</td>'+yenCell(r.net)+
    '<td>'+((r.net/(r.rate_components.capacity_notional/r.rate_components.reference_price)).toFixed(2))+(symbol==='TOPIX'?'pt':'円')+'／'+pct(100*r.net/r.rate_components.capacity_notional)+'</td>'+
    '<td>'+nf.format(r.win_quantity)+'／'+nf.format(r.loss_quantity)+'</td><td>'+nf.format(r.entry_quantity)+'</td><td>'+r.signal_groups+'／'+r.forced_groups+'</td><td>'+r.normal_groups+'／'+r.proxy_groups+'</td><td>'+r.max_long+'／'+r.max_short+'</td></tr>').join('');
  document.getElementById('session-total').innerHTML='<tr><td>41場合計</td><td class="pos">'+money(m.profit)+'</td><td class="neg">'+money(-m.loss)+'</td>'+yenCell(m.net)+'<td>平均 '+pct(m.mean_price_pct)+'</td>'+
    '<td>'+nf.format(m.win_quantity)+'／'+nf.format(m.loss_quantity)+'</td><td>'+nf.format(m.entry_quantity)+'</td><td>'+m.signal_groups+'／'+m.forced_groups+'</td><td>'+m.normal_groups+'／'+m.proxy_groups+'</td><td>—</td></tr>';
  document.querySelectorAll('[data-summary-method]').forEach(row=>row.classList.toggle('selected',row.dataset.summaryMethod===method));
  renderDiagnosis(method,symbol);
}

renderCards();renderSummary();renderSessions();
document.getElementById('method').addEventListener('change',renderSessions);
document.getElementById('symbol').addEventListener('change',renderSessions);
document.getElementById('ranking-note').textContent=DATA.ranking;
const allRed=DATA.specs.every(s=>DATA.metrics[s.id].TOPIX.net<0&&DATA.metrics[s.id].NK225.net<0);
const allActive=DATA.specs.every(s=>DATA.metrics[s.id].TOPIX.participation===41&&DATA.metrics[s.id].NK225.participation===41);
document.getElementById('goal-outcome').textContent=(allActive?'全条件で全41場の通常数量参加は達成。':'通常数量参加は条件別に確認。')+
  '平均0.5%＋全場参加の合格はTOPIX '+DATA.goal_methods.TOPIX.length+'/12、日経 '+DATA.goal_methods.NK225.length+'/12、同一方法で両商品 '+DATA.joint_goal_methods.length+'/12。'+
  (allRed?'手数料0でも24商品条件すべて累計赤字でした。':'');
document.getElementById('record-count').textContent='全24商品条件 × 41場 = '+DATA.records+'行をこのHTML内に収録。外部通信はありません。';
</script></html>'''


def main(result_path: Path,expected_sha: str,diagnosis_path: Path | None,goal_note: str,
         audit_path: Path | None,audit_sha: str | None,diagnosis_sha: str | None) -> None:
    """
    機能: 根から完成SHA通知を受けた後だけ結果を所有写しにし、HTMLと生成証跡を保存する。
    引数: result_path(Path)/expected_sha(str)は完成結果、diagnosis_path(Path|None)/diagnosis_sha(str|None)は短診断の拘束、goal_note(str)は固定目標説明、audit_path/audit_shaは任意の監査拘束。
    返り値: None。金融再生・原市場・試行台帳・アプリを変更しない。
    """
    raw=result_path.read_bytes();assert sha(raw)==expected_sha
    result=json.loads(raw)
    audit_binding=None
    if audit_path is not None:
        audit_raw=audit_path.read_bytes();assert audit_sha is not None and sha(audit_raw)==audit_sha
        audit=json.loads(audit_raw);assert audit['passed'] and audit['result_sha256']==expected_sha
        audit_binding=dict(path=audit_path.resolve().relative_to(ROOT).as_posix(),sha256=audit_sha)
    diagnosis=None;diagnosis_binding=None
    if diagnosis_path is not None and diagnosis_path.exists():
        diagnostic_raw=diagnosis_path.read_bytes()
        assert diagnosis_sha is not None and sha(diagnostic_raw)==diagnosis_sha
        diagnosis=json.loads(diagnostic_raw)
        if 'source_result' in diagnosis:assert diagnosis['source_result']['sha256']==expected_sha
        diagnosis_binding=dict(path=diagnosis_path.resolve().relative_to(ROOT).as_posix(),sha256=sha(diagnostic_raw))
    data=make_data(result,diagnosis)
    built=build_html(data,goal_note)
    owned=HERE/'owned';owned.mkdir(exist_ok=True)
    saved_input=owned/'完成結果.json'
    if saved_input.exists():assert saved_input.read_bytes()==raw
    else:saved_input.write_bytes(raw)
    PUBLIC.mkdir(parents=True,exist_ok=True)
    TARGET.write_text(built,encoding='utf-8')
    proof=dict(passed=True,input_path=result_path.resolve().relative_to(ROOT).as_posix(),input_sha256=expected_sha,
        html_path=TARGET.relative_to(ROOT).as_posix(),html_sha256=sha(TARGET.read_bytes()),records=984,
        sessions=41,methods=12,products=2,embedded_records=len(data['rows']),family_picks=data['family_picks'],
        goal_note=goal_note,goal_methods=data['goal_methods'],joint_goal_methods=data['joint_goal_methods'],audit=audit_binding,diagnosis=diagnosis_binding,
        source_sha256=sha(Path(__file__).read_bytes()),financial_replay=0,original_market_reads=0,registry_changes=0,
        描画確認='生成と984行のデータ収録を確認。Chromeの実描画確認は根担当。')
    target=HERE/'生成証跡.json';target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--diagnosis',type=Path)
    parser.add_argument('--diagnosis-sha256')
    parser.add_argument('--goal-note',default=DEFAULT_GOAL)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--audit-sha256')
    args=parser.parse_args()
    main(args.result,args.sha256,args.diagnosis,args.goal_note,args.audit,args.audit_sha256,args.diagnosis_sha256)
