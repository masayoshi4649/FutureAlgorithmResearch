"""欠測・同時刻・価格飛びを含む人工経路で注文と会計を敵対検査する。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import numpy as np
import adaptive_runner as runner
import dynamic_atr_engine_audit as helpers


def generated(seed: int, symbol: str) -> tuple:
    """機能: 利益探索に使わない固定乱数の人工板経路を作る。

    引数: seed (int)、symbol (str)。返り値: 価格・入口・数量操作の入力 (tuple)。
    """
    random=np.random.default_rng(seed)
    n=128;prices=100.+np.cumsum(random.choice((-5.,-2.,-1.,0.,1.,2.,5.),n))
    prices=np.maximum(20.,prices)
    ready,state,_,_=helpers.fixture(prices.tolist())
    ready['time_s'][:-2]=np.cumsum(random.choice((0.,1.,5.,10.,30.),n))
    ready['time_s'][-1]=ready['limit']+30.
    ready['atr'][:-2]=random.choice((2.,4.,8.),n)
    holes=random.choice(np.arange(5,n-5),8,replace=False)
    keep=np.ones(len(state),bool);keep[holes]=False
    for name in ('time_s','last','atr','seq'):ready[name]=ready[name][keep]
    state=state[keep]
    ready.update(symbol=symbol,session='2026-09-21_Day')
    count=len(state);index=np.arange(count)
    state[:]=np.repeat(random.choice((-1,0,1),11),12)[:count]
    events=np.flatnonzero(index%3==0)
    source=(index//3*3).astype(np.int64)
    bad=random.choice((-1,0,1),len(events)).astype(np.int8)[index//3]
    good=random.choice((-1,0,1),len(events)).astype(np.int8)[index//3]
    branch=random.choice((-1,0,1),len(events)).astype(np.int8)[index//3]
    valid=random.choice((False,True),len(events))[index//3]
    bad[~valid]=0;good[~valid]=0;branch[~valid]=0
    choice=random.choice((0,1),len(events)).astype(np.int8)[index//3]
    return ready,state,helpers.config(symbol,ready),bad,source,good,source.copy(),valid,branch,source.copy(),valid.copy(),choice


def play(args: tuple, policy: dict, budget: bool, delay: float, observed: bool, reflected: bool) -> dict:
    """機能: 人工経路を再生し、注文から全会計を復元する。

    引数: args (tuple)、policy (dict)、budget/observed/reflected (bool)、delay (float)。返り値: 再生結果 (dict)。
    """
    ready,state,config,bad,bs,good,gs,valid,branch,source,bv,choice=deepcopy(args)
    if reflected:
        ready['last']=500.-ready['last'];state=-state;bad=-bad;good=-good;branch=-branch
    result=runner.engine.run(ready,state,config,bad,bs,good,gs,policy,observed_fill=observed,
        good_valid=valid,budget_enabled=budget,min_delay_seconds=delay,branch_direction=branch,
        branch_source=source,branch_valid=bv,branch_choice=choice,branch_mode=policy['branch_mode'],
        branch_seed=0 if policy['branch_mode']=='random' else None)
    basic,curves=runner.accounting.reconstruct(ready,result,ready['symbol'])
    assert np.isfinite(curves['equity']).all()
    assert (curves['long']>=0).all() and (curves['short']>=0).all()
    assert max(curves['long'])<=config['audit_cap'] and max(curves['short'])<=config['audit_cap']
    assert curves['long'][-1]==curves['short'][-1]==0
    for order in result['orders']:
        i,j=int(order[0]),int(order[1])
        assert i>j and np.isfinite(ready['last'][i])
        assert ready['time_s'][i]>=ready['time_s'][j]+delay-1e-8
        assert ready['time_s'][i]<ready['limit']+600.
    if not budget:assert len(result['budget_events'])==0
    return result


def main() -> None:
    """機能: 64経路×2市場×4方式の上下反射と会計を照合する。

    引数: なし。返り値: なし (None)。実相場損益や最良人工seedは採用しない。
    """
    policies={p['id']:p for p in runner.design.policies()}
    names=('A0',runner.design.PRIMARY_POLICY,runner.design.REVERSE_POLICY,runner.design.CLOCK_POLICY)
    records=[]
    for seed in range(64):
        for symbol in runner.SYMBOLS:
            args=generated(seed,symbol)
            for offset,name in enumerate(names):
                policy=policies[name];delay=(0.,1.,5.,15.)[(seed+offset)%4]
                budget=bool((seed//4+offset)%2);observed=bool((seed//8+offset)%2)
                context=dict(seed=seed,symbol=symbol,policy=name,delay=delay,budget=budget,observed=observed)
                try:
                    actual=play(args,policy,budget,delay,observed,False)
                    opposite=play(args,policy,budget,delay,observed,True)
                    expected=actual['orders'].copy()
                    expected[:,3]*=-1;expected[:,5]=500.-expected[:,5]
                    np.testing.assert_allclose(opposite['orders'],expected,atol=1e-7,rtol=0)
                    np.testing.assert_allclose(opposite['cycles'][:,3],actual['cycles'][:,3],atol=1e-7,rtol=0)
                except Exception as error:
                    runner.save(runner.HERE/'random_path_failure.json',dict(**context,error=repr(error),新実相場損益=False))
                    raise
                records.append(dict(**context,会計と反射一致=True))
    runner.save(runner.HERE/'random_path_audit.json',dict(全合格=True,人工比較数=len(records),人工再生数=2*len(records),
        新実相場損益=False,欠測表現='有効観測列から行を欠落させ時間間隔を広げる。NaN価格は会計入力契約外。',
        初版契約外記録=runner.digest(runner.HERE/'random_path_input_contract_v1.json'),検査=records,SHA256={p.name:runner.digest(p) for p in (
            Path(__file__),runner.HERE/'engine_partial_restore.py',runner.HERE/'engine_shadow_plan.py',
            runner.HERE/'adaptive_runner.py',runner.HERE/'adaptive_cash_reconstruction.py')}))
    print(f'欠測・価格飛び・同時刻の人工{2*len(records)}再生で会計と上下反射一致。',flush=True)


if __name__=='__main__':main()
