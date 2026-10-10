"""帯生成の因果性・価格母集団の数量独立性を別実装で検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import band_events
import design

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def sha(path: Path) -> str:
    """機能: 読取資料の実体SHAを計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1048576):
            h.update(block)
    return h.hexdigest()


def write(name: str, value: dict) -> None:
    """機能: 日本語検査資料をJSON保存する。

    引数: name (str)、value (dict)。返り値: なし (None)。
    """
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def specifications() -> list[dict]:
    """機能: 採否モードで重複しない10種類の帯母集団を固定する。

    引数: なし。返り値: 基準2種類と板あり8感度 (list[dict])。
    """
    rows = [dict(id='BASE_BOARD', require_recovery=True, params={}),
            dict(id='BASE_PRICE', require_recovery=False, params={})]
    for identifier, name, value in [('A080','seed_seconds',24.), ('A120','seed_seconds',36.),
            ('T080','trial_seconds',24.), ('T120','trial_seconds',36.),
            ('D080','away_atr',.4), ('D120','away_atr',.6),
            ('K1','break_ticks',1.), ('K3','break_ticks',3.)]:
        rows.append(dict(id=identifier, require_recovery=True, params={name:value}))
    return rows


def cache_key(spec: dict) -> str:
    """機能: 採否と無関係な帯生成6変数と数量準備の有無を正準化する。

    引数: spec (dict)。返り値: 親entry_signalsと同構造のキー (str)。
    """
    values = band_events.parameters(spec['params'])
    selected = {key: values[key] for key in ['seed_seconds','trial_seconds','away_atr',
                'break_ticks','expiry_seconds','momentum_atr']}
    return json.dumps(dict(board_anchor=spec['require_recovery'],**selected),sort_keys=True)


