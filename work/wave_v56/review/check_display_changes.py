"""表示範囲を考慮した数量差と最良OFIを、独立した合成ケースで検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
MEASUREMENT=HERE.parent/'measurement'
sys.path.insert(0,str(MEASUREMENT))
from display_changes import side_changes, best_ofi
from measure_display_changes import book


def reference(before: dict,after: dict,side: str) -> dict:
    """機能: 全候補価格の旧量・新量を明示的に列挙して独立差分を作る。

    引数: before/after(dict)、side(str)。返り値: 比較値(dict)。
    """
    outcome=dict(common_add=0.,common_remove=0.,known_disappeared=0.,known_appeared=0.,
                 unknown_old_quantity=0.,unknown_new_quantity=0.)
    before_far=min(before) if side=='bid' else max(before)
    after_far=min(after) if side=='bid' else max(after)
    for price in set(before)|set(after):
        old=before.get(price);new=after.get(price)
        if old is not None and new is not None:
            outcome['common_add']+=max(0.,new-old)
            outcome['common_remove']+=max(0.,old-new)
        elif old is not None:
            inside=price>=after_far if side=='bid' else price<=after_far
            outcome['known_disappeared' if inside else 'unknown_old_quantity']+=old
        else:
            inside=price>=before_far if side=='bid' else price<=before_far
            outcome['known_appeared' if inside else 'unknown_new_quantity']+=new
    outcome['known_add']=outcome['common_add']+outcome['known_appeared']
    outcome['known_remove']=outcome['common_remove']+outcome['known_disappeared']
    return outcome


def main() -> None:
    """機能: 数量保存・売買鏡像・時点逆転・価格変換・OFI全分岐を検査する。

    引数: なし。返り値: なし(None)。実損益を参照せず旧コードを変更しない。
    """
    checks=[]
    before={100.-i:float(i+1) for i in range(10)}
    after={95.-i:float(i+7) for i in range(10)}
    r=side_changes(before,after,'bid')
    assert r['known_disappeared']==sum(before[p] for p in (100.,99.,98.,97.,96.))
    assert r['unknown_new_quantity']==sum(after[p] for p in (90.,89.,88.,87.,86.))
    assert r['best_disappeared']==1.
    checks.append('5段を飛び越える最良買い後退で有利側消失と新たな遠方表示を分離')

    before={100.-i*2:float(i+1) for i in range(10)}
    after=dict(before);del after[92.];after[93.]=20.
    r=side_changes(before,after,'bid')
    assert r['known_disappeared']==5. and r['known_appeared']==20.
    assert r['unknown_old_quantity']==r['unknown_new_quantity']==0.
    checks.append('最良不変でも、表示範囲内の価格穴と新しい価格の出現を計上')

    rng=np.random.default_rng(20261007)
    cases=0
    for side in ('bid','ask'):
        for _ in range(1000):
            before={float(p):float(q) for p,q in zip(rng.choice(np.arange(80,141),10,replace=False),rng.integers(0,100,10))}
            after={float(p):float(q) for p,q in zip(rng.choice(np.arange(80,141),10,replace=False),rng.integers(0,100,10))}
            actual=side_changes(before,after,side);expected=reference(before,after,side)
            for name,value in expected.items():
                assert actual[name]==value,(name,actual,expected)
            assert sum(after.values())-sum(before.values())==actual['known_add']-actual['known_remove']+actual['unknown_new_quantity']-actual['unknown_old_quantity']
            reverse=side_changes(after,before,side)
            for old,new in [('common_add','common_remove'),('known_appeared','known_disappeared'),('unknown_old_quantity','unknown_new_quantity')]:
                assert actual[old]==reverse[new]
            mirror=side_changes({500.-p:q for p,q in before.items()},{500.-p:q for p,q in after.items()},'ask' if side=='bid' else 'bid')
            transformed=side_changes({p*4.+1000.:q for p,q in before.items()},{p*4.+1000.:q for p,q in after.items()},side)
            for name in (*expected,'best_disappeared'):
                assert actual[name]==mirror[name]==transformed[name]
            cases+=1
    checks.append('2000組の独立差分・数量保存・時点逆転・売買鏡像・価格単位変換が一致')

    ofi_cases=0
    for bid in (99.,100.,101.):
        for ask in (109.,110.,111.):
            expected=(13.*int(bid>=100.)-7.*int(bid<=100.)-17.*int(ask<=110.)+11.*int(ask>=110.))
            actual=best_ofi((100.,7.),(110.,11.),(bid,13.),(ask,17.))
            assert actual==expected
            reverse=best_ofi((bid,13.),(ask,17.),(100.,7.),(110.,11.))
            assert reverse==-actual
            scaled=best_ofi((100.,21.),(110.,33.),(bid,39.),(ask,51.))
            assert scaled==3*actual
            mirrored=best_ofi((390.,11.),(400.,7.),(500.-ask,17.),(500.-bid,13.))
            assert mirrored==-actual
            ofi_cases+=1
    checks.append('最良買い3状態×最良売り3状態のOFI全9分岐、逆転と数量倍率も一致')

    raw={f'Buy{i}':dict(Price=101.-i,Qty=float(i)) for i in range(1,11)}
    assert book(raw,'Buy') is not None
    for mode in ('欠段','重複','逆順','負数量','不定数'):
        invalid={k:v.copy() for k,v in raw.items()}
        if mode=='欠段':del invalid['Buy5']
        elif mode=='重複':invalid['Buy5']['Price']=invalid['Buy4']['Price']
        elif mode=='逆順':invalid['Buy5']['Price']=200.
        elif mode=='負数量':invalid['Buy5']['Qty']=-1.
        else:invalid['Buy5']['Qty']=float('nan')
        assert book(invalid,'Buy') is None,mode
    checks.append('呼出側の10段品質検査が欠段・重複・逆順・負数量・非有限値を拒否')
    result=dict(合格=True,合成ケース=checks,独立数量差比較数=cases,OFI独立分岐数=ofi_cases,
                静的確認='不正原本行でpreviousを切断。深板差分は両時点両側10段が正常な場合だけ。最良OFIは最良価格・数量だけ。原因や心理の値を返さず、未来行を参照しない。',
                コードSHA256={name:hashlib.sha256((MEASUREMENT/name).read_bytes()).hexdigest()
                                for name in ('display_changes.py','measure_display_changes.py')})
    (HERE/'表示範囲とOFIの独立合成監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
