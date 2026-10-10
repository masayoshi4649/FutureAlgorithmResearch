"""相手確認を入口に固定し、保有contextだけを変える12対応を損益前に監査する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD, V27, V28 = (HERE.parent / name for name in ('wave_v23', 'wave_v27', 'wave_v28'))
for folder in (OLD, HERE.parent / 'wave_v25', V28, V27):
    sys.path.insert(0, str(folder))
import hierarchy_signals as SIGNALS
import engine as LEGACY_ENGINE
import engine_context as ENGINE
import managers
import discovery_managers
from hierarchy_signal_audit import mirrored_inputs
from context_engine_audit import accounting, equal

IDS = [f'H{number:03d}' for number in (3, 11, 19, 27, 35, 43, 51, 59, 67, 75, 83, 91)]
CATEGORIES = ('開始20分の準備', '自己原本ATR無効', '自己公開足なし', '自己指標の履歴不足',
              '自己方向中立', '相手公開足なし', '相手指標の履歴不足', '相手方向中立', '相手逆方向', '両方向一致')


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 現在データ取得を含む通信を明示的に拒否する。

    引数: args/kwargs (object)。返り値: なし (None)。必ず例外を送出する。
    """
    raise AssertionError('構造監査で通信は許可しません')


def read(path: Path):
    """機能: 指定したJSONだけを読み、gzipにも対応する。

    引数: path (Path)。返り値: JSON内容 (dict|list)。
    """
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def save(path: Path, value) -> None:
    """機能: 本作業の監査資料だけを保存する。

    引数: path (Path)、value (dict|list)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'wt', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def digest(path: Path) -> str:
    """機能: 大きな原本もブロック単位で指紋化する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def original_hashes() -> dict:
    """機能: 読取り専用3領域の78原本が固定時から変わっていないか検査する。

    引数: なし。返り値: 参照原本のSHA256 (dict)。
    """
    expected = read(OLD / '入力確認.json')['原本SHA256']
    assert len(expected) == 78
    actual = {}
    for relative, fingerprint in expected.items():
        path = (ROOT / relative).resolve()
        assert path.is_relative_to(ROOT.resolve()) and relative.split('/')[0] in ('book', 'candle_1min', 'candle_5min')
        actual[relative] = digest(path)
        assert actual[relative] == fingerprint, '原本の固定後変更: ' + relative
    return actual


def paired_specs() -> list[tuple[dict, dict]]:
    """機能: 成績を使わず全12入口と自己main参照IDを照合する。

    引数: なし。返り値: 元HとID−1の仕様対 (list[tuple[dict,dict]])。
    """
    catalog = {spec['id']: spec for spec in SIGNALS.catalog()}
    chosen = [spec for spec in catalog.values() if spec['params']['entry_kind'] == 'short_price' and spec['params']['peer_confirm']]
    assert [spec['id'] for spec in chosen] == IDS
    output = []
    for spec in chosen:
        own = catalog[f'H{int(spec["id"][1:]) - 1:03d}']
        expected = dict(spec['params'], peer_confirm=False)
        assert own['params'] == expected
        assert all(spec['params'][name] == 1 for name in ('clock_multiplier', 'peer_multiplier', 'confirmation_multiplier'))
        output.append((spec, own))
    return output


def create_lanes(spec: dict, own: dict, inputs: dict, features: dict) -> dict:
    """機能: 入口は元Hのみ、C/Sは各mainだけから生成する。

    引数: spec/own/inputs/features (dict)。返り値: entry/C/Sの辞書 (dict)。
    """
    return dict(entry=SIGNALS.build(spec, inputs, features), C=SIGNALS.main_directions(spec, inputs),
                S=SIGNALS.main_directions(own, inputs))


