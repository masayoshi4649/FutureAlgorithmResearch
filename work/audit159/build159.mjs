import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const source = path.join(root, 'work/research159/report159_all.json');
const sourceBytes = await fs.readFile(source);
const report = JSON.parse(sourceBytes.toString('utf8'));
const dayPath = path.join(root, 'work/score159/支持校正の保存分析159.json');
const nightPath = path.join(root, 'work/score159/夜間時間帯別の支持校正159.json');
const dayBytes = await fs.readFile(dayPath);
const nightBytes = await fs.readFile(nightPath);
const day = JSON.parse(dayBytes.toString('utf8'));
const night = JSON.parse(nightBytes.toString('utf8'));
const sourceHash = createHash('sha256').update(sourceBytes).digest('hex');
const qaDir = path.join(here, 'xlsx_checks');
const outputDir = path.join(root, 'outputs/00159_support');
const publicDir = path.join(root, 'アルゴリズム調査/00159_支持スコアの確度検証と夜間配分');
const filename = '支持スコアと昼夜の全セッション損益.xlsx';
const wb = Workbook.create();
const comparison = wb.worksheets.add('比較');
const support = wb.worksheets.add('支持の確度');
const sheets = new Map(report.methods.map(m => [m.id, wb.worksheets.add(`日経_${m.id}`)]));
const checks = [];
const ranges = [];
const metadata = [];
const money = '#,##0;[Red](#,##0);"—"';
if (sheets.size !== report.methods.length) throw new Error('手法ID重複');

/**
 * 数値を元会計と照合する。
 * @param {number} actual - 計算値。
 * @param {number} expected - 元の値。
 * @param {string} label - 対象名。
 * @returns {void} 不一致時は停止する。
 */
function equal(actual, expected, label) {
  if (!Number.isFinite(actual) || !Number.isFinite(expected) || Math.abs(actual - expected) > 1e-5) {
    throw new Error(`${label}: ${actual} / ${expected}`);
  }
}

/**
 * 最終照合セルを登録する。
 * @param {object} sheet - シート。
 * @param {string} address - セル番地。
 * @param {number} expected - 元会計値。
 * @returns {void} 返り値なし。
 */
function expect(sheet, address, expected) {
  if (!Number.isFinite(expected)) throw new Error(`根拠値なし: ${sheet.name}/${address}`);
  checks.push([sheet.name, address, expected]);
}

/**
 * 表題と共通書式を設定する。
 * @param {object} sheet - シート。
 * @param {string} end - 最終列。
 * @param {number} rows - 最終行。
 * @param {string} title - 表題。
 * @param {string} description - 手法と範囲。
 * @param {string} note - 短い注記。
 * @returns {void} 返り値なし。
 */
