"""新価格分類と旧執行源の全53接続を、売買なしの独立数式及び人工境界で検算する。"""

import copy
from pathlib import Path
import socket
import sys

import numpy as np

import common
import full
import price_checks


def toy() -> tuple:
    """
    機能: 当時観測可能な二市場価格と別Q源の人工素材を構成する。
    引数: なし。
    返り値: tuple[dict,dict]、価格素材と旧flow素材。
    """
    size=40;grid=np.arange(size,dtype=float)*5.;markets={};books={}
    for symbol in common.SYMBOLS:
        seq=np.arange(size,dtype=np.int64)
        markets[symbol]=dict(current=dict(index=seq,raw_seq=seq*3+7,time_s=grid-1.,value=np.full(size,100.),valid=np.ones(size,bool)),
            windows={300:dict(source_valid=np.ones(size,bool),ret_bp=np.zeros(size),efficiency=np.full(size,.2),total_variation=np.ones(size)),
                     30:dict(source_valid=np.ones(size,bool),ret_bp=np.zeros(size))},
            ranges={180:dict(source_valid=np.ones(size,bool),position_valid=np.ones(size,bool),width=np.full(size,2.),low=np.full(size,99.),high=np.full(size,101.))})
        books[symbol]=dict(flow={15:dict(source_valid=np.zeros(size,bool),valid=np.zeros(size,bool),missing_ofi=np.ones(size,bool),
                                        nonzero_ofi_count=np.zeros(size,np.int32),ofi_ratio=np.full(size,np.nan))})
    return dict(grid=grid,markets=markets),dict(grid=grid,markets=books)


def clipped(value: object,stop: int) -> object:
    """
    機能: 人工格子だけを未来切断する。
    引数: value(object)、stop(int)。
    返り値: object、元入力を変更しない接頭部。
    """
    if isinstance(value,dict):return {k:clipped(v,stop) for k,v in value.items()}
    return value[:stop].copy() if isinstance(value,np.ndarray) else value


def artificial(strategy: object,config: dict) -> dict:
    """
    機能: 価格確認源・共同不明・TVゼロ・Q逆証拠の意味を正負境界で検査する。
    引数: strategy(object)、config(dict)。
    返り値: dict、独立分類比較件数。正式実損益を求めない。
    """
    scenarios=('正常往復','短窓不明','300総変動ゼロ','価格peer源更新なし','境界の高ER',
               '少数OFIは逆証拠へ代用しない','十分OFIの逆証拠','レンジ外','一市場価格不明')
    count=0
    for scenario in scenarios:
        for side in (-1,1):
            price,book=toy()
            if scenario=='短窓不明':
                for market in price['markets'].values():market['windows'][30]['source_valid'][:10]=False
            elif scenario=='300総変動ゼロ':
                for market in price['markets'].values():market['windows'][300]['total_variation'][:]=0.
            elif scenario=='価格peer源更新なし':price['markets']['NK225']['current']['raw_seq'][:]=7
            elif scenario in ('境界の高ER','少数OFIは逆証拠へ代用しない','十分OFIの逆証拠'):
                for market in price['markets'].values():
                    market['windows'][300]['ret_bp'][:]=side*4;market['windows'][30]['ret_bp'][:]=side*.1
                    market['windows'][300]['efficiency'][:]=config['high_er']
                if scenario!='境界の高ER':
                    for market in book['markets'].values():
                        flow=market['flow'][15];flow['source_valid'][:]=flow['valid'][:]=True;flow['missing_ofi'][:]=False
                        flow['nonzero_ofi_count'][:]=2 if scenario.startswith('少数') else 3;flow['ofi_ratio'][:]=-side*.5
            elif scenario=='レンジ外':price['markets']['NK225']['current']['value'][:]=102.
            elif scenario=='一市場価格不明':price['markets']['TOPIX']['current']['valid'][:]=False
            expected=price_checks.restore_price(price,book,config);actual=strategy.price_state(price,book,config)
            common.same(expected,actual)
            if scenario=='短窓不明':
                assert (expected['raw_mode'][:10]==2).all() and expected['mode'][2]==2
                assert (expected['price_mode'][:12]==0).all() and expected['price_mode'][12]==2
            elif scenario in ('300総変動ゼロ','一市場価格不明'):assert not expected['valid'].any()
            elif scenario=='価格peer源更新なし':assert not (expected['mode']==2).any()
            elif scenario=='少数OFIは逆証拠へ代用しない':assert (expected['raw_mode']==side).all()
            elif scenario=='十分OFIの逆証拠':assert (expected['raw_mode']==0).all()
            for stop in (3,11,21,32):
                shorter=strategy.price_state(clipped(price,stop),clipped(book,stop),config)
                common.same(shorter,{k:v[:stop] for k,v in expected.items()})
                future=copy.deepcopy(price)
                for market in future['markets'].values():
                    market['current']['value'][stop:]*=8
                    market['current']['raw_seq'][stop:]+=100000
                    market['windows'][300]['ret_bp'][stop:]=1000
                changed=strategy.price_state(future,book,config)
                common.same({k:v[:stop] for k,v in changed.items()},{k:v[:stop] for k,v in expected.items()})
            count+=1
    return dict(独立人工分類=count,各人工未来切断=4,各人工未来変形=4,
                G0共同不明0の旧準備維持=True,G2は観測可能な連続確認=True,確認は価格原seq双方更新=True)


def main() -> None:
    """
    機能: 全53×31×2の準備信号と源分離を独立検算し、売買前に証跡を保存する。
    引数: なし。
    返り値: None、新監査JSON。正式売買・損益計算は0。
    """
    socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('保存素材限定'))
    sys.path.insert(0,str(common.WORK))
    import strategy,catalog
    data=common.module('分類監査用修正版入力94',common.WORK/'data_r1.py')
    material=data.load_inputs();cases=artificial(strategy,catalog.catalog()[0]);count=0
    for config in catalog.catalog():
        prepared=strategy.prepare(material,config)
        for session in material['grids']:
            for symbol in common.SYMBOLS:
                price_checks.signal_check(material,session,symbol,config,prepared[session,symbol]['signal']);count+=1
        print(f'{config["id"]} 全31両市場の独立価格分類・現在入口・旧BBO源分離合格',flush=True)
    assert count==53*31*2
    paths=[Path(__file__),Path(common.__file__),Path(price_checks.__file__),common.HERE/'state_checks.py',
           common.WORK/'strategy.py',common.WORK/'engine.py',common.WORK/'catalog.py',common.WORK/'data_r1.py',
           *material['paths']]
    common.save('全53全31の独立価格分類と現在入口及び旧執行源の接続検査.json',
                dict(全合格=True,条件数=53,全31既知=True,口座準備=count,人工=cases,
                     実取引実行=0,新保存場損益計算=0,新保存場損益閲覧=0,現在API取得=0,実注文=0,
                     SHA256=common.fingerprint(paths)))


if __name__=='__main__':main()
