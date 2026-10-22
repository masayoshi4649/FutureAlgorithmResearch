"""二脚組の表示と脚別会計を、実結果未読の八政策だけで確認する。"""

from copy import deepcopy
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

import report_v7 as R


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
    specs=[dict(id=f'{method.upper()}_L{length}_X{x}',method=method,lookback=length,exit_mode=x,family='momentum',name='合成'+method+str(length)+str(x),description='合成の相対継続。') for method in ('ratio_mr','ols_mr') for length in (30,60) for x in (0,1)]
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
                single_leg_seconds=1. if active else 0.,max_single_leg_notional=100000. if active else 0.,expected_close_fees=0.,legs=legs))
    return dict(sessions=scenes,splits={'全40':scenes},specs=specs,runs=rows,source_SHA256={'完全合成源':'a'*64})


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
            values.extend([str(r['aborted_parents']),str(r['no_fill_attempts']),str(r['unclosed'])])
            check([td.get_text(strip=True) for td in tr.select('td')]==values,'組P/Lと脚gross料netの全数表示')
        rr=[src[ident,scene] for scene in data['sessions']];expected=[num(sum(r['profit'] for r in rr)),num(sum(r['loss'] for r in rr)),num(sum(r['net'] for r in rr),True),str(sum(r['parents'] for r in rr))]
        for s in R.SYMBOLS:expected.extend([num(sum(r['legs'][s]['gross'] for r in rr),True),num(sum(r['legs'][s]['fees'] for r in rr)),num(sum(r['legs'][s]['net'] for r in rr),True)])
        expected.extend(['0','0','0場']);check([td.get_text(strip=True) for td in table.select('tfoot td')]==expected,'全場合計を組と脚で独立集計')
        case=public['cases'][ident]
        check('PAIR' in case['metrics'] and set(case['legs'])==set(R.SYMBOLS),'組metricsと脚metricsを分離')
        check(case['metrics']['PAIR']['black']==28 and case['metrics']['PAIR']['red']==8 and case['metrics']['PAIR']['inactive']==4,'無取引四場を勝ちにしない')
        check(sum(v['net'] for v in case['legs'].values())==case['metrics']['PAIR']['net'],'脚net合計と組net')
    text=page.get_text(' ',strip=True)
    check('二銘柄単独の両方が儲かった検証ではありません' not in text and '日経単独とTOPIX単独の両方が儲かった検証ではありません' in text,'二脚合算を単独両銘柄成功へ置換しない')
    check('未知検証ではありません' in text and '単脚返済は完成ペアの的中とは呼びません' in text,'既知と片脚の成功範囲')
    check('相対的な強さが続く向き' in text and '相対的に強い側を買い弱い側を売ります' in text,'相対回帰ではなく強さ継続の説明')
    check('2標準偏差進んだ後は残差peakから1標準偏差戻り' in text and '実受理集合も変わり' in text,'追尾と入口資格差を明示')
    check(not page.select('script[src],img[src]'),'外部通信なし')
    failed=deepcopy(data)
    for r in failed['runs']:
        for key in ('net','realized','profit','loss','fees','parents','wins','losses','unclosed','fills','closed_quantity','attempts','paired_parents','aborted_parents'):r[key]=0
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
        source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'report_v7.py',Path(__file__))},actual_result_reads=0,market_reads=0,financial_replay=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
