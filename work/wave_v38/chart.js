/**
 * 保存された確定足と全注文を、選択された方式・銘柄・区間に合わせて描く。
 * 引数: なし。
 * 返り値: なし (undefined)。通信・注文送信は行わない。
 */
function initialize() {
  const data = JSON.parse(document.getElementById('chart-data').textContent);
  const method = document.getElementById('method');
  const symbol = document.getElementById('symbol');
  const session = document.getElementById('session');
  const canvas = document.getElementById('chart');
  for (const [id, label] of Object.entries(data.methods)) method.add(new Option(label, id));
  for (const s of data.sessions) session.add(new Option(s.replace('_Day', ' 昼').replace('_Night', ' 夜'), s));
  session.value = data.sessions.at(-1);

  /**
   * 保存UNIX秒を日本時間の時分秒へ変換する。
   * @param {number|null} t - 秒又は欠損。
   * @returns {string} 時刻表示。
   */
  function stamp(t) {
    return t === null ? '—' : new Date(t*1000).toLocaleTimeString('ja-JP', {timeZone:'Asia/Tokyo', hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }

  /**
   * 有限数を桁区切りで表示する。
   * @param {number} value - 保存数値。
   * @returns {string} 数値表示。
   */
  function num(value) { return value.toLocaleString('ja-JP', {maximumFractionDigits:2}); }

  /**
   * 全行を省略せず、表の見出しと値からHTMLを作る。
   * @param {Array<string>} headers - 見出し。
   * @param {Array<Array<string|number>>} rows - 固定された表示値。
   * @returns {string} 表のHTML。
   */
  function table(headers, rows) {
    return '<div class="scroll"><table><thead><tr>'+headers.map(v=>`<th>${v}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>`<td>${v}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>';
  }

  /**
   * キャンバスと全注文・全返済・調整根拠の表を再描画する。
   * 引数: なし。
   * 返り値: なし (undefined)。描画後に検査用キーを公開する。
   */
  function render() {
    const key = `${method.value}|${session.value}|${symbol.value}`;
    const bars = data.candles[`${session.value}|${symbol.value}`];
    const orders = data.orders[key], trades = data.trades[key], trace = data.tracking[key], adjustments = data.adjustments[key], branches = data.branches[key];
    const box = canvas.getBoundingClientRect(), w = Math.max(300, box.width), h = box.height;
    const scale = window.devicePixelRatio || 1;
    canvas.width = w*scale; canvas.height = h*scale;
    const g = canvas.getContext('2d'); g.scale(scale, scale);
    g.fillStyle = '#0c1522'; g.fillRect(0, 0, w, h);
    const left=72, right=w-20, top=25, bottom=h-145;
    const first=bars[0][0], last=bars.at(-1)[0]+300;
    const values=bars.flatMap(b=>[b[2],b[3]]).concat(orders.map(o=>o[6]));
    let low=Math.min(...values), high=Math.max(...values);
    const pad=Math.max(1,(high-low)*.08); low-=pad; high+=pad;
    const x=t=>left+(t-first)/(last-first)*(right-left), y=p=>bottom-(p-low)/(high-low)*(bottom-top);
    g.font='12px sans-serif';
    for(let i=0;i<=5;i++){
      const p=low+(high-low)*i/5, t=first+(last-first)*i/5;
      g.strokeStyle='#273c51';g.beginPath();g.moveTo(left,y(p));g.lineTo(right,y(p));g.stroke();
      g.fillStyle='#b8c9dd';g.fillText(num(p),4,y(p)+4);g.fillText(stamp(t).slice(0,5),Math.min(right-35,x(t)-15),h-8);
    }
    const bw=Math.max(1,Math.min(8,(right-left)/bars.length*.65));
    for(const b of bars){
      g.fillStyle=g.strokeStyle=b[4]>=b[1]?'#65c5ba':'#da718c';
      g.beginPath();g.moveTo(x(b[0]+150),y(b[2]));g.lineTo(x(b[0]+150),y(b[3]));g.stroke();
      g.fillRect(x(b[0]+150)-bw/2,Math.min(y(b[1]),y(b[4])),bw,Math.max(1,Math.abs(y(b[1])-y(b[4]))));
    }
    g.lineWidth=1;g.globalAlpha=.32;
    for(const t of trades){
      g.strokeStyle=t[6]>=0?'#57dfa2':'#ff8da0';g.beginPath();g.moveTo(x(t[0]),y(t[4]));g.lineTo(x(t[1]),y(t[5]));g.stroke();
    }
    g.globalAlpha=1;
    for(const o of orders){
      const xx=x(o[0]),yy=y(o[6]),reason=o[7],side=o[4];
      g.lineWidth=2;
      if(reason===20){
        g.fillStyle=side>0?'#66ffbd':'#ff6687';g.beginPath();g.moveTo(xx,yy);g.lineTo(xx-5,yy+side*10);g.lineTo(xx+5,yy+side*10);g.closePath();g.fill();
      }else if(reason===31){
        g.strokeStyle='#63dcff';g.beginPath();g.moveTo(xx,yy-6);g.lineTo(xx+6,yy);g.lineTo(xx,yy+6);g.lineTo(xx-6,yy);g.closePath();g.stroke();
      }else if(reason===30){
        g.strokeStyle='#ffac66';g.strokeRect(xx-5,yy-5,10,10);
      }else{
        g.strokeStyle=reason===32?'#ff687f':'#ffe080';g.beginPath();g.moveTo(xx-4,yy-4);g.lineTo(xx+4,yy+4);g.moveTo(xx-4,yy+4);g.lineTo(xx+4,yy-4);g.stroke();
      }
    }
    // ----------------------------------------
    // 数量は時計以前の最後の観測だけ。補助線はその標本を保持する階段表示。
    // ----------------------------------------
    // 紫帯は方法を選んだ判断であり、価格上の注文マーカーと区別する。
    g.fillStyle='#bdb1ef';g.fillText('復元選択',4,bottom+25);
    g.strokeStyle='#45375f';g.beginPath();g.moveTo(left,bottom+20);g.lineTo(right,bottom+20);g.stroke();
    for(const b of branches){
      const xx=x(b[0]);g.fillStyle='#d1a3ff';g.beginPath();g.arc(xx,bottom+20,3,0,2*Math.PI);g.fill();
      g.fillText(b[4]===1?'信':'時',Math.min(right-14,xx+4),bottom+14);
    }
    if(!branches.length){g.fillStyle='#b8c9dd';g.fillText('選択イベントなし',left+8,bottom+15);}
    const pt=bottom+44,pb=h-33,maxq=Math.max(1,...trace.flatMap(v=>[v[2],v[3]]));
    const qy=q=>pb-q/maxq*(pb-pt);
    g.strokeStyle='#2b4056';g.strokeRect(left,pt,right-left,pb-pt);
    g.fillStyle='#b8c9dd';g.fillText('保有枚数',4,pt+12);g.fillText(String(maxq),15,pt+29);
    for(const [column,color,dash] of [[3,'#8195aa',[4,3]],[2,'#6cd8ff',[]]]){
      g.strokeStyle=color;g.lineWidth=1.5;g.setLineDash(dash);g.beginPath();
      for(let i=0;i<trace.length;i++){
        const current=trace[i];
        if(i===0) g.moveTo(x(current[0]),qy(current[column]));
        else {g.lineTo(x(current[0]),qy(trace[i-1][column]));g.lineTo(x(current[0]),qy(current[column]));}
      }
      g.stroke();g.setLineDash([]);
    }
    const net=trades.reduce((sum,t)=>sum+t[6],0), profit=trades.reduce((sum,t)=>sum+Math.max(t[6],0),0),loss=-trades.reduce((sum,t)=>sum+Math.min(t[6],0),0);
    document.getElementById('chart-summary').textContent=`利益 ${num(profit)}円 ／ 損失 ${num(loss)}円 ／ 収支 ${net>0?'+':''}${num(net)}円。全注文${orders.length}件、返済${trades.length}件。`;
    document.getElementById('method-description').textContent=data.descriptions[method.value];
    document.getElementById('order-table').innerHTML=table(['時刻','操作','買売','枚数','価格','原本行','判断元行'],orders.map(o=>[stamp(o[0]),data.reason_names[o[7]],o[4]>0?'買い':'売り',o[5],num(o[6]),o[1],o[2]]));
    document.getElementById('trade-table').innerHTML=table(['方向','枚数','新規時刻','新規価格','返済時刻','返済価格','収支 円','理由'],trades.map(t=>[t[2]>0?'買い':'売り',t[3],stamp(t[0]),num(t[4]),stamp(t[1]),num(t[5]),num(t[6]),data.reason_names[t[7]]]));
    document.getElementById('adjustment-table').innerHTML=table(['時刻','状態','操作','枚数','根拠公開','根拠行','判断元行','原本行'],adjustments.map(a=>[stamp(a[0]),data.adjustment_names[a[3]],a[4]<0?'減量':a[4]>0?'復元':'資格終了',a[7],stamp(a[9]),a[6],a[5],a[1]]));
    const classifications=['欠測・無効','有効中立','保有方向と同じ','保有逆方向'];
    document.getElementById('branch-table').innerHTML=table(['選択時刻','元組','減量回','選択方法','B01判定','方向','根拠公開','根拠行','判断行'],branches.map(b=>[stamp(b[0]),b[2],b[3],b[4]===1?'新しい肯定':'120秒時計',classifications[b[8]],!b[7]?'欠測・無効':b[5]>0?'上':b[5]<0?'下':'中立',stamp(b[11]),b[6],b[1]]));
    window.chartViewReady=true;window.chartRenderedKey=key;
  }
  method.addEventListener('change',render);symbol.addEventListener('change',render);session.addEventListener('change',render);
  window.addEventListener('resize',render);render();
}
initialize();
