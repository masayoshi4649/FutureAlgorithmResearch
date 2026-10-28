import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const work = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(work, '../..');
const output = path.join(root, 'outputs/00149_preus_reset');
const publication = path.join(root, 'アルゴリズム調査/00149_米国前の制限根拠と前後独立運転');
const filename = '米国前の制限と前後独立運転の損益.xlsx';
const report = JSON.parse(await fs.readFile(path.join(work, 'report149.json'), 'utf8'));
const market = JSON.parse(await fs.readFile(path.join(work, 'data/市場特性149.json'), 'utf8'));
const relative = JSON.parse(await fs.readFile(path.join(work, 'data/相対幅の先着149.json'), 'utf8'));
const methods = [...report.methods].sort((a,b) => a.id.localeCompare(b.id));
if (methods[0].id !== 'C00' || new Set(methods.map(m => m.id)).size !== methods.length) throw new Error('C00と独立条件が必要です。');
const workbook = Workbook.create();
const comparison = workbook.worksheets.add('比較');
const details = new Map(methods.map(m => [m.id, workbook.worksheets.add(`日経_${m.id}`)]));
const current = workbook.worksheets.add('当夜途中');
const marketSheet = workbook.worksheets.add('市場特性');
const expected = [];
const renders = [];
const formatMoney = '#,##0;[Red](#,##0);"—"';

/**
 * 元会計と計算結果を検算する。
 * @param {number} actual - セルの数値。
 * @param {number} wanted - 原会計の数値。
 * @param {string} label - 検算位置。
 * @returns {void} 不一致なら停止する。
 */
function equal(actual,wanted,label) {
  if (!Number.isFinite(actual) || !Number.isFinite(wanted) || Math.abs(actual-wanted)>0.0001) throw new Error(`${label}: ${actual} / ${wanted}`);
}

/**
 * 共通の読みやすい表書式を設定する。
 * @param {object} sheet - 対象シート。
 * @param {string} end - 最終列。
 * @param {number} rows - 最終行。
 * @param {string} title - 見出し。
 * @param {string} context - 条件説明。
 * @returns {void} 返り値なし。
 */
function style(sheet,end,rows,title,context) {
  sheet.showGridLines=false;
  sheet.tabColor='#244A70';
  const area=sheet.getRange(`A1:${end}${rows}`);
  area.format.font={name:'Yu Gothic',size:10,color:'#1B3048'};
  area.format.rowHeight=23;
  area.format.columnWidth=17;
  area.format.verticalAlignment='center';
  sheet.getRange(`A1:A${rows}`).format.columnWidth=27;
  sheet.getRange('A2').values=[[title]];
  sheet.getRange('A2').format.font={bold:true,size:14};
  sheet.getRange(`A2:${end}2`).format.borders={bottom:{style:'thin',color:'#A5B5C5'}};
  sheet.getRange('A3').values=[['日経mini・片方向上限10枚・手数料0円・気配差込み。2026/09/21〜10/23の既知25夜。']];
  sheet.getRange('A4').values=[[context]];
  sheet.getRange('A3:A5').format.font={size:10,color:'#52677C'};
}

/**
 * 明示名の正式なExcelテーブルを追加する。
 * @param {object} sheet - 対象シート。
 * @param {string[]} headers - 列見出し。
 * @param {number} begin - 見出し行。
 * @param {number} last - 最終データ行。
 * @param {string} end - 最終列。
 * @param {string} name - 表名。
 * @returns {void} 返り値なし。
 */
function table(sheet,headers,begin,last,end,name) {
  sheet.getRange(`A${begin}:${end}${begin}`).values=[headers];
  const t=sheet.tables.add(`A${begin}:${end}${last}`,true,name);
  t.showFilterButton=true;
  sheet.getRange(`A${begin}:${end}${begin}`).format={fill:'#244A70',font:{bold:true,color:'#FFFFFF'},
    horizontalAlignment:'center',wrapText:true,rowHeight:42,
    borders:{insideVertical:{style:'thin',color:'#FFFFFF'}}};
  if (begin===6) sheet.freezePanes.freezeRows(6);
}

