"""実結果を読まず、固定時刻の売買反転と気配差が消えない恒等式を検査する。"""

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import json

import reader


def synthetic(symbol: str, side: int) -> tuple[dict, dict, dict]:
    """
    機能: 明示した二つのBBOだけから一親一脚の会計を手計算する。
    引数: symbol(str)、side(int)。
    返り値: tuple は親・脚・両端気配。実入力を使わない。
    """
    q=10 if symbol=='TOPIX' else 20
    mult=1000 if symbol=='TOPIX' else 10
    cost=836 if symbol=='TOPIX' else 440
    entry=100.5 if side>0 else 100
    exit_price=101 if side>0 else 101.5
    gross=side*q*mult*(exit_price-entry)
    p=dict(parent=0,uid=0,side=side,quantity=q,gross_yen=gross,fee_yen=cost,net_yen=gross-cost)
    leg=dict(parent=0,uid=0,side=side,q=q,entry_row=1,exit_row=2,entry_price=entry,exit_price=exit_price,
        gross_yen=gross,entry_fee_allocated=cost//2,exit_fee=cost//2,net_yen=gross-cost)
    point=dict(q=q,side=side,entry_row=1,exit_row=2,新規=dict(bid=100,ask=100.5),返済=dict(bid=101,ask=101.5))
    return p,leg,point


def reject(function: object) -> None:
    """
    機能: 不正な会計がAssertionErrorで停止することを確認する。
    引数: function(Callable)。
    返り値: None。
    """
    try:
        function()
    except AssertionError:
        return
    raise AssertionError('不正な会計を受理した')


def main() -> None:
    """
    機能: 売買両側・料金・親符号・全792場の空場と二重費用禁止を合成検査する。
    引数: なし。
    返り値: None。金融結果・原NPZ・event・台帳・APIを読まない。
    """
    output=reader.HERE/'固定時刻反転と気配差の恒等式のSOURCE_ONLY人工.json'
    assert not output.exists()
    examples=[]
    for symbol in reader.CAP:
        for side in (1,-1):
            parent,leg,point=synthetic(symbol,side)
            value=reader.mirror_leg(leg,point,parent['quantity'],symbol)
            assert reader.exact(value['元net'])+reader.exact(value['反転net'])==-2*(reader.exact(value['気配差負担'])+reader.exact(value['元と共通の料']))
            assert value['反転net'] != -value['元net']
            assert value['mirror_side']==-side
            examples.append(dict(symbol=symbol,side=side,**value))
    for bad in (None,True,False,float('nan'),float('inf'),'1'):
        reject(lambda bad=bad:reader.exact(bad))
    p,leg,point=synthetic('TOPIX',1)
    for field in ('gross_yen','net_yen','entry_fee_allocated','exit_fee','entry_price'):
        broken=deepcopy(leg)
        broken[field]+=1
        reject(lambda broken=broken:reader.mirror_leg(broken,point,p['quantity'],'TOPIX'))
    broken=deepcopy(point)
    broken['返済']['ask']=broken['返済']['bid']
    reject(lambda:reader.mirror_leg(leg,broken,p['quantity'],'TOPIX'))
    assert reader.fee(1,'TOPIX')==41 and reader.fee(2,'TOPIX')==83
    assert reader.amounts([])['利益割合'] is None
    # 全十二×二商品×三十三。各case・商品に一親だけ、残る三十二場は無取引。
    cases=[reader.MAIN]+[f'合成条件{i}' for i in range(11)]
    sessions=[f'合成場{i:02d}_Day' for i in range(33)]
    result=dict(全合格=True,金融=True,configs=[dict(id=cid) for cid in cases],sessions=sessions,
        rows=[],parents=[],actual_legs=[],diagnostics=[])
    for cid in cases:
        for symbol in reader.CAP:
            p,leg,point=synthetic(symbol,1)
            for i,session in enumerate(sessions):
                meta=dict(case=cid,symbol=symbol,session=session)
                if i==0:
                    result['parents'].append(dict(p,**meta))
                    result['actual_legs'].append(dict(leg,**meta))
                    q=p['quantity'];mult=reader.MULT[symbol]
                    mid=q*mult
                    spread=Fraction(q*mult,2)
                    bd=dict(parent=0,uid=0,中値差粗損益=float(mid),気配差負担=float(spread),手数料=p['fee_yen'],収支=p['net_yen'],legs=[point])
                    row=dict(**reader.amounts([p['net_yen']]),費用=p['fee_yen'],**meta)
                    diagnostic=dict(中値差粗損益=float(mid),気配差負担=float(spread),手数料=p['fee_yen'],収支=p['net_yen'],parent_breakdown=[bd],**meta)
                else:
                    row=dict(**reader.amounts([]),費用=0,**meta)
                    diagnostic=dict(中値差粗損益=0,気配差負担=0,手数料=0,収支=0,parent_breakdown=[],**meta)
                result['rows'].append(row)
                result['diagnostics'].append(diagnostic)
    mirrored=reader.calculate(result)
    assert len(mirrored['rows'])==792 and len(mirrored['parents'])==len(mirrored['legs'])==24
    assert all(value['symbols']['TOPIX']['無取引場数']==32 for value in mirrored['aggregate'].values())
    assert all(value['symbols']['NK225']['反転赤字場数']==1 for value in mirrored['aggregate'].values())
    assert mirrored['counts']['追加有効性標本']==0 and mirrored['新金融'] is False
    md=reader.markdown(mirrored)
    assert md.count('| 合計 |')==12 and md.count('合成場')==396
    source_names=('reader.py','artificial_mirror.py')
    reader.write(output,dict(全合格=True,売買と商品4例=examples,合成掲載場=792,合成親=24,拒否境界=12,
        source_SHA256={name:reader.digest((reader.HERE/name).read_bytes()) for name in source_names},
        元結果=0,原NPZ=0,eventNPZ=0,台帳=0,新金融=0,API=0))
    print(json.dumps(dict(全合格=True,SHA256=reader.digest(output.read_bytes())),ensure_ascii=False))


if __name__=='__main__':
    main()
