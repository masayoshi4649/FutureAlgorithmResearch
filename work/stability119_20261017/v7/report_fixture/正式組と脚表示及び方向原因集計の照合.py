"""指定元を再読せず、正式公開小会計の全320行と保全コピーの原因診断を照合する。"""

from collections import Counter
import hashlib
import ast
import json
import math
from pathlib import Path
import statistics

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
V7=HERE.parent
BASE=V7.parent
ROOT=BASE.parents[1]
PUBLIC=BASE/'privatev7/public'
SOURCE_SHA='6920051e4b9217284cf89f9afb4652f9ac7ec560a17b25928a66135f876fcb14'
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


def main() -> None:
    """
    機能: 自身公開会計とHTMLを照合し、保全自己コピーから原因節だけ一目的抽出する。
    引数: なし。
    返り値: None。指定原結果・入力・市場を再読せず、別QAと小statsだけ保存する。
    """
    target=HERE/'正式320組と脚分離及び共同時計源の実表示照合.json';stats_path=BASE/'privatev7/八条件の小集計と相対共通費用分解.json'
    assert not target.exists() and not stats_path.exists()
    names=('data.json','相対的な強さの継続と残差追尾の全セッション損益.html','README.md','生成証跡.json')
    raw={name:(PUBLIC/name).read_bytes() for name in names};data=json.loads(raw['data.json']);generated=json.loads(raw['生成証跡.json'])
    page=BeautifulSoup(raw[names[1]].decode('utf8'),'html.parser')
    check(generated['passed'] is True and generated['fixture'] is False and generated['result_sha256']==SOURCE_SHA,'正式実会計版でfixture混同なし')
    check(data['source_SHA256']==SOURCE_SHA,'指定完成元SHA一致')
    for name,wanted in generated['artifacts'].items():check(hashlib.sha256(raw[name]).hexdigest()==wanted,'正式生成物のSHA一致')
    expected={'run_v7.py':'9c34e69e65f63c1305830796f414cc73f80e72f6fcadf13e6f804a3e22c7baae','plan_v7.py':'644ccd1434521481a4bf86f0d591433f775a18a67f2b22e404c6f9a6a2097cd4','engine_v7.py':'0d5737139f9b710706af48c2c498b28ed3e14625164b293e98ec39d9ad146353'}
    expected_paths={(V7/name).relative_to(ROOT).as_posix():value for name,value in expected.items()}
    check(data['economic_source_SHA256']==expected_paths,'共同clock最終三源の結果結合')
    for name,value in expected.items():check(hashlib.sha256((V7/name).read_bytes()).hexdigest()==value,'共同clock最終三源の現物一致')
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
            values.extend([str(r['aborted_parents']),str(r['no_fill_attempts']),str(r['unclosed'])])
            check(tr['data-session']==scene and [td.get_text(strip=True) for td in tr.select('td')]==values,'正式320組場と両脚全金額表示')
        m=metrics[ident];values=[fmt(m['profit']),fmt(m['loss']),fmt(m['net'],True),str(m['parents'])]
        for symbol in ('NK225','TOPIX'):values.extend([fmt(legmetrics[ident][symbol]['gross'],True),fmt(legmetrics[ident][symbol]['fees']),fmt(legmetrics[ident][symbol]['net'],True)])
        values.extend([str(m['aborted_parents']),str(m['no_fill_attempts']),str(m['unclosed_sessions'])+'場'])
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
        m=metrics[ident];values=[ident,'達成' if next(not r[0] for r in ranking if r[-1]==ident) else '未達',fmt(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",fmt(m['mean'],True),fmt(m['median'],True),fmt(m['worst'],True),fmt(m['top3_removed'],True),fmt(m['fees']),'—' if m['share'] is None else f"{m['share']*100:.1f}%",str(m['unclosed_sessions'])]
        check([td.get_text(strip=True) for td in tr.select('td')]==values,'主表の全安定指標表示')
    text=page.get_text(' ',strip=True)
    check('日経単独とTOPIX単独の両方が儲かった検証ではありません' in text and '未知検証ではありません' in text,'組と単商品及び既知開発の区別')
    check(not page.select('script[src],img[src]'),'外部通信なし')
    check('旧MRの収支を同時刻のまま符号反転した結果ではありません' in text,'cashstopと実受理が変わる実執行対照')
    check('相対的に強い側を買い弱い側を売ります' in text and '実受理集合も変わり' in text,'相対momentumと出口間の資格差')
    check({s['exit_mode'] for s in (c['spec'] for c in cases.values())}=={0,1} and {c['spec']['family'] for c in cases.values()}=={'momentum'},'八対照は両退出と同一家族')
    # ----------------------------------------
    # 指定元の再読はしない。自身の同bytes保全copyを原因節の抽出だけに一回使う。
    copy=BASE/'privatev7/received/相対的な強さの継続と残差追尾の全四十場.json';saved=copy.read_bytes();check(hashlib.sha256(saved).hexdigest()==SOURCE_SHA,'自己保全copyの完全同bytes')
    retained=json.loads(saved.decode('utf8'));diagnostic=retained['diagnostics'];check(len(diagnostic)==320,'原因診断320組')
    episodes={(r['method'],r['session']):r for r in retained['episodes']};check(len(episodes)==320,'方向診断の元親320組対応')
    tree=ast.parse((V7/'engine_v7.py').read_text(encoding='utf8'));columns=None
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PARENT_COLUMNS' for t in node.targets):columns=ast.literal_eval(node.value)
    check(columns is not None and len(columns)==37,'凍結核心の親37列名だけAST取得')
    ci={k:i for i,k in enumerate(columns)}
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
            for parent in ep['parents']:
                check(len(parent)==37 and parent[ci['side_nk']] in (-1,1),'実親方向はNK買売二値')
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
