"""公開時の予定リスク数量四条件を、短い説明と全33場会計へ表示する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import statistics

import e01_trade_report
import range_report
import trade_report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=range_report.PUBLIC
TITLE='予定リスクで枚数を変える4比較と全セッション損益'
ACCOUNTING_TITLE='予定リスク数量4比較の公開会計.json'
SOURCE=HERE/'e01_risk_sizing/finance/結果.json'
FIXED=HERE/'e01_risk_sizing/金融事前固定.json'
PLAN=HERE/'e01_risk_sizing/試行計画.json'
GOAL=HERE/'new_goal/数量四条件追加後の65基準と全候補判定.json'
DIAGNOSIS=HERE/'price_review/size_loss_diagnosis/最悪六場と旧勝ち赤字化二例の具体診断.json'
SYMBOLS=('TOPIX','NK225')
LABELS={'TOPIX':'TOPIXミニ','NK225':'日経マイクロ'}
TESTS=('金額利益65以上','赤字全場20以下','最大赤字は平均黒字以下')


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 完成した小JSONを同bytes一回で読み、表示に使った資料を指紋へ結ぶ。
    引数: path(Path) は保存資料の位置。
    返り値: tuple[dict,str] は内容とSHA256。大型cache・台帳・原板を読まない。
    """
    saved=path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def statistics_for(rows: list[dict], symbol: str) -> dict:
    """
    機能: 同商品33場の主金額、赤字頻度、平均黒字と最大赤字を再集計する。
    引数: rows(list[dict])、symbol(str) は保存済み共通schemaと商品。
    返り値: dict は表示用集計。平均黒字はセッションnetで、平均親利益ではない。
    """
    value=e01_trade_report.summarize(rows,symbol)
    selected=[r for r in rows if r['symbol']==symbol]
    positive=[r['net'] for r in selected if r['net']>0]
    mean=statistics.mean(positive) if positive else None
    worst=max([0.]+[-r['net'] for r in selected if r['net']<0])
    tests={TESTS[0]:value['profit_share'] is not None and value['profit_share']>=.65,
           TESTS[1]:value['negative']/len(selected)<=.2,
           TESTS[2]:mean is not None and worst<=mean}
    value.update(mean_positive_session_net=mean,worst_session_loss=worst,
        red_all=value['negative']/len(selected),red_active=value['negative']/value['active'] if value['active'] else None,
        tests=tests,pass_all=all(tests.values()))
    return value


def checked_goal(value: dict, expected: dict) -> None:
    """
    機能: 表示集計を根の最新三基準再集計に照合し、異なる定義の混入を拒否する。
    引数: value/expected(dict) は表示集計と同商品fullの保存根拠。
    返り値: None。未定義は0へ補完せず、数値と各達否を一致確認する。
    """
    fields={'profit':'profit','loss':'loss','net':'net','profit_share':'profit_share',
            'positive':'green','negative':'red','no_trade':'no_trade','active':'active',
            'mean_positive_session_net':'mean_green','worst_session_loss':'worst_red',
            'red_all':'red_all','red_active':'red_active'}
    for actual,target in fields.items():
        a,b=value[actual],expected[target]
        if a is None or b is None:assert a is b,(actual,a,b)
        else:assert abs(a-b)<1e-5,(actual,a,b)
    assert value['tests']==expected['tests'] and value['pass_all']==expected['pass_all']


