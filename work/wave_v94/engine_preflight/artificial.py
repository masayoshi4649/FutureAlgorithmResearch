"""53条件・旧5対照・現在ゲートと価格確認源を、再現可能な人工経路で検査する。"""

import copy
from pathlib import Path
import sys

import numpy as np

import support


def fixtures() -> object:
    """機能: 既知の人工原板作成器を読み、現セッション・損益は参照しない。

    引数: なし。返り値: objectは人工fixtureモジュール。
    """
    sys.path.append(str(support.WORK.parent/'wave_v92/audit'))
    return support.module('価格分離94用の人工fixture92',support.WORK.parent/'wave_v92/audit/execution_checks.py')


def enrich(record: dict,signal: dict) -> None:
    """機能: 執行源と異なる人工価格源及び旧N4時計を明示する。

    引数: record/signal(dict)。返り値: Noneはsignalへの追加のみ。
    """
    n=len(signal['grid']);seq=np.arange(n,dtype=np.int64)
    signal.update(own_source=seq,own_source_time=record['time_s']-.01,
                  peer_source_time=record['time_s']-.01,raw_range_valid=np.ones(n,bool),
                  raw_range_eligible=signal['mode']==2,raw_oldest_time=record['time_s']-301,
                  price_observable=np.ones(n,bool),price_mode=signal['mode'].copy(),
                  price_own_index=seq+1000,price_peer_index=seq+2000,price_own_raw_seq=seq+3000,
                  price_peer_raw_seq=seq+4000,price_own_time=record['time_s']-1,
                  price_peer_time=record['time_s']-2,price_own_valid=np.ones(n,bool),price_peer_valid=np.ones(n,bool))


def state_cases(strategy: object,config: dict) -> dict:
    """機能: G0の未知共同0準備とG2観測確認及び価格原seq持続を分けて検査する。

    引数: strategy(object)、config(dict)。返り値: dictは人工件数。
    """
    n=40;grid=np.arange(n,dtype=float)*5;markets={};execution={}
    for symbol in ('TOPIX','NK225'):
        markets[symbol]=dict(current=dict(index=np.arange(n),raw_seq=np.arange(n)*10,time_s=grid-1,
                                         value=np.full(n,100.),valid=np.ones(n,bool)),
            windows={300:dict(source_valid=np.ones(n,bool),ret_bp=np.zeros(n),efficiency=np.full(n,.2),total_variation=np.ones(n)),
                     30:dict(source_valid=np.ones(n,bool),ret_bp=np.zeros(n))},
            ranges={180:dict(source_valid=np.ones(n,bool),position_valid=np.ones(n,bool),width=np.full(n,2.),low=np.full(n,99.),high=np.full(n,101.))})
        execution[symbol]=dict(flow={15:dict(source_valid=np.zeros(n,bool),valid=np.zeros(n,bool),missing_ofi=np.ones(n,bool),
                                nonzero_ofi_count=np.zeros(n),ofi_ratio=np.full(n,np.nan))})
    price=dict(grid=grid,markets=markets);book=dict(grid=grid,markets=execution)
    base=strategy.price_state(price,book,config);assert base['mode'][2]==base['price_mode'][2]==2
    unknown=copy.deepcopy(price)
    for market in unknown['markets'].values():market['windows'][30]['source_valid'][:10]=False
    result=strategy.price_state(unknown,book,config)
    assert (result['raw_mode'][:10]==2).all() and result['mode'][2]==2
    assert (result['price_mode'][:12]==0).all() and result['price_mode'][12]==2
    stopped=copy.deepcopy(price);stopped['markets']['NK225']['current']['raw_seq'][:]=0
    assert not np.any(strategy.price_state(stopped,book,config)['mode']==2)
    for side in (-1,1):
        high=copy.deepcopy(price);flow=copy.deepcopy(book)
        for market in high['markets'].values():
            market['windows'][300]['ret_bp'][:]=side*4;market['windows'][30]['ret_bp'][:]=side*.1
            market['windows'][300]['efficiency'][:]=.5
        for market in flow['markets'].values():
            f=market['flow'][15];f['source_valid'][:]=f['valid'][:]=True;f['missing_ofi'][:]=False
            f['nonzero_ofi_count'][:]=2;f['ofi_ratio'][:]=-side
        assert (strategy.price_state(high,flow,config)['raw_mode']==side).all()
        for market in flow['markets'].values():market['flow'][15]['nonzero_ofi_count'][:]=3
        assert (strategy.price_state(high,flow,config)['raw_mode']==0).all()
    def cut(tree: object,stop: int) -> object:
        """機能: 人工価格格子を再帰切断する。

        引数: tree(object)、stop(int)。返り値: objectは接頭部。
        """
        if isinstance(tree,dict):return {key:cut(value,stop) for key,value in tree.items()}
        return tree[:stop].copy() if isinstance(tree,np.ndarray) else tree
    for stop in (3,11,21,32):
        result=strategy.price_state(cut(price,stop),cut(book,stop),config)
        for key,value in base.items():np.testing.assert_array_equal(result[key],value[:stop])
        changed=copy.deepcopy(price)
        for market in changed['markets'].values():
            market['current']['value'][stop:]=1e6;market['windows'][300]['ret_bp'][stop:]=200
            market['windows'][300]['efficiency'][stop:]=.99;market['current']['raw_seq'][stop:]+=9000
        result=strategy.price_state(changed,book,config)
        for key,value in base.items():np.testing.assert_array_equal(result[key][:stop],value[:stop])
    return dict(G0未知共同0の準備維持=True,G2観測可能な持続確認=True,価格原seq時計=True,
                十分な旧OFI逆証拠だけ除外=True,状態未来切断=4,状態未来変形=4)


