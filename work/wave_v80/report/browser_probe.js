/**
 * 機能: 2種類のHTMLの保存数値、切替、絞り込み、表示を実ブラウザで検査する。
 * @returns {object} 引数なし。返り値は照合数と表示結果。
 */
function independentVerify() {
  const test=window.reportTest,data=test.data;
  const assert=(value,message)=>{if(!value)throw Error(message);};
  const read=cell=>Number(cell.textContent.replaceAll(',','').replaceAll('円','').replaceAll('%','').replaceAll('倍','').replaceAll('−','-').trim());
  const close=(cell,value,label,digits=0)=>{if(value==null){assert(cell.textContent.trim()==='—',label+'の欠測');return;}assert(Math.abs(read(cell)-value)<=0.501*10**(-digits),label+': '+cell.textContent+'/'+value);};
  let numeric=0,lossColors=0,views=0,accounts=0,filters=0;
  const money=(cell,value,label)=>{close(cell,value,label);numeric++;if(value<0){const span=cell.querySelector('.loss');assert(span,'赤字クラス '+label);assert(getComputedStyle(span).color==='rgb(255, 147, 158)','赤色 '+label);lossColors++;}};
  if(data.final){
    assert(data.methods.length===11&&data.sessions.length===30,'11方法・30場');
    const method=document.getElementById('method-select'),delay=document.getElementById('delay-select');
    for(const m of data.methods)for(const wait of [0,1,5]){
      method.value=m.id;delay.value=String(wait);method.dispatchEvent(new Event('change'));
      for(const field of ['entry','during','exit'])assert(document.getElementById(field+'-text').textContent===m[field],'説明同期 '+field);
      const result=data.final[wait][m.id],rows=document.getElementById('session-results').rows;
      assert(rows.length===31,'全30場と合計');
      data.sessions.forEach((session,i)=>{
        assert(rows[i].dataset.session===session,'場順');
        ['TOPIX','NK225'].forEach((symbol,s)=>{
          const a=result.rows.find(r=>r.session===session&&r.symbol===symbol);assert(a.net===a.profit-a.loss,'会計');
          [a.profit,-a.loss,a.net].forEach((value,j)=>money(rows[i].cells[1+s*3+j],value,m.id+'/'+symbol));accounts++;
        });
      });
      ['TOPIX','NK225'].forEach((symbol,s)=>['profit','loss','net'].forEach((key,j)=>{
        const value=result.rows.filter(r=>r.symbol===symbol).reduce((sum,r)=>sum+r[key],0);
        assert(value===result.periods['対象'][symbol][key],'全場加算');money(rows[30].cells[1+s*3+j],key==='loss'?-value:value,'合計');
      }));
      const ps=document.getElementById('period-results').rows;assert(ps.length===6,'期間6行');
      ['前16','後14','対象'].forEach((period,p)=>['TOPIX','NK225'].forEach((symbol,s)=>{
        const a=result.periods[period][symbol],r=ps[p*2+s];
        [a.profit,-a.loss,a.net].forEach((value,j)=>money(r.cells[2+j],value,'期間'));
        close(r.cells[5],a.profit_share==null?null:a.profit_share*100,'割合',1);
        close(r.cells[6],a.trades,'組数');close(r.cells[7],a.payoff,'平均勝負',2);numeric+=3;
        assert(r.cells[8].textContent===`${a.winning_sessions}／${a.losing_sessions}／${a.no_trade_sessions}`,'黒字赤字無取引');
      }));views++;
    }
    const main=[...data.initial,...data.repaired];
    const latency=document.getElementById('latency-results').rows;assert(latency.length===12,'主6×2商品遅延');
    main.forEach((id,i)=>['TOPIX','NK225'].forEach((symbol,s)=>[0,1,5].forEach((wait,j)=>money(latency[i*2+s].cells[j+2],data.final[wait][id].periods['対象'][symbol].net,'遅延'))));
    const changes=document.getElementById('change-results').rows;assert(changes.length===6,'改修差6行');
    for(let i=0;i<3;i++)['TOPIX','NK225'].forEach((symbol,s)=>{
      const a=data.final[5][data.initial[i]].periods['対象'][symbol],b=data.final[5][data.repaired[i]].periods['対象'][symbol],r=changes[i*2+s];
      money(r.cells[2],a.loss-b.loss,'損失減');close(r.cells[3],a.profit-b.profit,'利益減');numeric++;money(r.cells[4],b.net-a.net,'改善額');
      assert(r.cells[5].textContent===`${a.trades} → ${b.trades}`,'取引前後');
    });
    const strict=document.getElementById('strict-results').rows;assert(strict.length===11,'厳格11案');
    data.methods.forEach((m,i)=>['TOPIX','NK225'].forEach((symbol,s)=>{money(strict[i].cells[1+s*2],data.strict[m.id][symbol].net,'厳格収支');close(strict[i].cells[2+s*2],data.strict[m.id][symbol].trades,'厳格取引');numeric++;}));
    const c=data.loss_case,caseText=document.getElementById('loss-case').textContent,waitText=document.getElementById('actual-waits').textContent;
    assert(c['収支円']===-60836,'最大損失の保存値');
    for(const o of Object.values(c['注文時計']))for(const key of ['判断','約定'])assert(caseText.includes(o[key].split('T')[1].slice(0,8)),'最大損失時計');
    for(const key of ['新規価格','返済価格','実際返済判断bid','設定幅による価格損失円','発動観測時点までの追加価格損失円','返済判断後の追加価格損失円','手数料円'])assert(caseText.includes(Number(c[key]).toLocaleString('ja-JP')),'最大損失数値 '+key);
    assert(caseText.includes('-60,836円'),'損失マイナス表示');
    for(const s of ['TOPIX','NK225'])for(const k of ['新規','返済'])assert(waitText.includes(String(Number(data.waits[s][k]['百分位95秒'].toFixed(2)))),'再生待ち95%点');
    assert(waitText.includes('再生上の注文待ち'),'実受信時計と混同しない注記');
    for(const button of document.querySelectorAll('[data-method]')){button.click();assert(method.value===button.dataset.method&&delay.value==='5','表から選択');}
    method.value=data.repaired[0];delay.value='5';method.dispatchEvent(new Event('change'));window.scrollTo(0,0);
  } else {
    assert(data.rows.length===330,'全330条件');
    const input=id=>document.getElementById(id),allBody=input('all-results');
    const checkRows=()=>{
      const stage=input('stage-filter').value,family=input('family-filter').value,mode=input('mode-filter').value,query=input('query-filter').value.toUpperCase().trim(),sort=input('sort-select').value;
      const expected=data.rows.filter(r=>(!stage||r.stage===stage)&&(!family||r.family===family)&&(mode===''||String(r.config.entry_mode)===mode)&&(!query||r.config.id.toUpperCase().includes(query)));
      const rows=[...allBody.rows];assert(rows.length===expected.length,'検索件数');
      const lookup=Object.fromEntries(expected.map(r=>[r.config.id,r]));
      rows.forEach((r,i)=>{
        const saved=lookup[r.dataset.id];assert(saved,'検索外ID');
        ['TOPIX','NK225'].forEach((symbol,s)=>{
          const a=saved.metrics[symbol];[a.profit,-a.loss,a.net].forEach((v,j)=>money(r.cells[2+s*4+j],v,'全条件収支'));
          const main=r.cells[5+s*4].childNodes[0].textContent;assert(main===(a.profit_share==null?'—':(a.profit_share*100).toFixed(1)+'%'),'全条件金額割合');
          assert(r.cells[5+s*4].querySelector('small').textContent===a.trades+'組','全条件組数');numeric+=2;
        });
        if(i&&sort!=='id')assert(lookup[rows[i-1].dataset.id].metrics[sort].net>=saved.metrics[sort].net,'商品別順位');
      });
      assert(input('result-count').textContent.startsWith(expected.length+'／330'),'件数表示');filters++;
    };
    checkRows();
    for(const stage of [...input('stage-filter').options])for(const family of [...input('family-filter').options])for(const mode of [...input('mode-filter').options]){
      input('stage-filter').value=stage.value;input('family-filter').value=family.value;input('mode-filter').value=mode.value;
      input('mode-filter').dispatchEvent(new Event('change'));checkRows();
    }
    for(const id of ['stage-filter','family-filter','mode-filter'])input(id).value='';
    for(const r of data.rows){input('query-filter').value=r.config.id;input('query-filter').dispatchEvent(new Event('input'));checkRows();}
    input('query-filter').value='存在しないID';input('query-filter').dispatchEvent(new Event('input'));checkRows();
    input('query-filter').value='';
    for(const value of ['TOPIX','NK225','id']){input('sort-select').value=value;input('sort-select').dispatchEvent(new Event('change'));checkRows();}
    views=330;accounts=660;
  }
  for(const detail of document.querySelectorAll('details'))detail.open=true;
  assert(document.documentElement.scrollWidth<=innerWidth+2,'全詳細展開横溢れ '+document.documentElement.scrollWidth+'/'+innerWidth);
  for(const detail of document.querySelectorAll('details'))detail.open=false;
  assert(!/NaN|undefined|Infinity|__DATA__|__SCRIPT__/.test(document.body.innerText),'未定義表示');
  assert(!document.querySelector('script[src],link[href],img[src]'),'外部資源');
  assert((window.browserErrors||[]).length===0,'JS例外 '+JSON.stringify(window.browserErrors));
  assert(getComputedStyle(document.body).backgroundColor==='rgb(16, 21, 30)','ダーク背景');
  return {全合格:true,手法遅延切替数:views,場商品数:accounts,数値照合数:numeric,赤字色照合数:lossColors,絞込並替照合数:filters,
          文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor,JS例外数:window.browserErrors.length};
}
try{document.body.dataset.check=JSON.stringify(independentVerify());}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
