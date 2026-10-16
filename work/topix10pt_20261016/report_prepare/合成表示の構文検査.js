
const D=JSON.parse(document.getElementById('report-data').textContent);
const selected=D.displayed.length?D.displayed[0].id:D.specifications[0].id;
const select=document.getElementById('method-select');
const rate=v=>v===null?'—':(100*v).toFixed(1)+'%';
const text=c=>c['順先']+'/'+c.n+'（'+rate(c['全候補順先率'])+'）';
const escapeText=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
/**
 * 機能: 保存した一手法の全37場だけを切り替えて表示する。
 * 引数: identity(string) は固定手法ID。
 * 返り値: undefined。率の再採点や候補の選び直しを行わない。
 */
function show(identity){
 const spec=D.specifications.find(v=>v.id===identity);
 const rows=D.rows.filter(v=>v.id===identity);
 const summary=D.summaries.find(v=>v.id===identity).periods['全37'];
 const group=s=>D.splits['学習'].includes(s)?'学習内':D.splits['選択'].includes(s)?'選択':D.splits['時系列別枠'].includes(s)?'既知の後6':'追加4';
 document.getElementById('selected-description').textContent=spec.name+'：'+(spec.condition||spec.description);
 document.getElementById('session-body').innerHTML=rows.map(r=>{const c=r.risks[1];return '<tr data-session="'+escapeText(r.session)+'"><th>'+escapeText(r.session)+'</th><td>'+group(r.session)+'</td><td>'+text(c)+'</td><td>'+c['逆先']+'</td><td>'+c['窓末未決']+'</td><td>'+c['EOF未決']+'</td><td>'+c['基準不可']+'</td><td>'+r['買い数']+'/'+r['売り数']+'</td></tr>'}).join('');
 const c=summary['主評価']['全体'];document.getElementById('session-footer').innerHTML='<tr><th>全37場合計</th><td>参考合算</td><td>'+text(c)+'</td><td>'+c['逆先']+'</td><td>'+c['窓末未決']+'</td><td>'+c['EOF未決']+'</td><td>'+c['基準不可']+'</td><td>'+summary['買い数']+'/'+summary['売り数']+'</td></tr>';
 select.value=identity;document.body.dataset.method=identity;
}
select.addEventListener('change',()=>show(select.value));
document.getElementById('reset').addEventListener('click',()=>show(selected));
document.querySelectorAll('.method-link').forEach(b=>b.addEventListener('click',()=>{show(b.dataset.id);document.getElementById('all-sessions').scrollIntoView({behavior:'smooth'})}));
show(selected);
