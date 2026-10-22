"""独立監査済み会計だけを、短いダークテーマの全場レポートへ表示する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SCENE='2026-10-19_Day'
PUBLIC=ROOT/'アルゴリズム調査/00124_追加セッションと日経オプションの検証/追加セッションとオプションの検証.html'
E01_OLD='work/stability119_20261017/v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json'
E01_OLD_SHA='d0f1f86cb955a2da7016f0a33f6ff097eb64edb14068e8d0a0b4278aebca963b'
GAP_OLD='work/stability123_20261017/途中利確なしの十九間隔と全四十場.json'
GAP_OLD_SHA='91475e3757d4a9462f1ecc9405c43e76145967693b0802c56e73068dd0db416c'


def digest(payload: bytes) -> str:
    """
    機能: 保存内容の同一性を求める。
    引数: payload(bytes)は対象内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def receive(path: Path, expected: str) -> tuple[dict,dict]:
    """
    機能: 根が完成SHAを明示した小JSONだけを一読し、同bytesで所有保全する。
    引数: path(Path)、expected(str)は完成位置と指紋。
    返り値: tuple[dict,dict]は内容と参照。原板・保存価格配列・金融を使用しない。
    """
    path=path.resolve();raw=path.read_bytes();assert digest(raw)==expected,str(path)
    target=HERE/'received'/path.parent.name/path.name
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():assert target.read_bytes()==raw,str(target)
    else:target.write_bytes(raw)
    return json.loads(raw.decode('utf-8-sig')),dict(path=path.relative_to(ROOT).as_posix(),sha256=expected)


def contains(value: object, expected: str) -> bool:
    """
    機能: 独立証跡に対象完成SHAの明示拘束があるか確認する。
    引数: value(object)は証跡、expected(str)は完成SHA。
    返り値: boolは対象SHAが明示値として存在するか。
    """
    if isinstance(value,dict):return any(contains(v,expected) for v in value.values())
    if isinstance(value,list):return any(contains(v,expected) for v in value)
    return value==expected


def normalized(row: dict, method: str, option: bool=False) -> dict:
    """
    機能: 旧保存と新会計を同じ表示列へ射影する。
    引数: row(dict)は保存行、method(str)は表示ID、option(bool)は前場IV比較か。
    返り値: dictは利益・損失・収支・勝負枚数等。未知の残玉を零補完しない。
    """
    profit=float(row['profit']);loss=float(row['loss']);net=float(row['net'])
    assert abs(profit-loss-net)<1e-5
    wins=float(row['winning_lots'] if 'winning_lots' in row else row['wins'])
    losses=float(row['losing_lots'] if 'losing_lots' in row else row['losses'])
    quantity=float(row['entries']) if 'entries' in row else wins+losses
    assert min(profit,loss,wins,losses,quantity)>=0
    assert all(v==int(v) for v in (wins,losses,quantity))
    return dict(session=row['session'],symbol=row['symbol'],method=method,profit=profit,loss=loss,net=net,
        wins=int(wins),losses=int(losses),quantity=int(quantity),fees=float(row['fees']),
        active=(quantity>0),known=bool(row.get('option_known',False)) if option else None,
        changed=bool(row.get('option_effective_changed',False)) if option else False,
        option=option,origin=row.get('origin','旧保存会計の引用'),unclosed=row.get('unclosed'),
        verified_flat=row.get('verified_flat',row.get('unclosed')==0))


def statistics_for(rows: list[dict]) -> dict:
    """
    機能: 表示対象の全場を分母に、黒赤無・中央値・最大赤字・枚数を計算する。
    引数: rows(list[dict])は同一商品・手法・範囲の表示行。
    返り値: dictは会計の算術集計。無取引を黒字に数えない。
    """
    values=[r['net'] for r in rows];positive=sorted((n for n in values if n>0),reverse=True)
    return dict(sessions=len(rows),profit=sum(r['profit'] for r in rows),loss=sum(r['loss'] for r in rows),
        net=sum(values),black=sum(n>0 for n in values),red=sum(n<0 for n in values),
        inactive=sum(not r['active'] for r in rows),active_zero=sum(r['active'] and r['net']==0 for r in rows),
        median=statistics.median(values) if values else None,worst_loss=max((-n for n in values if n<0),default=0),
        quantity=sum(r['quantity'] for r in rows),wins=sum(r['wins'] for r in rows),losses=sum(r['losses'] for r in rows),
        changed=sum(r['changed'] for r in rows),fees=sum(r['fees'] for r in rows),top3_removed=sum(values)-sum(positive[:3]))


