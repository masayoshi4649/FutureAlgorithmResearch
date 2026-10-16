"""source未完成の段階で、二価格票FAKと元出来高入口の独立期待を固定する。"""

import hashlib
import itertools
import json
from pathlib import Path
from fak_evidence_reference import Price, allowance, first_try
from entry_information_reference import fak_allowance, price_both, admitted


HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 二票境界・unknown・NaN・0Tfill/失効・PRICE/ANDの経済同値を純人工で確認する。
    引数: なし。
    返り値: None。新ownedへ純期待証跡を保存し、金融sourceをimportしない。
    """
    count=0;limited=0;price_accepted=0;diagnostic_change=0
    for side,k1,k2,n1,n2,b1,b2 in itertools.product((-1,1),(False,True),(False,True),(0,1,2,4),(0,1,2,4),
            (-1.,-.75,-.25,0.,.25,.749999,.75,1.,float('nan')),(-1.,-.75,-.25,0.,.25,.749999,.75,1.,float('nan'))):
        own,peer=Price(k1,n1,b1),Price(k2,n2,b2)
        expected=int(k1 and k2 and n1>=2 and n2>=2 and side*b1>=.75 and side*b2>=.75)
        actual=allowance(own,peer,side);old=fak_allowance(own,peer,side)
        assert actual==expected and actual<=old
        count+=2;limited+=actual!=old
        accepted=price_both(own,peer,side)
        if accepted:assert actual==old;price_accepted+=1
        elif actual!=old:diagnostic_change+=1
        assert admitted('VOL25',True,True,accepted)
        assert admitted('VOL25_PRICE_BOTH',True,True,accepted)==accepted
        count+=2
    assert limited>0 and diagnostic_change==limited
    # ----------------------------------------
    paths=[]
    for side,tick in itertools.product((-1,1),(.5,10.)):
        quote=4000. if tick==.5 else 65000.
        same=first_try(side,quote,tick,0,[(False,quote+side*tick),(True,quote)])
        assert same['約定'] and same['約定価格']==quote and same['試行行']==1
        bad=first_try(side,quote,tick,0,[(True,quote+side*tick),(True,quote)])
        assert not bad['約定'] and bad['試行行']==0 and bad['約定価格'] is None
        old=first_try(side,quote,tick,1,[(True,quote+side*tick)])
        assert old['約定']
        next_publication=first_try(side,quote+side*tick,tick,0,[(True,quote+side*tick)])
        assert next_publication['約定']
        paths.append(dict(方向=side,観測呼値=tick,同値0T約定=same,一回0T失効=bad,旧1T約定=old,後の別公開=next_publication))
        count+=4
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'fak_evidence_reference.py',Path(__file__))}
    proof=dict(全合格=True,純確認数=count,旧1Tから0Tへ限定した人工組数=limited,
        PRICE又はAND受理の許容不変組数=price_accepted,拒否公開の診断だけが変化する人工組数=diagnostic_change,
        一回FAK人工=paths,source_SHA256=sources,完成実源接続=False,
        留保='PRICE/AND受理では二票を既に要求するため経済不変。拒否公開のcap表示は変わり得るので九出力全exactとは別。実効能は未測定。',
        金融=0,原input=0,台帳=0,旧110金融本文=0,API=0,新実源import=0)
    target=HERE/'二価格票FAKだけの境界と0T一回試行の独立純期待.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,純確認数=count,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
