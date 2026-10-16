"""反転実運転の集計・期間・第一公開例を実結果なしで確認する。"""

from copy import deepcopy
import json

import reader


def fixture() -> tuple[dict, dict]:
    """
    機能: 全十二×全六十六のうち指定二例だけ取引する合成結果を構築する。
    引数: なし。
    返り値: tuple[dict,dict] は新結果と旧参考の合成。
    """
    cases=[reader.MAIN]+[f'QREVERSE_合成条件{i}' for i in range(11)]
    sessions=['2026-09-24_Night','2026-10-01_Night']+[f'合成場{i:02d}_'+('Day' if i%2 else 'Night') for i in range(31)]
    data=dict(全合格=True,金融=True,主候補=reader.MAIN,configs=[dict(id=c) for c in cases],sessions=sessions,
        rows=[],parents=[],actual_legs=[],diagnostics=[])
    mirror=dict(aggregate={})
    for cid in cases:
        old=cid.replace('QREVERSE_','QEXEC_',1)
        mirror['aggregate'][old]=dict(symbols={})
        for symbol in ('TOPIX','NK225'):
            mirror['aggregate'][old]['symbols'][symbol]=dict(元会計=dict(収支=-100),固定時刻反転=dict(収支=-200))
            for session in sessions:
                meta=dict(case=cid,symbol=symbol,session=session)
                match=[(s,t,seq) for s,t,seq in reader.EXAMPLES if s==symbol and t==session]
                if cid==reader.MAIN and match:
                    seq=match[0][2]
                    side=-1 if symbol=='TOPIX' else 1
                    q,mult,fee=(10,1000,836) if symbol=='TOPIX' else (20,10,440)
                    ap,bp=(100,101.5) if side<0 else (100.5,101)
                    gross=side*q*mult*(bp-ap)
                    net=gross-fee
                    p=dict(parent=0,uid=0,side=side,quantity=q,net_yen=net,fee_yen=fee,**meta)
                    leg=dict(parent=0,uid=0,q=q,side=side,entry_row=1,exit_row=2,entry_price=ap,
                        exit_price=bp,gross_yen=gross,entry_fee_allocated=fee//2,exit_fee=fee//2,net_yen=net,**meta)
                    entry=dict(raw_seq=seq+1,price_time_s=1001,bid=100,ask=100.5,bid_qty=20,ask_qty=10)
                    exit_point=dict(raw_seq=seq+2,price_time_s=1002,bid=101,ask=101.5,bid_qty=10,ask_qty=20)
                    public=dict(entry,raw_seq=seq,price_time_s=1000)
                    snapshot=dict(parent=0,uid=0,公開=public,新規=entry,最終返済=exit_point)
                    mid=side*q*mult
                    cross=q*mult/2
                    breakdown=dict(parent=0,uid=0,中値差粗損益=mid,気配差負担=cross,手数料=fee,収支=net,
                        legs=[dict(q=q,side=side,entry_row=1,exit_row=2,新規=entry,返済=exit_point)])
                    data['parents'].append(p);data['actual_legs'].append(leg)
                    row=dict(利益=max(net,0),損失=max(-net,0),収支=net,親数=1,**meta)
                    diag=dict(中値差粗損益=mid,気配差負担=cross,手数料=fee,収支=net,
                        snapshots=[snapshot],parent_breakdown=[breakdown],**meta)
                else:
                    row=dict(利益=0,損失=0,収支=0,親数=0,**meta)
                    diag=dict(中値差粗損益=0,気配差負担=0,手数料=0,収支=0,snapshots=[],parent_breakdown=[],**meta)
                data['rows'].append(row);data['diagnostics'].append(diag)
    return data,mirror


def reject(function: object) -> None:
    """
    機能: 不正会計と方向がAssertionErrorで拒否されることを確認する。
    引数: function(Callable)。
    返り値: None。
    """
    try:function()
    except AssertionError:return
    raise AssertionError('不正会計が受理された')


def main() -> None:
    """
    機能: 全期間と二例の反転方向・直接BBO分解・未知保持を合成で確認する。
    引数: なし。
    返り値: None。新旧結果・入力・台帳・APIは読まない。
    """
    output=reader.HERE/'反転結果と期間及び指定二例のSOURCE_ONLY人工.json'
    assert not output.exists()
    data,mirror=fixture()
    result=reader.calculate(data,mirror)
    assert len(result['十二条件の比較'])==12 and len(result['第一公開二例'])==2
    for symbol in ('TOPIX','NK225'):
        scope=result['主候補の期間'][symbol]
        assert scope['全33']['場数']==33 and scope['前16']['場数']==16 and scope['後17']['場数']==17
        assert scope['全33']['無取引場']==32 and scope['全33']['赤字場']==1
        assert scope['デイ']['親数']==0 and scope['ナイト']['親数']==1
        assert result['十二条件の比較'][reader.MAIN][symbol]['元115']['収支']==-100
    assert result['第一公開二例'][0]['parent']['side']==-1
    assert result['第一公開二例'][1]['parent']['side']==1
    for key in ('収支','気配差負担','手数料'):
        broken=deepcopy(data)
        diagnostic=next(d for d in broken['diagnostics'] if d['snapshots'])
        diagnostic[key]+=1
        reject(lambda broken=broken:reader.calculate(broken,mirror))
    broken=deepcopy(data)
    broken['parents'][0]['side']=1
    reject(lambda:reader.calculate(broken,mirror))
    for bad in (True,False,None,float('nan'),float('inf')):
        reject(lambda bad=bad:reader.number(bad))
    missing=deepcopy(data)
    diagnostic=next(d for d in missing['diagnostics'] if d['snapshots'])
    diagnostic['snapshots']=[]
    partial=reader.calculate(missing,mirror)
    assert partial['第一公開二例'][0]['実親保存有無'] is False
    assert 'parent' not in partial['第一公開二例'][0]
    reader.write(output,dict(全合格=True,合成場=792,条件=12,期間比較=10,指定二例=2,拒否境界=9,
        source_SHA256={name:reader.sha((reader.HERE/name).read_bytes()) for name in ('reader.py','artificial_diagnosis.py')},
        結果本文=0,原NPZ=0,eventNPZ=0,台帳=0,API=0,新金融=0))
    print(json.dumps(dict(全合格=True,SHA256=reader.sha(output.read_bytes())),ensure_ascii=False))


if __name__=='__main__':main()
