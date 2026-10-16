"""端点と価格経路を分離した第1修正版を、原本と独立窓及び実接頭から監査する。"""

from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import sys

import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
sys.path.insert(0,str(HERE))
import check_inputs as A


def corrected_mid(record: dict) -> dict:
    """
    機能: 原本照合済み最良価格と数量から、経路資格と端点資格を独立分離する。
    引数: record(dict)、旧初版資格を含む独立原本素材。
    返り値: dict、第1修正版の独立期待値。
    """
    result={**record}
    bid=record['bid'];ask=record['ask'];bq=record['bid_qty'];aq=record['ask_qty']
    path=(np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
          &np.isfinite(bq)&np.isfinite(aq)&(bq>0)&(aq>0))
    endpoint=path&(ask-bid<=2*record['tick']+1e-9)
    values=(bid+ask)/2.;values[~path]=np.nan
    result.update(valid=path,endpoint_valid=endpoint,values=values)
    quality={**record['price_quality']}
    quality.update(valid=path,path_valid=path,endpoint_valid=endpoint,mid=values,
                   best_price_or_quantity_invalid=~path,spread_endpoint_invalid=path&~endpoint)
    result['price_quality']=quality
    return result


def coupled_controls(key: tuple,grid: np.ndarray,execution: dict,old: dict,actual: dict,generator: object,core: object) -> None:
    """
    機能: I2の旧源資格を保つLP対照も実接頭と未来価格変形で検査する。
    引数: key(tuple)、grid(ndarray)、execution/old/actual(dict)、generator/core(object)。
    返り値: None、源旗を変更せず価格だけ再計算して照合する。
    """
    for fraction in (.2,.5,.8):
        length=max(1,int(len(grid)*fraction));past=grid[:length]
        cut=int(np.searchsorted(execution['time_s'],past[-1]-1.,side='left'))
        record=dict(seq=execution['seq'][:cut],time_s=execution['time_s'][:cut],price=execution['price'][:cut])
        market=A.grid_clip(old,length,len(grid))
        expected=A.grid_clip(actual,length,len(grid))
        short=generator.coupled_last_features(record,market,core)
        A.equal(short,expected,'I2実接頭/'+str(key))
        future=dict(seq=execution['seq'],time_s=execution['time_s'],price=execution['price'].copy())
        future['price'][cut:]*=1.071
        changed=generator.coupled_last_features(future,market,core)
        A.equal(changed,expected,'I2実未来価格変形/'+str(key))
        A.COUNTS['実接頭価格系列']+=1;A.COUNTS['実未来変形価格系列']+=1


def strict_controls(key: tuple,grid: np.ndarray,mid: dict,lp_record: dict,actual: dict,core: object,last: object) -> None:
    """
    機能: 観測可能期限そのものを切り、自己又は相手市場の未観測価格を変形する。
    引数: key(tuple)、grid(ndarray)、mid/lp_record/actual(dict)、core/last(object)。
    返り値: None。格子直前1秒を含む未観測行を接頭へ混ぜない。
    """
    for fraction in (.2,.5,.8):
        length=max(1,int(len(grid)*fraction));past=grid[:length];threshold=float(past[-1]-1.)
        cut_mid=int(np.searchsorted(mid['time_s'],threshold,side='left'))
        cut_lp=int(np.searchsorted(lp_record['time_s'],threshold,side='left'))
        short_mid=A.clip_record(mid,cut_mid);short_lp=A.clip_record(lp_record,cut_lp)
        ready=dict(seq=short_mid['seq'],time_s=short_mid['time_s'],tick=short_mid['tick'],last=short_mid['last'])
        book={k:short_mid[k] for k in ('bid','ask','last','bid_qty','ask_qty')}
        expected_mid=A.grid_clip(actual['I1'],length,len(grid));expected_lp=A.grid_clip(actual['I3'],length,len(grid))
        A.equal(A.grid_clip(core.price_features(past,1,ready,book),length,length),expected_mid,'厳密期限接頭I1/'+str(key))
        A.equal(last.last_price_features(past,1,short_lp),expected_lp,'厳密期限接頭I3/'+str(key))
        ready=dict(seq=mid['seq'],time_s=mid['time_s'],tick=mid['tick'],last=mid['last'])
        book={k:mid[k].copy() for k in ('bid','ask','last','bid_qty','ask_qty')}
        for field in ('bid','ask','last'):book[field][cut_mid:]*=1.013
        book['bid_qty'][cut_mid:]*=11.;book['ask_qty'][cut_mid:]*=.031
        future={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in lp_record.items()}
        future['last'][cut_lp:]*=.971
        A.equal(A.grid_clip(core.price_features(past,1,ready,book),length,length),expected_mid,'未観測自己又は相手価格変形I1/'+str(key))
        A.equal(last.last_price_features(past,1,future),expected_lp,'未観測自己又は相手価格変形I3/'+str(key))
        A.COUNTS['実接頭価格系列']+=2;A.COUNTS['実未来変形価格系列']+=2
        A.COUNTS['厳密期限の実接頭']+=2


