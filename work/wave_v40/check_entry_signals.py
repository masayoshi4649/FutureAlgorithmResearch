"""入口条件と相手情報の公開待ちを、人工・全候補・過去部分で独立検査する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import urllib.request

import numpy as np

import band_events
import design
import entry_signals as entry


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHECKS: list[str] = []


def denied(*args: object, **kwargs: object) -> None:
    """機能: 検査処理からの外部通信を拒否する。

    引数: 任意 (object)。返り値: なし (None)、常に例外を送出する。
    """
    raise AssertionError('入口監査は保存入力と人工値だけを使います')


def sha(path: Path) -> str:
    """機能: 保存資料の内容指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1048576):
            value.update(block)
    return value.hexdigest()


def write(name: str, value: dict) -> None:
    """機能: 有限な日本語JSONを一時ファイルから置換して保存する。

    引数: name (str)、value (dict)。返り値: なし (None)。
    """
    path = HERE/name
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def check(name: str, condition: bool) -> None:
    """機能: 独立期待の不一致で停止し、通過項目を記録する。

    引数: name (str)、condition (bool)。返り値: なし (None)。
    """
    assert condition, name
    CHECKS.append(name)


def rejects(function: object) -> bool:
    """機能: 不正な根拠が黙って候補にならないことを調べる。

    引数: function (callable)。返り値: 明示例外で拒否したか (bool)。
    """
    try:
        function()
    except (AssertionError, ValueError, TypeError, IndexError):
        return True
    return False


def select_rows(events: dict, selector: object) -> dict:
    """機能: 公開列を同じ行集合で切り出す。

    引数: events (dict[str,ndarray])、selector (slice|ndarray)。返り値: 独立コピー (dict)。
    """
    return {name: values[selector].copy() for name, values in events.items()}


def reflect(events: dict) -> dict:
    """機能: 正価格を保ちながら気配の側と数量を交換して反射する。

    引数: events (dict)。返り値: 上下対称の公開列 (dict)。
    """
    changed = select_rows(events, slice(None))
    anchor = 4.*float(np.nanmax(events['ask_prices']))
    changed['bid_prices'] = anchor-events['ask_prices']
    changed['ask_prices'] = anchor-events['bid_prices']
    changed['bid_qty'] = events['ask_qty'].copy()
    changed['ask_qty'] = events['bid_qty'].copy()
    return changed


def future_change(events: dict, count: int) -> dict:
    """機能: 指定行以後の気配・数量・ATR・価格品質を大きく変更する。

    引数: events (dict)、count (int)。返り値: 過去を変えない公開列 (dict)。
    """
    changed = select_rows(events, slice(None))
    n = len(events['seq'])-count
    offset = 10000.+np.arange(n, dtype=float)*3.
    for field in ('bid_prices', 'ask_prices'):
        changed[field][count:] += offset[:, None]
    for field in ('bid_qty', 'ask_qty'):
        changed[field][count:] = 999.
    changed['atr'][count:] = 777.
    changed['price_valid'][count:] = False
    changed['depth_valid'][count:] = False
    return changed


def quantity_change(events: dict) -> dict:
    """機能: 最良価格と時計を残し、数量と数量品質だけを全面無効化する。

    引数: events (dict)。返り値: 数量不明の公開列 (dict)。
    """
    changed = select_rows(events, slice(None))
    changed['bid_qty'][:] = np.nan
    changed['ask_qty'][:] = np.nan
    changed['depth_valid'][:] = False
    changed['continuity_reset_count'][:] = 9.
    return changed


