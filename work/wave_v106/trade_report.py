"""取引更新代理の入口条件36を、短い説明と全33場の利益・損失へ整理する。"""

import hashlib
import html
import json
from pathlib import Path

import range_report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=range_report.PUBLIC
SOURCE=HERE/'trade_gate/finance/results.json'
TITLE='約定更新を入口で確認する手法と全セッション損益'


def explanation(config: dict) -> str:
    """
    機能: 入口への追加確認と、途中・出口の不変条件を平易に説明する。
    引数: config(dict)は結果前に固定した36条件の一つ。
    返り値: strは日本語HTML。代理の票を真の売買数量とは説明しない。
    """
    scope={'R':'反発の入口だけ','C':'追従の入口だけ','BOTH':'反発と追従の両方'}[config['gate_scope']]
    mode='次の正常気配で新規' if config['range_entry']=='MARKET' else '公開した指値の最初の気配到達で新規'
    return (f'<p><b>入口：</b>両市場の往復なら帯の端から中心への反発、両市場の進行が同方向なら追従を選ぶ。{scope}で、直近{config["trade_window_seconds"]}代理秒の取引更新も確認する。</p>'
            '<p>出来高が増えた行の現在値が、直前の売気配以上なら買いの票、買気配以下なら売りの票。方向票が2回以上あり、新規方向への釣合いが25%以上の時に許す。出来高増分を全て一方向の約定量とは扱わない。</p>'
            f'<p><b>途中・出口：</b>取引更新の条件は新規公開時だけ。反発は当時の中心で利確、帯の外{config["margin_ticks"]}呼値で損切り。追従は元の支持線・損切り・広い追尾を維持。全玉を場内返済。反発は{mode}する。</p>')


def session_table(case: dict, sessions: list[str]) -> str:
    """
    機能: 両商品の全33場と合計の金額・勝ち負け枚数を描画する。
    引数: case(dict)、sessions(list[str])は保存会計と固定場順。
    返り値: strはHTML表。原板の読取や取引再生をしない。
    """
    index={(r['session'],r['symbol']):r for r in case['rows']};body=[]
    for session in sessions+['全33合計']:
        total=session=='全33合計';line='<tr'+(' class="total"' if total else '')+'><td>'+session.replace('_Day',' デイ').replace('_Night',' ナイト')+'</td>'
        for symbol in ('TOPIX','NK225'):
            value=case['summary'][symbol] if total else index[session,symbol]
            line+=range_report.cell(value['profit'])+range_report.cell(value['loss'],True)+range_report.cell(value['net'])
            line+='<td>'+range_report.number(value['winning_lots'])+'</td><td>'+range_report.number(value['losing_lots'])+'</td>'
        body.append(line+'</tr>')
    return '<div class="scroll"><table class="sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="5">TOPIXミニ：5枚・上限10枚</th><th colspan="5">日経マイクロ：10枚・上限20枚</th></tr><tr>'+('<th>利益</th><th>損失</th><th>収支</th><th>勝ち枚数</th><th>負け枚数</th>'*2)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


