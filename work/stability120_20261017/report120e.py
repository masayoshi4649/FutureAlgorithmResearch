"""指定された完成小会計だけを、可変政策数の全四十場レポートへ表示する。"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re
import statistics


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PRIVATE=HERE/'private_e'
HTML_NAME='上下対称の利益回転とカバー保持の全セッション損益.html'
SYMBOLS=('TOPIX','NK225')
EPS=1e-7
MONEY=('profit','loss','net','realized_net','cash','fees','max_drawdown','min_equity',
       'forced_loss','forced_profit','trail_net','long_net','short_net')
COUNTS=('closed_lots','wins','losses','unclosed','max_long','max_short','entries','canceled','clock_rejected')
FAMILIES=('KEEP','RESCUE','ROTATE')
E1_ENGINE_SHA='5fcecd4aa8061ce4be46291e90bfd7d912b11dbd0c1f7f7e3e535b34f346830a'
E1_CATALOG_SHA='509ffee62ecd2aa9ab1685b2c2066daaec17d477debeb140a6b7d9323d99dcf6'


def digest(payload: bytes) -> str:
    """
    機能: 保存内容と生成物を同bytesで識別する。
    引数: payload(bytes)は既に読み取った内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def encoded(value: object) -> bytes:
    """
    機能: 未測定nullを保持し、日本語と有限数値をJSONへ保存する。
    引数: value(object)は小会計又は生成証跡。
    返り値: bytesはUTF-8。非有限値は拒否する。
    """
    return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')


def esc(value: object) -> str:
    """
    機能: 結果のIDや日本語をHTMLの本文と属性へ安全に写す。
    引数: value(object)は文字列化する値。
    返り値: strは引用符も保護した文字列。
    """
    return html.escape(str(value),quote=True)


def fmt(value: float|None, signed: bool=False) -> str:
    """
    機能: 円表示を整え、未評価を零へ置き換えない。
    引数: value(float|None)は円額、signed(bool)は正負の明示。
    返り値: strは円額又は—。
    """
    if value is None:return '—'
    if abs(value)<=EPS:return '0'
    return format(value,('+' if signed else '')+',.0f')


def validate(data: dict) -> tuple[dict,dict]:
    """
    機能: 全政策・四十場・両商品の欠行、会計混同、上限超過を拒否する。
    引数: data(dict)は指定SHAの完成小会計又は完全合成。
    返り値: tuple[dict,dict]はID別仕様と商品場会計。原板やNPZは読まない。
    """
    scenes=data['sessions'];assert len(scenes)==len(set(scenes))==40
    specs={s['id']:dict(s) for s in data['specs']};assert len(specs)==len(data['specs'])>0
    for ident,s in specs.items():
        assert re.fullmatch('[A-Za-z0-9_]+',ident)
        assert s['mode'] in range(3) and all(isinstance(s[k],str) and s[k].strip() for k in ('name','description'))
        assert s['fraction']>0 and math.isfinite(s['fraction']) and s['trail']>0 and math.isfinite(s['trail'])
    rows={}
    for source in data['runs']:
        key=source['method'],source['session'],source['symbol']
        assert key[0] in specs and key[1] in scenes and key[2] in SYMBOLS and key not in rows,key
        row=dict(source)
        for k in MONEY:
            assert isinstance(row[k],(int,float)) and not isinstance(row[k],bool) and math.isfinite(row[k]),(key,k)
        for k in COUNTS:
            assert isinstance(row[k],(int,float)) and not isinstance(row[k],bool) and math.isfinite(row[k]) and int(row[k])==row[k] and row[k]>=0,(key,k)
            row[k]=int(row[k])
        assert min(row[k] for k in ('profit','loss','fees','max_drawdown','forced_loss','forced_profit'))>=-EPS
        assert row['wins']+row['losses']<=row['closed_lots']
        assert row['max_long']<=(10 if key[2]=='TOPIX' else 20) and row['max_short']<=(10 if key[2]=='TOPIX' else 20)
        assert math.isclose(row['profit']-row['loss'],row['realized_net'],rel_tol=0,abs_tol=1e-5)
        assert math.isclose(row['long_net']+row['short_net'],row['realized_net'],rel_tol=0,abs_tol=1e-5)
        if row['unclosed']==0:
            assert math.isclose(row['net'],row['realized_net'],rel_tol=0,abs_tol=1e-5)
            assert math.isclose(row['cash'],row['net'],rel_tol=0,abs_tol=1e-5)
        if row['entries']==0:assert row['closed_lots']==row['unclosed']==0 and abs(row['net'])<=EPS and abs(row['fees'])<=EPS
        assert row['step'] is None or isinstance(row['step'],(int,float)) and math.isfinite(row['step']) and row['step']>0
        rows[key]=row
    assert len(rows)==len(data['runs'])==len(specs)*len(scenes)*2
    assert data['source_SHA256'] and all(re.fullmatch('[0-9a-f]{64}',v) for v in data['source_SHA256'].values())
    return specs,rows


