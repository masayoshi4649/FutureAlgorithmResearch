"""完成した小会計だけから、固定十九条件の短い比較HTMLを作成する。"""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import statistics
from datetime import datetime,timedelta,timezone


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
NAME='途中利確なしの新規間隔比較.html'
OUTPUT=ROOT/'アルゴリズム調査/00123_途中利確なしの新規間隔比較'/NAME
BASELINE='I3_G3'
GAPS=(1,2,3,4,5,6,8,10,12,15)

EXAMPLE='2026-09-24_Day'


def digest(payload: bytes) -> str:
    """
    機能: 完成結果・会計監査・HTMLの同一内容を識別する。
    引数: payload(bytes)は既に読んだ内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def esc(value: object) -> str:
    """
    機能: 保存値をHTML本文や属性へ安全に表示する。
    引数: value(object)は表示する文字列又は数値。
    返り値: strは引用符を含めて保護した文字列。
    """
    return html.escape(str(value),quote=True)


def yen(value: float, signed: bool=False) -> str:
    """
    機能: 損失絶対額と符号付き収支を混同しない円表示を作る。
    引数: value(float)は円額、signed(bool)は正数の符号を明示するか。
    返り値: strは桁区切りした円額。
    """
    return '0' if abs(value)<1e-7 else format(value,'+,.0f' if signed else ',.0f')


def contains(value: object, expected: str) -> bool:
    """
    機能: 独立監査証跡が今回の完成結果SHAを明示しているか確認する。
    引数: value(object)はJSON互換値、expected(str)は根指定結果SHA。
    返り値: boolは値の完全一致が含まれるか。
    """
    if isinstance(value,dict):return any(contains(v,expected) for v in value.values())
    if isinstance(value,list):return any(contains(v,expected) for v in value)
    return isinstance(value,str) and value==expected


def validate(data: dict) -> tuple[list[str],dict,dict]:
    """
    機能: 固定十九設定・新720会計・旧40引用と代理精算資格を確認する。
    引数: data(dict)は指定SHAの完成内容又は完全合成。
    返り値: tuple[list[str],dict,dict]は場順・仕様順・表示用の条件別会計。
        旧methodの読替えはローカルcopyだけへ行い、原結果は変更しない。
    """
    assert data['passed'] is True
    sessions=data['sessions'];assert len(sessions)==len(set(sessions))==40
    specs={s['id']:s for s in data['specs']}
    expected=[(3,g) for g in GAPS]+[(g,g) for g in GAPS if g!=3]
    assert len(specs)==len(data['specs'])==19
    assert [(s['initial'],s['spacing']) for s in specs.values()]==expected
    assert list(specs)==[f'I{i}_G{g}' for i,g in expected]
    assert all(s['reused'] is (ident==BASELINE) for ident,s in specs.items())
    assert data['financial_accounts']==len(data['runs'])==720 and data['reused_baseline_accounts']==40
    baseline=data['baseline']
    assert baseline['source_method']=='HOLD_CLOSE_6M' and baseline['mapped_method']==BASELINE
    assert len(baseline['rows'])==40 and all(r['method']=='HOLD_CLOSE_6M' for r in baseline['rows'])
    assert all(r['method']!=BASELINE for r in data['runs'])
    assert data['original_market_reads']==data['API']==data['実注文']==0
    assert data['sources'] and all(isinstance(v,str) and len(v)==64 for v in data['sources'].values())
    rows={ident:{} for ident in specs}
    mapped=[dict(r,method=BASELINE) for r in baseline['rows']]
    for r in [*mapped,*data['runs']]:
        ident=r['method'];scene=r['session']
        assert ident in rows and scene in sessions and scene not in rows[ident] and r['symbol']=='TOPIX'
        for key in ('profit','loss','net','cash','fees','long_net','short_net'):
            assert isinstance(r[key],(int,float)) and not isinstance(r[key],bool) and math.isfinite(r[key])
        for key in ('wins','losses','closed_lots','entries','unclosed','max_long','max_short'):
            assert isinstance(r[key],(int,float)) and not isinstance(r[key],bool)
            assert math.isfinite(r[key]) and int(r[key])==r[key] and r[key]>=0
        assert r['unclosed']==0 and r['entries']==r['closed_lots']<=20
        assert r['wins']+r['losses']<=r['closed_lots']
        assert r['max_long']<=10 and r['max_short']<=10 and min(r['profit'],r['loss'],r['fees'])>=0
        assert math.isclose(r['profit']-r['loss'],r['net'],rel_tol=0,abs_tol=1e-5)
        assert math.isclose(r['net'],r['cash'],rel_tol=0,abs_tol=1e-5)
        assert math.isclose(r['long_net']+r['short_net'],r['net'],rel_tol=0,abs_tol=1e-5)
        assert math.isclose(r['fees'],82*r['closed_lots'],rel_tol=0,abs_tol=1e-5)
        if r['entries']==0:assert r['net']==r['profit']==r['loss']==r['fees']==0
        c=r['context']
        assert c['measured'] is True and c['approximation'] is True
        assert r['regular_closed']==0 and r['proxy_count']==r['closed_lots']==c['base_unclosed']
        for key in ('scheduled_time','reference_time','age_seconds','reference_last','reference_bid','reference_ask','last_price_reference_net'):
            assert isinstance(c[key],(int,float)) and math.isfinite(c[key])
        assert 0<=c['age_seconds']<=360 and c['reference_time']<=c['scheduled_time']
        assert math.isclose(c['scheduled_time']-c['reference_time'],c['age_seconds'],rel_tol=0,abs_tol=1e-5)
        assert c['reference_last']>0 and 0<c['reference_bid']<=c['reference_ask']
        rows[ident][scene]=r
    assert all(len(r)==40 for r in rows.values())
    return sessions,specs,rows


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 無取引を勝ちに数えず、四十場の収支と安定性を足し上げる。
    引数: rows(list[dict])は一条件の固定40場。
    返り値: dictはP/L、黒赤無零、中央値、最悪場、上位3黒字除外。
    """
    net=[r['net'] for r in rows]
    positive=[r['net'] for r in rows if r['entries']>0 and r['net']>1e-7]
    red=sum(r['entries']>0 and r['net']<-1e-7 for r in rows)
    inactive=sum(r['entries']==0 for r in rows)
    flat=len(rows)-len(positive)-red-inactive
    total={key:sum(r[key] for r in rows) for key in ('profit','loss','net','fees','wins','losses','closed_lots')}
    total.update(black=len(positive),red=red,inactive=inactive,flat=flat,median=statistics.median(net),
        worst=min(net),top3_removed=sum(net)-sum(sorted(positive,reverse=True)[:3]))
    return total


