"""追加9方向を独立指標から再計算し、旧13方向と同期を含めて照合する。"""

import hashlib
import json
import pickle

import numpy as np

from signals_real import HERE,WORK,independent,turning,event_average,reference,load_inputs


def build(ready: dict, book: dict) -> tuple:
    """機能: 追加価格幅・イベント数を独立実装へ通し、22方向を作る。

    引数: ready/book(dict)。返り値: 状態・有効性(tuple)。
    """
    base=independent(ready,book);n=len(ready['time_s'])
    states=[row.copy() for row in base['states']]
    valid=[row.copy() for row in base['valid']]
    usable=base['direction_price_valid'];mid=(book['bid']+book['ask'])/2
    for width in [16,32,64]:
        dirs,_,_=turning(mid,usable,width*ready['tick'])
        states.append(dirs);valid.append(usable.copy())
    raw=base['raw_ofi'];nonzero=np.flatnonzero(np.isfinite(raw)&(raw!=0));count=base['flow_count']
    for span in [512,2048]:
        ratios=event_average(raw[nonzero].astype(float),2/(span+1))
        flow=np.r_[np.nan,ratios][count].astype(np.float32)
        enough=usable&base['flow_comparable']&(count>=span)&np.isfinite(flow)
        for threshold in [.15,.30]:
            states.append(np.where(enough&(flow>=np.float32(threshold)),1,
                          np.where(enough&(flow<=-np.float32(threshold)),-1,0)).astype(np.int8))
            valid.append(enough.copy())
    for price,flow in [(13,16),(14,19)]:
        both=valid[price]&valid[flow]
        states.append(np.where(both&(states[price]==states[flow]),states[price],0).astype(np.int8))
        valid.append(both)
    assert len(states)==len(valid)==22
    return np.asarray(states),np.asarray(valid)


def main() -> None:
    """機能: 全60口座の拡張方向を原本対応価格数量から再照合する。

    引数: なし。返り値: なし(None)。損益は読み込まず監査JSONだけ保存する。
    """
    ready,books=load_inputs()
    path=WORK/'extended/signals.pkl'
    with path.open('rb') as stream:saved=pickle.load(stream)
    checks=rows=0
    for session in sorted({k[0] for k in ready}):
        model={s:build(ready[(session,s)],books[(session,s)]) for s in ['TOPIX','NK225']}
        for symbol,other in [('TOPIX','NK225'),('NK225','TOPIX')]:
            key=(session,symbol);packet=saved[key];t=ready[key]['time_s'];n=len(t)
            source,age=reference(t,ready[(session,other)]['time_s'])
            safe=np.maximum(source,0);fresh=(source>=0)&(age>0)&(age<=10)
            own,vo=model[symbol];peer,vp=model[other]
            pv=vp[:,safe]&fresh;ps=np.where(pv,peer[:,safe],0).astype(np.int8)
            both=vo&pv;common=np.where(both&(own==ps),own,0).astype(np.int8)
            expected=dict(states_self=own,states_peer=ps,states=common,valid_self=vo,valid_peer=pv,valid=both,
                          source_peer=source,age_peer=age)
            for name,value in expected.items():
                np.testing.assert_array_equal(value,packet[name],err_msg=f'{key} {name}')
                checks+=1
            rows+=n
        print(f'独立拡張方向 {session} 完了',flush=True)
    output=dict(合格=True,口座数=len(saved),方向数=22,追加方向数=9,原板行数=rows,照合配列数=checks,
        新損益参照=False,元13の独立計算を維持=True,自己と相手の厳密過去投影=True,
        素材SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
        コードSHA256=hashlib.sha256((WORK/'extensions.py').read_bytes()).hexdigest())
    (HERE/'拡張22方向の独立監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(output,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
