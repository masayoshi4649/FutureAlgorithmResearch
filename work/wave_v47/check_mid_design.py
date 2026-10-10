"""途中判断13条件の集合・由来・旧注文器接続を人工価格だけで検査する。"""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import socket
import sys
from unittest.mock import patch

import numpy as np

import mid_design as design

HERE, ROOT = design.HERE, design.ROOT
sys.path.insert(0,str(HERE.parent/'wave_v44'))
import runner as old
assert Path(old.__file__).resolve() == HERE.parent/'wave_v44/runner.py'
specification = importlib.util.spec_from_file_location('mid_old_check',HERE.parent/'wave_v44/check_runner.py')
helpers = importlib.util.module_from_spec(specification)
specification.loader.exec_module(helpers)


def must_reject(function: object, *args: object) -> None:
    """機能: 人工の仕様破損が受理されないことを検査する。

    引数: function(callable)、args(tuple)。返り値: なし(None)。
    """
    try:function(*args)
    except (AssertionError,KeyError,ValueError):return
    raise AssertionError('不正な条件が拒否されませんでした')


def run() -> dict:
    """機能: 全13接続と復元の有無・時計の新公開境界を旧厳格監査で検査する。

    引数: なし。返り値: 人工検査と由来集合の証跡(dict)。実入力は初期化しない。
    """
    old.audit.cash.close = old.audit.close
    specs = design.catalog(); origins = design.origins()
    assert len(specs) == 13 and set(origins) == {s['id'] for s in specs}
    seen = {(s['gate_threshold_atr'],s['policy']['reduce_fraction'],s['policy']['restore_mode'])
            for s in specs if s['id'] != design.BASELINE}
    assert seen == {(g,f,m) for g in (0.,1.5) for f in (.25,.5) for m in design.MODES}
    results = []; active = []; timers = []; rejected = 0
    for spec in specs:
        for symbol in ('TOPIX','NK225'):
            for inactive in (False,True):
                ready, columns, config = helpers.fixtures.artificial(spec,symbol,inactive)
                valid = columns[5].copy()
                actual = old.play(spec,ready,columns,config,gate_valid=valid)
                row, curves = helpers.inspect(spec,ready,columns,config,actual)
                check = old.causal_check(spec,ready,columns,config,actual,valid)
                if spec['policy']['restore_mode'] == 'none':assert row['restorations'] == 0
                if inactive:assert row['net_yen'] == 0 and row['cycles'] == 0
                results.append(dict(id=spec['id'],symbol=symbol,無活動=inactive,独立会計一致=True,**check))
            if spec['id'] == design.BASELINE:continue
            ready,columns,config,valid = helpers.active_gate_fixture(spec,symbol)
            ready['last'] = np.array([100,101,103,104,105,106,107,108,108,108,108,108,
                108,108,108,108,108,108,109,111,112,110,103,100,100,100.],float)
            actual = old.play(spec,ready,columns,config,gate_valid=valid)
            row,_ = helpers.inspect(spec,ready,columns,config,actual)
            usage = old.gate_record(spec,ready,columns,actual[1],actual[2],valid,actual[0])
            assert row['reductions'] > 0, (spec['id'],symbol,'減量未作動')
            if spec['policy']['restore_mode'] == 'none':assert row['restorations'] == 0
            else:assert row['restorations'] > 0,(spec['id'],symbol,'復元未作動')
            if spec['gate_threshold_atr'] > 0:
                assert usage['armed_campaigns'] > 0
                passed = actual[1][1] != 0
                assert np.all(actual[1][2][passed] > actual[2]['arm_row'][passed])
            active.append(dict(id=spec['id'],symbol=symbol,減量=row['reductions'],復元=row['restorations']))
    # ----------------------------------------
    # 時計復元は119秒時点の公開を保持しても許可せず、期限後の新しい公開を要求する。
    for symbol in ('TOPIX','NK225'):
        spec = design.specification(1.5,50,'timer')
        for case, expected in (('期限等号',13),('119秒公開の保持',16),('無効最新公開',17)):
            ready,columns,config,valid = helpers.active_gate_fixture(spec,symbol)
            ready['last'] = np.array([100,101,103,104,105,106,107,108,108,108,108,108,
                108,108,108,108,108,108,109,111,112,110,103,100,100,100.],float)
            cols = [v.copy() for v in columns]
            cols[3][:] = 0  # 時計方式は有効な中立公開でもよい。
            if case != '期限等号':
                ready['time_s'][11] = 359.
                cols[4][12:15] = 11
            if case == '無効最新公開':cols[5][15] = False
            actual = old.play(spec,ready,tuple(cols),config,gate_valid=valid)
            helpers.inspect(spec,ready,tuple(cols),config,actual)
            events = actual[0]['adjustment_events']
            restored = events[(events[:,2] == 2)&(events[:,3] == 1)]
            assert len(restored) == 1 and int(restored[0,0]) == expected,(case,symbol,restored)
            timers.append(dict(境界=case,symbol=symbol,復元行=expected,独立監査一致=True))
    # ----------------------------------------
    # 欠落・未分類の実行項目を名前変更として消去しない。
    for field in design.ECONOMIC_FIELDS:
        altered = deepcopy(specs[-1]);del altered[field]
        must_reject(design.economic_spec,altered,47);rejected += 1
    altered = deepcopy(specs[-1]);altered['unknown_execution_field'] = 1
    must_reject(design.economic_spec,altered,47);rejected += 1
    for field in ('restore_seconds','reduce_fraction','max_reductions','good_id','restore_mode'):
        altered = deepcopy(specs[-1]);del altered['policy'][field]
        must_reject(design.economic_spec,altered,47);rejected += 1
    evidence = design.reuse_evidence()
    assert evidence['全合格'] and evidence['成果再利用条件数'] == 7
    paths = {Path(__file__),HERE/'mid_design.py'}
    for module in tuple(sys.modules.values()):
        source = getattr(module,'__file__',None)
        if source:
            path = Path(source).resolve()
            if path.is_relative_to(ROOT/'work') and path.suffix == '.py':paths.add(path)
    references = {p.relative_to(ROOT).as_posix():design.digest(p) for p in sorted(paths)}
    for p in (HERE.parent/'wave_v37/partial_design_fixed.json',
              HERE.parent/'wave_v38/探索条件の固定.json',HERE.parent/'wave_v44/探索条件の固定.json'):
        references[p.relative_to(ROOT).as_posix()] = design.digest(p)
    return dict(全合格=True,全条件数=13,人工口座数=len(results),活動経路数=len(active),
        時計境界数=len(timers),時計境界=timers,破損拒否数=rejected,結果=results,減量復元の活動=active,再利用条件数=7,既知互換再生条件数=2,
        未試行機構条件数=4,旧厳格会計を無変更使用=True,新実相場損益=False,
        実入力初期化=False,現在API取得数=0,保存ライブ使用=False,参照資料SHA256=references)


if __name__ == '__main__':
    with patch.object(socket,'create_connection',side_effect=AssertionError('通信禁止')):
        result = run()
    design.save(HERE/'check_mid_design.json',result)
    print(f"人工{result['人工口座数']}・活動{result['活動経路数']}・拒否{result['破損拒否数']}合格",flush=True)
