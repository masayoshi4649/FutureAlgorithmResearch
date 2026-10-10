"""価格準備・公開順・反応分岐を、売買を再生せず人工と既知入力で検査する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import time

import numpy as np
import pandas as pd

import band_signals as signal


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def reject_network(*args, **kwargs) -> None:
    """機能: 人工・保存入力検査での外部通信を拒否する。

    引数: args/kwargs (object)。返り値: なし (None)、常に例外。
    """
    raise RuntimeError('保存入力だけを監査するため通信は禁止')


def digest(path: Path) -> str:
    """機能: ソースと入力の内容を固定する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(mid: np.ndarray | None = None, peer_mid: np.ndarray | None = None) -> tuple:
    """機能: 原本行と解放行を区別した価格停滞後の反転例を作る。

    引数: mid/peer_mid (ndarray|None、10秒間隔の中値)。
    返り値: inputs/features/events/spec (tuple)。specだけ人工用に開始待機を0へ置換する。
    """
    if mid is None:
        mid = np.array([100.] * 5 + [104.] * 8 + [100.] * 8)
    if peer_mid is None:
        peer_mid = np.full(len(mid), 100.)
    inputs, features, events = {}, {}, {}
    spec = deepcopy(signal.catalog()[34]); spec['params']['warmup_seconds'] = 0.
    for symbol, values in [('NK225', mid), ('TOPIX', peer_mid)]:
        values = np.asarray(values, dtype=float)
        n = len(values); ts = np.arange(n, dtype=float) * 10.
        rawtime = np.column_stack((ts - 1., ts)).ravel()
        rawseq = np.arange(n * 2, dtype=np.int64)
        key = ('人工_Day', symbol)
        inputs[key] = dict(seq=rawseq, time_s=rawtime, last=np.repeat(values, 2),
            atr=np.full(n * 2, 10.), start=0., limit=float(ts[-1] + 10.), tick=1.)
        features[key] = pd.DataFrame(dict(seq=rawseq[1::2], time_s=ts, source_time_s=ts-1.,
            source_first_seq=rawseq[::2], source_last_seq=rawseq[::2],
            source_mid_last=values, source_bid_last=values-.5, source_ask_last=values+.5,
            valid_event_count=np.ones(n, np.int64), continuity_reset_count=np.zeros(n, np.int64)))
        records = []
        for i in (10, 11):
            if i >= n:
                continue
            records.append(dict(current_seq=2*i, release_seq=2*i+1, release_time_s=ts[i],
                side=1, current_price=104.5, volume_to_side_qty=1.5, stable=True))
        events[key] = pd.DataFrame(records, columns=['current_seq','release_seq','release_time_s',
            'side','current_price','volume_to_side_qty','stable'])
    return inputs, features, events, spec


def render(inputs: dict, features: dict, events: dict, spec: dict, scale: float = 1.) -> dict:
    """機能: 再利用を解除して独立の一回の信号生成を行う。

    引数: inputs/features/events/spec (dict)、scale (float)。返り値: 生成結果 (dict)。
    """
    signal.clear_cache()
    output = signal.build(spec, inputs, features, events, scale)
    for row in output.values():
        json.dumps(dict(episodes=row['episodes'], activity=row['activity']), allow_nan=False)
    return output


def compare_arrays(a: dict, b: dict, prefix: dict | None = None, reflection: bool = False) -> int:
    """機能: 原本行の方向と証拠2列を完全一致で照合する。

    引数: a/b (dict)、prefix (dict|None、キー別比較長)、reflection (bool)。返り値: 列比較数 (int)。
    """
    count = 0
    for key in a:
        n = prefix[key] if prefix is not None else len(a[key]['direction'])
        for name in ('direction', 'source_episode', 'source_row'):
            expected = -a[key][name][:n] if reflection and name == 'direction' else a[key][name][:n]
            np.testing.assert_array_equal(expected, b[key][name][:n], err_msg=f'{key} {name}')
            count += 1
    return count


def reflected(inputs: dict, features: dict, events: dict) -> tuple:
    """機能: 上下を反射し、価格帯と代理の側も対称に入れ替える。

    引数: inputs/features/events (dict)。返り値: 独立コピー3組 (tuple)。
    """
    rr, ff, ee = {}, {}, {}
    for key, ready in inputs.items():
        frame, ev = features[key], events[key]
        center = float(np.nanmax(frame.source_ask_last.to_numpy()) * 2. + 100.)
        rr[key] = dict(ready, last=center-ready['last'])
        new = frame.copy(deep=True)
        new['source_mid_last'] = center-frame.source_mid_last
        new['source_bid_last'] = center-frame.source_ask_last
        new['source_ask_last'] = center-frame.source_bid_last
        ff[key] = new
        newev = ev.copy(deep=True)
        newev['side'] = -ev.side
        newev['current_price'] = center-ev.current_price
        ee[key] = newev
    return rr, ff, ee