def artificial(core: object,last: object) -> dict:
    """
    機能: 欠測時計・不正LP・同時計先頭・原seqgap・広気配を独立正負例で検査する。
    引数: core/last(object)、第1修正版の検査対象。
    返り値: dict、人工検査証拠。板又は価格欠測を救済しない。
    """
    base=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()
    def raw(second: float,price: object) -> dict:
        """
        機能: 独立人工LP原行を作る。
        引数: second(float)、price(object)。
        返り値: dict、原時計とLP及び無関係の板を含む行。
        """
        return dict(CurrentPriceTime=datetime.fromtimestamp(base+second,timezone.utc).isoformat(),CurrentPrice=price,
                    Buy1=dict(Price=-7,Qty=0),Sell1=dict(Price=-9,Qty=None),TradingVolume=-1)
    rows=[(0,raw(-1,99)),(1,raw(0,100)),(2,raw(1,101)),(3,dict(CurrentPriceTime=None,CurrentPrice=999)),
          (4,raw(3,None)),(5,raw(3,103)),(6,raw(4,104)),(7,raw(5,105)),(9,raw(6,106)),(10,raw(7,True))]
    observed=last.extract_last_prices(rows,base,base+30)
    A.equal(observed['seq'],np.array([1,2,4,5,6,7,9,10],np.int64),'人工LP原seq')
    A.equal(observed['time_s'],base+np.array([0,1,3,3,4,5,6,7],float),'人工LP時計')
    A.equal(observed['last'],np.array([100,101,np.nan,103,104,105,106,np.nan]),'人工LP値')
    A.equal(observed['reset_reason'],np.array([9,0,6,0,0,0,2,0],np.uint8),'人工LP断裂')
    broken_source=last.last_price_features(np.array([base+4.5]),1,observed)['current']
    assert broken_source['index'][0]==-1,'同時計後続又は古い正常への救済'
    altered=[(seq,{**value,'Buy1':dict(Price=10000,Qty=1000000),'Sell1':dict(Price=.1,Qty=9)}) for seq,value in rows]
    A.equal(last.extract_last_prices(altered,base,base+30),observed,'人工LPは板不参照')
    reverse=[(0,raw(4,100)),(1,raw(3,101))]
    try:last.extract_last_prices(reverse,base,base+30)
    except AssertionError:pass
    else:raise AssertionError('時計逆行を正常化した')
    n=1100;times=base+np.arange(n,dtype=float);seq=np.arange(n,dtype=np.int64)
    prices=100+np.arange(n,dtype=float)*.01
    record=dict(seq=seq,time_s=times,tick=.1,last=prices)
    book=dict(bid=prices-.05,ask=prices+.05,last=prices.copy(),bid_qty=np.ones(n),ask_qty=np.ones(n),
              valid=np.ones(n,bool),reset=np.zeros(n,bool),reset_reason=np.zeros(n,np.uint8))
    book['reset'][0]=True;book['reset_reason'][0]=1
    grid=base+np.arange(320.,1001.,5.)
    normal=core.price_features(grid,1,record,book)
    wide={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in book.items()}
    wide['bid'][450]=prices[450]-.15;wide['ask'][450]=prices[450]+.15
    changed=core.price_features(grid,1,record,wide)
    assert changed['price_quality']['path_valid'][450] and not changed['price_quality']['endpoint_valid'][450]
    crossed=(changed['windows'][300]['old']<450)&(changed['windows'][300]['now']>450)
    assert crossed.any() and changed['windows'][300]['source_valid'][crossed].all()
    A.equal(changed['windows'][300],normal['windows'][300],'人工途中広spreadは価格断裂にしない')
    at=core.price_features(np.array([base+452.]),1,record,wide)
    assert at['current']['index'][0]==-1,'現在広spreadの端点を救済'
    flat={**observed,**last.extract_last_prices([(i,raw(i,100)) for i in range(1000)],base,base+1000)}
    features=last.last_price_features(np.array([base+702]),1,flat)
    assert features['windows'][300]['source_valid'][0] and np.isnan(features['windows'][300]['efficiency'][0])
    return dict(原seq不連続を保持=True,時計欠測を次保存源の断裂へ保持=True,不正LPの時刻付きNaN保持=True,
                同時計先頭不正の後続又は過去正常への救済禁止=True,LP板不参照=True,時計逆行拒否=True,
                途中正常広spreadは価格断裂にしない=True,現在広spread端点拒否=True,平坦窓ERを既知ゼロへ代用しない=True)


