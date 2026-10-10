"""全条件の入力接続と人工価格の会計・保存を検査する。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
from unittest.mock import patch
import numpy as np
import adaptive_runner as runner
import dynamic_atr_engine_audit as helpers


def fixture(symbol: str) -> tuple:
    """機能: 復元期限をまたぐ人工価格と四種類の分岐根拠を作る。

    引数: symbol (str)。返り値: 入力・方向・設定・根拠列 (tuple)。
    """
    prices=[100,101,103,102,101,104,102,100,102,104,103,101,99,101,103,105,104,102,100,99,101,103,100,98]
    ready,state,_,_=helpers.fixture(prices)
    ready['time_s'][:-2]*=30.
    ready['time_s'][-1]=ready['limit']+30.
    ready.update(symbol=symbol,session='2026-09-21_Day')
    config=helpers.config(symbol,ready)
    n=len(state);source=np.arange(n,dtype=np.int64)
    bad=np.zeros(n,np.int8);bad[[2,8,14,20]]=-1
    good=np.zeros(n,np.int8);good[[6,12,18,22]]=1
    branch=np.resize(np.array([-1,0,1,0],np.int8),n)
    valid=np.ones(n,bool);branch_valid=(source%4)!=3
    return ready,state,config,bad,source,good,source.copy(),valid,branch,source.copy(),branch_valid


def wiring() -> int:
    """機能: 全974条件で窓・役割乱数・分岐を入力APIへ渡すことを確認する。

    引数: なし。返り値: 照合条件数 (int)。実データの列や損益を読み出さない。
    """
    specs=runner.design.catalog()+runner.design.supplementary()
    key=('2026-09-21_Day','TOPIX')
    ready,state,_,bad,source,good,_,valid,branch,_,branch_valid=fixture('TOPIX')
    runner.INPUTS={key:ready};n=len(state);events=np.arange(n,dtype=np.int32)
    for spec in specs:
        calls=[]
        def entry(signal,scale,pair):
            """機能: 入口引数を記録する。

            引数: signal (str)、scale (float)、pair (tuple)。返り値: 人工方向 (ndarray)。
            """
            calls.append(('entry',signal,scale,pair));return state
        def directions(identifier,pair,scale,seed,role):
            """機能: 役割別引数を記録する。

            引数: identifier/role (str)、pair (tuple)、scale (float)、seed (int|None)。返り値: 人工列 (tuple)。
            """
            calls.append(('direction',identifier,pair,scale,seed,role));return (bad if role=='bad' else good),source,events
        def quality(identifier,pair,scale):
            """機能: 品質引数を記録する。

            引数: identifier (str)、pair (tuple)、scale (float)。返り値: 人工品質 (ndarray)。
            """
            calls.append(('valid',identifier,pair,scale));return valid
        def condition(identifier,pair,scale):
            """機能: 分岐引数を記録する。

            引数: identifier (str)、pair (tuple)、scale (float)。返り値: 人工分岐列 (tuple)。
            """
            calls.append(('branch',identifier,pair,scale));return branch,source,events
        def choose(pair,seed,scale):
            """機能: 乱数分岐引数を記録する。

            引数: pair (tuple)、seed (int)、scale (float)。返り値: 人工選択列 (ndarray)。
            """
            calls.append(('choice',pair,seed,scale));return np.full(n,seed%2,np.int8)
        with patch.multiple(runner.inputs,entry=entry,directions=directions,publication_valid=quality,
                condition=condition,branch_choice=choose):
            result=runner.columns(spec,key)
        expected=[('entry',spec['signal_id'],spec['entry_scale'],key)]
        p=spec['policy']
        if p['kind']=='dynamic':
            expected += [('direction',p['bad_id'],key,spec['bad_scale'],spec['bad_seed'],'bad'),
                ('direction',p['good_id'],key,spec['good_scale'],spec['good_seed'],'good'),
                ('valid',p['good_id'],key,spec['good_scale']),('branch','B01',key,spec['branch_scale']),
                ('valid','B01',key,spec['branch_scale'])]
            if spec['branch_seed'] is not None: expected.append(('choice',key,spec['branch_seed'],spec['branch_scale']))
        assert calls==expected,spec['id']
        assert len(result)==10 and all(v.shape==(n,) for v in result)
    return len(specs)


def main() -> None:
    """機能: 全主条件の金額・数量・分岐・全組R超過を人工価格で検算する。

    引数: なし。返り値: なし (None)。実相場の新方式損益は計算しない。
    """
    wired=wiring();checks=[]
    assert (runner.HERE/'adaptive_cash_reconstruction.py').read_bytes()==(runner.HERE/'adaptive_cash_reconstruction_v2_candidate.py').read_bytes()
    for spec in runner.design.catalog():
        rows=[];series={}
        for symbol in runner.SYMBOLS:
            for inactive in (False,True):
                ready,state,config,bad,bs,good,gs,valid,branch,source,bv=fixture(symbol)
                if inactive:state[:]=0
                result=runner.engine.run(ready,state,config,bad,bs,good,gs,spec['policy'],
                    observed_fill=spec['observed_fill'],good_valid=valid,
                    budget_enabled=spec['budget_enabled'],min_delay_seconds=spec['min_delay_seconds'],
                    branch_direction=branch,branch_source=source,branch_valid=bv,
                    branch_mode=spec['branch_mode'],branch_seed=spec['branch_seed'])
                basic,curves=runner.accounting.reconstruct(ready,result,symbol)
                row=runner.session_row(spec['id'],ready,result,config,bad,basic,curves)
                trades=result['trades'];factor=config['point_value']
                gains=trades[:,2]*trades[:,3]*(trades[:,5]-trades[:,4])*factor
                assert abs(sum(gains)-row['net_yen'])<1e-6
                assert row['closed_units']==row['profit_units']+row['loss_units']+row['zero_units']
                assert row['reductions']==int(np.sum(result['orders'][:,6]==30))
                assert row['restorations']==int(np.sum(result['orders'][:,6]==31))
                assert row['signal_choices']+row['timer_choices']==len(result['branch_events'])
                if spec['branch_mode']!='fixed':assert len(result['branch_events'])==row['reductions']
                if not spec['budget_enabled']:assert row['budget_requests']==row['budget_completions']==0
                excess=[max(0.,-float(c[3])-float(c[4]))*factor for c in result['cycles']]
                assert abs(sum(excess)-row['cycle_risk_excess_yen'])<1e-6
                payload=dict(row=row,ledger={name:result[name].tolist() for name in runner.STORED},fingerprints=runner.fingerprints(result))
                assert json.loads(json.dumps(payload,ensure_ascii=False,allow_nan=False))==payload
                if inactive:assert row['closed_units']==row['net_yen']==row['cycles']==0
                else:rows.append(row);series[symbol]=curves['equity']*factor
                checks.append(dict(id=spec['id'],symbol=symbol,inactive=inactive,合格=True))
        summary=runner.period(rows,['2026-09-21_Day'])
        for symbol in runner.SYMBOLS:
            path=np.r_[0.,series[symbol]]
            assert abs(summary[symbol]['drawdown_yen']-np.max(np.maximum.accumulate(path)-path))<1e-6
    runner.save(runner.HERE/'adaptive_runner_synthetic.json',dict(全合格=True,全条件接続数=wired,人工会計数=len(checks),
        新実データ損益=False,検査=checks,SHA256={p.name:runner.digest(p) for p in (
            Path(__file__),runner.HERE/'adaptive_runner.py',runner.HERE/'adaptive_cash_reconstruction.py',
            runner.HERE/'adaptive_design.py',runner.HERE/'engine_partial_restore.py',runner.HERE/'engine_shadow_plan.py')}))
    print(f'全{wired}条件接続・人工{len(checks)}会計を照合。新実相場損益なし。',flush=True)


if __name__=='__main__':main()
