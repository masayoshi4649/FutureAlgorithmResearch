"""小枚数固定・全枚数固定・順行増加の三対照を、同じ入口で全四十場へ表示する。"""

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
BASE=HERE.parent
ROOT=BASE.parents[1]
PRIVATE=BASE/'privatev3'
DEFAULT_OUTPUT=PRIVATE/'public'
HTML_NAME='小枚数と順行増加の比較と全セッション損益.html'
SYMBOLS=('TOPIX','NK225')
BASELINES=()
MONEY=('net','realized','profit','loss','fees','max_drawdown')
COUNTS=('parents','wins','losses','closed_quantity','unclosed','canceled','fills','halted',
        'protected_fallbacks','protected_wait_rows','rejected_entries')
OPTIONAL=('canceled','fills','halted','protected_fallbacks','protected_wait_rows','rejected_entries')
SIZE_MODES=(0,1,2)
EXTRA_COUNTS=('max_quantity','initial_quantity_min','initial_quantity_max','add_fills')
EPS=1e-7


def sha(raw: bytes) -> str:
    """
    機能: 一読したbytes又は生成物の指紋を得る。
    引数: raw(bytes)は保存内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


def encoded(value: object) -> bytes:
    """
    機能: 日本語の有限値だけを保存可能なJSON bytesへ変換する。
    引数: value(object)は小会計又は表示証跡。
    返り値: bytesはUTF-8。Infinityを順位の保存値へ混ぜない。
    """
    return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')


def esc(value: object) -> str:
    """
    機能: ID・説明をHTMLへエスケープする。
    引数: value(object)は本文又は属性値。
    返り値: strは引用符も保護した文字列。
    """
    return html.escape(str(value),quote=True)


def fmt(value: float|None,signed: bool=False,decimals: int=0) -> str:
    """
    機能: 未評価をゼロへ置換せず、円又は比率を表示する。
    引数: value(float|None)、signed(bool)、decimals(int)は表示条件。
    返り値: strは千位区切りの値又は—。
    """
    if value is None:return '—'
    if abs(value)<=EPS:return '0'
    return format(value,('+' if signed else '')+',.'+str(decimals)+'f')


def is_inactive(row: dict) -> bool:
    """
    機能: 不明な約定回数をゼロ補完せず、無取引を会計上区別する。
    引数: row(dict)は一商品・一場会計。
    返り値: bool。未清算があれば無取引ではない。
    """
    if row['fills'] is not None:return row['fills']==0
    return row['parents']==row['closed_quantity']==row['unclosed']==0 and abs(row['fees'])<=EPS and abs(row['net'])<=EPS


def validate(data: dict) -> tuple[dict,dict]:
    """
    機能: 三十六条件・四十場・二商品の掲載元を確認し、欠場を拒否する。
    引数: data(dict)は指定完成SHAの一読結果又は合成fixture。
    返り値: tuple[dict,dict]は仕様表と商品場会計。原板や実注文は再検査しない。
    """
    scenes=data['sessions'];assert len(scenes)==len(set(scenes))==40
    specs={v['id']:dict(v) for v in data['specs']}
    assert len(specs)==len(data['specs'])==36
    for ident,spec in specs.items():
        for key in ('family','name','description'):assert isinstance(spec[key],str) and spec[key].strip(),(ident,key)
        assert len(ident)>0
        assert spec['entry_id']==spec['family'] and spec['allocation_mode'] in SIZE_MODES and spec['trail_multiple'] in (.5,1)
    groupkeys={(s['entry_id'],s['allocation_mode'],s['trail_multiple']) for s in specs.values()}
    assert len(groupkeys)==36 and len({s['entry_id'] for s in specs.values()})==6,'六入口×三配分×二追尾幅を一意に比較します。'
    assert len(data['runs'])==36*40*2
    rows={}
    for source in data['runs']:
        key=source['method'],source['session'],source['symbol']
        assert key[0] in specs and key[1] in scenes and key[2] in SYMBOLS and key not in rows
        row=dict(method=key[0],session=key[1],symbol=key[2])
        for name in MONEY:
            value=source[name];assert isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value),(key,name)
            row[name]=float(value)
        for name in COUNTS:
            value=source.get(name)
            if name in OPTIONAL and value is None:row[name]=None;continue
            assert isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and int(value)==value and value>=0,(key,name)
            row[name]=int(value)
        for name in EXTRA_COUNTS:
            value=source.get(name)
            assert value is None or (isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and int(value)==value and value>=0),(key,name)
            row[name]=None if value is None else int(value)
        if row['max_quantity'] is not None:assert row['max_quantity']<=(10 if key[2]=='TOPIX' else 20)
        assert (row['initial_quantity_min'] is None)==(row['initial_quantity_max'] is None)
        if row['initial_quantity_min'] is not None:assert 0<row['initial_quantity_min']<=row['initial_quantity_max']<=row['max_quantity']
        assert min(row[k] for k in ('profit','loss','fees','max_drawdown'))>=-EPS
        assert row['wins']+row['losses']<=row['parents']
        if not row['unclosed']:
            assert abs(row['net']-row['realized'])<=1e-5 and abs(row['profit']-row['loss']-row['net'])<=1e-5,(key,'完結親会計')
        if row['fills']==0:assert row['parents']==row['unclosed']==0 and abs(row['net'])<=EPS
        rows[key]=row
    assert isinstance(data['source_SHA256'],dict) and data['source_SHA256']
    return specs,rows


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 同じ商品の場netと完結親P/Lを別の母集団で集計する。
    引数: rows(list[dict])は四十場又は明示した期間。
    返り値: dictは無取引・未清算別の場数、正規化用の平均絶対net、損失比等。
    """
    nets=[r['net'] for r in rows];black=[];red=[];inactive=flat=unclosed=0
    for row in rows:
        if row['unclosed']:unclosed+=1
        elif is_inactive(row):inactive+=1
        elif row['net']>EPS:black.append(row['net'])
        elif row['net']<-EPS:red.append(-row['net'])
        else:flat+=1
    assert len(black)+len(red)+inactive+flat+unclosed==len(rows)
    p=sum(r['profit'] for r in rows);l=sum(r['loss'] for r in rows);net=sum(nets)
    mean_abs=statistics.mean(abs(v) for v in nets);median=statistics.median(nets)
    avgblack=statistics.mean(black) if black else None
    worst_red=max(red,default=0.)
    return dict(sessions=len(rows),profit=p,loss=l,net=net,fees=sum(r['fees'] for r in rows),
        parents=sum(r['parents'] for r in rows),closed_quantity=sum(r['closed_quantity'] for r in rows),
        black=len(black),red=len(red),inactive=inactive,flat=flat,unclosed_sessions=unclosed,
        mean=statistics.mean(nets),median=median,worst=min(nets),worst_red=worst_red,
        top3_removed=net-sum(sorted(black,reverse=True)[:3]) if not unclosed else None,
        share=p/(p+l) if p+l>EPS else None,mean_abs_net=mean_abs,
        normalized_median=median/mean_abs if mean_abs>EPS else None,
        mean_black=avgblack,worst_to_mean_black=worst_red/avgblack if avgblack is not None else None,
        all_positive=not unclosed and len(black)==len(rows),
        max_quantity=max((r['max_quantity'] for r in rows),default=None) if all(r['max_quantity'] is not None for r in rows) else None,
        initial_quantity_min=min((r['initial_quantity_min'] for r in rows if r['initial_quantity_min'] is not None),default=None),
        initial_quantity_max=max((r['initial_quantity_max'] for r in rows if r['initial_quantity_max'] is not None),default=None),
        initial_quantity_known=all(r['initial_quantity_min'] is not None or is_inactive(r) for r in rows),
        add_fills=sum(r['add_fills'] for r in rows) if all(r['add_fills'] is not None for r in rows) else None)


