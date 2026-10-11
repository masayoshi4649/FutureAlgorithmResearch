const METHODS=[D.benchmark,...D.methods],BYID=new Map(METHODS.map(m=>[m.id,m]));

/**
 * 機能: 選択した手法の全セッションを、両商品の利益・損失・収支で併記する。
 * @param {void} なし - 画面の手法選択と保存済み会計を参照する。
 * @returns {void} 返り値なし。折り畳みのない表を更新する。
 */
function allSessions(){
    const method=BYID.get(document.getElementById('session-method').value);
    const rows=D.sessions.map(session=>({
        label:sessionName(session),
        values:['TOPIX','NK225'].map(symbol=>method.rows.find(row=>row.session===session&&row.symbol===symbol)),
        total:false
    }));
    rows.push({label:'全30セッション合計',values:['TOPIX','NK225'].map(symbol=>method.periods.全30[symbol]),total:true});
    document.getElementById('all-session-results').innerHTML=`<table class="session-profit-table"><thead><tr><th rowspan="2" scope="col">セッション</th><th colspan="3" scope="colgroup">TOPIXミニ10枚</th><th colspan="3" scope="colgroup">日経225マイクロ20枚</th></tr><tr>${['TOPIX','NK225'].map(()=>'<th scope="col">利益</th><th scope="col">損失</th><th scope="col">収支</th>').join('')}</tr></thead><tbody>${rows.map(row=>`<tr${row.total?' class="total"':''}><th scope="row">${esc(row.label)}</th>${row.values.map(a=>`<td>${money(a.profit)}</td><td>${money(a.loss,false,true)}</td><td>${money(a.net,true)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

/**
 * 機能: 部品対照をIDだけでなく短い日本語で区別する。
 * @param {object} c - 固定設定。
 * @returns {string} 対照の表示名。
 */
function controlLabel(c){const names=[];if(c.flow_mode)names.push(c.flow_mode===1?'板の反対で撤退':'板と価格の反対で撤退');if(c.protect_fraction)names.push('幅の'+(c.protect_fraction*100)+'%順行で建値保護');if(c.hold_mode)names.push(c.hold_mode===1?'条件付き最大90分':'固定90分');if(c.rest_mode)names.push('2連敗休止＋再準備');return names.join('＋')||'従来の管理';}

/**
 * 機能: 基準と前半固定の代表を商品別に比較する。
 * @returns {void} 返り値なし。
 */
function comparison(){const s=document.getElementById('comparison-symbol').value,p=document.getElementById('comparison-period').value;document.getElementById('comparison').innerHTML=table(METHODS.map(m=>({label:esc(m.title)+`<br><span class="id">${esc(m.id)}</span>`,a:m.periods[p][s],total:m.id===D.benchmark.id})),true);}

/**
 * 機能: 方式の入口・途中・出口を短い章へする。
 * @param {object} method - 固定代表又は基準。
 * @param {number} index - 章番号。
 * @returns {string} 三段階説明のHTML。
 */
function methodCard(method,index){return `<section class="method" data-method-id="${esc(method.id)}"><h2>${index===0?'基準':index+'.'} ${esc(method.title)}</h2><p class="id">${esc(method.id)}</p><div class="steps">${[['入口','entry'],['途中','middle'],['出口','exit']].map(([label,key])=>`<div class="step"><strong>${label}</strong><p>${esc(method.steps[key])}</p></div>`).join('')}</div><p class="finding small">${esc(method.finding)}</p><button data-select-method="${esc(method.id)}">この手法の全場損益・売買図へ</button></section>`;}

/**
 * 機能: 選択方式の全場・期間内訳・注文図を更新する。
 * @returns {void} 返り値なし。
 */
function details(){const m=BYID.get(document.getElementById('detail-method').value),s=document.getElementById('detail-symbol').value,session=document.getElementById('detail-session').value;document.getElementById('session-results').innerHTML=table([...D.sessions.map(key=>({label:`<button class="session-link" data-session="${esc(key)}">${esc(sessionName(key))}</button>`,a:m.rows.find(r=>r.symbol===s&&r.session===key)})),{label:'全30合計',a:m.periods.全30[s],total:true}]);document.querySelectorAll('[data-session]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('detail-session').value=b.dataset.session;details();document.getElementById('chart').scrollIntoView({block:'center',behavior:'smooth'});}));document.getElementById('groups').innerHTML=table(m.groups[s].map(a=>({label:esc(a.label),a})),true)+`<p class="small">最大利益日は、同じ日付のデイ＋ナイトの合計で選び、その日の全売買を除いた事後診断です。取引条件の再選定ではありません。</p>`;
const a=m.periods.全30[s],status=m.management[s];document.getElementById('management').innerHTML=`<div class="table-wrap"><table><thead><tr><th>取引した場</th><th>一度でも休止した場</th><th>休止回数</th><th>休止で見送った入口</th><th>15分延長の回数</th><th>全手数料</th><th>最大負け取引</th><th>最大取引連敗</th><th>連続赤字場</th></tr></thead><tbody><tr><td>${a.active_sessions}/30</td><td>${status.paused_sessions}</td><td>${status.pauses}</td><td>${status.skipped_entries}</td><td>${status.extensions}</td><td>${NUMBER.format(a.fees)}円</td><td>${money(a.max_trade_loss,false,true)}</td><td>${a.max_consecutive_trade_losses}</td><td>${a.consecutive_losing_sessions}</td></tr></tbody></table></div><p class="small">休止した場でも、休止前後の取引は成績へ含めています。無取引は勝ちに数えません。平均勝ち／負けは実際の費用後決済額の平均比です。</p>`;document.getElementById('controls').innerHTML=table(m.controls.map(c=>({label:esc(controlLabel(c.config))+`<br><span class="id">${esc(c.id)}</span>`,a:c.periods.全30[s],total:c.id===m.id})),true);document.getElementById('sensitivity').innerHTML=table(m.sensitivity.map(c=>({label:'情報遅延'+c.delay+'秒・全30場',a:c.periods.全30[s],total:c.delay===5})),true);document.getElementById('chart-caption').textContent=m.title+' · '+sessionName(session)+' · '+NAMES[s];document.getElementById('chart').innerHTML=chart(m,s,session);document.getElementById('orders').innerHTML=history(m,s,session);}

// ----------------------------------------
// 保存数値と短い説明を組み立て、商品・期間・売買図の操作を接続する。
document.getElementById('parts-overview').innerHTML=`<table><thead><tr><th>加えた部品</th><th>TOPIX収支差</th><th>日経収支差</th><th>判断</th></tr></thead><tbody>${D.partsOverview.map(x=>`<tr><td>${esc(x.label)}</td><td>${money(x.difference.TOPIX,true)}</td><td>${money(x.difference.NK225,true)}</td><td class="wrap">${esc(x.reason)}</td></tr>`).join('')}</tbody></table>`;document.getElementById('direction-groups').innerHTML=`<table><thead><tr><th>結果の分類</th><th>場数</th><th>TOPIX収支</th><th>日経収支</th></tr></thead><tbody>${D.directionRows.map(x=>`<tr><td>${esc(x.label)}</td><td>${x.sessions}</td><td>${money(x.net.TOPIX,true)}</td><td>${money(x.net.NK225,true)}</td></tr>`).join('')}</tbody></table>`;document.title=D.title;document.getElementById('title').textContent=D.title;document.getElementById('conclusion').innerHTML=D.conclusions.map(x=>`<p>${esc(x)}</p>`).join('');document.getElementById('comparison-period').innerHTML=D.periodNames.map(p=>`<option${p==='全30'?' selected':''}>${esc(p)}</option>`).join('');document.getElementById('history').innerHTML=`<table><thead><tr><th>系統</th><th>扱い</th><th>理由</th><th>当時の評価条件</th></tr></thead><tbody>${D.history.map(x=>`<tr><td><a href="${esc(x.url)}">${esc(x.name)}</a></td><td>${esc(x.status)}</td><td class="wrap">${esc(x.reason)}</td><td class="wrap small">${esc(x.assumption)}</td></tr>`).join('')}</tbody></table>`;document.getElementById('methods').innerHTML=METHODS.map(methodCard).join('');document.getElementById('detail-method').innerHTML=METHODS.map(m=>`<option value="${esc(m.id)}">${esc(m.title+'｜'+m.id)}</option>`).join('');document.getElementById('detail-session').innerHTML=D.sessions.map(s=>`<option value="${esc(s)}">${esc(sessionName(s))}</option>`).join('');document.getElementById('detail-session').value=D.sessions.at(-1);document.getElementById('notes').innerHTML=D.notes.map(n=>`<li>${esc(n)}</li>`).join('');document.getElementById('parts-summary').innerHTML=D.partNotes.map(n=>`<li>${esc(n)}</li>`).join('');document.getElementById('all-link').href=D.allUrl;for(const id of ['comparison-symbol','comparison-period'])document.getElementById(id).addEventListener('change',comparison);for(const id of ['detail-method','detail-symbol','detail-session'])document.getElementById(id).addEventListener('change',details);document.querySelectorAll('[data-select-method]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('detail-method').value=b.dataset.selectMethod;details();document.getElementById('detail-method').scrollIntoView({block:'start',behavior:'smooth'});}));comparison();details();window.reportTest={D,METHODS,comparison,details,chart,history,table};


// ----------------------------------------
// 全場一覧は初期表示から開き、同じ四手法を両商品併記で切り替える。
document.getElementById('session-method').innerHTML=METHODS.map(m=>`<option value="${esc(m.id)}">${esc(m.title+'｜'+m.id)}</option>`).join('');
document.getElementById('session-method').value=D.benchmark.id;
document.getElementById('session-method').addEventListener('change',allSessions);
allSessions();
window.reportTest.allSessions=allSessions;
