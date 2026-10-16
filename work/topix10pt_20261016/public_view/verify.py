"""公開追補版だけを一読し、正式三候補と全四十四切替・広狭画像を独立確認する。"""

import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import subprocess
import traceback
from urllib.parse import unquote,urlsplit

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測'
HTML_NAME='十ポイント方向予兆の候補と全セッション結果.html'
JSON_NAME='十ポイント予兆の公開採点.json'
RESULT_SHA='b4eefa5f31e36c645fe9c54d2ed715ec074b556524cb024364bd10386121dcf2'
OFFICIAL=['L04_MA活動板二市場_P65','P02','Q04']
SOURCES=('plan.py','input.py','artificial_input.py','features.py','artificial_features.py',
    'targets.py','artificial_targets.py','learner.py','artificial_learner.py','run.py')
PLAN=HERE/'追補版の独立表示検査計画.json'
PROOF=HERE/'正式三候補と事後追補及び四十四条件全場表の独立表示検査.json'
EARLY='''<script>
window.__QA_ERRORS=[];window.__QA_CONSOLE=[];
for(const level of ['error','warn']){const original=console[level].bind(console);console[level]=function(...args){window.__QA_CONSOLE.push(level+': '+args.map(String).join(' '));original(...args);};}
window.addEventListener('error',e=>window.__QA_ERRORS.push(String(e.message||e.error)));
window.addEventListener('unhandledrejection',e=>window.__QA_ERRORS.push(String(e.reason)));
</script>'''
PROBE=r'''<script>
/**
 * 機能: 全44切替と公開分子分母から、全37場・合計・静的表を独立検査する。
 * @param {object} expected - Python側の公開JSONから組み立てた独立表示期待。
 * @returns {object} 表セル・null率・暗色・例外と横スクロールの検査結果。
 */
function verifyIndependent(expected){
 const Q=JSON.parse(document.getElementById('report-data').textContent);
 const fail=(x,s)=>{if(!x)throw Error(s);};
 const pct=x=>x===null?'—':(x*100).toFixed(1)+'%';
 const cell=x=>x['順先']+'/'+x.n+'（'+pct(x.n?x['順先']/x.n:null)+'）';
 let views=0,sessionCells=0,totalCells=0,staticCells=0,denominators=0,rates=0,nulls=0;
 const fields=['順先','逆先','窓末未決','EOF未決','基準不可'];
 /**
  * 機能: 件数合計と保存率を各一セルの独立算術へ照合する。
  * @param {object} x - 保存五状態セル。
  * @returns {undefined} 不一致は例外とする。
  */
 function verifyCell(x){
  for(const f of fields)fail(Number.isSafeInteger(x[f])&&x[f]>=0,'非負整数 '+f);
  fail(x.n===fields.reduce((n,k)=>n+x[k],0),'五状態分母');
  fail(x.resolved===x['順先']+x['逆先'],'解決分母');denominators+=7;
  for(const [k,value] of Object.entries({'全候補順先率':x.n?x['順先']/x.n:null,'解決内順先率':x.resolved?x['順先']/x.resolved:null,'解決率':x.n?x.resolved/x.n:null})){
   fail(value===null?x[k]===null:Math.abs(x[k]-value)<1e-12,'保存率 '+k);rates++;if(value===null)nulls++;
  }
 }
 const selector=document.getElementById('method-select');
 fail(selector.options.length===44&&Q.specifications.length===44&&Q.rows.length===44*37,'44/37場schema');
 fail(JSON.stringify(Q.selection['正式候補'])===JSON.stringify(expected.official),'正式3不変更');
 fail(selector.value===expected.initial&&document.body.dataset.method===expected.initial,'初期ビュー');
 const summaries=new Map(Q.summaries.map(s=>[s.id,s]));
 for(const spec of Q.specifications){
  selector.value=spec.id;selector.dispatchEvent(new Event('change',{bubbles:true}));
  fail(document.body.dataset.method===spec.id,'実際に切替');
  const saved=Q.rows.filter(x=>x.id===spec.id),rows=document.querySelector('#session-body').rows;
  fail(saved.length===37&&rows.length===37,'全37場');
  const sums=Object.fromEntries(fields.map(k=>[k,0]));let buys=0,sells=0;
  saved.forEach((r,i)=>{
   const x=r.risks[1];verifyCell(x);for(const k of fields)sums[k]+=x[k];buys+=r['買い数'];sells+=r['売り数'];
   const group=Q.splits['学習'].includes(r.session)?'学習内':Q.splits['選択'].includes(r.session)?'選択':Q.splits['時系列別枠'].includes(r.session)?'既知の後6':'追加4';
   const want=[r.session,group,cell(x),String(x['逆先']),String(x['窓末未決']),String(x['EOF未決']),String(x['基準不可']),r['買い数']+'/'+r['売り数']];
   fail(rows[i].cells.length===8,'場8列');want.forEach((v,j)=>{fail(rows[i].cells[j].textContent===v,'場セル '+spec.id+'/'+i+'/'+j);sessionCells++;});
  });
  const summary=summaries.get(spec.id).periods['全37'],x=summary['主評価']['全体'];verifyCell(x);
  for(const k of fields)fail(x[k]===sums[k],'全場から合計 '+k);fail(summary['買い数']===buys&&summary['売り数']===sells,'買売枚数でなく予兆数');
  const total=document.querySelector('#session-footer').rows;fail(total.length===1,'footer1');
  const want=['全37場合計','参考合算',cell(x),String(x['逆先']),String(x['窓末未決']),String(x['EOF未決']),String(x['基準不可']),buys+'/'+sells];
  want.forEach((v,j)=>{fail(total[0].cells[j].textContent===v,'合計セル '+spec.id+'/'+j);totalCells++;});
  fail(document.getElementById('selected-description').textContent===spec.name+'：'+(spec.condition||spec.description),'条件説明 '+spec.id);views++;
 }
 // ----------------------------------------
 // Pythonが公開JSONから作った静的期待値を、全セルへ照合する。
 for(const table of expected.tables){
  const rows=document.querySelectorAll(table.selector+' tbody tr');fail(rows.length===table.rows.length,'静的行数 '+table.selector);
  table.rows.forEach((want,i)=>{fail(rows[i].cells.length===want.length,'静的列数 '+table.selector);want.forEach((v,j)=>{fail(rows[i].cells[j].textContent===v,'静的セル '+table.selector+'/'+i+'/'+j+': '+rows[i].cells[j].textContent+' != '+v);staticCells++;});});
 }
 for(const [sel,value] of Object.entries(expected.fragment_text||{})){
  const node=document.querySelector(sel);fail(node!==null,'追補DOM '+sel);fail(node.textContent.includes(value),'追補文言 '+sel);
 }
 for(const [sel,value] of Object.entries(expected.exact_text||{}))fail(document.querySelector(sel).textContent===value,'厳密追補セル '+sel);
 document.getElementById('reset').click();fail(selector.value===expected.initial,'reset初期ビュー');
 const details=[...document.querySelectorAll('details')],opened=details.map(x=>x.open);details.forEach(x=>x.open=true);
 let scrollable=0;for(const wrap of document.querySelectorAll('.scroll')){
  fail(['auto','scroll'].includes(getComputedStyle(wrap).overflowX),'表overflow');
  if(wrap.scrollWidth>wrap.clientWidth+1){wrap.scrollLeft=wrap.scrollWidth;fail(wrap.scrollLeft>0,'横スクロール可能');wrap.scrollLeft=0;scrollable++;}
 }
 if(innerWidth<600)fail(scrollable>0,'モバイル横スクロール表');
 fail(document.documentElement.scrollWidth<=innerWidth+2,'文書横溢れ');
 const style=getComputedStyle(document.documentElement);fail(style.colorScheme.includes('dark'),'dark色指定');
 const bg=getComputedStyle(document.body).backgroundColor.match(/\d+/g).slice(0,3).map(Number);fail(Math.max(...bg)<80,'暗色背景');
 fail(!/NaN|Infinity|undefined|__DATA__/.test(document.body.innerText),'非数未定義表示');
 fail(window.__QA_ERRORS.length===0&&window.__QA_CONSOLE.length===0,'JavaScript/console例外');
 details.forEach((x,i)=>x.open=opened[i]);
 if(expected.focus){const node=document.querySelector(expected.focus);fail(node!==null,'撮影focus');let p=node;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}node.scrollIntoView();}
 return {全合格:true,表示切替:views,全場表示セル:sessionCells,合計セル:totalCells,静的セル:staticCells,分母照合:denominators,
  率照合:rates,null率:nulls,横スクロール表:scrollable,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,
  JS例外:window.__QA_ERRORS.length,console例外:window.__QA_CONSOLE.length};
}
try{document.body.dataset.check=JSON.stringify(verifyIndependent(JSON.parse(document.getElementById('qa-expected').textContent)));}
catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error),stack:error.stack});}
</script>'''