def rankings(specs: dict,cases: dict) -> list[dict]:
    """
    機能: 全三十六条件を同IDの両商品へ適用し、円額を跨いで比較せず順位を固定する。
    引数: specs/cases(dict)は仕様と商品別集計。
    返り値: list[dict]は資格→少ない黒字数→少ない正規化中央値→悪い損失補填比→ID順。
        除外する旧入口対照はなく、全条件を両商品共通の規則として比較する。
    """
    result=[]
    for ident in specs:
        values=[cases[ident]['metrics'][s] for s in SYMBOLS]
        qualified=all(v['net']>EPS and v['median']>EPS and v['top3_removed'] is not None and v['top3_removed']>EPS and not v['unclosed_sessions'] for v in values)
        norm=[v['normalized_median'] for v in values];risk=[v['worst_to_mean_black'] for v in values]
        result.append(dict(id=ident,family=specs[ident]['family'],qualified=qualified,
            min_black=min(v['black'] for v in values),min_normalized_median=min(norm) if all(v is not None for v in norm) else None,
            max_worst_to_mean_black=max(risk) if all(v is not None for v in risk) else None))
    result.sort(key=lambda v:(not v['qualified'],-v['min_black'],
        -v['min_normalized_median'] if v['min_normalized_median'] is not None else math.inf,
        v['max_worst_to_mean_black'] if v['max_worst_to_mean_black'] is not None else math.inf,v['id']))
    assert len(result)==36
    return result