def peer_oracle(events: dict) -> dict:
    """機能: asofと連続品質を単純走査して5分方向の独立期待を作る。

    引数: events (dict)。返り値: peer_pricesと比較する時刻・値・左行・seq (dict)。
    bandのqualityやsearchsortedを呼ばず、数量列を参照しない。
    """
    times = events['time_s']
    n = len(times)
    valid = []
    mids = []
    for i in range(n):
        bid, ask = events['bid_prices'][i, 0], events['ask_prices'][i, 0]
        atr, delay, gap = events['atr'][i], events['block_delay_seconds'][i], events['previous_release_gap'][i]
        valid.append(bool(events['price_valid'][i] and np.isfinite([bid, ask, atr, delay, gap]).all()
            and bid > 0 and ask > bid and atr > 0 and 0 < delay <= 60. and 0 < gap <= 60.))
        mids.append((bid+ask)/2.)
    scores = np.full(n, np.nan)
    lefts = np.full(n, -1, np.int64)
    for i in range(n):
        older = [j for j in range(i+1) if times[j] <= times[i]-300.]
        if not older:
            continue
        left = older[-1]
        if times[i]-300.-times[left] > 60. or not all(valid[left:i+1]):
            continue
        scores[i] = (mids[i]-mids[left])/events['atr'][i]
        lefts[i] = left
    return dict(time_s=times.copy(), score=scores, left=lefts, seq=events['seq'].copy())


def equal_peer(actual: dict, expected: dict) -> None:
    """機能: 相手の全列を比較し、反射による小数差だけ許す。

    引数: actual/expected (dict)。返り値: なし (None)。
    """
    assert set(actual) == set(expected)
    for name in actual:
        np.testing.assert_allclose(actual[name], expected[name], rtol=0, atol=1e-10, equal_nan=True)


def public_fixture() -> dict:
    """機能: 7分の人工公開列を作り、数量と価格の品質を独立に変更可能にする。

    引数: なし。返り値: 公開10段列 (dict)。
    """
    times = np.arange(70, dtype=float)*10.
    mids = 100.+times*.01
    n = len(times)
    return dict(seq=np.arange(n, dtype=np.int64)*5, ready_index=np.arange(n, dtype=np.int64)*3,
        time_s=times, atr=np.full(n, 10.), bid_prices=mids[:, None]-.5-np.arange(10)[None, :],
        ask_prices=mids[:, None]+.5+np.arange(10)[None, :], bid_qty=np.full((n,10), 10.),
        ask_qty=np.full((n,10), 10.), price_valid=np.ones(n, bool), depth_valid=np.ones(n, bool),
        block_delay_seconds=np.full(n, 10.), previous_release_gap=np.r_[np.nan, np.diff(times)],
        continuity_reset_count=np.zeros(n))


def band_fixture(u1: float | None = 1., u2: float | None = .5, price: bool = True) -> dict:
    """機能: 試行2の終了より後に初回突破した人工帯を作る。

    引数: u1/u2 (float|None)、price (bool)。返り値: 条件判定用の帯 (dict)。
    """
    return dict(band_id=1, direction=1, price=102., status='breakout',
        created=dict(event_index=1, ready_index=1, seq=11, time_s=10.),
        terminal=dict(event_index=12, ready_index=12, seq=22, time_s=120.),
        trials=[dict(complete=True, end=dict(event_index=5)), dict(complete=True, end=dict(event_index=11))],
        features=dict(two_trials_complete=True, price_comparable=True, quantity_comparable=u1 is not None and u2 is not None,
            u1=u1, u2=u2, b1=1., b2=.5 if price else 1., price_weakens=price))