def same(actual: object, expected: object, path: str = '') -> None:
    """機能: 記録の全キーと全値を比較し、浮動値の反射丸めだけ許す。

    引数: actual/expected (object)、path (str)。返り値: なし (None)。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), path
        for key in expected:
            same(actual[key], expected[key], path+'/'+key)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, (a, b) in enumerate(zip(actual, expected)):
            same(a, b, path+f'/{index}')
    elif isinstance(expected, float):
        assert isinstance(actual, (float, int)) and abs(actual-expected) <= 1e-8, (path, actual, expected)
    else:
        assert actual == expected, (path, actual, expected)


def observed(bands: list[dict], count: int) -> list[dict]:
    """機能: 切断時点までに確定した事実だけへ完成帯を投影する。

    引数: bands (list[dict])、count (int) は公開イベント先頭件数。
    返り値: created・過去の全イベント・確定試行・既観測sample (list[dict])。
    将来terminal/end/featuresと、未完試行の将来集計を比較しない。
    """
    result = []
    for band in bands:
        if band['created']['event_index'] >= count:
            continue
        item = {key: deepcopy(band[key]) for key in
                ['band_id','direction','price','atr','tick','created','expires_at','seed']}
        item['events'] = [deepcopy(value) for value in band['events'] if value['event_index'] < count]
        item['away'] = deepcopy(band['away']) if band['away'] is not None and band['away']['event_index'] < count else None
        item['terminal'] = deepcopy(band['terminal']) if band['terminal'] is not None and band['terminal']['event_index'] < count else None
        item['trials'] = []
        for trial in band['trials']:
            if trial['start']['event_index'] >= count:
                continue
            ended = trial['end'] is not None and trial['end']['event_index'] < count
            if ended:
                item['trials'].append(deepcopy(trial))
            else:
                item['trials'].append(dict(number=trial['number'], start=deepcopy(trial['start']),
                    observed_samples=[deepcopy(sample) for sample in trial['samples'] if sample['event_index'] < count]))
        completed = len(band['trials']) == 2 and all(trial['complete'] and trial['end'] is not None
            and trial['end']['event_index'] < count for trial in band['trials'])
        if completed:
            item['features'] = deepcopy(band['features'])
        result.append(item)
    return result


def price_path(bands: list[dict]) -> list[dict]:
    """機能: 数量を除去して、価格だけで決まる帯と試行の全経路を得る。

    引数: bands (list[dict])。返り値: 価格経路の完全記録 (list[dict])。
    """
    result = []
    for band in bands:
        item = {key: deepcopy(band[key]) for key in ['band_id','direction','price','atr','tick',
            'created','expires_at','status','phase','away','terminal','events']}
        item['seed'] = {key: deepcopy(band['seed'][key]) for key in ['left','right','window_seconds',
            'anchor_staleness_seconds','momentum','momentum_atr','quantity_required']}
        item['trials'] = []
        for trial in band['trials']:
            t = {key: deepcopy(trial[key]) for key in ['number','start','end','complete','sample_count',
                'maximum_pushback_atr','elapsed_seconds']}
            t['samples'] = [{key: deepcopy(sample[key]) for key in
                ['event_index','ready_index','seq','time_s','mid']} for sample in trial['samples']]
            item['trials'].append(t)
        item['features'] = {key: deepcopy(band['features'][key]) for key in
            ['two_trials_complete','price_comparable','b1','b2','pushback_change','price_weakens']}
        result.append(item)
    return result


def mirror_events(events: dict, anchor: float) -> dict:
    """機能: 公開数量と買売側を交換して価格を反射する。

    引数: events (dict[str,ndarray])、anchor (float)。返り値: 反射列 (dict)。
    """
    changed = {key: value.copy() for key, value in events.items()}
    changed['bid_prices'], changed['ask_prices'] = anchor-events['ask_prices'], anchor-events['bid_prices']
    changed['bid_qty'], changed['ask_qty'] = events['ask_qty'].copy(), events['bid_qty'].copy()
    return changed


def mirror_bands(bands: list[dict], anchor: float) -> list[dict]:
    """機能: 帯記録へ期待する上下対称変換だけを適用する。

    引数: bands (list[dict])、anchor (float)。返り値: 期待反射記録 (list[dict])。
    """
    changed = deepcopy(bands)
    for band in changed:
        band['direction'] *= -1
        band['price'] = anchor-band['price']
        band['seed']['momentum'] *= -1
        band['seed']['momentum_atr'] *= -1
        for trial in band['trials']:
            for sample in trial['samples']:
                sample['mid'] = anchor-sample['mid']
    return changed


def future_events(events: dict, count: int) -> dict:
    """機能: 切断以後だけの価格・数量・ATR・数量品質を大幅に変更する。

    引数: events (dict)、count (int)。返り値: 未来改変入力 (dict)。
    """
    changed = {key: value.copy() for key, value in events.items()}
    n = len(events['seq'])-count
    shift = np.where(np.arange(n)%2 == 0, 10000., 20000.)
    for key in ['bid_prices','ask_prices']:
        changed[key][count:] += shift[:,None]
    for key in ['bid_qty','ask_qty']:
        changed[key][count:] = np.arange(n)[:,None]+12345.
    changed['atr'][count:] = 1000.
    changed['depth_valid'][count:] = False
    changed['continuity_reset_count'][count:] = 9.
    return changed


def quantity_events(events: dict) -> dict:
    """機能: 価格を保ったまま全数量と数量品質を無効化する。

    引数: events (dict)。返り値: 数量だけ改変した入力 (dict)。
    """
    changed = {key: value.copy() for key, value in events.items()}
    changed['bid_qty'][:] = np.nan
    changed['ask_qty'][:] = np.nan
    changed['depth_valid'][:] = False
    changed['continuity_reset_count'][:] = 7.
    return changed


def fixture() -> dict:
    """機能: 二試行と最初の突破を含む、別設計の小さい人工板を作る。

    引数: なし。返り値: 公開列 (dict[str,ndarray])。
    """
    middle = np.array([100,101,102,103,103,103,103,98,103,103,103,103,107,107,107,107,107],float)
    n = len(middle)
    q = np.array([10,5,8,10,7,8,9,10,10,8,8,8,10,10,10,10,10],float)
    events = dict(seq=np.arange(n,dtype=np.int64)*3, ready_index=np.arange(n,dtype=np.int64)*2,
        time_s=np.arange(n)*10., atr=np.full(n,10.), price_valid=np.ones(n,bool),
        depth_valid=np.ones(n,bool), block_delay_seconds=np.full(n,1.),
        previous_release_gap=np.full(n,10.), continuity_reset_count=np.zeros(n))
    events['bid_prices'] = middle[:,None]-np.arange(1,11)[None,:]
    events['ask_prices'] = middle[:,None]+np.arange(1,11)[None,:]
    events['bid_qty'] = np.repeat(q[:,None],10,axis=1)
    events['ask_qty'] = events['bid_qty'].copy()
    return events


def synthetic() -> dict:
    """機能: 比較器が未来集計を除き、過去改変を拒否することを確認する。

    引数: なし。返り値: 合成検査結果 (dict)。
    """
    e = fixture(); settings = dict(start=0.,limit=10000.,tick=1.,params=dict(warmup_seconds=0.))
    b = band_events.build(e, **settings)
    assert len(b) >= 1 and b[0]['terminal']['reason'] == 'breakout'
    assert len(b[0]['trials']) == 2 and all(t['complete'] for t in b[0]['trials'])
    for cut in [5,8,10,12,13]:
        p = band_events.build({k:v[:cut].copy() for k,v in e.items()},**settings)
        same(observed(p,cut),observed(b,cut))
        f = band_events.build(future_events(e,cut),**settings)
        same(observed(f,cut),observed(b,cut))
    reflected = band_events.build(mirror_events(e,300.),**settings)
    same(reflected,mirror_bands(b,300.))
    p = band_events.build(e,require_recovery=False,**settings)
    q = band_events.build(quantity_events(e),require_recovery=False,**settings)
    same(price_path(p),price_path(q))
    failures = 0
    for kind in ['created','price','trial','pulse']:
        bad = deepcopy(b)
        if kind == 'created':bad[0]['created']['seq'] += 1
        elif kind == 'price':bad[0]['price'] += 1
        elif kind == 'trial':bad[0]['trials'][0]['maximum_pushback_atr'] += 1
        else:bad[0]['events'][0]['kind'] = '偽の遷移'
        try:
            same(observed(bad,len(e['seq'])),observed(b,len(e['seq'])))
        except AssertionError:
            failures += 1
    assert failures == 4
    return dict(全合格=True, prefix数=5, future数=5, reflection数=1,
                数量独立数=1, 過去改変の拒否数=failures, 新売買実行=False)


def main() -> None:
    """機能: 固定された状態機械を既知全26入力で独立検査する。

    引数: なし。返り値: なし (None)。売買・損益・現在データは読まない。
    """
    implementation = sha(OUT/'band_events.py')
    design_hash = sha(OUT/'design.py')
    audit_hash = sha(Path(__file__))
    fixed_input = json.loads((OUT/'released_depth_fixed.json').read_text(encoding='utf-8'))
    for path, expected in fixed_input['SHA256'].items():
        assert sha(ROOT/path) == expected, path
    specs = specifications()
    planned = set()
    for declared in design.catalog():
        planned.add(json.dumps(dict(board_anchor=declared['board_anchor'],
            seed_seconds=declared['anchor_seconds'],trial_seconds=declared['trial_seconds'],
            away_atr=declared['departure'],break_ticks=declared['break_ticks'],
            expiry_seconds=declared['lifetime'],momentum_atr=declared['momentum']),sort_keys=True))
    assert planned == {cache_key(spec) for spec in specs}, '設計母集団と独立監査の対象が異なる'
    protocol = dict(共通帯仕様=specs, 入力数=26, 仕様数=10, 全セル数=260,
        prefix比率=[.37,.73], future比率=[.37,.73],
        比較='切断前created・発行済み全遷移・確定trial・既観測sample。未来terminal/end/featuresは除外',
        数量独立='基準価格独立26入力で全数量NaN/reset/数量品質不正へ変更して価格全経路一致',
        band_events_SHA256=implementation, 新売買実行=False, 現在保存物使用=False, API取得数=0)
    write('band_causality_protocol.json',protocol)
    artificial = synthetic()
    write('band_causality_synthetic.json',artificial)
    events = pickle.loads((OUT/'released_depth.pkl').read_bytes())
    inputs = pickle.loads((ROOT/'work/wave_v23/inputs.pkl').read_bytes())
    assert set(events) == set(inputs) and len(events)==26
    rows, cache = [], {}
    for spec in specs:
        canonical = cache_key(spec)
        assert canonical not in cache
        cache[canonical] = {}
        for (session,symbol), e in sorted(events.items()):
            ready = inputs[(session,symbol)]
            options = dict(start=float(ready['start']),limit=float(ready['limit']),tick=float(ready['tick']),
                           require_recovery=spec['require_recovery'],params=spec['params'])
            baseline = band_events.build(e,**options)
            cache[canonical][(session,symbol)] = baseline
            n = len(e['seq'])
            cuts = []
            for fraction in [.37,.73]:
                rawcut = max(1,int(len(ready['seq'])*fraction))
                count = int(np.searchsorted(e['ready_index'],rawcut,side='left'))
                assert 0<count<n
                prefix = band_events.build({k:v[:count].copy() for k,v in e.items()},**options)
                same(observed(prefix,count),observed(baseline,count))
                future = band_events.build(future_events(e,count),**options)
                same(observed(future,count),observed(baseline,count))
                cuts.append(dict(raw_count=rawcut,event_count=count,seq=int(ready['seq'][rawcut]),
                                 過去帯数=len(observed(baseline,count)),全合格=True))
            anchor = float(4*np.nanmax(e['ask_prices']))
            reflected = band_events.build(mirror_events(e,anchor),**options)
            same(reflected,mirror_bands(baseline,anchor))
            independent = spec['id']=='BASE_PRICE'
            if independent:
                changed = band_events.build(quantity_events(e),**options)
                same(price_path(changed),price_path(baseline))
            rows.append(dict(id=spec['id'],session=session,symbol=symbol,全合格=True,
                帯数=len(baseline), 発行突破数=sum(b['terminal'] is not None and b['terminal']['reason']=='breakout' for b in baseline),
                prefix数=2,future数=2,reflection数=1,数量独立検査=independent,切断=cuts))
        print(f'{spec["id"]}: 26入力の因果・反射一致',flush=True)
    assert sha(OUT/'band_events.py') == implementation
    assert sha(OUT/'design.py') == design_hash and sha(Path(__file__)) == audit_hash
    for path, expected in fixed_input['SHA256'].items():
        assert sha(ROOT/path)==expected,path
    (OUT/'band_cache.pkl').write_bytes(pickle.dumps(cache,protocol=pickle.HIGHEST_PROTOCOL))
    refs = [OUT/'band_events.py',Path(__file__),OUT/'design.py',OUT/'band_causality_protocol.json',
            OUT/'band_causality_synthetic.json',OUT/'released_depth_fixed.json',OUT/'released_depth.pkl',
            ROOT/'work/wave_v23/inputs.pkl']
    result = dict(全合格=True,全セル数=260,入力数=26,仕様数=10,prefix数=520,future数=520,
        reflection数=260,数量独立数=26,結果=rows,人工検査=artificial,
        参照SHA256={str(path.relative_to(ROOT)).replace('\\','/'):sha(path) for path in refs},
        出力SHA256={'work/wave_v40/band_cache.pkl':sha(OUT/'band_cache.pkl')},
        キャッシュ正準キー=list(cache), 原本不変=True,新売買実行=False,現在保存物使用=False,API取得数=0)
    write('check_band_causality.json',result)
    print({key:result[key] for key in ['全合格','全セル数','prefix数','future数','reflection数']},flush=True)


if __name__=='__main__':
    main()
