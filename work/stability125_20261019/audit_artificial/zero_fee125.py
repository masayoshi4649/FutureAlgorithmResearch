"""手数料を除外する新指定を、同じ売買源の人工追加検査として分離する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import independent125 as A


def main() -> None:
    """
    機能: 同一十二条件をfee0で人工検査し、全料金・純粗損益・次行資格を照合する。
    引数: なし。
    返り値: None。金融再生、原市場、過去金融結果、登録、APIは0。
    """
    engine_sha=hashlib.sha256((A.WORK/'engine125.py').read_bytes()).hexdigest()
    catalog_sha=hashlib.sha256((A.WORK/'catalog125.py').read_bytes()).hexdigest()
    assert engine_sha=='867d3e8b621a8e78d31f535c6d080da6210ae5ebc5d0fcef6c18f457863f6661'
    assert catalog_sha=='c4255e393e426676a90f1da5a0d1d331ba1e59ae426cd48ce2f3ad886fed8a71'
    specs=A.C.specifications();base=next(s for s in specs if s['id']=='A00');broad=next(s for s in specs if s['id']=='B03')
    q,f,config=A.fixture([1000,1001,1001,1001,1011,1011,1011],[0,1800,1800,1801,3000,3000,3001])
    config['fee']=0.;details=[]
    for spec in specs:
        o,t,c,s=A.evaluate(q,f,config,spec)
        A.check(len(o)==2 and len(t)==1,'fee0全十二条件の非空往復')
        A.near(o[:,A.OI['fee']],0.,'fee0全注文料金ゼロ')
        A.near(t[:,A.TI['entry_fees']],0.,'fee0全新規料金ゼロ')
        A.near(t[:,A.TI['exit_fee']],0.,'fee0全返済料金ゼロ')
        A.near(t[:,A.TI['net']],t[:,A.TI['gross']],'fee0完結純損益と粗損益一致')
        A.near(s['fees_paid'],0.,'fee0全場料金ゼロ')
        A.near(s['net'],45000.,'fee0通常往復の外部期待45000円')
        details.append(dict(method=spec['id'],net=s['net'],fees=s['fees_paid'],entry_quantity=s['entry_quantity']))
    proxyq={k:v[:4].copy() for k,v in q.items()};proxyq['time'][-1]=3000.;proxyq['last'][-1]=1011.;proxyq['bid'][-1]=1010.5;proxyq['ask'][-1]=1011.5
    proxy=A.evaluate(proxyq,f,config,base)
    A.check(proxy[1][0,A.TI['proxy_flag']]==1 and len(proxy[0])==1,'fee0代理は架空返済注文なし')
    A.near(proxy[3]['net'],45000.,'fee0代理終端の外部期待45000円')
    aq,af,ac=A.fixture([1000,1001,1001,1007,1008,1007,1012,1012],[0,1800,1800,1801,1802,1803,3000,3001],'trend')
    ac['fee']=0.;added=A.evaluate(aq,af,ac,broad)
    A.check(added[3]['add_orders']==1,'fee0順行追加は一回')
    A.near(added[3]['net'],65000.,'fee0追加の外部期待65000円')
    A.near(added[1][0,A.TI['entry_fees']]+added[1][0,A.TI['exit_fee']],0.,'fee0追加群の全料金ゼロ')
    odd=A.evaluate(aq,af,dict(ac,cap=3),broad)
    A.near(odd[3]['net'],16000.,'fee0一枚と二枚の追加外部期待16000円')

    # ----------------------------------------
    # 同じwでも、手数料0ではspreadちょうど0.5wが判断・次行とも通る。
    boundary={k:v.copy() for k,v in q.items()};boundary['bid'][1]=1000.;boundary['ask'][1]=1002.
    exact=A.evaluate(boundary,f,config,base)
    A.check(exact[0][0,A.OI['decision_row']]==1,'fee0判断spread0.5wを受理')
    fill_boundary={k:v.copy() for k,v in q.items()};fill_boundary['bid'][2]=1000.;fill_boundary['ask'][2]=1002.
    exactfill=A.evaluate(fill_boundary,f,config,base)
    A.check(exactfill[0][0,A.OI['fill_row']]==2,'fee0次fillspread0.5wを受理')
    A.near(exactfill[3]['net'],42500.,'fee0境界気配の実建値損益42500円')
    wide,_,_=A.fixture([1000,1001,1001,1001,1001,1011,1011],[0,1800,1800,1801,1802,3000,3001])
    wide['bid'][2]=1000.;wide['ask'][2]=1002.5
    canceled=A.evaluate(wide,f,config,base)
    A.check(canceled[3]['canceled_entries']>=1 and canceled[0][0,A.OI['decision_row']]>=3,'fee0次fill広幅は取消し再判断')
    sq,sf,sc=A.fixture([1000,1001,1001,990,980,980,980],[0,1800,1800,1801,1802,3000,3001])
    sc['fee']=0.;stopped=A.evaluate(sq,sf,sc,base)
    A.near(stopped[3]['net'],-110000.,'fee0保険停止も次実気配のマイナス110000円')
    fq,ff,fc=A.fixture([1000,996,996,1001,1002,1002,1002,1002],[60,70,80,90,100,110,3000,3001],'trend')
    fc['fee']=0.;flipped=A.evaluate(fq,ff,fc,broad)
    entries=flipped[0][flipped[0][:,A.OI['kind']]==1];exits=flipped[0][flipped[0][:,A.OI['kind']]==2]
    A.check(len(entries)>=2 and exits[0,A.OI['fill_row']]<entries[1,A.OI['fill_row']],'fee0反転前実返済')
    A.near(flipped[3]['net'],-40000.,'fee0反転二群の外部期待マイナス40000円')
    A.near(flipped[3]['fees_paid'],0.,'fee0反転は料金ゼロ')
    A.check(hashlib.sha256((A.WORK/'engine125.py').read_bytes()).hexdigest()==engine_sha,'fee0実行中源不変')
    A.check(hashlib.sha256((A.WORK/'catalog125.py').read_bytes()).hexdigest()==catalog_sha,'fee0実行中条件不変')
    proof=dict(passed=True,engine_sha256=engine_sha,catalog_sha256=catalog_sha,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        independent_accounting_source_sha256=hashlib.sha256((A.HERE/'independent125.py').read_bytes()).hexdigest(),
        fee=0,normal_cases=details,checks=dict(A.CHECKS),check_count=sum(A.CHECKS.values()),
        original_market_reads=0,saved_price_array_reads=0,financial_replays=0,API=0,real_orders=0,registry_changes=0,
        target_arithmetic=dict(first_price=1000.,price_target=5.,cap=10,multiplier=1000.,
            normal_net=45000.,captured_price_width=4.5,
            definition='獲得価格幅=net/(cap*multiplier)、価格自身の0.5%=first_price*.005。人工の45000円は4.5ptであり、目標5pt達成とは数えない。'),
        limitation='旧有料v2は保存。追加人工は新無料条件の数値契約だけで、実41場や0.5%達成の有効性を検証していない。')
    path=A.HERE/'無料条件追加の十二往復と数量及び次行費用境界の独立人工.json'
    assert not path.exists();path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,path=path.relative_to(A.ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_sha256=proof['source_sha256'],engine_sha256=engine_sha,catalog_sha256=catalog_sha,check_count=proof['check_count']),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