def synthetic() -> dict:
    """機能: 条件除去、同値と不明、公開境界、相手遅延と乱数を人工検査する。

    引数: なし。返り値: 通過件数・全項目 (dict)。売買注文器は呼ばない。
    """
    modes = ('weaken','price_matched','price','all','quantity','last','mean','strengthen','first_break')
    for u1, u2 in ((1., .5), (.5, 1.), (1., 1.), (0., 0.), (1., 0.), (2., .5), (None, .5), (.5, None)):
        for price in (True, False):
            record = band_fixture(u1, u2, price)
            known = u1 is not None and u2 is not None
            expected = dict(weaken=known and price and u2<u1, price_matched=known and price,
                price=price, all=True, quantity=known and u2<u1, last=known and price and u2<1.,
                mean=known and price and (u1+u2)/2.<1., strengthen=known and price and u2>u1, first_break=True)
            for mode in modes:
                check(f'採否/{u1}/{u2}/{price}/{mode}', entry.eligible(record, mode) == expected[mode])
    for status in ('early_breakout','expiry','session_end','price_quality_interruption','open_at_data_end'):
        record = band_fixture()
        record['status'] = status
        for mode in modes:
            check(f'終了種類/{status}/{mode}', entry.eligible(record, mode) == (mode=='first_break' and status=='early_breakout'))
    for field in ('two_trials_complete','price_comparable'):
        record = band_fixture()
        record['features'][field] = False
        for mode in modes[:-1]:
            check(f'未完成又は価格不明/{field}/{mode}', not entry.eligible(record, mode))
    record = band_fixture()
    check('未定義モードを拒否', rejects(lambda: entry.eligible(record, '不存在')))
    for value in (float('nan'), float('inf'), -float('inf')):
        record = band_fixture(value, .5)
        for mode in ('weaken','price_matched','quantity','last','mean','strengthen'):
            check('比較可能な比率の非有限拒否/'+str(value)+'/'+mode, rejects(lambda: entry.eligible(record, mode)))
    # ----------------------------------------
    # 相手の最新公開は無効でも飛ばさず、60秒待ちと120秒期限は別に検査する。
    peer = dict(time_s=np.asarray([100., 200., 220.]), seq=np.asarray([10, 20, 22]), score=np.asarray([.25, np.nan, -.25]))
    for now, direction, answer, seq in ((159.999,1,False,None),(160.,1,True,10),
        (259.999,1,True,10),(260.,1,False,20),(279.999,-1,False,20),(280.,-1,True,22),
        (400.,-1,True,22),(400.001,-1,False,22),(280.,1,False,22)):
        accepted, proof = entry.peer_at(peer, now, direction)
        check(f'相手境界/{now}/{direction}', accepted == answer and proof.get('seq') == seq)
    for score, answer in ((.249999,False),(.25,True),(.250001,True),(np.nan,False)):
        p = dict(time_s=np.asarray([100.]), seq=np.asarray([10]), score=np.asarray([score]))
        check('相手閾値/'+str(score), entry.peer_at(p, 160., 1)[0] == answer)
    events = public_fixture()
    expected = peer_oracle(events)
    equal_peer(entry.peer_prices(events), expected)
    check('5分asof独立式', True)
    check('開始品質不明を飛ばして窓を短縮しない', np.isnan(expected['score'][30]) and expected['left'][31] == 1)
    for name in ('price_valid','atr','block_delay_seconds','previous_release_gap'):
        changed = select_rows(events, slice(None))
        changed[name][20] = False if name=='price_valid' else (0. if name=='atr' else 61.)
        equal_peer(entry.peer_prices(changed), peer_oracle(changed))
        check('5分窓内不正を無視しない/'+name, np.isnan(entry.peer_prices(changed)['score'][50]))
    changed = select_rows(events, slice(None))
    changed['time_s'] = events['time_s']+np.cumsum(np.arange(len(events['seq']))%3)
    changed['previous_release_gap'] = np.r_[np.nan, np.diff(changed['time_s'])]
    equal_peer(entry.peer_prices(changed), peer_oracle(changed))
    check('5分境界の直前asof', True)
    equal_peer(entry.peer_prices(quantity_change(events)), expected)
    check('相手価格は数量と数量品質から独立', True)
    mirrored = entry.peer_prices(reflect(events))
    mirror_expected = {key:value.copy() for key,value in expected.items()}
    mirror_expected['score'] *= -1
    equal_peer(mirrored, mirror_expected)
    check('相手価格の上下反射', True)
    for count in (31, 52):
        equal_peer(entry.peer_prices(select_rows(events, slice(0,count))), {key:value[:count] for key,value in expected.items()})
        altered = entry.peer_prices(future_change(events, count))
        equal_peer({key:value[:count] for key,value in altered.items()}, {key:value[:count] for key,value in expected.items()})
        check('相手価格prefix/future/'+str(count), True)
    # ----------------------------------------
    # 候補は判断行にだけ置く。売買の約定はここでは実行しない。
    key = ('人工_Day','TOPIX')
    ready = dict(seq=np.arange(30,dtype=np.int64)+10, time_s=np.arange(30,dtype=float)*10.)
    inputs = {key:ready}
    spec = design.catalog()[0]
    record = band_fixture()
    pulse, proof = entry.make(spec,key,inputs,[record],peer)
    check('判断行12だけに候補', np.flatnonzero(pulse).tolist()==[12] and pulse[12]==1)
    for row in (10, 11):
        changed = deepcopy(record)
        changed['terminal'].update(event_index=row, ready_index=row, seq=int(ready['seq'][row]),time_s=float(ready['time_s'][row]))
        check('試行2確定同時以前を拒否/'+str(row), rejects(lambda: entry.make(spec,key,inputs,[changed],peer)))
    changed = deepcopy(record)
    changed['status'] = 'early_breakout'
    changed['features']['two_trials_complete'] = False
    first = dict(spec, mode='first_break')
    check('先着対照だけ早い突破を保持', int(entry.make(first,key,inputs,[changed],peer)[0].sum())==1
          and int(entry.make(spec,key,inputs,[changed],peer)[0].sum())==0)
    check('同原本行の帯重複を拒否', rejects(lambda: entry.make(spec,key,inputs,[record,deepcopy(record)],peer)))
    changed = deepcopy(record)
    changed['terminal']['seq'] += 1
    check('原本seqの違う根拠を拒否', rejects(lambda: entry.make(spec,key,inputs,[changed],peer)))
    for seed in range(64):
        random_spec = dict(spec, seed=seed)
        salt = '|'.join(('v40',str(seed),key[0],key[1],str(record['terminal']['seq']))).encode('utf-8')
        expected_direction = -1 if int.from_bytes(hashlib.sha256(salt).digest()[:1], 'little') % 2 == 0 else 1
        first_pulse, first_proof = entry.make(random_spec,key,inputs,[record],peer)
        second_pulse, second_proof = entry.make(random_spec,key,inputs,[record],peer)
        reflected_record = deepcopy(record)
        reflected_record['direction'] *= -1
        reflected_pulse, _ = entry.make(random_spec,key,inputs,[reflected_record],peer)
        check(f'乱数{seed}/同候補・決定性・反射', np.array_equal(first_pulse,second_pulse)
            and first_proof==second_proof and first_pulse[12]==expected_direction
            and np.array_equal(first_pulse,-reflected_pulse))
    keys = {entry.cache_key(item) for item in design.catalog()+design.supplementary()}
    check('採否と乱数を母集団生成に混ぜない10集合', len(keys)==10)
    return dict(全合格=True, 人工検査数=len(CHECKS), 検査=CHECKS.copy(), 新売買実行=False,
                API取得数=0, 現在保存物使用=False)


