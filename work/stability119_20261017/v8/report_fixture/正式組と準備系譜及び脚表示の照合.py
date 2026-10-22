"""指定元を再読せず、正式公開小会計の全320行と保全コピーの原因診断を照合する。"""

from collections import Counter
import hashlib
import ast
import argparse
from decimal import Decimal, ROUND_FLOOR
import json
import math
from pathlib import Path
import statistics

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
V8=HERE.parent
BASE=V8.parent
ROOT=BASE.parents[1]
PUBLIC=BASE/'privatev8/public'
SOURCE_SHA=None
COUNTS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 正式表示又は独立足算の一致を記録する。
    引数: value(bool)は期待、label(str)は検査名。
    返り値: None。不一致は停止する。
    """
    assert value,label
    COUNTS[label]+=1


def near(a: float|None,b: float|None) -> bool:
    """
    機能: nullと金額の微小集計差を区別して比較する。
    引数: a/b(float|None)は比較値。
    返り値: boolは一致。金額の丸めは実会計へ戻さない。
    """
    return a is b if a is None or b is None else math.isclose(a,b,rel_tol=0,abs_tol=1e-5)


def fmt(value: float|None,signed: bool=False) -> str:
    """
    機能: 表示の期待文字列を独立に作る。
    引数: value(float|None)は数値、signed(bool)は符号指定。
    返り値: strは表示値又は—。
    """
    if value is None:return '—'
    if abs(value)<1e-7:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def check_lineage_and_money(ep: dict, row: dict, ci: dict, pi: dict) -> None:
    """
    機能: 原p46/prep21と注文14を結び、準備・予約・実会計を独立算数で照合する。
    引数: ep/row(dict)は保存episodeと場集計、ci/pi(dict[str,int])は列名対応。
    返り値: None。元quote又は金融を再生せず、未保存の確認価格を推測しない。
    """
    preps=ep['preparations'];parents=ep['parents'];orders=ep['orders']
    check(all(len(p)==21 for p in preps) and all(len(p)==46 for p in parents) and all(len(o)==14 for o in orders),'原p46/prep21/order14の全行型')
    byprep={int(p[pi['preparation_id']]):p for p in preps}
    check(len(byprep)==len(preps) and set(byprep)==set(range(len(preps))),'準備IDの一意性')
    state=[int(p[pi['state']]) for p in preps]
    check(all(v in (1,2,3,4) for v in state),'未予約準備も終端状態を保存')
    expected_counts=dict(preparations=len(preps),reserved_preparations=state.count(1),canceled_preparations=state.count(2)+state.count(3),unfinished_preparations=state.count(4))
    check(all(row[k]==v for k,v in expected_counts.items()) and row['attempts']==state.count(1),'準備予約取消EOFの全数対応')
    for p in preps:
        if p[pi['state']]!=1:
            check(all(v is None for v in p[10:19]),'未予約準備に架空qや損益を補完しない')
    complete=[p for p in parents if p[ci['complete']]==1]
    check(len(complete)==row['parents'] and sum(p[ci['net']]>1e-7 for p in complete)==row['wins'] and sum(p[ci['net']]<-1e-7 for p in complete)==row['losses'],'勝敗は完結した実親だけ')
    check(near(sum(max(p[ci['net']],0) for p in complete),row['profit']) and near(sum(max(-p[ci['net']],0) for p in complete),row['loss']),'親netの正負が場利益損失')
    check(near(sum(p[ci['net']] for p in parents),row['net']) and near(sum(o[9] for o in orders),row['fees']),'全親の時価netと全注文料が場会計')
    for parent in parents:
        prep=byprep[int(parent[ci['preparation_id']])];sgn=prep[pi['delta_sign']]
        check(prep[pi['state']]==1 and parent[ci['side_nk']]==-sgn,'準備方向を中心へ戻す実親へ対応')
        pairs=(('prepare_time','prepare_time'),('prepare_delta','prepare_delta'),('beta','beta'),('center','center'),('sigma','sigma'),('extreme_delta','extreme_delta'),('confirmation_clock_1','confirmation_clock_1'),('confirmation_clock_2','confirmation_clock_2'),('decision_time','reserve_time'),('entry_delta','reserve_delta'),('cash_loss_budget','cash_loss_budget'),('expected_center_gross','expected_center_gross'),('reserve_reference_nk','reference_nk'),('reserve_reference_top','reference_top'))
        check(all(near(parent[ci[a]],prep[pi[b]]) for a,b in pairs),'実親と準備の固定モデル極値二確認予約を同値連結')
        t0,t1,t2,tr=(prep[pi[k]] for k in ('prepare_time','confirmation_clock_1','confirmation_clock_2','reserve_time'))
        check(t0<t1<t2<=tr,'別二時計は準備後かつ実予約以前')
        sigma=prep[pi['sigma']];delta=prep[pi['reserve_delta']];extreme=prep[pi['extreme_delta']]
        check(sigma>0 and sgn*delta>=sigma-1e-12 and sgn*(extreme-delta)>=.5*sigma-1e-12,'予約残差一σと極値から半σの実戻り')
        qn,qt=(prep[pi[k]] for k in ('quantity_nk','quantity_top'))
        check(qn==int(qn) and qt==int(qt) and 1<=qn<=20 and 1<=qt<=10,'当時整数qと小口上限')
        fees=2*(int((Decimal(str(int(qn)))*Decimal('11')).to_integral_value(rounding=ROUND_FLOOR))+int((Decimal(str(int(qt)))*Decimal('41.8')).to_integral_value(rounding=ROUND_FLOOR)))
        nominal=qn*10*prep[pi['reference_nk']]
        check(near(prep[pi['cash_loss_budget']],sgn*(extreme-delta)*nominal+fees),'正の極値幅元本と明示往復料だけのcash予算')
        check(near(prep[pi['expected_center_gross']],abs(delta)*nominal) and prep[pi['expected_center_gross']]>=3*prep[pi['estimated_roundtrip_cost']]-1e-7,'予定中心利益と固定費用資格')
        own=[o for o in orders if int(o[0])==int(parent[ci['parent']])]
        paid=0
        for o in own:
            leg,kind,side,qty=int(o[1]),int(o[2]),int(o[3]),int(o[4])
            fee=int((Decimal(qty)*Decimal('11' if leg==0 else '41.8')).to_integral_value(rounding=ROUND_FLOOR));paid+=fee
            check(leg in (0,1) and kind in (1,2) and qty==(qn if leg==0 else qt) and o[9]==fee,'注文q固定とDecimal円未満切捨て')
            check(o[6]>o[5] and o[7]==int(o[7]),'注文は厳密な後clockの原row')
            expected_side=int(parent[ci['side_nk']])*(1 if leg==0 else -1)*(1 if kind==1 else -1)
            check(side==expected_side,'実新規返済の売買符号')
            check(near(o[5],parent[ci['decision_time' if kind==1 else 'exit_decision_time']]),'新規と返済の実判断時計')
        check(near(paid,parent[ci['fees_nk']]+parent[ci['fees_top']]),'親の実料は全注文の合計で予算と二重課金なし')
        if parent[ci['complete']]==1:
            gross=0
            for leg,name,multi in ((0,'nk',10),(1,'top',1000)):
                entered=[o for o in own if o[1]==leg and o[2]==1];exited=[o for o in own if o[1]==leg and o[2]==2]
                check(len(entered)==len(exited) and len(entered)<=1,'完結親の両脚各一新規一返済又は未約定')
                if entered:
                    en,x=entered[0],exited[0];value=en[3]*(x[8]-en[8])*en[4]*multi;gross+=value
                    check(near(en[8],parent[ci['entry_'+name]]) and near(x[8],parent[ci['exit_'+name]]) and near(value,parent[ci['gross_'+name]]),'実注文価格から脚grossを独立算数')
            check(near(gross-paid,parent[ci['net']]),'実注文grossと料金が完結親net')
    check(len(parents)<=state.count(1),'未予約取消を実親へ数えない')


def main() -> None:
    """
    機能: 自身公開会計とHTMLを照合し、保全自己コピーから原因節だけ一目的抽出する。
    引数: なし。
    返り値: None。指定原結果・入力・市場を再読せず、別QAと小statsだけ保存する。
    """
    global SOURCE_SHA
    parser=argparse.ArgumentParser();parser.add_argument('--expected-sha256',required=True);SOURCE_SHA=parser.parse_args().expected_sha256
    target=HERE/'正式320組とp46及びprep21の実表示照合.json';stats_path=BASE/'privatev8/八条件の小集計と相対共通費用分解.json'
    assert not target.exists() and not stats_path.exists()
    names=('data.json','相対乖離の復帰確認と残差追尾の全セッション損益.html','README.md','生成証跡.json')
    raw={name:(PUBLIC/name).read_bytes() for name in names};data=json.loads(raw['data.json']);generated=json.loads(raw['生成証跡.json'])
    page=BeautifulSoup(raw[names[1]].decode('utf8'),'html.parser')
    check(generated['passed'] is True and generated['fixture'] is False and generated['result_sha256']==SOURCE_SHA,'正式実会計版でfixture混同なし')
    check(data['source_SHA256']==SOURCE_SHA,'指定完成元SHA一致')
    for name,wanted in generated['artifacts'].items():check(hashlib.sha256(raw[name]).hexdigest()==wanted,'正式生成物のSHA一致')
    expected={'run_v8.py':'45a10846c384cb66ef6d55b381308748180a679d6b22da57dcf246fbea04675f','plan_v8.py':'05f3d543d693441106718d3b40e6ec6eb0d2148cebc84d9493eb029d7148710e','engine_v8.py':'499d00b4fd88418ee1e3a6894d64eb31fe95b25479403e8f9bb106a51d07b1fc'}
    expected_paths={(V8/name).relative_to(ROOT).as_posix():value for name,value in expected.items()}
    check(data['economic_source_SHA256']==expected_paths,'共同clock最終三源の結果結合')
    for name,value in expected.items():check(hashlib.sha256((V8/name).read_bytes()).hexdigest()==value,'共同clock最終三源の現物一致')
    scenes=data['sessions'];cases=data['cases'];rows={};metrics={};legmetrics={}
    check(len(scenes)==40 and scenes[0]=='2026-09-21_Day' and scenes[-1]=='2026-10-16_Night' and len(cases)==8,'正式八政策四十場')
    for ident,case in cases.items():
        check(len(case['rows'])==40,'一政策四十組会計')
        for row in case['rows']:
            check(row['symbol']=='PAIR' and (ident,row['session']) not in rows,'二脚を単商品口座へ変えない');rows[ident,row['session']]=row
        rr=[rows[ident,s] for s in scenes];net=[r['net'] for r in rr]
        positive=[r['net'] for r in rr if not r['unclosed'] and r['fills'] and r['net']>1e-7]
        negative=[-r['net'] for r in rr if not r['unclosed'] and r['fills'] and r['net']<-1e-7]
        inactive=sum(r['fills']==0 and not r['unclosed'] for r in rr);unclosed=sum(r['unclosed']>0 for r in rr)
        p=sum(r['profit'] for r in rr);loss=sum(r['loss'] for r in rr);median=statistics.median(net);meanabs=statistics.mean(abs(v) for v in net)
        m=dict(net=sum(net),profit=p,loss=loss,fees=sum(r['fees'] for r in rr),parents=sum(r['parents'] for r in rr),black=len(positive),red=len(negative),inactive=inactive,unclosed_sessions=unclosed,
            mean=statistics.mean(net),median=median,worst=min(net),top3_removed=None if unclosed else sum(net)-sum(sorted(positive,reverse=True)[:3]),share=p/(p+loss) if p+loss else None,
            normalized_median=median/meanabs if meanabs else None,worst_to_mean_black=max(negative,default=0)/statistics.mean(positive) if positive else None,
            paired_parents=sum(r['paired_parents'] for r in rr),aborted_parents=sum(r['aborted_parents'] for r in rr),no_fill_attempts=sum(r['no_fill_attempts'] for r in rr))
        for field in ('preparations','reserved_preparations','canceled_preparations','unfinished_preparations'):m[field]=sum(r[field] for r in rr)
        for k,v in m.items():check(near(case['metrics']['PAIR'][k],v),'組会計と安定性の独立集計')
        metrics[ident]=m;legmetrics[ident]={}
        for symbol in ('NK225','TOPIX'):
            lm={k:sum(r['legs'][symbol][k] for r in rr) for k in ('gross','fees','net','realized','unrealized_after_close_fees','fills','entry_quantity','closed_quantity')}
            lm['unclosed_sessions']=sum(r['legs'][symbol]['unclosed']>0 for r in rr)
            for k,v in lm.items():check(near(case['legs'][symbol][k],v),'脚gross料金netの独立集計')
            legmetrics[ident][symbol]=lm
        check(near(sum(lm['net'] for lm in legmetrics[ident].values()),m['net']) and near(sum(lm['fees'] for lm in legmetrics[ident].values()),m['fees']),'脚合計と組の一致')
    tables=page.select('table.sessions');check(len(tables)==8 and {t['data-method'] for t in tables}==set(cases),'全八政策掲載')
    for table in tables:
        ident=table['data-method'];trs=table.select('tbody tr');check(len(trs)==40,'全四十場を省略しない')
        for tr,scene in zip(trs,scenes):
            r=rows[ident,scene];values=[fmt(r['profit']),fmt(r['loss']),fmt(r['net'],True),str(r['parents'])]
            for symbol in ('NK225','TOPIX'):values.extend([fmt(r['legs'][symbol]['gross'],True),fmt(r['legs'][symbol]['fees']),fmt(r['legs'][symbol]['net'],True)])
            values.extend([str(r['aborted_parents']),str(r['no_fill_attempts']),str(r['unclosed'])]+[str(r[k]) for k in ('preparations','reserved_preparations','canceled_preparations','unfinished_preparations')])
            check(tr['data-session']==scene and [td.get_text(strip=True) for td in tr.select('td')]==values,'正式320組場と両脚全金額表示')
        m=metrics[ident];values=[fmt(m['profit']),fmt(m['loss']),fmt(m['net'],True),str(m['parents'])]
        for symbol in ('NK225','TOPIX'):values.extend([fmt(legmetrics[ident][symbol]['gross'],True),fmt(legmetrics[ident][symbol]['fees']),fmt(legmetrics[ident][symbol]['net'],True)])
        values.extend([str(m['aborted_parents']),str(m['no_fill_attempts']),str(m['unclosed_sessions'])+'場']+[str(m[k]) for k in ('preparations','reserved_preparations','canceled_preparations','unfinished_preparations')])
        check([td.get_text(strip=True) for td in table.select('tfoot td')]==values,'組と脚の全40合計表示')
    ranking=[]
    for ident,m in metrics.items():
        qualified=m['net']>0 and m['median']>0 and m['top3_removed'] is not None and m['top3_removed']>0 and not m['unclosed_sessions']
        ranking.append((not qualified,-m['black'],-m['normalized_median'] if m['normalized_median'] is not None else math.inf,m['worst_to_mean_black'] if m['worst_to_mean_black'] is not None else math.inf,ident))
    ordered=[r[-1] for r in sorted(ranking)]
    check(ordered==data['main_ids']==[r['id'] for r in data['common_ranking']],'事前の組順位と全八件')
    qualified_count=sum(not r[0] for r in ranking);check(qualified_count==data['qualification_count'],'PAIR資格の独立算式')
    summary=page.select('table.summary tbody tr');check(len(summary)==8,'主集計八行')
    for tr,ident in zip(summary,ordered):
        m=metrics[ident];values=[ident,'達成' if next(not r[0] for r in ranking if r[-1]==ident) else '未達',fmt(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",fmt(m['mean'],True),fmt(m['median'],True),fmt(m['worst'],True),fmt(m['top3_removed'],True),fmt(m['fees']),'—' if m['share'] is None else f"{m['share']*100:.1f}%",str(m['unclosed_sessions']),f"{m['preparations']}/{m['reserved_preparations']}/{m['canceled_preparations']}/{m['unfinished_preparations']}"]
        check([td.get_text(strip=True) for td in tr.select('td')]==values,'主表の全安定指標表示')
    text=page.get_text(' ',strip=True)
    check('日経単独とTOPIX単独の両方が儲かった検証ではありません' in text and '未知検証ではありません' in text,'組と単商品及び既知開発の区別')
    check(not page.select('script[src],img[src]'),'外部通信なし')
    check('未予約取消やEOF待機は利益でも勝ちでもありません' in text,'準備だけを勝ちへ数えない')
    check('毎回単調に縮小し続ける必要はありません' in text and '別の価格時計2回で確認' in text,'状態の二確認と単調縮小を混同しない')
    check({s['exit_mode'] for s in (c['spec'] for c in cases.values())}=={0,1} and {c['spec']['family'] for c in cases.values()}=={'confirmed_mr'},'八対照は両退出と同一家族')
    # ----------------------------------------
    # 指定元の再読はしない。自身の同bytes保全copyを原因節の抽出だけに一回使う。
    copy=BASE/'privatev8/received/相対乖離の実際の復帰確認と全四十場.json';saved=copy.read_bytes();check(hashlib.sha256(saved).hexdigest()==SOURCE_SHA,'自己保全copyの完全同bytes')
    retained=json.loads(saved.decode('utf8'));diagnostic=retained['diagnostics'];check(len(diagnostic)==320,'原因診断320組')
    episodes={(r['method'],r['session']):r for r in retained['episodes']};check(len(episodes)==320,'方向診断の元親320組対応')
    tree=ast.parse((V8/'engine_v8.py').read_text(encoding='utf8'));columns=None;prep_columns=None
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PARENT_COLUMNS' for t in node.targets):columns=ast.literal_eval(node.value)
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PREPARATION_COLUMNS' for t in node.targets):prep_columns=ast.literal_eval(node.value)
    check(columns is not None and len(columns)==46 and len(prep_columns)==21,'凍結核心の親46準備21列名だけAST取得')
    ci={k:i for i,k in enumerate(columns)};pi={k:i for i,k in enumerate(prep_columns)}
    check(retained['columns']['parents']==columns and retained['columns']['preparations']==prep_columns,'完成結果の親と準備の列名を接続')
    stats=[]
    for ident in ordered:
        totals={};found=[v for v in diagnostic if v['method']==ident]
        check(len(found)==40 and {v['session'] for v in found}==set(scenes),'四十場の事後原因対応')
        for scene in found:
            for k,v in scene['totals'].items():totals[k]=totals.get(k,0)+v
        m=metrics[ident]
        check(near(totals['relative_gross']+totals['common_gross'],totals['paired_gross']),'相対と共通の厳密gross和')
        if not m['unclosed_sessions']:
            check(near(totals['paired_net']+totals['single_leg_net'],m['net']) and near(totals['paired_fees']+totals['single_leg_fees'],m['fees']),'診断と実組収支費用の合計')
        direction={str(side):dict(parents=0,wins=0,losses=0,zero=0,unclosed=0,gross=0.,fees=0.,net=0.) for side in (-1,1)}
        for scene in scenes:
            ep=episodes[ident,scene];check(ep['diagnostics']['parents']==next(v['parents'] for v in found if v['session']==scene),'方向と診断親を同じ保存episodeへ対応')
            check_lineage_and_money(ep,rows[ident,scene],ci,pi)
            for parent in ep['parents']:
                check(len(parent)==46 and parent[ci['side_nk']] in (-1,1),'実親方向はNK買売二値')
                side=str(int(parent[ci['side_nk']]));d=direction[side]
                if not parent[ci['complete']]:d['unclosed']+=1;continue
                net=parent[ci['net']];gross=parent[ci['gross_nk']]+parent[ci['gross_top']];fees=parent[ci['fees_nk']]+parent[ci['fees_top']]
                check(near(gross-fees,net),'方向別完結親のgross料金net')
                d['parents']+=1;d['wins']+=int(net>1e-7);d['losses']+=int(net<-1e-7);d['zero']+=int(abs(net)<=1e-7);d['gross']+=gross;d['fees']+=fees;d['net']+=net
        if not m['unclosed_sessions']:
            check(near(sum(d['net'] for d in direction.values()),m['net']) and sum(d['parents'] for d in direction.values())==m['parents'],'NK買方向と売方向の親合計は組全体')
        stats.append(dict(id=ident,**m,legs=legmetrics[ident],decomposition=totals,direction=direction))
    small=dict(scope='既知40場の組会計。二銘柄単独成功ではない。相対/共通分解は事後恒等式。',source_SHA256=SOURCE_SHA,qualification_count=qualified_count,cases=stats,
        read_scope=dict(指定元結果の追加読取=0,自身公開小会計=1,自身同bytes保全copyの原因と方向抽出=1,原市場入力読取=0,金融再実行=0,API=0))
    stats_path.write_text(json.dumps(small,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    proof=dict(passed=True,scope='生成済み正式小会計・HTMLの一致と自己保全copyの診断及び方向抽出。金融エンジンの実会計監査ではない。',counts=dict(COUNTS),total_checks=sum(COUNTS.values()),
        pair_sessions=320,source_SHA256=expected_paths,result_sha256=SOURCE_SHA,artifacts={name:hashlib.sha256(payload).hexdigest() for name,payload in raw.items()},
        stats_path=stats_path.relative_to(ROOT).as_posix(),stats_sha256=hashlib.sha256(stats_path.read_bytes()).hexdigest(),read_scope=small['read_scope'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),proof_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),stats_sha256=proof['stats_sha256'],cases=[{k:r[k] for k in ('id','net','black','red','inactive','median','worst','top3_removed','fees','decomposition','direction')} for r in stats]),ensure_ascii=False))


if __name__=='__main__':
    main()