/**
 * 金額と赤字セルを整える。
 * @param {object} sheet - 対象シート。
 * @param {string} address - 金額範囲。
 * @returns {void} 返り値なし。
 */
function money(sheet,address) {
  const range=sheet.getRange(address);
  range.setNumberFormat(formatMoney);
  range.format.horizontalAlignment='right';
  range.conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#FBEAEC',font:{color:'#A02836'}}});
}

/**
 * JSONの原会計から独立に総計を求める。
 * @param {object[]} rows - 各セッションの原会計。
 * @returns {object} 合計と損失頻度。
 */
function totals(rows) {
  const sum=k=>rows.reduce((v,r)=>v+r[k],0);
  const nets=rows.map(r=>r.net).sort((a,b)=>b-a);
  return {profit:sum('profit'),loss:sum('loss'),net:sum('net'),entries:sum('entries'),
    pre:rows.reduce((s,r)=>s+r.pre.net,0),post:rows.reduce((s,r)=>s+r.post.net,0),
    wins:nets.filter(x=>x>0).length,losses:nets.filter(x=>x<0).length,
    maxloss:Math.max(0,-Math.min(...nets)),ex3:sum('net')-nets.slice(0,3).reduce((s,n)=>s+Math.max(0,n),0),
    zero_entries:rows.filter(r=>r.entries===0).length};
}

// ----------------------------------------
// 手法ごとの完了25夜。前後段と全夜の収支・累計はセル式で所有する。
for (const method of methods) {
  const rows=[...method.rows].sort((a,b)=>a.session.localeCompare(b.session));
  if (rows.length!==25 || new Set(rows.map(r=>r.session)).size!==25) throw new Error(`${method.id}:25夜ではありません。`);
  method.rows=rows;
  const sheet=details.get(method.id);
  style(sheet,'O',32,`${method.id}　全夜間の損益`,'利益・損失は完結した親取引で分類。前後は親の初回新規が米国開始より前か後かで区分。');
  sheet.getRange('A5').values=[[method.description]];
  sheet.getRange('A7:O31').values=rows.map(r=>[r.session,r.pre.profit,r.pre.loss,null,r.post.profit,r.post.loss,null,null,null,null,null,r.entries,r.pre.entries,r.post.entries,r.max_per_side]);
  let cumulative=0;
  rows.forEach((r,i)=>{
    const n=i+7;
    equal(r.pre.profit-r.pre.loss,r.pre.net,`${method.id}/${r.session}/前`);
    equal(r.post.profit-r.post.loss,r.post.net,`${method.id}/${r.session}/後`);
    equal(r.pre.profit+r.post.profit,r.profit,`${method.id}/${r.session}/利益`);
    equal(r.pre.loss+r.post.loss,r.loss,`${method.id}/${r.session}/損失`);
    equal(r.pre.net+r.post.net,r.net,`${method.id}/${r.session}/全夜`);
    sheet.getRange(`D${n}`).formulas=[[`=B${n}-C${n}`]];
    sheet.getRange(`G${n}:K${n}`).formulas=[[`=E${n}-F${n}`,`=B${n}+E${n}`,`=C${n}+F${n}`,`=H${n}-I${n}`,i===0?`=J${n}`:`=K${n-1}+J${n}`]];
    cumulative+=r.net;
    for (const [col,value] of [['D',r.pre.net],['G',r.post.net],['H',r.profit],['I',r.loss],['J',r.net],['K',cumulative]]) expected.push([sheet.name,`${col}${n}`,value]);
  });
  sheet.getRange('A32').values=[['25夜累計']];
  sheet.getRange('B32:O32').formulas=[['=SUM(B7:B31)','=SUM(C7:C31)','=B32-C32','=SUM(E7:E31)','=SUM(F7:F31)','=E32-F32','=B32+E32','=C32+F32','=H32-I32','=K31','=SUM(L7:L31)','=SUM(M7:M31)','=SUM(N7:N31)','=MAX(O7:O31)']];
  table(sheet,['セッション','前半利益（円）','前半損失（円）','前半収支（円）','後半利益（円）','後半損失（円）','後半収支（円）','全夜利益（円）','全夜損失（円）','全夜収支（円）','累計（円）','新規件数','前半新規件数','後半新規件数','最大片側保有枚数'],6,31,'O',`Method149_${method.id}`);
  money(sheet,'B7:K32');
  sheet.getRange('L7:O32').setNumberFormat('#,##0');
  sheet.getRange('A32:O32').format.font={bold:true};
  sheet.getRange('A32:O32').format.borders={top:{style:'thin',color:'#A5B5C5'}};
  const s=totals(rows);
  for (const [col,value] of [['D',s.pre],['G',s.post],['H',s.profit],['I',s.loss],['J',s.net],['K',s.net],['L',s.entries]]) expected.push([sheet.name,`${col}32`,value]);
  renders.push([sheet,'O',32]);
}

