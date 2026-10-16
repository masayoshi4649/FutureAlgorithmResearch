"""直近位相による入口改善を、変更点と全33場の会計だけで表示する。"""

import html
import json
from pathlib import Path

import range_report


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = range_report.PUBLIC
SOURCE = HERE/'local_phase/finance/results.json'


def explain(config: dict) -> str:
    """
    機能: 変えた入口と取消、変えていない出口を短く説明する。
    引数: config(dict)は結果前に固定した条件。
    返り値: strは日本語HTML。未発火を有効な反発検知と呼ばない。
    """
    policy = config['local_policy']
    rule = {'OWN_VETO':'自市場の直近2区間が反対へ強く進行していれば、反発の新規を見送る。',
            'BOTH_VETO':'両市場の直近2区間が反対へ強く進行していれば、反発の新規を見送る。',
            'ALIGNED':'両市場の直近2区間が新規方向へ強く進行した時だけ反発の新規を許す。この条件の反発候補は既知33場で0件だったため、表示損益は保存した追従単独の整数半量である。'}[policy]
    base = range_report.description(config)
    local = '<p><b>今回の追加：</b>'+rule+' 強い進行は、120秒前・60秒前・当時の3点で効率0.6以上かつ2呼値以上。未約定の反発注文も、同じ反対条件で取消。保有後の損切り・利確は変えていない。</p>'
    return local+'<details><summary>基準の入口・途中・出口</summary>'+base+'</details>'


