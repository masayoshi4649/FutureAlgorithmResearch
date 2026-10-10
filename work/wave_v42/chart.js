/**
 * 内蔵した保存台帳から固定4方式の図を切り替える。
 * @param {undefined} 引数なし。
 * @returns {undefined} 売買・通信は行わず、画面だけ更新する。
 */
(() => {
  const data = JSON.parse(document.getElementById('chart-data').textContent);
  const method = document.getElementById('method');
  const symbol = document.getElementById('symbol');
  const session = document.getElementById('session');
  const canvas = document.getElementById('chart');
  const formatter = new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
  const colors = {buy:'#69ddb2',sell:'#ff8498',stop:'#ff7188',target:'#f4cf72',time:'#84c5ff',close:'#c3cedb',grid:'#28415b',text:'#bdcfe3',equity:'#bca6ff'};

  /**
   * 数値を表示用に整える。
   * @param {number} value 数値。
   * @param {number} digits 小数桁数。
   * @returns {string} 桁区切り済みの文字。
   */
  function number(value, digits=0) { return Number(value).toLocaleString('ja-JP',{maximumFractionDigits:digits}); }

  /**
   * 原本の秒時刻を日本時間へ変換する。
   * @param {number} value 秒時刻。
   * @returns {string} 月日・時分秒。
   */
  function clock(value) { return formatter.format(new Date(value*1000)); }

  /**
   * 保存文字列をHTMLへ安全に表示する。
   * @param {unknown} value 表示値。
   * @returns {string} エスケープ済み文字。
   */
  function escape(value) { return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

  /**
   * 全行を省略せず表へ変換する。
   * @param {string[]} heads 見出し。
   * @param {Array<Array<unknown>>} rows 保存値の行。
   * @returns {string} 表HTML。
   */
  function table(heads, rows) {
    if (!rows.length) return '<p class="muted">取引なし</p>';
    return '<div class="scroll"><table><thead><tr>'+heads.map(h=>'<th>'+escape(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
  }

  /**
   * 選択肢を保存順で追加する。
   * @param {HTMLSelectElement} select 対象。
   * @param {string} value 値。
   * @param {string} label 表示名。
   * @returns {undefined} 返り値なし。
   */
  function option(select, value, label) { const item=document.createElement('option');item.value=value;item.textContent=label;select.appendChild(item); }

  /**
   * 全約定点、保有方向、標本化損益を描く。
   * @param {Array<Array<number>>} bars 確定5分足。
   * @param {object} record 選択された全台帳。
   * @returns {undefined} 返り値なし。
   */
  function draw(bars, record) {
    const width=Math.max(360,canvas.getBoundingClientRect().width||1000),height=640;
    const ratio=window.devicePixelRatio||1;
    canvas.width=Math.round(width*ratio);canvas.height=height*ratio;
    const ctx=canvas.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);
    ctx.fillStyle='#0d1827';ctx.fillRect(0,0,width,height);ctx.font='12px "Yu Gothic UI",sans-serif';
    if (!bars.length) {ctx.fillStyle=colors.text;ctx.fillText('確定5分足なし',20,40);return;}
    const left=76,right=18,top=34,priceBottom=354,positionTop=397,positionBottom=459,pnlTop=500,pnlBottom=600;
    const first=Math.min(bars[0][0],record.position[0][0]);
    const last=Math.max(bars[bars.length-1][0]+300,record.tracking[record.tracking.length-1][0]);
    const prices=bars.flatMap(v=>[v[2],v[3]]).concat(record.orders.map(v=>v[5]),record.bands.map(v=>v.price));
    let low=Math.min(...prices),high=Math.max(...prices);const pad=Math.max((high-low)*.08,1);low-=pad;high+=pad;
    const x=t=>left+(t-first)/Math.max(1,last-first)*(width-left-right);
    const y=p=>priceBottom-(p-low)/(high-low)*(priceBottom-top);
    const q=v=>(positionTop+positionBottom)/2-v*22;
    const values=record.tracking.map(v=>v[3]);let vlow=Math.min(0,...values),vhigh=Math.max(0,...values);
    const vpad=Math.max((vhigh-vlow)*.12,100);vlow-=vpad;vhigh+=vpad;
    const money=v=>pnlBottom-(v-vlow)/(vhigh-vlow)*(pnlBottom-pnlTop);
    ctx.strokeStyle=colors.grid;ctx.fillStyle=colors.text;ctx.textAlign='right';
    for(let i=0;i<=5;i++){const p=low+(high-low)*i/5;ctx.beginPath();ctx.moveTo(left,y(p));ctx.lineTo(width-right,y(p));ctx.stroke();ctx.fillText(number(p,1),left-8,y(p)+4);}
    for(let i=0;i<=5;i++){const t=first+(last-first)*i/5;ctx.beginPath();ctx.moveTo(x(t),top);ctx.lineTo(x(t),pnlBottom);ctx.stroke();ctx.textAlign='center';ctx.fillText(clock(t).slice(6,11),x(t),623);}
    // ----------------------------------------
    // 確定足と全返済までの控えめな接続線。
    const candleWidth=Math.max(1,Math.min(9,(width-left-right)*240/Math.max(1,last-first)));
    for(const b of bars){const color=b[4]>=b[1]?colors.buy:colors.sell;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(x(b[0]+150),y(b[2]));ctx.lineTo(x(b[0]+150),y(b[3]));ctx.stroke();ctx.fillRect(x(b[0]+150)-candleWidth/2,Math.min(y(b[1]),y(b[4])),candleWidth,Math.max(1,Math.abs(y(b[1])-y(b[4]))));}
    // ----------------------------------------
    // 実際の新規に使った帯だけ、公開済みの試行完了と突破へ結ぶ。
    ctx.strokeStyle='#bfa7ff';ctx.fillStyle='#d4c4ff';ctx.lineWidth=1;ctx.textAlign='center';
    for(const band of record.bands){
      const py=y(band.price);ctx.globalAlpha=.65;ctx.setLineDash([5,3]);
      ctx.beginPath();ctx.moveTo(x(band.created.time_s),py);ctx.lineTo(x(band.decision.time_s),py);ctx.stroke();
      ctx.globalAlpha=1;ctx.setLineDash([]);
      for(const trial of band.trials){if(trial.complete){const px=x(trial.end.time_s);ctx.beginPath();ctx.arc(px,py,4,0,Math.PI*2);ctx.stroke();ctx.fillText(String(trial.number),px,py-8);}}
      const px=x(band.decision.time_s);ctx.beginPath();ctx.moveTo(px,py-6);ctx.lineTo(px+5,py);ctx.lineTo(px,py+6);ctx.lineTo(px-5,py);ctx.closePath();ctx.fill();
    }
    ctx.globalAlpha=.35;ctx.setLineDash([3,4]);
    for(const t of record.trades){ctx.strokeStyle=t[4]>0?colors.buy:colors.sell;ctx.beginPath();ctx.moveTo(x(t[0]),y(t[5]));ctx.lineTo(x(t[1]),y(t[6]));ctx.stroke();}
    ctx.globalAlpha=1;ctx.setLineDash([]);ctx.lineWidth=2;
    for(const order of record.orders){const [time,,,,,price,reason,opening]=order;const px=x(time),py=y(price);
      if(opening){const direction=order[3];ctx.fillStyle=direction>0?colors.buy:colors.sell;ctx.beginPath();ctx.moveTo(px,py-direction*7);ctx.lineTo(px-5,py+direction*5);ctx.lineTo(px+5,py+direction*5);ctx.closePath();ctx.fill();}
      else{ctx.strokeStyle=reason===1?colors.stop:reason===2?colors.target:reason===3?colors.time:colors.close;ctx.beginPath();ctx.moveTo(px-5,py-5);ctx.lineTo(px+5,py+5);ctx.moveTo(px-5,py+5);ctx.lineTo(px+5,py-5);ctx.stroke();}}
    // ----------------------------------------
    // 数量は全約定の階段、損益は保存された過去asof標本を結ぶ。
    ctx.lineWidth=1;ctx.strokeStyle=colors.grid;ctx.fillStyle=colors.text;ctx.textAlign='right';
    for(const value of [-1,0,1]){ctx.beginPath();ctx.moveTo(left,q(value));ctx.lineTo(width-right,q(value));ctx.stroke();ctx.fillText(value>0?'+1':String(value),left-8,q(value)+4);}
    ctx.strokeStyle=colors.time;ctx.lineWidth=2;ctx.beginPath();
    for(let i=0;i<record.position.length;i++){const p=record.position[i];if(!i)ctx.moveTo(x(p[0]),q(p[2]));else{ctx.lineTo(x(p[0]),q(record.position[i-1][2]));ctx.lineTo(x(p[0]),q(p[2]));}}ctx.stroke();
    ctx.strokeStyle=colors.grid;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,money(0));ctx.lineTo(width-right,money(0));ctx.stroke();
    ctx.fillText(number(vhigh),left-8,pnlTop+4);ctx.fillText('0',left-8,money(0)+4);ctx.fillText(number(vlow),left-8,pnlBottom+4);
    ctx.strokeStyle=colors.equity;ctx.lineWidth=2;ctx.beginPath();record.tracking.forEach((p,i)=>{if(i)ctx.lineTo(x(p[0]),money(p[3]));else ctx.moveTo(x(p[0]),money(p[3]));});ctx.stroke();
    ctx.fillStyle='#e1edfc';ctx.textAlign='left';ctx.fillText('価格・全売買',left,19);ctx.fillText('保有枚数：＋1 ロング／−1 ショート',left,385);ctx.fillText('時価損益 円（5分＋全約定点）',left,487);
  }

  /**
   * 選択された1画面の図・全台帳・損益を更新する。
   * @param {Event|undefined} event 選択変更。
   * @returns {undefined} 描画完了のキーを公開する。
   */
  function render(event) {
    const key=method.value+'|'+session.value+'|'+symbol.value;
    const record=data.records[key],bars=data.candles[session.value+'|'+symbol.value];
    const t=record.totals;const badge=record.training?'<span class="badge">学習専用・取引0</span> ':'';
    const preview=data.preview?'<span class="badge">独立監査中の暫定表示</span> ':'';
    document.getElementById('chart-summary').innerHTML=preview+badge+escape(method.value+' '+data.methods[method.value])+' ／ 利益 '+number(t.profit_yen)+'円 ／ 損失 '+number(t.loss_yen)+'円 ／ <strong class="'+(t.net_yen>=0?'gain':'loss')+'">収支 '+number(t.net_yen)+'円</strong> ／ '+number(t.trades)+'取引 ／ 帯候補 '+number(record.candidate_count)+'・新規約定 '+number(record.bands.length);
    document.getElementById('order-table').innerHTML=table(['時刻','原本行','判断行','売買','枚数','価格','理由'],record.orders.map(o=>[clock(o[0]),o[1],o[2],o[3]>0?'買い':'売り',o[4],number(o[5],1),data.reason_names[o[6]]]));
    document.getElementById('trade-table').innerHTML=table(['新規時刻','返済時刻','方向','新規価格','返済価格','r幅','損益 円','返済理由','新規行','返済行'],record.trades.map(t=>[clock(t[0]),clock(t[1]),t[4]>0?'ロング':'ショート',number(t[5],1),number(t[6],1),number(t[7],1),number(t[8]*record.factor),data.reason_names[t[9]],t[2],t[3]]));
    document.getElementById('band-table').innerHTML=table(['帯ID','方向','帯価格P','生成','試行1完了','試行2完了','突破判断','新規約定','判断行','数量観測','使用u1／u2','旧公開端点u（参考）','b1／b2','相手公開'],record.bands.map(b=>[
      b.band_id,b.direction>0?'ロング':'ショート',number(b.price,1),clock(b.created.time_s),
      ...b.trials.map(t=>t.complete?clock(t.end.time_s):'未完了'),clock(b.decision.time_s),clock(b.entry_time),b.decision.ready_index,
      ({old:'旧公開端点',strict:'原本全行・旧品質維持',local:'原本全行・P局所品質'})[b.feature_source],
      [b.features.u1,b.features.u2].map(v=>v===null?'不明':number(v,3)).join(' ／ '),
      [b.old_features.u1,b.old_features.u2].map(v=>v===null?'不明':number(v,3)).join(' ／ '),
      [b.features.b1,b.features.b2].map(v=>v===null?'不明':number(v,3)).join(' ／ '),
      b.peer?clock(b.peer.public_time)+'（＋60秒後利用）':'確認なし']));
    draw(bars,record);window.chartRenderedKey=key;window.chartViewReady=true;
  }

  Object.entries(data.methods).forEach(([value,label])=>option(method,value,value+' '+label));
  data.sessions.forEach(value=>option(session,value,value+(data.training_sessions.includes(value)?'（学習専用）':'')));
  method.value='F00';session.value=data.sessions[data.sessions.length-1];symbol.value='TOPIX';
  [method,symbol,session].forEach(element=>element.addEventListener('change',render));
  window.addEventListener('resize',render);
  window.chartSelect=(m,s,k)=>{method.value=m;symbol.value=s;session.value=k;render();};
  render();
})();