def rules(spec: dict) -> dict:
    """
    機能: 同じ機械的規則の入口・保有・出口を各一文の日本語へ整える。
    引数: spec(dict)は数値結果で変更しない固定仕様。
    返り値: dict[str,str]は平易な三つの説明。
    """
    entry=spec['description'].strip().rstrip('。')+'。'
    size=spec['allocation_mode'];trail=spec['trail_multiple']
    if size==2:
        hold='最初は上限の20%で入り、順行を確認したときだけ40%・70%・100%へ増やします。初回の円損失枠を増やさず、1幅順行後は料金込みの建値以上へ停止線を有利にだけ動かします。'
    elif size==0:hold='上限の20%を固定して保有し、追加しません。小さく張っただけで結果が改善するかを確認する対照です。'
    elif size==1:hold='最初から上限の100%を固定して保有し、追加しません。増加法と同じ最大枚数の対照です。'
    else:hold='固定した枚数配分を保ち、当時の停止線と場内返済に従います。枚数方式の詳細は保存仕様に従います。'
    width='0.5幅' if trail==.5 else ('1幅' if trail==1 else '固定幅')
    exit_rule=width+'の戻りを追尾し、損切り又は場末では残玉を全て返済します。'
    return dict(入口=entry,保有=hold,出口=exit_rule)


def stat_cells(v: dict) -> str:
    """
    機能: 常時表示すべき安定性・費用・未清算の表セルを一組作る。
    引数: v(dict)は一商品・一政策の全四十場集計。
    返り値: strはHTMLセル。P/(P+L)と場黒字率を混同しない。
    """
    return ''.join('<td>'+value+'</td>' for value in (
        fmt(v['net'],True),f"{v['black']}/{v['red']}/{v['inactive']}",fmt(v['median'],True),
        fmt(v['worst'],True),fmt(v['top3_removed'],True),fmt(v['fees']),
        str(v['unclosed_sessions']),str(v['flat']),('—' if v['share'] is None else f"{v['share']*100:.1f}%")))


def stat_table(items: list[tuple[str,str,str,dict]],caption: str) -> str:
    """
    機能: 政策名・資格・商品を付けた安定性比較を共通形式で表示する。
    引数: items(list[tuple])は表示名・資格・商品・集計、caption(str)は表題。
    返り値: strは表だけ横スクロールするHTML。
    """
    body=''.join('<tr><th>'+esc(name)+'</th><td>'+esc(status)+'</td><td>'+symbol+'</td>'+stat_cells(v)+'</tr>' for name,status,symbol,v in items)
    return '<div class="table-wrap"><table><caption>'+esc(caption)+'</caption><thead><tr><th>政策</th><th>共通資格</th><th>商品</th><th>収支円</th><th>黒／赤／無</th><th>中央値円</th><th>最悪円</th><th>上位3黒字除外円</th><th>手数料円</th><th>未返済場</th><th>零収支場</th><th>金額利益割合</th></tr></thead><tbody>'+body+'</tbody></table></div>'


