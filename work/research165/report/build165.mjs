import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here=path.dirname(fileURLToPath(import.meta.url)),work=path.dirname(here),root=path.resolve(work,'../..');
const qa=path.join(here,'xlsx_checks'),source=path.join(work,'report_data165.json');
const sourceBytes=await fs.readFile(source),sourceHash=createHash('sha256').update(sourceBytes).digest('hex');
const report=JSON.parse(sourceBytes),methods=report.methods;
const marker=JSON.parse(await fs.readFile(path.join(here,'authoring開始165.json'),'utf8'));
const completion=JSON.parse(await fs.readFile(path.join(work,'再生全完了165.json'),'utf8'));
const audit=JSON.parse(await fs.readFile(path.join(work,'audit/audit165.json'),'utf8'));
if(!marker.marker_executed||marker.returncode!==0||marker.source_sha256!==sourceHash)throw new Error('確定資料での作者開始記録が必要です');
if(!completion.completed||completion.returncode!==0||completion.sessions!==27||completion.cases!==378||!audit.passed)throw new Error('全再生と独立会計の完了が必要です');
if(methods.length!==15||new Set(methods.map(m=>m.id)).size!==15)throw new Error('基準を含む固定15手法が必要です');
const expectedSessions=methods[0].rows.map(r=>r.session);
if(JSON.stringify(expectedSessions)!==JSON.stringify([...expectedSessions].sort()))throw new Error('セッションは時系列順である必要があります');
for(const m of methods)if(JSON.stringify(m.rows.map(r=>r.session))!==JSON.stringify(expectedSessions))throw new Error('手法間で対象セッションが異なります');
const filename='米国開始後の板判断と全セッション損益.xlsx';
const outputDir=path.join(root,'outputs/00165_research');
const publicDir=path.join(root,'アルゴリズム調査/00165_米国開始後の板追随と損失安定化');
const wb=Workbook.create(),comparison=wb.worksheets.add('比較');
comparison.tabColor='#264D70';
const sheets=new Map(methods.map(m=>[m.id,wb.worksheets.add(`日経_${m.id.replace('NK225_','')}`)]));
const checks=[],texts=[],tables=[],previews=[];
const money='#,##0;[Red](#,##0);"—"',counts='#,##0',decimal='0.0;[Red](0.0);"—"';

/**
 * 数値を会計側の期待値と照合する。
 * @param {number} actual - 再計算した値。
 * @param {number} expected - 期待値。
 * @param {string} label - 対象名。
 * @returns {void} 返り値なし。不一致は例外。
 */
function equal(actual,expected,label){
  if(!Number.isFinite(actual)||!Number.isFinite(expected)||Math.abs(actual-expected)>1e-5)throw new Error(`${label}: ${actual}/${expected}`);
}

/**
 * 数値と文字の期待値を独立検算用に保持する。
 * @param {object} sh - 対象シート。
 * @param {string} cell - セル番地。
 * @param {number|string} value - 期待値。
 * @returns {void} 返り値なし。
 */
function expect(sh,cell,value){(typeof value==='number'?checks:texts).push([sh.name,cell,value]);}

/**
 * 共通の表題、文字、寸法を設定する。
 * @param {object} sh - 対象シート。
 * @param {string} end - 終列。
 * @param {number} last - 終行。
 * @param {string} title - 表題。
 * @param {string} note - 補足。
 * @returns {void} 返り値なし。
 */
function style(sh,end,last,title,note){
  sh.showGridLines=false;
  sh.getRange(`A1:${end}${last}`).format={font:{name:'Yu Gothic',size:10,color:'#20384D'},rowHeight:25,columnWidth:17,verticalAlignment:'center'};
  sh.getRange('A1').format.rowHeight=10;
  sh.getRange('A2').values=[[title]];sh.getRange('A2').format.font={size:14,bold:true};
  sh.getRange('A3').values=[[note]];sh.getRange('A3:A4').format.font={size:10,color:'#536B80'};
  sh.getRange(`C6:${end}${last}`).setNumberFormat(money);
  sh.getRange(`C6:${end}${last}`).format.horizontalAlignment='right';
  sh.getRange(`A1:A${last}`).format.columnWidth=25;
  sh.getRange(`B1:B${last}`).format.columnWidth=13;
  sh.freezePanes.freezeRows(5);
  sh.freezePanes.freezeColumns(1);
}