def table(headers: list[str], rows: list[list[str]], caption: str, footer: list[str]|None=None) -> str:
    """
    機能: 狭い画面で表だけ横スクロールする静的比較表を作る。
    引数: headers(list[str])は見出し、rows(list[list[str]])は本文、
          caption(str)は表題、footer(list[str]|None)は合計行。
    返り値: strはHTML。値を再計算するJavaScriptは使わない。
    """
    body=''.join('<tr>'+''.join('<th>'+esc(v)+'</th>' if i==0 else '<td>'+esc(v)+'</td>' for i,v in enumerate(row))+'</tr>' for row in rows)
    foot='' if footer is None else '<tfoot><tr>'+''.join('<th>'+esc(v)+'</th>' if i==0 else '<td>'+esc(v)+'</td>' for i,v in enumerate(footer))+'</tr></tfoot>'
    return '<div class="wrap"><table><caption>'+esc(caption)+'</caption><thead><tr>'+''.join('<th>'+esc(v)+'</th>' for v in headers)+'</tr></thead><tbody>'+body+'</tbody>'+foot+'</table></div>'


def render(data: dict, result_sha: str, fixture: bool=False) -> tuple[str,dict]:
    """
    機能: 固定順十九一覧と基準既定の全40場切替を一つの暗色HTMLへまとめる。
    引数: data(dict)は完成内容、result_sha(str)は由来、fixture(bool)は完全合成か。
    返り値: tuple[str,dict]はHTMLと十九条件の小集計。結果で条件を選び直さない。
    """
    sessions,specs,rows=validate(data);jst=timezone(timedelta(hours=9));metrics={}
    for ident in specs:
        rr=[rows[ident][scene] for scene in sessions];m=aggregate(rr)
        m['last_reference_net']=sum(r['context']['last_price_reference_net'] for r in rr)
        metrics[ident]=m
    overview=[];options=[];panels=[]
    for ident,spec in specs.items():
        m=metrics[ident];label=ident+('（保存）' if spec['reused'] else '')
        count=f"{m['black']}/{m['red']}/{m['inactive']}"+(f"・零{m['flat']}" if m['flat'] else '')
        overview.append([label,f"{spec['initial']:g}",f"{spec['spacing']:g}",count,yen(m['net'],True),yen(m['median'],True),yen(max(0,-m['worst'])),str(int(m['closed_lots']))])
        selected=' selected' if ident==BASELINE else ''
        options.append('<option value="'+esc(ident)+'"'+selected+'>'+esc(spec['name']+('（保存基準）' if spec['reused'] else ''))+'</option>')
        daily=[]
        for scene in sessions:
            r=rows[ident][scene];base=rows[BASELINE][scene];c=r['context']
            clock=datetime.fromtimestamp(c['reference_time'],jst).strftime('%H:%M:%S')
            zero=int(r['closed_lots']-r['wins']-r['losses'])
            daily.append([scene,yen(r['profit']),yen(r['loss']),yen(r['net'],True),str(int(r['closed_lots'])),f"{int(r['wins'])}/{int(r['losses'])}/{zero}",yen(base['net'],True),yen(r['net']-base['net'],True),clock,f"{c['age_seconds']:g}"])
        footer=['全40場',yen(m['profit']),yen(m['loss']),yen(m['net'],True),str(int(m['closed_lots'])),f"{int(m['wins'])}/{int(m['losses'])}/{int(m['closed_lots']-m['wins']-m['losses'])}",yen(metrics[BASELINE]['net'],True) if BASELINE in metrics else yen(sum(rows[BASELINE][scene]['net'] for scene in sessions),True),yen(m['net']-sum(rows[BASELINE][scene]['net'] for scene in sessions),True),'—','—']
        share='—（未定義）' if m['profit']+m['loss']==0 else f"{m['profit']/(m['profit']+m['loss'])*100:.2f}%"
        hidden='' if ident==BASELINE else ' hidden'
        detail='<p>利益 '+yen(m['profit'])+'円／損失 '+yen(m['loss'])+'円、利益割合 '+share+'。上位3黒字場除外 '+yen(m['top3_removed'],True)+'円、手数料 '+yen(m['fees'])+'円。</p>'
        detail+='<p class="muted">無取引 '+str(m['inactive'])+'場／取引あり零収支 '+str(m['flat'])+'場。同じ玉をLastで評価した感応度 '+yen(m['last_reference_net'],True)+'円。実引け約定や追加条件の成績ではありません。</p>'
        panels.append('<section class="case" id="case-'+esc(ident)+'" data-id="'+esc(ident)+'"'+hidden+'><h3>'+esc(spec['name'])+' <small>'+esc(ident)+'</small></h3>'+detail+table(['セッション','利益円','損失円','収支円','枚数','勝／負／零枚数','基準3/3円','基準差円','参照JST','引けまで秒'],daily,'本条件と保存基準の同じ40場。参照時計は引け代理の実観測時刻。',footer)+'</section>')
    if fixture:lead='完全合成の表示確認です。実測成績ではありません。'
    elif all(m['net']<0 for m in metrics.values()):lead='19条件すべて累計赤字。間隔変更だけでは安定黒字に至りませんでした。'
    else:lead='固定19条件を比較しました。累計収支だけでなく各場と参加枚数を確認してください。'
    doc='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>途中利確なしの新規間隔比較</title><style>\nbody{margin:0;background:#0b1120;color:#e5edf8;font:15px/1.65 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:22px 16px}h1{font-size:25px}h2{font-size:20px;margin-top:25px}h3{font-size:18px}p{margin:9px 0}.note{background:#17283d;border-left:3px solid #e9c077;padding:11px 14px}.muted,small{color:#b1c0d4;font-size:13px}.wrap{overflow-x:auto;max-width:100%;border:1px solid #34445a;margin:12px 0}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid #34445a;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}caption{text-align:left;padding:9px;font-weight:bold}select{max-width:100%;font:inherit;background:#17283d;color:#e5edf8;padding:9px;border:1px solid #64748b;border-radius:5px}code{overflow-wrap:anywhere}[hidden]{display:none!important}@media(max-width:600px){main{padding:14px 10px}h1{font-size:22px}}\n</style></head><body><!--\n[コンポーネント概要]\n#overviewは結果前の固定順十九条件です。無取引と活動零収支を区別します。\n#conditionは表示だけを選び、初期は保存基準I3_G3です。\n.caseは各条件の全40場と基準差で、外部取得や金融再計算は行いません。\n--><main><h1>途中利確なしの新規間隔比較</h1>'
    doc+='<p class="note"><strong>'+esc(lead)+'</strong></p><p>初回3pt固定（3＋j×間隔）と、初回も間隔と同じ（1・2・3…段×間隔）の二系統。3/3重複は統合し、保存40会計と新18条件720会計を比較します。TOPIXミニの各方向上限10枚、途中利確・再起算なし、新規締切15:00／05:20。</p>'
    doc+='<p class="muted"><strong>全条件は引け15:45／06:00の直前6分内の最終BBOによる代理精算で、実引け約定ではありません。</strong> 幅を広げると無取引や枚数減も生じます。損失額の減少だけを収益源の改善としません。</p>'
    doc+='<section id="overview"><h2>固定19条件</h2>'+table(['条件','初回pt','間隔pt','黒／赤／無','40場収支円','中央値円','最大赤字円','累計枚数'],overview,'並びは固定。最大赤字は最悪赤字場の絶対額、零は取引あり零収支。')+'</section>'
    doc+='<h2>条件別の全40場</h2><label for="condition">表示する条件：</label> <select id="condition">'+''.join(options)+'</select>'+''.join(panels)
    doc+='<p class="muted">利益・損失と勝／負枚数は1枚玉の費用後net正負。料82円/玉は内数で再控除しません。利益割合は利益÷（利益＋損失）、両方0なら未定義。無取引を勝ちに数えず、活動零収支も別です。初回・間隔・19順は結果前に固定し、各場の結果で条件を選ぶ手法ではありません。</p>'
    doc+='<p class="muted">正常Lastの動く極値を信号に使い、後の正常BBOで買ask／売bid。新規はspread1pt以内・不利0.5pt以内の一回判定。ラージ気配代理で実ミニ板・受信順は未観測。同じ既知40場の開発で19設定は独立標本ではありません。生成器の原板・NPZ・API・実注文・金融再生は0。</p>'
    doc+='<details><summary>完成結果と固定源</summary><p><code>'+esc(result_sha)+'</code></p><ul>'+''.join('<li><code>'+esc(path)+' '+esc(sha)+'</code></li>' for path,sha in data['sources'].items())+'</ul></details></main>'
    doc+="<noscript><style>.case[hidden]{display:block!important}</style>JavaScript無効時は全条件を表示します。</noscript><script>\n/**\n * 機能: 保存済み十九表の表示だけを選択する。\n * 引数: なし。#conditionの値は固定した条件ID。\n * 返り値: なし。外部通信や売買計算は行わない。\n */\nfunction showCondition(){\n const chosen=document.getElementById('condition').value;\n for(const panel of document.querySelectorAll('.case'))panel.hidden=panel.dataset.id!==chosen;\n}\ndocument.getElementById('condition').addEventListener('change',showCondition);\nshowCondition();\n</script></body></html>"
    return doc,metrics