def session_table(ident: str,scenes: list[str],rows: dict,cases: dict) -> str:
    """
    機能: 四十場の両商品について親P/L・場net・親数・料金・残玉を全件表示する。
    引数: ident(str)、scenes(list[str])、rows/cases(dict)は保存小会計。
    返り値: strは四十行と全場合計。未取引行を省略しない。
    """
    body=[]
    for scene in scenes:
        cells='<th>'+esc(scene.replace('_Day',' デイ').replace('_Night',' ナイト'))+'</th>'
        for symbol in SYMBOLS:
            r=rows[ident,scene,symbol]
            cells+=''.join('<td>'+v+'</td>' for v in (fmt(r['profit']),fmt(r['loss']),fmt(r['net'],True),str(r['parents']),fmt(r['fees']),str(r['unclosed'])))
        body.append('<tr data-session="'+esc(scene)+'">'+cells+'</tr>')
    foot='<th>全40場合計</th>'
    for symbol in SYMBOLS:
        v=cases[ident]['metrics'][symbol]
        foot+=''.join('<td>'+x+'</td>' for x in (fmt(v['profit']),fmt(v['loss']),fmt(v['net'],True),str(v['parents']),fmt(v['fees']),str(v['unclosed_sessions'])+'場'))
    return '<div class="table-wrap"><table class="sessions" data-method="'+esc(ident)+'"><thead><tr><th rowspan="2">セッション</th><th colspan="6">TOPIXミニ10枚</th><th colspan="6">日経マイクロ20枚</th></tr><tr>'+2*'<th>利益円</th><th>損失円</th><th>収支円</th><th>完結親</th><th>手数料円</th><th>未返済枚数</th>'+'</tr></thead><tbody>'+''.join(body)+'</tbody><tfoot><tr>'+foot+'</tr></tfoot></table></div>'


def sizing_comparison(specs: dict,cases: dict) -> tuple[str,list]:
    """
    機能: 同じ入口・追尾幅で小枚数、全枚数、順行増加を対照表示する。
    引数: specs/cases(dict)は固定仕様と公開小会計。
    返り値: tuple[str,list]は比較表HTMLと商品別三方式の効果。異商品円額は足さない。
    """
    groups={}
    for ident,spec in specs.items():
        family=spec['entry_id'];mode=spec['allocation_mode'];trail=spec['trail_multiple']
        if mode not in SIZE_MODES or trail not in (.5,1):continue
        key=family,float(trail)
        assert mode not in groups.setdefault(key,{}),'同じ入口・追尾幅・配分方式の重複。'
        groups[key][mode]=ident
    rows=[];saved=[]
    for (family,trail),modes in sorted(groups.items()):
        if set(modes)!=set(SIZE_MODES):continue
        for symbol in SYMBOLS:
            m={mode:cases[ident]['metrics'][symbol] for mode,ident in modes.items()}
            saved.append(dict(family=family,trail_r=trail,symbol=symbol,methods=modes,
                grow_minus_scout=m[2]['net']-m[0]['net'],
                grow_minus_full=m[2]['net']-m[1]['net'],
                grow_fewer_red_than_full=m[2]['red']<m[1]['red'],
                grow_worst_better_than_full=m[2]['worst']>m[1]['worst']))
            for mode in SIZE_MODES:
                v=m[mode];label={0:'20%固定',1:'100%固定',2:'20→40→70→100%'}[mode]
                quantities='—' if not v['initial_quantity_known'] else ('無取引' if v['initial_quantity_min'] is None else str(v['initial_quantity_min']) if v['initial_quantity_min']==v['initial_quantity_max'] else str(v['initial_quantity_min'])+'〜'+str(v['initial_quantity_max']))
                fields=(esc(family),fmt(trail),symbol,label,fmt(v['net'],True),f"{v['black']}/{v['red']}/{v['inactive']}",
                    fmt(v['median'],True),fmt(v['worst'],True),fmt(v['top3_removed'],True),
                    fmt(v['max_quantity']),quantities,fmt(v['add_fills']))
                rows.append('<tr>'+''.join('<td>'+str(x)+'</td>' for x in fields)+'</tr>')
    if not rows:return '<p>枚数方式・追尾幅の対応は元仕様に従います。比較キー未保存のため三方式を機械的にまとめていません。</p>',saved
    head=('入口','追尾幅','商品','方式','収支円','黒／赤／無','中央値円','最悪円','上位3黒字除外円','実最大枚数','初回枚数','追加約定数')
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+v+'</th>' for v in head)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>',saved