/**
 * 正式Excelテーブルを追加する。
 * @param {object} sh - シート。
 * @param {string[]} headers - 列見出し。
 * @param {number} header - 見出し行。
 * @param {number} last - 最終データ行。
 * @param {string} name - 一意の表名。
 * @returns {void} 返り値なし。
 */
function table(sh,headers,header,last,name){
  const end=String.fromCharCode(64+headers.length),reference=`A${header}:${end}${last}`;
  sh.getRange(`A${header}:${end}${header}`).values=[headers];
  sh.tables.add(reference,true,name).showFilterButton=true;
  sh.getRange(`A${header}:${end}${header}`).format={fill:'#264D70',font:{bold:true,color:'#FFFFFF'},rowHeight:43,wrapText:true,horizontalAlignment:'center'};
  tables.push({sheet:sh.name,name,reference,rows:last-header});
  headers.forEach((v,i)=>expect(sh,`${String.fromCharCode(65+i)}${header}`,v));
}

/**
 * 負数だけを見やすくする。
 * @param {object} sh - シート。
 * @param {string} range - 範囲。
 * @returns {void} 返り値なし。
 */
function negative(sh,range){sh.getRange(range).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#FBE9EB',font:{color:'#9C2632'}}});}

/**
 * 候補と数量だけの比較対照を区別する。
 * @param {object} m - 手法データ。
 * @returns {string} 比較表での区分。
 */
function category(m){
  if(m.id==='NK225_U164_00')return '基準';
  if(['NK225_U165_01','NK225_U165_12'].includes(m.id))return '半量対照';
  return m.selected?'前20夜で固定':'比較候補';
}

// ----------------------------------------
// 一手法一シートで全27夜を掲載し、収支と累計を式で計算する。
for(const m of methods){
  const sh=sheets.get(m.id),rows=m.rows;
  if(rows.length!==27)throw new Error(`${m.id}: 27夜が必要です`);
  style(sh,'M',33,`${m.id}　米国開始後の損益`,m.description);
  sh.getRange('A4').values=[['片側上限micro100枚＝mini10枚相当／1pt・1micro＝10円／手数料0／ラージ気配で約定。']];
  sh.getRange('I1:K33').format.columnWidth=12;
  sh.getRange('L1:L33').format.columnWidth=17;sh.getRange('M1:M33').format.columnWidth=13;
  let cumulative=0;
  rows.forEach((r,i)=>{
    const n=i+6,closed=r.closed_micro,held=r.held_seconds,period=i<20?'前20夜':'後7夜';
    if(!Number.isFinite(closed)||!Number.isFinite(held))throw new Error('数量・保有時間が欠測です');
    cumulative+=r.net;equal(r.profit-r.loss,r.net,'利益−損失');equal(cumulative,r.cumulative,'累計');
    sh.getRange(`A${n}:M${n}`).values=[[r.session,period,r.profit,r.loss,null,null,r.minimum_equity,r.maximum_dd,r.new_orders,null,closed,null,held/60]];
    sh.getRange(`E${n}:F${n}`).formulas=[[`=C${n}-D${n}`,i?`=F${n-1}+E${n}`:`=E${n}`]];
    sh.getRange(`J${n}`).formulas=[[`=IF(I${n}=0,1,0)`]];
    sh.getRange(`L${n}`).formulas=[[`=IF(K${n}=0,"n.a.",E${n}/(K${n}*10))`]];
    const expected=[r.session,period,r.profit,r.loss,r.net,cumulative,r.minimum_equity,r.maximum_dd,r.new_orders,r.new_orders===0?1:0,closed,closed?r.net/(closed*10):'n.a.',held/60];
    expected.forEach((v,j)=>expect(sh,`${String.fromCharCode(65+j)}${n}`,v));
  });
  sh.getRange('A33').values=[['累計／場内最悪値']];
  sh.getRange('C33:M33').formulas=[['=SUM(C6:C32)','=SUM(D6:D32)','=C33-D33','=F32','=MIN(G6:G32)','=MAX(H6:H32)','=SUM(I6:I32)','=SUM(J6:J32)','=SUM(K6:K32)','=IF(K33=0,"n.a.",E33/(K33*10))','=SUM(M6:M32)']];
  sh.getRange('A33:M33').format.font={bold:true};
  const s=m.summary.全場;
  const expected=[s.profit,s.loss,s.net,s.net,s.minimum_equity,s.maximum_dd,s.new_orders,s.no_entries,s.closed_micro,s.net_per_closed_micro_point??'n.a.',rows.reduce((v,r)=>v+r.held_seconds/60,0)];
  expected.forEach((v,j)=>expect(sh,`${String.fromCharCode(67+j)}33`,v));
  sh.getRange('I6:K33').setNumberFormat(counts);sh.getRange('L6:M33').setNumberFormat(decimal);
  negative(sh,'E6:G32');negative(sh,'L6:L32');
  table(sh,['セッション','資料区分','利益（円）','損失（円）','収支（円）','累計（円）','場内最悪収支（円）','最大下落額（円）','新規回数','無取引','返済micro枚数','返済1枚平均（pt）','保有時間（分）'],5,32,`R165_${m.id}`);
  previews.push([sh.name,'A1:M33']);
}

// ----------------------------------------
// 同じ指標を全27夜・選択前20夜・確認後7夜で比較する。
style(comparison,'N',58,'米国開始後の板判断　15手法の比較','全27夜は既知資料です。前20夜で候補を固定し、後7夜で選び直していません。');
comparison.getRange('A4').values=[['全27夜。損失割合＝損失÷（利益＋損失）。損失は正額、場内最悪は確定＋含み。']];
comparison.getRange('F1:G58').format.columnWidth=11;
comparison.getRange('L1:L58').format.columnWidth=13;
comparison.getRange('M1:N58').format.columnWidth=19;
const periods=[['全場','全27夜',5,6,32],['前20夜','前20夜',24,6,25],['後7夜','後7夜',43,26,32]];
for(const [key,title,header,first,last]of periods){
  if(header!==5){comparison.getRange(`A${header-1}`).values=[[title]];comparison.getRange(`A${header-1}`).format.font={bold:true,size:12};}
  methods.forEach((m,i)=>{
    const n=header+i+1,sh=sheets.get(m.id),s=m.summary[key],prefix=`'${sh.name}'!`;
    if(s.sessions!==last-first+1)throw new Error(`${m.id}/${key}: 期間の場数が不一致です`);
    const range=c=>`${prefix}${c}${first}:${c}${last}`;
    comparison.getRange(`A${n}:N${n}`).values=[[m.id,category(m),null,null,null,null,null,null,null,null,null,null,null,null]];
    comparison.getRange(`C${n}:N${n}`).formulas=[[
      `=SUM(${range('C')})`,`=SUM(${range('D')})`,`=C${n}-D${n}`,
      `=COUNTIFS(${range('E')},"<0")`,`=SUM(${range('J')})`,
      `=IF(F${n}=0,0,-SUMIFS(${range('E')},${range('E')},"<0")/F${n})`,
      `=MAX(0,-MIN(${range('E')}))`,`=MIN(${range('G')})`,`=MAX(${range('H')})`,
      `=IF(C${n}+D${n}=0,"n.a.",D${n}/(C${n}+D${n}))`,
      `=IF(SUM(${range('K')})=0,"n.a.",E${n}/(SUM(${range('K')})*10))`,
      `=E${n}-LARGE(${range('E')},1)-LARGE(${range('E')},2)-LARGE(${range('E')},3)`
    ]];
    const expected=[m.id,category(m),s.profit,s.loss,s.net,s.negative_sessions,s.no_entries,s.mean_loss,s.maximum_loss,s.minimum_equity,s.maximum_dd,s.loss_share??'n.a.',s.net_per_closed_micro_point??'n.a.',s.excluding_top3];
    expected.forEach((v,j)=>expect(comparison,`${String.fromCharCode(65+j)}${n}`,v));
  });
  table(comparison,['手法ID','区分','利益（円）','損失（円）','収支（円）','赤字場数','無取引場数','平均赤字（円）','最大赤字（円）','場内最悪収支（円）','最大下落額（円）','損失割合','返済1枚平均（pt）','大勝ち3場除外（円）'],header,header+15,`R165_comparison_${header}`);
  comparison.getRange(`F${header+1}:G${header+15}`).setNumberFormat(counts);
  comparison.getRange(`L${header+1}:L${header+15}`).setNumberFormat('0.0%');
  comparison.getRange(`M${header+1}:M${header+15}`).setNumberFormat(decimal);
  negative(comparison,`E${header+1}:E${header+15}`);negative(comparison,`J${header+1}:J${header+15}`);negative(comparison,`M${header+1}:N${header+15}`);
  previews.unshift([comparison.name,`A${header===5?1:header-1}:N${header+15}`,`比較_${title}`]);
}

// ----------------------------------------
// 再計算と全セル照合、全シート描画を終えてから一つのxlsxを保存する。
wb.recalculate();
for(const [sn,address,value]of checks)equal(wb.worksheets.getItem(sn).getRange(address).values[0][0],value,`${sn}/${address}`);
for(const [sn,address,value]of texts)if(wb.worksheets.getItem(sn).getRange(address).values[0][0]!==value)throw new Error(`文字照合失敗 ${sn}/${address}`);
await fs.mkdir(qa,{recursive:true});
const inspection=await wb.inspect({kind:'table',range:'比較!A1:N20',include:'values,formulas',tableMaxRows:20,tableMaxCols:14});
await fs.writeFile(path.join(qa,'比較の検査.ndjson'),inspection.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100}});
await fs.writeFile(path.join(qa,'式エラーの検査.ndjson'),errors.ndjson);
if(!errors.ndjson.includes('matched 0 entries'))throw new Error('式エラー検索を確認してください');
const rendered=[];
for(const [sheetName,range,name]of previews){
  const prior=path.join(qa,`${name??sheetName}.png`);
  if(process.argv.includes('--reuse-method-renders')&&sheetName!=='比較'){
    await fs.access(prior);rendered.push({sheet:sheetName,path:prior,range});continue;
  }
  const image=await wb.render({sheetName,range,scale:1.25,format:'png'}),target=path.join(qa,`${name??sheetName}.png`);
  await fs.writeFile(target,new Uint8Array(await image.arrayBuffer()));rendered.push({sheet:sheetName,path:target,range});
}
await fs.mkdir(outputDir,{recursive:true});await fs.mkdir(publicDir,{recursive:true});
const output=await SpreadsheetFile.exportXlsx(wb),target=path.join(outputDir,filename);
await output.save(target);await fs.copyFile(target,path.join(publicDir,filename));
const exported=await fs.readFile(target),workbookHash=createHash('sha256').update(exported).digest('hex');
await fs.writeFile(path.join(qa,'作者期待値165.json'),JSON.stringify({source,source_sha256:sourceHash,workbook:path.join(publicDir,filename),workbook_sha256:workbookHash,checks,texts,tables,previews:rendered,sheets:[comparison.name,...[...sheets.values()].map(s=>s.name)]},null,2));
console.log(JSON.stringify({sheets:16,tables:tables.length,cells:checks.length,texts:texts.length,workbook_sha256:workbookHash}));
