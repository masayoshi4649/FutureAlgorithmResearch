"""人工だけで研究台帳・疎な反転記録・指紋の実保存再読込を照合する。"""

import hashlib
from pathlib import Path
import sys

import numpy as np

import artificial
import support


def equal(left: object, right: object) -> int:
    """
    機能: 辞書及び配列の保存往復をNaN込みで独立比較する。
    引数: left/right(object)。
    返り値: intは一致した末端要素の数。
    """
    if isinstance(left,dict):
        assert left.keys()==right.keys()
        return sum(equal(left[key],right[key]) for key in left)
    if isinstance(left,np.ndarray):
        np.testing.assert_array_equal(left,right)
    else:
        assert left==right
    return 1


def dense(changes: np.ndarray, size: int) -> np.ndarray:
    """
    機能: 疎な全原行状態を保存形式から独立復元する。
    引数: changes(ndarray[float])、size(int)は元の原行数。
    返り値: ndarray[float]は全原行状態。先頭又は範囲欠落は拒否する。
    """
    assert len(changes) and changes[0,0]==0
    rows=changes[:,0].astype(int)
    assert (np.diff(rows)>0).all() and rows[-1]<size
    result=np.empty((size,changes.shape[1]-1),np.float64)
    for i,row in enumerate(rows):
        end=rows[i+1] if i+1<len(rows) else size
        result[row:end]=changes[i,1:]
    return result


def fake_prepared(config: dict) -> dict:
    """
    機能: 原本と混同しない人工上下2場・両商品の保存用preparedを作る。
    引数: config(dict)。
    返り値: dict[tuple,dict]は人工原板・信号・候補診断。実入力を使用しない。
    """
    result={}
    for mirrored,session in ((False,'2000-01-03_人工上'),(True,'2000-01-04_人工下')):
        for symbol in ('TOPIX','NK225'):
            record,signal=artificial.fixture(symbol,mirrored,'fallback')
            grid=signal['grid'];event=signal['event']
            indices=np.flatnonzero(event)
            candidates=np.column_stack((signal['mapped'][indices],indices,event[indices],indices,indices)).astype(float)
            state=event[grid.astype(int)]
            result[session,symbol]=dict(record=record,signal=signal,
                trend_candidate_state=dict(states=state,valid=np.ones(len(grid),bool),pulse=state,
                    candidates=candidates,own_source=np.arange(len(grid)),peer_source=np.arange(len(grid))+1000),
                trend_lp_allowed={1:np.ones(len(grid),bool),-1:np.ones(len(grid),bool)})
    return result


def fake_run(research: object, config: dict, prepared: dict, base: Path) -> str:
    """
    機能: 研究run_oneへ人工だけを渡し、正式front/back保存先を拒否する。
    引数: research(object)、config/prepared(dict)、base(Path)。
    返り値: strは人工保存した条件ID。正式実入力・正式損益へ接続しない。
    """
    expected=(support.HERE/'人工保存往復').resolve()
    assert base.resolve().is_relative_to(expected)
    assert not base.resolve().is_relative_to((support.WORK/'front').resolve())
    assert not base.resolve().is_relative_to((support.WORK/'back').resolve())
    sessions=['2000-01-03_人工上','2000-01-04_人工下']
    assert set(prepared)=={(session,symbol) for session in sessions for symbol in ('TOPIX','NK225')}
    assert all(record['record']['start']==0. and record['record']['limit']==1000. for record in prepared.values())
    return research.run_one(config,sessions,base,prepared)


def main() -> None:
    """
    機能: 全38×両商品×上下の人工出力をledger/run_one保存後へ完全照合する。
    引数: なし。
    返り値: Noneは保存実装SHA付き証跡。正式新損益及び旧成果を編集しない。
    """
    strategy,catalog,_=support.components()
    sys.path.insert(0,str(support.WORK))
    sys.modules['strategy']=strategy;sys.modules['catalog']=catalog
    research=support.module('人工ledger保存95の根研究読取',support.WORK/'research.py')
    generation=1
    base=support.HERE/'人工保存往復'/f'run_one_{generation:05d}'
    while base.exists():
        generation+=1
        base=support.HERE/'人工保存往復'/f'run_one_{generation:05d}'
    checked=items=restored=0;outputs=[]
    for config in catalog.catalog():
        prepared=fake_prepared(config);expected={};original={}
        for key,value in prepared.items():
            output=strategy.play(config,key,prepared)
            original[key]=output
            expected[key]=research.ledger(output,value)
            assert len(expected[key]['loss_event_columns'])==66
        assert fake_run(research,config,prepared,base)==config['id']
        path=base/'ledgers'/(config['id']+'.pkl');result_path=base/'results'/(config['id']+'.json')
        reloaded=support.read(path);result=support.read(result_path)
        assert result['ledger_SHA256']==support.digest(path)
        assert result['config']==config and len(result['rows'])==4
        items+=equal(expected,reloaded)
        for key,out in original.items():
            saved=reloaded[key]
            np.testing.assert_array_equal(saved['loss_reentry_events'],out['loss_reentry_events'])
            assert saved['loss_event_columns']==strategy.ENGINE.LOSS_EVENT_COLUMNS
            for name,sparse,signature in (('target_trace','trace_changes','target_trace_SHA256'),
                ('range_state_trace','range_state_changes','range_state_SHA256'),
                ('risk_state_trace','risk_state_changes','risk_state_SHA256'),
                ('price_source_trace','price_source_changes','price_source_SHA256')):
                rebuilt=dense(saved[sparse],len(out['curve']))
                np.testing.assert_array_equal(rebuilt,out[name])
                assert hashlib.sha256(rebuilt.tobytes()).hexdigest()==saved[signature]
                restored+=1
            rebuilt=dense(saved['trend_event_changes'],len(out['curve']))[:,0].astype(np.int8)
            np.testing.assert_array_equal(rebuilt,prepared[key]['signal']['event'])
            assert hashlib.sha256(rebuilt.tobytes()).hexdigest()==saved['trend_event_SHA256']
            for field in ('loss_observations','execution_lp_index'):
                assert hashlib.sha256(prepared[key]['signal'][field].tobytes()).hexdigest()==saved[field+'_SHA256']
            checked+=1
        outputs.extend((path,result_path))
    assert checked==152 and restored==608
    support.save('全38人工の根ledgerとrun_one及び66列反転記録と疎復元の保存往復一致.json',
        dict(全合格=True,人工保存位置=str(base.relative_to(support.ROOT)),人工条件=38,人工口座=checked,保存往復末端一致=items,疎全原行状態復元=restored,
             反転診断列=66,候補及び価格執行別源保持=True,正式保存先拒否=True,正式新損益計算=0),
        [Path(__file__),support.WORK/'research.py',support.WORK/'accounting.py',support.HERE/'artificial.py',*outputs])


if __name__=='__main__':
    main()
