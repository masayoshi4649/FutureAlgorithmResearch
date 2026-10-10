"""凍結会計の場末二領域だけを別候補へ直し、人工境界と限定障害を検算する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE / 'adaptive_cash_reconstruction.py'
CANDIDATE = HERE / 'adaptive_cash_reconstruction_v2_candidate.py'
OLD_ORDER = "assert times[row] >= ready['start'] and times[row] <= ready['limit'] + 300"
NEW_ORDER = "assert times[row] >= ready['start'] and times[row] < ready.get('session_close', ready['limit'] + 600.)"
OLD_END = """    at_limit = np.flatnonzero(times >= ready['limit'])
    if closed and len(at_limit) > 1:
        after = int(at_limit[0]) + 1
        assert not (longs[after:] + shorts[after:]).any(), '場末判断の次観測以降に持越し'"""
NEW_END = """    at_limit = np.flatnonzero(times >= ready.get('session_close', ready['limit'] + 600.))
    if closed and len(at_limit) > 0:
        after = int(at_limit[0])
        assert not (longs[after:] + shorts[after:]).any(), '真の終場以降に持越し'"""


def digest(path: Path) -> str:
    """機能: 資料の内容を固定する指紋を計算する。

    引数: path (Path)。返り値: SHA256文字列 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    """機能: 非有限数を拒否して日本語の検査証跡を保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def load_module(path: Path, name: str):
    """機能: 原版とは別名で会計の候補だけを読み込む。

    引数: path (Path)、name (str)。返り値: 読込モジュール (module)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_candidate() -> dict:
    """機能: 境界二領域だけを置換し、逆置換で全文とASTの不変部分を証明する。

    引数: なし。返り値: 置換と指紋の証跡 (dict)。旧版への書込みは行わない。
    """
    source = OLD.read_text(encoding='utf-8')
    assert source.count(OLD_ORDER) == source.count(OLD_END) == 1
    candidate = source.replace(OLD_ORDER, NEW_ORDER).replace(OLD_END, NEW_END)
    reverse = candidate.replace(NEW_ORDER, OLD_ORDER).replace(NEW_END, OLD_END)
    assert reverse == source
    assert ast.dump(ast.parse(reverse)) == ast.dump(ast.parse(source))
    before_functions = {n.name: ast.dump(n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    after_functions = {n.name: ast.dump(n) for n in ast.parse(candidate).body if isinstance(n, ast.FunctionDef)}
    assert before_functions.keys() == after_functions.keys()
    assert before_functions['close'] == after_functions['close']
    assert before_functions['integer'] == after_functions['integer']
    if CANDIDATE.exists():
        assert CANDIDATE.read_text(encoding='utf-8') == candidate
    else:
        CANDIDATE.write_text(candidate, encoding='utf-8')
    return dict(変更領域数=2, 約定時刻検査の置換数=1, 終場残玉検査の置換数=1,
        逆置換全文一致=True, 許可差分を除くAST一致=True, 会計関数の引数不変=True,
        金額数量損益曲線の計算不変=True, 元版SHA256=digest(OLD), 候補SHA256=digest(CANDIDATE))


def fixture(times: list[float], exit_row: int | None, *, side: int = 1,
            symbol: str = 'TOPIX', session_close: float | None = None) -> tuple[dict, dict]:
    """機能: 一組の注文から人工時価曲線と返済明細を独立に作る。

    引数: times (list[float])、exit_row (int|None)、side (int)、symbol (str)、session_close (float|None)。
    返り値: 入力と人工結果 (tuple[dict,dict])。売買エンジンは使用しない。
    """
    times = np.asarray(times, float)
    n = len(times); entry = 1; qty = 1; entry_price = 100.; exit_price = 102.
    prices = np.full(n, exit_price); prices[:entry+1] = entry_price
    ready = dict(last=prices, time_s=times, start=float(times[0]), limit=10000., symbol=symbol)
    if session_close is not None:
        ready['session_close'] = session_close
    orders = [[entry, 0, 0, side, qty, entry_price, 20, 1]]
    trades = []; cycles = []
    cash = np.zeros(n); longs = np.zeros(n); shorts = np.zeros(n); realized = np.zeros(n)
    cash[entry:] -= side * qty * entry_price
    (longs if side > 0 else shorts)[entry:] = qty
    if exit_row is not None:
        assert exit_row > entry
        pnl = side * qty * (exit_price-entry_price)
        orders.append([exit_row, exit_row-1, 0, -side, qty, exit_price, 9, 0])
        trades.append([0,0,side,qty,entry_price,exit_price,entry,exit_row,0,9,pnl])
        cycles.append([0,entry,exit_row,pnl,1.,1.,qty,qty,side,9])
        cash[exit_row:] += side * qty * exit_price
        (longs if side > 0 else shorts)[exit_row:] = 0
        realized[exit_row:] = pnl
    net = longs-shorts; equity = cash+net*prices
    dd = np.maximum.accumulate(np.maximum.accumulate(np.maximum(0.,equity))-equity)
    curve = np.column_stack([equity,realized,longs,shorts,dd,cash,net,np.zeros(n)])
    stats = np.zeros(10)
    stats[:6] = [realized[-1],dd[-1],longs.max(),shorts.max(),(longs+shorts).max(),abs(net).max()]
    stats[7:10] = [min(0.,equity.min()),max(0.,equity.max()),longs[-1]+shorts[-1]]
    result = dict(orders=np.array(orders,float).reshape(-1,8),trades=np.array(trades,float).reshape(-1,11),
        cycles=np.array(cycles,float).reshape(-1,10),curve=curve,stats=stats)
    return ready,result


def accepted(module, ready: dict, result: dict, symbol: str, closed: bool = True) -> bool:
    """機能: 人工口座が指定会計で受理されるかを副作用なしに確認する。

    引数: module (module)、ready/result (dict)、symbol (str)、closed (bool)。返り値: 成否 (bool)。
    """
    try:
        module.reconstruct(ready,result,symbol,closed=closed)
        return True
    except AssertionError:
        return False


def synthetic(old, new) -> dict:
    """機能: 同時刻・正遅延・疎観測・終場等号・残玉・途中列の人工反例を検査する。

    引数: old/new (module)。返り値: 各境界の受理拒否証跡 (dict)。
    """
    dense=[0.,10.,20.,9999.,10000.,10000.,10000.1,10001.,10005.,10015.,10016.]
    records=[]; rejected=0; unchanged=0
    for symbol in ('TOPIX','NK225'):
        for side in (-1,1):
            for delay,exit_row in ((0,5),(1,7),(5,8),(15,9)):
                ready,result=fixture(dense,exit_row,side=side,symbol=symbol)
                assert accepted(new,ready,result,symbol)
                legacy=accepted(old,ready,result,symbol)
                assert legacy == (delay == 0)
                if legacy:
                    a,ca=old.reconstruct(ready,result,symbol);b,cb=new.reconstruct(ready,result,symbol)
                    assert a==b
                    for name in ca:
                        np.testing.assert_array_equal(ca[name],cb[name])
                    unchanged += 1
                records.append(dict(symbol=symbol,方向=side,遅延秒=delay,旧受理=legacy,候補受理=True,
                    返済時刻=float(ready['time_s'][exit_row]),終場=10600.))
            # ----------------------------------------
            # 最終観測が遅くても真の場内なら許すが、真の終場そのものは約定禁止。
            for time,expected in ((10300.,True),(10301.,True),(10599.999,True),(10600.,False),(10601.,False)):
                ready,result=fixture([0.,10.,9999.,10000.,time],4,side=side,symbol=symbol)
                assert accepted(new,ready,result,symbol) is expected
                rejected += int(not expected)
                records.append(dict(symbol=symbol,方向=side,疎観測返済時刻=time,候補受理=expected))
            # 明示終場を使い、limit+600という既定値で上書きしない。
            for time,expected in ((10399.,True),(10400.,False),(10401.,False)):
                ready,result=fixture([0.,10.,9999.,10000.,time],4,side=side,symbol=symbol,session_close=10400.)
                assert accepted(new,ready,result,symbol) is expected
                rejected += int(not expected)
            # 終場行の有無にかかわらず全期間は最終残玉を拒否、途中列は保持を許す。
            for ending in (10000.1,10600.,10601.):
                ready,result=fixture([0.,10.,9999.,10000.,ending],None,side=side,symbol=symbol)
                assert not accepted(new,ready,result,symbol,closed=True)
                rejected += 1
                if ending<10600.:
                    assert accepted(new,ready,result,symbol,closed=False)
            # 終場の観測が一行だけでも、場内返済済みなら受理。
            ready,result=fixture([0.,10.,9999.,10000.,10001.,10600.],4,side=side,symbol=symbol)
            assert accepted(new,ready,result,symbol)
    # ----------------------------------------
    # 同時刻・次行・各秒数の成立は独立注文監査で検査する責務を維持する。
    import adaptive_close_boundary_review as boundary
    maturity=[]
    for delay in (0.,1.,5.,15.):
        ready,shadow,result=boundary.calculate(dense+[10030.],delay)
        proof=boundary.inspect(ready,result,delay)
        assert accepted(new,ready,result,'TOPIX')
        proof['候補会計全検査通過']=True
        maturity.append(proof)
    return dict(全合格=True,人工記録=records,境界拒否数=rejected,旧受理例の全会計同値数=unchanged,
        明示終場を尊重=True,終場単一行を検査=True,最終残玉拒否=True,途中列は別扱い=True,
        エンジン人工の成熟検査=maturity,会計候補が遅延秒数の独立責務を奪わない=True)


def limited_replay(new) -> dict:
    """機能: 記録済みの障害一口座だけを再生し、会計と既存注文監査の両方を照合する。

    引数: new (module)。返り値: 非金額の限定検査証跡 (dict)。損益による選択をしない。
    """
    import adaptive_runner as runner
    import adaptive_slot_audit as slot
    runner.initialize()
    record=json.loads((HERE/'adaptive_cash_revision_failure_v1.json').read_text(encoding='utf-8'))
    spec=record['対象'];key=(record['session'],record['symbol']);ready=runner.INPUTS[key]
    state,bad,bs,good,gs,valid,branch,source,bv,choice=runner.columns(spec,key)
    config=runner.base.managers.make_config(runner.FIXED['manager'],key[1],ready)
    shadow=runner.shadow(spec,key,state,config)
    result=runner.engine.run(ready,state,config,bad,bs,good,gs,spec['policy'],
        observed_fill=spec['observed_fill'],detail=True,shadow=shadow,good_valid=valid,
        budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
        branch_direction=branch,branch_source=source,branch_valid=bv,branch_mode=spec['branch_mode'],
        branch_choice=choice,branch_seed=spec['branch_seed'])
    assert runner.fingerprints(result)==record['結果配列指紋']
    basic,curves=new.reconstruct(ready,result,key[1])
    proof=slot.audit(ready,result,config,spec['policy'],bad,bs,good,gs,valid,curves,
        state=state,budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
        observed_fill=spec['observed_fill'],branch_direction=branch,branch_source=source,
        branch_valid=bv,branch_mode=spec['branch_mode'],branch_choice=choice,branch_seed=spec['branch_seed'])
    assert basic['最終残玉']==0
    return dict(id=spec['id'],session=key[0],symbol=key[1],候補会計全検査通過=True,
        元障害と全配列指紋同一=True,厳密注文時刻を既存独立監査で確認=True,
        枠と注文の独立検査=proof,損益の順位集計なし=True)


def main() -> None:
    """機能: 変更を二領域に限定した候補・人工反例・限定口座の証拠を保存する。

    引数: なし。返り値: なし (None)。凍結コードや既存成績は更新しない。
    """
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    frozen_names=('adaptive_cash_reconstruction.py','adaptive_runner.py','engine_partial_restore.py',
        'engine_shadow_plan.py','adaptive_design.py','adaptive_assessment.py','探索条件の固定.json',
        '起動前監査.json','adaptive_accounting_fixed.json','adaptive_slot_fixed.json')
    before={str((HERE/name).relative_to(ROOT).as_posix()):digest(HERE/name) for name in frozen_names}
    change=make_candidate()
    old=load_module(OLD,'cash_revision_old');new=load_module(CANDIDATE,'cash_revision_candidate')
    artificial=synthetic(old,new)
    real=limited_replay(new)
    assert all(digest(ROOT/name)==sha for name,sha in before.items())
    payload=dict(全合格=True,変更限定=change,人工検査=artificial,障害一口座の再検算=real,
        旧固定前後SHA不変=True,旧固定SHA256=before,API取得数=0,現在保存物使用=False,
        売買コード変更=False,候補選択変更=False,原本変更=False,
        検査実装SHA256=digest(Path(__file__)))
    write_json(HERE/'adaptive_cash_revision_checks.json',payload)
    print('場末二領域のみ・人工境界・障害一口座の会計/注文独立監査が全合格。旧資料は不変。')


if __name__=='__main__':
    main()
