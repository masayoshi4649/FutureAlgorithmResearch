"""最初の実建玉に対する常設利確指値と成行返済十二対照を公開会計へ整理する。"""

import argparse
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
SOURCE=HERE/'e01_resting_takeprofit/finance/結果.json'
TITLE='常設利確指値と成行返済の比較及び全セッション損益'
ACCOUNTING_TITLE='常設利確と成行返済の公開会計.json'
SYMBOLS=('TOPIX','NK225')
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支','元勝ち親が赤字化')


def build(source: dict, source_sha: str) -> dict:
    """
    機能: 完成十二政策の全33場・枚数と同入口の利確二法差を保存小会計へ対応させる。
    引数: source(dict)、source_sha(str)は完成金融結果と同bytes指紋。
    返り値: dictは公開値。元GU全場との差を注文方法だけの効果へ流用しない。
    """
    assert source['全合格'] and source['source開始終端一致'] and source['新政策会計']==792
    assert source['元GU出口使用']==source['入口engine再生']==0
    sessions=source['sessions'];assert len(sessions)==33 and len(set(sessions))==33
    assert len(source['configs'])==12 and len(source['利確二法の各場比較'])==396
    cases={}
    for config in source['configs']:
        assert config['quantity']=={'TOPIX':5,'NK225':10} and config['cap']=={'TOPIX':10,'NK225':20}
        assert config['stop_ticks'] in (4,8,16) and config['takeprofit_ticks']==1 and config['method'] in ('RESTING','NEXT_MARKET')
        ident=config['id'];value=source['results'][ident];rows=[e01_trade_report.mapped(r) for r in value['rows']]
        assert len(rows)==66 and {(r['session'],r['symbol']) for r in rows}=={(s,y) for s in sessions for y in SYMBOLS}
        summary={s:e01_trade_report.summarize(rows,s) for s in SYMBOLS}
        compare={}
        for symbol in SYMBOLS:
            original=value['symbols'][symbol];mapped=summary[symbol]
            for old,new in (('利益','profit'),('損失','loss'),('収支','net'),('勝ち枚数','winning_lots'),('負け枚数','losing_lots'),
                            ('黒字場','positive'),('赤字場','negative'),('無取引場','no_trade'),('上位3利益場除外収支','top3_excluded')):
                assert abs(original[old]-mapped[new])<1e-5
            assert original['利益割合']==mapped['profit_share']
            ds=[d for d in source['利確二法の各場比較'] if d['mode']==config['mode'] and d['stop']==config['stop_ticks'] and d['symbol']==symbol]
            assert len(ds)==33 and {d['session'] for d in ds}==set(sessions)
            for d in ds:
                assert abs(d['収支変化']-(d['常設']['収支']-d['成行']['収支']))<1e-5
                assert abs(d['収支変化']-(d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支']))<1e-5
            compare[symbol]={f:sum(d[f] for d in ds) for f in FIELDS}
        cases[ident]=dict(config=config,rows=rows,summary=summary,order_comparison=compare)
    robust=sum(all(c['summary'][s]['top3_excluded']>0 for s in SYMBOLS) for c in cases.values())
    money=sum(all(c['summary'][s]['profit_share'] is not None and c['summary'][s]['profit_share']>=.8 for s in SYMBOLS) for c in cases.values())
    positive=sum(all(c['summary'][s]['net']>0 for s in SYMBOLS) for c in cases.values())
    return dict(sessions=sessions,cases=cases,both_net_positive_count=positive,both_top3_positive_count=robust,
        both_money80_count=money,source=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=source_sha),
        observed_tick={'TOPIX':.5,'NK225':10},actual_product_tick={'TOPIXmini':.25,'NK225micro':5},
        scope='元W60候補の場最初の実newfill、一場一親、初回5/10枚、原GU出口と部分返済は使わない。',
        resting_assumption='ラージBBOが固定targetへ接触したら固定指値価格で全量約定する仮定。native待ち順位/実商品quoteは未確認。',
        新金融再生=0,原NPZ読取=0,API取得=0)


def explanation(config: dict) -> str:
    """
    機能: 元の入口と単一玉・固定利確二法・損切りと場内期限を三行で説明する。
    引数: config(dict)は登録済み十二条件。
    返り値: strは短いHTML。常設の全量約定を実戦の証明とは説明しない。
    """
    entry=('方向票2回以上・新規方向の釣合い25%以上なら許可' if config['mode']=='CONFIRM'
           else '方向票2回以上・逆方向の釣合い25%以上なら見送る。不明や中立は元どおり')
    method=('新規約定後に固定利確指値を常設し、次行以降の正常気配が接触した最初行で固定価格の全量約定を仮定する。'
            if config['method']=='RESTING' else '同じ固定利確価格へ正常気配が接触したら返済を判断し、次の正常気配で成行返済する。')
    return ('<p><b>入口：</b>元E01の新規公開時に直近60代理秒で'+entry+'。その場の最初の実新規だけを5枚・10枚で採用する。</p>'
        '<p><b>途中：</b>一場一親で追加玉・部分決済・再参加はしない。利確線は建値からラージ板の観測1呼値（TOPIX 0.5pt／日経10円）で固定。これは実ミニ／マイクロの2呼値。</p>'
        f'<p><b>出口：</b>{method}損切りは建値から{config["stop_ticks"]}観測呼値の初接触で判断し、次正常気配へ全返済。既知の静観時間と場内期限は優先して返済する。</p>')


def changes(case: dict) -> str:
    """
    機能: 同じ入口・停止幅で常設指値から成行返済を引いた差と勝ち赤字化を表示する。
    引数: case(dict)は同入口二法の保存寄与。
    返り値: strは二商品表。二方法で同じ比較を表示し、新たな標本に数えない。
    """
    rows=[]
    for symbol in SYMBOLS:
        d=case['order_comparison'][symbol]
        rows.append('<tr><td>'+symbol+'</td>'+''.join(range_report.cell(d[f],f=='失った基準利益') for f in FIELDS[:-1])+f'<td>{d[FIELDS[-1]]}</td></tr>')
    return '<details><summary>同入口・同損切り幅の注文方法差（常設−成行）</summary><div class="scroll"><table><thead><tr><th>商品</th><th>収支差</th><th>消失損失</th><th>消失利益</th><th>共通親の出口差</th><th>新入口</th><th>成行の勝ちが常設で赤字</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></details>'


def document(data: dict) -> str:
    """
    機能: 全十二条件の先頭比較と全33場切替損益をダークHTMLへ描画する。
    引数: data(dict)はbuildで検算済み公開会計。
    返り値: strは自己完結HTML。APIや金融を実行しない。
    """
    cases=data['cases'];header=[];sections=[];options=[]
    for ident,case in cases.items():
        line='<tr><td>'+html.escape(ident)+'</td>'
        for symbol in SYMBOLS:
            v=case['summary'][symbol];share='—' if v['profit_share'] is None else range_report.number(v['profit_share']*100,1)+'%'
            line+=range_report.cell(v['net'])+f'<td>{v["positive"]}/{v["negative"]}/{v["no_trade"]}</td><td>'+share+'</td>'+range_report.cell(v['top3_excluded'])
        header.append(line+'</tr>')
        options.append('<option value="'+html.escape(ident,quote=True)+'">'+html.escape(ident)+'</option>')
        sections.append('<section data-case="'+html.escape(ident,quote=True)+'" hidden><h2>'+html.escape(ident)+'</h2>'+explanation(case['config'])+changes(case)+trade_report.session_table(case,data['sessions'])+'</section>')
    sample=cases['E01_FIRST_W60_CONFIRM_TP1_S16_RESTING']['summary'];nk=sample['NK225'];top=sample['TOPIX']
    rate=range_report.number(nk['positive']/nk['active']*100,1) if nk['active'] else '—'
    example=(f'停止16・常設指値の日経は{nk["positive"]}/{nk["active"]}取引で黒字（{rate}%）でも、収支'+range_report.number(nk['net'])+'円・金額利益割合'+range_report.number(nk['profit_share']*100,1)+'%。同じ条件のTOPIXは'+range_report.number(top['net'])+'円でした。')
    css='*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui}main{max-width:1360px;margin:auto;padding:26px 20px}h1{font-size:26px}h2{font-size:20px;overflow-wrap:anywhere}a{color:#8fbeff}.note{color:#aab9d0}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1120px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:15px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}details summary{cursor:pointer;color:#b6caff}@media(max-width:600px){main{padding:16px 12px}section{padding:12px}h1{font-size:23px}}'
    script='''/**
 * 機能: 常設利確と成行返済の説明・全33場会計を切り替える。
 * @param {string} id - 保存した十二条件のID。
 * @returns {undefined} 表示だけを更新する。金融や通信を行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase(__FIRST__);'''.replace('__FIRST__',json.dumps(next(iter(cases))))
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1>'
        +'<p><b>常設指値でも、損失幅と利幅の不均衡が残りました。95%以上の勝率だけでは、安定した金額利益の証明になりません。</b></p><p>'+example+'</p>'
        +f'<p>両商品とも黒字：{data["both_net_positive_count"]}/12。両商品とも利益上位3場除外で黒字：{data["both_top3_positive_count"]}/12。両商品とも金額利益80%：{data["both_money80_count"]}/12。</p>'
        +'<p class="note">初回TOPIXミニ5枚・日経マイクロ10枚、上限10枚・20枚。元GUの最初の実新規だけを採用し、原出口・後続新規・部分決済を使わない一場一親の比較。手数料込み、全33場は既知データです。</p>'
        +'<div class="scroll"><table id="comparison"><thead><tr><th rowspan="2">手法ID</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr><tr>'+('<th>全収支</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>利益上位3場除外</th>'*2)+'</tr></thead><tbody>'+''.join(header)+'</tbody></table></div>'
        +'<select id="case" aria-label="利確方法と損切り幅の条件">'+''.join(options)+'</select>'+''.join(sections)
        +'<p class="note">常設指値はラージBBO到達時に固定指値で全量約定する仮定です。実商品の待ち順位・実ミニ／マイクロ気配は未確認で、実戦で同じ約定が得られる証明ではありません。観測1呼値はTOPIX0.5pt／日経10円で実商品の2呼値。元GU全場との違いには後続取引や部分返済を除いた効果も含まれ、注文方法だけの改善とは扱いません。無取引を勝ちに数えません。金額利益割合は総利益÷（総利益＋総損失）、勝ち/負け枚数は実決済枚数です。</p>'
        +'<p><a href="一呼値の小利益で終える改善と全セッション損益.html">場全体の小利益停止</a> · <a href="README.md">読む順序</a></p></main><script>'+script+'</script></body></html>')