// ----------------------------------------
// 比較は各明細から参照する。C00は今回のGo模型で再生した独立の基準。
const last=methods.length+6;
style(comparison,'N',last,'米国前の制限と前後独立運転の比較','C00は今回のGo再生基準。旧145の保存D07とは別模型。R条件は米国開始で指標・戦略状態を初期化。');
comparison.getRange('A5').values=[['条件の説明は同じフォルダの補足md。前後段の区分と枚数は各手法シートで確認できます。']];
methods.forEach((method,i)=>{
  const n=i+7;
  const p=`'日経_${method.id}'!`;
  const nets=`${p}$J$7:$J$31`;
  const entries=`${p}$L$7:$L$31`;
  comparison.getRange(`A${n}`).values=[[method.id]];
  comparison.getRange(`B${n}:N${n}`).formulas=[[`=${p}D32`,`=${p}G32`,`=${p}J32`,`=${p}H32`,`=${p}I32`,`=IF(F${n}=0,"損失なし",E${n}/F${n})`,
    `=COUNTIFS(${nets},">0")`,`=COUNTIFS(${nets},"<0")`,`=MAX(0,-MIN(${nets}))`,
    `=D${n}-MAX(0,LARGE(${nets},1))-MAX(0,LARGE(${nets},2))-MAX(0,LARGE(${nets},3))`,
    `=${p}L32`,`=COUNTIFS(${entries},0)`,`=D${n}-$D$7`]];
  const s=totals(method.rows);
  for (const [col,value] of [['B',s.pre],['C',s.post],['D',s.net],['E',s.profit],['F',s.loss],['H',s.wins],['I',s.losses],['J',s.maxloss],['K',s.ex3],['L',s.entries],['M',s.zero_entries],['N',s.net-totals(methods[0].rows).net]]) expected.push([comparison.name,`${col}${n}`,value]);
  if (s.loss) expected.push([comparison.name,`G${n}`,s.profit/s.loss]);
});
table(comparison,['手法ID','前半収支（円）','後半収支（円）','全夜収支（円）','総利益（円）','総損失（円）','利益損失比','黒字場数','赤字場数','最大赤字（円）','上位3黒字除外（円）','新規件数','無取引場数','C00差（円）'],6,last,'N','Comparison149');
comparison.getRange(`A1:A${last}`).format.columnWidth=12;
money(comparison,`B7:F${last}`);money(comparison,`J7:K${last}`);money(comparison,`N7:N${last}`);
comparison.getRange(`G7:G${last}`).setNumberFormat('0.00');
renders.unshift([comparison,'N',last]);