def render(data: dict,result_sha: str,result_path: str) -> tuple[str,dict,str]:
    """
    機能: 全既知四十場の配分比較を、共通順位・三家族・全三十六条件へ表示する。
    引数: data(dict)、result_sha/result_path(str)は完成結果の指紋と原位置。
    返り値: tuple[str,dict,str]はHTML、全小会計、README。売買再生はしない。
    """
    specs,rows=validate(data);scenes=data['sessions'];cases={}
    for ident,spec in specs.items():
        cases[ident]=dict(spec=spec,rules=rules(spec),metrics={symbol:aggregate([rows[ident,s,symbol] for s in scenes]) for symbol in SYMBOLS},
            rows=[rows[ident,s,symbol] for s in scenes for symbol in SYMBOLS])
    rank=rankings(specs,cases);main=[];seen=set()
    for r in rank:
        if r['family'] not in seen:main.append(r['id']);seen.add(r['family'])
        if len(main)==3:break
    eligible=sum(r['qualified'] for r in rank)
    allpositive=sum(all(cases[r['id']]['metrics'][s]['all_positive'] for s in SYMBOLS) for r in rank)
    headline='既知40場内で両商品が毎場黒字の規則がありますが、未知データの成功ではありません。' if allpositive else '<strong>毎セッションの安定黒字は未達です。</strong>'
    lead=main[0];common='両商品へ同じID <code>'+esc(lead)+'</code>を適用する規則を先頭の参考にします。'
    common+='<br>'+esc(cases[lead]['rules']['入口'])+' '+esc(cases[lead]['rules']['保有'])+' '+esc(cases[lead]['rules']['出口'])
    principal=[]
    for ident in main:
        r=next(x for x in rank if x['id']==ident)
        principal.extend((specs[ident]['name'],'達成' if r['qualified'] else '未達・参考',symbol,cases[ident]['metrics'][symbol]) for symbol in SYMBOLS)
    summary=stat_table(principal,'上位の異なる入口家族・最大3規則（全40場）')
    sections=[]
    for ident in main:
        r=cases[ident]['rules'];body='<h2>'+esc(specs[ident]['name'])+'</h2><p class="muted"><code>'+esc(ident)+'</code></p>'
        body+=''.join('<p><b>'+key+'：</b>'+esc(r[key])+'</p>' for key in ('入口','保有','出口'))
        body+='<details><summary>この規則の全40場</summary>'+session_table(ident,scenes,rows,cases)+'</details>'
        sections.append('<section>'+body+'</section>')
    allitems=[];full=[]
    for item in rank:
        ident=item['id']
        allitems.extend((ident,'達成' if item['qualified'] else '未達',s,cases[ident]['metrics'][s]) for s in SYMBOLS)
        full.append('<details><summary>'+esc(ident)+' — '+esc(specs[ident]['name'])+'</summary>'+session_table(ident,scenes,rows,cases)+'</details>')
    sizing,sizing_effects=sizing_comparison(specs,cases)
    growth=[v for v in sizing_effects if v['grow_minus_scout']>EPS and v['grow_minus_full']>EPS]
    growth_note='同入口・同追尾幅の両固定対照より増加法の収支が高かった商品別比較は'+str(len(growth))+'/'+str(len(sizing_effects))+'件です。'
    growth_note+='この数は両商品共通の採用資格や将来の改善確率ではありません。'
    css='body{margin:0;background:#0b1120;color:#e6edf8;font:16px/1.6 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:28px 20px}h1{font-size:27px}h2{font-size:21px;margin-top:27px}p{max-width:1150px}a{color:#8ec8ff}strong{color:#ffd083}.muted{font-size:14px;color:#b0c0d6}code{overflow-wrap:anywhere}.note{background:#18263d;padding:14px 17px;border-left:4px solid #d7a952}.table-wrap{overflow-x:auto;max-width:100%;border:1px solid #34445a;border-radius:8px}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}th,td{padding:8px 10px;border-bottom:1px solid #34445a;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}caption{padding:10px;text-align:left;color:#cee1fa;font-weight:600}summary{padding:10px 0;color:#a7d0ff;cursor:pointer}details{margin-bottom:12px}@media(max-width:600px){main{padding:16px 10px}h1{font-size:23px}body{font-size:15px}}'
    doc='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小枚数と順行増加の比較と全セッション損益</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\nmainは全既知四十場の同入口配分比較を表示します。全三十六条件を共通順位へ含めます。\n.table-wrapは表だけの横スクロール領域、detailsは全条件と全場会計です。\n無取引と未清算を勝ちへ変えず、原入力又は金融の再生は行いません。\n--><main><h1>小枚数と順行増加の比較と全セッション損益</h1><p class="note">'+headline+' 共通比較資格は'+str(eligible)+'/36、両商品40場すべて黒字は'+str(allpositive)+'/36です。</p><p>'+common+'</p><p class="muted">上限TOPIXミニ10枚・日経マイクロ20枚、手数料とラージBBOの気配差込み。6入口×3配分×2追尾幅の全36規則を同じIDで両商品へ適用します。全40場を知った後の開発・事後順位で、確認13場・追加3場も未知検証ではありません。</p>'+summary+'<p class="muted">共通資格は両商品の全40収支・中央値・上位3黒字除外収支が正、かつ未返済0。順位は少ない方の黒字数→少ない方の中央値/平均絶対場収支→悪い方の最悪赤字/平均黒字の小ささ。同率はID固定順です。無取引・零収支・未返済を勝ちに数えません。金額割合は完結親P/(P+L)です。</p>'+''.join(sections)+'<h2>小さく張った効果と増加法の効果</h2><p>'+growth_note+'</p><p class="muted">20%固定と100%固定は同じ入口の枚数対照です。増加法は順行時の追加とbasket停止線を合わせた政策の比較で、追加だけの独立寄与ではありません。初回円リスクの維持は停止線に基づく設計で、気配の飛びや約定遅れによる損失上限を保証しません。追加約定数は枚数と区別し、未保存は—です。</p><details><summary>同入口・同追尾幅の三方式と実枚数</summary>'+sizing+'</details><details><summary>全36条件のまとめ</summary>'+stat_table(allitems,'全36条件の全40場集計')+'</details><details><summary>全36条件それぞれの全40場</summary>'+''.join(full)+'</details><p class="muted">実ミニ・マイクロの待ち順位・真の受信時刻は未観測で、観測価格時計による期限は壁時計での約定保証ではありません。未返済がある期間の上位3黒字除外は未評価です。</p><p><a href="data.json">全36条件の場会計JSON</a>　<a href="README.md">案内</a></p><p class="muted">原結果：<code>'+esc(result_path)+'</code><br>SHA256：<code>'+esc(result_sha)+'</code></p></main></body></html>'
    public=dict(sessions=scenes,splits=data.get('splits'),source_path=result_path,source_SHA256=result_sha,
        economic_source_SHA256=data['source_SHA256'],common_ranking=rank,main_ids=main,
        qualification_count=eligible,all40_positive_count=allpositive,cases=cases,sizing_comparisons=sizing_effects,
        ranking_scope='全既知40場での事後開発。全36規則を同じIDで両商品へ適用。',
        normalization='中央値/全40場の平均絶対net。最悪赤字/黒字場平均。円跨ぎ・Rcash比較なし。',
        market_reads=0,financial_replay=0,API=0)
    readme='# 小枚数と順行増加の比較と全セッション損益\n\n最初に['+HTML_NAME+']('+HTML_NAME+')を開いてください。全36規則の共通順位から異なる入口家族を最大3つ表示します。各条件の全40場、全比較、小枚数・全枚数・増加法の対照は折り畳みに残します。\n\n全40場を知った後の開発です。確認13・追加3を未知検証成功とは呼びません。上限はTOPIXミニ10枚・日経マイクロ20枚。親完結netの総正負がP/Lで、無取引・零収支・未返済は勝ちに数えません。\n\n小さく張っただけで損失が減った効果と、順行してから増やした効果を同入口・同追尾幅で比較します。増加法は追加と停止線を合わせた政策で、追加だけの独立効果とは呼びません。円リスク固定は設計上の停止線であり、飛びや費用を無視した実損失保証ではありません。合計黒字だけで採用せず、中央値・最悪・上位3黒字除外・未返済を確認します。\n\n[data.json](data.json)は全36条件の小会計です。原結果 `'+result_path+'`、SHA256 `'+result_sha+'`。原結果は指定SHAで一読し、同bytesを私有保全します。実小型板の待ち順位・真受信時計は未証明です。\n'
    return doc,public,readme