def sha(body: bytes) -> str:
    """
    機能: 読取済みbytesを指紋化する。
    引数: body(bytes) は公開又はsource。
    返り値: str はSHA256。追加本文読取を行わない。
    """
    return hashlib.sha256(body).hexdigest()


def sources() -> dict:
    """
    機能: この検査器と変更不可source10の指紋を取得する。
    引数: なし。
    返り値: dict は検査sourceと元実装の指紋。report writerの可変源は含めない。
    """
    return dict(検査源=sha(Path(__file__).read_bytes()),不変実装10={name:sha((WORK/name).read_bytes()) for name in SOURCES})


def write(path: Path,value: dict) -> None:
    """
    機能: 私有証跡を有限JSONで新規保存する。
    引数: path(Path)、value(dict) は所有証跡。
    返り値: None。旧成功・False・公開物を上書きしない。
    """
    assert path.parent==HERE and not path.exists();path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def pct(value) -> str:
    """
    機能: 未定義分母と観測0%を区別する。
    引数: value(float|None) は保存又は独立算術の率。
    返り値: str は百分率又は横棒。
    """
    return '—' if value is None else f'{100*value:.1f}%'


def count_text(cell: dict) -> str:
    """
    機能: 全候補を分母にした先着表記を作る。
    引数: cell(dict) は五状態セル。
    返り値: str は順先/n（全候補率）。未決を分母から除かない。
    """
    return str(cell['順先'])+'/'+str(cell['n'])+'（'+pct(cell['順先']/cell['n'] if cell['n'] else None)+'）'


