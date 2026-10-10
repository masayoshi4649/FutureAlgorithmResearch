"""共通の価格帯記録へ条件除去と相手確認を適用し、公開後だけ発火する。"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import numpy as np
import band_events


def band_settings(spec: dict) -> dict:
    """機能: 比較の採否を含まない、共通の帯生成条件だけを取り出す。

    引数: spec (dict)。返り値: 同時帯と試行の設定 (dict)。
    """
    return dict(seed_seconds=spec['anchor_seconds'], trial_seconds=spec['trial_seconds'],
        away_atr=spec['departure'],break_ticks=spec['break_ticks'],
        expiry_seconds=spec['lifetime'],momentum_atr=spec['momentum'])


def cache_key(spec: dict) -> str:
    """機能: 母集団を変える設定だけを指紋の前段として識別する。

    引数: spec (dict)。返り値: 正準文字列 (str)。採用条件を帯生成へ混ぜない。
    """
    return json.dumps(dict(board_anchor=spec['board_anchor'],**band_settings(spec)),sort_keys=True)


def eligible(band: dict, mode: str) -> bool:
    """機能: 先に列挙された初回突破を、現在までに確定した試行だけで採否する。

    引数: band (dict)、mode (str)。返り値: 採用するか (bool)。
    """
    allowed={'weaken','price_matched','price','all','quantity','last','mean','strengthen','first_break'}
    if mode not in allowed:raise ValueError('未知の入口判定: '+str(mode))
    if mode=='first_break':return band['status'] in ('breakout','early_breakout')
    if band['status']!='breakout':return False
    f=band['features']
    if not f['two_trials_complete'] or not f['price_comparable']:return False
    if mode=='all':return True
    price=f['price_weakens'] is True
    if mode=='price':return price
    if not f['quantity_comparable']:return False
    u1,u2=f['u1'],f['u2']
    if not np.isfinite([u1,u2]).all():raise ValueError('比較可能とされた板比率が有限ではありません')
    if mode=='price_matched':return price
    if mode=='quantity':return bool(u2<u1)
    if mode=='weaken':return bool(price and u2<u1)
    if mode=='last':return bool(price and u2<1.)
    if mode=='mean':return bool(price and (u1+u2)/2<1.)
    return bool(price and u2>u1)


def peer_prices(events: dict) -> dict:
    """機能: 数量に依存しない相手の過去5分方向を、各公開時点で作る。

    引数: events (dict[str,ndarray])。返り値: 公開時刻・有効性・ATR尺度の変化 (dict)。
    """
    valid,_,mid=band_events.quality(events,band_events.parameters())
    t=events['time_s'];n=len(t);score=np.full(n,np.nan);lefts=np.full(n,-1,np.int64)
    valid_since=0
    for i in range(n):
        if not valid[i]:valid_since=i+1;continue
        boundary=t[i]-300.;left=int(np.searchsorted(t,boundary,side='right'))-1
        if left<valid_since or left<0 or boundary-t[left]>60.:continue
        score[i]=(mid[i]-mid[left])/events['atr'][i];lefts[i]=left
    return dict(time_s=t.copy(),score=score,left=lefts,seq=events['seq'].copy())


def peer_at(peer: dict, now: float, direction: int) -> tuple[bool,dict]:
    """機能: 公開から60秒経過した最新相手情報を、無効も飛ばさず参照する。

    引数: peer (dict)、now (float)、direction (int)。返り値: 合否と公開根拠 (tuple[bool,dict])。
    """
    index=int(np.searchsorted(peer['time_s'],now-60.,side='right'))-1
    if index<0:return False,dict(reason='追加60秒後に利用可能な相手公開なし')
    age=float(now-peer['time_s'][index]-60.)
    value=peer['score'][index]
    okay=bool(0<=age<=120. and np.isfinite(value) and direction*value>=.25)
    return okay,dict(seq=int(peer['seq'][index]),public_time=float(peer['time_s'][index]),
        extra_delay=60.,age_after_delay=age,score=float(value) if np.isfinite(value) else None,
        accepted=okay)


def make(spec: dict, key: tuple[str,str], inputs: dict, bands: list[dict], peer: dict) -> tuple[np.ndarray,dict]:
    """機能: 共通帯から条件別の入口候補を作り、約定前の根拠を保存する。

    引数: spec/inputs/peer (dict)、key (tuple[str,str])、bands (list[dict])。
    返り値: 原本行の符号と採用段階別の記録 (tuple[ndarray,dict])。
    """
    ready=inputs[key];pulse=np.zeros(len(ready['seq']),np.int8);details=[];counts=Counter()
    for band in bands:
        counts['全帯']+=1;counts['終了:'+band['status']]+=1
        f=band['features']
        counts['二試行完了']+=int(f['two_trials_complete'])
        counts['板比較可能']+=int(f['quantity_comparable'])
        if not eligible(band,spec['mode']):continue
        terminal=band['terminal'];row=terminal['ready_index'];d=band['direction']
        assert row<len(pulse) and ready['seq'][row]==terminal['seq']
        assert ready['time_s'][row]==terminal['time_s']
        assert terminal['time_s']>band['created']['time_s']
        if spec['mode']!='first_break':
            assert all(t['complete'] for t in band['trials'])
            assert terminal['event_index']>band['trials'][1]['end']['event_index']
        counts['自己条件通過']+=1
        confirmation=None
        if spec['peer']:
            okay,confirmation=peer_at(peer,terminal['time_s'],d)
            if not okay:counts['相手確認不成立']+=1;continue
        if spec['invert']:d=-d
        if spec['seed'] is not None:
            salt=f"v40|{spec['seed']}|{key[0]}|{key[1]}|{terminal['seq']}".encode('utf-8')
            d*=1 if hashlib.sha256(salt).digest()[0]&1 else -1
        assert pulse[row]==0,'同じ原本行に複数帯を採用'
        pulse[row]=d;counts['全候補']+=1
        details.append(dict(band_id=band['band_id'],decision=terminal,direction=int(d),
            band_direction=band['direction'],price=band['price'],features=f,peer=confirmation))
    return pulse,dict(段階件数=dict(counts),候補=details,
        母集団キー=cache_key(spec),口座保有休止前の候補=True)