def main() -> None:
    """
    機能: 第1修正版62素材の独立原本・全格子・未来不変監査を保存する。
    引数: なし。
    返り値: None、新監査JSON一つ。初版と凍結旧資料を変更しない。
    """
    socket.socket.connect=A.deny;socket.create_connection=A.deny
    metadata=A.load(WORK/'prepared_r1/metadata.json')
    sources={**metadata['旧入力SHA256'],**metadata['新コードSHA256'],**metadata['新入力SHA256']}
    for path in (WORK/'prepared_r1/metadata.json',WORK/'data_r1.py',Path(A.__file__),Path(__file__)):
        sources[str(path.relative_to(ROOT))]=A.digest(path)
    for relative,expected in sources.items():assert A.digest(ROOT/relative)==expected,relative
    material=A.module('独立不変旧93素材R1',ROOT/'work/wave_v93/data.py').load_inputs()
    lanes=A.load(WORK/'prepared_r1/price_lanes.pkl');raw_lp=A.load(WORK/'prepared_r1/raw_last_records.pkl')
    core=A.module('監査対象R1価格',WORK/'inputs_r1/core.py')
    last=A.module('監査対象R1原LP',WORK/'inputs_r1/last_price.py')
    generator=A.module('監査対象R1準備',WORK/'prepare_inputs_r1.py')
    cases=artificial(core,last)
    diagnoses={(v['場'],v['商品']):v for v in metadata['素材取得診断']}
    rows=[]
    for key,execution in sorted(material['prices'].items()):
        lp,mid,review=A.scan(key,execution,raw_lp[key],diagnoses[key])
        mid=corrected_mid(mid)
        grid=material['grids'][key[0]]['grid'];old=material['grids'][key[0]]['markets'][key[1]]
        old_record=dict(seq=execution['seq'],time_s=execution['time_s'],values=execution['price'],
                        valid=execution['price_valid'],reset=material['features'][key]['reset'])
        actual={kind:lanes[kind][key[0]]['markets'][key[1]] for kind in ('I1','I2','I3')}
        for kind,record in (('I1',mid),('I2',old_record),('I3',lp)):
            A.equal(lanes[kind][key[0]]['grid'],grid,'格子/'+kind+str(key))
            A.equal(actual[kind],A.oracle(grid,record,kind,old),'独立R1全格子/'+kind+str(key))
            A.COUNTS['全格子価格系列']+=1;A.COUNTS['価格現在格子']+=len(grid)
            A.COUNTS['価格窓格子']+=len(grid)*len(A.WINDOWS);A.COUNTS['価格高安格子']+=len(grid)*len(A.RANGES)
        strict_controls(key,grid,mid,raw_lp[key],actual,core,last)
        coupled_controls(key,grid,execution,old,actual['I2'],generator,core)
        bbo=old['current']['index'];i1=actual['I1']['current']['index'];lp_seq=actual['I3']['current']['raw_seq']
        bbo_seq=np.full(len(grid),-1,np.int64);bbo_seq[bbo>=0]=execution['seq'][bbo[bbo>=0]]
        review.update(全3价格系全格子一致=True,実接頭3点及び未来価格変形一致=True,
                      I1価格源と旧BBO源が異なる格子=int((i1!=bbo).sum()),
                      I3価格原seqと旧BBO原seqが異なる格子=int((lp_seq!=bbo_seq).sum()),
                      価格源index名前空間='I1/I2はretained、I3は全原本LP、raw_seq別列',
                      正常広気配を断裂から除外=int(mid['price_quality']['spread_endpoint_invalid'].sum()))
        rows.append(review)
        print(f'{key[0]} {key[1]} R1独立原本{review["原本行数"]:,}・全3価格系全格子・厳密実接頭3点合格',flush=True)
    connected=A.module('監査対象R1接続',WORK/'data_r1.py').load_inputs()
    for key in ('prices','grids','legacy','entries','features','metadata'):
        A.equal(connected[key],material[key],'旧素材及びQFlow接続不変/'+key)
    for lane in ('I1','I2','I3'):A.equal(connected['price_lanes'][lane],lanes[lane],'新価格別名前空間/'+lane)
    for session in material['grids']:
        for symbol in ('TOPIX','NK225'):
            published=connected['price_lanes']['I0'][session]['markets'][symbol]
            old=material['grids'][session]['markets'][symbol]
            A.equal(published['windows'],old['windows'],'I0旧窓')
            A.equal(published['ranges'],old['ranges'],'I0旧高安')
    for relative,expected in sources.items():assert A.digest(ROOT/relative)==expected,('監査途中変更',relative)
    result=dict(全検査合格=True,全31既知=True,新未見場数=0,口座数=62,全格子価格系列=186,
                人工独立正負=cases,独立検算=dict(A.COUNTS),場別検算=rows,
                path_validとendpoint_valid分離=True,原LP欠測及び同時計先頭保守=True,
                価格源と旧BBO源分離=True,旧素材及びQFlow全列接続不変=True,
                独立窓期待値への対象実装使用=0,初版書込み=0,凍結旧領域書込み=0,新損益実行=0,現在API取得=0,実注文=0,
                限界=['CurrentPriceTimeは約定代理時計で真の受信時計ではない。',
                      '保存seq連続は全配信イベントの取得保証ではない。',
                      '入力可用性及び因果性を確認しただけで方向的優位又は利益を認定しない。'],SHA256=sources)
    output=HERE/'修正版全62原本と3価格系の全格子及び実接頭の独立検算.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('R1全62原本・186価格系独立監査完了。新損益0。',flush=True)


if __name__=='__main__':main()