def sliced(inputs: dict, cuts: dict) -> dict:
    """機能: readyの原本行列だけをキー別の排他的上限まで切断する。

    引数: inputs/cuts (dict)。返り値: ready辞書 (dict)。
    """
    return {key: {name: value[:cuts[key]].copy() if isinstance(value, np.ndarray) and value.ndim and len(value) == len(ready['seq']) else value
        for name, value in ready.items()} for key, ready in inputs.items()}


def self_test() -> dict:
    """機能: 準備母集団・先着消費・時刻境界・情報追加の因果性を人工で検算する。

    引数: なし。返り値: 検査名と結果 (dict)。注文や損益は計算しない。
    """
    inputs, frames, events, spec = fixture()
    key = ('人工_Day', 'NK225')
    spec['params']['peer_mode'] = 'none'
    base = render(inputs, frames, events, spec)
    ep = base[key]['episodes'][0]
    assert ep['setup_time_s'] == 120 and ep['confirmation_time_s'] == 130
    assert ep['response_direction'] == -1 and ep['accepted'] and ep['stable_volume_score'] == 3.
    assert ep['setup_seq'] == 25 and ep['confirmation_seq'] == 27
    assert base[key]['direction'][26] == 0 and base[key]['direction'][27] == -1
    checks = {'別解放の初回反転と原本seq対応': True, 'JSON非有限値なし': True}
    # ----------------------------------------
    # 出来高は価格区間の準備や消費を変えず、後発量で過去の採否を修正しない。
    common = [{k:v for k,v in ep.items() if not k.startswith('peer_') and k not in
        ('accepted','proxy_pass','branch_pass','rejection_reasons','signal_expiry_time_s')} for ep in base[key]['episodes']]
    for proxy, threshold in [('price', 0), ('all_volume', 2), ('stable_volume', 5)]:
        other = deepcopy(spec); other['params'].update(proxy=proxy, volume_threshold=threshold)
        value = render(inputs, frames, events, other)
        current = [{k:v for k,v in ep.items() if not k.startswith('peer_') and k not in
            ('accepted','proxy_pass','branch_pass','rejection_reasons','signal_expiry_time_s')} for ep in value[key]['episodes']]
        assert common == current
        assert value[key]['episodes'][0]['accepted'] == (threshold <= 3)
    future_events = deepcopy(events)
    future_events[key] = pd.concat([events[key], pd.DataFrame([dict(current_seq=26, release_seq=27,
        release_time_s=130., side=1,current_price=104.5,volume_to_side_qty=999.,stable=True)])], ignore_index=True)
    compare_arrays(base, render(inputs, frames, future_events, spec))
    checks['共通準備と出来高凍結'] = True
    flipped = deepcopy(spec); flipped['params']['branch'] = 'breakout'
    value = render(inputs, frames, events, flipped)
    assert value[key]['episodes'][0]['resolution'] == 'confirmed'
    assert 'opposite_branch_first' in value[key]['episodes'][0]['rejection_reasons']
    assert not value[key]['direction'].any()
    checks['望まない側が先なら消費して待ち直さない'] = True
    ttl = deepcopy(spec); ttl['params'].update(setup_lifetime_min=10., setup_lifetime_windows=0.)
    value = render(inputs, frames, events, ttl)
    assert value[key]['episodes'][0]['resolution'] == 'expired' and not value[key]['direction'].any()
    checks['準備期限の等号では失効優先'] = True
    reset = deepcopy(frames); reset[key].loc[9, 'continuity_reset_count'] = 3
    value = render(inputs, reset, events, spec)
    compare_arrays(base, value)
    assert value[key]['episodes'][0]['continuity_reset_count'] == 3
    checks['途中リセットを診断に残し有効endpointを除外しない'] = True
    invalid = deepcopy(frames); invalid[key].loc[13, 'source_time_s'] = 0
    value = render(inputs, invalid, events, spec)
    assert value[key]['episodes'][0]['resolution'] == 'data_unavailable'
    checks['公開遅れによる準備失効'] = True
    model = signal.price_model(inputs[key], frames[key], spec['params'])
    assert not model['predicate'][13] and base[key]['episodes'][0]['resolution'] == 'confirmed'
    checks['停滞崩れを価格反応とし失効させない'] = True
    index = signal.volume_index(events[key])
    assert signal.volume_score(index, 1,104.5,220.,1000,120.)['all_volume_score'] == 3.
    assert signal.volume_score(index, 1,104.5,220.001,1000,120.)['all_volume_score'] == 1.5
    assert signal.volume_score(index, 1,104.5,110.,21,120.)['all_volume_score'] == 1.5
    checks['出来高左端包含と同時刻seq上限'] = True
    precise = pd.DataFrame([dict(current_seq=i*2,release_seq=i*2+1,release_time_s=float(i*10),
        side=1,current_price=104.5,volume_to_side_qty=.1 if i == 0 else 1/3,stable=i>0)
        for i in range(7)])
    exact = signal.volume_score(signal.volume_index(precise),1,104.5,60.,13,50.)
    assert exact['all_volume_score'] == exact['stable_volume_score'] == 2.
    precise = precise.iloc[:2].copy()
    precise['volume_to_side_qty'] = [.3,2.]
    exact = signal.volume_score(signal.volume_index(precise),1,104.5,10.,3,1.)
    assert exact['all_volume_score'] == exact['stable_volume_score'] == 2.
    checks['窓外累積の桁落ちを避けK等号と部分集合を保持'] = True
    # ----------------------------------------
    # 相手の遅延可用性、有効中立と欠測、TTL置換を直接小さな状態で検査する。
    peer = dict(time=np.array([0.]), seq=np.array([4]), valid=np.array([True]),
        peer_direction=np.array([0],np.int8), source_last=np.array([3]), anchor=np.array([0]), short_anchor=np.array([0]))
    assert not signal.peer_information(peer,59.999,spec['params'])['peer_available']
    assert signal.peer_information(peer,60.,spec['params'])['peer_available']
    assert signal.peer_information(peer,120.,spec['params'])['peer_available']
    assert not signal.peer_information(peer,120.001,spec['params'])['peer_available']
    checks['相手60秒解放と鮮度等号'] = True
    ep2 = deepcopy(ep); ep2.update(episode_id=1, confirmation_seq=35,confirmation_time_s=170., stable_volume_score=0.)
    params = deepcopy(spec['params']); params['signal_lifetime_seconds'] = 40.
    value = signal.adopt(inputs[key],[ep,ep2],None,params)
    assert value['direction'][34] == -1 and value['direction'][35] == 0
    ep2.update(confirmation_seq=33,confirmation_time_s=160.,stable_volume_score=3.)
    value = signal.adopt(inputs[key],[ep,ep2],None,params)
    assert value['source_episode'][33] == 1 and value['direction'][37] == -1 and value['direction'][41] == 0
    checks['不採用は延命せず新採用だけ期限置換'] = True
    cuts = {k:27 for k in inputs}
    compare_arrays(base, render(sliced(inputs,cuts),frames,events,spec),cuts)
    reflect = render(*reflected(inputs,frames,events),spec)
    compare_arrays(base, reflect, reflection=True)
    checks['人工接頭部と売買反射'] = True
    return dict(全合格=True, 検査数=len(checks), 検査=checks, 売買再生=False, API取得数=0)


