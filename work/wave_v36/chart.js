/**
 * 保存された５分足と売買明細を選択に合わせて表示する。
 * 引数: なし。
 * 返り値: なし (undefined)。外部通信・注文処理は行わない。
 */
function initialize() {
  const data = JSON.parse(document.getElementById('chart-data').textContent);
  const method = document.getElementById('method');
  const symbol = document.getElementById('symbol');
  const session = document.getElementById('session');
  for (const [id, name] of Object.entries(data.methods)) method.add(new Option(`${id} ${name}`, id));
  for (const id of data.sessions) session.add(new Option(id.replace('_Day', ' 昼').replace('_Night', ' 夜'), id));
  session.value = data.sessions.at(-1);
  const canvas = document.getElementById('chart');

  /**
   * UNIX秒を日本時間の時分秒へ変換する。
   * @param {number} time - UNIX秒。
   * @returns {string} 日本時間の表示。
   */
  function stamp(time) {
    return new Date(time * 1000).toLocaleTimeString('ja-JP', {timeZone:'Asia/Tokyo', hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }

  /**
   * 選択された確定足・取引をキャンバスと表へ再描画する。
   * 引数: なし。
   * 返り値: なし (undefined)。
   */
  function render() {
    const bars = data.candles[`${session.value}|${symbol.value}`];
    const trades = data.trades[`${method.value}|${session.value}|${symbol.value}`];
    const box = canvas.getBoundingClientRect();
    const w = Math.max(300, box.width), h = box.height;
    const scale = window.devicePixelRatio || 1;
    canvas.width = w * scale; canvas.height = h * scale;
    const g = canvas.getContext('2d'); g.scale(scale, scale);
    g.fillStyle = '#0c1522'; g.fillRect(0, 0, w, h);
    const left = 70, right = w - 15, top = 25, bottom = h - 155;
    const first = bars[0][0], last = bars.at(-1)[0] + 300;
    const plotkey=`${method.value}|${session.value}|${symbol.value}`;
    const tracking=data.tracking[plotkey];
    const episodes=data.episodes[plotkey];
    const prices=bars.flatMap(b=>[b[2],b[3]]).concat(trades.flatMap(t=>[t[4],t[5]])).concat(tracking.flatMap(t=>[t[7],t[8]]).filter(Number.isFinite));
    let low = Math.min(...prices), high = Math.max(...prices);
    const pad = Math.max(1, (high-low)*.09); low -= pad; high += pad;
    const x = t=>left+(t-first)/(last-first)*(right-left);
    const y = p=>bottom-(p-low)/(high-low)*(bottom-top);
    g.font = '12px sans-serif';
    for (let n=0;n<=5;n++) {
      const p = low+(high-low)*n/5;
      g.strokeStyle = '#25374c'; g.beginPath(); g.moveTo(left,y(p)); g.lineTo(right,y(p)); g.stroke();
      g.fillStyle = '#bbcbdc'; g.fillText(p.toLocaleString('ja-JP',{maximumFractionDigits:1}), 5, y(p)+4);
      const t = first+(last-first)*n/5;
      g.fillText(stamp(t).slice(0,5), Math.min(right-30,Math.max(left-10,x(t)-17)),h-13);
    }
    const bw = Math.max(1,Math.min(8,(right-left)/bars.length*.65));
    for (const b of bars) {
      g.strokeStyle = g.fillStyle = b[4]>=b[1] ? '#65c5ba' : '#db718a';
      g.beginPath();g.moveTo(x(b[0]+150),y(b[2]));g.lineTo(x(b[0]+150),y(b[3]));g.stroke();
      g.fillRect(x(b[0]+150)-bw/2,Math.min(y(b[1]),y(b[4])),bw,Math.max(1,Math.abs(y(b[1])-y(b[4]))));
    }
    const seen = new Set();
    for (const t of trades) {
      g.strokeStyle = t[6]>=0 ? '#57e0a1' : '#ff8496';g.lineWidth=1.4;
      g.beginPath();g.moveTo(x(t[0]),y(t[4]));g.lineTo(x(t[1]),y(t[5]));g.stroke();
      const key = `${t[0]}|${t[2]}|${t[4]}`;
      if (!seen.has(key)) {
        seen.add(key);g.fillStyle=t[2]>0?'#53ffb1':'#ff6687';
        const xx=x(t[0]), yy=y(t[4]), dir=t[2];
        g.beginPath();g.moveTo(xx,yy);g.lineTo(xx-5,yy+dir*11);g.lineTo(xx+5,yy+dir*11);g.closePath();g.fill();
      }
      g.strokeStyle='#ffdf7c';g.lineWidth=2;g.beginPath();g.moveTo(x(t[1])-4,y(t[5])-4);g.lineTo(x(t[1])+4,y(t[5])+4);g.moveTo(x(t[1])-4,y(t[5])+4);g.lineTo(x(t[1])+4,y(t[5])-4);g.stroke();g.lineWidth=1;
    }
    // ----------------------------------------
    // 5分時計の原本asof標本だけを描く。組が異なる区間とフラットは接続しない。
    /**
     * 保存された標本列を同一組の範囲だけ補助線として描く。
     * @param {number} column - 値の列番号。
     * @param {string} color - 暗色背景用の描画色。
     * @param {Function} vertical - 値を縦座標へ変える関数。
     * @returns {undefined} 描画のみ。
     */
    function drawSamples(column,color,vertical){
      g.strokeStyle=color;g.fillStyle=color;g.lineWidth=1.2;g.setLineDash([4,3]);
      for(let i=0;i<tracking.length;i++){
        const current=tracking[i];
        if(!current[3]||!Number.isFinite(current[column])) continue;
        g.beginPath();g.arc(x(current[0]),vertical(current[column]),1.7,0,Math.PI*2);g.fill();
        if(i+1<tracking.length){
          const next=tracking[i+1];
          if(next[3]&&next[2]===current[2]&&Number.isFinite(next[column])){
            g.beginPath();g.moveTo(x(current[0]),vertical(current[column]));g.lineTo(x(next[0]),vertical(next[column]));g.stroke();
          }
        }
      }
      g.setLineDash([]);g.lineWidth=1;
    }
    drawSamples(7,'#e895b0',y);drawSamples(8,'#e9be55',y);
    const panelTop=bottom+37,panelBottom=h-35;
    const atrValues=tracking.flatMap(t=>[t[4],t[5]]).filter(Number.isFinite);
    const maxAtr=Math.max(1,...atrValues)*1.1;
    const ay=v=>panelBottom-v/maxAtr*(panelBottom-panelTop);
    g.strokeStyle='#283c53';g.strokeRect(left,panelTop,right-left,panelBottom-panelTop);
    g.fillStyle='#bbcbdc';g.fillText('ATR',5,panelTop+11);g.fillText(maxAtr.toFixed(1),7,panelTop+26);
    drawSamples(4,'#61c7e2',ay);drawSamples(5,'#b492f1',ay);
    const net = trades.reduce((sum,t)=>sum+t[6],0);
    document.getElementById('episode-table').innerHTML=episodes.length?'<div class="scroll"><table><thead><tr><th>準備ID</th><th>価格準備</th><th>帯価格</th><th>先着確認</th><th>反応</th><th>全量代理</th><th>維持代理</th><th>採用</th><th>原本seq 準備/確認</th></tr></thead><tbody>'+episodes.map(e=>`<tr><td>${e.episode_id}</td><td>${stamp(e.setup_time_s)}</td><td>${e.band_price}</td><td>${e.confirmation_time_s===null?'—':stamp(e.confirmation_time_s)}</td><td>${e.response_branch==='reversal'?'反転':e.response_branch==='breakout'?'突破':e.resolution==='expired'?'期限切れ':e.resolution==='data_unavailable'?'根拠失効':'未確認'}</td><td>${e.all_volume_score.toFixed(3)}</td><td>${e.stable_volume_score.toFixed(3)}</td><td>${e.accepted?'採用':'不採用'}</td><td>${e.setup_seq} / ${e.confirmation_seq??'—'}</td></tr>`).join('')+'</tbody></table></div>':'旧H019には今回の価格帯準備を割り当てません。';

    document.getElementById('chart-summary').textContent = `決済 ${trades.length}件 ／ 収支 ${net>0?'+':''}${net.toLocaleString('ja-JP')}円。チャートは再生上の約定値を５分足上に重ねています。`;
    document.getElementById('trade-table').innerHTML = '<div class="scroll"><table><thead><tr><th>方向</th><th>建玉</th><th>枚数</th><th>新規時刻</th><th>新規価格</th><th>返済時刻</th><th>返済価格</th><th>収支 円</th><th>理由</th></tr></thead><tbody>'+trades.map(t=>`<tr><td>${t[2]>0?'買い':'売り'}</td><td>${t[8]||''}</td><td>${t[3]}</td><td>${stamp(t[0])}</td><td>${t[4]}</td><td>${stamp(t[1])}</td><td>${t[5]}</td><td class="${t[6]>0?'good':t[6]<0?'bad':'muted'}">${t[6]>0?'+':''}${t[6].toLocaleString('ja-JP')}</td><td>${t[7]}</td></tr>`).join('')+'</tbody></table></div>';
  }
  // ----------------------------------------
  // 選択変更と表示幅の変更だけを監視する。
  method.addEventListener('change',render);symbol.addEventListener('change',render);session.addEventListener('change',render);
  window.addEventListener('resize',render);render();
}
initialize();