def main() -> None:
    """機能: 全53人工と旧5完全一致及び初回現在ゲートの機会消費を確認する。

    引数: なし。返り値: Noneは対象SHA付き人工証跡の保存。
    """
    strategy,catalog,_=support.components();engine=strategy.ENGINE;old=strategy.LEGACY.ENGINE;fixture=fixtures()
    configs=catalog.catalog();controls={'OLD_C11','J8','J10','I0_G0_S0_T0','I0_G0_S1_T0'}
    count=matched=0
    for config in configs:
        for symbol in ('TOPIX','NK225'):
            for mirrored in (False,True):
                record,signal=fixture.sample(symbol,'観測回復の自己と相手の時差',mirrored,config);enrich(record,signal)
                signal['event'][10]=-1 if mirrored else 1
                result=engine.execute(record,signal,config)
                assert result['price_source_trace'].shape==(len(record['time_s']),22)
                if config['id'] in controls:
                    previous=old.execute(record,signal,config)
                    for name in ('orders','trades','curve','source_curve','target_trace','events','stats','slots',
                                 'range_state_trace','risk_state_trace','range_parent_diagnostics'):
                        np.testing.assert_array_equal(result[name],previous[name])
                    matched+=1
                count+=1
    byid={config['id']:config for config in configs};boundaries=prefixes=0
    for gate in (1,2):
        for symbol in ('TOPIX','NK225'):
            for mirrored in (False,True):
                config=byid[f'I3_G{gate}_S0_T0']
                record,signal=fixture.sample(symbol,'同値極値の形成行を保持',mirrored,config);enrich(record,signal)
                if gate==1:signal['price_observable'][11]=False
                else:signal['price_mode'][11]=0
                signal['arm_common'][19]=1 if mirrored else -1
                result=engine.execute(record,signal,config);events=result['events'];gates=events[events[:,3]==27]
                np.testing.assert_array_equal(gates[:2,0],[11,28]);np.testing.assert_array_equal(gates[:2,11],[0,1])
                assert not np.any((result['orders'][:,7]==1)&(result['orders'][:,1]<28))
                assert (result['risk_state_trace'][11:19,0]==1).all()
                trace=result['price_source_trace'];assert trace[11,2]!=trace[11,6] and trace[11,3]!=trace[11,7]
                assert trace[11,17]==11 and trace[11,18]==0 and trace[28,17]==28 and trace[28,18]==1
                for stop in (6,11,12,18,20,29,34):
                    r,s=support.prefix(record,signal,stop);part=engine.execute(r,s,config,finish=False)
                    support.prefix_equal(result,part,stop);prefixes+=1
                boundaries+=1
    state=state_cases(strategy,configs[0])
    paths=[Path(__file__),support.WORK.parent/'wave_v92/audit/execution_checks.py',
           support.WORK.parent/'wave_v93/engine.py',support.WORK.parent/'wave_v93/strategy.py']
    support.save('全53人工と旧5経済及び独立価格の現在ゲート因果検査.json',
                 dict(全合格=True,条件数=53,人工経路=count,旧5比較経路=matched,旧比較配列数=11,
                      初回現在ゲート境界経路=boundaries,境界未来切断=prefixes,価格分類の検査=state,
                      新保存場損益計算=0,採択用新損益閲覧=0),paths)


if __name__=='__main__':main()
