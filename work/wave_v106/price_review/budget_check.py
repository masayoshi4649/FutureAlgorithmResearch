"""停止予算18の登録前sourceと入口気配差境界を独立少数人工で確認する。"""

from pathlib import Path
import json

import numpy as np

from range_engine_check import load,digest
from e01_trade_finance_audit import inspect_orders
import range_finance_audit as A


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_trade_budget'


def fixture(symbol: str, side: int, spread: int, invalid_next: bool) -> tuple:
    """
    機能: 後には利益になるGUを、入口料金だけで早期停止し得る人工として作る。
    引数: symbol(str)、side/spread(int)、invalid_next(bool)は商品・売買・入口幅・次気配資格。
    返り値: tuple[dict,ndarray,ndarray]は8行気配と実新規/元返済/UID。未来実原本不使用。
    """
    tick=.5 if symbol=='TOPIX' else 10.;base=4000. if symbol=='TOPIX' else 68000.;q=5 if symbol=='TOPIX' else 10
    bid=np.full(8,base);ask=bid+tick;ask[1]=base+spread*tick;bid[4:]=base+6*tick;ask[4:]=bid[4:]+tick
    if side<0:bid,ask=2*base-ask,2*base-bid
    valid=np.ones(8,bool)
    if invalid_next:valid[2]=False
    quotes=dict(seq=np.arange(8,dtype=np.int64),time_s=np.arange(8,dtype=float),bid=bid,ask=ask,quote_valid=valid)
    entry=ask[1] if side>0 else bid[1];exit_price=bid[7] if side>0 else ask[7]
    orders=np.array([[1,0,7,side,q,entry,90,1],[7,6,7,-side,q,exit_price,91,0]],float)
    return quotes,orders,np.array([21,-1],np.int64)


def main() -> None:
    """
    機能: 金融結果を読まず16人工の停止先着・UID料・勝ち赤字化とsource固定を検証する。
    引数: なし。巨大input/結果/API/金融engineは呼ばない。
    返り値: Noneはreview独立証跡。元33場の新政策損益は計算しない。
    """
    target=HERE/'budget_18固定と入口費用境界の独立人工.json';assert not target.exists()
    before={str(p.relative_to(ROOT)):digest(p) for p in SOURCE.glob('*.py')}
    D=load('独立予算daily',SOURCE/'daily.py');P=load('独立予算policy',SOURCE/'policy.py')
    assert digest(SOURCE/'daily.py')==digest(ROOT/'work/wave_v106/e01_daily/core.py')
    observations=[]
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10;tick=.5 if symbol=='TOPIX' else 10.;mult=1000 if symbol=='TOPIX' else 10;unit=q*tick*mult
        for side in (-1,1):
            for spread in (1,2):
                for invalid in (False,True):
                    quotes,orders,uids=fixture(symbol,side,spread,invalid);base=D.reconstruct(('人工',symbol),orders,uids,quotes)
                    out=D.apply_policy(base,quotes,dict(profit_ticks=1,loss_ticks=2));parents,_,_=inspect_orders(out,quotes,symbol)
                    expected_entry=-spread*unit-2*D.fee(q,symbol);assert base['liquidation_yen'][1]==expected_entry
                    if spread==2:
                        expected_fill=3 if invalid else 2
                        assert out['control']['種別']=='損失予算' and out['control']['判断行']==1 and out['control']['返済行']==expected_fill
                        assert base['summary']['収支']>0 and out['summary']['収支']<0
                        assert out['summary']['収支']==-2*unit-2*D.fee(q,symbol)
                    else:
                        assert out['control']['種別']=='利益目標' and out['control']['判断行']==4 and out['control']['返済行']==5
                        assert out['summary']['収支']==5*unit-2*D.fee(q,symbol)
                    row=out['control']['判断行'];assert not np.any(out['orders'][(out['orders'][:,0]>row)&(out['orders'][:,7]==1)])
                    assert out['exit_target_uids'][-1]==21 and len(parents)==1 and out['order_fees'].sum()==2*D.fee(q,symbol)
                    observations.append(dict(symbol=symbol,side=side,入口spread=spread,次quote不正=invalid,入口当時清算=expected_entry,判断=row,実返済=out['control']['返済行'],実収支=out['summary']['収支'],後なら勝った元GU=base['summary']['収支']))
    configs=P.configs();assert len(configs)==18 and sum(c['saved_alias'] for c in configs)==2
    assert len({(c['mode'],c['profit_ticks'],c['loss_ticks']) for c in configs})==18
    plan=json.loads((SOURCE/'試行計画.json').read_text(encoding='utf8'));fixed=json.loads((SOURCE/'金融前の固定.json').read_text(encoding='utf8'));art=json.loads((SOURCE/'小利益と損失予算の最小結合人工.json').read_text(encoding='utf8'))
    assert digest(SOURCE/'試行計画.json')=='876257fd118afd482f30a7251ec7b42bf984fbe15cde4622669b20a4a004790e'
    assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    posix={Path(k).as_posix():v for k,v in before.items()}
    assert fixed['source_SHA256']==plan['spec']['implementation']==art['source_SHA256']==posix
    assert art['全合格'] and fixed['configs']==plan['spec']['entry']['conditions']==configs
    assert fixed['plan_SHA256']==digest(SOURCE/'試行計画.json') and fixed['新政策口座']==1056 and fixed['表示口座']==1188
    text=(SOURCE/'runner.py').read_text(encoding='utf8')
    assert "len(registered)==1 and registered[0]['spec']==plan['spec']" in text and "assert not (common.HERE/'finance').exists()" in text
    assert "if config['saved_alias']:\n                            fresh=base" in text and "fresh=daily.apply_policy(gu,quotes,config)" in text
    assert "gu['summary']==old['summary']" in text and '元勝ち親が赤字化' in text
    assert before=={str(p.relative_to(ROOT)):digest(p) for p in SOURCE.glob('*.py')}
    proof=dict(全合格=True,scope='budget18の新金融前source固定・政策配置及び独立16買売/商品人工。正式input/新政策結果未読。',人工口座=16,独立検査数=sum(A.COUNT.values()),人工=observations,source_SHA256=before,source開始終端一致=True,レビューsource_SHA256=digest(Path(__file__)),計画SHA256=digest(SOURCE/'試行計画.json'),旧GU再生=0,新政策金融=0,原NPZ=0,現在API=0,registry変更=0,留意点=['損失予算L2は2tickの価格stop幅ではなく費用込み口座判断閾値。2tick入口spread＋往復料で初回fill行に達する。','次qok返済を待つため予算額を超える損失を保証付きで防げない。初回fill直後の即停止でも同row返済は禁止。','L2で後のGU勝ちを負けへ変える人工反証が両商品買売で成立。設定変更は損失減だけの改善とみなさない。','停止後は当行までの実注文接頭だけ保持し、未来の元注文を取り込まない。旧GUのshadow statesを新政策の保有と混ぜない。','P1L8 alias2条件は既存の同金融引用、新16×66だけを新政策と数える。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('budget独立人工合格',len(observations),digest(target))


if __name__=='__main__':main()
