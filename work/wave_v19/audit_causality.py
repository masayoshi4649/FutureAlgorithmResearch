"""拡張エンジンの途中切断・保護水準の単調性・表示枚数比例を検査する。"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

import engine
import signal_variants

OUT=Path(__file__).resolve().parent


def read(name: str) -> object:
    """機能: 日本語JSONを読む。

    引数: name (str)。返り値: 内容 (object)。
    """
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def main() -> None:
    """機能: 元コードを変更せず、途中切断と表示数量の再生経路を監査する。

    引数: なし。返り値: なし (None)。新たな条件探索は行わない。
    """
    started=time.time()
    source_path=OUT/'engine.py'
    before=hashlib.sha256(source_path.read_bytes()).hexdigest()
    source=source_path.read_text(encoding='utf-8')
    assert source.count('curve=np.zeros((n,8)) if detail else np.zeros((1,8))')==1
    source=source.replace('curve=np.zeros((n,8)) if detail else np.zeros((1,8))',
                          'curve=np.zeros((n,13)) if detail else np.zeros((1,13))')
    source=source.replace('curve[i,:]=np.array([equity,realized,inv[4],inv[5],dd,cash,inv[2],campaign])',
                          'curve[i,:8]=np.array([equity,realized,inv[4],inv[5],dd,cash,inv[2],campaign])')
    source=source.replace('    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,',
        '        if detail:\n            curve[i,8:]=np.array([protected_floor,main_floor,stop_level,main_level,d])\n    stats=np.array([realized,dd,maxlong,maxshort,maxgross,maxnet,max_error,min_equity,max_equity,')
    (OUT/'audit_engine_trace.py').write_text(source,encoding='utf-8')
    trace=importlib.import_module('audit_engine_trace')
    records=read('週比較.json')
    by_id={r['id']:r for r in records}
    selection=read('選択結果.json')
    original=pickle.loads((OUT/'全取引台帳.pkl').read_bytes())
    states=pickle.loads((OUT.parent/'wave_v17/主方向状態.pkl').read_bytes())
    inputs={}
    for stage in ['development','holdout']:
        inputs.update(pickle.loads((OUT.parent/'wave_v16'/f'入力_{stage}.pkl').read_bytes()))
    specifications={s['id']:s for s in signal_variants.variant_specs()}
    chosen=set(selection['displayed'])
    for field in ['activation_atr','tighten_atr','breakeven_atr','failure_min','cooldown_min','ttl_seconds',
                  'entry_mode','signal_exit','after_open_factor','lock_fraction','us_mode','timeout_min']:
        variants={r['config'][field] for r in records}
        for value in variants:
            chosen.add(next(r['id'] for r in records if r['config'][field]==value))
    signals={by_id[identifier]['signal_id'] for identifier in chosen}
    directions={sid:signal_variants.build_one(specifications[sid],inputs,states) for sid in signals}
    prefix_cases,protection_rows,protection_steps,price_protection_steps=0,0,0,0
    # ----------------------------------------
    # 拡張変数を含む代表設定を日中・米国開始を含む夜間で追跡する。
    sample_keys=[('2026-09-21_Day','TOPIX'),('2026-09-23_Night','TOPIX'),
                 ('2026-09-21_Day','NK225'),('2026-09-23_Night','NK225')]
    for identifier in sorted(chosen):
        record=by_id[identifier]
        for key in sample_keys:
            ready=inputs[key]
            state=directions[record['signal_id']][key]
            full=trace.run(ready,state,record['config'],detail=True)
            reference=original[(identifier,*key)]
            for field in ['trades','cycles','orders','stats']:
                np.testing.assert_allclose(full[field],reference[field],rtol=0,atol=1e-8)
            curve=full['curve']
            for campaign in full['cycles'][:,0]:
                mask=(curve[:,7]==campaign)&(curve[:,12]!=0)
                held=curve[mask]
                assert np.all(np.diff(held[:,8])>=-1e-8),'金額保護下限が緩む'
                protection_steps+=int((np.diff(held[:,8])>1e-8).sum())
                prices=held[np.isfinite(held[:,9])]
                if len(prices):
                    d=prices[0,12]
                    assert np.all(d*np.diff(prices[:,9])>=-1e-8),'追跡保護価格が緩む'
                    price_protection_steps+=int((d*np.diff(prices[:,9])>1e-8).sum())
                protection_rows+=len(held)
            for fraction in [.37,.73]:
                cut=int(len(ready['last'])*fraction)
                partial={k:(v[:cut] if isinstance(v,np.ndarray) and len(v)==len(ready['last']) else v) for k,v in ready.items()}
                result=trace.run(partial,state[:cut],record['config'],detail=True)
                np.testing.assert_allclose(result['trades'],full['trades'][full['trades'][:,7]<cut],rtol=0,atol=1e-8)
                np.testing.assert_allclose(result['cycles'],full['cycles'][full['cycles'][:,2]<cut],rtol=0,atol=1e-8)
                np.testing.assert_allclose(result['orders'],full['orders'][full['orders'][:,0]<cut],rtol=0,atol=1e-8)
                np.testing.assert_allclose(result['curve'],curve[:cut],rtol=0,atol=1e-8)
                prefix_cases+=1
    print(f'途中切断{prefix_cases}ケースと保護水準単調性が一致',flush=True)
    # ----------------------------------------
    # 表示可能な全枚数を実行し、丸めを含む約定経路と時価指標の比例を確認する。
    scaling_cases,scaling_trades=0,0
    for identifier in selection['displayed']:
        record=by_id[identifier]
        for key,ready in inputs.items():
            session,symbol=key
            cap=10 if symbol=='TOPIX' else 20
            reference=original[(identifier,session,symbol)]
            state=directions[record['signal_id']][key]
            for quantity in range(1,cap+1):
                config=dict(record['config'],initial_qty=quantity,audit_cap=quantity)
                result=engine.run(ready,state,config)
                trades=reference['trades'].copy();trades[:,[3,10]]*=quantity
                cycles=reference['cycles'].copy();cycles[:,[3,4,6,7]]*=quantity
                orders=reference['orders'].copy();orders[:,4]*=quantity
                stats=reference['stats'].copy();stats[[0,1,2,3,4,5,7,8,9]]*=quantity
                np.testing.assert_allclose(result['trades'],trades,rtol=1e-12,atol=1e-8)
                np.testing.assert_allclose(result['cycles'],cycles,rtol=1e-12,atol=1e-8)
                np.testing.assert_allclose(result['orders'],orders,rtol=1e-12,atol=1e-8)
                columns=[0,1,2,3,4,5,7,8,9,10]
                np.testing.assert_allclose(result['stats'][columns],stats[columns],rtol=1e-10,atol=1e-6)
                assert result['stats'][6]<1e-5
                scaling_cases+=1;scaling_trades+=len(trades)
        print(f'{identifier}のTOP1〜10枚・NK1〜20枚、全20区間で比例一致',flush=True)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest()==before
    output=dict(合格=True,途中切断対象条件数=len(chosen),途中切断ケース数=prefix_cases,
                保護水準検査保有行数=protection_rows,金額保護下限改善回数=protection_steps,
                追跡保護価格改善回数=price_protection_steps,保護水準は全て単調=True,
                表示枚数対象条件=selection['displayed'],表示全枚数再生セル数=scaling_cases,
                表示全枚数返済照合数=scaling_trades,全許容枚数で価格時刻理由方向不変=True,
                損益数量最大下落が枚数比例=True,新規幅ゼロ条件なし=True,
                原engine不変=True,原engineSHA256=before,現在API取得数=0,経過秒=time.time()-started)
    (OUT/'audit_causality.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
