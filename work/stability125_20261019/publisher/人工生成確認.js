
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
  const items=input.filter(r=>r.symbol===symbol&&(!r.method||r.method===method)).slice(0,3);
  document.getElementById('diagnosis').innerHTML=items.length?items.map(r=>'<details><summary>'+esc(r.title||scene(r.session))+
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