// ----------------------------------------
// 取得済み当夜は実現と含みを分離し、25夜合計へ加算しない。
const partial=[...report.partial].sort((a,b)=>a.id.localeCompare(b.id));
style(current,'F',partial.length+6,'2026/10/26ナイト　取得済み途中評価','21:13:52まで。既知3波を含む資料。終端一括返済をせず、完了25夜の合計から除外。');
current.getRange('A3').values=[['日経mini・片方向上限10枚・手数料0円・気配差込み。当夜の取得済み範囲だけを表示。']];
partial.forEach((row,i)=>{
  const n=i+7;
  current.getRange(`A${n}:F${n}`).values=[[row.id,row.net,row.unrealized,null,row.entries,row.max_per_side]];
  current.getRange(`D${n}`).formulas=[[`=B${n}+C${n}`]];
  equal(row.net+row.unrealized,row.equity,`${row.id}/途中評価`);
  expected.push([current.name,`D${n}`,row.equity]);
});
table(current,['手法ID','実現収支（円）','含み損益（円）','合計評価（円）','新規件数','最大片側保有枚数'],6,partial.length+6,'F','Partial149');
money(current,`B7:D${partial.length+6}`);
renders.push([current,'F',partial.length+6]);

// ----------------------------------------
// 市場記述は夜単位の平均率。未到達を除かない率と条件付き率を区別する。
const marketRows=[];
/**
 * 記述統計の要約行を追加する。
 * @param {string} label - 指標名。
 * @param {string} unit - 単位。
 * @param {object} item - 夜単位の対比較。
 * @param {string} note - 分母と対象。
 * @returns {void} 返り値なし。
 */
function marketRow(label,unit,item,note) {
  marketRows.push([label,unit,item.n,item.pre_mean,item.post_mean,null,...item.mean_difference_ci95,note]);
}
marketRow('正常気配中値の高低差','pt',market.paired.range_mid,'同じ315分');
marketRow('1分足の符号反転率','割合',market.paired.reversal_fraction,'0変動を除き、欠測を跨がない');
marketRow('分末気配差の中央値','pt',market.paired.spread_minute_median,'観測分を等しく重み付け');
marketRow('分末気配差の90%点','pt',market.paired.spread_minute_p90,'観測分を等しく重み付け');
marketRow('1時間当たりBBO価格変化','回/時',market.paired.bbo_changes_per_hour,'受信件数・約定件数ではない');
marketRow('固定100ptの先着率・両方向','割合',market.paired['全方向_全観測_100_favorable_first'],'未到達を分母に含む');
marketRow('相対幅の先着率・両方向','割合',relative.paired['全方向_favorable_first'],'共通9時点、未到達を分母に含む');
marketRow('相対幅の接触時先着率・両方向','割合',relative.paired['全方向_conditional_favorable_first'],'いずれかへ到達した事象だけ');
marketRow('相対幅の先着率・傾き方向','割合',relative.paired['傾き方向_favorable_first'],'前後双方に傾き事象がある夜');
marketRow('相対幅の平均閾値・傾き方向','pt',relative.paired['傾き方向_threshold'],'直前20分幅×0.5、下限20pt');
const marketLast=marketRows.length+6;
style(marketSheet,'I',marketLast+5,'米国開始前後の市場特性','前17:00〜22:15、後22:45〜04:00。夜を独立単位に集計。差の95%区間は夜単位の再標本化。');
marketSheet.getRange('A3').values=[['日経ラージの正常気配。既知25夜の記述分析であり、実売買の勝率・損益ではありません。']];
marketSheet.getRange('A5').values=[['前は値幅が小さめ。幅に合わせた無条件先着には明瞭な不利なし。傾き追随の適合は不確実。']];
marketSheet.getRange(`A7:I${marketLast}`).values=marketRows;
marketRows.forEach((row,i)=>{
  const n=i+7;
  marketSheet.getRange(`F${n}`).formulas=[[`=D${n}-E${n}`]];
  marketSheet.getRange(`D${n}:H${n}`).setNumberFormat(row[1]==='割合'?'0.0%':'#,##0.0');
  expected.push([marketSheet.name,`F${n}`,row[3]-row[4]]);
});
table(marketSheet,['指標','単位','比較夜数','米国前平均','米国後平均','前−後','差95%下限','差95%上限','対象と分母'],6,marketLast,'I','Market149');
marketSheet.getRange(`A1:A${marketLast+5}`).format.columnWidth=44;
marketSheet.getRange(`B1:C${marketLast+5}`).format.columnWidth=13;
marketSheet.getRange(`I1:I${marketLast+5}`).format.columnWidth=42;
marketSheet.getRange(`A${marketLast+2}`).values=[[`相対幅の観測アンカー：前${relative.counts['前'].anchors}・後${relative.counts['後'].anchors}。傾き該当：前${relative.counts['前'].slope_anchors}・後${relative.counts['後'].slope_anchors}。`]];
marketSheet.getRange(`A${marketLast+3}`).values=[['傾き該当夜：前23・後24、双方22。原行やアンカーを独立標本数として扱わない。']];
marketSheet.getRange(`A${marketLast+4}`).values=[['気配の価格時計に基づく観測。空白分は補完しない。途中10/26はこの比較から除外。']];
renders.push([marketSheet,'I',marketLast+4]);