def truncate(inputs: dict, features: dict, cutoffs: dict) -> tuple[dict, dict]:
    """機能: 各セッションの共通時刻で両市場の原本と特徴を切る。

    引数: inputs/features/cutoffs (dict)。返り値: 切断済み入力と特徴 (tuple[dict,dict])。
    """
    output, frames = {}, {}
    for key, ready in inputs.items():
        count = int(np.searchsorted(ready['time_s'], cutoffs[key[0]], side='right'))
        assert count > 0
        output[key] = {name: value[:count].copy() if isinstance(value, np.ndarray) else value for name, value in ready.items()}
        frame = features[key]
        frames[key] = frame.loc[(frame.time_s <= output[key]['time_s'][-1]) & (frame.seq <= output[key]['seq'][-1])].copy()
    return output, frames


def measurement_valid(bars: dict, params: dict) -> np.ndarray:
    """機能: 0方向に初期履歴不足が混ざる範囲を、閾値変更なしで区別する。

    引数: bars/params (dict)。返り値: 指標が計算できる足の真偽 (ndarray[bool])。
    """
    kind = params['main_kind']
    setting = SIGNALS.DESIGN['主方向'][kind]
    scale = params['time_multiplier'] * params['clock_multiplier']
    count = len(bars['time_s'])
    positions = np.arange(count)
    if kind.startswith('ema'):
        needed = SIGNALS._size(setting['slow'] * scale) + SIGNALS._size(setting['slope_bars'] * scale)
        valid = positions >= needed - 1
    elif kind in ('momentum20', 'breakout20'):
        valid = positions >= SIGNALS._size(setting['window'] * scale)
    elif kind == 'regression30':
        valid = positions >= max(2, SIGNALS._size(setting['window'] * scale)) - 1
    else:
        vwap = pd.Series(np.asarray(bars['vwap']))
        valid = np.isfinite(vwap) & np.isfinite(vwap.diff(SIGNALS._size(setting['slope_bars'] * scale)))
    return np.asarray(valid) & np.isfinite(bars['atr']) & (np.asarray(bars['atr']) > 0)