def prepare(grid: dict,e01: dict,old_grid: dict,old_e01: dict) -> dict:
    """
    機能: 旧40引用と追加1場を混ぜず、全41場の選択表示データを組み立てる。
    引数: grid/e01/old_grid/old_e01(dict)は監査された完成集計と固定比較元。
    返り値: dictはHTML埋込専用。新金融再生は0。
    """
    sessions=grid['sessions'];assert len(sessions)==41 and sessions[-1]==SCENE
    assert old_grid['sessions']==old_e01['sessions']==sessions[:-1]
    assert len(grid['specs'])==12 and len(grid['rows'])==984 and len(grid['latest_rows'])==19
    assert len(e01['rows'])==2 and {r['symbol'] for r in e01['rows']}=={'TOPIX','NK225'}
    assert all(r['session']==SCENE for r in e01['rows'])
    specs=[dict(id=s['id'],name=s['name']) for s in grid['specs']]
    options=[normalized(r,r['method'],True) for r in grid['rows']]
    e01_rows=[normalized(r,'E01') for r in old_e01['rows']+e01['rows']]
    gaps=[normalized(r,r['method']) for r in old_grid['runs']]
    gaps += [normalized(r,'I3_G3') for r in old_grid['baseline']['rows']]
    gaps += [normalized(r,r['method']) for r in grid['latest_rows']]
    all_rows=options+e01_rows
    for symbol in ('TOPIX','NK225'):
        for spec in [*specs,dict(id='E01')]:
            own=[r for r in all_rows if r['symbol']==symbol and r['method']==spec['id']]
            assert [r['session'] for r in own]==sessions
    gap_specs=[dict(id=s['id'],name=f"初回{s['initial']:g}pt／間隔{s['spacing']:g}pt") for s in old_grid['specs']]
    for spec in gap_specs:
        own=sorted((r for r in gaps if r['method']==spec['id']),key=lambda r:sessions.index(r['session']))
        assert len(own)==41 and [r['session'] for r in own]==sessions
    known={r['session'] for r in options if r['known']};assert len(known)==11
    assert len({(r['symbol'],r['method'],r['session']) for r in all_rows})==len(all_rows)
    latest=[r for r in e01_rows if r['session']==SCENE]
    latest += [next(r for r in gaps if r['session']==SCENE and r['method']==m) for m in ('I3_G3','I3_G10','I15_G15')]
    return dict(sessions=sessions,specs=specs,gap_specs=gap_specs,rows=all_rows,gap_rows=gaps,latest=latest,
        summaries={symbol:{s['id']:statistics_for([r for r in options if r['symbol']==symbol and r['method']==s['id']])
            for s in specs} for symbol in ('TOPIX','NK225')},known=len(known),unknown=len(sessions)-len(known),synthetic=False)


STYLE='''
:root{color-scheme:dark;--bg:#0c111a;--panel:#151e2b;--text:#e5ebf4;--muted:#a5b3c8;--line:#2c3a50;--green:#70dfb2;--red:#ff929b;--accent:#83b8ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,"Yu Gothic",sans-serif}main{max-width:1360px;margin:auto;padding:30px 22px 60px}h1{font-size:25px;margin:0 0 12px}h2{font-size:20px;margin:0}p{margin:8px 0;color:var(--muted)}section,details{margin:24px 0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px}.controls{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:14px 0}label{display:flex;align-items:center;gap:8px}select{font:inherit;padding:7px 10px;background:#0e1623;color:var(--text);border:1px solid #40526e;border-radius:6px;max-width:100%}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-variant-numeric:tabular-nums}th,td{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line)}th{font-size:13px;color:var(--muted);font-weight:600}th:first-child,td:first-child{text-align:left}tbody tr:hover{background:#1c2b40}tfoot{font-weight:700}.gain{color:var(--green)}.loss{color:var(--red)}.new{background:#18324d}.new td:first-child{color:#b0d4ff}.tag{font-size:11px;background:#2b4e77;color:#d2e6ff;padding:2px 5px;margin-left:7px;border-radius:4px}.note{font-size:13px;color:var(--muted)}summary{cursor:pointer;color:var(--accent);font-weight:600}.compact{margin:10px 0}.callout{color:var(--text)}.split td{font-size:13px}.nowrap{white-space:nowrap}a{color:var(--accent)}@media(max-width:700px){main{padding:18px 12px}h1{font-size:22px}section,details{padding:14px}th,td{padding:8px}.controls{gap:10px}label{flex-wrap:wrap}select{font-size:14px}}
'''


