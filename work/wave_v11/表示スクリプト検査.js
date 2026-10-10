
const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);let selected=-1,points=[],visibleTrades=[];
/**
 * 機能: HTMLの特殊文字を表示用に変換する。
 * @param {unknown} x - 表示値。
 * @returns {string} 安全な文字列。
 */
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 機能: 円を万円の表示にする。
 * @param {number|null} x - 円。
 * @returns {string} 金額表記。
 */
function yen(x){if(x==null)return '—';x=Math.abs(x)<.000001?0:x;return (x>0?'+':'')+(x/10000).toLocaleString('ja-JP',{minimumFractionDigits:1,maximumFractionDigits:1});}
/**
 * 機能: 数値の正負を色付きで表示する。
 * @param {number|null} x - 円。
 * @returns {string} HTML。
 */
function cash(x){return `<span class="${x>0?'up':x<0?'down':''}">${yen(x)}</span>`;}
/**
 * 機能: 秒時刻を日本時間の月日と時分秒にする。
 * @param {number} t - Unix秒。
 * @param {boolean} date - 日付を表示するか。
 * @returns {string} 時刻。
 */
function clock(t,date=false){return new Date(t*1000).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',...(date?{month:'2-digit',day:'2-digit'}:{}),hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});}
/**
 * 機能: 行と列定義からスクロール表を作る。
 * @param {Array<object>} rows - 行。
 * @param {Array<Array>} cols - 見出しと取得関数。
 * @returns {string} 表HTML。
 */
function table(rows,cols){return `<div class="scroll"><table><thead><tr>${cols.map(c=>`<th>${esc(c[0])}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>'<tr>'+cols.map(c=>`<td>${c[1](r)}</td>`).join('')+'</tr>').join('')}</tbody></table></div>`;}
/**
 * 機能: 指定範囲の確定取引を合算する。
 * @param {Array<object>} rows - 集計行。
 * @returns {object} 合算値。
 */
function sum(rows){const out={};for(const k of ['利益円','損失円','収支円','費用倍収支円','評価損益円','取引数','未返済数','勝ち数','枚数上限換算収支円'])out[k]=rows.reduce((a,r)=>a+(r[k]||0),0);out.dd=Math.max(0,...rows.map(r=>r.全行最大下落円||0));return out;}
/**
 * 機能: ナイト保存断面の既知部分を完全セッションと区別する。
 * @param {string} value - セッション識別子。
 * @returns {string} 表示名。
 */
function sessionLabel(value){return value==='2026-09-23_Night'?value+'（既知・翌00:02まで）':value;}
/**
 * 機能: 条件を選んだ対象銘柄と、同条件の参考適用を区別する。
 * @param {string} id - 条件識別子。
 * @param {string} symbol - 銘柄。
 * @returns {string} 選択用途。
 */
function methodUse(id,symbol){const uses=Object.entries(D.selection.銘柄別主選択??{}).filter(([s,p])=>Object.values(p).some(c=>c.採用?.方式===id)).map(([s])=>s);return uses.includes(symbol)?symbol+'用の主候補':uses.length?'他銘柄への参考適用':'共通・群別候補';}
/**
 * 機能: 全脚の標準集計列を返す。
 * @returns {Array<Array>} 表列。
 */
function metricCols(){return [['利益／万円',r=>cash(r.利益円)],['損失／万円',r=>yen(r.損失円)],['収支／万円',r=>cash(r.収支円)],['費用倍／万円',r=>cash(r.費用倍収支円)],['未返済評価／万円',r=>cash(r.評価損益円)],['全行下落／万円',r=>yen(r.全行最大下落円??r.dd)],['確定脚数',r=>r.取引数],['未返済脚',r=>r.未返済数??0]];}
/**
 * 機能: 主評価と思想別の章を描画する。
 * @returns {void} 返り値はない。
 */
function renderChapters(){const names=['予測主導','予測と注文の組合せ','注文主導'],hypotheses=['方向予測の寄与を分けるため、検知後に成行で入り、５・15・30・60分後の固定時間で返します。平均回帰、出来高、継続、板、２銘柄の24系統を比べます。','方向の検知に、反発・突破を待つ入口、小損切りと大きい利益、条件付き追跡短縮、段階利確・利益方向への追加を組み合わせます。見送りへの減点は設けません。','方向予測モデルを置かず、固定コイン、同時両建て、上下逆指値、固定・再中心化・在庫補正グリッド、利益脚の先行返済を比較します。価格経路への暗黙の仮説は残ります。'];
 $('overview-text').innerHTML=`<p>${D.counts.条件数?.toLocaleString()??'—'}条件、予測24系統・注文10系統を比較。全${D.counts.売買数?.toLocaleString()??'—'}件の新規・返済／未返済記録を保存しました。</p>`;
 $('overview-cards').innerHTML=D.walk_summary.map(r=>`<div class="card"><span>${esc(r.思想)}</span><strong class="${r.収支円>=0?'up':'down'}">${yen(r.収支円)}万円</strong><span>費用倍 ${yen(r.費用倍収支円)}万円／${r.取引数}脚<br>最大枚数で除した収支 ${yen(r.枚数上限換算収支円)}万円</span></div>`).join('');
 $('overview-table').innerHTML=table(D.walk_summary,[['思想',r=>esc(r.思想)],...metricCols().filter(c=>!['未返済脚','全行下落／万円','未返済評価／万円'].includes(c[0])),['上限枚数換算／万円',r=>cash(r.枚数上限換算収支円)]]);
 $('walk-detail').innerHTML=table(D.walk,[['思想',r=>esc(r.思想)],['評価セッション',r=>esc(sessionLabel(r.セッション))],['銘柄',r=>r.銘柄],['過去だけで選んだ条件',r=>esc(r.方式)],...metricCols()]);
 $('chapters').innerHTML=names.map((name,idx)=>{const ms=D.methods.filter(m=>m.philosophy===name), primary=D.selection.主選択?.[name]?.採用?.方式, history=ms.flatMap(m=>['NK225','TOPIX'].map(symbol=>({id:m.id,label:m.label,cap:m.max_positions,symbol,usage:methodUse(m.id,symbol),...sum(D.rows.filter(r=>r.方式===m.id&&r.銘柄===symbol&&D.complete.includes(r.セッション)))})));return `<section class="panel" id="chapter${idx}"><div class="chapter-caption">第${idx+1}章</div><h2>${esc(name)}</h2><h3>思想と試したこと</h3><p>${hypotheses[idx]}</p><h3>結果はどうだったか</h3><p>完全５セッションの探索で選ばれた主候補は <b>${esc(primary??'該当なし')}</b>。下表は思想内の群別代表を含む探索内の成績を銘柄ごとに示します。個別用として選んだ条件を他銘柄へ適用した参考結果も分けています。上の時間順３回とは異なる範囲です。</p>${table(history,[['代表条件',r=>`<a href="#visual" data-select="${esc(r.id)}">${esc(r.id)}</a><div class="small muted wrap">${esc(r.label)}</div>`],['銘柄',r=>r.symbol],['選択用途',r=>esc(r.usage)],['総枚数上限／銘柄',r=>r.cap],...metricCols().filter(c=>!['未返済脚','未返済評価／万円'].includes(c[0])),['上限枚数換算／万円',r=>cash(r.枚数上限換算収支円)]])}<p class="small muted">下落は各銘柄の５セッションの含み損込み最大下落のうち最大値。複数日を連結した下落ではありません。損失は正の大きさで表示。</p>${ms.map(m=>`<details><summary>${esc(m.id)}｜具体的な入口・出口</summary><p>${esc(m.label)}</p><div class="rules">${m.rules.map(x=>`<p class="rule">${esc(x)}</p>`).join('')}</div><p><a href="#visual" data-select="${esc(m.id)}">この条件をチャートで確認</a></p></details>`).join('')}</section>`;}).join('');}
/**
 * 機能: 研究仮説、診断と監査の一覧を描画する。
 * @returns {void} 返り値はない。
 */
function renderResearch(){ $('prediction-list').innerHTML=table(D.profiles,[['系統',r=>esc(r.id)],['思想',r=>esc(r.group)],['仮説と条件',r=>`<div class="wrap"><b>${esc(r.label)}</b><br>${esc(r.rules)}</div>`],['一次資料',r=>`<a href="${esc(r.source)}">${esc(r.source_name)}</a>`]]);$('order-list').innerHTML=table(D.order_profiles,[['系統',r=>esc(r.family)],['注文仮説',r=>`<div class="wrap">${esc(r.label)}</div>`],['最大総枚数',r=>r.max_positions],['条件',r=>`<div class="wrap">${esc(r.exact_rules)}</div>`],['一次資料',r=>`<a href="${esc(r.provenance)}">研究の着想</a>`]]);
 let text='<p>コイントスは、都合のよい乱数を選ばず、主乱数を固定した上で64種類の感度を調べます。固定した予測の信号時刻でも方向だけを入れ替え、時刻と方向の寄与を分けます。入口・出口の比較は、相手側の条件をそろえた対応比較を使います。</p>';
 for(const [label,key,file] of [['定刻コインと３脚分割の64乱数','coins','定刻コイン_64種.csv'],['信号時刻をそろえた方向64乱数','signal_coins','信号時刻固定_方向64種.csv'],['入口と出口の対応比較','contrasts','入口と出口の対応比較.csv']]){const rows=D[key]??[];text+=`<details><summary>${label}（${rows.length}行）</summary><p><a href="資料/${file}">全明細CSV</a></p>`+(rows.length?table(rows.slice(0,100),Object.keys(rows[0]).map(k=>[k,r=>typeof r[k]==='number'?Number(r[k].toFixed(3)).toLocaleString('ja-JP'):esc(r[k])])):'<p>資料作成時点で診断結果は未保存。</p>')+'</details>';}
 text+='<p class="small muted">出口プリセットは初期損切りや利確も一緒に変わる場合があります。プリセット差を「追跡幅の短縮だけの効果」とは扱いません。多数条件からの選択と短い期間のため、無調整の勝率や順位だけで有意とは認定しません。</p>';$('diagnostic-content').innerHTML=text;
 $('audit-content').innerHTML=D.audits.map(a=>`<details><summary>${esc(a.file)}</summary><p><a href="資料/${esc(a.file)}">監査記録を開く</a></p><pre class="scroll small">${esc(JSON.stringify(a.record,null,2).slice(0,12000))}</pre></details>`).join('');
 $('live-content').innerHTML=D.live.record?'<p>一回取得記録を読み込み済み。区間別の全脚清算価値と明細は最終集計の組込み後に表示します。</p>':'<p class="notice">現在セッションの追加区間は、保存データでの比較と条件固定を終えてから一回だけ取得・照合します。この資料の生成時点では未取得です。</p>';}
/**
 * 機能: 銘柄ごとに条件を選ぶ追加方針を、共通条件と分けて表示する。
 * @returns {void} 返り値はない。
 */
function renderSymbolChoices(){const policies=D.selection.銘柄別主選択??{},names=['予測主導','予測と注文の組合せ','注文主導'];for(const [index,name] of names.entries()){const rows=(D.symbol_walk_summary??[]).filter(r=>r.思想===name),chosen=Object.entries(policies).map(([symbol,x])=>({symbol,id:x[name]?.採用?.方式})).filter(x=>x.id);const section=document.createElement('div');section.innerHTML=`${name==='注文主導'?`<p class="notice">注文主導${D.order_evidence.条件数}条件は、完全５セッション・両銘柄合計ですべて赤字。最良でも${cash(D.order_evidence.最良合計円)}万円で、銘柄別${D.order_evidence.銘柄別組数}組もすべて赤字でした。利益脚だけを先に確定しても、損失脚と全費用を合わせた優位性はこの範囲で見つかりませんでした。</p>`:''}<h3>銘柄ごとに条件を分けるとどうか</h3><p class="muted">共通条件の銘柄差を見て、探索途中で追加した選択方針です。上の共通条件を置き換えず、同じ３回の時間順評価を並べます。</p>${table(rows,[['銘柄',r=>r.銘柄],...metricCols().filter(c=>!['全行下落／万円','未返済脚','未返済評価／万円'].includes(c[0]))])}<details><summary>実際に各回で選んだ条件と損益</summary>${table(D.symbol_walk.filter(r=>r.思想===name),[['評価セッション',r=>esc(sessionLabel(r.セッション))],['銘柄',r=>r.銘柄],['選んだ条件',r=>esc(r.方式)],['収支／万円',r=>cash(r.収支円)],['費用倍／万円',r=>cash(r.費用倍収支円)]])}</details><p>完全５セッションから固定した条件: ${chosen.map(r=>`${esc(r.symbol)} <a href="#visual" data-select="${esc(r.id)}">${esc(r.id)}</a>`).join(' ／ ')}</p>`;const anchor=$('chapter'+index).querySelector('h3:nth-of-type(2)');anchor.after(section);}
 const id=policies.NK225?.['予測と注文の組合せ']?.採用?.方式;if(id){const hist=sum(D.rows.filter(r=>r.方式===id&&r.銘柄==='NK225'&&D.complete.includes(r.セッション))),walk=D.symbol_walk_summary.find(r=>r.思想==='予測と注文の組合せ'&&r.銘柄==='NK225'),known=sum(D.rows.filter(r=>r.方式===id&&r.銘柄==='NK225'&&r.セッション==='2026-09-23_Night')),latest=D.live.全体参考集計?.find(r=>r.方式===id&&r.銘柄==='NK225');const hero=document.createElement('div');hero.className='notice';hero.innerHTML=`<b>探索では有望だったが、最新夜間に崩れた候補: NK225の${esc(D.methods.find(m=>m.id===id)?.label??id)}</b><p>完全５セッションの探索で ${cash(hist.収支円)}万円／${hist.取引数}脚・${hist.勝ち数}勝（売買勝率${(100*hist.勝ち数/hist.取引数).toFixed(0)}%）。有取引４セッションで9/23デイは新規なし。これはLSTMの予測精度ではありません。NKで過去だけから条件を選び直す方針の時間順３回は ${cash(walk?.収支円)}万円、費用倍でも ${cash(walk?.費用倍収支円)}万円。最終固定条件だけの３回成績ではありません。TOPIXへ同じ条件をそのまま適用できるとは判断しません。</p><p>既に閲覧済みの9/23ナイト17:00〜翌00:02は ${cash(known.収支円)}万円・${known.取引数}脚。今回の未読追加区間では ${cash(D.live.セッション集計?.find(r=>r.方式===id&&r.銘柄==='NK225')?.追加清算価値円)}万円、区間内新規${D.live.セッション集計?.find(r=>r.方式===id&&r.銘柄==='NK225')?.区間内新規脚数??'—'}脚。ナイト全体の今回末尾までは ${cash(latest?.収支円)}万円・${latest?.取引数??'—'}脚でした。既知部分の失速も含め、安定した規則を確認できたとは判断しません。</p><p>有望な候補と、統計的に確認済みの規則は分けています。銘柄別方針は探索途中の追加で、現在照合の結果も下で確認してください。時間順では9/22デイは追跡新規0.25ATR、9/22ナイトと9/23デイは検知後の成行相当が選ばれました。<a href="#visual" data-select="${esc(id)}">入口・出口と全売買を見る</a></p>`;$('overview-text').prepend(hero);}}
/**
 * 機能: 一回照合の清算価値変化を、確定損益と残存評価から分けて表示する。
 * @returns {void} 返り値はない。
 */
function renderLive(){const rows=D.live.セッション集計??[];if(!rows.length)return;const rec=D.live.record,policies=[];for(const [name,x] of Object.entries(D.selection.主選択??{})){for(const symbol of ['NK225','TOPIX']){const r=rows.find(r=>r.方式===x.採用?.方式&&r.銘柄===symbol);if(r)policies.push({...r,policy:'共通条件／'+name});}}for(const [symbol,all] of Object.entries(D.selection.銘柄別主選択??{})){for(const [name,x] of Object.entries(all)){const r=rows.find(r=>r.方式===x.採用?.方式&&r.銘柄===symbol);if(r)policies.push({...r,policy:'銘柄別／'+name});}}
 const cols=[['銘柄',r=>r.銘柄],['条件',r=>`<a href="#visual" data-live="${esc(r.方式)}" data-symbol="${r.銘柄}">${esc(r.方式)}</a>`],['追加清算価値／万円',r=>cash(r.追加清算価値円)],['費用倍／万円',r=>cash(r.費用倍追加清算価値円)],['上限枚数換算／万円',r=>cash(r.枚数上限換算追加円)],['新起源分／万円',r=>cash(r.新信号起源追加円)],['旧起源分／万円',r=>cash(r.旧起源追加円)],['区間内新規脚',r=>r.区間内新規脚数],['末尾残脚',r=>r.終了未返済数],['判定材料',r=>r.区間内新規脚数===0?(r.旧起源追加円!==0?'新規なし・旧建玉の評価継続':'新規なし・材料不足'):'新規あり']];
 $('live-content').innerHTML=`<p>対象は ${esc(rec.known_cutoff)} から ${esc(rec.cutoff)} 未満。条件を固定後、２銘柄×生板・１分足・５分足の６URLを一回だけ取得しました。</p><div class="notice">主指標は「00:02直前の全脚清算価値」から「取得末尾の全脚清算価値」への変化です。既知区間で作った建玉も継続し、旧建玉の損失や末尾の未返済評価を隠しません。取得前に生じた未読データの照合であり、実時間の前向き運用ではありません。</div>${table(policies,[['選択方針',r=>esc(r.policy)],...cols])}<details><summary>全固定候補の追加区間成績</summary>${table(rows,cols)}</details><details><summary>確定利益・損失・開始評価・終了評価の内訳</summary>${table(rows,[['条件',r=>esc(r.方式)],['銘柄',r=>r.銘柄],['区間確定利益／万円',r=>cash(r.区間内確定利益円)],['区間確定損失／万円',r=>yen(r.区間内確定損失円)],['区間確定収支／万円',r=>cash(r.区間内確定収支円)],['開始含み評価／万円',r=>cash(r.開始評価損益円)],['末尾含み評価／万円',r=>cash(r.終了評価損益円)],['追加清算価値／万円',r=>cash(r.追加清算価値円)]])}</details><p class="small muted">旧保存ファイルの最終行を境界にした補助評価も確認しました。最終約定時刻が古いまま届いた行による差は54セル中３セルのみ（＋１万円・＋１万円・−0.5万円）で、NK主候補−９万円は同じ。主表の00:02境界は凍結通りです。<a href="資料/現在照合_旧保存行境界の補足.csv">行境界の補足</a></p><p class="small muted">新規が０脚で評価変化も０なら、この区間で予測精度が確認できたことにはなりません。確定損益には00:02以前からの値動きも含む場合があるため、追加清算価値と別の数字です。</p><p><a href="資料/現在照合_セッション集計.csv">照合集計CSV</a> ／ <a href="資料/現在照合_凍結記録.json">条件とソースの凍結記録</a> ／ <a href="資料/現在照合_取得記録.json">６要求の取得記録</a></p>`;}
/**
 * 機能: 有望候補の幅感度と公平な方向対照を、選択後の診断として示す。
 * @returns {void} 返り値はない。
 */
function renderCandidateDiagnostics(){const id=D.selection.銘柄別主選択?.NK225?.['予測と注文の組合せ']?.採用?.方式;if(!id)return;const cfg=D.methods.find(m=>m.id===id),n=D.neighbors.filter(r=>r.元方式===id&&r.銘柄==='NK225'&&D.complete.includes(r.セッション)),grouped=new Map();for(const r of n){const key=r.変更項目+'|'+r.倍率;if(!grouped.has(key))grouped.set(key,{change:r.変更項目,old:r.元値,new:r.変更値,rows:[]});grouped.get(key).rows.push(r);}const rows=[...grouped.values()].map(g=>({...g,...sum(g.rows)})),labels={entry_offset:'新規の反発待ち幅',initial_stop_atr:'初期損切り幅',trail_atr:'追跡返済幅'};const hist=sum(D.rows.filter(r=>r.方式===id&&r.銘柄==='NK225'&&D.complete.includes(r.セッション))),coin=D.signal_coins.filter(r=>r.元方式===id&&r.銘柄==='NK225'),seeds=new Map();for(const r of coin)seeds.set(r.乱数種,(seeds.get(r.乱数種)||0)+r.収支円);const values=[...seeds.values()].sort((a,b)=>a-b),median=values.length?(values[(values.length-1)>>1]+values[values.length>>1])/2:0;
 const section=document.createElement('div');section.innerHTML=`<h3>NK225の候補 ${esc(id)}：入口と出口の幅のトレードオフ</h3><p>主設定の完全５セッションは ${cash(hist.収支円)}万円、費用倍 ${cash(hist.費用倍収支円)}万円。次の表は一つの数値だけを±25%変更した探索後の感度です。</p>${table(rows,[['変えた箇所',r=>esc(labels[r.change]??r.change)],['元のATR倍',r=>r.old],['変更後',r=>r.new],['収支／万円',r=>cash(r.収支円)],['費用倍／万円',r=>cash(r.費用倍収支円)],['確定脚数',r=>r.取引数]])}<p>利益の返却を減らすため追跡幅を狭めても、細かな揺れで返済が増え、収支が下がる場合があります。「幅を狭めるほど正しい」とは評価しません。</p>${values.length?`<p>同じ信号時刻で方向だけを64乱数に変えたNK225の５セッション収支は、最小 ${cash(values[0])}万円、中央値 ${cash(median)}万円、最大 ${cash(values.at(-1))}万円。実方向 ${cash(hist.収支円)}万円以上は${values.filter(v=>v>=hist.収支円).length}/${values.length}種でした。ただし候補を既知結果から選んだ後の診断なので、この比率を有意確率とは呼びません。</p>`:''}<p class="small muted">追加費用０・１・２・４呼値の表は、注文経路を基本２呼値の条件のまま固定して再採点したものです。条件判断まで各費用で作り直す再実行とは異なります。<a href="資料/追加費用0_1_2_4呼値.csv">費用感度CSV</a></p>`;$('diagnostic-content').prepend(section);
 const stats=Object.entries(D.statistics.時間順全政策??{}).map(([name,r])=>({name,...r}));if(stats.length){const block=document.createElement('div');block.innerHTML='<h3>経済的な候補と統計的な確認を分ける</h3>'+table(stats,[['選択方針',r=>esc(r.name)],['時間順セッション数',r=>r.セッション数],['未補正の符号反転比率',r=>r.未補正比率],['６政策のHolm補正',r=>r.全政策のHolm補正比率]])+'<p class="muted">時間順３ブロックでは両側比率は最小でも0.25です。セッション独立性・符号対称性も確認できず、これまでの研究の設計変更まで補正できません。<a href="資料/独立統計診断.md">独立統計診断</a></p>';$('diagnostic-content').append(block);}
 const prediction=D.predictions.filter(r=>r.系統===cfg?.signal&&r.銘柄==='NK225'&&D.complete.includes(r.セッション)),horizons=[5,15,30,60].map(h=>{const a=prediction.filter(r=>r.予測分===h),number=a.reduce((s,r)=>s+r.予測数,0),ok=a.reduce((s,r)=>s+r.方向正解,0),ng=a.reduce((s,r)=>s+r.方向不正解,0);return {h,number,rate:ok+ng?ok/(ok+ng):null,mean:number?a.reduce((s,r)=>s+(r.平均費用後円||0)*r.予測数,0)/number:null};});const box=document.createElement('details');box.innerHTML='<summary>長い時間幅ほど方向正答率が上がるか：NK候補の信号診断</summary><p>公開信号ごとの５・15・30・60分後を比べる事後診断です。期間が重なる予測は独立な取引ではありません。方向正答率は同値を除き、売買勝率とは別です。</p>'+table(horizons,[['予測時間／分',r=>r.h],['評価信号数',r=>r.number],['方向正答率',r=>r.rate==null?'—':(r.rate*100).toFixed(1)+'%'],['平均費用後／万円',r=>cash(r.mean)]])+'<p class="small muted">時間幅を長くすれば必ず有効になる、という前提は置いていません。この診断ラベルを入口の計算へ逆流させていません。</p>';$('diagnostic-content').append(box);}
/**
 * 機能: 表示する条件・銘柄・セッションの組を返す。
 * @returns {object} 選択値と対応データ。
 */
function selection(){const method=$('method').value,symbol=$('symbol').value,session=$('session').value;return {method,symbol,session,cfg:D.methods.find(m=>m.id===method),bars:D.candles[`${session}|${symbol}`]??[],trades:D.trades.filter(t=>t.method===method&&t.symbol===symbol&&t.session===session),curve:D.curves[`${method}|${session}|${symbol}`]??[]};}
/**
 * 機能: 選択した条件のルールと全脚明細を描画する。
 * @returns {void} 返り値はない。
 */
function refresh(){const s=selection();visibleTrades=s.trades;$('chart-rules').innerHTML=s.cfg?.rules.map(x=>`<p>${esc(x)}</p>`).join('')??'';const row=D.rows.filter(r=>r.方式===s.method&&r.セッション===s.session&&r.銘柄===s.symbol);$('session-summary').innerHTML=table(row,[['総枚数上限／銘柄',r=>r.設定最大枚数],...metricCols(),['上限枚数換算／万円',r=>cash(r.枚数上限換算収支円)]]);
 $('trade-table').innerHTML='<div class="scroll"><table><thead><tr>'+['脚','組','方向','条件作成','新規','新規価格','返済／評価','価格','確定収支／万円','未返済評価／万円','最大順行／万円','理由'].map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>'+s.trades.map((t,i)=>`<tr data-trade="${i}" class="${selected===i?'selected':''}"><td>${i+1}</td><td>${t.cycle==null?'—':t.cycle+1}</td><td>${t.side>0?'買':'売'}</td><td>${clock(t.condition)}</td><td>${clock(t.entry)}</td><td>${t.ep.toLocaleString()}</td><td>${clock(t.exit)}</td><td>${t.xp.toLocaleString()}</td><td>${t.closed?cash(t.net):'—'}</td><td>${t.closed?'—':cash(t.net)}</td><td>${yen(t.mfe)}</td><td>${esc(t.reason)}</td></tr>`).join('')+'</tbody></table></div>';
 $('method-table').innerHTML=table(D.rows.filter(r=>r.方式===s.method),[['セッション',r=>esc(sessionLabel(r.セッション))],['銘柄',r=>r.銘柄],...metricCols()]);draw(s);}
/**
 * 機能: 高解像度のキャンバス描画領域を初期化する。
 * @param {string} id - キャンバスID。
 * @returns {object} 文脈と寸法。
 */
function canvas(id){const el=$(id),r=el.getBoundingClientRect(),dpr=window.devicePixelRatio||1;el.width=r.width*dpr;el.height=r.height*dpr;const ctx=el.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#0a1423';ctx.fillRect(0,0,r.width,r.height);ctx.font='12px "Yu Gothic UI",sans-serif';return {ctx,w:r.width,h:r.height};}
/**
 * 機能: 時間と値の範囲に沿って暗色の目盛を描く。
 * @param {object} c - 描画領域。
 * @param {number} lo - 開始秒。
 * @param {number} hi - 終了秒。
 * @param {number} bottom - 最小値。
 * @param {number} top - 最大値。
 * @param {boolean} cashAxis - 万円で表示するか。
 * @returns {object} 座標変換関数。
 */
function axes(c,lo,hi,bottom,top,cashAxis=false){const {ctx,w,h}=c,L=76,R=22,T=26,B=39,x=t=>L+(t-lo)/(hi-lo)*(w-L-R),y=v=>h-B-(v-bottom)/(top-bottom)*(h-T-B);ctx.strokeStyle='#253952';ctx.fillStyle='#aebed5';ctx.lineWidth=1;for(let k=0;k<=5;k++){const yy=T+k*(h-T-B)/5,v=top-k*(top-bottom)/5;ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(w-R,yy);ctx.stroke();ctx.textAlign='right';ctx.fillText(cashAxis?(v/10000).toFixed(1):v.toLocaleString('ja-JP',{maximumFractionDigits:1}),L-9,yy+4);}for(let k=0;k<=6;k++){const t=lo+k*(hi-lo)/6,xx=x(t);ctx.beginPath();ctx.moveTo(xx,T);ctx.lineTo(xx,h-B);ctx.stroke();ctx.textAlign='center';ctx.fillText(clock(t).slice(0,5),xx,h-15);}if(cashAxis){ctx.textAlign='left';ctx.fillText('万円',12,14);}return {x,y,L,R,T,B};}
/**
 * 機能: ５分足、建玉線、エントリー・返済記号、資産曲線を描画する。
 * @param {object} s - 選択したデータ。
 * @returns {void} 返り値はない。
 */
function draw(s){points=[];let lo=s.bars[0]?.[0]??s.curve[0]?.[0],hi=Math.max(s.bars.at(-1)?.[0]+300||0,...s.trades.map(t=>t.exit||0),s.curve.at(-1)?.[0]||0);if(!lo||!hi){const c=canvas('chart');c.ctx.fillStyle='#b0c1d8';c.ctx.fillText('この範囲の描画データはありません。',30,50);canvas('equity');return;}if($('range').value==='current'&&s.session.includes('Night'))lo=Math.min(hi-300,Math.max(lo,D.known_cutoff));if($('range').value==='trade'&&s.trades[selected]){const t=s.trades[selected];lo=Math.max(lo,t.entry-1800);hi=Math.min(hi,t.exit+1800);}if(hi-lo<600)hi=lo+600;const bars=s.bars.filter(b=>b[0]+300>=lo&&b[0]<=hi),ts=s.trades.map((t,i)=>({...t,i})).filter(t=>t.exit>=lo&&t.entry<=hi),prices=bars.flatMap(b=>[b[2],b[3]]).concat(ts.flatMap(t=>[t.ep,t.xp]));if(!prices.length)return;let low=Math.min(...prices),high=Math.max(...prices),pad=Math.max((high-low)*.12, s.symbol==='NK225'?30:1.5);low-=pad;high+=pad;const c=canvas('chart'),{ctx,w,h}=c,a=axes(c,lo,hi,low,high),body=Math.max(1,Math.min(11,(w-98)*300/(hi-lo)*.63));
 if(s.session.includes('23_Night')&&D.known_cutoff>=lo&&D.known_cutoff<=hi){ctx.fillStyle='#9478e018';ctx.fillRect(a.x(D.known_cutoff),a.T,w-a.x(D.known_cutoff)-22,h-a.T-a.B);ctx.fillStyle='#c0aaf3';ctx.textAlign='right';ctx.fillText('00:02以降の追加区間',w-25,17);}
 for(const b of bars){const xx=a.x(b[0]+150),up=b[4]>=b[1];ctx.strokeStyle=ctx.fillStyle=up?'#51cca5':'#ee8294';ctx.beginPath();ctx.moveTo(xx,a.y(b[2]));ctx.lineTo(xx,a.y(b[3]));ctx.stroke();ctx.fillRect(xx-body/2,Math.min(a.y(b[1]),a.y(b[4])),body,Math.max(1,Math.abs(a.y(b[1])-a.y(b[4]))));}
 for(const t of ts){const focus=selected===t.i,alpha=selected>=0&&!focus ? .2 : .8;ctx.globalAlpha=alpha;ctx.strokeStyle=t.net>=0?'#67e2b2':'#ff9fa8';ctx.lineWidth=focus?2.5:1;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(a.x(t.entry),a.y(t.ep));ctx.lineTo(a.x(t.exit),a.y(t.xp));ctx.stroke();ctx.setLineDash([]);const x=a.x(t.entry),y=a.y(t.ep),r=focus?8:6;ctx.fillStyle=t.side>0?'#58ddb0':'#ff8d9d';ctx.beginPath();ctx.moveTo(x,y+(t.side>0?-r:r));ctx.lineTo(x-r,y+(t.side>0?r:-r));ctx.lineTo(x+r,y+(t.side>0?r:-r));ctx.closePath();ctx.fill();points.push({x,y,trade:t});const xx=a.x(t.exit),yy=a.y(t.xp);ctx.strokeStyle=t.closed?'#ecf4ff':'#ffd386';ctx.lineWidth=2;ctx.beginPath();if(t.closed){ctx.moveTo(xx-5,yy-5);ctx.lineTo(xx+5,yy+5);ctx.moveTo(xx+5,yy-5);ctx.lineTo(xx-5,yy+5);}else{ctx.moveTo(xx,yy-7);ctx.lineTo(xx+7,yy);ctx.lineTo(xx,yy+7);ctx.lineTo(xx-7,yy);ctx.closePath();}ctx.stroke();points.push({x:xx,y:yy,trade:t});ctx.globalAlpha=1;}ctx.textAlign='left';ctx.fillStyle='#d5e5fa';ctx.fillText(`${s.symbol} ｜ ${s.session} ｜ ${s.method}`,80,17);
 const ec=canvas('equity'),curve=s.curve.filter(r=>r[0]>=lo&&r[0]<=hi);if(curve.length){const values=curve.flatMap(r=>[r[2],r[3]]).concat([0]);let mn=Math.min(...values),mx=Math.max(...values),p=Math.max((mx-mn)*.1,10000);const e=axes(ec,lo,hi,mn-p,mx+p,true);for(const [col,color] of [[2,'#58ddb0'],[3,'#ffb57f']]){ec.ctx.strokeStyle=color;ec.ctx.lineWidth=1.8;ec.ctx.beginPath();curve.forEach((r,i)=>i?ec.ctx.lineTo(e.x(r[0]),e.y(r[col])):ec.ctx.moveTo(e.x(r[0]),e.y(r[col])));ec.ctx.stroke();}}}
/**
 * 機能: 最寄りの売買マーカーの明細を表示する。
 * @param {MouseEvent} event - マウス移動。
 * @returns {void} 返り値はない。
 */
function tooltip(event){const r=$('chart').getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top,p=points.reduce((best,p)=>Math.hypot(p.x-x,p.y-y)<Math.hypot((best?.x??-1e5)-x,(best?.y??-1e5)-y)?p:best,null),el=$('tooltip');if(!p||Math.hypot(p.x-x,p.y-y)>16){el.style.display='none';return;}const t=p.trade;el.innerHTML=`<b>脚${t.i+1} ${t.side>0?'買い':'売り'} ${t.cycle==null?'':`／組${t.cycle+1}`}</b><br>新規 ${clock(t.entry,true)}　${t.ep}<br>${t.closed?'返済':'評価'} ${clock(t.exit,true)}　${t.xp}<br>${t.closed?'確定収支':'未返済評価'} ${cash(t.net)}万円<br>ATR ${t.atr.toFixed(2)}／最大順行 ${yen(t.mfe)}万円<br>${esc(t.reason)}`;el.style.display='block';el.style.left=Math.min(x+14,r.width-360)+'px';el.style.top=Math.min(y+12,r.height-160)+'px';}
// ----------------------------------------
renderChapters();renderResearch();renderSymbolChoices();renderLive();renderCandidateDiagnostics();$('method').innerHTML=D.methods.map(m=>`<option value="${esc(m.id)}">${esc(m.id)}｜${esc(m.label)}</option>`).join('');$('session').innerHTML=D.sessions.map(s=>`<option value="${esc(s)}">${esc(sessionLabel(s))}</option>`).join('');const primary=D.selection.銘柄別主選択?.NK225?.['予測と注文の組合せ']?.採用?.方式??D.selection.主選択?.['予測と注文の組合せ']?.採用?.方式;if(primary)$('method').value=primary;$('session').value='2026-09-22_Night';
for(const id of ['method','symbol','session'])$(id).addEventListener('change',()=>{selected=-1;refresh();});$('range').addEventListener('change',refresh);$('reset').addEventListener('click',()=>{selected=-1;refresh();});$('trade-table').addEventListener('click',e=>{const tr=e.target.closest('[data-trade]');if(tr){selected=Number(tr.dataset.trade);refresh();}});document.addEventListener('click',e=>{const live=e.target.closest('[data-live]');if(live){$('method').value=live.dataset.live;$('symbol').value=live.dataset.symbol;$('session').value=D.live.display_session;$('range').value='current';selected=-1;refresh();return;}const a=e.target.closest('[data-select]');if(a){$('method').value=a.dataset.select;selected=-1;refresh();}});$('chart').addEventListener('mousemove',tooltip);$('chart').addEventListener('mouseleave',()=>{$('tooltip').style.display='none';});window.addEventListener('resize',()=>draw(selection()));refresh();
