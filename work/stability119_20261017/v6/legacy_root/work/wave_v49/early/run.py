"""元の初回と通常影時計を固定して、候補1の早期保護だけを比較する。"""

from __future__ import annotations

from copy import deepcopy
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'gates'))
import gate_replay as source

integration=source.integration
shadow_api=integration.engine.shadow_engine
old_engine=shadow_api.original
BASE_ID='F50_NONE__E11'


def save(path: Path,value: object) -> None:
    """機能: 今作業内へ有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
    path.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)


def catalog() -> list[dict]:
    """機能: 損益を見る前に基準と早期保護十条件を列挙する。

    引数: なし。返り値: 条件一覧(list[dict])。
    """
    return [dict(id='E00',name='元の候補1',changes={}),
        dict(id='E01',name='初期損切0.75ATR',changes=dict(stop_atr=.75)),
        dict(id='E02',name='初期損切0.5ATR',changes=dict(stop_atr=.5)),
        dict(id='E03',name='1ATR順行から幅1ATR',changes=dict(activation_atr=1.,main_trail=1.)),
        dict(id='E04',name='0.75ATR順行から幅0.75ATR',changes=dict(activation_atr=.75,main_trail=.75)),
        dict(id='E05',name='0.5ATR順行から幅0.5ATR',changes=dict(activation_atr=.5,main_trail=.5)),
        dict(id='E06',name='0.5ATR順行から幅0.75ATR',changes=dict(activation_atr=.5,main_trail=.75)),
        dict(id='E07',name='初期0.75ATR・0.75ATR順行から幅0.75ATR',changes=dict(stop_atr=.75,activation_atr=.75,main_trail=.75)),
        dict(id='E08',name='初期0.5ATR・0.5ATR順行から幅0.5ATR',changes=dict(stop_atr=.5,activation_atr=.5,main_trail=.5)),
        dict(id='E09',name='0.75ATR順行後に組全体の建値を守る',changes=dict(breakeven_atr=.75,breakeven_floor=0.)),
        dict(id='E10',name='15分で0.5ATR未達なら損失枠0.5ATRへ',changes=dict(failure_min=15.,failure_mfe=.5,failure_stop=.5))]


def freeze() -> dict:
    """機能: 条件・固定する入口時計・比較範囲を経済再生前に固定する。

    引数: なし。返り値: 仕様(dict)。
    """
    fixed=dict(基準=BASE_ID,条件=catalog(),入口='元H019の準備・初回時刻・価格・方向・ATR・数量を全件固定',
        影時計='元の通常影stop1ATR/activation1.5ATR/main_trail3ATR/tightenなしを毎回過去から再生成し、その新規準備行だけ許可',
        途中='F50_NONEの悪化時半減・復元なし。1.5ATR減量許可も元通常影から計算する。早期全返済後に再参加しない。',
        出口='変更は指定config値だけ。3ATR順行後0.75ATR上限・2ATR部分利確・360分・場内返済は維持。',
        注文='観測行後に設けたストップは次行から有効。すでに通過した条件は次行価格で返済し、過去の有利な水準へ遡及しない。',
        枚数={'TOPIX':dict(初回=5,上限=10,円倍率=1000),'NK225':dict(初回=10,上限=20,円倍率=10)},
        リスク単位='実口座の既存R集計は初回枚数×初回ATRを維持。初期stopを狭めてもR分母を縮めない。金額と1枚平均勝敗比で比較。',
        評価='全16の再探索。旧15と問題Nightを別掲。新20モード版と混ぜず、既存候補1の出口変更として扱う。',
        費用=0,指定価格約定=True,API取得数=0)
    target=HERE/'条件の事前固定.json'
    if target.exists():assert source.read(target)==fixed
    else:save(target,fixed)
    return fixed


def configs(spec: dict,ready: dict,variant: dict) -> tuple[dict,dict]:
    """機能: 基準と出口変更後の設定を分ける。

    引数: spec/ready/variant(dict)。返り値: 基準と変更設定(tuple[dict,dict])。
    """
    base=integration.config_for(spec,ready)
    modified=dict(base,**variant['changes'])
    assert base['stop_atr']==1 and base['activation_atr']==1.5 and base['main_trail']==3
    assert all(modified[k]==base[k] for k in base if k not in variant['changes'])
    return base,modified


def make_shadow(ready: dict,state: np.ndarray,base: dict,config: dict) -> dict:
    """機能: 元の通常影時計へ、出口だけを早めた既存再生器を同期する。

    引数: ready/base/config(dict)、state(ndarray)。返り値: 出口影と通常影(dict)。
    """
    scheduler=old_engine.run(ready,state,dict(base,tighten_atr=0.,tight_width=1.),detail=True)
    allow=np.zeros(len(state),bool)
    allow[scheduler['prepare_events'][:,1].astype(int)]=True
    par=np.asarray([config[name] for name in old_engine.PARAMS],float)
    values=old_engine.simulate(ready['time_s'],ready['last'],ready['atr'],ready['atr'],state,state,
        ready['tick'],ready['start'],ready['limit'],ready['us_open'],par,True,int(config['audit_cap']),0,False,
        allow,0.,float(ready.get('session_close',ready['limit']+600)))
    shadow=dict(zip(shadow_api.FIELDS,values))
    shadow.update(scheduler=scheduler,schedule_prepare_allow=allow,
        input_sha256=integration.engine.input_digest(ready,state,config,False,0.),observed_fill=False,min_delay_seconds=0.)
    for field in ('prepare_events','entry_preparations'):
        np.testing.assert_array_equal(shadow[field],scheduler[field])
    opens=lambda result: result['orders'][(result['orders'][:,7]==1)&(result['orders'][:,6]==20)]
    np.testing.assert_array_equal(opens(shadow),opens(scheduler))
    lookup={int(c[0]):c for c in shadow['cycles']}
    for cycle in scheduler['cycles']:
        current=lookup[int(cycle[0])]
        np.testing.assert_array_equal(current[[0,1,5,8]],cycle[[0,1,5,8]])
        assert current[2]<=cycle[2]
    return shadow


def play(spec: dict,ready: dict,columns: tuple,valid: np.ndarray,base: dict,config: dict) -> tuple:
    """機能: 元の減量許可と早期出口影を既存数量器へ接続する。

    引数: spec/ready/base/config(dict)、columns(tuple)、valid(ndarray)。返り値: 実結果・実効列・許可証跡(tuple)。
    """
    shadow=make_shadow(ready,columns[0],base,config)
    bad,origin,evidence=integration.reference.gate.gate_bad(ready,shadow['scheduler'],columns[1],columns[2],
        spec['gate_threshold_atr'],mode=spec['gate_mode'],valid=valid)
    effective=(columns[0],bad,origin,*columns[3:])
    result=integration.reference.reference.play(integration.engine,spec,ready,effective,config,shadow)
    return result,effective,evidence


def inspect(spec: dict,ready: dict,actual: tuple,config: dict) -> tuple:
    """機能: 注文会計・初回固定・枠数・次行条件と場内返済を確認する。

    引数: spec/ready/config(dict)、actual(tuple)。返り値: 統計・時価・証跡(tuple)。
    """
    result,effective,_=actual
    basic,curves=source.followup.audit.cash.reconstruct(ready,result,ready['symbol'])
    # 集計器のstop_atrは実際の注文幅ではなく、元R=数量×1ATRの検査前提。
    # 約定に使用した幅はconfigと台帳へ別保存し、R集計だけ1ATRで比較する。
    risk_config=dict(config,stop_atr=1.)
    row=source.followup.audit.statistics.session(spec['id'],ready,result,risk_config,basic,curves,effective,spec)
    row['actual_stop_atr']=config['stop_atr']
    row['risk_denominator_atr']=1.
    orders=result['orders'];cycles=result['cycles'];shadow=result['shadow'];scheduler=shadow['scheduler']
    initial=orders[(orders[:,7]==1)&(orders[:,6]==20)]
    original=scheduler['orders'][(scheduler['orders'][:,7]==1)&(scheduler['orders'][:,6]==20)]
    np.testing.assert_array_equal(initial,original)
    np.testing.assert_array_equal(result['prepare_events'],scheduler['prepare_events'])
    for order in orders:
        fill,origin=int(order[0]),int(order[1])
        assert 0<=origin<fill<len(ready['last'])
    expected=int(config['initial_qty'])
    assert np.max(curves['long'],initial=0)<=expected if 'long' in curves else True
    assert row['max_long']<=expected and row['max_short']<=expected
    assert all(int(c[2])<len(ready['last']) and ready['time_s'][int(c[2])]<ready.get('session_close',ready['limit']+600) for c in cycles)
    lookup={int(c[0]):c for c in shadow['cycles']}
    for cycle in cycles:
        earlier=lookup[int(cycle[0])]
        assert cycle[1]==earlier[1] and cycle[2]<=earlier[2] and cycle[8]==earlier[8]
        assert abs(cycle[4]-expected*cycle[5])<1e-8
    # ----------------------------------------
    # 元枠の減量と終了だけを許し、復元・増玉・セッション越えを拒む。
    assert not np.any(orders[:,6]==31)
    assert np.all(initial[:,4]==expected)
    for cid in set(orders[:,2].astype(int)):
        group=orders[orders[:,2]==cid]
        assert group[group[:,7]==1,4].sum()==expected
        assert group[group[:,7]==0,4].sum()==expected
    proof=dict(独立会計=True,全初回一致=True,元影時計一致=True,原本次行順=True,枚数上限=True,場内完済=True,
               復元増玉なし=True,実R分母不変=True)
    return row,curves['equity'],proof


def causal(spec: dict,ready: dict,columns: tuple,valid: np.ndarray,base: dict,config: dict,actual: tuple) -> dict:
    """機能: 早期出口接続を切断・未来変更・反射の各条件で作り直す。

    引数: spec/ready/base/config(dict)、columns/actual(tuple)、valid(ndarray)。返り値: 証跡(dict)。
    """
    old=integration.reference.causal;n=len(ready['last']);cut=max(2,int(n*.37))
    partial=play(spec,old.clipped(ready,cut),tuple(v[:cut].copy() for v in columns),valid[:cut].copy(),base,config)
    integration.prefix_check(actual,partial,cut)
    del partial
    change=int(n*.73);future=old.clipped(ready,n)
    future['last'][change:]+=ready['tick']*(37+np.arange(n-change));future['atr'][change:]*=3
    edited=[v.copy() for v in columns]
    for index in (0,1,3,6):edited[index][change:]=np.where(edited[index][change:]==1,-1,1)
    for index in (2,4,7):edited[index][change:]=np.arange(change,n)
    changed=play(spec,future,tuple(edited),valid.copy(),base,config)
    integration.prefix_check(actual,changed,change)
    del changed
    center=float(2*np.ceil(np.max(ready['last'])/ready['tick'])*ready['tick'])
    reflected=dict(ready,last=center-ready['last'])
    values=tuple(-v if i in (0,1,3,6) else v.copy() for i,v in enumerate(columns))
    mirror=play(spec,reflected,values,valid.copy(),base,config)
    old.reflected_result(actual[0],mirror[0],center,True)
    old.reflected_result(actual[0]['shadow'],mirror[0]['shadow'],center,False)
    old.reflected_result(actual[0]['shadow']['scheduler'],mirror[0]['shadow']['scheduler'],center,False)
    return dict(切断=True,未来変更=True,上下反射=True,通常影から再生成=True)


def evaluate(variant: dict) -> None:
    """機能: 一つの早期保護条件を全32口座で再生する。

    引数: variant(dict)。返り値: なし(None)。
    """
    started=time.perf_counter()
    spec=deepcopy(next(s for s in source.followup.catalog('new') if s['id']==BASE_ID))
    spec['id']=BASE_ID+'__'+variant['id']
    original=source.prior_ledgers(BASE_ID)
    rows,ledgers,proofs,series=[],[],[],{}
    for key,ready in sorted(source.INPUTS.items()):
        columns,valid=source.replay.new_columns(spec,key)
        base,config=configs(spec,ready,variant)
        actual=play(spec,ready,columns,valid,base,config)
        row,curve,proof=inspect(spec,ready,actual,config)
        result=actual[0]
        ledger=dict(session=key[0],symbol=key[1],config=config,
            **{field:result[field].tolist() for field in integration.STORED},
            result_fingerprints=integration.reference.old.fingerprints(result),
            shadow_fingerprints=integration.reference.old.fingerprints(result['shadow'],integration.reference.reference.EXPECTED_SHADOW_FIELDS),
            scheduler_fingerprints=integration.reference.old.fingerprints(result['shadow']['scheduler'],integration.reference.reference.EXPECTED_SHADOW_FIELDS),
            scheduler_cycles=result['shadow']['scheduler']['cycles'].tolist(),
            scheduler_orders=result['shadow']['scheduler']['orders'].tolist())
        assert ledger['scheduler_fingerprints']==original[key]['scheduler_fingerprints']
        if variant['id']=='E00':
            for field in ('result_fingerprints','shadow_fingerprints','scheduler_fingerprints'):
                assert ledger[field]==original[key][field],(key,field)
            proof['基準全指紋一致']=True
        if key[0]==source.NEW:proof['因果']=causal(spec,ready,columns,valid,base,config,actual)
        proof.update(session=key[0],symbol=key[1],元通常影全指紋一致=True)
        row['initial_entries']=len(result['entry_preparations'])
        row['active_session']=bool(row['initial_entries'])
        rows.append(row);ledgers.append(ledger);proofs.append(proof);series[key]=curve
    names=sorted({r['session'] for r in rows})
    periods={}
    for label,chosen in (('旧15',[s for s in names if s!=source.NEW]),('問題Night',[source.NEW]),('全16',names)):
        periods[label]={symbol:source.period(rows,series,chosen,symbol) for symbol in ('TOPIX','NK225')}
    summary=dict(id=spec['id'],variant=variant,全合格=True,periods=periods,経過秒=time.perf_counter()-started)
    for folder,value,suffix in (('sessions',rows,'.json.gz'),('ledgers',ledgers,'.json.gz'),('audits',proofs,'.json.gz'),('summaries',summary,'.json')):
        save(HERE/folder/(variant['id']+suffix),value)
    print(variant['id']+' 完了 '+str(round(time.perf_counter()-started,1))+'秒',flush=True)


def main() -> None:
    """機能: 固定条件を指定範囲だけ全口座へ再生する。

    引数: --ids(str)、--freeze(bool)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--ids',default='all');parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args();freeze()
    if args.freeze:return
    source.initialize()
    for variant in catalog():
        if args.ids=='all' or variant['id'] in args.ids.split(','):evaluate(variant)


if __name__=='__main__':main()
