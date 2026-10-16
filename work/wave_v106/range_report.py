"""新しい価格往復入口24条件と保存C対照を、短い説明と全場損益へ整理する。"""

import hashlib
import html
import json
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=HERE/'range_price/finance/results.json'
PUBLIC=ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def summary(rows: list[dict], symbol: str) -> dict:
    """
    機能: 商品別の金額、活動、中央値と突出利益除外を保存会計だけから求める。
    引数: rows(list[dict])、symbol(str)は33場の商品会計と対象。
    返り値: dictは再集計。金融再生や将来の正答率を計算しない。
    """
    values=[row for row in rows if row['symbol']==symbol];assert len(values)==33
    profits=sum(row['profit'] for row in values);losses=sum(row['loss'] for row in values)
    nets=[row['net'] for row in values];wins=sum(row['winning_campaigns'] for row in values);losers=sum(row['losing_campaigns'] for row in values)
    ordered=sorted(nets,reverse=True);active=sum(row['campaigns']>0 for row in values)
    result=dict(profit=profits,loss=losses,net=profits-losses,profit_share=profits/(profits+losses) if profits+losses else None,
        pf=profits/losses if losses else None,median=statistics.median(nets),active=active,
        positive=sum(value>1e-5 for value in nets),negative=sum(value < -1e-5 for value in nets),
        no_trade=33-active,top3_excluded=sum(nets)-sum(ordered[:3]),best_excluded=sum(nets)-ordered[0],
        worst=min(nets),winning_lots=sum(row['winning_lots'] for row in values),losing_lots=sum(row['losing_lots'] for row in values),
        campaigns=sum(row['campaigns'] for row in values),average_win=profits/wins if wins else None,average_loss=losses/losers if losers else None)
    assert abs(result['net']-sum(nets))<1e-4
    return result


def number(value: float | None, digits: int=0) -> str:
    """
    機能: 金額や割合を未定義と負のゼロなしで表示する。
    引数: value(float | None)、digits(int)は数値と表示桁。
    返り値: strはHTMLに安全な数字。
    """
    if value is None:return '—'
    if abs(value)<.5*10**(-digits):value=0
    return f'{value:,.{digits}f}'


def cell(value: float, loss: bool=False) -> str:
    """
    機能: 収支の符号を暗背景で読める色へ対応させる。
    引数: value(float)、loss(bool)は会計額と正数で表示する損失欄の指定。
    返り値: strは表セルHTML。
    """
    return '<td class="'+('negative' if loss and value>0 else 'positive' if value>0 else 'negative' if value<0 else '')+'">'+number(value)+'</td>'


def description(config: dict | None) -> str:
    """
    機能: 新往復入口と追従の選択を入口・途中・出口へ短く説明する。
    引数: config(dict | None)は固定条件。Noneは保存対照の派生。
    返り値: strは三つの簡潔な説明。
    """
    if config is None:
        return '<p><b>入口：</b>日経とTOPIXの直近5分が同方向へ0.02%以上動き、板の進行入口も一致した時に入る。</p><p><b>途中：</b>方向の一致が消えただけでは降りず、最初の停止線を保つ。</p><p><b>出口：</b>支持4呼値と始値0.1%の保険、始値0.4%の追尾、または場内期限で返済。保存した全量注文を正確に半量へ写した比較で、新たな再生ではない。</p>'
    auto=config['mode']=='AUTO';margin=config['margin_ticks'];er=config['range_er'];entry=config['range_entry']
    lead='両市場の往復時は反発型、それ以外の同方向進行時は板の追従型を自動選択する。' if auto else '両市場が往復している時だけ、価格帯の端から中心への反発を取る。'
    order='判断後の次の正常気配で入る。' if entry=='MARKET' else '買いは買気配、売りは売気配の指値を置き、公開後の最初の到達で入る。'
    return f'<p><b>入口：</b>{lead}直近5分の6点効率が双方{er:g}以下の時、幅4呼値以上の帯の外側25%内で両気配が1呼値反発したら候補。手数料後の中心までの利幅が予定損失の1.25倍以上を要求。{order}</p><p><b>途中：</b>未約定の反発指値は、両市場が進行型へ変わるか固定停止線を破れば取消。約定後は固定線を保つ。</p><p><b>出口：</b>反発型は当時の中心で利確、当時の帯の外{margin}呼値で損切り。どちらも条件成立後の次の正常気配で返済。'+('追従型は基準の広い追尾を使う。' if auto else '')+'全玉を場内返済。</p>'