def run(destination: Path | None) -> None:
    """
    機能: 完成小JSONだけを照合し、根の公開先又は私有準備proofへ保存する。
    引数: destination(Path|None)は公開先。Noneなら公共へ書き込まない。
    返り値: None。巨大台帳・原NPZ・API・金融再生を行わない。
    """
    saved=SOURCE.read_bytes();data=build(json.loads(saved),hashlib.sha256(saved).hexdigest());text=document(data)
    proof=dict(全合格=True,source=data['source'],条件数=12,会計口座数=792,全場表セル数=12*34*10,
        注文法差セル数=12*2*6,先頭指標数=12*2*4,観測呼値=data['observed_tick'],実商品呼値=data['actual_product_tick'],
        公共書込=destination is not None,金融再生=0,原NPZ読取=0,API取得=0,目視確認=False,
        HTML_SHA256=hashlib.sha256(text.encode('utf8')).hexdigest(),
        source_SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__).resolve(),HERE/'resting_view.py',HERE/'e01_trade_report.py',HERE/'range_report.py',HERE/'trade_report.py')})
    if destination is not None:
        assert destination.exists() and destination.is_dir()
        (destination/ACCOUNTING_TITLE).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
        (destination/(TITLE+'.html')).write_text(text,encoding='utf8',newline='\n')
    review=HERE/'review/resting';review.mkdir(parents=True,exist_ok=True)
    name='根の生成会計とsource対応.json' if destination is not None else '小会計とsource対応の準備検査.json'
    (review/name).write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='常設利確十二条件の保存会計表示')
    parser.add_argument('--check-source',action='store_true');parser.add_argument('--output-dir',type=Path,default=PUBLIC)
    args=parser.parse_args();run(None if args.check_source else args.output_dir)
