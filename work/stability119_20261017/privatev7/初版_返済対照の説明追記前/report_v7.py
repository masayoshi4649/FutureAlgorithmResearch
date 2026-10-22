"""二脚相対継続の八組政策を、両脚別の費用と全四十場合計まで表示する。"""

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
PRIVATE=BASE/'privatev7'
HTML_NAME='相対的な強さの継続と残差追尾の全セッション損益.html'
SYMBOLS=('NK225','TOPIX')
EPS=1e-7


def sha(raw: bytes) -> str:
    """
    機能: 一読内容又は生成物の指紋を求める。
    引数: raw(bytes)はファイル内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


def encoded(value: object) -> bytes:
    """
    機能: 日本語の有限JSONをUTF-8へ変換する。
    引数: value(object)は小会計や生成証跡。
    返り値: bytesは保存内容。不正なInfinityを許さない。
    """
    return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')


def esc(value: object) -> str:
    """
    機能: 本文と属性へ使う文字列を保護する。
    引数: value(object)は説明又はID。
    返り値: strはエスケープ済み文字列。
    """
    return html.escape(str(value),quote=True)


def fmt(value: float|None,signed: bool=False) -> str:
    """
    機能: 未評価と零を区別して円を表示する。
    引数: value(float|None)は保存数値、signed(bool)は符号指定。
    返り値: strは千位区切り又は—。
    """
    if value is None:return '—'
    if abs(value)<=EPS:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def validate(data: dict) -> tuple[dict,dict]:
    """
    機能: 八政策・四十組場・両脚会計を確認し、欠場と暗黙の零補完を拒否する。
    引数: data(dict)は指定完成SHAの結果又は完全合成値。
    返り値: tuple[dict,dict]は仕様と組場会計。市場・金融を再生しない。
    """
    scenes=data['sessions'];assert len(scenes)==len(set(scenes))==40
    specs={s['id']:s for s in data['specs']}
    assert len(specs)==8 and {(s['method'],s['lookback'],s['exit_mode']) for s in specs.values()}=={(m,l,x) for m in ('ratio_mr','ols_mr') for l in (30,60) for x in (0,1)} and all(s['family']=='momentum' for s in specs.values())
    rows={};assert len(data['runs'])==320
    money=('net','realized','profit','loss','fees','max_drawdown','single_leg_seconds','max_single_leg_notional','expected_close_fees')
    counts=('parents','wins','losses','unclosed','fills','canceled','halted','closed_quantity','attempts','no_fill_attempts','paired_parents','aborted_parents','pending_entries')
    for row in data['runs']:
        key=row['method'],row['session'];assert key[0] in specs and key[1] in scenes and key not in rows and row['symbol']=='PAIR'
        for k in money:assert isinstance(row[k],(int,float)) and not isinstance(row[k],bool) and math.isfinite(row[k]),(key,k)
        for k in counts:assert isinstance(row[k],(int,float)) and int(row[k])==row[k] and row[k]>=0,(key,k)
        assert min(row[k] for k in ('profit','loss','fees','max_drawdown','single_leg_seconds','max_single_leg_notional','expected_close_fees'))>=-EPS
        if not row['unclosed']:assert abs(row['profit']-row['loss']-row['net'])<1e-5 and abs(row['realized']-row['net'])<1e-5
        assert row['wins']+row['losses']<=row['parents'] and row['paired_parents']+row['aborted_parents']==row['parents']
        assert set(row['legs'])==set(SYMBOLS)
        for symbol,leg in row['legs'].items():
            for k in ('gross','fees','realized','unrealized_after_close_fees','net'):assert isinstance(leg[k],(int,float)) and math.isfinite(leg[k]),(key,symbol,k)
            for k in ('fills','entry_quantity','closed_quantity','unclosed'):assert int(leg[k])==leg[k] and leg[k]>=0
            assert abs(leg['net']-leg['realized']-leg['unrealized_after_close_fees'])<1e-5
            assert abs(leg['gross']-leg['fees']-leg['realized'])<1e-5,(key,symbol,'脚の実現会計')
        for keyname in ('net','realized','fees','fills','closed_quantity','unclosed'):
            assert abs(sum(row['legs'][s][keyname] for s in SYMBOLS)-row[keyname])<1e-5,(key,keyname)
        if row['fills']==0:assert row['parents']==row['unclosed']==0 and abs(row['net'])<EPS and abs(row['fees'])<EPS
        rows[key]=row
    assert data['source_SHA256']
    return specs,rows


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 組全体の費用後資産と完結親P/Lを、無取引・未清算と分けて集計する。
    引数: rows(list[dict])は一政策の四十場。
    返り値: dictはPAIR集計。片脚の収益を相対継続的中率と呼ばない。
    """
    net=[r['net'] for r in rows];black=[];red=[];inactive=flat=unclosed=0
    for r in rows:
        if r['unclosed']:unclosed+=1
        elif r['fills']==0:inactive+=1
        elif r['net']>EPS:black.append(r['net'])
        elif r['net']<-EPS:red.append(-r['net'])
        else:flat+=1
    p=sum(r['profit'] for r in rows);loss=sum(r['loss'] for r in rows)
    mean_abs=statistics.mean(abs(v) for v in net);median=statistics.median(net)
    return dict(sessions=len(rows),net=sum(net),profit=p,loss=loss,fees=sum(r['fees'] for r in rows),parents=sum(r['parents'] for r in rows),
        black=len(black),red=len(red),inactive=inactive,flat=flat,unclosed_sessions=unclosed,
        mean=statistics.mean(net),median=median,worst=min(net),top3_removed=sum(net)-sum(sorted(black,reverse=True)[:3]) if not unclosed else None,
        share=p/(p+loss) if p+loss>EPS else None,normalized_median=median/mean_abs if mean_abs>EPS else None,
        worst_to_mean_black=max(red,default=0)/statistics.mean(black) if black else None,
        paired_parents=sum(r['paired_parents'] for r in rows),aborted_parents=sum(r['aborted_parents'] for r in rows),
        no_fill_attempts=sum(r['no_fill_attempts'] for r in rows),single_leg_seconds=sum(r['single_leg_seconds'] for r in rows),
        max_single_leg_notional=max(r['max_single_leg_notional'] for r in rows),all_positive=len(black)==len(rows) and not unclosed)