def build(finance: dict, fixed: dict, plan: dict, goal: dict, sources: dict) -> dict:
    """
    機能: 四条件と比較元の表示会計を組み、金融・事前固定・最新目標へ束縛する。
    引数: finance/fixed/plan/goal/sources(dict) は完成小結果、固定資料と直接指紋。
    返り値: dict は公開JSON用値。新金融・注文比例換算・巨大台帳読取は行わない。
    """
    assert finance['全合格'] and fixed['全合格'] and goal['全合格']
    assert finance['source開始終端一致'] and finance['新GUengine']==132 and finance['会計口座数']==264
    assert finance['source_SHA256']==fixed['source_SHA256']==plan['spec']['implementation']
    assert sources[PLAN.relative_to(ROOT).as_posix()]==fixed['計画SHA256']
    assert sources[SOURCE.relative_to(ROOT).as_posix()]==goal['新金融元']['sha256']
    assert goal['新金融元']['path']==SOURCE.relative_to(ROOT).as_posix()
    assert finance['sessions']==fixed['sessions'] and finance['configs']==fixed['configs']
    sessions=finance['sessions'];assert len(sessions)==33
    configurations={c['id']:c for c in finance['configs']};assert len(configurations)==4
    assert set(configurations)==set(finance['results'])==set(goal['新候補'])
    cases={}
    for identifier,raw in finance['results'].items():
        rows=[e01_trade_report.mapped(r) for r in raw['rows']]
        assert len(rows)==66 and len({(r['session'],r['symbol']) for r in rows})==66
        assert {r['session'] for r in rows}==set(sessions)
        summary={s:statistics_for(rows,s) for s in SYMBOLS}
        for symbol in SYMBOLS:
            checked_goal(summary[symbol],goal['新候補'][identifier]['symbols'][symbol]['full'])
            saved=raw['symbols'][symbol];value=summary[symbol]
            for a,b in (('profit','利益'),('loss','損失'),('net','収支'),('winning_lots','勝ち枚数'),('losing_lots','負け枚数')):
                assert abs(value[a]-saved[b])<1e-5,(identifier,symbol,a)
            assert abs(value['top3_excluded']-saved['上位3利益場除外収支'])<1e-5
            assert abs(raw['actual_leg_symbols'][symbol]['収支']-value['net'])<1e-5
        cases[identifier]=dict(config=configurations[identifier],rows=rows,summary=summary,
            diagnosis=finance['diagnosis'][identifier],actual_legs=raw['actual_leg_symbols'],
            top3={s:goal['新候補'][identifier]['symbols'][s]['without_top3'] for s in SYMBOLS})
    both_black=sum(all(c['summary'][s]['net']>0 for s in SYMBOLS) for c in cases.values())
    both_pass=sum(all(c['summary'][s]['pass_all'] for s in SYMBOLS) for c in cases.values())
    assert both_black==both_pass==0
    old=[]
    for mode,symbol in (('VETO','TOPIX'),('CONFIRM','NK225')):
        identifier=next(k for k,c in configurations.items() if c['mode']==mode and c['profit_ticks']==1)
        reference=fixed['comparisons'][identifier]['旧P1L8']
        rows=[e01_trade_report.mapped(r) for r in reference['rows']]
        old.append(dict(id=reference['id'],symbol=symbol,summary=statistics_for(rows,symbol),
            reference_kind='保存した商品別代表。新数量条件とは枚数・停止予算が違う。'))
    return dict(全合格=True,title=TITLE,sessions=sessions,cases=cases,old_representatives=old,
        both_net_positive=both_black,both_goal_pass=both_pass,表示条件=4,表示口座=264,
        sources=sources,金融source_SHA256=finance['source_SHA256'],根拠範囲=dict(主金額='完結実親net正負合計',
            実玉副表='部分返済玉の実新規料配分及び返済料控除後net正負。親数欄はここだけ実決済玉数。',
            枚数='実決済玉の勝ち枚数・負け枚数。新規枚数と同一ではない。'),
        比較引用={k:{label:ref['id'] for label,ref in fixed['comparisons'][k].items()} for k in cases},
        新金融再生=0,大型input読取=0,巨大ledger読取=0,原板読取=0,NPZ読取=0,API取得=0)


# ----------------------------------------
def percent(value: float|None) -> str:
    """
    機能: 未定義を保持して割合を小数一桁へ表示する。
    引数: value(float|None) は0〜1の割合又は未定義。
    返り値: str はHTML用の表示文字。
    """
    return '—' if value is None else range_report.number(value*100,1)+'%'


def label(config: dict) -> str:
    """
    機能: 固定四条件を短い日本語名へ対応させる。
    引数: config(dict) は母gateと利益目標を持つ条件。
    返り値: str は表示名。元IDは別途保持する。
    """
    return ('同方向確認' if config['mode']=='CONFIRM' else '強い逆票回避')+'・P'+str(config['profit_ticks'])


