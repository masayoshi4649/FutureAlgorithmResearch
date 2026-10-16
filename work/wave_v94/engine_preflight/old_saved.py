"""許可済み旧5対照だけを全31で再生し、旧保存経済台帳へ完全一致させる。"""

import gc
import hashlib
from pathlib import Path

import numpy as np

import support


def main() -> None:
    """機能: 旧5対照310口座の注文・親・全原板時価と潜在状態を照合する。

    引数: なし。返り値: None。新部品の完結損益や採択用集計は作らない。
    """
    strategy,catalog,data=support.components();material=data.load_inputs()
    configs={config['id']:config for config in catalog.catalog()}
    pairs={'I0_G0_S0_T0':'C00','I0_G0_S1_T0':'C01','OLD_C11':'C11','J8':'S00','J10':'S01'}
    checks=[];paths=[Path(__file__),Path(data.__file__),*material['paths']]
    for ident,previous in pairs.items():
        ledgers={}
        for part in ('front','back'):
            path=support.WORK.parent/'wave_v93'/part/'ledgers'/f'{previous}.pkl'
            result_path=support.WORK.parent/'wave_v93'/part/'results'/f'{previous}.json'
            result=support.read(result_path);assert support.digest(path)==result['ledger_SHA256']
            ledgers.update(support.read(path));paths.extend((path,result_path))
        prepared=strategy.prepare(material,configs[ident])
        for key in sorted(prepared):
            output=strategy.play(configs[ident],key,prepared);old=ledgers[key]
            for name in ('orders','trades','events','stats','slots','range_parent_diagnostics'):
                np.testing.assert_array_equal(output[name],old[name])
            for name in ('curve','source_curve','target_trace','range_state_trace','risk_state_trace'):
                stored={'range_state_trace':'range_state_SHA256','risk_state_trace':'risk_state_SHA256'}.get(name,name+'_SHA256')
                assert hashlib.sha256(output[name].tobytes()).hexdigest()==old[stored],(ident,key,name)
            checks.append(dict(id=ident,旧ID=previous,session=key[0],symbol=key[1],全原板行数=len(output['curve'])))
            del output
        print(ident+' 旧'+previous+' 全31注文・全時価・旧状態が一致',flush=True)
        del ledgers,prepared;gc.collect()
    assert len(checks)==310
    support.save('旧5対照の全31経済と状態の完全一致.json',dict(全合格=True,条件数=5,口座数=310,
                 各口座=checks,新基本条件の完結損益計算=0,採択用新損益集計=0),paths)


if __name__=='__main__':main()