def aggregate_leg(rows: list[dict],symbol: str) -> dict:
    """
    機能: 個別脚の総gross・実費用・時価込みnetを独立に集計する。
    引数: rows(list[dict])は組の四十場、symbol(str)は対象脚。
    返り値: dictは脚別集計。単独戦略の利益確率又は勝ち数を作らない。
    """
    values=[r['legs'][symbol] for r in rows]
    return dict(gross=sum(v['gross'] for v in values),fees=sum(v['fees'] for v in values),net=sum(v['net'] for v in values),
        realized=sum(v['realized'] for v in values),unrealized_after_close_fees=sum(v['unrealized_after_close_fees'] for v in values),
        fills=sum(v['fills'] for v in values),entry_quantity=sum(v['entry_quantity'] for v in values),closed_quantity=sum(v['closed_quantity'] for v in values),
        unclosed_sessions=sum(v['unclosed']>0 for v in values))


def rules(spec: dict) -> dict:
    """
    機能: 同じ相対momentum入口と二つの退出政策を短い説明にする。
    引数: spec(dict)は固定したモデル・期間・退出。
    返り値: dict[str,str]は入口・保有・出口。
    """
    model='NK/TOP対数比' if spec['method']=='ratio_mr' else '対数価格の回帰残差'
    entry=f"過去{spec['lookback']}分の{model}が中心から2標準偏差以上離れたら、相対的に強い側を買い弱い側を売ります。"
    hold='予約時のモデル・標準偏差・整数枚数を固定します。両脚は別々に約定し、60秒で片脚だけなら未約定側を取消後に孤立脚を返済します。'
    if spec['exit_mode']==0:
        exit_rule='固定中心へ戻るか、入口からさらに2標準偏差進めば返済します。現金の損失枠は入口乖離に相当する額で、場末も全返済します。'
    else:
        exit_rule='2標準偏差進んだ後は残差peakから1標準偏差戻りで追尾返済し、入口から逆へ1標準偏差又は同幅の現金損失でも停止します。場末も全返済します。'
    return dict(入口=entry,保有=hold,出口=exit_rule)