def overview(data: dict) -> str:
    """
    機能: 四条件・二商品の総収支と最新三基準を同じ表で明示する。
    引数: data(dict) は検算済み公開会計。
    返り値: str は8行の概要表。赤字率は33場分母と活動場分母を分ける。
    """
    body=[]
    for identifier,case in data['cases'].items():
        for symbol in SYMBOLS:
            value=case['summary'][symbol]
            tests=' / '.join('達成' if value['tests'][k] else '未達' for k in TESTS)
            body.append('<tr data-case-id="'+html.escape(identifier,quote=True)+'" data-symbol="'+symbol+'"><td>'+label(case['config'])+
                '<small>'+html.escape(identifier)+'</small></td><td>'+LABELS[symbol]+'</td>'+range_report.cell(value['net'])+
                '<td>'+percent(value['profit_share'])+'</td><td>'+str(value['negative'])+'/33 ('+percent(value['red_all'])+')</td>'+ 
                '<td>'+percent(value['red_active'])+'</td><td>'+str(value['no_trade'])+'</td><td>'+range_report.number(value['mean_positive_session_net'],1)+
                '</td>'+range_report.cell(value['worst_session_loss'],True)+'<td>'+tests+'</td></tr>')
    return '<div class="scroll"><table id="overview"><thead><tr><th>条件</th><th>商品</th><th>総収支（円）</th><th>金額利益割合</th><th>赤字/全33場</th><th>赤字/活動場</th><th>無取引場</th><th>平均黒字場net（円）</th><th>最大赤字場（円）</th><th>割合 / 赤字率 / 一場損失</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


def explanation(config: dict) -> str:
    """
    機能: 数量制御の入口・途中・出口を三行へ要約する。
    引数: config(dict) は結果前に固定した条件。
    返り値: str は短い日本語HTML。予定損失を実損失保証とは呼ばない。
    """
    entry='同方向の更新が2票以上・方向釣合い25%以上の候補だけ許す。' if config['mode']=='CONFIRM' else '反対方向の更新が2票以上・方向釣合い25%以上の候補を見送る。不明や中立は元どおり。'
    goals=config['profit_goal_yen'];loss=config['loss_budget_yen']
    return ('<p><b>入口：</b>元E01の候補で直近60代理秒の票を使い、'+entry+
        '公開時のATR・気配差・実料と残予算から、TOPIX最大5枚・日経最大10枚まで数量を決め、次正常気配で新規。</p>'
        '<p><b>途中：</b>元の仮想5枚/10枚の判断は維持する。実玉の部分返済は累積返済割合を整数へ切り下げ、最後は残玉全返済。数量0や未知ならその候補を見送る。</p>'
        '<p><b>出口：</b>元E01の返済を維持し、場の費用後清算利益がTOPIX'+range_report.number(goals['TOPIX'])+'円・日経'+range_report.number(goals['NK225'])+
        '円、又は損失がTOPIX'+range_report.number(loss['TOPIX'])+'円・日経'+range_report.number(loss['NK225'])+'円へ先に達したら、次正常気配で残玉を返済し、その場の新規を終了。</p>')


def details(case: dict, old: list[dict]) -> str:
    """
    機能: 大勝ち除外・数量出口の五寄与・実玉副表を折り畳んで表示する。
    引数: case(dict)、old(list[dict]) は選択条件と保存した旧商品別代表。
    返り値: str は補足HTML。旧代表を同枚数や純粋出口差と呼ばない。
    """
    trim=[]
    for symbol in SYMBOLS:
        v=case['summary'][symbol];t=case['top3'][symbol]
        trim.append('<tr><td>新数量条件</td><td>'+LABELS[symbol]+'</td>'+range_report.cell(v['median'])+range_report.cell(t['net'])+
            '<td>'+percent(t['profit_share'])+'</td><td>'+str(t['red'])+'/'+str(t['sessions'])+'</td><td>'+range_report.number(t['mean_green'],1)+
            '</td>'+range_report.cell(t['worst_red'],True)+'</tr>')
    for v in old:
        s=v['summary'];trim.append('<tr><td>旧代表 '+html.escape(v['id'])+'</td><td>'+LABELS[v['symbol']]+'</td>'+range_report.cell(s['median'])+
            range_report.cell(s['top3_excluded'])+'<td colspan="4">数量と損失枠が異なる保存比較</td></tr>')
    more='<details><summary>大勝ちへの依存と中央値</summary><div class="scroll"><table><thead><tr><th>比較</th><th>商品</th><th>全33中央値</th><th>利益上位3場除外収支</th><th>除外後金額割合</th><th>除外後赤字場</th><th>除外後平均黒字net</th><th>除外後最大赤字</th></tr></thead><tbody>'+''.join(trim)+'</tbody></table></div></details>'
    change=[]
    fields=('収支変化','避けた基準損失','失った基準利益','共通入口の数量/出口差','新たな入口の収支')
    for symbol in SYMBOLS:
        for kind,d in case['diagnosis'][symbol].items():
            change.append('<tr><td>'+LABELS[symbol]+'</td><td>'+kind+'</td>'+''.join(range_report.cell(d[f],f=='失った基準利益') for f in fields)+
                '<td>'+str(d['元勝ち親が赤字化'])+'</td></tr>')
    more+='<details><summary>旧条件との差と失った利益（円）</summary><p class="note">同じpaper親でも、数量・部分返済の整数丸め・料金・停止時点が変わる。共通親差を出口だけの効果とは扱わない。</p><div class="scroll"><table><thead><tr><th>商品</th><th>比較元</th><th>収支差</th><th>避けた損失</th><th>失った利益</th><th>共通親の数量/出口差</th><th>新後続の収支</th><th>元勝ち親の赤字化</th></tr></thead><tbody>'+''.join(change)+'</tbody></table></div></details>'
    legs=[]
    for symbol in SYMBOLS:
        p=case['summary'][symbol];l=case['actual_legs'][symbol]
        legs.append('<tr><td>'+LABELS[symbol]+'</td>'+range_report.cell(p['profit'])+range_report.cell(p['loss'],True)+
            '<td>'+percent(p['profit_share'])+'</td>'+range_report.cell(l['利益'])+range_report.cell(l['損失'],True)+
            '<td>'+percent(l['利益割合'])+'</td><td>'+str(l['実決済玉数'])+'</td></tr>')
    return more+'<details><summary>完結親の主評価と部分返済玉の副評価</summary><p class="note">主評価は一新規から全返済までの親net。副評価は部分返済ごとの料配分後netで、正負の相殺範囲が違う。副表の玉数は枚数ではない。</p><div class="scroll"><table><thead><tr><th>商品</th><th>親利益</th><th>親損失</th><th>親金額割合</th><th>玉利益</th><th>玉損失</th><th>玉金額割合</th><th>実決済玉数</th></tr></thead><tbody>'+''.join(legs)+'</tbody></table></div></details>'