function style(sheet, end, rows, title, description, note) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${end}${rows}`).format = {
    font: {name: 'Yu Gothic', size: 10, color: '#21384D'},
    rowHeight: 25, columnWidth: 16, verticalAlignment: 'center',
  };
  sheet.getRange('A1').format.rowHeight = 10;
  sheet.getRange('A2').values = [[title]];
  sheet.getRange('A2').format.font = {size: 14, bold: true};
  sheet.getRange('A3').values = [[description]];
  sheet.getRange('A4').values = [[note]];
  sheet.getRange('A3:A4').format.font = {color: '#536B80', size: 10};
  sheet.getRange(`B6:${end}${rows}`).format.horizontalAlignment = 'right';
  sheet.getRange(`B6:${end}${rows}`).setNumberFormat(money);
  sheet.freezePanes.freezeRows(5);
}

/**
 * フィルター付き正式Excelテーブルを作る。
 * @param {object} sheet - シート。
 * @param {string[]} headers - 見出し。
 * @param {string} end - 最終列。
 * @param {number} last - 最終明細行。
 * @param {string} name - 一意名。
 * @returns {void} 返り値なし。
 */
function table(sheet, headers, end, last, name) {
  sheet.getRange(`A5:${end}5`).values = [headers];
  const t = sheet.tables.add(`A5:${end}${last}`, true, name);
  t.showFilterButton = true;
  sheet.getRange(`A5:${end}5`).format = {fill: '#264D70', font: {bold: true, color: '#FFFFFF'},
    rowHeight: 45, wrapText: true, horizontalAlignment: 'center'};
  metadata.push({sheet: sheet.name, table: name, reference: `A5:${end}${last}`, rows: last - 5});
}

/**
 * 赤字を色でも区別する。
 * @param {object} sheet - シート。
 * @param {string} range - 対象範囲。
 * @returns {void} 返り値なし。
 */
function lossColor(sheet, range) {
  sheet.getRange(range).conditionalFormats.add('cellIs', {operator: 'lessThan', formula: 0,
    format: {fill: '#FBE9EB', font: {color: '#9C2632'}}});
}

// ----------------------------------------
// 昼の旧26場と追加完了版は別シート。夜は旧25場と追加1場を明細上でも区別する。
for (const m of report.methods) {
  const sheet = sheets.get(m.id);
  const last = m.rows.length + 5;
  const total = last + 1;
  const isNight = m.kind === 'Night';
  const end = isNight ? 'L' : 'J';
  const note = m.id === 'J02型完了確認' ? '旧J02と返済対象の配賦が異なるため別集計。既知区間の全口座時価は一致。micro100枚上限・費用0。' :
    '片側micro100枚＝mini10枚相当・手数料0。途中最悪は確定＋全玉含み、最大下落は当場ピークからの落差。';
  style(sheet, end, total, `日経 ${m.id}　${isNight ? '夜間' : '日中'}損益`, m.description,note);
  sheet.getRange(`A1:A${total}`).format.columnWidth = 25;
  sheet.getRange(`B1:B${total}`).format.columnWidth = 15;
  sheet.getRange(`C1:C${total}`).format.columnWidth = 10;
  let cumulative = 0;
  m.rows.forEach((r, i) => {
    const n = i + 6;
    equal(r.profit-r.loss, r.net, `${m.id}/${r.session}`);
    const legacyComplete = m.kind === 'Day' && ['S01','J02'].includes(m.id) && m.rows.length === 26 && r.sample_group === '旧完了場';
    if (r.partial || (r.remaining_qty !== 0 && !legacyComplete)) throw new Error(`未完場を完了表へ混入: ${m.id}/${r.session}`);
    cumulative += r.net;
    const values = [r.session, r.sample_group || '旧完了場', r.direction, r.profit, r.loss,
      null, null, r.intraday_risk.min_equity, r.intraday_risk.max_drawdown, r.entries];
    if (isNight) values.push(r.phases?.前半?.net ?? 0, r.phases?.後半?.net ?? 0);
    sheet.getRange(`A${n}:${end}${n}`).values = [values];
    sheet.getRange(`F${n}:G${n}`).formulas = [[`=D${n}-E${n}`, i ? `=G${n-1}+F${n}` : `=F${n}`]];
    sheet.getRange(`B${n}:C${n}`).format.horizontalAlignment = 'left';
    for (const [col,value] of [['D',r.profit],['E',r.loss],['F',r.net],['G',cumulative],
      ['H',r.intraday_risk.min_equity],['I',r.intraday_risk.max_drawdown],['J',r.entries]]) expect(sheet,`${col}${n}`,value);
    if (isNight) {
      equal(values[10] + values[11], r.net, `${m.id}/${r.session}/前後合算`);
      expect(sheet, `K${n}`, values[10]); expect(sheet, `L${n}`, values[11]);
    }
  });
  const headers = ['セッション','資料区分','場の方向','利益（円）','損失（円）','収支（円）','累計（円）',
    '途中最悪収支（円）','最大下落額（円）','新規回数'];
  if (isNight) headers.push('米国前収支（円）','米国後収支（円）');
  table(sheet, headers, end, last, `R159_${m.id.replace(/[^A-Za-z0-9]/g,'_')}_${metadata.length}`);
  sheet.getRange(`A${total}`).values = [['累計／場内最悪値']];
  sheet.getRange(`D${total}:J${total}`).formulas = [[`=SUM(D6:D${last})`,`=SUM(E6:E${last})`,`=D${total}-E${total}`,
    `=G${last}`,`=MIN(H6:H${last})`,`=MAX(I6:I${last})`,`=SUM(J6:J${last})`]];
  if (isNight) sheet.getRange(`K${total}:L${total}`).formulas = [[`=SUM(K6:K${last})`,`=SUM(L6:L${last})`]];
  sheet.getRange(`A${total}:${end}${total}`).format = {font:{bold:true},borders:{top:{style:'thin',color:'#93AABD'}}};
  for (const [col,key] of [['D','profit'],['E','loss'],['F','net'],['G','net'],['H','min_equity'],['I','max_drawdown'],['J','entries']]) {
    expect(sheet,`${col}${total}`,m.summary[key]);
  }
  lossColor(sheet,`F6:H${last}`);
  if (isNight) lossColor(sheet,`K6:L${last}`);
  ranges.push([sheet.name,`A1:${end}${total}`]);
}

// ----------------------------------------
// 全条件を残す比較表。単純な収益順位にせず、場数・無取引・赤字深さを併記する。
const clast = report.methods.length + 5;
const directionHeader = clast + 4;
const directionEnd = directionHeader + report.methods.length;
style(comparison,'P',directionEnd,'支持スコアと昼夜の比較',
  '日中の旧26場と追加完了版は別集計。夜間は旧25場＋追加完了1場。利益・損失は完結した親ごとの合算。',
  '夜N00の旧25場は00151の保存経路を再現した比較元。追加完了版も途中を既に見た資料で、未見の予測成績ではない。');
comparison.getRange(`A1:A${clast}`).format.columnWidth = 24;
comparison.getRange(`B1:C${clast}`).format.columnWidth = 12;
comparison.getRange(`D1:P${clast}`).format.columnWidth = 16;
report.methods.forEach((m,i) => {
  const n = i+6;
  const last = m.rows.length+5, total = last+1;
  const sn = `'日経_${m.id}'`;
  comparison.getRange(`A${n}:C${n}`).values = [[m.id, m.kind==='Night'?'夜間':'日中',m.rows.length]];
  comparison.getRange(`D${n}:P${n}`).formulas = [[
    `=${sn}!D${total}`,`=${sn}!E${total}`,`=${sn}!F${total}`,
    `=COUNTIFS(${sn}!F6:F${last},"<0")`,
    `=IF(G${n}=0,0,-SUMIFS(${sn}!F6:F${last},${sn}!F6:F${last},"<0")/G${n})`,
    `=MAX(0,-MIN(${sn}!F6:F${last}))`,
    m.rows.length===1 ? `=F${n}-MAX(0,${sn}!F6)` : `=F${n}-${[1,2,3].filter(k=>k<=m.rows.length).map(k=>`MAX(0,LARGE(${sn}!F6:F${last},${k}))`).join('-')}`,
    `=${sn}!H${total}`,`=${sn}!I${total}`,`=${sn}!J${total}`,
    `=COUNTIFS(${sn}!J6:J${last},"=0")`,
    `=COUNTIFS(${sn}!B6:B${last},"旧完了場")`,
    `=COUNTIFS(${sn}!B6:B${last},"追加完了版")`,
  ]];
  const s=m.summary;
  for(const[col,value]of[['C',s.sessions],['D',s.profit],['E',s.loss],['F',s.net],['G',s.losses],['H',s.avgloss],
    ['I',s.maxloss],['J',s.ex3],['K',s.min_equity],['L',s.max_drawdown],['M',s.entries],['N',s.no_trade],
    ['O',m.rows.filter(r=>(r.sample_group||'旧完了場')==='旧完了場').length],['P',m.rows.filter(r=>r.sample_group==='追加完了版').length]]) expect(comparison,`${col}${n}`,value);
});
table(comparison,['手法','時間帯','場数','利益（円）','損失（円）','収支（円）','赤字場数','平均赤字（円）',
  '最大赤字（円）','上位3黒字除外（円）','途中最悪収支（円）','最大下落額（円）','新規回数','無取引場数','旧完了場数','追加完了場数'],
  'P',clast,'R159_comparison');
lossColor(comparison,`F6:F${clast}`); lossColor(comparison,`J6:K${clast}`);
comparison.getRange(`A${directionHeader-2}`).values=[['当場の上昇・下落別（始終のLast代理で事後分類。売買判断には未使用）']];
comparison.getRange(`A${directionHeader}:K${directionHeader}`).values=[['手法','時間帯','上昇場数','上昇収支（円）','上昇赤字場数',
  '下落場数','下落収支（円）','下落赤字場数','横ばい場数','横ばい収支（円）','横ばい赤字場数']];
report.methods.forEach((m,i)=>{
  const n=directionHeader+i+1,last=m.rows.length+5,sn=`'日経_${m.id}'`;
  comparison.getRange(`A${n}:B${n}`).values=[[m.id,m.kind==='Night'?'夜間':'日中']];
  comparison.getRange(`C${n}:K${n}`).formulas=[['上昇','下落','横ばい'].flatMap(d=>[
    `=COUNTIFS(${sn}!C6:C${last},"${d}")`,
    `=SUMIFS(${sn}!F6:F${last},${sn}!C6:C${last},"${d}")`,
    `=COUNTIFS(${sn}!C6:C${last},"${d}",${sn}!F6:F${last},"<0")`])];
  ['上昇','下落','横ばい'].forEach((d,di)=>{
    const rows=m.rows.filter(r=>r.direction===d),cols=[['C','D','E'],['F','G','H'],['I','J','K']][di];
    [rows.length,rows.reduce((s,r)=>s+r.net,0),rows.filter(r=>r.net<0).length].forEach((v,j)=>expect(comparison,`${cols[j]}${n}`,v));
  });
});
const dt=comparison.tables.add(`A${directionHeader}:K${directionEnd}`,true,'R159_direction');dt.showFilterButton=true;
comparison.getRange(`A${directionHeader}:K${directionHeader}`).format={fill:'#264D70',font:{bold:true,color:'#FFFFFF'},rowHeight:45,wrapText:true,horizontalAlignment:'center'};
metadata.push({sheet:comparison.name,table:'R159_direction',reference:`A${directionHeader}:K${directionEnd}`,rows:report.methods.length});
lossColor(comparison,`D${directionHeader+1}:D${directionEnd}`);lossColor(comparison,`G${directionHeader+1}:G${directionEnd}`);lossColor(comparison,`J${directionHeader+1}:J${directionEnd}`);
ranges.unshift([comparison.name,`A1:P${directionEnd}`]);

// ----------------------------------------
// 支持の強さを勝率と同一視しない。欠測を0の弱支持帯に混ぜない。
const scoreRows=[];
for(const[label,g]of[['日中・旧26場',day.groups.全体],['夜・米国前・旧25場',night.phases.前半.全体],['夜・米国後・旧25場',night.phases.後半.全体]]) {
  for(const b of g.bins)scoreRows.push([label,`${b.lower}～${b.upper}`,b]);
  scoreRows.push([label,'未知（計算不可）',g.unknown]);
}
const slast=scoreRows.length+5;
style(support,'M',slast,'支持スコアは勝率を示すか',
  '初回玉の全返済を1枚当たり値幅へ換算。支持は発注時点の値、未来損益は採点だけに使用。',
  '支持スコアは勝率ではない。95%区間は場単位再抽出の平均値幅区間。少数の帯と未知を別表示する。');
support.getRange(`A1:A${slast}`).format.columnWidth=25;
support.getRange(`B1:B${slast}`).format.columnWidth=22;
support.getRange(`C1:G${slast}`).format.columnWidth=11;
support.getRange(`H1:M${slast}`).format.columnWidth=16;
scoreRows.forEach(([label,band,b],i)=>{
  const n=i+6;
  const has=b.parents>0;
  const wins=has?b.wins:0, losses=has?b.losses:0, flat=has?b.flat:0;
  const ci=has?b.initial_pt.cluster_mean_95:[null,null];
  support.getRange(`A${n}:M${n}`).values=[[label,band,b.parents,b.sessions,wins,losses,null,
    has?b.initial_pt.mean:null,ci[0],ci[1],has?b.mfe.mean:null,has?b.mae.mean:null,flat]];
  support.getRange(`G${n}`).formulas=[[`=IF(C${n}=0,"",E${n}/C${n})`]];
  support.getRange(`B${n}`).format.horizontalAlignment='left';
  support.getRange(`G${n}`).setNumberFormat('0.0%');
  support.getRange(`H${n}:L${n}`).setNumberFormat('0.0;[Red](0.0);"—"');
  for(const[col,value]of[['C',b.parents],['D',b.sessions],['E',wins],['F',losses],['M',flat]])expect(support,`${col}${n}`,value);
  if(has)for(const[col,value]of[['G',b.win.mean],['H',b.initial_pt.mean],['I',ci[0]],['J',ci[1]],['K',b.mfe.mean],['L',b.mae.mean]])expect(support,`${col}${n}`,value);
});
table(support,['時間帯と資料','支持帯','親数','場数','勝ち親数','負け親数','初回玉勝率','平均損益（pt）',
  '平均の95%下限','平均の95%上限','平均最大順行（pt）','平均最大逆行（pt）','引分親数'],
  'M',slast,'R159_support');
ranges.splice(1,0,[support.name,`A1:M${slast}`]);

// ----------------------------------------
// 原会計照合・再計算・全シート描画後に保存する。初回作者マーカーは実行前に一度だけ外側で記録する。
wb.recalculate();
for(const[name,address,value]of checks)equal(wb.worksheets.getItem(name).getRange(address).values[0][0],value,`${name}/${address}`);
const first=report.methods[0], test=sheets.get(first.id), original=test.getRange('D6').values[0][0];
test.getRange('D6').values=[[original+100]];
wb.recalculate();
equal(comparison.getRange('F6').values[0][0],first.summary.net+100,'入力変更の収支連動');
test.getRange('D6').values=[[original]];
wb.recalculate();
for(const[name,address,value]of checks)equal(wb.worksheets.getItem(name).getRange(address).values[0][0],value,`復元/${name}/${address}`);
await fs.mkdir(qaDir,{recursive:true});
const inspection=await wb.inspect({kind:'table',range:`比較!A1:P${clast}`,include:'values,formulas',tableMaxRows:clast,tableMaxCols:16});
await fs.writeFile(path.join(qaDir,'比較の検査.ndjson'),inspection.ndjson,'utf8');
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'式エラー検査'});
await fs.writeFile(path.join(qaDir,'式エラーの検査.ndjson'),errors.ndjson,'utf8');
const previews=[];
for(const[name,range]of ranges){
  const image=await wb.render({sheetName:name,range,scale:1.4,format:'png'});
  const target=path.join(qaDir,`${name}.png`);
  await fs.writeFile(target,new Uint8Array(await image.arrayBuffer()));
  previews.push(target);
}
await fs.mkdir(outputDir,{recursive:true}); await fs.mkdir(publicDir,{recursive:true});
const book=await SpreadsheetFile.exportXlsx(wb);
const target=path.join(outputDir,filename);
await book.save(target); await fs.copyFile(target,path.join(publicDir,filename));
const bookHash=createHash('sha256').update(await fs.readFile(target)).digest('hex');
if(createHash('sha256').update(await fs.readFile(source)).digest('hex')!==sourceHash)throw new Error('集計根拠が変更された');
await fs.writeFile(path.join(qaDir,'Excel照合159.json'),JSON.stringify({passed:true,checks:checks.length,check_cells:checks,
  input_mutation_recalculation:true,source_unchanged:true,book_sha256:bookHash,report_sha256:sourceHash,
  score_sources:[{path:dayPath,sha256:createHash('sha256').update(dayBytes).digest('hex')},{path:nightPath,sha256:createHash('sha256').update(nightBytes).digest('hex')}],
  previews,tables:metadata,sheets:report.methods.length+2,native_excel_recalculation:false},null,2),'utf8');
console.log(JSON.stringify({passed:true,sheets:report.methods.length+2,checks:checks.length,book_sha256:bookHash,output:path.join(publicDir,filename)}));