SCRIPT=r'''
const data=JSON.parse(document.getElementById('data').textContent);
const ids=['session-profit','session-loss','session-net','session-wins','session-losses'];
/**
 * 日本円又は枚数を桁区切りで表示する。
 * @param {number} value - 有限な対象値。
 * @param {boolean} signed - 正数へ符号を付けるか。
 * @returns {string} 表示文字列。
 */
function number(value,signed=false){if(value===0)value=0;return (signed&&value>0?'+':'')+value.toLocaleString('ja-JP',{maximumFractionDigits:0});}
/**
 * 文字をHTMLとして解釈させない。
 * @param {string} value - 対象文字列。
 * @returns {string} HTML用文字列。
 */
function escapeText(value){return String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
/**
 * 収支の表示色と符号を付ける。
 * @param {number} value - 純収支。
 * @returns {string} 金額セル内部のHTML。
 */
function money(value){return '<span class="'+(value>0?'gain':value<0?'loss':'')+'">'+number(value,true)+'</span>';}
/**
 * 場ごとの表示値から小集計を作る。
 * @param {Array<object>} rows - 同一条件の会計行。
 * @returns {object} 利益・損失・収支と黒赤無・枚数。
 */
function stats(rows){const values=rows.map(r=>r.net),sorted=[...values].sort((a,b)=>a-b);return {profit:rows.reduce((s,r)=>s+r.profit,0),loss:rows.reduce((s,r)=>s+r.loss,0),net:values.reduce((s,n)=>s+n,0),wins:rows.reduce((s,r)=>s+r.wins,0),losses:rows.reduce((s,r)=>s+r.losses,0),quantity:rows.reduce((s,r)=>s+r.quantity,0),black:values.filter(n=>n>0).length,red:values.filter(n=>n<0).length,inactive:rows.filter(r=>!r.active).length,median:sorted.length?(sorted[Math.floor((sorted.length-1)/2)]+sorted[Math.floor(sorted.length/2)])/2:0,worst:Math.max(0,...values.map(n=>-n))};}
/**
 * 手法名と商品名を表示用へ変換する。
 * @param {object} row - 会計行。
 * @returns {string} 簡単な名称。
 */
function title(row){if(row.method==='E01')return '少額E01';return data.gap_specs.find(s=>s.id===row.method)?.name||row.method;}
/**
 * 追加一場の固定比較五行を表示する。
 * @returns {undefined} 表を更新する。
 */
function renderLatest(){document.getElementById('latest-body').innerHTML=data.latest.map(r=>'<tr><td>'+escapeText(title(r))+'</td><td>'+escapeText(r.symbol==='TOPIX'?'TOPIXミニ':'日経マイクロ')+'</td><td class="gain">'+number(r.profit)+'</td><td class="loss">'+number(r.loss)+'</td><td>'+money(r.net)+'</td><td>'+number(r.wins)+'／'+number(r.losses)+'</td></tr>').join('');}
/**
 * 商品を選び、十二IV条件の全41場小集計を表示する。
 * @returns {undefined} 比較表を更新する。
 */
function renderSummary(){const symbol=document.getElementById('summary-symbol').value;document.getElementById('summary-body').innerHTML=data.specs.map(s=>{const r=data.summaries[symbol][s.id];return '<tr><td>'+escapeText(s.id+' '+s.name)+'</td><td>'+money(r.net)+'</td><td>'+r.black+'／'+r.red+'／'+r.inactive+'</td><td>'+money(r.median)+'</td><td class="loss">'+number(r.worst_loss)+'</td><td>'+number(r.quantity)+'</td><td>'+r.changed+'場</td></tr>';}).join('');}
/**
 * 全セッションを掲載し、追加一場と合計を明示する。
 * @param {Array<object>} rows - 同一条件の全41行。
 * @param {string} prefix - 対象表のID接頭語。
 * @returns {undefined} 表と合計を更新する。
 */
function renderRows(rows,prefix){const ordered=[...rows].sort((a,b)=>data.sessions.indexOf(a.session)-data.sessions.indexOf(b.session));document.getElementById(prefix+'-body').innerHTML=ordered.map(r=>'<tr class="'+(r.session===data.sessions.at(-1)?'new':'')+'"><td>'+escapeText(r.session.replace('_Day',' デイ').replace('_Night',' ナイト'))+(r.session===data.sessions.at(-1)?'<span class="tag">追加</span>':'')+'</td><td class="gain">'+number(r.profit)+'</td><td class="loss">'+number(r.loss)+'</td><td>'+money(r.net)+'</td><td>'+number(r.wins)+'</td><td>'+number(r.losses)+'</td><td>'+(r.option?(r.known?'既知':'不明'):'―')+'</td></tr>').join('');const total=stats(rows);document.getElementById(prefix+'-total').innerHTML='<td>全41場合計</td><td class="gain">'+number(total.profit)+'</td><td class="loss">'+number(total.loss)+'</td><td>'+money(total.net)+'</td><td>'+number(total.wins)+'</td><td>'+number(total.losses)+'</td><td>―</td>';}
/**
 * 商品・手法を選び、全41場と期間別内訳を表示する。
 * @returns {undefined} 全場表と区分表を更新する。
 */
function renderSessions(){const symbol=document.getElementById('session-symbol').value,method=document.getElementById('session-method').value,rows=data.rows.filter(r=>r.symbol===symbol&&r.method===method);renderRows(rows,'session');const groups=[['旧40場',rows.filter(r=>r.session!==data.sessions.at(-1))],['追加1場',rows.filter(r=>r.session===data.sessions.at(-1))]];if(method!=='E01'){groups.push(['前場IVが既知の11場',rows.filter(r=>r.known)],['前場IVが不明の30場',rows.filter(r=>!r.known)]);}document.getElementById('split-body').innerHTML=groups.map(([name,items])=>{const s=stats(items);return '<tr><td>'+name+'</td><td>'+number(s.profit)+'</td><td>'+number(s.loss)+'</td><td>'+money(s.net)+'</td><td>'+s.black+'／'+s.red+'／'+s.inactive+'</td></tr>';}).join('');const s=stats(rows);document.getElementById('session-caption').textContent=(method==='E01'?'少額E01':data.specs.find(v=>v.id===method).name)+' ｜ 黒字'+s.black+'・赤字'+s.red+'・無取引'+s.inactive+'場、累計'+number(s.quantity)+'枚';}
/**
 * 旧十九間隔の全41場を切り替える。
 * @returns {undefined} 比較表を更新する。
 */
function renderGaps(){const method=document.getElementById('gap-method').value;renderRows(data.gap_rows.filter(r=>r.method===method),'gap');}
/**
 * 選択肢と変更操作を接続して初期表示する。
 * @returns {undefined} 初期化を完了する。
 */
function initialize(){document.getElementById('session-method').innerHTML='<option value="E01">少額E01（固定設定）</option>'+data.specs.map(s=>'<option value="'+s.id+'">'+escapeText(s.id+' '+s.name)+'</option>').join('');document.getElementById('session-method').value='O00';document.getElementById('gap-method').innerHTML=data.gap_specs.map(s=>'<option value="'+s.id+'">'+escapeText(s.name)+'</option>').join('');document.getElementById('gap-method').value='I3_G3';document.getElementById('summary-symbol').addEventListener('change',renderSummary);document.getElementById('session-symbol').addEventListener('change',renderSessions);document.getElementById('session-method').addEventListener('change',renderSessions);document.getElementById('gap-method').addEventListener('change',renderGaps);renderLatest();renderSummary();renderSessions();renderGaps();document.body.dataset.ready='true';}
initialize();
'''


