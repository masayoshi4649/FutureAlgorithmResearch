"""E01公開時確認24・小利益予算18・保存比較4を短い説明と全33場へ表示する。"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import statistics

import range_report
import trade_report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=range_report.PUBLIC
TITLE='E01の取引更新と損失幅の改善及び全セッション損益'
ACCOUNTING_TITLE='E01取引更新と損失予算の公開会計.json'
TRADE_SOURCE=HERE/'e01_trade_gate/finance/結果.json'
BUDGET_SOURCE=HERE/'e01_trade_budget/finance/結果.json'
BASELINE_SOURCE=HERE/'e01_trade_gate/金融事前固定.json'
SYMBOLS=('TOPIX','NK225')
HEAD_CASES=(('E01_TRADE_W60_VETO_D0_P1L8','商品別の代表：TOPIX'),
            ('E01_TRADE_W60_CONFIRM_D0_P1L8','商品別の代表：日経'),
            ('E01_BUDGET_W60_VETO_D0_P1_L4','小損失予算で勝ちも切った比較'),
            ('E01_BUDGET_W60_CONFIRM_D0_P1_L4','小損失予算で勝ちも切った比較'))


def mapped(row: dict) -> dict:
    """
    機能: 日本語の親会計と実決済枚数を、既存全場表の共通schemaへ対応させる。
    引数: row(dict)は保存済み同商品同場の会計。
    返り値: dictはprofit/loss/net/campaigns/勝負枚数。新金融を計算しない。
    """
    value=dict(session=row['session'],symbol=row['symbol'],profit=float(row['利益']),loss=float(row['損失']),net=float(row['収支']),
        campaigns=int(row['親数']),winning_campaigns=int(row['勝ち親']),losing_campaigns=int(row['負け親']),
        winning_lots=int(row['勝ち枚数']),losing_lots=int(row['負け枚数']),fees=float(row['費用']))
    assert abs(value['profit']-value['loss']-value['net'])<1e-5
    return value


def summarize(rows: list[dict], symbol: str) -> dict:
    """
    機能: 不変range_reportの同商品会計を再利用し、活動中央値と利益場だけの除外を補足する。
    引数: rows(list[dict])、symbol(str)は共通schemaと対象。
    返り値: dictは表示会計。活動場と無取引込みの中央値を区別する。
    """
    value=range_report.summary(rows,symbol);selected=[r for r in rows if r['symbol']==symbol]
    active=[r for r in selected if r['campaigns']>0];positive=sorted([r['net'] for r in selected if r['net']>0],reverse=True)
    value.update(active_median=statistics.median(r['net'] for r in active) if active else None,
        active_positive_rate=value['positive']/value['active'] if value['active'] else None,
        top3_excluded=sum(r['net'] for r in selected)-sum(positive[:3]),
        average_payoff=value['average_win']/value['average_loss'] if value['average_win'] is not None and value['average_loss'] not in (None,0) else None)
    return value


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 小さい完成結果を同bytes一回で読み、指紋を残す。
    引数: path(Path)は保存JSON。
    返り値: tuple[dict,str]は結果とSHA256。巨大ledgerや生板を読まない。
    """
    saved=path.read_bytes();return json.loads(saved),hashlib.sha256(saved).hexdigest()


