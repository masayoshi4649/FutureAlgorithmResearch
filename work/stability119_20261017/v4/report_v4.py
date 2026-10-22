"""元候補の順逆売買と既知時刻回避を分離し、全四十八規則・全四十場を表示する。"""

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
PRIVATE=BASE/'privatev4'
DEFAULT_OUTPUT=PRIVATE/'public'
HTML_NAME='順逆売買と時間回避の比較と全セッション損益.html'
SYMBOLS=('TOPIX','NK225')
BASELINES=()
MONEY=('net','realized','profit','loss','fees','max_drawdown')
COUNTS=('parents','wins','losses','closed_quantity','unclosed','canceled','fills','halted',
        'protected_fallbacks','protected_wait_rows','rejected_entries')
OPTIONAL=('canceled','fills','halted','protected_fallbacks','protected_wait_rows','rejected_entries')
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
    機能: 四十八条件・四十場・二商品の掲載元を確認し、欠場を拒否する。
    引数: data(dict)は指定完成SHAの一読結果又は合成fixture。
    返り値: tuple[dict,dict]は仕様表と商品場会計。原板や実注文は再検査しない。
    """
    scenes=data['sessions'];assert len(scenes)==len(set(scenes))==40
    specs={v['id']:dict(v) for v in data['specs']}
    assert len(specs)==len(data['specs'])==48
    for ident,spec in specs.items():
        for key in ('family','name','description'):assert isinstance(spec[key],str) and spec[key].strip(),(ident,key)
        assert spec['execution_mode'] in (0,1,2,3)
        assert spec['exit_mode'] in (0,1,2,3,4,5)
        assert spec['family']==spec['entry_id'] and spec['direction_mode'] in ('direct','reverse') and spec['time_mode'] in (0,1) and spec['guard']==2
    groups={(s['entry_id'],s['direction_mode'],s['exit_mode'],s['execution_mode'],s['time_mode']) for s in specs.values()}
    assert len(groups)==48 and {s['family'] for s in specs.values()}=={'COMMON20','OPEN20','LAG20'}
    assert {s['exit_mode'] for s in specs.values()}=={4,5} and {s['execution_mode'] for s in specs.values()}=={0,3}
    assert len(data['runs'])==48*40*2
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
        all_positive=not unclosed and len(black)==len(rows))


def rankings(specs: dict,cases: dict) -> list[dict]:
    """
    機能: 全四十八条件を同IDの両商品へ適用し、円額を跨いで比較せず順位を固定する。
    引数: specs/cases(dict)は仕様と商品別集計。
    返り値: list[dict]は資格→少ない黒字数→少ない正規化中央値→悪い損失補填比→ID順。
        順逆や時刻回避を別家族へ水増しせず、全条件を共通ランキングへ含める。
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
    assert len(result)==48
    return result


def rules(spec: dict) -> dict:
    """
    機能: 同じ機械的規則の入口・保有・出口を各一文の日本語へ整える。
    引数: spec(dict)は数値結果で変更しない固定仕様。
    返り値: dict[str,str]は平易な三つの説明。
    """
    descriptions={
        'COMMON20':'自他の20分変化が各0.75幅以上で同方向、経路効率が自己0.35・相手0.25以上、現在値も自己平均の同方向側となった元候補で',
        'OPEN20':'最初20本の正常な足で固定した高安帯から、確定価格と公開現在値が1観測呼値を超えて外へ出た元候補で',
        'LAG20':'相手が20分で1幅進み経路効率0.4以上、自身の進行は小さい一方で直近3分が相手方向へ1観測呼値以上進んだ元候補で'}
    entry=descriptions[spec['entry_id']]+('その反対方向へ参加します。' if spec['direction_mode']=='reverse' else 'その方向へ参加します。')
    hold='順逆に対応した元の根拠の撤回・固定損切り・場の損失枠に達するまで保有し、追加しません。'
    if spec['exit_mode']==5:exit_rule='建値から1幅の利確又は1幅の損切りで返済し、場末には全玉を返済します。'
    elif spec['exit_mode']==4:exit_rule='1幅順行した後は0.5幅の戻りを追尾し、1幅逆行又は場末で全玉を返済します。'
    else:exit_rule='旧版と同じ利確・損切り・場予算を保ち、保護の有無だけを比較します。'
    mode=spec['execution_mode']
    if mode&1:entry=entry.rstrip('。')+'が、新規の既知気配と価格上限で不利な約定も制限します。'
    if mode&2:exit_rule=exit_rule.rstrip('。')+'が、返済時は固定価格を保護し、価格時計30秒後は成行へ切り替えます。'
    if spec['time_mode']:
        entry+=' 日本開始帯とNYの公表・現物開始前後の固定時間帯では新規を止めます。'
        exit_rule+=' その時間帯の足が公開されたときも返済を判断します。'
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