def run() -> None:
    """
    機能: 保存済み24条件の全33場会計を検算し、ダークHTMLと閲覧会計を更新する。
    引数: なし。完成金融資料を読む。
    返り値: None。取引再生、板再読、API取得は行わない。
    """
    raw=SOURCE.read_bytes();source=json.loads(raw);assert source['全合格'] and source['account_count']==1584
    sessions=source['sessions'];assert len(sessions)==33
    configs={config['id']:config for config in source['configs']};cases={}
    for ident,case in source['cases'].items():
        assert len(case['rows'])==66
        cases[ident]=dict(config=configs[ident],rows=case['rows'],summary={s:summary(case['rows'],s) for s in ('TOPIX','NK225')})
    for er,case in source['derived_C_comparators'].items():
        ident=f'C_ONLY_B2_ER{int(float(er)*100)}_B4_半量派生'
        cases[ident]=dict(config=None,rows=case['rows'],derived=True,summary={s:summary(case['rows'],s) for s in ('TOPIX','NK225')})
    target=sum(all(case['summary'][symbol]['positive']==33 and (case['summary'][symbol]['profit_share'] or 0)>=.8 for symbol in ('TOPIX','NK225')) for ident,case in cases.items() if ident in configs)
    compare=['AUTO_ER40_M2_LIMIT','R_ONLY_ER40_M2_LIMIT','C_ONLY_B2_ER40_B4_半量派生']
    head=[]
    for ident in compare:
        for symbol in ('TOPIX','NK225'):
            result=cases[ident]['summary'][symbol]
            head.append('<tr><td>'+html.escape(ident)+'</td><td>'+symbol+'</td>'+cell(result['net'])+f'<td>{result["positive"]}/{result["negative"]}/{result["no_trade"]}</td><td>'+number((result['profit_share'] or 0)*100,1)+'%</td>'+cell(result['median'])+cell(result['top3_excluded'])+cell(result['worst'])+'</tr>')
    options=[];sections=[]
    for ident,case in cases.items():
        options.append('<option value="'+html.escape(ident,quote=True)+'">'+html.escape(ident)+'</option>')
        index={(row['session'],row['symbol']):row for row in case['rows']};assert len(index)==66
        body=[]
        for session in sessions:
            row='<tr><td>'+session.replace('_Day',' デイ').replace('_Night',' ナイト')+'</td>'
            for symbol in ('TOPIX','NK225'):
                values=index[session,symbol]
                row+=cell(values['profit'])+cell(values['loss'],True)+cell(values['net'])+'<td>'+number(values['winning_lots'])+'</td><td>'+number(values['losing_lots'])+'</td>'
            body.append(row+'</tr>')
        total='<tr class="total"><td>全33合計</td>'
        for symbol in ('TOPIX','NK225'):
            s=case['summary'][symbol];total+=cell(s['profit'])+cell(s['loss'],True)+cell(s['net'])+'<td>'+number(s['winning_lots'])+'</td><td>'+number(s['losing_lots'])+'</td>'
        body.append(total+'</tr>')
        sections.append('<section data-case="'+html.escape(ident,quote=True)+'" hidden><h2>'+html.escape(ident)+'</h2>'+description(case['config'])+'<div class="scroll"><table><thead><tr><th rowspan="2">セッション</th><th colspan="5">TOPIXミニ：5枚・上限10枚</th><th colspan="5">日経マイクロ：10枚・上限20枚</th></tr><tr>'+('<th>利益</th><th>損失</th><th>収支</th><th>勝ち枚数</th><th>負け枚数</th>'*2)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div></section>')
    css='body{background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui;margin:0}main{max-width:1320px;margin:auto;padding:28px 22px}h1{font-size:26px}h2{font-size:20px}.note{color:#aab9d0}a{color:#8fbeff}.scroll{overflow:auto;max-width:100%;margin:18px 0}table{border-collapse:collapse;min-width:1050px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;max-width:820px;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:16px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}@media(max-width:600px){main{padding:18px 12px}section{padding:12px}h1{font-size:23px}}'
    script='''/**
 * 機能: 選択した固定条件の説明と全33場損益を表示する。
 * @param {string} id - 保存した条件ID。
 * @returns {undefined} 表示状態を更新する。売買や通信は行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase('AUTO_ER40_M2_LIMIT');'''
    document='<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>価格往復型と自動選択の全セッション損益</title><style>'+css+'</style><main><h1>価格往復型と自動選択の全セッション損益</h1><p><b>固定24条件の目標達成：'+str(target)+'件。</b>毎場黒字と金額利益80%を同時に満たすかを確認します。</p><p class="note">初回TOPIX5枚・日経10枚、上限10枚・20枚。手数料と正常ラージ気配差込み。以下は結果を見る前に決めた三対照です。</p><div class="scroll"><table><thead><tr><th>手法</th><th>商品</th><th>全収支（円）</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>中央値（円）</th><th>上位3利益場除外（円）</th><th>最悪場（円）</th></tr></thead><tbody>'+''.join(head)+'</tbody></table></div><p>入口・途中・出口と全33場：</p><select id="case" aria-label="手法">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">利益・損失は一組を全返済した手数料後金額、枚数は勝ち/負けで返済した枚数。無取引は勝ちに含めません。予定利幅1.25倍は判断時の予定で、次気配の悪化による損失超過も結果へ含めます。6点の往復は全ティックの往復とは異なり、保存されていない受信時計による二市場の順序と、実ミニ/マイクロ板の待ち順位は未検証です。</p><p><a href="README.md">調査状況</a> · <a href="損失箇所と改善の記録.md">損失箇所</a></p></main><script>'+script+'</script></html>'
    document=document.replace('<html lang="ja"><meta','<html lang="ja"><head><meta').replace('</style><main>','</style></head><body><main>').replace('</script></html>','</script></body></html>')
    document=document.replace('毎場黒字と金額利益80%を同時に満たすかを確認します。','毎場黒字と金額利益80%を両商品で同時に満たす条件は得られていません。' if target==0 else '毎場黒字と金額利益80%を両商品で同時に満たす条件がありました。')
    public=dict(sessions=sessions,cases=cases,finance_conditions=24,derived_conditions=2,target_count=target,
        source=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(raw).hexdigest()),新金融再生=0)
    (PUBLIC/'価格往復型と自動選択の公開会計.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    (PUBLIC/'価格往復型と自動選択の全セッション損益.html').write_text(document,encoding='utf8',newline='\n')
    print(json.dumps(dict(全合格=True,固定条件=24,表示条件=26,場数=33,目標達成=target,新金融再生=0),ensure_ascii=False))


if __name__=='__main__':run()
