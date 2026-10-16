"""常設指値12の到達仮定と予約優先を独立の価格・料金人工で確認する。"""

from pathlib import Path
import json

import numpy as np

from range_engine_check import load,digest
from e01_trade_finance_audit import fee


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_resting_takeprofit'


def fixture(symbol: str, side: int, kind: str) -> tuple:
    """
    機能: 利確接触・gap・entry stop破れ・予約反転・timer介入の8正常行人工を作る。
    引数: symbol/ kind(str)、side(int)は商品・人工種別・方向。
    返り値: tuple[dict,dict,dict]は単一玉入力、first新規、独立期待入出。
    """
    tick=.5 if symbol=='TOPIX' else 10.;base=4000 if symbol=='TOPIX' else 68000.;q=5 if symbol=='TOPIX' else 10
    bid=np.full(8,base,float);ask=bid+tick;valid=np.ones(8,bool);quiet=np.zeros(8,bool)
    expected=dict(RESTING=dict(row=2,decision=1,price=base+2*tick,reason='常設利確指値',code=101),NEXT_MARKET=dict(row=3,decision=2,price=base+tick,reason='利確判断後成行',code=102))
    bid[2]=base+2*tick;bid[3]=base+tick;ask=bid+tick
    if kind=='gap':bid[2]=base+5*tick;ask[2]=bid[2]+tick
    if kind=='entry_stop':
        ask[1]=base+5*tick;bid[2]=base+6*tick;ask[2]=bid[2]+tick
        expected={m:dict(row=2,decision=1,price=base+6*tick,reason='損切り',code=103) for m in expected}
    if kind in ('stop_rebound','quiet_override'):
        bid[2]=base-3*tick;ask[2]=bid[2]+tick;valid[3]=False;bid[4:]=base+3*tick;ask[4:]=bid[4:]+tick
        expected={m:dict(row=4,decision=2,price=base+3*tick,reason='損切り',code=103) for m in expected}
        if kind=='quiet_override':
            quiet[4]=True;valid[4]=False
            expected={m:dict(row=5,decision=3,price=base+3*tick,reason='既知quiet',code=104) for m in expected}
    if kind=='quiet':
        quiet[2]=True;bid[2]=base+5*tick;ask[2]=bid[2]+tick
        expected={m:dict(row=2,decision=1,price=base+5*tick,reason='既知quiet',code=104) for m in expected}
    if side<0:
        bid,ask=2*base-ask,2*base-bid
        for v in expected.values():v['price']=2*base-v['price']
    quotes=dict(seq=np.arange(100,108,dtype=np.int64),time_s=np.arange(8,dtype=float),bid=bid,ask=ask,quote_valid=valid)
    entry=dict(order=np.array([1,0,4,side,q,ask[1] if side>0 else bid[1],90,1],float),uid=11)
    account=dict(session='人工',symbol=symbol,quotes=quotes,record=dict(limit=7.,tick=tick),quiet=quiet,quiet_force=np.zeros(8,bool))
    return account,entry,expected