def factor_comparison(specs: dict,cases: dict) -> tuple[str,list]:
    """
    機能: 同じ入口・出口・執行で順逆と時刻回避の四通りを並べ、二因子を分ける。
    引数: specs/cases(dict)は固定仕様と小会計。
    返り値: tuple[str,list]は商品別二十四行のHTMLと差分。異商品円額を足さない。
    """
    groups={}
    for ident,spec in specs.items():
        key=spec['entry_id'],spec['exit_mode'],spec['execution_mode']
        pair=spec['direction_mode'],spec['time_mode']
        assert pair not in groups.setdefault(key,{})
        groups[key][pair]=ident
    assert len(groups)==12 and all(set(v)=={('direct',0),('reverse',0),('direct',1),('reverse',1)} for v in groups.values())
    saved=[];rows=[]
    for (family,xm,pm),methods in sorted(groups.items()):
        for symbol in SYMBOLS:
            nets={pair:cases[ident]['metrics'][symbol]['net'] for pair,ident in methods.items()}
            difference=dict(reverse_minus_direct_time0=nets['reverse',0]-nets['direct',0],
                reverse_minus_direct_time1=nets['reverse',1]-nets['direct',1],
                avoid_minus_all_direct=nets['direct',1]-nets['direct',0],
                avoid_minus_all_reverse=nets['reverse',1]-nets['reverse',0])
            saved.append(dict(entry_id=family,exit_mode=xm,execution_mode=pm,symbol=symbol,
                methods={d+'_T'+str(t):ident for (d,t),ident in methods.items()},**difference))
            fields=[family,'対称1幅' if xm==5 else '0.5幅追尾','保護なし' if pm==0 else '両保護',symbol]
            fields.extend(fmt(nets[pair],True) for pair in (('direct',0),('reverse',0),('direct',1),('reverse',1)))
            fields.extend(fmt(value,True) for value in difference.values())
            rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in fields)+'</tr>')
    headings=('入口','出口','執行','商品','順・全時間円','逆・全時間円','順・回避円','逆・回避円','逆−順 全時間円','逆−順 回避円','回避−全 順円','回避−全 逆円')
    table='<div class="table-wrap"><table class="factors"><thead><tr>'+''.join('<th>'+v+'</th>' for v in headings)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    return table,saved