def run() -> None:
    """
    機能: 完成36条件の説明・基準差・全場会計をダークHTMLへ掲載する。
    引数: なし。保存小会計だけを読む。
    返り値: None。新金融再生・板読取・API取得を行わない。
    """
    raw=SOURCE.read_bytes();source=json.loads(raw);assert source['全合格'] and source['account_count']==2376
    sessions=source['sessions'];configs={c['id']:c for c in source['configs']};cases={}
    for ident,value in source['cases'].items():
        assert len(value['rows'])==66
        cases[ident]=dict(config=configs[ident],rows=value['rows'],summary={s:range_report.summary(value['rows'],s) for s in ('TOPIX','NK225')})
    comparisons=[f'TRADE_GATE_{scope}_W10_M2_MARKET' for scope in ('R','C','BOTH')]
    top=[]
    for ident in comparisons:
        for symbol in ('TOPIX','NK225'):
            value=cases[ident]['summary'][symbol]
            top.append('<tr><td>'+ident+'</td><td>'+symbol+'</td>'+range_report.cell(value['net'])+
                       f'<td>{value["positive"]}/{value["negative"]}/{value["no_trade"]}</td><td>'+range_report.number((value['profit_share'] or 0)*100,1)+'%</td>'+range_report.cell(value['top3_excluded'])+'</tr>')
    options=[];sections=[]
    for ident,case in cases.items():
        options.append('<option value="'+html.escape(ident,quote=True)+'">'+html.escape(ident)+'</option>');changes=[]
        for symbol in ('TOPIX','NK225'):
            delta=source['diagnosis'][ident][symbol]
            changes.append('<tr><td>'+symbol+'</td>'+range_report.cell(delta['収支変化'])+range_report.cell(delta['避けた基準損失'])+
                           range_report.cell(delta['失った基準利益'],True)+range_report.cell(delta['共通入口の出口変化'])+range_report.cell(delta['新たな入口の収支'])+'</tr>')
        sections.append('<section data-case="'+ident+'" hidden><h2>'+ident+'</h2>'+explanation(case['config'])+
                        '<details><summary>同じ枚数の基準との差（円）</summary><div class="scroll"><table><thead><tr><th>商品</th><th>収支変化</th><th>避けた損失</th><th>失った利益</th><th>同入口の出口差</th><th>新たな入口収支</th></tr></thead><tbody>'+''.join(changes)+'</tbody></table></div></details>'+session_table(case,sessions)+'</section>')
    target=sum(all(v['positive']==33 and (v['profit_share'] or 0)>=.8 for v in c['summary'].values()) for c in cases.values())
    robust=sum(all(v['top3_excluded']>0 for v in c['summary'].values()) for c in cases.values())
    assert target==robust==0
    css='body{background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui;margin:0}main{max-width:1320px;margin:auto;padding:28px 22px}h1{font-size:26px}h2{font-size:20px}a{color:#8fbeff}.note{color:#aab9d0}.scroll{overflow:auto;max-width:100%;margin:18px 0}table{border-collapse:collapse;min-width:1050px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;max-width:900px;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:16px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}@media(max-width:600px){main{padding:18px 12px}section{padding:12px}h1{font-size:23px}}'
    script='''/**
 * 機能: 選択した入口条件の説明と全場会計を表示する。
 * @param {string} id - 保存した36条件のID。
 * @returns {undefined} 表示だけを変更する。取引を実行しない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase('TRADE_GATE_BOTH_W10_M2_MARKET');'''
    document='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1><p><b>入口への取引更新確認だけでは、安定利益に届きませんでした。</b>全36条件で、両商品とも利益上位3場を除いて黒字だった条件は0件です。</p><p class="note">手数料・ラージ気配差込み。初回TOPIX5枚・日経10枚、上限10枚・20枚。以下は同じ10代理秒・2呼値・成行で、追加する入口だけを比較します。</p><div class="scroll"><table><thead><tr><th>確認する入口</th><th>商品</th><th>全収支（円）</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>利益上位3場除外（円）</th></tr></thead><tbody>'+''.join(top)+'</tbody></table></div><select id="case" aria-label="手法">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">金額利益割合は利益÷（利益＋損失）。利益・損失は全返済した組別、枚数は勝ち/負けで返済した枚数。36条件の2376表示口座のうち、1129を実再生、1247は全執行入力が同じ経済を再利用。独立な2376標本ではありません。窓は価格時計の代理秒で、実受信の経過秒ではありません。実攻撃方向・実ミニ/マイクロの待ち順位は未確認です。</p><p><a href="README.md">調査状況</a> · <a href="損失箇所と改善の記録.md">具体的な失敗箇所</a></p></main><script>'+script+'</script></body></html>'
    public=dict(sessions=sessions,cases=cases,target_count=target,robust_count=robust,source=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(raw).hexdigest()),新金融再生=0)
    (PUBLIC/'約定更新確認の公開会計.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    (PUBLIC/(TITLE+'.html')).write_text(document,encoding='utf8',newline='\n')
    print('36固定条件・全33場を掲載。目標達成0、再集計のみ。')


if __name__=='__main__':run()
