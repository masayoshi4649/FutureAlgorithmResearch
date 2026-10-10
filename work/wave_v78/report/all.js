/**
 * 機能: 全固定条件を閲覧用に並べ替えて表示する。
 * @returns {void} 返り値なし。
 */
function ranking(){const s=document.getElementById('symbol').value,p=document.getElementById('period').value,sort=document.getElementById('sort').value,methods=[...D.methods];methods.sort((a,b)=>{if(sort==='id')return a.id.localeCompare(b.id);const av=a.periods[p][s][sort],bv=b.periods[p][s][sort];return av==null?1:bv==null?-1:(sort==='drawdown'?av-bv:bv-av)||a.id.localeCompare(b.id);});document.getElementById('ranking').innerHTML=table(methods.map(m=>({label:`<button class="session-link" data-pick="${esc(m.id)}">${esc(m.id)}</button>${D.selectedIds.includes(m.id)?' <span class="small">代表</span>':m.id===D.baselineId?' <span class="small">基準</span>':''}`,a:m.periods[p][s],total:m.id===D.baselineId})),true);document.querySelectorAll('[data-pick]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('method').value=b.dataset.pick;sessions();document.getElementById('method').scrollIntoView({block:'start'});}));sessions();}

/**
 * 機能: 任意の固定条件について全三十場の会計を表示する。
 * @returns {void} 返り値なし。
 */
function sessions(){const m=D.methods.find(x=>x.id===document.getElementById('method').value),s=document.getElementById('symbol').value;document.getElementById('description').textContent=m.configText;document.getElementById('sessions').innerHTML=table([...D.sessions.map(key=>({label:esc(sessionName(key)),a:m.rows.find(r=>r.session===key&&r.symbol===s)})),{label:'全30合計',a:m.periods.全30[s],total:true}]);}

// ----------------------------------------
// 全条件を常に残し、並べ替えは代表の選び直しに使用しない。
document.getElementById('main-link').href=D.mainUrl;document.getElementById('period').innerHTML=D.periodNames.map(p=>`<option${p==='全30'?' selected':''}>${esc(p)}</option>`).join('');document.getElementById('method').innerHTML=D.methods.map(m=>`<option value="${esc(m.id)}">${esc(m.id)}</option>`).join('');document.getElementById('method').value=D.baselineId;for(const id of ['symbol','period','sort'])document.getElementById(id).addEventListener('change',ranking);document.getElementById('method').addEventListener('change',sessions);ranking();window.reportTest={D,ranking,sessions,table};