def render(data: dict,result_sha: str,result_path: str) -> tuple[str,dict,str]:
    """
    機能: 順逆と時刻の固定四十八対照を、共通順位・三家族・全場会計へ表示する。
    引数: data(dict)、result_sha/result_path(str)は完成結果の指紋と原位置。
    返り値: tuple[str,dict,str]はHTML、小会計JSON、README。売買を再生しない。
    """
    specs,rows=validate(data);scenes=data['sessions'];cases={}
    for ident,spec in specs.items():
        cases[ident]=dict(spec=spec,rules=rules(spec),metrics={symbol:aggregate([rows[ident,s,symbol] for s in scenes]) for symbol in SYMBOLS},
            rows=[rows[ident,s,symbol] for s in scenes for symbol in SYMBOLS])
    rank=rankings(specs,cases);main=[];seen=set()
    for item in rank:
        if item['family'] not in seen:main.append(item['id']);seen.add(item['family'])
        if len(main)==3:break
    eligible=sum(r['qualified'] for r in rank)
    allpositive=sum(all(cases[r['id']]['metrics'][s]['all_positive'] for s in SYMBOLS) for r in rank)
    headline='既知40場で両商品が毎場黒字の規則がありますが、未知の成功ではありません。' if allpositive else '<strong>毎セッションの安定黒字は未達です。</strong>'
    lead=main[0];common='同じID <code>'+esc(lead)+'</code>を両商品へ適用する規則を先頭の参考にします。<br>'+esc(cases[lead]['rules']['入口'])+' '+esc(cases[lead]['rules']['出口'])
    principal=[];sections=[];allitems=[];full=[]
    for ident in main:
        status=next(r['qualified'] for r in rank if r['id']==ident)
        principal.extend((specs[ident]['name'],'達成' if status else '未達・参考',symbol,cases[ident]['metrics'][symbol]) for symbol in SYMBOLS)
        ruleset=cases[ident]['rules']
        body='<h2>'+esc(specs[ident]['name'])+'</h2><p class="muted"><code>'+esc(ident)+'</code></p>'
        body+=''.join('<p><b>'+key+'：</b>'+esc(ruleset[key])+'</p>' for key in ('入口','保有','出口'))
        body+='<details><summary>この規則の全40場</summary>'+session_table(ident,scenes,rows,cases)+'</details>'
        sections.append('<section>'+body+'</section>')
    for item in rank:
        ident=item['id']
        allitems.extend((ident,'達成' if item['qualified'] else '未達',symbol,cases[ident]['metrics'][symbol]) for symbol in SYMBOLS)
        full.append('<details><summary>'+esc(ident)+' — '+esc(specs[ident]['name'])+'</summary>'+session_table(ident,scenes,rows,cases)+'</details>')
    comparison,factors=factor_comparison(specs,cases)
    css='body{margin:0;background:#0b1120;color:#e6edf8;font:16px/1.6 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:28px 20px}h1{font-size:27px}h2{font-size:21px;margin-top:27px}p{max-width:1150px}a{color:#8ec8ff}strong{color:#ffd083}.muted{font-size:14px;color:#b0c0d6}code{overflow-wrap:anywhere}.note{background:#18263d;padding:14px 17px;border-left:4px solid #d7a952}.table-wrap{overflow-x:auto;max-width:100%;border:1px solid #34445a;border-radius:8px}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}th,td{padding:8px 10px;border-bottom:1px solid #34445a;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}caption{padding:10px;text-align:left;color:#cee1fa;font-weight:600}summary{padding:10px 0;color:#a7d0ff;cursor:pointer}details{margin-bottom:12px}@media(max-width:600px){main{padding:16px 10px}h1{font-size:23px}body{font-size:15px}}'
    note='元と同じ候補公開時点のentryを順方向又は逆方向にし、実際の買ask・売bidで運転をやり直します。旧収支の符号反転ではありません。撤回条件も左右交換し、反転後の損益で出口・再参加・場停止を判定するので、実際の入口時刻の集合は一致しません。'
    limitations='時刻回避は日本08:45以上09:15未満と、NYの毎日08:30/09:30の前後15分です。America/New_Yorkの夏時間を使い、休日例外は設けない保守窓です。ニュースの数値は使いません。窓開始そのもののtimerではなく、その窓にある価格時計の足公開で新規拒否・待機取消・保有返済を判断します。同原行ではquoteが先なので新規が約定してから返済判断となり得ます。入場資格を消すため、場予算の最初の有効Rも後ろへずれ得ます。'
    doc='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>順逆売買と時間回避の比較と全セッション損益</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\nmainは全四十八条件の共通順位と全四十場を表示します。順逆・時刻別の比較表をdetailsに収めます。\n.table-wrapは表だけの横スクロール領域です。無取引・未返済を勝ちに数えません。\n原市場や金融を再生せず、保存結果の会計だけを表示します。\n--><main><h1>順逆売買と時間回避の比較と全セッション損益</h1><p class="note">'+headline+' 共通比較資格'+str(eligible)+'/48、両商品40場すべて黒字'+str(allpositive)+'/48です。</p><p>'+common+'</p><p class="muted">TOPIXミニ10枚・日経マイクロ20枚、手数料とラージBBOの気配差込み。3入口×順逆2×出口2×執行2×時刻2の48規則を、同じIDで両商品へ適用します。全40場を知った後の開発・事後順位で、確認13場と追加3場も未知検証ではありません。</p>'+stat_table(principal,'上位の異なる入口家族・最大3規則（全40場）')+'<p class="muted">共通資格は両商品の収支・中央値・上位3黒字除外収支が正、未返済0。順位は少ない方の黒字数→少ない方の中央値/平均絶対場収支→悪い方の最悪赤字/平均黒字の小ささ、同率はID順です。異商品の円額を足して順位にしません。無取引・零収支・未返済は勝ちに数えず、金額割合は完結親P/(P+L)です。</p>'+''.join(sections)+'<details><summary>方向と時刻を分けた比較（同入口・同出口・同執行）</summary><p>順と逆の差は同じ時刻条件内で、回避の差は同じ方向条件内で比較します。単に損失の符号を逆にした計算ではありません。</p>'+comparison+'</details><details><summary>全48条件のまとめ</summary>'+stat_table(allitems,'全48条件の全40場集計')+'</details><details><summary>全48条件それぞれの全40場</summary>'+''.join(full)+'</details><details><summary>比較の範囲と限界</summary><p>'+note+'</p><p>'+limitations+'</p><p>場の損失枠は最初の有効R×上限数量×倍率の2倍で、v3の少量基準とは異なります。返済気配の飛びで超過し得ます。実小型板の待ち順位・真受信時計・壁時計30秒の約定は未証明です。未返済がある期間の上位3黒字除外は未評価です。</p></details><p><a href="data.json">全48条件の場会計JSON</a>　<a href="README.md">案内</a></p><p class="muted">原結果：<code>'+esc(result_path)+'</code><br>SHA256：<code>'+esc(result_sha)+'</code></p></main></body></html>'
    public=dict(sessions=scenes,splits=data.get('splits'),source_path=result_path,source_SHA256=result_sha,
        economic_source_SHA256=data['source_SHA256'],common_ranking=rank,main_ids=main,
        qualification_count=eligible,all40_positive_count=allpositive,cases=cases,factor_comparisons=factors,
        ranking_scope='既知全40場の事後開発。48規則全て同IDで両商品へ適用。',
        normalization='中央値/全40平均絶対net、最悪赤字/黒字場平均。異商品円額の合計とRcashを使わない。',
        market_reads=0,financial_replay=0,API=0)
    readme='# 順逆売買と時間回避の比較と全セッション損益\n\n最初に['+HTML_NAME+']('+HTML_NAME+')を開いてください。共通48規則を同じIDで両商品へ適用し、異なる元入口家族から最大3規則を上部へ掲載します。全48の全40場と方向・時刻の四通り対照は折り畳みに残します。\n\n全40場を知った後の開発です。確認13・追加3も未知検証ではありません。TOPIXミニ10枚・日経マイクロ20枚、費用後の完結親netの総正負がP/Lです。無取引・零収支・未返済を成功へ変えません。中央値・最悪・上位3黒字除外・手数料・未返済を常に併記します。\n\n'+note+'\n\n'+limitations+'\n\n[data.json](data.json)は全48小会計です。原結果 `'+result_path+'`、SHA256 `'+result_sha+'`。指定元を一読して同bytesの私有copyを保全します。実小型板の待ち順位・真受信時計・約定遅延の再現は未証明です。\n'
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
        policies=48,common_ranking=48,baseline_controls=0,sessions=40,symbol_sessions=3840,
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
