"""予定距離・実損切り・新観測解除の意味を、明示した人工正負例で検査する。"""

from pathlib import Path
import numpy as np

import common
import execution_checks
import entry_checks
import protocol


def run(config,symbol,scenario,reflected):
    """
    機能: 指定した人工板を再生し、独立入力状態・親会計・最初triggerを照合する。
    引数: config(dict)、symbol/scenario(str)、reflected(bool)。
    返り値: tuple[dict,dict,dict] の原板・信号・結果。
    """
    import strategy
    record,signal = execution_checks.sample(symbol,scenario,reflected,config)
    result = strategy.ENGINE.execute(record,signal,config)
    protocol.verify(record,signal,config,result)
    protocol.arm_state(record,signal,config,result)
    return record,signal,result


def main():
    """
    機能: 不合格消費、停止OR、中心負け、予約後休止、新源と再準備の正負条件を検算する。
    引数: なし。
    返り値: None。人工以外の完結損益は計算又は閲覧しない。
    """
    import sys
    sys.path.insert(0,str(common.WORK))
    import catalog
    configs = {value['id']:value for value in catalog.catalog()}
    checks = []
    for symbol in common.SYMBOLS:
        for mirror in (False,True):
            _,_,r = run(configs['C03'],symbol,'初回見送り後に古い回復復活禁止',mirror)
            gates = r['events'][r['events'][:,3]==27]
            assert len(gates) and gates[0,0]==11 and gates[0,11]==0
            assert not np.isin(gates[:,0],np.arange(12,20)).any()
            assert r['risk_state_trace'][14,0]==1
            checks.append(dict(商品=symbol,反射=mirror,条件='見送りは同エピ消費',判断行=11))
            _,_,r = run(configs['C03'],symbol,'見送り解除後の新準備',mirror)
            gates = r['events'][r['events'][:,3]==27]
            assert gates[0,11]==0 and ((gates[:,0]>19)&(gates[:,11]==1)).any()
            _,_,r = run(configs['C02'],symbol,'停止OR両証拠を保存',mirror)
            assert np.array_equal(r['risk_state_trace'][14,18:20],[1,1])
            assert r['range_parent_diagnostics'][0,25]==r['range_parent_diagnostics'][0,26]==1
            checks.append(dict(商品=symbol,反射=mirror,条件='停止OR両証拠',判断行=14))
            _,_,r = run(configs['C11'],symbol,'返済予約だけで休止しない',mirror)
            assert not r['risk_state_trace'][14:19,21].any() and r['risk_state_trace'][19,21]==1
            checks.append(dict(商品=symbol,反射=mirror,条件='実返済まで休止しない',実返済行=19))
            _,_,r = run(configs['C09'],symbol,'極値停止の次気配で利益なら休止しない',mirror)
            assert r['trades'][0,11]>0 and not r['risk_state_trace'][:20,21].any()
            _,_,r = run(configs['C09'],symbol,'固定停止だけは構造休止しない',mirror)
            assert r['trades'][0,11]<0 and r['range_parent_diagnostics'][0,25]==1
            assert r['range_parent_diagnostics'][0,26]==0 and not r['risk_state_trace'][:20,21].any()
            _,_,r = run(configs['C11'],symbol,'中心利確の次気配損失',mirror)
            assert r['trades'][0,13]==15 and r['trades'][0,11]<0
            assert not r['risk_state_trace'][:20,21].any()
            checks.append(dict(商品=symbol,反射=mirror,条件='中心返済でも実約定負なら損失',実損失=float(r['trades'][0,11])))
            _,_,r = run(configs['C06'],symbol,'同一行停止と中心利確の優先',mirror)
            assert r['trades'][0,13]==14 and r['range_parent_diagnostics'][0,26]==1
            assert r['range_parent_diagnostics'][0,27]==0
            for scenario in ('N4自己帰還のみ','N4相手時計同時は解除しない','N4相手源未更新は解除しない',
                             'N4帰還欠測は解除しない','同時計後続N4の源時計'):
                _,_,r = run(configs['C09'],symbol,scenario,mirror)
                assert r['risk_state_trace'][20,21]==1
                assert not ((r['events'][:,3]==30)&(r['events'][:,0]==20)).any()
                _,_,self_only = run(configs['C08'],symbol,scenario,mirror)
                assert self_only['risk_state_trace'][20,21]==0
                checks.append(dict(商品=symbol,反射=mirror,条件=scenario,双方解除しない行=20,自己のみ解除行=20))
            _,_,r = run(configs['C09'],symbol,'N4異時点帰還を寄せ集めない',mirror)
            assert r['risk_state_trace'][20:22,21].all() and r['risk_state_trace'][22,21]==0
            for scenario in ('N4新準備の欠測Falseを除外','N4新準備の全窓未更新を除外','N4新準備の共同方向Falseは有効'):
                _,_,r = run(configs['C10'],symbol,scenario,mirror)
                assert r['risk_state_trace'][20:22,30].sum()==0
                assert r['risk_state_trace'][22,30]==1 and r['risk_state_trace'][23,21]==0
                assert not ((r['events'][:,3]==12)&(r['events'][:,0]==23)).any()
                assert ((r['events'][:,3]==12)&(r['events'][:,0]==24)).any()
                checks.append(dict(商品=symbol,反射=mirror,条件=scenario,有効False行=22,確認True解除行=23,新準備行=24))
            record,_,r = run(configs['C09'],symbol,'N4旧失敗中心を復活しない',mirror)
            assert r['range_state_trace'][21,1]==record['price'][21]
            assert r['range_state_trace'][21,1]!=r['risk_state_trace'][21,22]
            checks.append(dict(商品=symbol,反射=mirror,条件='旧失敗中心と新注文中心を別記録',新準備行=21))
    common.save('予定距離と停止OR及び実損切り後の新観測の人工正負境界.json',
                dict(全合格=True,全31既知=True,具体例=checks,新完結実損益計算=0,新完結実損益閲覧=0,
                     SHA256=common.fingerprint([Path(__file__),Path(execution_checks.__file__),Path(entry_checks.__file__),
                                               common.WORK/'engine.py',common.WORK/'strategy.py',common.WORK/'catalog.py'])))


if __name__=='__main__':
    main()
