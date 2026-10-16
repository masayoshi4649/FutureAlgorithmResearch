"""一呼値料金差引目標の固定数学・境界到達・次quote悪化を独立人工で検算する。"""

from pathlib import Path
import json
import sys

import numpy as np

from range_engine_check import load,digest
import e01_trade_finance_audit as M
import range_finance_audit as A


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_tick_net_goal'


def fixture(symbol: str, side: int, invalid_next: bool, partial: bool) -> tuple:
    """
    機能: 一呼値だけ順行した後に戻る人工GUと、当行partial・次quote不正を作る。
    引数: symbol(str)、side(int)、invalid_next/partial(bool)は商品・方向・境界条件。
    返り値: tuple[dict,ndarray,ndarray]は気配・実注文・UID。実データは読まない。
    """
    tick=.5 if symbol=='TOPIX' else 10.;opening=4000 if symbol=='TOPIX' else 68000.;q=5 if symbol=='TOPIX' else 10
    bid=np.full(8,opening,float);bid[2:4]=opening+2*tick;ask=bid+tick
    if side<0:bid,ask=2*opening-ask,2*opening-bid
    valid=np.ones(8,bool);valid[3]=not invalid_next
    quotes=dict(seq=np.arange(8,dtype=np.int64),time_s=np.arange(8,dtype=float),bid=bid,ask=ask,quote_valid=valid)
    entry=ask[1] if side>0 else bid[1];end=bid[7] if side>0 else ask[7]
    orders=[[1,0,2,side,q,entry,90,1]];uids=[101];remaining=q
    if partial:
        amount=2 if symbol=='TOPIX' else 3;price=bid[2] if side>0 else ask[2];orders.append([2,1,2,-side,amount,price,91,0]);uids.append(-1);remaining-=amount
    orders.append([7,6,2,-side,remaining,end,91,0]);uids.append(-1)
    return quotes,np.array(orders,float),np.array(uids,np.int64)


def main() -> None:
    """
    機能: 完成source通知後に固定目標6の少数独立人工と8部品を結果前に確認する。
    引数: なし。新政策結果/原本/NPZ/現在APIを読まない。
    返り値: Noneは金融前人工証跡。元33場の新政策会計は実行しない。
    """
    target=HERE/'tick_goal_固定純目標と当時境界及びUIDの独立人工.json';assert not target.exists()
    paths=list(SOURCE.glob('*.py'));before={str(p.relative_to(ROOT)):digest(p) for p in paths}
    D=load('独立純目標daily',SOURCE/'daily.py');old=sys.modules.get('daily');sys.modules['daily']=D
    try:P=load('独立純目標policy',SOURCE/'policy.py')
    finally:
        if old is None:sys.modules.pop('daily',None)
        else:sys.modules['daily']=old
    assert P.goals()=={'TOPIX':2082.,'NK225':780.}
    cases=[]
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10;tick=.5 if symbol=='TOPIX' else 10;mult=1000 if symbol=='TOPIX' else 10;unit=q*tick*mult;goal=unit-2*M.fee(q,symbol)
        assert goal>0 and P.goals()[symbol]==goal and (goal/unit)*unit==goal
        config=next(c for c in P.configs() if c['mode']=='CONFIRM' and c['loss_ticks']==8)
        for side in (-1,1):
            for invalid in (False,True):
                for partial in (False,True):
                    quotes,orders,uids=fixture(symbol,side,invalid,partial);base=D.reconstruct(('人工',symbol),orders,uids,quotes)
                    out=P.apply(base,quotes,config);M.inspect_orders(out,quotes,symbol)
                    assert out['control']['目標']==goal and out['control']['種別']=='利益目標' and out['control']['判断行']==2 and out['control']['返済行']==(4 if invalid else 3)
                    assert out['exit_target_uids'][-1]==101 and not np.any(out['orders'][(out['orders'][:,0]>2)&(out['orders'][:,7]==1)])
                    amount=(2 if symbol=='TOPIX' else 3) if partial else 0
                    fees=M.fee(q,symbol)+(M.fee(amount,symbol) if amount else 0)+M.fee(q-amount,symbol)
                    expected=(amount-(q-amount))*tick*mult-fees if invalid else unit-fees
                    assert out['summary']['収支']==expected and out['summary']['費用']==fees
                    oldgoal=D.apply_policy(base,quotes,dict(profit_ticks=1,loss_ticks=8))
                    assert not oldgoal['control']['発動'] and oldgoal['summary']['収支']<0
                    cases.append(dict(symbol=symbol,side=side,partial=partial,次quote不正=invalid,固定純目標=goal,当時清算=base['liquidation_yen'][2],実収支=expected,旧値幅目標P1=oldgoal['summary']['収支']))
    configs=P.configs();assert len(configs)==6 and {(c['mode'],c['loss_ticks']) for c in configs}=={(m,l) for m in ('CONFIRM','VETO') for l in (4,8,16)}
    plan=json.loads((SOURCE/'試行計画.json').read_text(encoding='utf8'));fixed=json.loads((SOURCE/'金融前の固定.json').read_text(encoding='utf8'))
    assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    assert all(digest(ROOT/p)==h for p,h in fixed['source_SHA256'].items()) and fixed['source_SHA256']==plan['spec']['implementation']
    assert fixed['configs']==configs and fixed['新政策会計']==396
    assert digest(SOURCE/'daily.py')==digest(ROOT/'work/wave_v106/e01_daily/core.py')
    assert before=={str(p.relative_to(ROOT)):digest(p) for p in paths}
    text=(SOURCE/'runner.py').read_text(encoding='utf8');assert "matched[0]['spec']==plan['spec']" in text and "assert not (common.HERE/'finance').exists()" in text
    proof=dict(全合格=True,scope='一呼値から初回往復料金を引く固定場内純目標6の金融前source/境界人工。正式入力/結果未読。',人工=cases,人工口座=16,独立UID会計検査=sum(A.COUNT.values()),source_SHA256=before,source開始終端一致=True,レビューsource_SHA256=digest(Path(__file__)),計画SHA256=digest(SOURCE/'試行計画.json'),新金融=0,正式入力読取=0,原NPZ=0,現NightAPI=0,留意点=['目標は場全体の清算収支2082/780円で、各親を建値から一呼値で必ず返済する指示とは違う。','一呼値ちょうどのfee純目標へ当時到達しても、次正常quoteで戻れば実収支は負になる。目標達成額の保証なし。','partialの注文別floorで全量返済と料金が1円違い得る。初回全量往復料から決まる目標はその都度改変しない。','元GU/P1対照の保存注文を使う。新規engine/入口票/紙上を再生しない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('純目標の独立人工合格',len(cases),digest(target))


if __name__=='__main__':main()
