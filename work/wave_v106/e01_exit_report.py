"""保有中の反対票と損失の同時退出6条件を、全33場の会計へ整理する。"""

import hashlib
import html
import json
from pathlib import Path

import e01_trade_report
import range_report
import trade_report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=range_report.PUBLIC
SOURCE=HERE/'e01_trade_exit/finance/結果.json'
TITLE='保有中の反対票による返済と全セッション損益'


def explanation(config: dict) -> str:
    """
    機能: 公開時の入口票と保有中の退出票を分け、固定条件を三行で説明する。
    引数: config(dict)は登録済みの6条件。
    返り値: strは日本語HTML。保有中の逆票だけを検証したと表現しない。
    """
    entry='同方向の更新票を要求' if config['mode']=='CONFIRM' else '強い逆方向の更新票なら見送る'
    return ('<p><b>入口：</b>元E01の候補に対し、公開時の直近60代理秒で'+entry+'。次正常気配で新規。</p>'
            f'<p><b>途中：</b>実際の残玉方向と反対の取引更新が直近{config["window_seconds"]}代理秒で強く、かつ場の費用後清算損失が初回4呼値分へ達した時だけ早く降りる。未知・無保有では発動しない。</p>'
            '<p><b>出口：</b>元の利益1呼値・最終損失8呼値も維持。最初に条件が成立した行で返済を予約し、次正常気配へ残玉を全返済、その場の新規終了。途中票が戻っても予約を取消さない。</p>')


def changes(case: dict) -> str:
    """
    機能: 追加退出なしと一律4呼値停止の二対照との差・勝ち赤字化を表示する。
    引数: case(dict)は完成診断を持つ固定条件。
    返り値: strは折畳みHTML。寄与を将来予測の正答率と呼ばない。
    """
    rows=[]
    for baseline,label in (('P1L8','追加退出なし'),('P1L4','一律4呼値停止')):
        for symbol in ('TOPIX','NK225'):
            d=case['diagnosis'][baseline][symbol]
            row='<tr><td>'+label+'</td><td>'+symbol+'</td>'
            for name in ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支'):
                row+=range_report.cell(d[name],name=='失った基準利益')
            rows.append(row+'<td>'+str(d['元勝ち親が赤字化'])+'</td></tr>')
    return '<details><summary>二つの基準との差と失った勝ち</summary><div class="scroll"><table><thead><tr><th>基準</th><th>商品</th><th>収支差</th><th>避けた損失</th><th>失った利益</th><th>共通出口差</th><th>後続入口</th><th>勝ち赤字化</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></details>'


def run() -> None:
    """
    機能: 完成6政策だけを読取り、目標判定・全33場合計をダークHTMLへ掲載する。
    引数: なし。未完成の結果は表示しない。
    返り値: None。金融・原板・巨大台帳・現在APIは再実行しない。
    """
    if not SOURCE.exists():print('途中退出6の結果未完成。公開しない。');return
    saved=SOURCE.read_bytes();source=json.loads(saved)
    assert source['全合格'] and source['新政策会計']==396 and len(source['configs'])==6
    cases={}
    for config in source['configs']:
        ident=config['id'];rows=[e01_trade_report.mapped(r) for r in source['results'][ident]['rows']]
        assert len(rows)==66
        cases[ident]=dict(config=config,rows=rows,summary={s:e01_trade_report.summarize(rows,s) for s in ('TOPIX','NK225')},diagnosis=source['diagnosis'][ident])
    robust=sum(all(c['summary'][s]['top3_excluded']>0 for s in ('TOPIX','NK225')) for c in cases.values())
    money=sum(all((c['summary'][s]['profit_share'] or 0)>=.8 for s in ('TOPIX','NK225')) for c in cases.values())
    target=sum(all(c['summary'][s]['positive']==33 and (c['summary'][s]['profit_share'] or 0)>=.8 for s in ('TOPIX','NK225')) for c in cases.values())
    header=[];sections=[];options=[]
    for ident,case in cases.items():
        row='<tr><td>'+html.escape(ident)+'</td>'
        for symbol in ('TOPIX','NK225'):
            value=case['summary'][symbol]
            share='—' if value['profit_share'] is None else range_report.number(value['profit_share']*100,1)+'%'
            row+=range_report.cell(value['net'])+f'<td>{value["positive"]}/{value["negative"]}/{value["no_trade"]}</td><td>'+share+'</td>'+range_report.cell(value['top3_excluded'])
        header.append(row+'</tr>')
        options.append('<option value="'+html.escape(ident,quote=True)+'">'+html.escape(ident)+'</option>')
        sections.append('<section data-case="'+html.escape(ident,quote=True)+'" hidden><h2>'+html.escape(ident)+'</h2>'+explanation(case['config'])+changes(case)+trade_report.session_table(case,source['sessions'])+'</section>')
    first=next(iter(cases))
    css='*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui}main{max-width:1360px;margin:auto;padding:26px 20px}h1{font-size:26px}h2{font-size:20px;overflow-wrap:anywhere}a{color:#8fbeff}.note{color:#aab9d0}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1120px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:15px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}details summary{cursor:pointer;color:#b6caff}@media(max-width:600px){main{padding:16px 12px}section{padding:12px}h1{font-size:23px}}'
    script='''/**
 * 機能: 途中退出の説明と全33場損益を切り替える。
 * @param {string} id - 保存した6条件のID。
 * @returns {undefined} 表示のみを更新する。金融・通信は行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase(__FIRST__);'''.replace('__FIRST__',json.dumps(first))
    document='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1><p><b>同じ条件で両商品とも上位3利益場を除いて黒字：'+str(robust)+'/6。金額利益80%：'+str(money)+'/6。全33黒字かつ金額利益80%：'+str(target)+'/6。</b></p><p>一律に損切りを狭めた比較で勝ちまで失ったため、反対側の取引更新も強まった時だけ早く降りる条件を追加しました。</p><p class="note">TOPIXミニ初回5枚・上限10枚、日経マイクロ初回10枚・上限20枚。手数料・ラージ気配差込み。全33場は既知データです。</p><div class="scroll"><table id="comparison"><thead><tr><th rowspan="2">手法ID</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr><tr>'+('<th>全収支</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>利益上位3場除外</th>'*2)+'</tr></thead><tbody>'+''.join(header)+'</tbody></table></div><select id="case" aria-label="途中退出条件">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">保有中の逆票だけで降りる対照は未測定。無取引は勝ちに数えません。4・8呼値は返済判断閾値で、約定損失の上限保証ではありません。代理票の時計は保存価格時計で、真の攻撃方向や二市場の実受信順は不明です。</p><p><a href="E01の取引更新と損失幅の改善及び全セッション損益.html">入口と損失幅の前比較</a> · <a href="E01で残った損失と改善の具体例.md">具体損失</a> · <a href="README.md">読む順序</a></p></main><script>'+script+'</script></body></html>'
    public=dict(sessions=source['sessions'],cases=cases,target_count=target,both_money80_count=money,both_top3_positive_count=robust,source=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(saved).hexdigest()),新金融再生=0)
    (PUBLIC/'保有中反対票の公開会計.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    (PUBLIC/(TITLE+'.html')).write_text(document,encoding='utf8',newline='\n')
    print(json.dumps(dict(全合格=True,条件6=6,両商品上位3除外黒字=robust,両商品金額利益80=money,全33黒字と80=target,金融再生=0),ensure_ascii=False))


if __name__=='__main__':run()
