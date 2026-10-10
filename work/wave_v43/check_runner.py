"""実相場の損益を作らず、時間窓合議の注文接続を元の厳格監査で検査する。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import socket
import sys
from unittest.mock import patch

import numpy as np

import runner
import adaptive_statistics_selftest as fixtures


HERE, ROOT = runner.HERE, runner.ROOT


def wiring(specs: list[dict]) -> dict:
    """機能: 入口だけを置換し、元の九つの管理入力を変更しないことを検査する。

    引数: specs(list[dict])。返り値: 接続と旧六条件の照合結果(dict)。
    実入力や旧保存損益を読まず、条件定義と人工列だけを用いる。
    """
    key = ('2026-09-21_Day', 'TOPIX')
    ready, columns, _ = fixtures.artificial(specs[0], key[1])
    original = runner.read(HERE.parent/'wave_v38/探索条件の固定.json')['conditions']
    by_id = {spec['id']: spec for spec in original}
    entries = {name: {key: np.roll(columns[0], i).copy()} for i, name in enumerate(runner.design.SIGNALS)}
    count, legacy = 0, []
    with patch.object(runner, 'ENTRIES', entries):
        for spec in specs:
            with patch.object(runner.old, 'columns', return_value=columns) as prior:
                result = runner.columns_for(spec, key)
            args = prior.call_args.args
            assert args == (dict(spec, signal_id='H019', entry_scale=1.), key)
            assert result[0] is entries[spec['window_id']][key]
            assert len(result) == 10 and all(result[i] is columns[i] for i in range(1, 10))
            previous = runner.legacy_id(spec)
            if previous:
                older = by_id[previous]
                exclusions = {'id', 'signal_id', 'entry_scale', 'variant_id', 'role', 'primary', 'window_id', 'prior_manager'}
                assert {k:v for k,v in spec.items() if k not in exclusions} == {
                    k:v for k,v in older.items() if k not in exclusions}, previous
                assert older['entry_scale'] == {'S080':.8, 'S100':1., 'S120':1.2}[spec['window_id']]
                legacy.append(dict(id=spec['id'], 旧ID=previous, 元管理不変=True))
            count += 1
    assert len(legacy) == 6 and len({v['旧ID'] for v in legacy}) == 6
    return dict(全条件入力接続数=count, 旧単一窓条件対応=legacy,
                旧実入力156同値は本再生で検査=True, この検査で旧実入力を再生=False)


def strict_inspect(spec: dict, ready: dict, columns: tuple, config: dict, result: dict) -> tuple:
    """機能: 原版の会計・枠・予約・成熟注文と別式の全表示統計を照合する。

    引数: spec/ready/config/result(dict)、columns(tuple)。返り値: 指標・曲線・証跡(tuple)。
    診断版を使わず、不一致を緩和しない。
    """
    row, curves, proof, basic = runner.audit.inspect(spec, ready, result, config, columns)
    assert all(proof[flag] is True for flag in runner.PROOF_FLAGS)
    assert proof['原本行数'] == len(ready['last'])
    displayed = runner.old.session_row(spec['id'], ready, result, config, columns[1], basic, curves)
    runner.audit.statistics.equal(displayed, row, '人工全session必須統計')
    return row, curves, proof


def stronger_future(spec: dict, ready: dict, columns: tuple, config: dict, result: dict) -> None:
    """機能: 未来の価格・ATRに加え、根拠元と品質の全役割を変更して過去を守る。

    引数: spec/ready/config/result(dict)、columns(tuple)。返り値: なし(None)。
    影も変えた入力から作り直し、元の未来計画を再利用しない。
    """
    n = len(ready['last']); cut = max(2, int(n*.73))
    changed = runner.causal.clipped(ready, n)
    changed['last'][cut:] += ready['tick']*(37+np.arange(n-cut))
    changed['atr'][cut:] *= 3
    altered = [v.copy() for v in columns]
    for index in (0, 1, 3, 6):
        altered[index][cut:] = np.where(altered[index][cut:] == 1, -1, 1)
    for index in (2, 4, 7):
        altered[index][cut:] = np.arange(cut, n)
    for index in (5, 8):
        altered[index][cut:] = ~altered[index][cut:]
    altered[9][cut:] = 1-altered[9][cut:]
    future = runner.play(spec, changed, tuple(altered), config)
    runner.causal.prefix(result, future, cut)


def reflection(spec: dict, ready: dict, columns: tuple, config: dict, result: dict) -> None:
    """機能: 全方向と価格の鏡映が、金銭・数量・注文・管理状態を保つか確認する。

    引数: spec/ready/config/result(dict)、columns(tuple)。返り値: なし(None)。
    """
    center = float(2*np.ceil(max(ready['last'])/ready['tick'])*ready['tick'])
    mirrored = dict(ready, last=center-ready['last'])
    directions = tuple(-v if i in (0,1,3,6) else v.copy() for i,v in enumerate(columns))
    other = runner.play(spec, mirrored, directions, config)
    strict_inspect(spec, mirrored, directions, config, other)
    runner.causal.reflected_result(result, other, center, True)
    runner.causal.reflected_result(result['shadow'], other['shadow'], center, False)


def reject_damage(retained: tuple) -> int:
    """機能: 注文・枠・状態の改竄と必須統計の欠落が元監査で拒否されるか試す。

    引数: retained(tuple)。返り値: 拒否数(int)。
    """
    spec, ready, columns, config, actual, row = retained
    rejected = 0
    for field, index in (('orders',(0,4)), ('slot_curve',(2,0)), ('control_curve',(2,2))):
        changed = deepcopy(actual); changed[field][index] += 1
        try:
            strict_inspect(spec, ready, columns, config, changed)
        except (AssertionError, IndexError, KeyError, ValueError):
            rejected += 1
        else:
            raise AssertionError('破損を受理:'+field)
    for name in row:
        changed = deepcopy(row); del changed[name]
        try:
            runner.audit.statistics.equal(changed, row, '全統計の必須項目欠落')
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError('統計欠落を受理:'+name)
    return rejected


def run() -> dict:
    """機能: 全32条件の両銘柄・活動/無取引128入力を実相場なしで検査する。

    引数: なし。返り値: 参照指紋を含む人工監査証跡(dict)。
    """
    runner.audit.cash.close = runner.audit.close
    assert Path(runner.engine.__file__).resolve() == HERE.parent/'wave_v41/engine_partial_restore_corrected.py'
    assert Path(runner.audit.__file__).resolve() == HERE.parent/'wave_v38/adaptive_accounting_audit.py'
    assert Path(runner.audit.slots.__file__).resolve() == HERE.parent/'wave_v38/adaptive_slot_audit.py'
    paths = {Path(__file__), HERE/'runner.py', HERE/'design.py'}
    for value in tuple(sys.modules.values()):
        name = getattr(value, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.is_relative_to(ROOT/'work') and path.suffix == '.py':
                paths.add(path)
    paths.add(HERE.parent/'wave_v38/探索条件の固定.json')
    before = {p.relative_to(ROOT).as_posix():runner.digest(p) for p in sorted(paths)}
    specs = runner.design.catalog(); assert len(specs) == len({v['id'] for v in specs}) == 32
    connection = wiring(specs)
    inputs = 0; periods = 0; mirror = 0; legacy_artificial = 0; retained = None; records = []
    for spec in specs:
        rows_by_mode = {False:[], True:[]}; curves_by_mode = {False:{}, True:{}}
        for symbol in runner.old.SYMBOLS:
            for inactive in (False, True):
                ready, columns, config = fixtures.artificial(spec, symbol, inactive)
                result = runner.play(spec, ready, columns, config)
                row, curves, proof = strict_inspect(spec, ready, columns, config, result)
                runner.causal_check(spec, ready, columns, config, result)
                stronger_future(spec, ready, columns, config, result)
                assert bool(len(result['orders'])) is not inactive, (spec['id'],symbol,inactive)
                if inactive:
                    assert row['closed_units'] == row['net_yen'] == 0
                else:
                    reflection(spec, ready, columns, config, result); mirror += 1
                if runner.legacy_id(spec):
                    old_result = fixtures.play(spec, ready, columns, config)
                    assert runner.old.fingerprints(old_result) == runner.old.fingerprints(result)
                    assert runner.old.fingerprints(old_result['shadow'],runner.reference.EXPECTED_SHADOW_FIELDS) == runner.old.fingerprints(result['shadow'],runner.reference.EXPECTED_SHADOW_FIELDS)
                    legacy_artificial += 1
                rows_by_mode[inactive].append(row)
                curves_by_mode[inactive][(ready['session'],symbol)] = curves['equity']
                records.append(dict(id=spec['id'],symbol=symbol,無取引=inactive,
                    元厳格監査合格=True,全統計一致=True,先頭切断一致=True,未来全入力改変一致=True,
                    原本行数=proof['原本行数']))
                inputs += 1
                if retained is None and spec['prior_manager'] != 'A0' and not inactive:
                    retained = spec,ready,columns,config,result,row
        for inactive in (False,True):
            rows=rows_by_mode[inactive]; series=curves_by_mode[inactive]; names=['2026-09-21_Day']
            old_period = runner.old.period(rows,names)
            for symbol in runner.old.SYMBOLS:
                independent = runner.audit.statistics.period(rows,series,names,symbol,runner.old.base.research.MULT[symbol])
                runner.audit.statistics.equal(old_period[symbol],independent,'人工全period必須統計')
                periods += 1
    # ----------------------------------------
    # 同秒の行順も次行規則で扱い、現在の後続同秒行を過去へ含めない。
    ties = 0
    for spec in specs:
        if spec['window_id'] != 'M2_100' or spec['variant_id'] not in ('V000','L015'):
            continue
        for symbol in runner.old.SYMBOLS:
            ready, columns, config = fixtures.artificial(spec,symbol)
            ready['time_s'][5] = ready['time_s'][4]
            result = runner.play(spec,ready,columns,config)
            strict_inspect(spec,ready,columns,config,result)
            check=runner.causal_check(spec,ready,columns,config,result)
            assert check['未来変更行'] == 5
            short=runner.play(spec,runner.causal.clipped(ready,5),tuple(v[:5].copy() for v in columns),config)
            runner.causal.prefix(result,short,5)
            ties += 1
    assert inputs == periods == 128 and mirror == 64 and ties == 8 and legacy_artificial == 24
    assert retained is not None
    rejections = reject_damage(retained)
    assert before == {relative:runner.digest(ROOT/relative) for relative in before}
    return dict(全合格=True,全条件数=32,人工入力検査数=inputs,人工期間比較数=periods,
        先頭切断検査数=inputs,未来方向価格ATR改変数=inputs,未来根拠品質全列改変数=inputs,
        上下反射検査数=mirror,同時刻境界検査数=ties,元旧実装人工全15配列一致数=legacy_artificial,
        破損欠落拒否数=rejections,原版厳格監査を無変更使用=True,修正版注文器の明示パス確認=True,
        **connection,検査=records,参照資料SHA256=before,
        新実相場損益=False,旧実相場再生=False,現在API取得数=0,保存ライブ使用=False)


if __name__ == '__main__':
    with patch.object(socket,'create_connection',side_effect=AssertionError('通信禁止')), \
         patch.object(socket.socket,'connect',side_effect=AssertionError('通信禁止')):
        result = run()
    runner.save(HERE/'check_runner.json',result)
    print('全32条件・人工128入力、厳格会計・全統計・因果性検査に合格。',flush=True)
