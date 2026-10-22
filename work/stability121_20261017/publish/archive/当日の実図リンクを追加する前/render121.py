"""完成した小会計だけから、固定四条件の短い比較HTMLを作成する。"""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
NAME='三ポイント間隔と五ポイント追尾の比較.html'
OUTPUT=ROOT/'アルゴリズム調査/00121_三ポイント間隔と五ポイント追尾'/NAME
IDS=('ROTATE_S2_T1','G1_T5_SLOT','G3_T5_SLOT','G3_T5_RESET')
NAMES=('保存対照：旧間隔・1pt追尾','旧間隔・5pt追尾','3pt間隔・固定枠','提案：3pt間隔・利確後再起算')
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


def validate(data: dict) -> tuple[list[str],dict]:
    """
    機能: 新120会計と旧40引用を分離し、全40場の固定四条件を確認する。
    引数: data(dict)は指定SHAの完成小会計又は完全合成。
    返り値: tuple[list[str],dict]は場順と条件別場会計。金融計算は行わない。
    """
    assert data['passed'] is True
    sessions=data['sessions'];assert len(sessions)==len(set(sessions))==40 and EXAMPLE in sessions
    specs={s['id']:s for s in data['specs']}
    assert set(specs)==set(IDS[1:]) and len(data['specs'])==3
    for ident,spacing,reset in ((IDS[1],1.,False),(IDS[2],3.,False),(IDS[3],3.,True)):
        assert specs[ident]['spacing']==spacing and specs[ident]['trail']==5.
        assert specs[ident]['reset_after_profit'] is reset
    assert data['financial_accounts']==len(data['runs'])==120 and data['reused_baseline_accounts']==40
    assert data['baseline']['method']==IDS[0] and len(data['baseline']['rows'])==40
    assert data['original_market_reads']==data['API']==data['実注文']==0
    assert data['sources'] and all(isinstance(v,str) and len(v)==64 for v in data['sources'].values())
    table={ident:{} for ident in IDS}
    for row in [*data['baseline']['rows'],*data['runs']]:
        ident=row['method'];scene=row['session']
        assert ident in table and scene in sessions and scene not in table[ident] and row['symbol']=='TOPIX'
        for key in ('profit','loss','net','fees','cash'):
            assert isinstance(row[key],(int,float)) and not isinstance(row[key],bool) and math.isfinite(row[key])
        for key in ('wins','losses','closed_lots','entries','unclosed','max_long','max_short'):
            assert isinstance(row[key],(int,float)) and not isinstance(row[key],bool)
            assert math.isfinite(row[key]) and int(row[key])==row[key] and row[key]>=0
        assert min(row['profit'],row['loss'],row['fees'])>=0 and row['unclosed']==0
        assert row['entries']==row['closed_lots'] and row['wins']+row['losses']<=row['closed_lots']
        assert row['max_long']<=10 and row['max_short']<=10
        assert math.isclose(row['profit']-row['loss'],row['net'],rel_tol=0,abs_tol=1e-5)
        assert math.isclose(row['net'],row['cash'],rel_tol=0,abs_tol=1e-5)
        table[ident][scene]=row
    assert all(len(rows)==40 for rows in table.values())
    return sessions,table


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
    機能: 条件を結果から選び直さず、固定四比較を短い暗色HTMLへ並べる。
    引数: data(dict)は完成内容、result_sha(str)は由来、fixture(bool)は合成か。
    返り値: tuple[str,dict]はHTMLと同時に保存する固定四条件の小集計。
    """
    sessions,rows=validate(data)
    metrics={ident:aggregate([rows[ident][s] for s in sessions]) for ident in IDS}
    examples=[];totals=[];daily=[]
    for ident,name in zip(IDS,NAMES):
        row=rows[ident][EXAMPLE]
        examples.append([name,yen(row['profit']),yen(row['loss']),yen(row['net'],True)])
        m=metrics[ident]
        totals.append([name,yen(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",yen(m['median'],True),yen(m['worst'],True),yen(m['top3_removed'],True),yen(m['fees'])])
    for scene in sessions:
        proposal=rows[IDS[3]][scene]
        daily.append([scene,*[yen(rows[ident][scene]['net'],True) for ident in IDS],yen(proposal['profit']),yen(proposal['loss']),f"{int(proposal['wins'])}/{int(proposal['losses'])}"])
    pm=metrics[IDS[3]]
    footer=['全40場',*[yen(metrics[ident]['net'],True) for ident in IDS],yen(pm['profit']),yen(pm['loss']),f"{int(pm['wins'])}/{int(pm['losses'])}"]
    headline='完全合成の表示確認です。実測成績ではありません。' if fixture else '固定した4条件を比較しました。提案の成否は全40場の収支と赤字場を併せて確認してください。'
    descriptions=[
        '<b>保存対照：</b>空き枠のLast極値から3・4・5…pt、個別利益の追尾幅1pt。旧40会計を再利用。',
        '<b>利確幅だけ変更：</b>同じ3・4・5…ptの枠で、追尾幅を5ptに変更。',
        '<b>段間隔だけ変更：</b>3・6・9…ptで新規し、5pt追尾。返済した固定枠を再利用。',
        '<b>提案：</b>同じ3・6・9…pt／5pt追尾。利益追尾返済が実約定後も黒字なら、その方向の空き段を現在Lastから3・6・9…ptへ再割当。保有玉と反対側は維持し、同原行で同方向へ再新規しない。']
    doc='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>三ポイント間隔と五ポイント追尾の比較</title><style>
body{margin:0;background:#0b1120;color:#e5edf8;font:16px/1.65 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:22px 16px}h1{font-size:25px}h2{font-size:20px;margin-top:26px}p,li{margin:8px 0}.note{background:#17283d;border-left:3px solid #e9c077;padding:10px 14px}.muted{color:#b1c0d4;font-size:13px}.wrap{overflow-x:auto;border:1px solid #34445a;margin:12px 0}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:14px}th,td{padding:8px 10px;border-bottom:1px solid #34445a;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}caption{text-align:left;padding:9px;font-weight:bold}code{overflow-wrap:anywhere}@media(max-width:600px){main{padding:14px 10px}h1{font-size:22px}}
</style></head><body><!--
[コンポーネント概要]
mainは固定四条件の短い説明・当日比較・全40場の表です。
.wrap内だけ表を横スクロールし、損失は正の絶対額、収支は符号付きで表示します。
読み込み後の外部取得・条件選択・金融再生はありません。
--><main><h1>三ポイント間隔と五ポイント追尾の比較</h1>'''
    doc+='<p class="note">'+esc(headline)+'</p><ul>'+''.join('<li>'+s+'</li>' for s in descriptions)+'</ul>'
    doc+='<p>TOPIXミニ、片方向上限10枚。買い・売りは上下対称。費用後の玉別清算純益peakが正になった後、最高値から5pt相当戻り、現在純益が正なら次正常気配で返済します。独立損切りはなく、負け玉も場末返済へ含めます。</p>'
    doc+='<h2>2026年9月24日デイ</h2>'+table(['条件','利益円','損失円','収支円'],examples,'指定日の4条件。利益・損失は費用後の完結1枚玉を集計。')
    doc+='<h2>全40場の比較</h2>'+table(['条件','合計収支円','黒／赤／無','中央値円','最悪場収支円','上位3黒字除外円','手数料円'],totals,'同じ40場。取引あり零収支は黒字・無取引へ加えない。')
    doc+='<h2>全セッション</h2>'+table(['セッション','保存対照 net円','旧間隔5追尾 net円','3間隔固定枠 net円','提案RESET net円','提案利益円','提案損失円','提案勝／負枚数'],daily,'全40場の4条件と提案の玉別P/L・枚数。',footer)
    doc+='<p class="muted">利益・損失には一注文41円ずつ、往復82円の手数料を含むため、料を再度差し引きません。勝／負枚数は完結1枚玉の費用後net正負です。無取引や零損益を勝ちに数えません。末尾未返済0を確認した完成結果だけ表示します。</p>'
    doc+='<p class="muted">Lastの極値は信号用で、約定は判断より後の正常BBOの買ask／売bid。新規は判断・到来時spread1pt以内、判断の反対気配から不利0.5pt以内の一回判定です。追尾判断後の値飛び損失も計上します。Day15:00新規締切／15:20返済判断、Night05:20／05:40。</p>'
    doc+='<p class="muted">源と3設定は結果前に固定。新3条件120会計と保存40会計を区別し、結果から手法を選び直していません。同じ既知40場の開発で、将来の安定黒字を保証しません。ラージBBOによるミニ代理で、実小型板・待ち順位・真受信順は未観測。生成器の原板読取・API・実注文・金融再生は0です。</p>'
    doc+='<details><summary>完成結果と固定源の指紋</summary><p><code>'+esc(result_sha)+'</code></p><ul>'+''.join('<li><code>'+esc(path)+' '+esc(sha)+'</code></li>' for path,sha in data['sources'].items())+'</ul></details></main></body></html>'
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
        metrics=metrics,financial_accounts=120,reused_baseline_accounts=40,fixture=False,
        market_reads=0,NPZ_reads=0,financial_replay=0,registry_reads=0,API=0,実注文=0)
    args.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,HTML_SHA256=digest(result),proof=str(args.proof)),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