def real_cases() -> tuple[dict, dict, dict]:
    """機能: 全281の発火数と21代表の全26入力に対する因果性を成績なしで調べる。

    引数: なし。返り値: 頻度、全入口監査、参照指紋 (tuple[dict,dict,dict])。
    全13基準と主8近傍の2接頭部・未公開相手改変・上下反射を検査する。
    """
    band_audit = json.loads((HERE/'check_band_causality.json').read_text(encoding='utf-8'))
    assert band_audit['全合格'] and band_audit['全セル数']==260
    references = dict(band_audit['参照SHA256'])
    references.update(band_audit['出力SHA256'])
    released = json.loads((HERE/'released_depth_fixed.json').read_text(encoding='utf-8'))
    references.update(released['SHA256'])
    for path in (Path(__file__), HERE/'entry_signals.py', HERE/'design.py', HERE/'band_events.py',
                 HERE/'check_band_causality.json', HERE/'released_depth_fixed.json'):
        references[path.relative_to(ROOT).as_posix()] = sha(path)
    for relative, value in references.items():
        assert sha(ROOT/relative)==value, relative
    inputs = pickle.loads((ROOT/'work/wave_v23/inputs.pkl').read_bytes())
    events = pickle.loads((HERE/'released_depth.pkl').read_bytes())
    cache = pickle.loads((HERE/'band_cache.pkl').read_bytes())
    specs = design.catalog()+design.supplementary()
    assert len(specs)==len({s['id'] for s in specs})==281 and set(inputs)==set(events) and len(inputs)==26
    settings = {entry.cache_key(s):s for s in specs}
    assert len(settings)==10 and set(cache)==set(settings)
    assert all(set(c)==set(inputs) for c in cache.values())
    representatives = [s for s in specs if s['id'] in {f'B{i:02d}' for i in range(13)} or s.get('parent')=='B00' and s['role']=='sensitivity']
    assert len(representatives)==21
    peers = {key:entry.peer_prices(e) for key,e in events.items()}
    for key,e in events.items():
        equal_peer(entry.peer_prices(quantity_change(e)), peers[key])
    frequency, causal = [], []
    for key, ready in sorted(inputs.items()):
        session, symbol = key
        other = (session,'NK225' if symbol=='TOPIX' else 'TOPIX')
        baseline = {}
        for spec in specs:
            bands = cache[entry.cache_key(spec)][key]
            pulse, proof = entry.make(spec,key,inputs,bands,peers[other])
            repeated, proof_again = entry.make(spec,key,inputs,bands,peers[other])
            assert np.array_equal(pulse,repeated) and proof==proof_again
            assert np.isin(pulse,[-1,0,1]).all() and len(pulse)==len(ready['seq'])
            frequency.append(dict(id=spec['id'],session=session,symbol=symbol,
                候補数=int(np.count_nonzero(pulse)),ロング数=int((pulse==1).sum()),ショート数=int((pulse==-1).sum()),
                段階件数=proof['段階件数'],母集団キー=proof['母集団キー'],
                パルスSHA256=hashlib.sha256(pulse.tobytes()).hexdigest()))
            if any(spec['id']==r['id'] for r in representatives):
                baseline[spec['id']] = (pulse,proof)
        # ----------------------------------------
        # 同じ帯設定の再生成を共有し、条件除去の各入口には別々に適用する。
        pairs = [(max(1,int(len(ready['seq'])*fraction)), fraction) for fraction in (.37,.73)]
        variants = {}
        for cache_id, spec in settings.items():
            options = dict(start=float(ready['start']),limit=float(ready['limit']),tick=float(ready['tick']),
                           require_recovery=spec['board_anchor'],params=entry.band_settings(spec))
            variants[cache_id] = dict(reflect=band_events.build(reflect(events[key]),**options), cuts={})
            for cut,fraction in pairs:
                count = int(np.searchsorted(events[key]['ready_index'],cut,side='left'))
                variants[cache_id]['cuts'][cut] = dict(
                    prefix=band_events.build(select_rows(events[key],slice(0,count)),**options),
                    future=band_events.build(future_change(events[key],count),**options))
        mirror_peer = entry.peer_prices(reflect(events[other]))
        for spec in representatives:
            pulse, proof = baseline[spec['id']]
            changed, mirror_proof = entry.make(spec,key,inputs,variants[entry.cache_key(spec)]['reflect'],mirror_peer)
            np.testing.assert_array_equal(changed,-pulse)
            assert [r['band_id'] for r in mirror_proof['候補']]==[r['band_id'] for r in proof['候補']]
            cuts = []
            for cut,fraction in pairs:
                known_time = float(ready['time_s'][cut-1])
                peer_count = int(np.searchsorted(events[other]['time_s'],known_time-60.,side='right'))
                limited_peer = entry.peer_prices(select_rows(events[other],slice(0,peer_count)))
                changed_peer = entry.peer_prices(future_change(events[other],peer_count))
                short_ready = {name:(values[:cut].copy() if isinstance(values,np.ndarray) and values.ndim and len(values)==len(pulse)
                                     else values) for name,values in ready.items()}
                group = variants[entry.cache_key(spec)]['cuts'][cut]
                part, part_proof = entry.make(spec,key,{key:short_ready},group['prefix'],limited_peer)
                altered, altered_proof = entry.make(spec,key,inputs,group['future'],changed_peer)
                np.testing.assert_array_equal(part,pulse[:cut])
                np.testing.assert_array_equal(altered[:cut],pulse[:cut])
                expected_details = [r for r in proof['候補'] if r['decision']['ready_index']<cut]
                assert part_proof['候補']==expected_details
                assert [r for r in altered_proof['候補'] if r['decision']['ready_index']<cut]==expected_details
                cuts.append(dict(raw_count=cut,原本最終既知時刻=known_time,
                    相手公開保持数=peer_count,相手公開保持末尾=float(events[other]['time_s'][peer_count-1]) if peer_count else None,
                    prefix一致=True,未公開相手と未来自己改変一致=True,根拠一致=True))
            causal.append(dict(id=spec['id'],session=session,symbol=symbol,prefix数=2,future数=2,
                reflection数=1,全一致=True,切断=cuts))
        print(f'{session} {symbol}: 全281候補・代表21入口の因果一致',flush=True)
    assert len(frequency)==7306 and len(causal)==546
    aggregate = []
    for spec in specs:
        row = dict(id=spec['id'],spec=spec,symbols={})
        for symbol in ('TOPIX','NK225'):
            group = [r for r in frequency if r['id']==spec['id'] and r['symbol']==symbol]
            assert len(group)==13
            row['symbols'][symbol] = dict(候補数=sum(r['候補数'] for r in group),
                ロング数=sum(r['ロング数'] for r in group),ショート数=sum(r['ショート数'] for r in group),
                候補がある場数=sum(r['候補数']>0 for r in group))
        aggregate.append(row)
    for relative,value in references.items():
        assert sha(ROOT/relative)==value, relative
    freq = dict(全条件数=281,全入力数=7306,損益ではなく候補頻度=True,
        実約定又は勝敗ではない=True,集計=aggregate,セッション=frequency)
    audit = dict(全候補条件数=281,全候補入力数=7306,代表条件数=21,代表入力数=546,
        prefix数=1092,future数=1092,reflection数=546,相手価格数量独立数=26,
        代表ID=[r['id'] for r in representatives],結果=causal)
    return freq,audit,references


