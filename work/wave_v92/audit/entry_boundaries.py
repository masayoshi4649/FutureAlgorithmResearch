"""回復確認と中心帰還が実際に違う判断を作る人工反例を具体値で固定する。"""

from pathlib import Path

import numpy as np

import common
import entry_checks
from execution_checks import sample


def main():
    """
    機能: 確認なし・自己・両回復と、異時点帰還を足せない境界を独立状態と照合する。
    引数: なし。
    返り値: None。全実損益を計算又は閲覧せず人工証跡だけ保存する。
    """
    import sys
    sys.path.insert(0, str(common.WORK))
    import strategy, catalog
    configs = {value['id']:value for value in catalog.catalog()}
    proofs = []
    for symbol in common.SYMBOLS:
        for reflected in (False,True):
            firsts = {}
            for ident in ('R0_C','R_S25_C','R_B25_C'):
                config = configs[ident]
                record,signal = sample(symbol,'観測回復の自己と相手の時差',reflected,config)
                result = strategy.ENGINE.execute(record,signal,config)
                entry_checks.verify(record,signal,config,result)
                reserve = result['events'][(result['events'][:,2]==1)&(result['events'][:,3]==1)]
                firsts[ident] = int(reserve[0,0])
            assert firsts == dict(R0_C=5,R_S25_C=11,R_B25_C=14), firsts
            config = configs['R_S25_C']
            record,signal = sample(symbol,'同値極値の形成行を保持',reflected,config)
            result = strategy.ENGINE.execute(record,signal,config)
            entry_checks.verify(record,signal,config,result)
            own_column,peer_column = (8,12) if not reflected else (10,14)
            assert np.all(result['range_state_trace'][8:11,own_column]==8)
            assert np.all(result['range_state_trace'][8:11,peer_column]==8)
            record,signal = sample(symbol,'気配差だけ縮小して回復なし',reflected,config)
            result = strategy.ENGINE.execute(record,signal,config)
            entry_checks.verify(record,signal,config,result)
            reserves = result['events'][(result['events'][:,2]==1)&(result['events'][:,3]==1)]
            assert not (reserves[:,0]<20).any()
            record,signal = sample(symbol,'残存約定価格から逸脱を初選択しない',reflected,config)
            result = strategy.ENGINE.execute(record,signal,config)
            entry_checks.verify(record,signal,config,result)
            assert not ((result['events'][:,3]==17)&(result['events'][:,0]>=5)&(result['events'][:,0]<14)).any()
            record,signal = sample(symbol,'約定価格欠測でも既監視の気配回復',reflected,config)
            result = strategy.ENGINE.execute(record,signal,config)
            entry_checks.verify(record,signal,config,result)
            assert ((result['events'][:,3]==1)&(result['events'][:,2]==1)&(result['events'][:,0]==11)).sum()==1
            returns = {}
            for ident in ('KS25','KB25'):
                config = configs[ident]
                record,signal = sample(symbol,'双方帰還を異時点で足し合わせない',reflected,config)
                result = strategy.ENGINE.execute(record,signal,config)
                entry_checks.verify(record,signal,config,result)
                returns[ident] = int(result['events'][result['events'][:,3]==24,0][0])
            assert returns == dict(KS25=19,KB25=34), returns
            barriers = {}
            for scenario in ('返済時相手欠測後の同一源帰還は無効','相手中心初観測を帰還として数えない'):
                config = configs['KB25']
                record,signal = sample(symbol,scenario,reflected,config)
                result = strategy.ENGINE.execute(record,signal,config)
                entry_checks.verify(record,signal,config,result)
                returned_rows = result['events'][result['events'][:,3]==24,0]
                assert len(returned_rows) and returned_rows[0] == 20
                barriers[scenario] = dict(帰還行=20,初観測又は同じ源の19行を拒否=True,
                                          返済時公開源=result['range_state_trace'][18,19])
            proofs.append(dict(商品=symbol,上下反射=reflected,最初成行判断=firsts,
                               最初再参加帰還=returns,同値極値形成行=8,
                               気配差縮小のみを回復へ代用しない=True,
                               初選択には有効約定価格が必要=True,
                               既選択後は気配mid回復で判定可能=True,
                               相手欠測の帰還障壁=barriers))
    common.save('新規確認と同時帰還の具体的人工境界.json',dict(
        全合格=True,条件数=len(configs),人工境界=proofs,新完結実損益計算=0,新完結実損益閲覧=0,
        現在API取得=0,実注文=0,SHA256=common.fingerprint([
            Path(__file__),common.HERE/'entry_checks.py',common.HERE/'execution_checks.py',
            common.HERE/'protocol.py',common.WORK/'engine.py',common.WORK/'strategy.py',common.WORK/'catalog.py'])))
    print('回復なし5行・自己11行・双方14行、自己帰還19行・同時双方34行を独立確認',flush=True)


if __name__ == '__main__':
    main()