def main() -> None:
    """
    機能: 根指定の完成SHAと独立会計合格を確認して一読保全後に公開する。
    引数: CLIのresult/expected-sha256/audit/audit-sha256は完成資料、
          output/proofはHTMLと私有生成証跡の未使用保存先。
    返り値: None。README・案内・別チャート・元結果を編集しない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--audit-sha256',required=True)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--proof',type=Path,default=HERE/'正式表示の生成証跡.json')
    args=parser.parse_args();expected=args.expected_sha256.lower()
    assert len(expected)==64 and set(expected)<=set('0123456789abcdef')
    assert not args.output.exists() and not args.proof.exists() and not (HERE/'received').exists()
    auditraw=args.audit.read_bytes();assert digest(auditraw)==args.audit_sha256.lower()
    audit=json.loads(auditraw);assert audit['passed'] is True and contains(audit,expected)
    payload=args.result.read_bytes();assert digest(payload)==expected
    received=HERE/'received';received.mkdir();(received/args.result.name).write_bytes(payload)
    doc,metrics=render(json.loads(payload),expected)
    args.output.parent.mkdir(parents=True,exist_ok=True);result=doc.encode('utf8');args.output.write_bytes(result)
    proof=dict(passed=True,result_path=str(args.result),result_sha256=expected,source_reads=1,
        audit=dict(path=str(args.audit),SHA256=digest(auditraw)),
        output=dict(path=str(args.output),SHA256=digest(result)),report_sha256=digest(Path(__file__).read_bytes()),
        metrics=metrics,financial_accounts=720,reused_baseline_accounts=40,fixture=False,
        market_reads=0,NPZ_reads=0,financial_replay=0,registry_reads=0,API=0,実注文=0)
    args.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,HTML_SHA256=digest(result),proof=str(args.proof)),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