def real_checks() -> dict:
    """機能: 全26既知入力の枝同一性と代表条件の未来不変・反射を調べる。

    引数: なし。返り値: 監査記録 (dict)。新損益、現在保存物、原本書換えを行わない。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((ROOT / 'work/wave_v23/features_depth.pkl').read_bytes())
    events = pickle.loads((HERE / 'events.pkl').read_bytes())
    specs = signal.catalog()
    records = []
    direction_sha = hashlib.sha256()
    mother_hash = {}
    comparisons = 0
    started = time.perf_counter()
    signal.clear_cache()
    for scale in (.8, 1., 1.2):
        for spec in specs:
            output = signal.build(spec,inputs,features,events,scale)
            for key, row in output.items():
                json.dumps(dict(episodes=row['episodes'],activity=row['activity']),allow_nan=False)
                neutral = row['direction'] == 0
                assert (row['source_episode'][neutral] == -1).all() and (row['source_row'][neutral] == -1).all()
                assert (row['source_row'][~neutral] <= inputs[key]['seq'][~neutral]).all()
                for ep in row['episodes']:
                    assert 0. <= ep['stable_volume_score'] <= ep['all_volume_score']
                    if ep['resolution'] == 'confirmed':
                        assert ep['confirmation_seq'] > ep['setup_seq']
                        assert ep['confirmation_time_s'] < ep['expiry_time_s']
                    if ep['accepted'] and spec['params']['peer_mode'] != 'none':
                        assert ep['peer_available'] and ep['peer_available_time_s'] <= ep['confirmation_time_s']
                basic = [{k:v for k,v in ep.items() if not k.startswith('peer_') and k not in
                    ('accepted','proxy_pass','branch_pass','rejection_reasons','signal_expiry_time_s')} for ep in row['episodes']]
                h = hashlib.sha256(json.dumps(basic,sort_keys=True).encode()).hexdigest()
                common_key = (key,spec['params']['window_seconds'],scale)
                if common_key in mother_hash:
                    assert mother_hash[common_key] == h
                mother_hash[common_key] = h
                direction_sha.update(row['direction'].tobytes())
                comparisons += 1
            records.append(dict(id=spec['id'],clock_scale=scale,
                準備数=sum(len(r['episodes']) for r in output.values()),
                採用数=sum(r['activity'].get('accepted',0) for r in output.values())))
    # ----------------------------------------
    # 代理5種・反応3枝・相手3扱い・両Wを含む18代表を、全26の2境界で検査する。
    selected = [specs[i] for i in (0,4,8,10,14,17,19,23,26,28,31,34,37,40,44,45,79,89)]
    prefix_count = future_count = mirror_count = 0
    mirror_inputs = reflected(inputs,features,events)
    for j,spec in enumerate(selected):
        scale = (.8,1.,1.2)[j % 3]
        full = render(inputs,features,events,spec,scale)
        mirror = render(*mirror_inputs,spec,scale)
        mirror_count += compare_arrays(full,mirror,reflection=True)
        for fraction in (.3,.7):
            shared_times = {}
            for session in {key[0] for key in inputs}:
                members = [ready for key, ready in inputs.items() if key[0] == session]
                beginning = max(float(ready['time_s'][0]) for ready in members)
                ending = min(float(ready['time_s'][-1]) for ready in members)
                shared_times[session] = beginning + (ending - beginning) * fraction
            cuts = {key:int(np.searchsorted(ready['time_s'],shared_times[key[0]],side='left'))
                    for key,ready in inputs.items()}
            prefix = render(sliced(inputs,cuts),features,events,spec,scale)
            prefix_count += compare_arrays(full,prefix,cuts)
            rr,ff,ee = {},{},{}
            for key,ready in inputs.items():
                cut=cuts[key]; rawseq=int(ready['seq'][cut])
                rr[key]=dict(ready,atr=ready['atr'].copy(),last=ready['last'].copy())
                rr[key]['atr'][cut:]=777.;rr[key]['last'][cut:]=999999.
                ff[key]=features[key].copy(deep=True);mask=ff[key].seq>=rawseq
                ff[key].loc[mask,'source_mid_last']=999999.
                ff[key].loc[mask,'source_bid_last']=999998.
                ff[key].loc[mask,'source_ask_last']=1000000.
                ee[key]=events[key].copy(deep=True);mask=ee[key].release_seq>=rawseq
                ee[key].loc[mask,'volume_to_side_qty']=9999.
                ee[key].loc[mask,'current_price']=999999.
                ee[key].loc[mask,'stable']=True
            changed=render(rr,ff,ee,spec,scale)
            future_count+=compare_arrays(full,changed,cuts)
        print(f'因果検査 {j+1}/{len(selected)} {spec["id"]}',flush=True)
    return dict(全監査合格=True, 全入力数=len(inputs),全条件時計入力数=comparisons,
        共通価格母集団数=len(mother_hash),全条件方向SHA256=direction_sha.hexdigest(),
        接頭部列比較数=prefix_count,未来改変列比較数=future_count,売買反射列比較数=mirror_count,
        条件別活動量=records,経過秒=time.perf_counter()-started,
        新損益読取=False,売買再生=False,API取得数=0,現在保存物使用=False)


def main() -> None:
    """機能: 人工検査と必要時の全保存入力検査を記録する。

    引数: --synthetic-only (bool)。返り値: なし (None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--synthetic-only',action='store_true')
    args=parser.parse_args()
    socket.socket.connect=reject_network;socket.create_connection=reject_network
    paths=[HERE/'band_signals.py',HERE/'band_design.py',HERE/'band_signal_audit.py',
        ROOT/'work/wave_v23/inputs.pkl',ROOT/'work/wave_v23/features_depth.pkl',HERE/'events.pkl']
    before={p.relative_to(ROOT).as_posix():digest(p) for p in paths if p.exists()}
    synthetic=self_test()
    print({'人工検査合格':True,'検査数':synthetic['検査数']},flush=True)
    result=dict(人工検査=synthetic,参照SHA256=before)
    if not args.synthetic_only:
        result.update(real_checks())
    assert before=={p.relative_to(ROOT).as_posix():digest(p) for p in paths if p.exists()}
    result['入力ソース前後不変']=True
    target=HERE/('band_signal_selftest.json' if args.synthetic_only else 'band_signal_audit.json')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    main()