def render(data: dict) -> str:
    """
    機能: 四条件固定切替、主要八行と全33場を自己完結の暗色HTMLへ描画する。
    引数: data(dict) は指紋と会計を検算した公開値。
    返り値: str はHTML。通信・取引・金融再生を含まない。
    """
    options=[];sections=[]
    for identifier,case in data['cases'].items():
        options.append('<option value="'+html.escape(identifier,quote=True)+'">'+html.escape(label(case['config'])+' — '+identifier)+'</option>')
        table=trade_report.session_table(case,data['sessions'])
        table=table.replace('TOPIXミニ：5枚・上限10枚','TOPIXミニ：新規1〜5枚・上限10枚')
        table=table.replace('日経マイクロ：10枚・上限20枚','日経マイクロ：新規1〜10枚・上限20枚')
        sections.append('<section data-case="'+html.escape(identifier,quote=True)+'" hidden><h2>'+html.escape(label(case['config']))+
            '<small>'+html.escape(identifier)+'</small></h2>'+explanation(case['config'])+details(case,data['old_representatives'])+table+'</section>')
    css='*{box-sizing:border-box}body{background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui;margin:0}main{max-width:1400px;margin:auto;padding:24px 20px}h1{font-size:26px}h2{font-size:21px}p{margin:10px 0}small{display:block;color:#aebed4;font-size:12px;overflow-wrap:anywhere}a{color:#91c2ff}.note{color:#b0bed1}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1150px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #35445c;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;min-width:0;background:#18263b;color:#dce4f2;border:1px solid #74839b;padding:12px;font-size:15px}section{border:1px solid #35445c;border-radius:10px;padding:20px;margin:20px 0}section[hidden]{display:none}details{margin:12px 0}summary{cursor:pointer;color:#bad1ef}@media(max-width:600px){main{padding:16px 12px}h1{font-size:23px}section{padding:12px}}'
    first=next(iter(data['cases']))
    script='''/**
 * 機能: 固定した四条件から一つの説明と全33場会計を表示する。
 * @param {string} id - 保存した条件ID。
 * @returns {undefined} 表示だけを更新し、取引や通信を行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase('''+json.dumps(first)+''');'''
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+
        '</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1><p><b>両商品がともに黒字の条件は0/4件。最新の三基準を両商品で満たす条件も0/4件でした。</b></p>'
        '<p>逆票回避・P2は両商品の「最大赤字≦平均黒字」を満たした一方、どちらも赤字が15/33場。数量を減らしても、安定して利益を積む解には届いていません。</p>'
        '<p class="note">判定順：金額利益割合65%以上 / 赤字セッション20%以下 / 最大赤字が平均黒字1場以下。金額は手数料後、平均黒字はセッションnet。無取引は勝ちに含めない。</p>'+
        overview(data)+'<select id="case" aria-label="予定リスク数量の四条件">'+''.join(options)+'</select>'+''.join(sections)+
        '<details><summary>なぜ少枚数でも負けたか：同じ入口の二例</summary><p>固定円の利益目標を維持したため、少枚数では必要値幅が大きくなった。下表の旧条件は初回5枚/10枚・P1L8、新条件は逆票回避P2・予定リスク数量で、数量と出口予算が異なる。旧の利益を新手法の実現利益へ置き換えた比較ではない。</p>'
        '<div class="scroll"><table id="loss-examples"><thead><tr><th>商品・場</th><th>新規</th><th>旧が返済した時の新口座</th><th>旧条件の実利益</th><th>新条件の実返済</th></tr></thead><tbody>'
        '<tr><td>TOPIX・9/29ナイト</td><td>19:21:02 買1枚 @4,067</td><td>19:24:34 +918円（目標5,000円）</td><td>5枚 +4,582円</td><td>19:41:57 @4,063 / −4,082円</td></tr>'
        '<tr><td>日経・10/5デイ</td><td>10:31:00 買1枚 @70,170</td><td>10:33:03 +278円（目標2,000円）</td><td>10枚 +2,780円</td><td>11:59:06 @70,070 / −1,022円</td></tr>'
        '</tbody></table></div><p>一方、TOPIX9/24ナイト翌00:21:43の売りと日経9/30ナイト21:35:19の買いは、実親の清算評価が一度もプラスにならなかった。全損失を利確の遅さだけで説明できない。後続再参加が損失を増やす例も残る。</p></details>'
        '<p class="note">予定リスクは「公開ATR＋気配差」と注文別実料で計算し、残予算内の整数枚数を選ぶ。元paperの停止幅0.75ATRとは別の1ATR尺度で、損失上限の保証ではない。次の比較は初回受理枚数に合わせて利確目標だけを下げる。損失予算は据え置き、利益平均の縮小も検証する。</p>'
        '<p class="note">利益・損失は完結実親のnet正負、勝ち/負け枚数は実決済玉の枚数。票の60秒は価格時計の代理秒。ラージ気配を使い、実ミニ/マイクロ板・待ち順位は未測。既知33場での再検証で、未見相場の成功確認ではない。</p>'
        '<p><a href="README.md">調査状況</a> · <a href="予定リスク数量4比較の公開会計.json">表示会計と資料指紋</a></p></main><script>'+script+'</script></body></html>')