def session_table(ident: str,scenes: list[str],rows: dict,cases: dict) -> str:
    """
    機能: 全四十場の組P/L/netと各脚gross/fees/netを同じ表へ掲載する。
    引数: ident(str)、scenes(list[str])、rows/cases(dict)は公開小会計。
    返り値: strは横スクロール表。無取引行を省略しない。
    """
    output=[]
    for scene in scenes:
        r=rows[ident,scene];values=[fmt(r['profit']),fmt(r['loss']),fmt(r['net'],True),str(r['parents'])]
        for symbol in SYMBOLS:values.extend([fmt(r['legs'][symbol]['gross'],True),fmt(r['legs'][symbol]['fees']),fmt(r['legs'][symbol]['net'],True)])
        values.extend([str(r['aborted_parents']),str(r['no_fill_attempts']),str(r['unclosed'])])
        output.append('<tr data-session="'+esc(scene)+'"><th>'+esc(scene.replace('_Day',' デイ').replace('_Night',' ナイト'))+'</th>'+''.join('<td>'+v+'</td>' for v in values)+'</tr>')
    case=cases[ident];m=case['metrics']['PAIR'];total=[fmt(m['profit']),fmt(m['loss']),fmt(m['net'],True),str(m['parents'])]
    for symbol in SYMBOLS:total.extend([fmt(case['legs'][symbol]['gross'],True),fmt(case['legs'][symbol]['fees']),fmt(case['legs'][symbol]['net'],True)])
    total.extend([str(m['aborted_parents']),str(m['no_fill_attempts']),str(m['unclosed_sessions'])+'場'])
    heads=('セッション','組利益円','組損失円','組収支円','完結組','NK粗損益円','NK料円','NK収支円','TOP粗損益円','TOP料円','TOP収支円','単脚返済組','全未約定','未返済枚数')
    return '<div class="table-wrap"><table class="sessions" data-method="'+esc(ident)+'"><thead><tr>'+''.join('<th>'+h+'</th>' for h in heads)+'</tr></thead><tbody>'+''.join(output)+'</tbody><tfoot><tr><th>全40場合計</th>'+''.join('<td>'+v+'</td>' for v in total)+'</tr></tfoot></table></div>'