def number(value) -> str:
    """
    機能: 価格・signed診断値を表示期待へ変換する。
    引数: value(float|None) は保存値。
    返り値: str は有限値又は横棒。
    """
    return '—' if value is None else f'{0 if value==0 else value:,.4f}'.rstrip('0').rstrip('.')


def clock(value) -> str:
    """
    機能: 保存価格代理時計を日本時間へ表示する。
    引数: value(float|None) はepoch秒。
    返り値: str は日時又は横棒。
    """
    return '—' if value is None else datetime.fromtimestamp(value,timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')


def expectations(data: dict) -> dict:
    """
    機能: 公開JSONだけから正式三候補・全期間・全比較の静的期待を独立構築する。
    引数: data(dict) は公開採点。
    返り値: dict はDOM selectorsと全セル期待。
    """
    summaries={v['id']:v for v in data['summaries']};displayed={v['id']:v for v in data['displayed']};tables=[];primary=[];bias=[]
    for item in data['displayed']:
        identity=item['id'];hold=summaries[identity]['periods']['別枠10'];q=hold['主評価'];cell=q['全体']
        delta='—' if hold['対固定方向改善'] is None else f"{hold['対固定方向改善']*100:+.1f}pt"
        primary.append([identity+item['status'],count_text(cell),str(cell['逆先']),str(cell['窓末未決']+cell['EOF未決'])+f"窓末{cell['窓末未決']}／EOF{cell['EOF未決']}",
            count_text(q['常時買い']),count_text(q['常時売り']),delta,str(hold['活動場数'])+'/'+str(hold['場数'])])
        for label,cell in (('別枠デイ',summaries[identity]['periods']['別枠デイ']['主評価']['全体']),('別枠ナイト',summaries[identity]['periods']['別枠ナイト']['主評価']['全体']),('買い予兆',q['買い']),('売り予兆',q['売り'])):
            bias.append([identity,label,count_text(cell),str(cell['逆先']),str(cell['窓末未決']+cell['EOF未決'])])
        period_rows=[];titles={'学習':'学習内21場','選択':'選択6場','時系列別枠':'既知の後6場','追加別枠':'追加4場','別枠10':'別枠10場','別枠デイ':'別枠のデイ','別枠ナイト':'別枠のナイト','全37':'全37場（合算参考）'}
        for period in data['periods']:
            saved=summaries[identity]['periods'][period];q=saved['主評価'];cell=q['全体']
            period_rows.append([titles[period],count_text(cell),str(cell['逆先']),str(cell['窓末未決']+cell['EOF未決']),str(saved['活動場数'])+'/'+str(saved['場数']),count_text(q['常時買い']),count_text(q['常時売り'])])
        widths=[]
        for q in hold['risks']:
            cell=q['全体'];widths.append(['順10pt／逆'+number(q['逆行幅'])+'pt',count_text(cell),str(cell['逆先']),str(cell['窓末未決']+cell['EOF未決']),count_text(q['常時買い']),count_text(q['常時売り'])])
        examples=[]
        for example in item['例']:
            label=example['labels'][1];description='10pt先着' if label==1 else '逆5pt先着' if label==-1 else '窓末未決' if label==0 else 'EOF未決'
            if label==-1 and example['十pt到達秒'] is not None:description+='・後に10pt到達'
            examples.append([example['session'],'買い' if example['方向']==1 else '売り',clock(example['公開秒']),number(example['基準']),clock(example['十pt到達秒']),description,number(example['十pt到達前MAE'])])
        tables.extend([dict(selector='#method-'+identity+' .period-table',rows=period_rows),dict(selector='#method-'+identity+' .width-table',rows=widths)])
        if examples:tables.append(dict(selector='#method-'+identity+' .example-table',rows=examples))
    tables.extend([dict(selector='#primary-table',rows=primary),dict(selector='#bias-table',rows=bias)])
    comparisons=[]
    for spec in data['specifications']:
        identity=spec['id'];status=displayed[identity]['status'] if identity in displayed else '正式表示対象外'
        comparisons.append([identity+spec['family'],status]+[count_text(summaries[identity]['periods'][p]['主評価']['全体']) for p in ('学習','選択','時系列別枠','追加別枠','別枠10')])
    tables.append(dict(selector='#comparison-table',rows=comparisons))
    # ----------------------------------------
    # 事後追補も同じ公開summary/rowsから全幅・全期間・全場を照合する。
    posthoc_comparisons=[]
    for identity in ('S03','T01'):
        q=summaries[identity]['periods']['別枠10']['risks'][2]
        diff=q['全体']['全候補順先率']-max(q['常時買い']['全候補順先率'],q['常時売り']['全候補順先率'])
        posthoc_comparisons.append([identity,count_text(q['全体']),count_text(q['常時買い']),count_text(q['常時売り']),f'{100*diff:+.1f}pt'])
    widths=[]
    for q in summaries['S03']['periods']['別枠10']['risks']:
        c=q['全体'];widths.append(['逆'+number(q['逆行幅'])+'pt',count_text(c),str(c['逆先']),str(c['窓末未決']+c['EOF未決'])])
    periods=[]
    for name,saved in summaries['S03']['periods'].items():
        c=saved['risks'][2]['全体'];periods.append([name,count_text(c),str(c['逆先']),str(c['窓末未決']+c['EOF未決']),str(saved['活動場数'])+'/'+str(saved['場数'])])
    sessions=[[r['session']]+[count_text(c) for c in r['risks']] for r in data['rows'] if r['id']=='S03']
    tables.extend([dict(selector='#posthoc-comparison-table',rows=posthoc_comparisons),dict(selector='#posthoc-width-table',rows=widths),
        dict(selector='#posthoc-period-table',rows=periods),dict(selector='#posthoc-session-table',rows=sessions)])
    return dict(official=OFFICIAL,initial=data['view_initial_id'],tables=tables,
        fragment_text={'#posthoc-s03':'多重比較','#posthoc-full-caution':'全37場','#posthoc-steps':'EMA2・3・4・5・6・8'},exact_text={})


def validate_public(data: dict) -> dict:
    """
    機能: 公開44条件・37場の全幅と全八期間を整数分母から再照合する。
    引数: data(dict) は一読した公開JSON。
    返り値: dict は算術検査数とnull数。原市場採点は再測定しない。
    """
    fields=('順先','逆先','窓末未決','EOF未決','基準不可');count=0;nulls=0

    def cell(value: dict) -> None:
        """
        機能: 排他的件数と三種類の率を独立に照合する。
        引数: value(dict) は公開採点セル。
        返り値: None。
        """
        nonlocal count,nulls
        assert all(type(value[k]) is int and value[k]>=0 for k in fields)
        assert value['n']==sum(value[k] for k in fields) and value['resolved']==value['順先']+value['逆先'];count+=7
        expected={'全候補順先率':value['順先']/value['n'] if value['n'] else None,
            '解決内順先率':value['順先']/value['resolved'] if value['resolved'] else None,
            '解決率':value['resolved']/value['n'] if value['n'] else None}
        for key,want in expected.items():
            assert value[key] is None if want is None else value[key] is not None and math.isclose(value[key],want,rel_tol=1e-12,abs_tol=1e-13)
            count+=1;nulls+=want is None

    lookup={(r['id'],r['session']):r for r in data['rows']};assert len(lookup)==44*37
    for row in data['rows']:
        assert row['採用予兆数']==row['買い数']+row['売り数']
        for q in row['risks']:
            for group in ('全体','買い','売り','常時買い','常時売り'):cell(q if group=='全体' else q[group])
            assert q['n']==row['採用予兆数'] and q['買い']['n']==row['買い数'] and q['売り']['n']==row['売り数']
            assert q['常時買い']['n']==q['常時売り']['n']==q['n'];count+=5
    for summary in data['summaries']:
        for period,pool in data['periods'].items():
            rows=[lookup[summary['id'],s] for s in pool];saved=summary['periods'][period]
            assert saved['場数']==len(rows) and saved['予兆数']==sum(v['採用予兆数'] for v in rows)
            assert saved['活動場数']==sum(v['採用予兆数']>0 for v in rows) and saved['無信号場数']==sum(v['採用予兆数']==0 for v in rows)
            for ri in range(3):
                for group in ('全体','買い','売り','常時買い','常時売り'):
                    total=saved['risks'][ri][group];cell(total)
                    for field in (*fields,'n'):
                        assert total[field]==sum((v['risks'][ri] if group=='全体' else v['risks'][ri][group])[field] for v in rows);count+=1
    assert data['posthoc_S03']['source']['SHA256']=='9e5adfa1a76b4af0994b284f5582cb30779f0153ae244ff0177bf1dbe3bb45e1'
    metrics=data['posthoc_S03']['metrics']
    assert {k:metrics[k] for k in ('予兆数','十pt到達','十pt未到達','逆5先着後十pt到達','到達前MAE有限','到達前MAE不明')}==dict(
        予兆数=40,十pt到達=26,十pt未到達=14,逆5先着後十pt到達=7,到達前MAE有限=26,到達前MAE不明=0)
    assert metrics['signed_MAE分位']['0.5']==-2.5 and metrics['十pt前観測逆行幅分位']['0.5']==2.5
    assert metrics['到達代理秒分位']['0.5']==3946.
    return dict(独立算術検査数=count,未定義率数=nulls,追補40予兆のfinite分母=26)


def render(source: str,expected: dict,name: str,width: int,focus: str|None=None) -> dict:
    """
    機能: 公開同bytes私有複製を専用Chrome profileで検査しPNGを保存する。
    引数: source(str)、expected(dict)、name(str)、width(int)、focus(str|None)。
    返り値: dict はDOM検査と画像位置。通常ブラウザprofileを使用しない。
    """
    visual=HERE/'visual';visual.mkdir(exist_ok=True);target=visual/(name+'.html');picture=visual/(name+'.png');profile=visual/('profile_'+name)
    assert not any(p.exists() for p in (target,picture,profile)) and source.count('<head>')==source.count('</body>')==1
    expected=dict(expected,focus=focus);payload=json.dumps(expected,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    copied=source.replace('<head>','<head><base href="'+PUBLIC.as_uri()+'/">'+EARLY,1)
    copied=copied.replace('</body>','<script id="qa-expected" type="application/json">'+payload+'</script>'+PROBE+'</body>',1);target.write_text(copied,encoding='utf-8')
    command=['C:/Program Files/Google/Chrome/Application/chrome.exe','--headless=new','--disable-gpu','--no-first-run',
        '--disable-background-networking','--disable-component-update','--disable-sync','--run-all-compositor-stages-before-draw',
        '--disable-features=PaintHolding','--proxy-server=http://127.0.0.1:9',f'--window-size={width},2400','--virtual-time-budget=1800',
        '--user-data-dir='+str(profile),'--screenshot='+str(picture),'--dump-dom',target.as_uri()]
    proc=subprocess.run(command,capture_output=True,timeout=55,creationflags=subprocess.CREATE_NO_WINDOW)
    (visual/(name+'_stderr.txt')).write_bytes(proc.stderr)
    assert proc.returncode==0 and picture.exists(),'Chrome終了/PNG'
    dom=proc.stdout.decode('utf-8',errors='replace');found=re.search(r'<body\b[^>]*\bdata-check="([^"]*)"',dom)
    if found is None:
        (visual/(name+'_False_DOM.html')).write_bytes(proc.stdout);raise AssertionError('DOM検査完了なし')
    result=json.loads(html.unescape(found.group(1)))
    if not result['全合格']:(visual/(name+'_False_DOM.html')).write_bytes(proc.stdout)
    assert result['全合格'],result
    return dict(画面=name,画像=picture.relative_to(ROOT).as_posix(),画像_SHA256=sha(picture.read_bytes()),隔離profile=profile.relative_to(ROOT).as_posix(),**result)


def prepare() -> None:
    """
    機能: 公開完成前の読取目的と画面/数値契約を固定する。
    引数: なし。
    返り値: None。公開本文の存在確認や読取も行わない。
    """
    write(PLAN,dict(全合格=True,段階='writer完成SHA待ち',source_SHA256=sources(),元結果_SHA256=RESULT_SHA,
        対象=dict(公開HTML=HTML_NAME,公開JSON=JSON_NAME,追補MD='writer完成通知の相対pathをCLIで指定'),
        予定読取=dict(公開HTML=1,公開JSON=1,追補MD=1,市場結果=0,prepared=0,raw=0,event=0,金融=0,API=0),
        検査='正式三候補不変・全44切替×37場・footer・全八期間・全risk・分子分母・S03別章と事後留保・同bytesJSON・リンク・JS例外・暗色/横溢れ/スクロール。',
        画像='PC1450/モバイル520の先頭とS03追補。専用Chrome隔離profile。根が実画像を見るまで目視確認False。',
        不一致='Falseを残して根へ報告。公開やsource10を変更しない。'))
    print(json.dumps(dict(準備完了=True,計画_SHA256=sha(PLAN.read_bytes()),公開本文読取=0),ensure_ascii=False))


def execute(args) -> None:
    """
    機能: 根の追補完成SHA解除後だけ公開三本文を各一読し表示QAする。
    引数: args(Namespace) はHTML/JSON/MD期待SHA・MD名と追補DOM ID。
    返り値: None。原市場結果・preparedは読まない。
    """
    assert all(len(v)==64 for v in (args.html_sha,args.json_sha,args.md_sha)) and args.root_revision_complete
    assert not any(p.exists() for p in (HERE/'開始.json',HERE/'False.json',PROOF))
    plan=json.loads(PLAN.read_bytes());initial=sources();assert initial==plan['source_SHA256']
    tally=dict(公開HTML=0,公開JSON=0,追補MD=0,市場結果=0,prepared=0,raw=0,event=0,金融=0,API=0)
    write(HERE/'開始.json',dict(予定=plan['予定読取'],指定=dict(HTML=args.html_sha,JSON=args.json_sha,MD=args.md_sha),自動再実行=False))
    try:
        owned=HERE/'owned';owned.mkdir();bodies={}
        for kind,name,expected in (('公開HTML',HTML_NAME,args.html_sha),('公開JSON',JSON_NAME,args.json_sha),('追補MD',args.md_name,args.md_sha)):
            path=(PUBLIC/name).resolve();assert path.is_relative_to(PUBLIC)
            tally[kind]+=1;body=path.read_bytes();assert sha(body)==expected,(kind,sha(body));bodies[kind]=body
            (owned/('同bytes_'+path.name)).write_bytes(body)
        text=bodies['公開HTML'].decode('utf-8');data=json.loads(bodies['公開JSON']);md=bodies['追補MD'].decode('utf-8')
        assert data['全合格'] and data['result']['SHA256']==RESULT_SHA and data['selection']['正式候補']==OFFICIAL
        assert len(data['sessions'])==37 and len(data['specifications'])==44 and len(data['rows'])==44*37
        assert data['source_SHA256']=={(WORK/k).relative_to(ROOT).as_posix():v for k,v in initial['不変実装10'].items()}
        soup=BeautifulSoup(text,'html.parser');assert json.loads(soup.find('script',id='report-data').get_text())==data
        assert '事後' in md and 'S03' in md and '10' in md and '多重' in md
        arithmetic=validate_public(data)
        assert data['view_initial_id']=='S03' and len(soup.select('#posthoc-steps li'))==3
        assert soup.find('h1').find_next('section').get('id')=='posthoc-s03'
        links=[]
        for tag in soup.select('a[href],img[src]'):
            href=tag.get('href',tag.get('src'));parts=urlsplit(href);assert not parts.scheme and not parts.netloc
            target=(PUBLIC/unquote(parts.path)).resolve() if parts.path else PUBLIC/HTML_NAME
            assert target.is_relative_to(ROOT) and target.is_file(),str(target)
            if parts.fragment and target==PUBLIC/HTML_NAME:assert soup.find(id=unquote(parts.fragment)) is not None
            links.append(dict(href=href,path=target.relative_to(ROOT).as_posix()))
        expected=expectations(data);focus='#'+args.posthoc_id
        expected['fragment_text'][focus]='S03'
        expected['fragment_text']['body']='事後'
        assert soup.select_one(focus) is not None
        results=[]
        for name,width,target in (('PC1450',1450,None),('モバイル520',520,None),('PC1450_S03',1450,focus),('モバイル520_S03',520,focus)):
            results.append(render(text,expected,name,width,target));print(name+' 表示検査合格',flush=True)
        assert initial==sources() and tally==plan['予定読取']
        write(PROOF,dict(全合格=True,目視確認=False,元結果_SHA256=RESULT_SHA,公開_SHA256={k:sha(v) for k,v in bodies.items()},
            source_SHA256=initial,source始終一致=True,正式候補=OFFICIAL,初期ビュー='S03',画面=results,リンク=links,算術=arithmetic,読取計数=tally,
            留保='公開JSON/HTML/追補MDの表示検査。市場採点の再測定・有効性の追加標本・金融ではない。画像は根の実目視待ち。'))
        print(json.dumps(dict(全合格=True,証跡=str(PROOF),SHA256=sha(PROOF.read_bytes()),目視確認=False),ensure_ascii=False))
    except BaseException as exc:
        write(HERE/'False.json',dict(全合格=False,例外=repr(exc),trace=traceback.format_exc(),読取計数=tally,source_SHA256=initial));raise


def main() -> None:
    """
    機能: 公開待ちの準備と、完成SHA指定の単回QAを分ける。
    引数: CLI --prepare又は--run、root解除/各SHA/MD名/追補DOM ID。
    返り値: None。未解除では公開本文を読まない。
    """
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare',action='store_true');mode.add_argument('--run',action='store_true');parser.add_argument('--root-revision-complete',action='store_true')
    for name in ('html-sha','json-sha','md-sha','md-name','posthoc-id'):parser.add_argument('--'+name,default='')
    args=parser.parse_args();prepare() if args.prepare else execute(args)


if __name__=='__main__':main()