def build(trade: dict, budget: dict, base: dict, sources: dict) -> dict:
    """
    機能: 24＋18＋保存4比較を重複明示の46選択肢へまとめ、共通目標を動的に判定する。
    引数: trade/budget/base/sources(dict)は完成小会計と元比較・指紋。
    返り値: dictは公開会計用値。予算alias2は別の独立証拠に数えない。
    """
    assert trade['全合格'] and budget['全合格'] and base['全合格']
    sessions=trade['sessions'];assert len(sessions)==33 and budget['sessions']==sessions
    configs={c['id']:c for c in trade['configs']};bconfigs={c['id']:c for c in budget['configs']}
    assert len(configs)==24 and len(bconfigs)==18
    cases={}
    for kind,source,configuration in (('入口確認',trade,configs),('損失予算',budget,bconfigs)):
        for identifier,value in source['results'].items():
            rows=[mapped(r) for r in value['rows']];assert len(rows)==66
            assert len({(r['session'],r['symbol']) for r in rows})==66
            config=configuration[identifier]
            cases[identifier]=dict(kind=kind,config=config,rows=rows,summary={s:summarize(rows,s) for s in SYMBOLS},
                saved_alias=bool(config.get('saved_alias',False)),alias_source_id=config.get('baseline_id') if config.get('saved_alias',False) else None,
                diagnosis=source['diagnosis'][identifier])
    comparators=(('D0_GU','保存比較：元E01 成行・元出口'),('D20_GU','保存比較：元E01 0.2ATR指値・元出口'),
                 ('D20_P1L8','保存比較：元E01 0.2ATR指値・小利益停止'))
    for key,label in comparators:
        value=base['基準'][key];identifier='BASE_'+key;rows=[mapped(r) for r in value['rows']]
        cases[identifier]=dict(kind='保存比較',label=label,config=dict(execution='D0' if key.startswith('D0') else 'D20',exit='P1L8' if key.endswith('P1L8') else 'GU'),
            rows=rows,summary={s:summarize(rows,s) for s in SYMBOLS},saved_alias=True,alias_source_id=value['id'],diagnosis=None)
    value=trade['new_D0_P1L8'];rows=[mapped(r) for r in value['rows']]
    cases['BASE_D0_P1L8']=dict(kind='保存比較',label='保存比較：元E01 成行・小利益停止',config=dict(execution='D0',exit='P1L8'),
        rows=rows,summary={s:summarize(rows,s) for s in SYMBOLS},saved_alias=True,alias_source_id='完成新D0_P1L8基準',diagnosis=None)
    assert len(cases)==46
    for c in bconfigs.values():
        if c['saved_alias']:
            before=cases[c['baseline_id']];after=cases[c['id']]
            assert after['rows']==before['rows'] and after['summary']==before['summary'],c['id']
    for identifier,label in HEAD_CASES:assert identifier in cases
    candidates=[c for c in cases.values() if c['kind']!='保存比較' and not c['saved_alias']]
    money80=sum(all(c['summary'][s]['net']>0 and c['summary'][s]['profit_share'] is not None and c['summary'][s]['profit_share']>=.8 for s in SYMBOLS) for c in candidates)
    all33=sum(all(c['summary'][s]['positive']==33 and c['summary'][s]['profit_share'] is not None and c['summary'][s]['profit_share']>=.8 for s in SYMBOLS) for c in candidates)
    robust=sum(all(c['summary'][s]['top3_excluded']>0 for s in SYMBOLS) for c in candidates)
    return dict(sessions=sessions,cases=cases,head=list(HEAD_CASES),target_count=all33,both_money80_count=money80,both_top3_positive_count=robust,
        counts=dict(入口確認24表示=24,予算18表示=18,元保存比較=4,総表示=46,予算内保存重複=2,予算新政策会計=1056,予算engine再生=0),
        sources=sources,新金融再生=0,原板読取=0,巨大ledger読取=0,API取得=0,未見セッション成功確認=0)


def explanation(case: dict) -> str:
    """
    機能: 元E01と追加自己票/場内停止を、平易な入口・途中・出口の三行へ要約する。
    引数: case(dict)は一つの表示条件。
    返り値: strは日本語HTML。固定時間保有や架空清算を説明に加えない。
    """
    cfg=case['config'];execution=cfg['execution'];order='公開判断の次の正常気配で成行新規。' if execution=='D0' else '判断時価格から0.2ATR有利な指値で待ち、公開後の最初の正常気配到達で新規。'
    if case['kind']=='保存比較':entry='元E01の買い・売り候補をそのまま使う。'+order
    elif cfg['mode']=='CONFIRM':entry=f'元E01候補で、直近{cfg.get("window_seconds",60)}代理秒に新規方向の取引更新票が2回以上・方向釣合い25%以上なら入る。'+order
    else:entry=f'元E01候補で、直近{cfg.get("window_seconds",60)}代理秒に反対方向の取引更新票が2回以上・方向釣合い25%以上なら見送る。不明や中立は元の候補どおり。'+order
    middle='票は新規公開時だけ使う。保有中の判断・未約定取消・部分返済・返済期限は元E01のまま。'
    stopped=case['kind']=='損失予算' or cfg.get('exit')=='P1L8'
    if stopped:
        p=cfg.get('profit_ticks',1);loss=cfg.get('loss_ticks',8)
        exit_text=f'口座の費用後清算利益が初回{p}呼値分に達するか、損失が{loss}呼値分に達したら、その場の新規を止める。残玉は次の正常気配で建玉ごとに全返済。'
    else:exit_text='元E01の損切り・追尾・部分返済と場内返済期限を使う。'
    return '<p><b>入口：</b>'+entry+'</p><p><b>途中：</b>'+middle+'</p><p><b>出口：</b>'+exit_text+'</p>'