def validate_origin(data: dict) -> None:
    """
    機能: e未実行版を混ぜず、正式e1の名前と事前指定した経済SHAへ結ぶ。
    引数: data(dict)は根指定SHAで既に一読保全した完成内容又は合成境界。
    返り値: None。源ファイルを追加読取せず、元結果の由来と件数を確認する。
    """
    ids={f'{tag}_S{width}_T{trail}' for tag in FAMILIES for width in (1,2,3) for trail in (1,3)}
    assert len(data['specs'])==18 and {s['id'] for s in data['specs']}==ids
    assert data['financial_accounts']==len(data['runs'])==1440
    assert data['original_market_reads']==0 and data['reused_input_reads']==80
    source=data['source_SHA256']
    for name,sha in (('engine120e1.py',E1_ENGINE_SHA),('catalog120e1.py',E1_CATALOG_SHA)):
        selected=[value for path,value in source.items() if Path(path).name==name]
        assert selected==[sha],name+'の事前指定SHA不一致'
    assert len([path for path in source if Path(path).name=='run120e1.py'])==1
    assert not any(Path(path).name in ('engine120e.py','catalog120e.py','run120e.py') for path in source)


# ----------------------------------------


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 完結1枚玉のP/Lと場収支の安定性を別母集団で集計する。
    引数: rows(list[dict])は一商品・一政策の同じ四十場。
    返り値: dictは金額、場数、保有中リスク、末尾未返済等の表示値。
    """
    positive=[];negative=[];inactive=flat=unfinished=0
    for r in rows:
        if r['unclosed']:unfinished+=1
        elif not r['entries']:inactive+=1
        elif r['net']>EPS:positive.append(r['net'])
        elif r['net']<-EPS:negative.append(-r['net'])
        else:flat+=1
    nets=[r['net'] for r in rows];p=sum(r['profit'] for r in rows);loss=sum(r['loss'] for r in rows)
    meanabs=statistics.mean(abs(v) for v in nets);median=statistics.median(nets);meanblack=statistics.mean(positive) if positive else None
    result={k:sum(r[k] for r in rows) for k in ('profit','loss','net','realized_net','fees','closed_lots','wins','losses','entries','forced_loss','forced_profit','trail_net','long_net','short_net')}
    result.update(sessions=len(rows),black=len(positive),red=len(negative),inactive=inactive,flat=flat,unclosed_sessions=unfinished,
        terminal_unclosed_lots=sum(r['unclosed'] for r in rows),mean=statistics.mean(nets),median=median,worst=min(nets),
        top3_removed=None if unfinished else sum(nets)-sum(sorted(positive,reverse=True)[:3]),share=p/(p+loss) if p+loss>EPS else None,
        normalized_median=median/meanabs if meanabs>EPS else None,mean_black=meanblack,
        worst_to_mean_black=max(negative,default=0)/meanblack if meanblack is not None else None,
        min_session_equity=min(r['min_equity'] for r in rows),max_session_drawdown=max(r['max_drawdown'] for r in rows),
        max_long=max(r['max_long'] for r in rows),max_short=max(r['max_short'] for r in rows),all_positive=len(positive)==len(rows) and not unfinished)
    assert len(positive)+len(negative)+inactive+flat+unfinished==len(rows)
    return result


def rank_cases(specs: dict,cases: dict) -> list[dict]:
    """
    機能: 同じIDを両商品へ適用し、円額の銘柄跨ぎ比較なしで参考順位を固定する。
    引数: specs/cases(dict)は固定仕様と商品別集計。
    返り値: list[dict]は共通資格・弱い黒字数・正規化中央値・損失補填比・ID順。
    """
    ranked=[]
    for ident,s in specs.items():
        values=[cases[ident]['metrics'][symbol] for symbol in SYMBOLS]
        norm=[v['normalized_median'] for v in values];risks=[v['worst_to_mean_black'] for v in values]
        ranked.append(dict(id=ident,family=FAMILIES[s['mode']],qualified=all(v['net']>EPS and v['median']>EPS and v['top3_removed'] is not None and v['top3_removed']>EPS and not v['unclosed_sessions'] for v in values),
            min_black=min(v['black'] for v in values),min_normalized_median=min(norm) if all(v is not None for v in norm) else None,
            max_worst_to_mean_black=max(risks) if all(v is not None for v in risks) else None))
    ranked.sort(key=lambda r:(not r['qualified'],-r['min_black'],-r['min_normalized_median'] if r['min_normalized_median'] is not None else math.inf,r['max_worst_to_mean_black'] if r['max_worst_to_mean_black'] is not None else math.inf,r['id']))
    return ranked


def rules(spec: dict) -> dict:
    """
    機能: e三管理の組回収と玉別利益回転を、混同しない日本語へ整える。
    引数: spec(dict)はmode0/1/2の固定仕様。
    返り値: dict[str,str]は入口・途中・出口。市場値や実結果は読まない。
    """
    mode=spec['mode'];assert mode in range(3)
    entry='正常な保存Lastの動く安値から3/4/5…単位の反発で買い、高値から同幅の反落で売りを待ちます。初回は1枚だけ予約し、その実約定後は買い・売り両側の空き枠へ各1枚ずつ段階追加します。'
    entry+='気配差が広い間も正常Lastで極値を更新し、気配差は発注と最初の約定候補の資格だけに使います。'
    entry+='判断時と最初の次正常気配のspreadは1単位以内、買価格は判断ask＋観測1刻み以内、売価格は判断bid−観測1刻み以内とし、外れれば一回失効します。'
    if mode==2:
        hold='玉別の費用後清算純益peakが正になった時点から追尾します。含み損玉は利益玉の返済後も残り、返済した枠は現在Lastから再準備します。'
        exit_rule=f"玉別peak−当時純益が{spec['trail']:g}単位以上で、当時純益が正なら、その1枚を次正常原行で返済します。組全体の利益追尾は行いません。"
    else:
        hold='利益カバーを個別に先に外さず、全玉の費用後清算equity−組開始cashを組純損益として追います。途中の確定損失も同じ組に残します。'
        if mode==0:hold+='買い・売り両側が上限まで埋まった場合も、その同枚数の組を維持します。'
        else:hold+='両側の枚数が上限に達した時だけLastの極値を追い、3単位の反発では売り側、反落では買い側の最悪負け玉1枚を次気配で整理します。整理した実損も組純損益から消しません。'
        exit_rule=f"組純益peakが{spec['trail']+1:g}単位以上になった後、{spec['trail']:g}単位戻りかつ当時組純益が正なら全玉を次正常原行で返済します。"
    exit_rule+='全三管理とも方向別3単位停止はありません。次気配で損失になれば実損を計上し、場末も全返済します。組全返済の完了原行では新規せず、極値を現在Lastへ戻して翌原行から再準備します。'
    return dict(入口=entry,途中=hold,出口=exit_rule)


# ----------------------------------------


def metric_cells(m: dict) -> list[str]:
    """
    機能: 手数料・含み損を含めた比較表の一商品分を整える。
    引数: m(dict)は商品別の全場集計。
    返り値: list[str]は表示セル。未返済は勝ちにも零にも数えない。
    """
    return [fmt(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",fmt(m['mean'],True),fmt(m['median'],True),fmt(m['worst'],True),fmt(m['top3_removed'],True),fmt(m['fees']),fmt(m['min_session_equity'],True),str(m['unclosed_sessions'])]


def metric_table(items: list[tuple],caption: str) -> str:
    """
    機能: 複数政策の両商品を同じ安定性見出しで表示する。
    引数: items(list[tuple])はID・状態・商品・集計、caption(str)は表題。
    返り値: strは横スクロール可能なHTML比較表。
    """
    heads=('政策','比較資格','商品','時価込収支円','黒／赤／無','平均円','中央値円','最悪場円','上位3黒字除外円','手数料円','保有中最小資産円','未返済場')
    body=''.join('<tr data-method="'+esc(ident)+'" data-symbol="'+symbol+'"><th>'+esc(ident)+'</th><td>'+esc(status)+'</td><td>'+symbol+'</td>'+''.join('<td>'+esc(v)+'</td>' for v in metric_cells(m))+'</tr>' for ident,status,symbol,m in items)
    return '<div class="table-wrap"><table class="metrics"><caption>'+esc(caption)+'</caption><thead><tr>'+''.join('<th>'+h+'</th>' for h in heads)+'</tr></thead><tbody>'+body+'</tbody></table></div>'


def session_table(ident: str,scenes: list[str],rows: dict,cases: dict) -> str:
    """
    機能: 一政策の全四十場を同じ行に両商品並べ、省略せず表示する。
    引数: ident(str)、scenes(list[str])、rows/cases(dict)は会計対応。
    返り値: strは全場表と合計。利益と損失は完結1枚玉が母集団。
    """
    body=[]
    for scene in scenes:
        cells=[]
        for symbol in SYMBOLS:
            r=rows[ident,scene,symbol]
            cells.extend([fmt(r['profit']),fmt(r['loss']),fmt(r['realized_net'],True),fmt(r['net'],True),fmt(r['fees']),str(r['closed_lots']),str(r['unclosed']),f"{r['max_long']}/{r['max_short']}"])
        body.append('<tr data-session="'+esc(scene)+'"><th>'+esc(scene.replace('_Day',' デイ').replace('_Night',' ナイト'))+'</th>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr>')
    foot=[]
    for symbol in SYMBOLS:
        m=cases[ident]['metrics'][symbol]
        foot.extend([fmt(m['profit']),fmt(m['loss']),fmt(m['realized_net'],True),fmt(m['net'],True),fmt(m['fees']),str(m['closed_lots']),str(m['terminal_unclosed_lots']),f"{m['max_long']}/{m['max_short']}"])
    return '<div class="table-wrap"><table class="sessions" data-method="'+esc(ident)+'"><thead><tr><th rowspan="2">セッション</th><th colspan="8">TOPIXミニ</th><th colspan="8">日経マイクロ</th></tr><tr>'+2*'<th>利益円</th><th>損失円</th><th>確定円</th><th>時価込円</th><th>料円</th><th>返済枚数</th><th>未返済枚数</th><th>最大買／売</th>'+'</tr></thead><tbody>'+''.join(body)+'</tbody><tfoot><tr><th>全40場合計／最大保有</th>'+''.join('<td>'+v+'</td>' for v in foot)+'</tr></tfoot></table></div>'


def render(data: dict,result_sha: str,result_path: str,fixture: bool=False) -> tuple[str,dict,str]:
    """
    機能: 可変政策数の小会計を、短い結論・共通上位・全政策選択へ配置する。
    引数: data(dict)、result_sha/result_path(str)は内容と由来、fixture(bool)は完全合成。
    返り値: tuple[str,dict,str]はHTML・公開JSON・案内。金融又はNPZを再生しない。
    """
    specs,rows=validate(data);scenes=data['sessions'];cases={}
    for ident,spec in specs.items():
        cases[ident]=dict(spec=spec,policy_index=list(specs).index(ident),rules=rules(spec),metrics={symbol:aggregate([rows[ident,s,symbol] for s in scenes]) for symbol in SYMBOLS},rows=[rows[ident,s,symbol] for s in scenes for symbol in SYMBOLS])
    ranking=rank_cases(specs,cases);main=[];seen=set()
    for item in ranking:
        if item['family'] not in seen:main.append(item['id']);seen.add(item['family'])
        if len(main)==3:break
    eligible=sum(r['qualified'] for r in ranking);every=sum(all(cases[r['id']]['metrics'][s]['all_positive'] for s in SYMBOLS) for r in ranking)
    headline='既知40場で両商品が毎場黒字の条件があります。未知の将来での成功は未確認です。' if every else '毎セッションの安定黒字は未達です。'
    if fixture:headline='完全合成の表示検査です。実測や有望性を示す数値ではありません。'
    mainitems=[];allitems=[]
    for item in ranking:
        ident=item['id'];state='比較資格あり' if item['qualified'] else '未達・参考'
        allitems.extend((ident,state,s,cases[ident]['metrics'][s]) for s in SYMBOLS)
        if ident in main:mainitems.extend((ident,state,s,cases[ident]['metrics'][s]) for s in SYMBOLS)
    sections=[]
    for ident in main:
        sections.append('<section><h2>'+esc(specs[ident]['name'])+' <small>'+esc(ident)+'</small></h2>'+''.join('<p><b>'+key+'：</b>'+esc(value)+'</p>' for key,value in cases[ident]['rules'].items())+'<p><a href="#case-'+esc(ident)+'" data-open="'+esc(ident)+'">この条件の全40場を表示</a></p></section>')
    panels=[]
    for ident in [r['id'] for r in ranking]:
        spec=specs[ident];rr=cases[ident]['rules'];risk=[]
        for symbol in SYMBOLS:
            m=cases[ident]['metrics'][symbol]
            risk.append(symbol+'：場末返済の利益 '+fmt(m['forced_profit'])+'円／損失 '+fmt(m['forced_loss'])+'円、追尾返済の収支 '+fmt(m['trail_net'],True)+'円、最大場内下落 '+fmt(m['max_session_drawdown'])+'円。')
        hidden='' if ident==main[0] else ' hidden'
        panels.append('<section class="case-panel" id="case-'+esc(ident)+'" data-method="'+esc(ident)+'"'+hidden+'><h3>'+esc(ident)+' — '+esc(spec['name'])+'</h3><p>'+esc(rr['途中'])+' 幅は最初の当時中値の'+esc(f"{spec['fraction']*100:g}")+'%を観測刻みに四捨五入、最小1刻み。追尾 '+esc(f"{spec['trail']:g}")+'単位。</p>'+session_table(ident,scenes,rows,cases)+'<details><summary>この条件の保有中リスク・場末整理</summary><p>'+esc(' '.join(risk))+'</p><p>上の最大下落は各場の最大値であり、40場を連結した資産曲線の最大下落ではありません。</p></details></section>')
    options=''.join('<option value="'+esc(r['id'])+'">'+esc(r['id']+' — '+specs[r['id']]['name'])+'</option>' for r in ranking)
    css='body{margin:0;background:#0b1120;color:#e6edf8;font:16px/1.65 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:25px 18px}h1{font-size:27px}h2{font-size:21px}h3{font-size:18px}small,.muted{font-size:14px;color:#b0bfd2}strong{color:#ffda8c}a{color:#91c9ff}code{overflow-wrap:anywhere}.note{background:#18263d;border-left:4px solid #e2b85f;padding:14px 17px}.table-wrap{overflow-x:auto;max-width:100%;border:1px solid #34445a;border-radius:7px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{padding:8px 10px;border-bottom:1px solid #34445a;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}caption{text-align:left;padding:9px;font-weight:600}section{margin:22px 0}details{margin:13px 0}summary{cursor:pointer;color:#a7cfff}select{max-width:100%;background:#17263d;color:#e6edf8;padding:10px;border:1px solid #526580;border-radius:5px;font-size:15px}[hidden]{display:none!important}@media(max-width:600px){main{padding:15px 10px}h1{font-size:23px}body{font-size:15px}}'
    script='''
<script>
/**
 * 機能: 保存済み全政策の表を選択して表示する。
 * 引数: なし。画面内の選択欄とリンクだけを使用する。
 * 返り値: なし。外部取得や売買再計算は行わない。
 */
const selector=document.querySelector('#policy');
/**
 * 機能: 選択した政策の保存済み表だけを表示する。
 * 引数: なし。selector.value(string)は政策ID。
 * 返り値: なし。hidden状態だけを変更する。
 */
function showPolicy(){
  for(const panel of document.querySelectorAll('.case-panel'))panel.hidden=panel.dataset.method!==selector.value;
}
selector.addEventListener('change',showPolicy);
for(const link of document.querySelectorAll('[data-open]'))link.addEventListener('click',()=>{selector.value=link.dataset.open;showPolicy();});
showPolicy();
</script>'''
    doc='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+HTML_NAME[:-5]+'</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\nmainは1枚玉の完結損益と全玉清算時価を分離して表示します。\n#policyは全政策の説明・全四十場を選択し、.table-wrap内だけ横スクロールします。\n.case-panelには非表示の政策も全て保存し、原市場・金融・外部通信は利用しません。\n--><main><h1>上下対称の利益回転とカバー保持の比較</h1><p class="note"><strong>'+esc(headline)+'</strong> 共通の比較資格 '+str(eligible)+'/'+str(len(specs))+'、両商品40場すべて黒字 '+str(every)+'/'+str(len(specs))+'。</p><p>初回1枚からLast極値の反発・反落で両方向へ段階追加します。KEEPとRESCUEは勝ちカバーを組回収まで残す組全体追尾、ROTATEは上下対称の玉別利益回転です。組純損益はequity−組開始cashで、途中の確定損失を含みます。全eに方向別3単位停止はありません。単位の起点はBBO中値、約定・清算純益もBBOです。片方向上限はTOPIXミニ10枚・日経マイクロ20枚。全40場を知った後の開発比較で、未知検証の成功ではありません。</p>'+metric_table(mainitems,'両商品共通の上位・異なる系統から最大3条件')+'<p class="muted">利益・損失は完結1枚玉の費用後netの総正負。確定収支＝利益−損失、時価込収支は未返済玉の清算評価も含みます。費用は内数です。無取引・取引あり零収支・未返済を勝ちに数えません。利益玉の返済だけで残る損失を隠しません。</p>'+''.join(sections)+'<h2>全'+str(len(specs))+'政策の全40場</h2><label for="policy">表示する政策：</label> <select id="policy">'+options+'</select><p class="muted">最大買／売は各場の実同時保有最大枚数。合計行は40場中の最大値です。未返済枚数の合計は各場末残玉の合計で、持越しの新規政策を意味しません。</p>'+''.join(panels)+'<details><summary>全政策の参考順位と安定性を一覧</summary>'+metric_table(allitems,'全政策・両商品別')+'</details><details><summary>比較資格・範囲・観測と約定の限界</summary><p>比較資格は両商品の合計・中央値・上位3黒字除外が正、未返済0という内部の参考序列で、新たなユーザー必須条件ではありません。資格→弱い方の黒字数→弱い方の中央値/平均絶対収支→悪い方の最悪赤字/黒字場平均→IDで並べます。商品間の円額を直接比較せず、系統が異なるだけで分散効果を確認したとも言いません。</p><p>KEEP/RESCUEは組純益peakが追尾幅＋1単位以上で起動し、追尾幅戻りかつ組純益が正なら全返済予約します。ROTATEは玉別netpeak&gt;0で起動し、追尾幅戻りかつ当時net&gt;0の玉だけ返済予約します。次正常原行のBBOで損失になれば実損失です。新規締切は15:00／05:20、時刻返済判断は15:20／05:40。末尾に架空返済は作らず、残玉があれば成功扱いしません。</p><p>単位は最初の当時中値×割合を観測刻みに四捨五入し最小1観測刻み。観測ラージ刻みはTOPIX0.5pt／日経10円で、実ミニ0.25pt／マイクロ5円とは区別します。1枚別注文の片道料金は41円／11円で、41.8円／11円の円未満切捨て。ラージ気配による代理で、実小型板・待ち順位・真受信時刻は未取得です。価格時計と原行順の模型は実注文の約定保証ではありません。</p></details><p><a href="data.json">全政策の会計JSON</a>　<a href="README.md">案内</a></p><p class="muted">原結果：<code>'+esc(result_path)+'</code><br>SHA256：<code>'+esc(result_sha)+'</code></p></main><noscript><style>.case-panel[hidden]{display:block!important}</style><p>JavaScript無効のため全政策を表示しています。</p></noscript>'+script+'</body></html>'
    public=dict(sessions=scenes,source_path=result_path,source_SHA256=result_sha,economic_source_SHA256=data['source_SHA256'],common_ranking=ranking,main_ids=main,qualification_count=eligible,all40_positive_count=every,cases=cases,cache=data.get('cache',[]),artifact_columns={k:data.get(k) for k in ('order_columns','lot_columns','curve_columns')},
        baseline_reference=dict(path='work/stability120_20261017/recovery_b/measurement/段階トレーリングと利益玉部分返済の全四十場.json',sha256='c99743d739c9d24a08088f1b5ebdc78af8285b19e9704773965ea05f13890ce1',reference_only=True,financial_replay=0),entry_reference='初回1枚後の両方向Last極値段階追加。KEEP/RESCUE組追尾、ROTATE玉別利益回転。方向別3U停止なし。単位・約定・費用・清算はBBO。',account_basis='1枚lot UIDごとの完結net正負。netは全残玉の返済BBO時価と予定返済料を含む。',fixture=fixture,market_reads=0,financial_replay=0,API=0)
    readme='# 上下対称の利益回転とカバー保持\n\n最初に['+HTML_NAME+']('+HTML_NAME+')を開く。共通上位3系統を短く説明し、全政策の全40場を選択欄で切り替える。\n\n'+headline+'\n\nTOPIXミニ片方向10枚・日経マイクロ20枚が上限。利益と損失は完結1枚玉の費用後net正負、確定収支と残玉込清算時価は別。利確した玉だけで安定性を判断せず、場末整理・最小清算資産・未返済も併記する。手数料は利益損失の内数。全40場は既知の開発で未知検証ではない。\n\n[data.json](data.json)に全政策会計と元NPZの参照を保存する。生成器はNPZ・原市場を読まず金融を再生しない。原結果 `'+result_path+'`、SHA256 `'+result_sha+'`。生成時に一読して同bytes私有コピーを保全する。\n'
    doc=doc.replace('<p><a href="data.json">','<p class="muted">eは利益カバーを組回収前に外さないKEEP/RESCUEと、玉別利益回転ROTATEの18条件です。旧b/c/dの96条件とは管理が異なります。旧会計を新1440行へ合算せず、既存96条件の損失から本仕様の成否を推定しません。</p><p><a href="data.json">',1)
    readme+='\nKEEP/RESCUEは全玉清算equity−組開始cash（途中実損も含む）の組追尾、ROTATEは個別netpeak>0からの利益回転。全e方向別3U停止なし。Last値での約定を意味しない。旧b/c/dは別保存の参照のみで、新18政策の1440会計へ足さない。公開時の比較元へのリンクは根の案内にまとめる。\n'
    return doc,public,readme


def generate(data: dict,output: Path,result_sha: str,result_path: str,fixture: bool=False) -> dict:
    """
    機能: 一読済み完成内容から、正式・合成を区別して新規出力する。
    引数: data(dict)、output(Path)、result_sha/result_path(str)、fixture(bool)。
    返り値: dictは指紋と件数。既存正式成果を上書きしない。
    """
    doc,public,readme=render(data,result_sha,result_path,fixture);assert not output.exists();output.mkdir(parents=True)
    payloads={HTML_NAME:doc.encode('utf8'),'data.json':encoded(public),'README.md':readme.encode('utf8')}
    for name,payload in payloads.items():(output/name).write_bytes(payload)
    proof=dict(passed=True,fixture=fixture,result_path=result_path,result_sha256=result_sha,report_sha256=digest(Path(__file__).read_bytes()),artifacts={k:digest(v) for k,v in payloads.items()},policies=len(data['specs']),sessions=40,symbol_sessions=len(data['runs']),main_ids=public['main_ids'],market_reads=0,financial_replay=0,API=0)
    (output/'生成証跡.json').write_bytes(encoded(proof));return proof


def main() -> None:
    """
    機能: 根担当指定の完成SHAだけを一読し、同bytes保全後に正式表示を作る。
    引数: CLI --result(Path)、--expected-sha256(str)、任意--output/--received(Path)。
    返り値: None。実測値の再読・NPZ・市場・売買の実行はしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--result',type=Path,required=True);parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--output',type=Path,default=PRIVATE/'public');parser.add_argument('--received',type=Path,default=PRIVATE/'received');parser.add_argument('--fixture',action='store_true')
    args=parser.parse_args();expected=args.expected_sha256.lower();assert re.fullmatch('[0-9a-f]{64}',expected)
    assert not args.output.exists() and not args.received.exists()
    payload=args.result.read_bytes();assert digest(payload)==expected,'指定完成SHA不一致'
    args.received.mkdir(parents=True);copy=args.received/args.result.name;copy.write_bytes(payload)
    (args.received/'一読と同bytes保全.json').write_bytes(encoded(dict(source_path=str(args.result),source_SHA256=expected,own_copy=str(copy),source_reads=1,fixture=args.fixture,market_reads=0,financial_replay=0,API=0)))
    try:path=args.result.resolve().relative_to(ROOT).as_posix()
    except ValueError:path=str(args.result.resolve())
    data=json.loads(payload.decode('utf8'))
    if not args.fixture:validate_origin(data)
    print(json.dumps(generate(data,args.output,expected,path,args.fixture),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