def render(data: dict,result_sha: str,result_path: str) -> tuple[str,dict,str]:
    """
    機能: 二脚組口座の固定八条件を簡潔なHTMLと小JSONへ変換する。
    引数: data(dict)、result_sha/result_path(str)は指定完成内容と由来。
    返り値: tuple[str,dict,str]はHTML・公開小会計・README。市場/金融読取はない。
    """
    specs,rows=validate(data);scenes=data['sessions'];cases={}
    for ident,spec in specs.items():
        rr=[rows[ident,scene] for scene in scenes]
        cases[ident]=dict(spec=spec,rules=rules(spec),metrics=dict(PAIR=aggregate(rr)),legs={s:aggregate_leg(rr,s) for s in SYMBOLS},rows=rr)
    rank=[]
    for ident,case in cases.items():
        m=case['metrics']['PAIR'];qualified=m['net']>EPS and m['median']>EPS and m['top3_removed'] is not None and m['top3_removed']>EPS and not m['unclosed_sessions']
        rank.append(dict(id=ident,family=specs[ident]['family'],qualified=qualified,black=m['black'],normalized_median=m['normalized_median'],worst_to_mean_black=m['worst_to_mean_black']))
    rank.sort(key=lambda r:(not r['qualified'],-r['black'],-r['normalized_median'] if r['normalized_median'] is not None else math.inf,r['worst_to_mean_black'] if r['worst_to_mean_black'] is not None else math.inf,r['id']))
    eligible=sum(r['qualified'] for r in rank);allpositive=sum(c['metrics']['PAIR']['all_positive'] for c in cases.values())
    headline='<strong>毎セッションの安定黒字は未達です。</strong>' if not allpositive else '既知40場で毎場黒字の組がありますが、未知の成功ではありません。'
    statrows=[];sections=[]
    for item in rank:
        ident=item['id'];m=cases[ident]['metrics']['PAIR'];share='—' if m['share'] is None else f"{m['share']*100:.1f}%"
        values=[ident,'達成' if item['qualified'] else '未達',fmt(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",fmt(m['mean'],True),fmt(m['median'],True),fmt(m['worst'],True),fmt(m['top3_removed'],True),fmt(m['fees']),share,str(m['unclosed_sessions'])]
        statrows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
        section='<section><h2>'+esc(specs[ident]['name'])+'</h2><p class="muted"><code>'+esc(ident)+'</code></p>'
        section+=''.join('<p><b>'+key+'：</b>'+esc(value)+'</p>' for key,value in cases[ident]['rules'].items())
        section+='<details><summary>組と各脚の全40場</summary>'+session_table(ident,scenes,rows,cases)+'</details></section>';sections.append(section)
    heads=('政策','組資格','組収支円','黒／赤／無','平均円','中央値円','最悪円','上位3黒字除外円','実手数料円','金額利益割合','未返済場')
    summary='<div class="table-wrap"><table class="summary"><thead><tr>'+''.join('<th>'+h+'</th>' for h in heads)+'</tr></thead><tbody>'+''.join(statrows)+'</tbody></table></div>'
    css='body{margin:0;background:#0b1120;color:#e6edf8;font:16px/1.6 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:25px 20px}h1{font-size:27px}h2{font-size:21px}a{color:#8ec8ff}strong{color:#ffd083}.note{background:#18263d;padding:14px 17px;border-left:4px solid #d7a952}.muted{color:#afbed3;font-size:14px}code{overflow-wrap:anywhere}.table-wrap{overflow-x:auto;max-width:100%;border:1px solid #34445a;border-radius:8px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{text-align:right;padding:8px 10px;border-bottom:1px solid #34445a}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}details{margin:12px 0}summary{cursor:pointer;color:#a7d0ff;padding:8px 0}@media(max-width:600px){main{padding:15px 10px}h1{font-size:23px}body{font-size:15px}}'
    caveat='一場一つの二脚組口座であり、日経単独とTOPIX単独の両方が儲かった検証ではありません。片脚の実損益も隠さず表示します。無取引・全未約定は勝ちに数えず、単脚返済は完成ペアの的中とは呼びません。未清算の収支には清算時価を含み、上位3黒字除外は未評価です。'
    doc='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>相対的な強さの継続と残差追尾の全セッション損益</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\nmainは八つの二脚組口座を全四十場で表示します。単商品二つの成功へ読み替えません。\n.table-wrapは表だけ横スクロールし、detailsに組P/Lと各脚gross/fees/netを全て残します。\n金融又は原市場を再生せず、指定保存結果のみを表示します。\n--><main><h1>相対的な強さの継続と残差追尾の全セッション損益</h1><p class="note">'+headline+' 組の比較資格は'+str(eligible)+'/8、40場すべて黒字は'+str(allpositive)+'/8です。</p><p>固定した八条件で、日経とTOPIXの相対的な強さが続く向きに二脚を持ちます。上限はNK225マイクロ20枚・TOPIXミニ10枚。手数料とラージの売買気配差を含みます。全40場は既知の開発で、確認13場と追加3場も未知検証ではありません。</p>'+summary+'<p class="muted">組資格は合計収支・中央値・上位3黒字除外収支が正、未返済0です。各脚の黒字は必須としません。順序は資格→黒字場数→中央値/平均絶対場収支→最悪赤字/平均黒字→IDです。利益・損失は完結した親組netの総正負、金額割合はP/(P+L)です。</p>'+''.join(sections)+'<details><summary>比較の範囲と限界</summary><p>'+caveat+'</p><p>過去00009/00011のNT momentumと発想は重なります。v5の相対回帰が負けた既知40場を見た後の対立仮説です。推定式のmethod名にMRが残りますが、売買は相対momentumです。全8件は同系統の変数対照で、8つの独立した収益源ではありません。固定退出は入口乖離額、残差追尾は2標準偏差額を予定利益として料金の3倍以上を審査します。したがって二出口は実受理集合も変わり、出口だけの同一取引比較ではありません。予約時のモデルと枚数を固定し、事後の相対収益/共通元本差分解を売買判断へ戻しません。実ミニ・マイクロ板の待ち順位・真受信順・壁時計の期限内約定は未証明です。</p></details><p><a href="data.json">全8条件の組と各脚の会計JSON</a>　<a href="README.md">案内</a></p><p class="muted">原結果：<code>'+esc(result_path)+'</code><br>SHA256：<code>'+esc(result_sha)+'</code></p></main></body></html>'
    public=dict(sessions=scenes,splits=data.get('splits'),source_path=result_path,source_SHA256=result_sha,economic_source_SHA256=data['source_SHA256'],
        common_ranking=rank,main_ids=[r['id'] for r in rank],qualification_count=eligible,all40_positive_count=allpositive,cases=cases,
        account_scope='PAIR八政策。一場一組口座の合算。脚は独立戦略の成功とは呼ばない。',market_reads=0,financial_replay=0,API=0)
    readme='# 相対的な強さの継続と残差追尾の全セッション損益\n\n最初に['+HTML_NAME+']('+HTML_NAME+')を開いてください。8条件全ての全40場に、組の利益・損失・収支と日経/TOPIX脚それぞれの粗損益・実費用・収支を掲載します。\n\n'+caveat+'\n\n全40場は既知開発で、未知検証の成功とは呼びません。組の合計黒字だけで採用せず、中央値・最悪・上位3黒字除外・費用・未清算を併記します。\n\n[data.json](data.json)が公開小会計です。原結果 `'+result_path+'`、SHA256 `'+result_sha+'`。指定内容を一読し同bytes私有コピーを保全します。原市場・金融を再生しません。\n'
    return doc,public,readme


def generate(data: dict,output: Path,result_sha: str,result_path: str,fixture: bool=False) -> dict:
    """
    機能: 一読メモリの結果から、正式版と人工版を区別した新規出力を生成する。
    引数: data(dict)、output(Path)、result_sha/result_path(str)、fixture(bool)は内容と由来。
    返り値: dictはv2〜4互換の生成証跡。既存成果を上書きしない。
    """
    doc,public,readme=render(data,result_sha,result_path);assert not output.exists();output.mkdir(parents=True)
    payloads={HTML_NAME:doc.encode('utf8'),'data.json':encoded(public),'README.md':readme.encode('utf8')}
    for name,raw in payloads.items():(output/name).write_bytes(raw)
    proof=dict(passed=True,fixture=fixture,result_path=result_path,result_sha256=result_sha,report_sha256=sha(Path(__file__).read_bytes()),
        artifacts={name:sha(raw) for name,raw in payloads.items()},policies=8,common_ranking=8,baseline_controls=0,sessions=40,pair_sessions=320,
        main_ids=public['main_ids'],market_reads=0,financial_replay=0,API=0)
    (output/'生成証跡.json').write_bytes(encoded(proof));return proof


def main() -> None:
    """
    機能: 根担当指定SHAの完成元だけを一読し、私有コピーを保全して生成する。
    引数: CLI --result(Path)、--expected-sha256(str)、任意--output/--received(Path)、--fixture(bool)。
    返り値: None。実測読取は完成SHAの明示後だけ行う。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--result',type=Path,required=True);parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--output',type=Path,default=PRIVATE/'public');parser.add_argument('--received',type=Path,default=PRIVATE/'received');parser.add_argument('--fixture',action='store_true')
    args=parser.parse_args();expected=args.expected_sha256.lower()
    assert re.fullmatch('[0-9a-f]{64}',expected) and not args.output.exists() and not args.received.exists()
    raw=args.result.read_bytes();assert sha(raw)==expected,'指定SHA不一致。'
    args.received.mkdir(parents=True);copy=args.received/args.result.name;copy.write_bytes(raw)
    (args.received/'一読と同bytes保全.json').write_bytes(encoded(dict(source_path=str(args.result),source_SHA256=expected,own_copy=str(copy),own_copy_SHA256=sha(raw),source_reads=1,fixture=args.fixture,market_reads=0,financial_replay=0,API=0)))
    try:source_path=args.result.resolve().relative_to(ROOT).as_posix()
    except ValueError:source_path=str(args.result.resolve())
    print(json.dumps(generate(json.loads(raw.decode('utf8')),args.output,expected,source_path,args.fixture),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
