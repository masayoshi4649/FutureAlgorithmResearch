/**
 * 固定された表示参照だけを使い、足と全注文を描く。
 * 引数: なし。
 * 返り値: なし (undefined)。外部通信・注文処理は行わない。
 */
function initialize() {
  const data=JSON.parse(document.getElementById('chart-data').textContent);
  const method=document.getElementById('method'),session=document.getElementById('session'),symbol=document.getElementById('symbol');
  for(const [id,name] of Object.entries(data.methods)) method.add(new Option(name,id));
  for(const id of data.sessions) session.add(new Option(id.replace('_Day',' 昼').replace('_Night',' 夜'),id));
  method.value='POLICY';session.value=data.sessions.at(-1);
  const canvas=document.getElementById('chart');
  /**
   * UNIX秒を日本時間の時分秒にする。
   * @param {number} value - UNIX秒。
   * @returns {string} 表示時刻。
   */
  function stamp(value){return new Date(value*1000).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});}
  /**
   * 数値を表の短い表示に変換する。
   * @param {number|null} value - 表示値。
   * @returns {string} 値又は欠測記号。
   */
  function number(value){return Number.isFinite(value)?value.toLocaleString('ja-JP',{maximumFractionDigits:2}):'―';}
  /**
   * 列名と行からスクロール可能な表を作る。
   * @param {string[]} headers - 見出し。
   * @param {Array[]} rows - 表示値。
   * @returns {string} 表HTML。
   */
  function table(headers,rows){return '<div class="scroll"><table><thead><tr>'+headers.map(v=>`<th>${v}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>`<td>${v}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>';}
  /**
   * 選択された枠の実参照方式を解決し、図と明細を描画する。
   * 引数: なし。
   * 返り値: なし (undefined)。
   */
  function render(){
    const source=data.views[`${method.value}|${session.value}|${symbol.value}`],item=data.cases[source];
    const bars=data.candles[`${session.value}|${symbol.value}`],trades=item.trades,tracking=item.tracking;
    const box=canvas.getBoundingClientRect(),w=Math.max(300,box.width),h=box.height,scale=window.devicePixelRatio||1;
    canvas.width=w*scale;canvas.height=h*scale;
    const g=canvas.getContext('2d');g.scale(scale,scale);g.fillStyle='#0c1522';g.fillRect(0,0,w,h);
    const left=75,right=w-15,top=24,bottom=h-155,first=bars[0][0],last=bars.at(-1)[0]+300;
    const prices=bars.flatMap(b=>[b[2],b[3]]).concat(trades.flatMap(t=>[t[4],t[5]])).concat(tracking.flatMap(t=>[t[7],t[8],t[9]]).filter(Number.isFinite));
    let low=Math.min(...prices),high=Math.max(...prices);const pad=Math.max(.1,(high-low)*.08);low-=pad;high+=pad;
    const x=t=>left+(t-first)/(last-first)*(right-left),y=p=>bottom-(p-low)/(high-low)*(bottom-top);
    g.font='12px sans-serif';
    for(let n=0;n<=5;n++){
      const p=low+(high-low)*n/5,t=first+(last-first)*n/5;
      g.strokeStyle='#25374c';g.beginPath();g.moveTo(left,y(p));g.lineTo(right,y(p));g.stroke();
      g.fillStyle='#bbcbdc';g.fillText(number(p),5,y(p)+4);g.fillText(stamp(t).slice(0,5),Math.min(right-30,Math.max(left-10,x(t)-17)),h-10);
    }
    const bw=Math.max(1,Math.min(8,(right-left)/bars.length*.65));
    for(const b of bars){g.strokeStyle=g.fillStyle=b[4]>=b[1]?'#65c5ba':'#db718a';g.beginPath();g.moveTo(x(b[0]+150),y(b[2]));g.lineTo(x(b[0]+150),y(b[3]));g.stroke();g.fillRect(x(b[0]+150)-bw/2,Math.min(y(b[1]),y(b[4])),bw,Math.max(1,Math.abs(y(b[1])-y(b[4]))));}
    /**
     * 原本asof標本を同じ保有組の範囲だけ結ぶ。
     * @param {number} column - 標本の列。
     * @param {string} color - 線色。
     * @param {Function} vertical - 縦座標変換。
     * @returns {undefined} 描画のみ。
     */
    function line(column,color,vertical){
      g.strokeStyle=g.fillStyle=color;g.lineWidth=1.2;g.setLineDash([4,3]);
      for(let i=0;i<tracking.length;i++){
        const p=tracking[i];if(!p[3]||!Number.isFinite(p[column]))continue;
        g.beginPath();g.arc(x(p[0]),vertical(p[column]),1.5,0,Math.PI*2);g.fill();
        const q=tracking[i+1];if(q&&q[3]&&q[2]===p[2]&&Number.isFinite(q[column])){g.beginPath();g.moveTo(x(p[0]),vertical(p[column]));g.lineTo(x(q[0]),vertical(q[column]));g.stroke();}
      }
      g.setLineDash([]);
    }
    line(9,'#758fae',y);line(7,'#e895b0',y);line(8,'#e9be55',y);
    for(const e of item.events){g.fillStyle=e[8]>=2?'#ce9bff':'#8298b0';g.beginPath();g.arc(x(e[0]),y(e[7]),e[8]>=2?2.5:1.2,0,Math.PI*2);g.fill();}
    const seen=new Set();
    for(const t of trades){
      g.strokeStyle=t[6]>=0?'#57e0a1':'#ff8496';g.lineWidth=1.4;g.beginPath();g.moveTo(x(t[0]),y(t[4]));g.lineTo(x(t[1]),y(t[5]));g.stroke();
      const key=`${t[9]}|${t[2]}|${t[4]}`;
      if(!seen.has(key)){seen.add(key);g.fillStyle=t[2]>0?'#53ffb1':'#ff6687';const xx=x(t[0]),yy=y(t[4]),d=t[2];g.beginPath();g.moveTo(xx,yy);g.lineTo(xx-5,yy+d*11);g.lineTo(xx+5,yy+d*11);g.closePath();g.fill();}
      g.strokeStyle='#ffdf7c';g.lineWidth=2;g.beginPath();g.moveTo(x(t[1])-4,y(t[5])-4);g.lineTo(x(t[1])+4,y(t[5])+4);g.moveTo(x(t[1])-4,y(t[5])+4);g.lineTo(x(t[1])+4,y(t[5])-4);g.stroke();
    }
    const panelTop=bottom+32,panelBottom=h-34,maxAtr=Math.max(1,...tracking.flatMap(t=>[t[4],t[5]]).filter(Number.isFinite))*1.12;
    const ay=v=>panelBottom-v/maxAtr*(panelBottom-panelTop);g.strokeStyle='#263b50';g.lineWidth=1;g.beginPath();g.moveTo(left,panelTop);g.lineTo(right,panelTop);g.stroke();g.fillStyle='#adc0d5';g.fillText('ATR',8,panelTop+16);
    line(4,'#64d8e9',ay);line(5,'#ae97f6',ay);
    const note=method.value==='SELECTED'?' ／ 全期間固定の診断（運用ではない）':'';
    document.getElementById('chart-summary').textContent=`${item.phase} ／ 実参照 ${item.method} ／ 返済 ${trades.length}件 ／ 収支 ${item.net_yen>0?'+':''}${number(item.net_yen)}円${note}`;
    document.getElementById('trade-table').innerHTML=table(['方向','枚数','新規時刻','新規価格','返済時刻','返済価格','収支 円','理由'],trades.map(t=>[t[2]>0?'買い':'売り',t[3],stamp(t[0]),number(t[4]),stamp(t[1]),number(t[5]),number(t[6]),t[7]]));
    document.getElementById('event-table').innerHTML=`<p>追加短縮で線を進めた回数 ${item.control.additional_advance_events} ／ 固定候補による進行 ${item.control.fixed_advance_events}。悪化が出ただけの回数とは異なります。</p>`+table(['判断時刻','原本行','根拠','旧線','新線','悪化判断行','悪化参照行','At参照行'],item.events.map(e=>[stamp(e[0]),e[1],e[8]===1?'固定候補':e[8]===2?'常時MIN':'悪化条件',number(e[4]),number(e[7]),e[13],e[14],e[12]]));
    document.getElementById('preparation-table').innerHTML='<p>影と実の準備・新規約定は全件一致。準備は約定ではありません。</p>'+table(['準備時刻','原本行','準備ID','方向','初期水準','A0','期限','枚数','約定行','約定時刻'],item.preparations.actual.map(p=>[stamp(p[0]),p[1],p[2],p[3]>0?'買い':'売り',number(p[4]),number(p[5]),stamp(p[6]),p[7],p[10],p[11]===null?'なし':stamp(p[11])]));
  }
  // ----------------------------------------
  // 選択された表示枠と画面幅だけを再描画へ反映する。
  method.addEventListener('change',render);session.addEventListener('change',render);symbol.addEventListener('change',render);
  window.addEventListener('resize',render);render();
}
initialize();
