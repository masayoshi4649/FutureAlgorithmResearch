"""無効価格を挟む返済反映と、T4の条件未達を追加確認する。"""

import numpy as np

from boundaries import fixture, check_source_order
from support import components, clip, compare_prefix, save, source_hashes


def main():
    """
    機能: 無効観測でも返済事実を失わず、T4の根拠無効又は1ATR未達を拒否するか確認する。
    引数: なし。
    返り値: None。固定戦略を変更せず証跡だけを保存する。
    """
    strategy, catalog, _, _ = components()
    strategy.base.integration.reference.initialize()
    configs = {c['id']: c for c in catalog.catalog()}
    hashes = source_hashes()
    checks = []
    for reflected in (False, True):
        ready, feature = fixture([100,101,106,104,np.nan,100,101,106,104],
                                  list(range(9)), reflected=reflected)
        config = configs['T2_A0']
        full, _ = strategy.play(config,ready,feature,observed=True)
        check_source_order(full)
        assert full['prepare_events'][:,1].tolist()==[0,5]
        assert full['orders'][full['orders'][:,7]==1,0].tolist()==[1,6]
        assert full['reentry_events'][0,:2].tolist()==[3,4]
        for count in (4,5,6,7):
            part,_=strategy.play(config,clip(ready,count,9),clip(feature,count,9),observed=True)
            compare_prefix(full,part,count)
        checks.append(dict(検査='返済直後が無効価格でも次有効観測から新準備、当該無効観測の返済反映は一回',
                           ショート=reflected,合格=True))
        for observed in (False,True):
            for invalid,peak in ((False,104.5),(True,105.)):
                ready,feature=fixture([100,101,peak,104,103,100],list(range(6)),reflected=reflected,
                    bad=[0,0,-1,1,1,1],source=[-1,-1,2,2,2,2],
                    valid=[True,True,not invalid,True,True,True])
                result,_=strategy.play(configs['T4_A0'],ready,feature,observed=observed)
                assert len(result['dynamic_events'])==0
                checks.append(dict(検査='無効B00又は最大順行1ATR未達では短縮しない',
                    根拠無効=invalid,ショート=reflected,観測約定=observed,合格=True))
    assert source_hashes()==hashes
    save('欠測反映とT4未達の追加境界.json',dict(全合格=True,検査=checks,実装SHA256=hashes))
    print('追加境界',len(checks),'件合格',flush=True)


if __name__=='__main__':
    main()
