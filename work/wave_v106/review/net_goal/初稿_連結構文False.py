"""一呼値料金差引の場全体目標六条件を、全33場と二基準差へ整理する。"""

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
SOURCE=HERE/'e01_tick_net_goal/finance/結果.json'
TITLE='一呼値の小利益で終える改善と全セッション損益'
ACCOUNTING_TITLE='一呼値小利益の公開会計.json'
SYMBOLS=('TOPIX','NK225')
GOALS={'TOPIX':2082.,'NK225':780.}
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def build(source: dict, source_sha: str) -> dict:
    """
    機能: 完成六政策の全33場損益・枚数・二対照寄与を公開値へexactに対応させる。
    引数: source(dict)、source_sha(str)は保存小結果と同bytesのSHA256。
    返り値: dictは公開会計。目標や不明値を0へ補完せず、新金融を計算しない。
    """
    assert source['全合格'] and source['source開始終端一致'] and source['新政策会計']==396
    sessions=source['sessions'];assert len(sessions)==33 and len(set(sessions))==33
    assert len(source['configs'])==6
    cases={}
    for config in source['configs']:
        assert config['goal_yen']==GOALS and config['loss_ticks'] in (4,8,16)
        assert config['window_seconds']==60 and config['execution']=='D0'
        assert config['quantity']=={'TOPIX':5,'NK225':10} and config['cap']=={'TOPIX':10,'NK225':20}
        ident=config['id'];value=source['results'][ident]
        rows=[e01_trade_report.mapped(r) for r in value['rows']]
        assert len(rows)==66 and {(r['session'],r['symbol']) for r in rows}=={(s,y) for s in sessions for y in SYMBOLS}
        summary={symbol:e01_trade_report.summarize(rows,symbol) for symbol in SYMBOLS}
        for symbol in SYMBOLS:
            original=value['symbols'][symbol];mapped=summary[symbol]
            for old,new in (('利益','profit'),('損失','loss'),('収支','net'),('勝ち枚数','winning_lots'),('負け枚数','losing_lots'),
                            ('黒字場','positive'),('赤字場','negative'),('無取引場','no_trade'),('上位3利益場除外収支','top3_excluded')):
                assert abs(original[old]-mapped[new])<1e-5,(ident,symbol,old)
            assert original['利益割合']==mapped['profit_share']
            for baseline in ('P1L8','P1L4'):
                d=source['diagnosis'][ident][baseline][symbol]
                assert abs(d['収支変化']-(d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支']))<1e-5
        cases[ident]=dict(config=config,rows=rows,summary=summary,diagnosis=source['diagnosis'][ident])
    robust=sum(all(c['summary'][s]['top3_excluded']>0 for s in SYMBOLS) for c in cases.values())
    money=sum(all(c['summary'][s]['profit_share'] is not None and c['summary'][s]['profit_share']>=.8 for s in SYMBOLS) for c in cases.values())
    target=sum(all(c['summary'][s]['positive']==33 and c['summary'][s]['profit_share'] is not None and c['summary'][s]['profit_share']>=.8 for s in SYMBOLS) for c in cases.values())
    return dict(sessions=sessions,cases=cases,target_count=target,both_money80_count=money,both_top3_positive_count=robust,
        source=dict(path=SOURCE.relative_to(ROOT).as_posix(),sha256=source_sha),
        fixed_goal_yen=GOALS,goal_scope='各親でなく、場全体の手数料後清算利益。',新金融再生=0,原NPZ読取=0,API取得=0)


def explanation(config: dict) -> str:
    """
    機能: 元W60入口と固定円目標・損失予算を、三行の平易な日本語で説明する。
    引数: config(dict)は登録済み六条件。
    返り値: strはHTML。固定円目標を各親一呼値出口と混同しない。
    """
    entry=('方向票2回以上・新規方向の釣合い25%以上を要求する' if config['mode']=='CONFIRM'
           else '方向票2回以上・逆方向の釣合い25%以上なら見送る。不明や中立は元の候補どおり')
    return ('<p><b>入口：</b>元E01の候補を公開する時、直近60代理秒の取引更新で'+entry+'。次の正常気配で成行新規。</p>'
            '<p><b>途中：</b>元の損切り・追尾・部分返済を続け、場全体の手数料後清算利益がTOPIX 2,082円・日経780円に達したら、その場の新規を終了する。各親が一呼値上がったら降りる方法ではない。</p>'
            f'<p><b>出口：</b>利益目標又は初回{config["loss_ticks"]}呼値分の損失予算に最初に達した行で全返済を予約し、次の正常気配で残UIDを別々に返済する。場内期限も維持し、その場で再参加しない。</p>')


def changes(case: dict) -> str:
    """
    機能: 純利益一呼値目標のP1L8/P1L4と、五寄与・元勝ち親の赤字化を表示する。
    引数: case(dict)は完成二対照診断。
    返り値: strは四行の折畳み表。各場停止の寄与を予測正答率とは説明しない。
    """
    rows=[]
    for baseline,label in (('P1L8','従来の純利益1呼値・損失8呼値'),('P1L4','従来の純利益1呼値・損失4呼値')):
        for symbol in SYMBOLS:
            d=case['diagnosis'][baseline][symbol]
            line='<tr><td>'+label+'</td><td>'+symbol+'</td>'
            for field in FIELDS:line+=range_report.cell(d[field],field=='失った基準利益')
            rows.append(line+'<td>'+str(d['元勝ち親が赤字化'])+'</td></tr>')
    return '<details><summary>二つの基準との差と失った勝ち</summary><div class="scroll"><table><thead><tr><th>基準</th><th>商品</th><th>収支差</th><th>避けた損失</th><th>失った利益</th><th>共通出口差</th><th>後続入口</th><th>勝ち赤字化</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></details>'


def document(data: dict) -> str:
    """
    機能: 全六条件の先頭比較と全33場切替表を暗背景HTMLへ描画する。
    引数: data(dict)はbuildで会計照合済みの公開値。
    返り値: strは自己完結HTML。通信や金融実行を含まない。
    """
    cases=data['cases'];header=[];sections=[];options=[]
    for ident,case in cases.items():
        line='<tr><td>'+html.escape(ident)+'</td>'
        for symbol in SYMBOLS:
            value=case['summary'][symbol]
            share='—' if value['profit_share'] is None else range_report.number(value['profit_share']*100,1)+'%'
            line+=range_report.cell(value['net'])+f'<td>{value["positive"]}/{value["negative"]}/{value["no_trade"]}</td><td>'+share+'</td>'+range_report.cell(value['top3_excluded'])
        header.append(line+'</tr>')
        options.append('<option value="'+html.escape(ident,quote=True)+'">'+html.escape(ident)+'</option>')
        sections.append('<section data-case="'+html.escape(ident,quote=True)+'" hidden><h2>'+html.escape(ident)+'</h2>'+explanation(case['config'])+changes(case)+trade_report.session_table(case,data['sessions'])+'</section>')
    css='*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui}main{max-width:1360px;margin:auto;padding:26px 20px}h1{font-size:26px}h2{font-size:20px;overflow-wrap:anywhere}a{color:#8fbeff}.note{color:#aab9d0}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1120px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:15px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}details summary{cursor:pointer;color:#b6caff}@media(max-width:600px){main{padding:16px 12px}section{padding:12px}h1{font-size:23px}}'
    script='''/**
 * 機能: 一呼値料金差引目標の説明と全33場損益を切り替える。
 * @param {string} id - 保存した六条件のID。
 * @returns {undefined} 表示のみ更新する。通信や金融を実行しない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase(__FIRST__);'''.replace('__FIRST__',json.dumps(next(iter(cases))))
    status=(f'両商品とも利益上位3場を除いて黒字：{data["both_top3_positive_count"]}/6。'
            f'金額利益80%：{data["both_money80_count"]}/6。全33黒字かつ金額利益80%：{data["target_count"]}/6。')
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1>'
        '<p><b>一呼値の料金差引後まで目標を下げても、両商品で安定する方法にはなりませんでした。</b></p><p>'+status+'</p>'
        '<p>小利益目標はTOPIX 2,082円・日経780円で固定。初回一呼値の値幅から往復料金を引いた額を、セッション口座全体へ適用します。</p>'
        '<p class="note">TOPIXミニ初回5枚・上限10枚、日経マイクロ初回10枚・上限20枚。手数料とラージ気配差込み。既知の全33場を同じ条件で再生しました。</p>'
        '<div class="scroll"><table id="comparison"><thead><tr><th rowspan="2">手法ID</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr><tr>'+('<th>全収支</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>利益上位3場除外</th>'*2)+'</tr></thead><tbody>'+''.join(header)+'</tbody></table></div>'
        '<select id="case" aria-label="小利益と損失予算の条件">'+''.join(options)+'</select>'+''.join(sections)
        '<p class="note">目標は各親の一呼値利確ではありません。過去親の損失や部分返済料によって必要な順行量が変わります。判断後の次気配で損益が変わるため、黒字や損失上限は保証しません。無取引は勝ちに数えません。金額利益割合は完結親の総利益÷（総利益＋総損失）、勝ち/負け枚数は実決済枚数です。代理秒は保存価格時計で、実受信時刻や真の攻撃注文方向は不明です。</p>'
        '<p><a href="E01の取引更新と損失幅の改善及び全セッション損益.html">入口と損失幅の比較</a> · <a href="保有中の反対票による返済と全セッション損益.html">反対票による途中退出の比較</a> · <a href="README.md">読む順序</a></p></main><script>'+script+'</script></body></html>')


def run(destination: Path | None) -> None:
    """
    機能: 完成小JSONだけを確認し、根指定の公開先又は私有source対応proofへ保存する。
    引数: destination(Path|None)は公開先。Noneなら私有proofだけで公開はしない。
    返り値: None。巨大台帳・原NPZ・API・金融再生を使わない。
    """
    saved=SOURCE.read_bytes();data=build(json.loads(saved),hashlib.sha256(saved).hexdigest())
    text=document(data)
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (Path(__file__).resolve(),HERE/'net_goal_view.py',HERE/'e01_trade_report.py',HERE/'range_report.py',HERE/'trade_report.py')}
    proof=dict(全合格=True,source=data['source'],source_SHA256=sources,条件数=6,会計口座数=396,
        全場表セル数=6*34*10,診断セル数=6*4*6,先頭指標数=6*2*4,
        固定目標=GOALS,損失呼値=[4,8,16],公共書込=destination is not None,金融再生=0,原NPZ読取=0,API取得=0,
        HTML_SHA256=hashlib.sha256(text.encode('utf8')).hexdigest(),目視確認=False)
    if destination is not None:
        assert destination.exists() and destination.is_dir()
        (destination/ACCOUNTING_TITLE).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
        (destination/(TITLE+'.html')).write_text(text,encoding='utf8',newline='\n')
    review=HERE/'review/net_goal';review.mkdir(parents=True,exist_ok=True)
    name='根の生成会計とsource対応.json' if destination is not None else '小会計とsource対応の準備検査.json'
    (review/name).write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='一呼値小利益六条件の保存会計表示')
    parser.add_argument('--check-source',action='store_true');parser.add_argument('--output-dir',type=Path,default=PUBLIC)
    args=parser.parse_args();run(None if args.check_source else args.output_dir)