def run() -> None:
    """
    機能: 完成した12実再生と6保存派生を、6基準と同量比較して掲載する。
    引数: なし。小結果と保存会計のみを読む。
    返り値: None。新金融再生や板・現在APIの追加取得はしない。
    """
    source = json.loads(SOURCE.read_text(encoding='utf8'))
    assert source['全合格'] and source['account_count']==792 and source['display_account_count']==1188
    sessions = source['sessions']; cases = {}; configs = {c['id']:c for c in source['configs']}
    for ident, case in source['cases'].items():
        assert len(case['rows'])==66
        cases[ident] = dict(config=configs[ident], rows=case['rows'],
                           summary={s:range_report.summary(case['rows'],s) for s in ('TOPIX','NK225')},
                           derived=configs[ident]['local_policy']=='ALIGNED')
    compare = ['AUTO_ER40_M2_LIMIT_OWN_VETO','AUTO_ER40_M2_LIMIT_BOTH_VETO','AUTO_ER40_M2_LIMIT_ALIGNED']
    short = []
    for ident in compare:
        for symbol in ('TOPIX','NK225'):
            value=cases[ident]['summary'][symbol]
            short.append('<tr><td>'+html.escape(ident)+'</td><td>'+symbol+'</td>'+range_report.cell(value['net'])+
                         f'<td>{value["positive"]}/{value["negative"]}/{value["no_trade"]}</td>'+
                         '<td>'+range_report.number(value['profit_share']*100,1)+'%</td>'+range_report.cell(value['top3_excluded'])+'</tr>')
    options=[]; sections=[]
    for ident,case in cases.items():
        config=case['config']; options.append('<option value="'+ident+'">'+ident+'</option>')
        baseline=source['baselines'][config['base_id']]
        total=[]
        for symbol in ('TOPIX','NK225'):
            old=range_report.summary(baseline['rows'],symbol); new=case['summary'][symbol]; delta=source['diagnosis'][ident][symbol]
            total.append('<tr><td>'+symbol+'</td>'+range_report.cell(old['net'])+range_report.cell(new['net'])+
                         range_report.cell(delta['避けた基準損失'])+range_report.cell(delta['失った基準利益'],True)+
                         range_report.cell(delta['共通入口の出口変化'])+range_report.cell(delta['新たな入口の収支'])+'</tr>')
        index={(r['session'],r['symbol']):r for r in case['rows']}; body=[]
        for session in sessions:
            line='<tr><td>'+session.replace('_Day',' デイ').replace('_Night',' ナイト')+'</td>'
            for symbol in ('TOPIX','NK225'):
                row=index[session,symbol]
                line+=(range_report.cell(row['profit'])+range_report.cell(row['loss'],True)+range_report.cell(row['net'])+
                       '<td>'+range_report.number(row['winning_lots'])+'</td><td>'+range_report.number(row['losing_lots'])+'</td>')
            body.append(line+'</tr>')
        line='<tr class="total"><td>全33合計</td>'
        for symbol in ('TOPIX','NK225'):
            value=case['summary'][symbol]
            line+=(range_report.cell(value['profit'])+range_report.cell(value['loss'],True)+range_report.cell(value['net'])+
                   '<td>'+range_report.number(value['winning_lots'])+'</td><td>'+range_report.number(value['losing_lots'])+'</td>')
        body.append(line+'</tr>')
        sections.append('<section data-case="'+ident+'" hidden><h2>'+ident+'</h2>'+explain(config)+
            '<div class="scroll"><table><thead><tr><th>商品</th><th>基準収支</th><th>変更後収支</th><th>避けた損失</th><th>失った利益</th><th>同入口の出口差</th><th>新たな入口収支</th></tr></thead><tbody>'+''.join(total)+'</tbody></table></div>'+
            '<div class="scroll"><table class="sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="5">TOPIXミニ：5枚・上限10枚</th><th colspan="5">日経マイクロ：10枚・上限20枚</th></tr><tr>'+('<th>利益</th><th>損失</th><th>収支</th><th>勝ち枚数</th><th>負け枚数</th>'*2)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div></section>')
    target=sum(all(v['positive']==33 and (v['profit_share'] or 0)>=.8 for v in c['summary'].values()) for c in cases.values() if not c['derived'])
    assert target==0
    css='body{background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui;margin:0}main{max-width:1320px;margin:auto;padding:28px 22px}h1{font-size:26px}h2{font-size:20px}a{color:#8fbeff}.note{color:#aab9d0}.scroll{overflow:auto;max-width:100%;margin:18px 0}table{border-collapse:collapse;min-width:1050px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;max-width:900px;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:16px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}@media(max-width:600px){main{padding:18px 12px}section{padding:12px}h1{font-size:23px}}'
    script='''/**
 * 機能: 一つの固定手法の全場損益を表示する。
 * @param {string} id - 保存済み手法ID。
 * @returns {undefined} 表示状態だけを変更する。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase('AUTO_ER40_M2_LIMIT_OWN_VETO');'''
    document='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>直近の進行を分ける改善と全セッション損益</title><style>'+css+'</style></head><body><main><h1>直近の進行を分ける改善と全セッション損益</h1><p><b>損失は減りましたが、毎場の安定利益には至っていません。</b>新たな12条件の両銘柄で、利益上位3場を除いても黒字となった条件は0件です。</p><p class="note">18表示のうち12条件を新規再生。両市場の反発を完全に待つ6条件は反発入口0件で、保存した追従単独の整数半量を再利用しています。無取引は勝ちに数えません。</p><div class="scroll"><table><thead><tr><th>手法</th><th>商品</th><th>全収支（円）</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>利益上位3場除外（円）</th></tr></thead><tbody>'+''.join(short)+'</tbody></table></div><p>入口を避けた効果と全33場：</p><select id="case" aria-label="手法">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">金額は手数料・正常ラージ気配差込み。利益・損失は全返済した組別、枚数は勝ち/負けで返済した枚数。新規拒否後の別の入口も再処理しており、基準の負けだけを差し引いた比較ではありません。受信時計・実ミニ/マイクロ板と待ち順位は未取得です。</p><p><a href="README.md">調査状況</a> · <a href="価格往復型と自動選択の全セッション損益.html">変更前の価格往復型</a></p></main><script>'+script+'</script></body></html>'
    public=dict(sessions=sessions,cases=cases,actual_financial_conditions=12,derived_conditions=6,target_count=target,
                source=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=range_report.hashlib.sha256(SOURCE.read_bytes()).hexdigest()),新金融再生=0)
    (PUBLIC/'直近位相の公開会計.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    (PUBLIC/'直近の進行を分ける改善と全セッション損益.html').write_text(document,encoding='utf8',newline='\n')
    print('全33場・新12条件と保存派生6条件を掲載。目標達成0、新金融再生0。')


if __name__=='__main__':run()
