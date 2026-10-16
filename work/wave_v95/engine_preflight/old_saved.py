"""許可済み旧2数量対照だけを全31で再生し、旧保存経済台帳へ完全一致させる。"""

import gc
import hashlib
from pathlib import Path

import numpy as np

import support


def main() -> None:
    """機能: 旧2数量対照124口座の注文・親・全原板時価と潜在状態を照合する。

    引数: なし。返り値: None。新部品の完結損益や採択用集計は作らない。
    """
    strategy,catalog,data=support.components();material=data.load_inputs()
    configs={config['id']:config for config in catalog.catalog()}
    pairs={'P0_R0':'J8','J10':'J10'}
    checks=[];signal_checks=[];paths=[Path(__file__),Path(data.__file__),*material['paths']]
    for ident,previous in pairs.items():
        ledgers={}
        for part in ('front','back'):
            path=support.WORK.parent/'wave_v94'/part/'ledgers'/f'{previous}.pkl'
            result_path=support.WORK.parent/'wave_v94'/part/'results'/f'{previous}.json'
            result=support.read(result_path);assert support.digest(path)==result['ledger_SHA256']
            ledgers.update(support.read(path));paths.extend((path,result_path))
        prepared=strategy.prepare(material,configs[ident])
        legacy_prepared=strategy.LEGACY.prepare(material,configs[ident])
        signal_count=0
        for key in prepared:
            for name,array in legacy_prepared[key]['signal'].items():
                if isinstance(array,np.ndarray):
                    np.testing.assert_array_equal(prepared[key]['signal'][name],array)
                    signal_count+=1
            assert prepared[key]['trend_candidate_state'] is material['legacy'][key]
        signal_checks.append(dict(id=ident,旧ID=previous,全旧信号配列一致数=signal_count,
                                  旧候補保持=True,入口イベント保持=True))
        del legacy_prepared
        for key in sorted(prepared):
            output=strategy.play(configs[ident],key,prepared);old=ledgers[key]
            for name in ('orders','trades','events','stats','slots','range_parent_diagnostics'):
                np.testing.assert_array_equal(output[name],old[name])
            for name in ('curve','source_curve','target_trace','range_state_trace','risk_state_trace','price_source_trace'):
                stored={'range_state_trace':'range_state_SHA256','risk_state_trace':'risk_state_SHA256','price_source_trace':'price_source_SHA256'}.get(name,name+'_SHA256')
                assert hashlib.sha256(output[name].tobytes()).hexdigest()==old[stored],(ident,key,name)
            assert len(output['loss_reentry_events'])==0
            checks.append(dict(id=ident,旧ID=previous,session=key[0],symbol=key[1],全原板行数=len(output['curve'])))
            del output
        print(ident+' 旧'+previous+' 全31注文・全時価・旧状態・signal '+str(signal_count)+'配列一致',flush=True)
        del ledgers,prepared;gc.collect()
    assert len(checks)==124
    support.save('旧2数量対照の全31経済と状態の完全一致.json',dict(全合格=True,条件数=2,口座数=124,
                 各口座=checks,信号対照=signal_checks,全旧信号配列一致数=sum(row['全旧信号配列一致数'] for row in signal_checks),
                 新基本条件の完結損益計算=0,採択用新損益集計=0),paths)


if __name__=='__main__':main()