def comparison(case: dict, symbol: str, label: str, identifier: str) -> str:
    """
    機能: 代表又は悪化比較の金額割合と活動/大勝ち依存を一行表示する。
    引数: case(dict)、symbol/label/identifier(str)は会計・商品・比較名・ID。
    返り値: strは暗色比較表の一行。
    """
    s=case['summary'][symbol];pct='—' if s['profit_share'] is None else range_report.number(s['profit_share']*100,1)+'%'
    median='<td>—</td>' if s['active_median'] is None else range_report.cell(s['active_median'])
    return '<tr><td>'+html.escape(label)+'<small>'+html.escape(identifier)+'</small></td><td>'+('TOPIXミニ' if symbol=='TOPIX' else '日経マイクロ')+'</td>'+range_report.cell(s['net'])+f'<td>{s["positive"]}/{s["negative"]}/{s["no_trade"]}</td><td>'+pct+'</td><td>'+range_report.number(s['pf'],2)+'</td>'+median+range_report.cell(s['top3_excluded'])+range_report.cell(s['worst'])+'</tr>'


def diagnosis_table(case: dict) -> str:
    """
    機能: 同じ枚数の基準との5寄与と、元勝ち親の赤字化件数を表示する。
    引数: case(dict)は保存診断を持つ条件。
    返り値: strは差分表又は空文字。事後寄与を当時判定条件へ混ぜない。
    """
    if not case['diagnosis']:return ''
    rows=[]
    for s in SYMBOLS:
        d=case['diagnosis'][s];values=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
        cells=''.join(range_report.cell(d[k],k=='失った基準利益') for k in values)
        turned=d.get('元勝ち親が赤字化');cells+='<td>'+('—' if turned is None else str(turned))+'</td>'
        rows.append('<tr><td>'+s+'</td>'+cells+'</tr>')
    source='対応する完成P1L8' if case['kind']=='損失予算' else '同じ成行/指値と出口の元E01'
    return '<details><summary>'+source+'との差（事後診断）</summary><div class="scroll"><table><thead><tr><th>商品</th><th>収支変化</th><th>避けた損失</th><th>失った利益</th><th>共通親の出口差</th><th>新後続の収支</th><th>元勝ち親の赤字化</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></details>'