// ----------------------------------------
// 入力の変更伝播を確認し、原値へ戻してから全表を検算・描画・保存する。
const probe=details.get('C00');
const old=probe.getRange('B7').values[0][0];
const firstNet=methods[0].rows[0].net;
const baseline=totals(methods[0].rows).net;
probe.getRange('B7').values=[[old+123]];
equal(probe.getRange('J7').values[0][0],firstNet+123,'入力変更と全夜収支');
equal(probe.getRange('K31').values[0][0],baseline+123,'入力変更と累計');
equal(comparison.getRange('D7').values[0][0],baseline+123,'入力変更と比較');
probe.getRange('B7').values=[[old]];
workbook.recalculate();
for (const [name,cell,value] of expected) equal(workbook.worksheets.getItem(name).getRange(cell).values[0][0],value,`${name}/${cell}`);
await fs.mkdir(output,{recursive:true});
await fs.mkdir(publication,{recursive:true});
const checks=path.join(work,'xlsx_checks');
await fs.mkdir(checks,{recursive:true});
const inspected=await workbook.inspect({kind:'table',range:'比較!A6:N10',include:'values,formulas',tableMaxRows:5,tableMaxCols:14,maxChars:6500});
await fs.writeFile(path.join(checks,'比較の検査.ndjson'),inspected.ndjson,'utf8');
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},maxChars:5000});
await fs.writeFile(path.join(checks,'式エラーの検査.ndjson'),errors.ndjson,'utf8');
let firstReport=null;
try { firstReport=JSON.parse(await fs.readFile(path.join(work,'first_report149.json'),'utf8')); } catch (error) { if (error.code!=='ENOENT') throw error; }
const renderReused=[];
for (const [sheet,col,row] of renders) {
  if (process.env.PREUS149_RENDER_ONLY && process.env.PREUS149_RENDER_ONLY!==sheet.name) continue;
  const picture=path.join(checks,`${sheet.name}.png`);
  let exists=true;
  try { await fs.access(picture); } catch { exists=false; }
  const identifier=sheet.name.startsWith('日経_')?sheet.name.slice(3):null;
  const previous=identifier && firstReport?.methods.find(m=>m.id===identifier);
  const unchanged=previous && JSON.stringify(previous)===JSON.stringify(methods.find(m=>m.id===identifier));
  if (exists && firstReport && (unchanged || sheet===marketSheet)) {
    renderReused.push(sheet.name);
    continue;
  }
  const image=await workbook.render({sheetName:sheet.name,range:`A1:${col}${row}`,scale:1,format:'png'});
  await fs.writeFile(picture,new Uint8Array(await image.arrayBuffer()));
}
const exported=await SpreadsheetFile.exportXlsx(workbook);
await exported.save(path.join(output,filename));
await fs.copyFile(path.join(output,filename),path.join(publication,filename));
await fs.writeFile(path.join(checks,'Excel計算との照合.json'),JSON.stringify({verified_cells:expected.length,sheets:methods.length+3,tables:methods.length+3,complete_sessions:25,partial_excluded:true,input_change_propagated:true,restored:true,unchanged_render_reused:renderReused,output:path.join(publication,filename)},null,2),'utf8');
console.log(JSON.stringify({output:path.join(publication,filename),sheets:methods.length+3,verified:expected.length}));