def table(prefix: str) -> str:
    """
    機能: 全41場の会計表部品を生成する。
    引数: prefix(str)は表のID接頭語。
    返り値: strは空表と合計行のHTML。
    """
    return f'''<div class="table-wrap"><table id="{prefix}-table"><thead><tr><th>セッション</th><th>利益（円）</th><th>損失（円）</th><th>収支（円）</th><th>勝ち枚数</th><th>負け枚数</th><th>前場IV</th></tr></thead><tbody id="{prefix}-body"></tbody><tfoot><tr id="{prefix}-total"></tr></tfoot></table></div>'''


def render(data: dict) -> str:
    """
    機能: 金融実行を伴わない自己完結HTMLを作る。
    引数: data(dict)は監査済み会計の表示射影、又は明示した人工値。
    返り値: strは通信不要のダークテーマHTML。
    """
    text=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    symbol='<option value="TOPIX">TOPIXミニ</option><option value="NK225">日経マイクロ</option>'
    synthetic='<p class="loss">人工値による表示確認。金融結果ではありません。</p>' if data['synthetic'] else ''
    conclusion=''
    latest_note=''
    if not data['synthetic']:
        top=data['summaries']['TOPIX'];nk=data['summaries']['NK225']
        if all(r['net']<0 for r in top.values()) and all(r['median']<0 for r in nk.values()):
            conclusion='<p class="callout"><strong>IV調整を加えても、両商品で安定黒字には至りませんでした。</strong>TOPIXは12条件すべて合計赤字。日経は合計黒字でも、典型的な1場の収支は赤字です。</p>'
        change={s:data['summaries'][s]['O01']['net']-data['summaries'][s]['O00']['net'] for s in ('TOPIX','NK225')}
        if all(data['summaries'][s]['O01']['changed']==1 for s in change):
            conclusion+=f'<p>緩いIV間隔調整O01と基準の差は、TOPIX{change["TOPIX"]:+,.0f}円／日経{change["NK225"]:+,.0f}円。設定差が生じたのは追加の1場だけです。</p>'
        if all(not r['active'] for r in data['latest'] if r['method']=='E01'):
            latest_note='<p class="note">少額E01は紙上候補TOPIX2件・日経1件が出来高方向票の条件を満たさず、両商品とも無取引でした。</p>'
        newest=[r for r in data['gap_rows'] if r['session']==data['sessions'][-1]]
        negative=sum(statistics_for([r for r in data['gap_rows'] if r['method']==s['id']])['net']<0 for s in data['gap_specs'])
        latest_note+=f'<p class="note">19間隔全体では、追加1場は{sum(r["net"]>0 for r in newest)}黒字・{sum(r["net"]<0 for r in newest)}赤字。全41場合計は{negative}条件が赤字です。</p>'
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>追加セッションとオプションの検証</title><style>{STYLE}</style></head><body><main>
<!--
[コンポーネント概要]
#latest-table は追加一場の既存固定手法を比較します。
#summary-symbol は十二IV条件の対象商品を切り替えます。
#session-symbol と #session-method は全41場と区分集計を切り替えます。
#gap-method は旧十九間隔の全41場を切り替えます。
.new は新しく追加した一場です。利益・損失は手数料後、枚数は返済した実数量です。
-->
<h1>追加セッションと日経オプションの検証</h1>{synthetic}
<p>追加：2026年10月19日 デイ。旧40場の保存結果と合わせて全41場。全て手数料後です。</p>{conclusion}
<section><h2>追加された1場の結果</h2><div class="table-wrap"><table id="latest-table"><thead><tr><th>手法</th><th>商品</th><th>利益（円）</th><th>損失（円）</th><th>収支（円）</th><th>勝ち／負け枚数</th></tr></thead><tbody id="latest-body"></tbody></table></div><p class="note">少額E01は従来の入口・利確・損失制限を固定。間隔3条件は途中返済せず、引け前6分以内の売買気配で一括精算した代理結果です。</p>{latest_note}</section>
<section><h2>オプション情報を加えると改善したか</h2><p>途中利確なしの両方向エントリーに、日経オプションの前場末尾IVを加え、新規幅や上限枚数を調整しました。IVは値動きの大きさの尺度で、上昇・下落の予測ではありません。</p><p>場中の受信時刻が保存されていないため、当場の情報を先物の過去へ結び付けず、前場の完了後に次場用へ固定しました。全41場中、利用可能11場・不明30場です。</p><div class="controls"><label>商品<select id="summary-symbol">{symbol}</select></label></div><div class="table-wrap"><table id="summary-table"><thead><tr><th>手法</th><th>全41場収支（円）</th><th>黒／赤／無</th><th>場収支中央値（円）</th><th>最大赤字（円）</th><th>累計枚数</th><th>IVで設定変更</th></tr></thead><tbody id="summary-body"></tbody></table></div><p class="note">「IVで設定変更」は基準O00と実際の新規幅・上限が異なった場数。不明時は基準設定へ戻します。O10・O11はIVを使わない固定幅の対照です。</p></section>
<section><h2>全セッションの損益</h2><div class="controls"><label>商品<select id="session-symbol">{symbol}</select></label><label>手法<select id="session-method"></select></label></div><p id="session-caption" class="callout"></p><details class="compact"><summary>旧40場・追加1場・IV既知／不明の内訳</summary><div class="table-wrap"><table class="split"><thead><tr><th>範囲</th><th>利益（円）</th><th>損失（円）</th><th>収支（円）</th><th>黒／赤／無</th></tr></thead><tbody id="split-body"></tbody></table></div></details>{table('session')}</section>
<details><summary>旧19間隔：TOPIXの全41セッション</summary><div class="controls"><label>初回幅／追加間隔<select id="gap-method"></select></label></div>{table('gap')}</details>
<p class="note">利益・損失は各完結建玉の手数料後損益を分けて合計しています。無取引は勝ちに含めません。旧40場は開発データ、追加1場は固定設定の確認です。少額E01の旧33場の返済完了は当時の監査を引用しています。</p>
</main><script id="data" type="application/json">{text}</script><script>{SCRIPT}</script></body></html>'''


def main() -> None:
    """
    機能: 完成SHAと独立監査SHAが全て与えられた後だけ正式HTMLを生成する。
    引数: なし。コマンド引数でgrid/e01各結果と独立監査の位置・SHAを受ける。
    返り値: None。再生・元板・API・台帳配列の読取は行わない。
    """
    parser=argparse.ArgumentParser()
    for name in ('grid','audit','e01','e01-audit'):
        parser.add_argument('--'+name,type=Path,required=True)
        parser.add_argument('--'+name+'-sha',required=True)
    args=parser.parse_args()
    ga,ga_ref=receive(args.audit,args.audit_sha)
    ea,ea_ref=receive(args.e01_audit,args.e01_audit_sha)
    assert ga.get('passed',ga.get('全合格',False)) and contains(ga,args.grid_sha)
    assert ea.get('passed',ea.get('全合格',False)) and contains(ea,args.e01_sha)
    grid,grid_ref=receive(args.grid,args.grid_sha);e01,e01_ref=receive(args.e01,args.e01_sha)
    assert grid['passed'] and e01['passed']
    old_grid,old_grid_ref=receive(ROOT/GAP_OLD,GAP_OLD_SHA)
    old_e01,old_e01_ref=receive(ROOT/E01_OLD,E01_OLD_SHA)
    data=prepare(grid,e01,old_grid,old_e01)
    content=render(data).encode('utf8');PUBLIC.parent.mkdir(parents=True,exist_ok=True)
    assert not PUBLIC.exists(),str(PUBLIC);PUBLIC.write_bytes(content)
    proof=dict(passed=True,report=dict(path=PUBLIC.relative_to(ROOT).as_posix(),sha256=digest(content)),
        sources=[grid_ref,e01_ref,ga_ref,ea_ref,old_grid_ref,old_e01_ref],
        renderer_sha256=digest(Path(__file__).read_bytes()),summary_rows=24,
        full_session_rows=26*41,gap_rows=19*41,original_market_reads=0,financial_replay=0,API=0,real_orders=0,
        e01_old_unknown_unclosed_preserved=sum(r['unclosed'] is None for r in data['rows'] if r['method']=='E01'),
        known_option_sessions=data['known'],unknown_option_sessions=data['unknown'])
    target=HERE/'正式表示の生成証跡.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