def render(data: dict) -> str:
    """
    機能: 代表二つ・悪化比較二つと46切替を、短いダークHTMLへ描画する。
    引数: data(dict)は検算済み表示会計。
    返り値: strは自己完結HTML。売買や外部通信は含まない。
    """
    cases=data['cases'];head=[]
    for identifier,label in data['head']:
        for symbol in SYMBOLS:head.append(comparison(cases[identifier],symbol,label,identifier))
    options=[];sections=[]
    for identifier,case in cases.items():
        alias='<p class="note">保存経済の再利用：'+html.escape(case['alias_source_id'] or '')+'。予算P1L8二つは入口確認24内と同じ結果で、新しい成功証拠ではありません。</p>' if case['saved_alias'] else ''
        name=case.get('label',identifier)
        options.append('<option value="'+html.escape(identifier,quote=True)+'">'+html.escape(name)+'</option>')
        sections.append('<section data-case="'+html.escape(identifier,quote=True)+'" hidden><h2>'+html.escape(name)+'</h2>'+alias+explanation(case)+diagnosis_table(case)+trade_report.session_table(case,data['sessions'])+'</section>')
    target=data['target_count'];money=data['both_money80_count'];robust=data['both_top3_positive_count']
    conclusion=('同じ条件で両商品とも「全33黒字＋金額利益80%」を満たすものは'+str(target)+'件。'
        '金額利益80%だけでは'+str(money)+'件、利益上位3場を除いて両商品黒字は'+str(robust)+'件です。')
    css='*{box-sizing:border-box}body{background:#0b1120;color:#dce4f2;font:16px/1.65 system-ui;margin:0}main{max-width:1360px;margin:auto;padding:26px 20px}h1{font-size:26px}h2{font-size:20px;overflow-wrap:anywhere}p{margin:10px 0}small{display:block;font-size:12px;color:#afbed5}.note{color:#aab9d0}a{color:#8fbeff}.scroll{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;min-width:1120px;width:100%;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}th{background:#1d2c43}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.total{font-weight:bold;background:#1d2c43!important}select{width:100%;max-width:1100px;min-width:0;background:#18263b;color:#dce4f2;border:1px solid #72819a;padding:12px;font-size:15px}section{border:1px solid #33425a;padding:20px;border-radius:10px;margin:22px 0}section[hidden]{display:none}details summary{cursor:pointer;color:#b6caff}@media(max-width:600px){main{padding:16px 12px}section{padding:12px}h1{font-size:23px}}'
    script='''/**
 * 機能: 保存した一つの手法の説明と全33場損益を切り替える。
 * @param {string} id - 保存条件ID。
 * @returns {undefined} 表示のみ更新する。売買・通信は行わない。
 */
function showCase(id){for(const node of document.querySelectorAll('[data-case]'))node.hidden=node.dataset.case!==id;document.getElementById('case').value=id;}
document.getElementById('case').addEventListener('change',event=>showCase(event.target.value));showCase('E01_TRADE_W60_VETO_D0_P1L8');'''
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1><p><b>'+conclusion+'</b></p><p><a href="../00044_新候補2手法と基準の説明と損益/新候補2手法の説明と損益.html">元E01の入口・途中・出口の説明</a>。今回の追加は、新規公開時の取引更新確認と、口座の利益・損失予算です。</p><p>商品別ではTOPIXの逆向き票の見送りと、日経の同方向票確認が代表です。小さい損失予算は、利益へ回復する元の勝ちも切る比較として示します。</p><p class="note">初回TOPIXミニ5枚・上限10枚、日経マイクロ10枚・上限20枚。費用とラージ気配差込み。全33場は既知データで、将来の保証ではありません。</p><div class="scroll"><table id="comparison"><thead><tr><th>代表と比較</th><th>商品</th><th>収支（円）</th><th>黒字/赤字/無取引</th><th>金額利益割合</th><th>PF</th><th>活動中央値</th><th>上位3利益場除外</th><th>最悪場</th></tr></thead><tbody>'+''.join(head)+'</tbody></table></div><p>全46表示：入口確認24＋予算18＋保存比較4。予算内P1L8二つは入口確認内と同じ保存経済です。</p><select id="case" aria-label="手法と執行方式">'+''.join(options)+'</select>'+''.join(sections)+'<p class="note">利益・損失は全返済した親の手数料後金額、勝ち/負け枚数は実決済した玉の枚数です。金額利益割合＝利益÷（利益＋損失）。無取引は勝ちに含めません。予算は判断閾値で、次気配の悪化による損失上限を保証しません。初回1呼値分はTOPIX2,500円・日経1,000円の口座清算利益です。票の窓は価格時計の代理秒で受信秒ではなく、Last対直前BBOは攻撃方向の代理です。ミニ/マイクロの実板・待ち順位は未検証、未見の成功確認は0です。</p><p><a href="README.md">調査状況</a> · <a href="損失箇所と改善の記録.md">損失箇所</a> · <a href="E01で残った損失と改善の具体例.md">E01で残った損失と改善の具体例</a></p></main><script>'+script+'</script></body></html>'


def run(destination: Path) -> None:
    """
    機能: 完成24と18小結果だけを検算し、根の実行時に指定先へHTMLと公開会計を出す。
    引数: destination(Path)は根が指定する出力先。
    返り値: None。未完成budgetなら出力せず待機する。公共変更はこのCLIを根が実行した時だけ。
    """
    if not BUDGET_SOURCE.exists():print('損失予算18の結果未完成：出力待機。');return
    trade,tsha=read(TRADE_SOURCE);budget,bsha=read(BUDGET_SOURCE);base,sha=read(BASELINE_SOURCE)
    sources={str(p.relative_to(ROOT)).replace('\\','/'):s for p,s in ((TRADE_SOURCE,tsha),(BUDGET_SOURCE,bsha),(BASELINE_SOURCE,sha))}
    value=build(trade,budget,base,sources);document=render(value)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/ACCOUNTING_TITLE).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    (destination/(TITLE+'.html')).write_text(document,encoding='utf8',newline='\n')
    print(json.dumps(dict(全合格=True,表示条件=len(value['cases']),金額8割両商品=value['both_money80_count'],全33黒字と8割=value['target_count'],新金融再生=0),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,default=PUBLIC);args=parser.parse_args();run(args.output_dir)
