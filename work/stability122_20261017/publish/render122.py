"""完成した小会計だけから、固定三条件の短い比較HTMLを作成する。"""

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
NAME='途中利確なしと引け一括の比較.html'
OUTPUT=ROOT/'アルゴリズム調査/00122_途中利確なしと引け一括精算'/NAME
IDS=('G3_T5_RESET','HOLD_EARLY','HOLD_CLOSE_6M')
NAMES=('保存対照：5pt利確＋再起算','途中利確なし・通常返済','提案：途中利確なし・引け代理')
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
    機能: 通常実返済40と引け代理40及び旧40引用を分離して確認する。
    引数: data(dict)は根指定SHAの完成小会計又は完全合成。
    返り値: tuple[list[str],dict]は場順と条件別場会計。価格を補完しない。
    """
    assert data['passed'] is True
    sessions=data['sessions'];assert len(sessions)==len(set(sessions))==40 and EXAMPLE in sessions
    specs={s['id']:s for s in data['specs']}
    assert set(specs)==set(IDS[1:]) and len(data['specs'])==2
    assert specs[IDS[1]]['kind']=='EARLY' and specs[IDS[2]]['kind']=='CLOSE_PROXY'
    assert data['financial_accounts']==len(data['runs'])==80 and data['reused_baseline_accounts']==40
    assert len(data['baseline']['rows'])==40 and all(r['method']==IDS[0] for r in data['baseline']['rows'])
    assert data['original_market_reads']==data['API']==data['実注文']==0
    assert data['sources'] and all(isinstance(v,str) and len(v)==64 for v in data['sources'].values())
    rows={ident:{} for ident in IDS}
    for r in [*data['baseline']['rows'],*data['runs']]:
        ident=r['method'];scene=r['session']
        assert ident in rows and scene in sessions and scene not in rows[ident] and r['symbol']=='TOPIX'
        for key in ('profit','loss','net','cash','fees','long_net','short_net'):
            assert isinstance(r[key],(int,float)) and not isinstance(r[key],bool) and math.isfinite(r[key])
        for key in ('wins','losses','closed_lots','entries','unclosed','max_long','max_short'):
            assert isinstance(r[key],(int,float)) and not isinstance(r[key],bool)
            assert math.isfinite(r[key]) and int(r[key])==r[key] and r[key]>=0
        assert r['unclosed']==0 and r['entries']==r['closed_lots'] and r['wins']+r['losses']<=r['closed_lots']
        assert r['max_long']<=10 and r['max_short']<=10 and min(r['profit'],r['loss'],r['fees'])>=0
        assert math.isclose(r['profit']-r['loss'],r['net'],rel_tol=0,abs_tol=1e-5)
        assert math.isclose(r['net'],r['cash'],rel_tol=0,abs_tol=1e-5)
        assert math.isclose(r['long_net']+r['short_net'],r['net'],rel_tol=0,abs_tol=1e-5)
        if ident!=IDS[0]:
            c=r['context'];assert r['closed_lots']<=20
            if ident==IDS[1]:
                assert c['approximation'] is False and c['base_unclosed']==0
                assert r['regular_closed']==r['closed_lots'] and r['proxy_count']==0
            else:
                assert c['measured'] is True and c['approximation'] is True
                assert r['regular_closed']==0 and r['proxy_count']==r['closed_lots']==c['base_unclosed']
                for key in ('scheduled_time','reference_time','age_seconds','reference_last','reference_bid','reference_ask','last_price_reference_net'):
                    assert isinstance(c[key],(int,float)) and math.isfinite(c[key])
                assert 0<=c['age_seconds']<=360 and c['reference_time']<=c['scheduled_time']
                assert math.isclose(c['scheduled_time']-c['reference_time'],c['age_seconds'],rel_tol=0,abs_tol=1e-5)
                assert c['reference_last']>0 and 0<c['reference_bid']<=c['reference_ask']
                assert c['terminal_event']['scheduled_time']==c['scheduled_time']
        rows[ident][scene]=r
    assert all(len(r)==40 for r in rows.values())
    assert all(rows[IDS[1]][scene]['entries']==rows[IDS[2]][scene]['entries'] for scene in sessions)
    return sessions,rows


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
    機能: 利確あり保存対照・通常返済・引け代理の三条件を短く表示する。
    引数: data(dict)は完成内容、result_sha(str)は由来、fixture(bool)は完全合成か。
    返り値: tuple[str,dict]は暗色HTMLと固定三条件の小集計。引けを実約定にしない。
    """
    sessions,rows=validate(data);jst=timezone(timedelta(hours=9))
    metrics={ident:aggregate([rows[ident][scene] for scene in sessions]) for ident in IDS}
    examples=[];totals=[];daily=[]
    for ident,name in zip(IDS,NAMES):
        r=rows[ident][EXAMPLE];m=metrics[ident]
        examples.append([name,yen(r['profit']),yen(r['loss']),yen(r['net'],True)])
        totals.append([name,yen(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",yen(m['median'],True),yen(m['worst'],True),yen(m['top3_removed'],True)])
    for scene in sessions:
        r=rows[IDS[2]][scene];c=r['context']
        reference=datetime.fromtimestamp(c['reference_time'],jst).strftime('%H:%M:%S')
        daily.append([scene,*[yen(rows[ident][scene]['net'],True) for ident in IDS],yen(r['profit']),yen(r['loss']),f"{int(r['wins'])}/{int(r['losses'])}",reference,f"{c['age_seconds']:g}"])
    m=metrics[IDS[2]]
    footer=['全40場',*[yen(metrics[ident]['net'],True) for ident in IDS],yen(m['profit']),yen(m['loss']),f"{int(m['wins'])}/{int(m['losses'])}",'—','—']
    doc='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>途中利確なしと引け一括の比較</title><style>\nbody{margin:0;background:#0b1120;color:#e5edf8;font:16px/1.65 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:22px 16px}h1{font-size:25px}h2{font-size:20px;margin-top:26px}p,li{margin:8px 0}.note{background:#17283d;border-left:3px solid #e9c077;padding:10px 14px}.muted{color:#b1c0d4;font-size:13px}.wrap{overflow-x:auto;border:1px solid #34445a;margin:12px 0}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:14px}th,td{padding:8px 10px;border-bottom:1px solid #34445a;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1a2b44}caption{text-align:left;padding:9px;font-weight:bold}code{overflow-wrap:anywhere}@media(max-width:600px){main{padding:14px 10px}h1{font-size:22px}}\n</style></head><body><!--\n[コンポーネント概要]\nmainは固定三条件の説明・指定日比較・全40場です。\n引け代理精算は通常次原行の約定と分離し、実際の参照時計を同じ行に示します。\n.wrap内だけ表を横スクロールし、外部取得・条件選択・金融再生は行いません。\n--><main><h1>途中利確なしと引け一括の比較</h1>'
    if fixture:doc+='<p class="note">完全合成の表示確認です。実測成績ではありません。</p>'
    doc+='<p class="note"><strong>引け一括は実際の引け約定ではなく、15:45／06:00の直前6分内で最後に観測したBBOによる代理精算です。</strong></p>'
    doc+='<ul><li><b>保存対照：</b>3・6・9…pt新規、5ptの利益追尾と利確後の空き段再起算。旧40会計を再利用。</li><li><b>通常返済：</b>同じ3・6・9…pt新規で途中利確・再起算を行わず、15:20／05:40から次正常原行で返済。</li><li><b>引け代理：</b>途中利確・再起算なし。引け前の参照BBOで全玉を代理会計し、実返済原行は作らない。</li></ul>'
    doc+='<p>TOPIXミニだけ、各方向10枚・合計最大20枚。新規締切は比較元と同じ15:00／05:20。途中の利益玉を外さず、損失玉も終了会計に含めます。</p>'
    doc+='<h2>2026年9月24日デイ</h2>'+table(['条件','利益円','損失円','収支円'],examples,'通常返済と引け代理の違いを分離した3比較。')
    last_values=[rows[IDS[2]][scene]['context']['last_price_reference_net'] for scene in sessions]
    doc+='<p class="muted"><strong>同じ保有玉を最後のLastで評価すると、9/24は'+yen(rows[IDS[2]][EXAMPLE]['context']['last_price_reference_net'],True)+'円、全40場は'+yen(sum(last_values),True)+'円（'+str(sum(v>0 for v in last_values))+'黒'+str(sum(v<0 for v in last_values))+'赤）。実引け約定ではなく、追加の戦略・口座ではありません。</strong></p>'
    doc+='<h2>全40場の比較</h2>'+table(['条件','合計収支円','黒／赤／無','中央値円','最悪場収支円','上位3黒字除外円'],totals,'同じ既知40場。無取引と取引あり零収支は勝ちに数えない。')
    doc+='<h2>全セッション</h2>'+table(['セッション','保存対照net円','通常返済net円','引け代理net円','引け代理利益円','引け代理損失円','勝／負枚数','代理参照JST','引けまで秒'],daily,'末尾2列は引け代理の参照時刻。通常返済の約定時刻ではない。',footer)
    doc+='<p class="muted">利益・損失は1枚玉の費用後net正負、勝／負枚数もその正負です。一注文41円・往復82円は内数で再控除しません。代理参照の時差を表に残し、過去BBOを予定引け時刻の実約定として扱いません。</p>'
    doc+='<p class="muted">新規は判断後の正常BBOで買ask／売bid、発注・最初の到来気配ともspread1pt以内、不利0.5pt以内の一回判定。通常返済は後の正常原行、引け代理は別台帳です。実小型板・待ち順位・真受信順は未観測です。</p>'
    doc+='<p class="muted">結果前に固定した新2条件80会計と旧40引用。同じ既知40場の開発で将来の成功証明ではなく、結果で条件を選び直しません。生成器の原板読取・NPZ読取・API・実注文・金融再生は0。</p>'
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
        metrics=metrics,financial_accounts=80,reused_baseline_accounts=40,fixture=False,
        market_reads=0,NPZ_reads=0,financial_replay=0,registry_reads=0,API=0,実注文=0)
    args.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,HTML_SHA256=digest(result),proof=str(args.proof)),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