# ----------------------------------------
def run(destination: Path) -> None:
    """
    機能: 根が明示的に実行した時だけ、完成小会計からHTMLと公開JSONを作る。
    引数: destination(Path) は根が指定する公開又は検査用の保存先。
    返り値: None。源と固定の指紋を確認し、金融・巨大入力読取は実行しない。
    """
    values={};sources={}
    for path in (SOURCE,FIXED,PLAN,GOAL,DIAGNOSIS):
        value,sha=read(path);values[path]=value;sources[path.relative_to(ROOT).as_posix()]=sha
    finance=values[SOURCE]
    for relative,expected in finance['source_SHA256'].items():
        actual=hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
        assert actual==expected,(relative,actual,expected)
    value=build(finance,values[FIXED],values[PLAN],values[GOAL],sources)
    diagnosis=values[DIAGNOSIS]
    assert diagnosis['全合格'] and diagnosis['条件ID']=='E01_SIZE_W60_VETO_D0_P2_L2_A1'
    expected={
        '2026-09-29_Night|TOPIX':(4582.,-4082.,918.),
        '2026-10-05_Day|NK225':(2780.,-1022.,278.),
    }
    for key,(old_net,new_net,mark) in expected.items():
        case=diagnosis['場別'][key]['旧勝ち赤字化の事後参考']
        assert case['旧親']['収支']==old_net and case['新親']['収支']==new_net
        assert case['旧返済判断時の新実口座清算']==mark
        assert case['同一公開及び実新規']
    value['損失診断の表示検査']=True
    value['表示source_SHA256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__).resolve(),HERE/'e01_trade_report.py',HERE/'trade_report.py',HERE/'range_report.py')}
    document=render(value)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/ACCOUNTING_TITLE).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    (destination/(TITLE+'.html')).write_text(document,encoding='utf-8',newline='\n')
    print(json.dumps(dict(全合格=True,表示条件=4,表示口座=264,両商品黒字=value['both_net_positive'],両商品三基準達成=value['both_goal_pass'],新金融再生=0),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=PUBLIC)
    args=parser.parse_args();run(args.output_dir)
