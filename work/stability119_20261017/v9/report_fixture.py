"""二脚組の表示と脚別会計を、実結果未読の八政策だけで確認する。"""

from copy import deepcopy
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

import report_v9 as R


HERE=Path(__file__).resolve().parent
COUNTS={}


def check(value: bool,label: str) -> None:
    """
    機能: 人工表示の一致を項目別に記録する。
    引数: value(bool)は期待、label(str)は検査項目。
    返り値: None。不一致で停止する。
    """
    assert value,label
    COUNTS[label]=COUNTS.get(label,0)+1


def fixture() -> dict:
    """
    機能: 旧市場とは無関係な八条件・四十場と脚別gross/fee/netを作る。
    引数: なし。
    返り値: dictは完成予定schema。両脚の一方を赤字にして合算と区別する。
    """
    scenes=[str(date(2035,1,1)+timedelta(days=i//2))+('_Day' if i%2==0 else '_Night') for i in range(40)]
    specs=[dict(id=f'{method.upper()}_CONF_L{length}_X{x}_CB',baseline_id=f'{method.upper()}_CONF_L{length}_X{x}',method=method,lookback=length,exit_mode=x,family='confirmed_mr',name='合成'+method+str(length)+str(x),description='合成の相対復帰確認。') for method in ('ratio_mr','ols_mr') for length in (30,60) for x in (0,1)]
    rows=[]
    for k,spec in enumerate(specs):
        for i,scene in enumerate(scenes):
            active=i>=4;net=(150.+k if i<32 else -70.) if active else 0.;legs={}
            for symbol,gross,fee,qty in (('NK225',1000.+k if active else 0.,22. if active else 0.,2),('TOPIX',net+106.-1000.-k if active else 0.,84. if active else 0.,1)):
                legs[symbol]=dict(gross=gross,fees=fee,realized=gross-fee,unrealized_after_close_fees=0.,net=gross-fee,
                    fills=2 if active else 0,entry_quantity=qty if active else 0,closed_quantity=qty if active else 0,unclosed=0)
            rows.append(dict(session=scene,symbol='PAIR',method=spec['id'],net=net,realized=net,profit=max(net,0),loss=max(-net,0),fees=106. if active else 0.,
                max_drawdown=80.,parents=int(active),wins=int(net>0),losses=int(net<0),unclosed=0,fills=4 if active else 0,canceled=0,halted=0,
                closed_quantity=3 if active else 0,attempts=int(active),no_fill_attempts=0,paired_parents=int(active),aborted_parents=0,pending_entries=0,
                single_leg_seconds=1. if active else 0.,max_single_leg_notional=100000. if active else 0.,expected_close_fees=0.,legs=legs,
                preparations=4 if active else (3 if i==0 else 2 if i==1 else 1 if i==2 else 0),
                reserved_preparations=1 if active or i==2 else 0,canceled_preparations=2 if active else 3 if i==0 else 0,
                unfinished_preparations=1 if active else 2 if i==1 else 0))
            if i==2:rows[-1].update(attempts=1,no_fill_attempts=1)
    oldrows=deepcopy(rows)
    for row in oldrows:
        row['method']=row['method'][:-3]
        if row['fills']:
            row['net']+=12.;row['realized']+=12.;row['profit']=max(row['net'],0);row['loss']=max(-row['net'],0)
            for key in ('gross','realized','net'):row['legs']['TOPIX'][key]+=12.
    return dict(sessions=scenes,splits={'全40':scenes},specs=specs,runs=rows,source_SHA256={'完全合成源':'a'*64},
        baseline_runs=oldrows,baseline_financial_rerun=0,baseline_reference=dict(path='完全合成/旧v8会計.json',sha256='d'*64,saved_rows=320,financial_replay=0,source_SHA256={'完全合成旧源':'e'*64}))


def num(value: float,signed: bool=False) -> str:
    """
    機能: 表示を独立に期待文字列へ変換する。
    引数: value(float)は数値、signed(bool)は符号指定。
    返り値: strは千位区切り。
    """
    if abs(value)<1e-7:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def main() -> None:
    """
    機能: 全320組場と各脚を合成期待へ照合し、無活動・未知・脚の誤称を確認する。
    引数: なし。
    返り値: None。実結果・入力・金融を読まず別証跡を作る。
    """
    target=HERE/'report_fixture/八組口座と二脚会計及び未達の純表示検査.json';assert not target.exists()
    data=fixture();folder=HERE/'report_fixture/public_v2';generation=R.generate(data,folder,'b'*64,'完全合成/二脚.json',True)
    public=json.loads((folder/'data.json').read_text(encoding='utf8'));page=BeautifulSoup((folder/R.HTML_NAME).read_text(encoding='utf8'),'html.parser')
    check(len(public['cases'])==len(public['common_ranking'])==8,'固定八条件を全数保存')
    check(public['qualification_count']==8,'組資格は脚別黒字を要求しない')
    src={(r['method'],r['session']):r for r in data['runs']};tables=page.select('table.sessions')
    check(len(tables)==8 and {t['data-method'] for t in tables}==set(public['cases']),'全八条件の表')
    for table in tables:
        ident=table['data-method'];check(len(table.select('tbody tr'))==40,'各表四十場を省略しない')
        for tr,scene in zip(table.select('tbody tr'),data['sessions']):
            r=src[ident,scene];values=[num(r['profit']),num(r['loss']),num(r['net'],True),str(r['parents'])]
            for s in R.SYMBOLS:values.extend([num(r['legs'][s]['gross'],True),num(r['legs'][s]['fees']),num(r['legs'][s]['net'],True)])
            values.extend([str(r['aborted_parents']),str(r['no_fill_attempts']),str(r['unclosed'])]+[str(r[k]) for k in ('preparations','reserved_preparations','canceled_preparations','unfinished_preparations')])
            check([td.get_text(strip=True) for td in tr.select('td')]==values,'組P/Lと脚gross料netの全数表示')
        rr=[src[ident,scene] for scene in data['sessions']];expected=[num(sum(r['profit'] for r in rr)),num(sum(r['loss'] for r in rr)),num(sum(r['net'] for r in rr),True),str(sum(r['parents'] for r in rr))]
        for s in R.SYMBOLS:expected.extend([num(sum(r['legs'][s]['gross'] for r in rr),True),num(sum(r['legs'][s]['fees'] for r in rr)),num(sum(r['legs'][s]['net'] for r in rr),True)])
        expected.extend(['0','1','0場']+[str(sum(r[k] for r in rr)) for k in ('preparations','reserved_preparations','canceled_preparations','unfinished_preparations')]);check([td.get_text(strip=True) for td in table.select('tfoot td')]==expected,'全場合計を組と脚で独立集計')
        case=public['cases'][ident]
        check('PAIR' in case['metrics'] and set(case['legs'])==set(R.SYMBOLS),'組metricsと脚metricsを分離')
        check(case['metrics']['PAIR']['black']==28 and case['metrics']['PAIR']['red']==8 and case['metrics']['PAIR']['inactive']==4,'無取引四場を勝ちにしない')
        check(sum(v['net'] for v in case['legs'].values())==case['metrics']['PAIR']['net'],'脚net合計と組net')
    text=page.get_text(' ',strip=True)
    check('二銘柄単独の両方が儲かった検証ではありません' not in text and '日経単独とTOPIX単独の両方が儲かった検証ではありません' in text,'二脚合算を単独両銘柄成功へ置換しない')
    check('未知検証ではありません' in text and '単脚返済は完成ペアの的中とは呼びません' in text,'既知と片脚の成功範囲')
    check('観測極値から0.5標準偏差以上戻った状態を別の価格時計2回で確認' in text and '中心へ戻る向き' in text,'実復帰二確認の説明')
    check('毎回単調に縮小し続ける必要はありません' in text and '未予約取消やEOF待機は利益でも勝ちでもありません' in text,'単調条件の捏造と準備の勝ち誤認を防ぐ')
    check('1標準偏差改善した後' in text and '準備後の固定極値への逆戻り' in text,'極値撤回と残差改善追尾の区別')
    check(not page.select('script[src],img[src]'),'外部通信なし')
    check(len(public['cases'])==8 and len(public['baseline_cases'])==8 and generation['baseline_controls']==8 and generation['reused_baseline_rows']==320,'旧八基準を新八候補へ混在させない')
    for tr in page.select('table.comparison tbody tr'):
        ident=tr['data-method'];spec=next(s for s in data['specs'] if s['id']==ident);old=[r for r in data['baseline_runs'] if r['method']==spec['baseline_id']];new=[r for r in data['runs'] if r['method']==ident]
        om=public['baseline_cases'][spec['baseline_id']]['metrics']['PAIR'];nm=public['cases'][ident]['metrics']['PAIR']
        values=[ident,num(sum(r['net'] for r in old),True),num(sum(r['net'] for r in new),True),num(sum(r['net'] for r in new)-sum(r['net'] for r in old),True),f"{om['black']}/{om['red']}/{om['inactive']} → {nm['black']}/{nm['red']}/{nm['inactive']}",f"{om['parents']} → {nm['parents']}",f"{om['reserved_preparations']} → {nm['reserved_preparations']}",num(sum(r['fees'] for r in old)),num(sum(r['fees'] for r in new))]
        check([td.get_text(strip=True) for td in tr.select('td')]==values,'八対応の旧新と差額を独立に表示')
    check('その後の保有・再参加の変化も含みます' in text and '会計バグの修正とは呼びません' in text,'一因子対照の経路差と設計変更を明示')

    check(all(c['metrics']['PAIR']['inactive']==4 and c['metrics']['PAIR']['reserved_preparations']==37 and c['metrics']['PAIR']['preparations']==150 for c in public['cases'].values()),'予約済未fillと未予約取消を黒字へ数えない')
    failed=deepcopy(data)
    for r in failed['runs']:
        for key in ('net','realized','profit','loss','fees','parents','wins','losses','unclosed','fills','closed_quantity','attempts','paired_parents','aborted_parents','no_fill_attempts','preparations','reserved_preparations','canceled_preparations','unfinished_preparations'):r[key]=0
        for leg in r['legs'].values():
            for key in leg:leg[key]=0
    doc,pub,_=R.render(failed,'c'*64,'完全合成')
    check(pub['qualification_count']==0 and '<strong>毎セッションの安定黒字は未達です。</strong>' in doc,'無活動は未達を太字')
    check(all(c['metrics']['PAIR']['inactive']==40 and c['metrics']['PAIR']['black']==0 for c in pub['cases'].values()),'全無取引を黒字へ数えない')
    broken=deepcopy(data);broken['runs'][0]['legs']['TOPIX']['net']+=1
    try:R.validate(broken)
    except AssertionError:check(True,'脚会計改変を拒否')
    else:raise AssertionError('脚会計改変を拒否')
    proof=dict(passed=True,scope='完全合成の八条件320組場と脚別会計表示だけ。実金融の証明ではない。',counts=COUNTS,total_checks=sum(COUNTS.values()),generation=generation,
        source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'report_v9.py',Path(__file__))},actual_result_reads=0,market_reads=0,financial_replay=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