def durations(spec: dict, inputs: dict, lanes: dict) -> tuple[list[dict], list[dict]]:
    """機能: C/S不一致を原本時計で積分し、C=0の連続区間の原因混在を記録する。

    引数: spec/inputs/lanes (dict)。返り値: 区間集計と中立連続区間 (tuple[list[dict],list[dict]])。
    損益や建玉を読まないため、実際の保有時間や返済原因とは呼ばない。
    """
    models = {key: SIGNALS._main_model(ready, spec['params']) for key, ready in inputs.items()}
    valid = {key: measurement_valid(SIGNALS.LEGACY._bars(ready), spec['params']) for key, ready in inputs.items()}
    output, spells = [], []
    for key, ready in inputs.items():
        time_s = ready['time_s']
        own_key = key
        peer_key = (key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225')
        oi = np.searchsorted(models[own_key]['time_s'], time_s, side='right') - 1
        pi = np.searchsorted(models[peer_key]['time_s'] + 60, time_s, side='right') - 1
        own_raw = np.where(oi >= 0, models[own_key]['direction'][np.maximum(oi, 0)], 0).astype(np.int8)
        peer_raw = np.where(pi >= 0, models[peer_key]['direction'][np.maximum(pi, 0)], 0).astype(np.int8)
        own_valid = (oi >= 0) & valid[own_key][np.maximum(oi, 0)]
        peer_valid = (pi >= 0) & valid[peer_key][np.maximum(pi, 0)]
        warmup = time_s < ready['start'] + 1200
        badatr = ~np.isfinite(ready['atr']) | (ready['atr'] <= 0)
        expected_s = own_raw.copy(); expected_s[warmup | badatr] = 0
        expected_c = expected_s.copy(); expected_c[own_raw != peer_raw] = 0
        np.testing.assert_array_equal(expected_s, lanes['S'][key])
        np.testing.assert_array_equal(expected_c, lanes['C'][key])
        c, s, entry = lanes['C'][key], lanes['S'][key], lanes['entry'][key]
        assert np.all(c[c != 0] == s[c != 0])
        assert np.all(c[s == 0] == 0)
        assert np.all(entry[entry != 0] == c[entry != 0])
        category = np.select([warmup, badatr, oi < 0, ~own_valid, s == 0,
                              pi < 0, ~peer_valid, peer_raw == 0, peer_raw != s],
                             np.arange(9), default=9)
        assert np.all(category[c != 0] == 9), '非中立を欠測分類へ誤帰属'
        following = np.r_[time_s[1:], time_s[-1]]
        weights = np.maximum(0., np.minimum(following, ready['limit']) - np.maximum(time_s, ready['start']))
        assert np.isclose(weights.sum(), max(0., min(time_s[-1], ready['limit']) - max(time_s[0], ready['start'])))
        totals = {name: float(weights[category == number].sum()) for number, name in enumerate(CATEGORIES)}
        mismatch = float(weights[c != s].sum())
        assert np.isclose(mismatch, sum(totals[CATEGORIES[i]] for i in (5, 6, 7, 8)))
        zero = (c == 0) & (time_s >= ready['start']) & (time_s <= ready['limit'])
        boundaries = np.flatnonzero(np.r_[True, zero[1:] != zero[:-1], True])
        long_runs = mixed = 0
        for first, end in zip(boundaries[:-1], boundaries[1:]):
            if not zero[first]:
                continue
            seconds = float(weights[first:end].sum())
            causes = {name: float(weights[first:end][category[first:end] == number].sum())
                      for number, name in enumerate(CATEGORIES) if np.any((category[first:end] == number) & (weights[first:end] > 0))}
            if seconds >= 600:
                long_runs += 1
                if len(causes) > 1:
                    mixed += 1
                spells.append(dict(signal_id=spec['id'], session=key[0], symbol=key[1], 開始行=int(first),
                                   終了直前行=int(end - 1), 開始seq=int(ready['seq'][first]),
                                   開始時刻=float(time_s[first]), 連続0秒=seconds, 原因別秒=causes,
                                   原因混在=len(causes) > 1, 実際の保有を表すものではない=True))
        output.append(dict(signal_id=spec['id'], own_reference=f'H{int(spec["id"][1:]) - 1:03d}',
                           main_kind=spec['params']['main_kind'], time_multiplier=spec['params']['time_multiplier'],
                           session=key[0], symbol=key[1], 観測時間秒=float(weights.sum()), C_S不一致秒=mismatch,
                           自己買いかつC中立秒=float(weights[(s == 1) & (c == 0)].sum()),
                           自己売りかつC中立秒=float(weights[(s == -1) & (c == 0)].sum()),
                           原因別秒=totals, 連続0が10分以上の区間数=long_runs, うち原因混在区間数=mixed,
                           同一時刻の零時間行数=int(np.count_nonzero(np.diff(time_s) == 0))))
    return output, spells


def copied_candles(inputs: dict, name: str, modified_symbol: str | None = None,
                   cutoffs: dict | None = None, pivots: dict | None = None) -> Path:
    """機能: 未来相手足又は反射足を作業領域の複写にだけ保存する。

    引数: inputs (dict)、name (str)、modified_symbol (str|None)、cutoffs/pivots (dict|None)。
    返り値: 複写したcandle_1minの根 (Path)。原本は書き換えない。
    """
    target_root = HERE / 'audit_candles' / name
    for key in inputs:
        frame = pd.read_csv(ROOT / 'candle_1min' / key[1] / f'{key[0]}.csv')
        if cutoffs is not None and key[1] == modified_symbol:
            release = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120
            future = release > cutoffs[key[0]] - 60
            for column in ('open', 'high', 'low', 'close'):
                frame[column] = frame[column].astype(float)
                frame.loc[future, column] = frame.loc[future, column] * 1.5 + 7000
            frame['volume'] = frame['volume'].astype(float)
            frame.loc[future, 'volume'] = frame.loc[future, 'volume'] * 1e6 + 1e6
            frame.loc[future, 'volume_complete'] = True
        if pivots is not None:
            pivot = pivots[key]
            high, low = frame.high.copy(), frame.low.copy()
            for column in ('open', 'close'):
                frame[column] = 2 * pivot - frame[column]
            frame['high'], frame['low'] = 2 * pivot - low, 2 * pivot - high
        destination = (target_root / 'candle_1min' / key[1] / f'{key[0]}.csv').resolve()
        assert destination.is_relative_to((HERE / 'audit_candles').resolve())
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(destination, index=False, encoding='utf-8')
    return target_root


def future_peer(inputs: dict, features: dict, symbol: str, cutoffs: dict) -> tuple[dict, dict]:
    """機能: 相手の遅延後に未来となる価格・ATR・板だけを大きく改変する。

    引数: inputs/features/cutoffs (dict)、symbol (str) は改変市場。返り値: 改変入力と特徴 (tuple[dict,dict])。
    """
    output, frames = {}, {}
    for key, ready in inputs.items():
        output[key], frames[key] = dict(ready), features[key].copy()
        if key[1] != symbol:
            continue
        future = ready['time_s'] > cutoffs[key[0]] - 60
        for column in ('last', 'atr'):
            output[key][column] = ready[column].copy()
            output[key][column][future] = output[key][column][future] * 2 + 1000
        mask = frames[key].time_s > cutoffs[key[0]] - 60
        for column in frames[key].select_dtypes(include='number').columns:
            if 'time' not in column and 'seq' not in column:
                frames[key][column] = frames[key][column].astype(float)
                frames[key].loc[mask, column] = frames[key].loc[mask, column] * 3 + 1000
    return output, frames


def structural() -> dict:
    """機能: 損益ファイルとエンジン実行なしで全C/S構造と因果性を監査する。

    引数: なし。返り値: 構造監査 (dict)。
    """
    began = time.perf_counter()
    originals = original_hashes()
    paths = [Path(__file__), V27 / 'hierarchy_signals.py', V27 / 'hierarchy_design_fixed.json',
             OLD / 'signals.py', V28 / 'engine_context.py', OLD / 'inputs.pkl', OLD / 'features_depth.pkl']
    hashes = {str(path): digest(path) for path in paths}
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    assert len(inputs) == 26
    specs = paired_specs()
    full, state_rows, zero_spells = {}, [], []
    SIGNALS.set_root(ROOT)
    for spec, own in specs:
        full[spec['id']] = create_lanes(spec, own, inputs, features)
        with np.load(V27 / 'directions' / f'{spec["id"]}.npz') as archive:
            for key in inputs:
                np.testing.assert_array_equal(full[spec['id']]['entry'][key], archive['|'.join(key)])
        rows, spells = durations(spec, inputs, full[spec['id']])
        state_rows += rows; zero_spells += spells
    print('全12入口の保存列・ID−1自己main・C/S恒等式・中立時間を照合', flush=True)
    prefix = future = self_independent = reflected = 0
    for fraction in (.37, .73):
        cutoffs = {}
        for session in {key[0] for key in inputs}:
            pair = [r for key, r in inputs.items() if key[0] == session]
            start, end = max(r['start'] for r in pair), min(r['time_s'][-1] for r in pair)
            cutoffs[session] = start + fraction * (end - start)
        partial, short_features = truncate(inputs, features, cutoffs)
        SIGNALS.set_root(ROOT)
        for spec, own in specs:
            limited = create_lanes(spec, own, partial, short_features)
            for key, lane in itertools_product(inputs, ('entry', 'C', 'S')):
                np.testing.assert_array_equal(full[spec['id']][lane][key][:len(limited[lane][key])], limited[lane][key])
                prefix += 1
        for modified_symbol in ('TOPIX', 'NK225'):
            changed, changed_features = future_peer(inputs, features, modified_symbol, cutoffs)
            copy_root = copied_candles(inputs, f'相手未来_{modified_symbol}_{fraction}', modified_symbol, cutoffs)
            SIGNALS.set_root(copy_root)
            for spec, own in specs:
                altered = create_lanes(spec, own, changed, changed_features)
                for key in inputs:
                    if key[1] == modified_symbol:
                        continue
                    count = int(np.searchsorted(inputs[key]['time_s'], cutoffs[key[0]], side='right'))
                    for lane in ('entry', 'C', 'S'):
                        np.testing.assert_array_equal(full[spec['id']][lane][key][:count], altered[lane][key][:count])
                        future += 1
                    np.testing.assert_array_equal(full[spec['id']]['S'][key], altered['S'][key])
                    self_independent += 1
    changed, changed_features, pivots = mirrored_inputs(inputs, features)
    mirror_root = copied_candles(inputs, '上下反射', pivots=pivots)
    SIGNALS.set_root(mirror_root)
    for spec, own in specs:
        mirror = create_lanes(spec, own, changed, changed_features)
        for key, lane in itertools_product(inputs, ('entry', 'C', 'S')):
            np.testing.assert_array_equal(-full[spec['id']][lane][key], mirror[lane][key])
            reflected += 1
    SIGNALS.set_root(ROOT)
    assert hashes == {str(path): digest(path) for path in paths}
    assert originals == original_hashes()
    groups = defaultdict(list)
    for row in state_rows:
        groups[(row['signal_id'], row['symbol'])].append(row)
    overview = [dict(signal_id=key[0], symbol=key[1], C_S不一致秒=sum(r['C_S不一致秒'] for r in rows),
                     観測時間秒=sum(r['観測時間秒'] for r in rows),
                     連続0が10分以上の区間数=sum(r['連続0が10分以上の区間数'] for r in rows),
                     うち原因混在区間数=sum(r['うち原因混在区間数'] for r in rows)) for key, rows in sorted(groups.items())]
    report = dict(構造検査合格=True, 損益ファイル読取=False, 売買再生=False, API取得数=0, 現在データ使用=False,
                  入口ID=IDS, 自己参照ID=[own['id'] for _, own in specs], 保存入口完全一致数=312,
                  C_S恒等式検査数=len(state_rows), prefix比較数=prefix, 未来相手変更比較数=future,
                  相手変更に対する自己全列不変数=self_independent, 上下反射比較数=reflected,
                  状態時間定義='直前原本行の状態で次原本時刻まで積分。同時刻行は0秒。開始から場末以内。実保有時間ではない。',
                  状態別全312入力=state_rows, 入口銘柄別集計=overview,
                  中立原因の限界='履歴不足を区別したが、方向0は相場の真の中立を意味しない。原因交代でもC=0が続けば中立時計は継続。開始時の0列を実保有の返済原因へ直接転用しない。',
                  その他の懸念=['自己のみは中立撤回を減らすだけでなく、自己反転の返済を早め得る。',
                               '自己中立だけの返済では自己が反対方向へ変わると中立時計を解除し、逆向きの玉を長く保持する場合がある。',
                               'Cは遅延した相手の足方向を使い、相手の短期入口を要求しない。',
                               'CurrentPriceTimeは受信時刻ではない。長い無更新区間の秒数は観測時計上の継続である。'],
                  原本78SHA256=originals, 参照SHA256=hashes, 実行秒=time.perf_counter() - began)
    save(HERE / 'context_zero_spells.json.gz', zero_spells)
    save(HERE / 'context_structure_audit.json', report)
    write_note(report)
    return report


def itertools_product(keys: dict, lanes: tuple[str, ...]):
    """機能: 監査する原本キーと信号種別の全組合せを返す。

    引数: keys (dict)、lanes (tuple[str,...])。返り値: 組合せの反復子 (generator)。
    """
    for key in keys:
        for lane in lanes:
            yield key, lane


def write_note(report: dict) -> None:
    """機能: 損益前の構造結果と、追加時のB0互換を短い日本語で保存する。

    引数: report (dict)。返り値: なし (None)。
    """
    lines = ['# 相手確認と保有撤回・構造監査', '',
             '入口は相手確認ありの12条件で固定し、SはID−1のmainだけを参照した。自己のみの入口配列へ交換していない。構造段階では損益ファイルを読まず、売買も実行していない。', '',
             f'- 保存入口312配列、C/S恒等式312入力が一致。非0のCは必ずSと同方向で、S=0ならCも0。',
             f'- prefix {report["prefix比較数"]}、未来相手変更{report["未来相手変更比較数"]}、自己全列の相手非依存{report["相手変更に対する自己全列不変数"]}、上下反射{report["上下反射比較数"]}が一致。',
             '- 全78原本の固定SHAと監査前後SHAが一致。原本・旧コード・現在保存物は変更していない。', '',
             '|入口|銘柄|C/S不一致分|観測時間に対する割合|連続0が10分以上|うち原因混在|', '|---|---|---:|---:|---:|---:|']
    for row in report['入口銘柄別集計']:
        lines.append(f'|{row["signal_id"]}|{row["symbol"]}|{row["C_S不一致秒"]/60:,.1f}|{row["C_S不一致秒"]/row["観測時間秒"]:.1%}|{row["連続0が10分以上の区間数"]}|{row["うち原因混在区間数"]}|')
    lines += ['', 'この時間は原本CurrentPriceTime上の信号状態であり、実際の保有時間ではない。同時刻行は0秒として、直前の状態を次の時点まで積分した。準備20分・ATR・指標履歴不足を別分類し、0を全部相手不一致とは呼んでいない。',
              '', '中立10分の途中で自己中立と相手不一致が交代しても、C=0が続けば時計は継続する。返済時点の一原因だけに全区間を帰属できない。自己contextは中立撤回を減らし得る一方、自己反転の返済を早めるため、一律に保有を長くする方法でもない。']
    if 'B0旧互換' in report:
        lines += ['', '## 後段のB0旧互換', '', f'新しい撤回条件の損益を計算せず、12入口×26入力＝{report["B0旧互換"]["比較数"]}件でL000と旧D273の全注文・全返済・全行会計が厳密一致。旧保存台帳SHAとも一致。']
    (HERE / 'context_structure_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def baseline() -> dict:
    """機能: 構造結果保存後に限り12B0を旧D273と全入力で比較する。

    引数: なし。返り値: B0旧互換記録 (dict)。新しいC/S撤回の損益は計算しない。
    """
    report = read(HERE / 'context_structure_audit.json')
    assert report['構造検査合格'] and not report['損益ファイル読取'] and not report['売買再生']
    originals = original_hashes()
    fixed = read(HERE / '探索条件の固定.json')
    specs = paired_specs()
    assert {s['id'] for s in fixed['signals']} == set(IDS)
    management = next(m for m in fixed['managers'] if m['id'] == 'L000')
    old_spec = next(m for m in discovery_managers.catalog() if m['id'] == 'D273')
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    count = rows = 0
    for spec, own in specs:
        expected = next(c for c in read(V27 / 'summaries' / f'{spec["id"]}.json')['candidates'] if c['manager_id'] == 'D273')
        hasher = hashlib.sha256()
        with np.load(V27 / 'directions' / f'{spec["id"]}.npz') as archive:
            for key, ready in inputs.items():
                old_cfg = managers.make_config(old_spec, key[1], ready)
                new_cfg = managers.make_config(management, key[1], ready)
                assert old_cfg == new_cfg, 'B0管理の旧D273との差'
                direction = archive['|'.join(key)]
                old = LEGACY_ENGINE.run(ready, direction, old_cfg, detail=True)
                actual = ENGINE.run(ready, direction, new_cfg, detail=True, context=None)
                equal(old, actual)
                rows += accounting(ready, actual, new_cfg)
                hasher.update(str(key).encode()); hasher.update(actual['trades'].tobytes())
                count += 1
        assert hasher.hexdigest() == expected['ledger_hash']
    assert originals == original_hashes()
    record = dict(比較数=count, 全原本行会計数=rows, 旧保存台帳SHA一致入口数=len(specs), 新撤回条件の損益計算=False,
                  B0管理設定=management, 原本不変=True)
    report['B0旧互換'] = record
    save(HERE / 'context_structure_audit.json', report)
    write_note(report)
    return record


def main() -> None:
    """機能: 損益前の構造検査と後段のB0互換を別実行にする。

    引数: --baseline (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    result = baseline() if args.baseline else structural()
    print(json.dumps({key: value for key, value in result.items() if key in (
        '構造検査合格', 'prefix比較数', '未来相手変更比較数', '上下反射比較数', '相手変更に対する自己全列不変数',
        '比較数', '全原本行会計数', '実行秒')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