def main() -> None:
    """機能: 人工又は全保存入力の入口監査を実行し、前後SHAと全件証跡を保存する。

    引数: --synthetic-only (bool)。返り値: なし (None)。売買損益は計算しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--synthetic-only',action='store_true')
    args = parser.parse_args()
    socket.create_connection = denied
    socket.socket.connect = denied
    urllib.request.urlopen = denied
    artificial = synthetic()
    sources = {p.relative_to(ROOT).as_posix():sha(p) for p in
               [Path(__file__),HERE/'entry_signals.py',HERE/'design.py',HERE/'band_events.py']}
    write('check_entry_signals_synthetic.json',dict(artificial,参照SHA256=sources))
    if args.synthetic_only:
        print(json.dumps(dict(全合格=True,人工検査数=artificial['人工検査数']),ensure_ascii=False))
        return
    frequency,audit,references = real_cases()
    write('入口候補頻度.json',frequency)
    references.update({(HERE/'入口候補頻度.json').relative_to(ROOT).as_posix():sha(HERE/'入口候補頻度.json'),
        (HERE/'check_entry_signals_synthetic.json').relative_to(ROOT).as_posix():sha(HERE/'check_entry_signals_synthetic.json')})
    for relative,value in sources.items():
        assert sha(ROOT/relative)==value,relative
    write('check_entry_signals.json',dict(全合格=True,人工検査=artificial,**audit,
        参照SHA256=references,入力と実装前後不変=True,新売買実行=False,損益参照=False,
        現在保存物使用=False,API取得数=0))
    print(json.dumps(dict(全合格=True,全候補入力数=7306,代表入力数=546,
        人工検査数=artificial['人工検査数']),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
