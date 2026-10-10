"""板圧力の予想差・対照・相手確認を公開イベントから機械判定する。"""

from __future__ import annotations

import hashlib
import numpy as np


def price_events(ready: dict, events: dict) -> tuple[np.ndarray,np.ndarray]:
    """機能: 原本の分境界先頭行だけから価格差と共通の連続性を作る。

    引数: ready/events (dict)。返り値: ATR規格化変化・品質 (tuple[ndarray, ndarray])。
    同秒の末尾行を検索して後続観測へ進むことはない。
    """
    rows = np.asarray(events['indices'],np.int64)
    change = np.full(len(rows),np.nan)
    if len(rows) > 1:
        change[1:] = np.diff(ready['last'][rows])/ready['atr'][rows[1:]]
    valid = np.isfinite(change) & np.isfinite(ready['atr'][rows]) & (ready['atr'][rows] > 0)
    valid &= np.r_[False,(np.diff(events['minute'])==1)&(np.diff(events['time_s'])<=90)] if len(rows) else np.empty(0,bool)
    valid &= events['time_s'] >= ready['start']+1200
    return change, valid


def candidate_events(score: np.ndarray, valid: np.ndarray, change: np.ndarray,
                     threshold: float, rearm: float, confirmation: float) -> tuple[np.ndarray,dict]:
    """機能: 閾値到達を1回だけ消費し、価格確認後の新規候補を作る。

    引数: score/valid/change (ndarray)、threshold/rearm/confirmation (float)。
    返り値: イベント方向列と発火内訳 (tuple[ndarray,dict])。欠測は観測0と区別する。
    """
    assert len(score)==len(valid)==len(change) and threshold>0 and 0<rearm<1
    result = np.zeros(len(score),np.int8)
    armed = True; previous = 0; crossings = rejected = missing = 0
    for i in range(len(score)):
        if not valid[i] or not np.isfinite(score[i]):
            armed = True;previous = 0;missing += 1
            continue
        value = score[i]
        if abs(value) < threshold*rearm:
            armed = True
        if abs(value) >= threshold:
            d = 1 if value>0 else -1
            if armed or d!=previous:
                crossings += 1
                if confirmation==0. or d*change[i]>=confirmation:
                    result[i] = d
                else:
                    rejected += 1
                armed = False;previous = d
    return result,dict(閾値到達数=crossings,価格不一致数=rejected,無効区間数=missing,
        価格確認後候補数=int(np.count_nonzero(result)))


def make(spec: dict, key: tuple, inputs: dict, events: dict, forecasts: dict) -> tuple[np.ndarray,dict]:
    """機能: 自市場の候補を固定してから相手確認・方向対照を適用する。

    引数: spec (dict)、key ((session,symbol))、inputs/events/forecasts (dict)。
    返り値: 原本行対応の入口パルスと候補根拠 (tuple[ndarray,dict])。
    この関数は売買履歴・未来ラベルを読まず、相手の未公開行も参照しない。
    """
    ready,own = inputs[key],events[key]
    model = forecasts[spec['lag']][key]
    assert np.array_equal(own['seq'],ready['seq'][own['indices']])
    assert np.array_equal(own['time_s'],ready['time_s'][own['indices']])
    assert np.array_equal(model['seq'],own['seq']) and np.array_equal(model['time_s'],own['time_s'])
    change,price_valid = price_events(ready,own)
    sessions = sorted({k[0] for k in inputs},key=lambda s:min(v['start'] for k,v in inputs.items() if k[0]==s))
    evaluation = key[0] in sessions[2:]
    valid = price_valid & evaluation & (own['time_s'] < ready['limit']-300)
    if spec['mode'] != 'price_independent':
        valid &= model['forecast_valid']
    if spec['mode'] == 'residual': score = model['residual']/model['residual_rms']
    elif spec['mode'] == 'raw': score = model['observed']/model['raw_ofi_rms']
    elif spec['mode'] == 'predicted': score = model['prediction']/model['raw_ofi_rms']
    elif spec['mode'] in ('price','price_independent'): score = change/.05
    else: raise ValueError('未定義の入口モードです')
    confirmation = 0. if spec['mode'] in ('price','price_independent') else spec['price_confirm']
    selected,audit = candidate_events(score,valid,change,spec['threshold'],spec['rearm'],confirmation)
    own_candidates = selected.copy()
    peer_sources = np.full(len(selected),-1,np.int64)
    peer_reasons = np.zeros(len(selected),np.int8)
    if spec['peer'] != 'none':
        peer_key = (key[0],'TOPIX' if key[1]=='NK225' else 'NK225')
        peer = events[peer_key];other = forecasts[spec['lag']][peer_key]
        lookup = np.searchsorted(peer['time_s']+60,own['time_s'],side='right')-1
        peer_change,peer_valid = price_events(inputs[peer_key],peer)
        peer_score = other['residual']/other['residual_rms'] if spec['peer']=='residual' else peer_change/.05
        peer_valid &= other['forecast_valid'] if spec['peer']=='residual' else evaluation
        for i in np.flatnonzero(selected):
            j = int(lookup[i]);reason = 0
            if j < 0: reason = 1
            else:
                peer_sources[i] = int(peer['seq'][j])
                assert peer['time_s'][j]+60 <= own['time_s'][i]
                if own['time_s'][i]-(peer['time_s'][j]+60)>120: reason = 2
                elif not peer_valid[j] or not np.isfinite(peer_score[j]): reason = 1
                elif selected[i]*peer_score[j] < 0: reason = 3
                elif selected[i]*peer_score[j] < 1: reason = 4
            peer_reasons[i] = reason
            if reason: selected[i] = 0
    if spec['invert']: selected *= -1
    if spec['seed'] is not None:
        for i in np.flatnonzero(selected):
            payload=f"v39|{spec['seed']}|{key[0]}|{key[1]}|{int(own['seq'][i])}".encode('utf-8')
            sign=1 if hashlib.sha256(payload).digest()[0]&1 else -1
            selected[i] *= sign
    dense = np.zeros(len(ready['seq']),np.int8)
    dense[own['indices']] = selected
    audit.update(初期学習専用=not evaluation,共通有効区間数=int(valid.sum()),
        相手不明数=int(np.sum(peer_reasons==1)),相手古さ数=int(np.sum(peer_reasons==2)),
        相手逆方向数=int(np.sum(peer_reasons==3)),相手不足数=int(np.sum(peer_reasons==4)),
        最終候補数=int(np.count_nonzero(selected)),候補行=own['indices'][selected!=0].tolist(),
        自己候補行=own['indices'][own_candidates!=0].tolist(),
        方向=selected[selected!=0].tolist(),相手公開行=peer_sources[selected!=0].tolist())
    return dense,audit