def main() -> None:
    """
    機能: 最終sourceの単一玉価格・cash・fee・部分接頭を金融前小人工だけで確認する。
    引数: なし。正式input/新損益/原NPZ/現在APIを読まない。
    返り値: Noneは独立証跡。queue実約定を証明しない。
    """
    target=HERE/'resting_単一玉と到達注文及びtimerの独立人工.json';assert not target.exists()
    paths=list(SOURCE.glob('*.py'));before={str(p.relative_to(ROOT)):digest(p) for p in paths};P=load('独立常設注文policy',SOURCE/'policy.py')
    checks=0;cases=[]
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10;m=1000 if symbol=='TOPIX' else 10
        for side in (-1,1):
            for kind in ('normal','gap','entry_stop','stop_rebound','quiet','quiet_override'):
                account,entry,expect=fixture(symbol,side,kind)
                for method in ('RESTING','NEXT_MARKET'):
                    c=next(c for c in P.configs() if c['mode']=='CONFIRM' and c['stop_ticks']==4 and c['method']==method)
                    out=P.play(account,entry,c);e=expect[method];o=out['orders'];assert len(o)==2 and o[0,0]==1 and o[1,0]==e['row'] and o[1,1]==e['decision'] and o[1,5]==e['price'] and o[1,6]==e['code'];checks+=6
                    assert out['control']['種別']==e['reason'] and out['control']['利確公開行']==1 and out['control']['元観測予約判断行']==(2 if kind in ('stop_rebound','quiet_override') else 1 if kind=='entry_stop' else 2 if method=='NEXT_MARKET' and kind in ('normal','gap') else -1);checks+=3
                    cost=fee(q,symbol);net=side*q*(e['price']-entry['order'][5])*m-2*cost
                    assert out['summary']['収支']==net and out['summary']['費用']==2*cost;checks+=2
                    eq=np.zeros(8);liq=np.zeros(8);held=np.zeros(8,np.int64);last=None
                    for row in range(8):
                        if account['quotes']['quote_valid'][row]:last=row
                        if 1<=row<e['row']:
                            mark=account['quotes']['bid' if side>0 else 'ask'][last];eq[row]=side*q*(mark-entry['order'][5])*m-cost;liq[row]=eq[row]-cost;held[row]=q
                        if row>=e['row']:eq[row]=liq[row]=net
                    np.testing.assert_array_equal(out['equity_yen'],eq);np.testing.assert_array_equal(out['liquidation_yen'],liq);np.testing.assert_array_equal(out['long_qty']+out['short_qty'],held);checks+=24
                    # ----------------------------------------
                    # entry直後接頭は返済せず保有と入口料のみ。将来quoteは接頭を変えない。
                    short=dict(account,quotes={k:v[:2] for k,v in account['quotes'].items()},quiet=account['quiet'][:2],quiet_force=account['quiet_force'][:2]);prefix=P.play(short,entry,c,finish=False)
                    assert len(prefix['orders'])==1 and prefix['summary']['親数']==0 and prefix['summary']['費用']==cost
                    np.testing.assert_array_equal(prefix['equity_yen'],out['equity_yen'][:2]);np.testing.assert_array_equal(prefix['liquidation_yen'],out['liquidation_yen'][:2]);checks+=7
                    cases.append(dict(symbol=symbol,side=side,人工=kind,method=method,return_row=e['row'],判断row=e['decision'],net=net))
    a,e,_=fixture('TOPIX',1,'normal');c=P.configs()[0];out=P.play(a,None,c);assert len(out['orders'])==0 and out['summary']['親数']==out['summary']['利益']==out['summary']['費用']==0;checks+=3
    configs=P.configs();assert len(configs)==12 and len({(c['mode'],c['stop_ticks'],c['method']) for c in configs})==12
    fixed=json.loads((SOURCE/'金融前の固定.json').read_text(encoding='utf8'));plan=json.loads((SOURCE/'試行計画.json').read_text(encoding='utf8'));art=json.loads((SOURCE/'常設利確と次気配返済の人工検査.json').read_text(encoding='utf8'))
    assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    assert fixed['configs']==plan['spec']['entry']['conditions']==configs
    assert fixed['source_SHA256']==plan['spec']['implementation']==art['source_SHA256']
    assert all(digest(ROOT/p)==h for p,h in fixed['source_SHA256'].items())
    text=(SOURCE/'runner.py').read_text(encoding='utf8');prep=(SOURCE/'prepared.py').read_text(encoding='utf8')
    assert "found[0]['spec']==plan['spec']" in text and "assert not (common.HERE/'finance').exists()" in text
    assert 'indices=np.flatnonzero(gu[\'orders\'][:,7]==1)' in prep and 'ix=int(indices[0])' in prep and "row==min(int(gu['orders'][j,0]) for j in indices)" in prep
    assert before=={str(p.relative_to(ROOT)):digest(p) for p in paths}
    proof=dict(全合格=True,scope='常設/次qの単一最初玉12の金融前sourceと48独立人工、entry接頭/費用/timer/OCO資格。正式金融/input未読。',人工口座=len(cases),検査数=checks,人工=cases,source_SHA256=before,source開始終端一致=True,レビューsource_SHA256=digest(Path(__file__)),計画SHA256=digest(SOURCE/'試行計画.json'),新金融=0,正式input=0,原NPZ=0,現在API=0,留意点=['常設はpost後の到達で固定line全量約定という仮定。quoteがlineより有利でもline価格を使い、queueと実mini/micro約定は未確認。','固定lineの常設は接触行でもpostrowより後。観測後成行を当該接触rowへ巻き戻していない。','hard判断予約後の反発でも損切り予約を保持、quiet介入は元観測判断rowとtimerを別保存。','最初実newだけへ限定するため元GU全戦略との差を注文技術だけの効果と呼ばない。','finishFalseの未返済親は勝ちに数えず、入口料と残返済料を含む曲線へ残す。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('常設注文独立人工合格',len(cases),checks,digest(target))


if __name__=='__main__':main()