def generate(data: dict,output: Path,result_sha: str,result_path: str,fixture: bool=False) -> dict:
    """
    機能: 元結果の再読なしでHTMLと全小会計を新規フォルダへ保存する。
    引数: data(dict)、output(Path)、result_sha/result_path(str)、fixture(bool)は合成の区別。
    返り値: dictは生成SHAと件数。既存初回stagingを変更しない。
    """
    doc,public,readme=render(data,result_sha,result_path)
    assert not output.exists(),'既存公開物は上書きしません。'
    output.mkdir(parents=True)
    payloads={HTML_NAME:doc.encode('utf8'),'data.json':encoded(public),'README.md':readme.encode('utf8')}
    for name,raw in payloads.items():(output/name).write_bytes(raw)
    proof=dict(passed=True,fixture=fixture,result_path=result_path,result_sha256=result_sha,
        report_sha256=sha(Path(__file__).read_bytes()),artifacts={name:sha(raw) for name,raw in payloads.items()},
        policies=36,common_ranking=36,baseline_controls=0,sessions=40,symbol_sessions=2880,
        main_ids=public['main_ids'],market_reads=0,financial_replay=0,API=0)
    (output/'生成証跡.json').write_bytes(encoded(proof))
    return proof


def main() -> None:
    """
    機能: 根が指定した完成SHAの原本だけを一読し、同bytes保全後に生成する。
    引数: CLI --result(Path)、--expected-sha256(str)、--output(Path)、--received(Path)。
    返り値: None。指紋不一致・既存copy・既存公開は生成前に拒否する。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--received',type=Path,default=PRIVATE/'received')
    parser.add_argument('--fixture',action='store_true')
    args=parser.parse_args();expected=args.expected_sha256.lower()
    assert re.fullmatch('[0-9a-f]{64}',expected) and not args.output.exists() and not args.received.exists()
    raw=args.result.read_bytes();assert sha(raw)==expected,'指定完成SHAとの不一致。'
    args.received.mkdir(parents=True);copy=args.received/args.result.name;copy.write_bytes(raw)
    receipt=dict(source_path=str(args.result),source_SHA256=expected,bytes=len(raw),source_reads=1,
        own_copy=str(copy),own_copy_SHA256=sha(raw),fixture=args.fixture,market_reads=0,financial_replay=0,API=0)
    (args.received/'一読と同bytes保全.json').write_bytes(encoded(receipt))
    data=json.loads(raw.decode('utf8'))
    try:source_path=args.result.resolve().relative_to(ROOT).as_posix()
    except ValueError:source_path=str(args.result.resolve())
    print(json.dumps(generate(data,args.output,expected,source_path,args.fixture),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
