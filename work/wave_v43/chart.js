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
   * 構成票と使用入口を、売買・保有と分離して描画する。
   * @param {Array<Array<number>>} bars 確定5分足。
   * @param {object} record 全台帳と票列。
   * @returns {undefined} 返り値なし。
   */
  function draw(bars,record) {
    const width=Math.max(360,canvas.getBoundingClientRect().width||1000),height=790,ratio=window.devicePixelRatio||1;
    canvas.width=Math.round(width*ratio);canvas.height=height*ratio;
    const ctx=canvas.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);
    ctx.fillStyle='#0d1827';ctx.fillRect(0,0,width,height);ctx.font='12px "Yu Gothic UI",sans-serif';
    if(!bars.length){ctx.fillStyle=colors.text;ctx.fillText('確定5分足なし',20,40);return;}
    const left=96,right=18,top=34,priceBottom=335,bandTop=370,positionTop=491,positionBottom=561,pnlTop=610,pnlBottom=741;
    const first=Math.min(bars[0][0],record.position[0][0]);
    const last=Math.max(bars[bars.length-1][0]+300,record.tracking[record.tracking.length-1][0]);
    const prices=bars.flatMap(v=>[v[2],v[3]]).concat(record.orders.map(v=>v[6]));
    let low=Math.min(...prices),high=Math.max(...prices);const pad=Math.max(1,(high-low)*.08);low-=pad;high+=pad;
    const x=t=>left+(t-first)/Math.max(1,last-first)*(width-left-right);
    const y=p=>priceBottom-(p-low)/(high-low)*(priceBottom-top);
    const maximum=Math.max(1,...record.position.flatMap(v=>[v[2],v[3]]));
    const q=v=>(positionTop+positionBottom)/2-v/maximum*(positionBottom-positionTop)/2;
    const values=record.tracking.map(v=>v[4]);let vlow=Math.min(0,...values),vhigh=Math.max(0,...values);
    const vpad=Math.max(100,(vhigh-vlow)*.12);vlow-=vpad;vhigh+=vpad;
    const money=v=>pnlBottom-(v-vlow)/(vhigh-vlow)*(pnlBottom-pnlTop);
    ctx.strokeStyle=colors.grid;ctx.fillStyle=colors.text;ctx.textAlign='right';
    for(let i=0;i<=5;i++){const p=low+(high-low)*i/5;ctx.beginPath();ctx.moveTo(left,y(p));ctx.lineTo(width-right,y(p));ctx.stroke();ctx.fillText(number(p,1),left-8,y(p)+4);}
    for(let i=0;i<=5;i++){const t=first+(last-first)*i/5;ctx.beginPath();ctx.moveTo(x(t),top);ctx.lineTo(x(t),pnlBottom);ctx.stroke();ctx.textAlign='center';ctx.fillText(clock(t).slice(6,11),x(t),765);}
    // ----------------------------------------
    // 売買位置は保存約定価格。減量・復元を初回売買と別の形で表示する。
    const candleWidth=Math.max(1,Math.min(9,(width-left-right)*240/Math.max(1,last-first)));
    for(const b of bars){const color=b[4]>=b[1]?colors.buy:colors.sell;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(x(b[0]+150),y(b[2]));ctx.lineTo(x(b[0]+150),y(b[3]));ctx.stroke();ctx.fillRect(x(b[0]+150)-candleWidth/2,Math.min(y(b[1]),y(b[4])),candleWidth,Math.max(1,Math.abs(y(b[1])-y(b[4]))));}
    ctx.globalAlpha=.25;ctx.setLineDash([3,4]);
    for(const t of record.trades){ctx.strokeStyle=t[2]>0?colors.buy:colors.sell;ctx.beginPath();ctx.moveTo(x(t[0]),y(t[4]));ctx.lineTo(x(t[1]),y(t[5]));ctx.stroke();}
    ctx.globalAlpha=1;ctx.setLineDash([]);ctx.lineWidth=2;
    for(const o of record.orders){const px=x(o[0]),py=y(o[6]),reason=o[7],opening=o[8],side=o[4];
      if(reason===30){ctx.strokeStyle='#ffb45d';ctx.strokeRect(px-5,py-5,10,10);}
      else if(reason===31){ctx.strokeStyle='#6ee4ff';ctx.beginPath();ctx.moveTo(px,py-7);ctx.lineTo(px+6,py);ctx.lineTo(px,py+7);ctx.lineTo(px-6,py);ctx.closePath();ctx.stroke();}
      else if(opening){ctx.fillStyle=side>0?colors.buy:colors.sell;ctx.beginPath();ctx.moveTo(px,py-side*7);ctx.lineTo(px-5,py+side*5);ctx.lineTo(px+5,py+side*5);ctx.closePath();ctx.fill();}
      else{ctx.strokeStyle=reason===32?'#ff667e':'#f4cf72';ctx.beginPath();ctx.moveTo(px-5,py-5);ctx.lineTo(px+5,py+5);ctx.moveTo(px-5,py+5);ctx.lineTo(px+5,py-5);ctx.stroke();}}
    // ----------------------------------------
    // 票列は同一原本行での状態。全変化を保存し、同秒の変更は幅0のまま描く。
    const labels=['窓0.8','窓1.0','窓1.2','使用入口'];
    const faded={1:'#327b65','0':'#283647','-1':'#824858'},bright={1:'#76efba','0':'#4d6178','-1':'#ff95aa'};
    for(let column=0;column<4;column++){
      const yy=bandTop+column*20;ctx.fillStyle=column===3?bright[0]:faded[0];ctx.fillRect(left,yy,width-left-right,14);
      ctx.fillStyle=column===3?'#fff0bc':colors.text;ctx.textAlign='right';ctx.fillText(labels[column],left-8,yy+12);
      for(let i=0;i+1<record.votes.length;i++){const row=record.votes[i],next=record.votes[i+1];const duration=x(next[0])-x(row[0]);if(duration<0)throw Error('票時計の逆行');ctx.fillStyle=(column===3?bright:faded)[String(row[2+column])];ctx.fillRect(x(row[0]),yy,duration,14);}
    }
    ctx.lineWidth=1;ctx.strokeStyle=colors.grid;ctx.fillStyle=colors.text;ctx.textAlign='right';
    for(const value of [-maximum,0,maximum]){ctx.beginPath();ctx.moveTo(left,q(value));ctx.lineTo(width-right,q(value));ctx.stroke();ctx.fillText(value>0?'+'+number(value):number(value),left-8,q(value)+4);}
    for(const [column,sign,color] of [[2,1,colors.buy],[3,-1,colors.sell]]){
      ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();
      record.position.forEach((p,i)=>{if(!i)ctx.moveTo(x(p[0]),q(sign*p[column]));else{ctx.lineTo(x(p[0]),q(sign*record.position[i-1][column]));ctx.lineTo(x(p[0]),q(sign*p[column]));}});ctx.stroke();
    }
    ctx.strokeStyle=colors.grid;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,money(0));ctx.lineTo(width-right,money(0));ctx.stroke();
    ctx.fillText(number(vhigh),left-8,pnlTop+4);ctx.fillText('0',left-8,money(0)+4);ctx.fillText(number(vlow),left-8,pnlBottom+4);
    ctx.strokeStyle=colors.equity;ctx.lineWidth=2;ctx.beginPath();record.tracking.forEach((p,i)=>{if(i)ctx.lineTo(x(p[0]),money(p[4]));else ctx.moveTo(x(p[0]),money(p[4]));});ctx.stroke();
    ctx.fillStyle='#e1edfc';ctx.textAlign='left';ctx.fillText('価格・全売買',left,19);ctx.fillText('3窓の票と使用入口（注文・保有とは別）',left,359);ctx.fillText('保有枚数：買い＋／売り−',left,480);ctx.fillText('時価損益 円（5分＋全約定点）',left,599);
  }

  /**
   * 固定4方式の選択された図・全注文・全返済を表示する。
   * @param {Event|undefined} event 選択変更。
   * @returns {undefined} 完了キーをwindowへ保存する。
   */
  function render(event) {
    const key=method.value+'|'+session.value+'|'+symbol.value,record=data.records[key],bars=data.candles[session.value+'|'+symbol.value],t=record.totals;
    const preview=data.preview?'人工表示 ／ ':'';
    document.getElementById('chart-summary').innerHTML=preview+escape(data.methods[method.value])+' ／ 利益 '+number(t.gross_profit_yen)+'円 ／ 損失 '+number(t.gross_loss_yen)+'円 ／ <strong class="'+(t.net_yen>=0?'gain':'loss')+'">収支 '+number(t.net_yen)+'円</strong> ／ 決済 '+number(t.closed_units)+'枚';
    document.getElementById('method-description').textContent=record.signal==='S100'?'単一S100：中央1.0倍だけを入口に使用。0.8／1.2倍の票は参考表示。':'M2_100：3窓の同方向2票以上を入口に使用。反対1票は許容。';
    document.getElementById('order-table').innerHTML=table(['時刻','原本行','判断行','組','売買','枚数','価格','理由'],record.orders.map(o=>[clock(o[0]),o[1],o[2],o[3],o[4]>0?'買い':'売り',o[5],number(o[6],1),data.reason_names[o[7]]]));
    document.getElementById('trade-table').innerHTML=table(['新規時刻','返済時刻','方向','枚数','新規価格','返済価格','損益 円','理由','新規行','返済行','組','元脚'],record.trades.map(t=>[clock(t[0]),clock(t[1]),t[2]>0?'ロング':'ショート',t[3],number(t[4],1),number(t[5],1),number(t[6]),data.reason_names[t[7]],t[8],t[9],t[10],t[11]]));
    draw(bars,record);window.chartRenderedKey=key;window.chartViewReady=true;
  }

  Object.entries(data.methods).forEach(([value,label])=>option(method,value,label));
  data.sessions.forEach(value=>option(session,value,value));
  method.value=Object.keys(data.methods)[0];session.value=data.sessions[data.sessions.length-1];symbol.value='TOPIX';
  [method,symbol,session].forEach(element=>element.addEventListener('change',render));
  window.addEventListener('resize',render);
  window.chartSelect=(m,s,k)=>{method.value=m;symbol.value=s;session.value=k;render();};
  render();
})();

