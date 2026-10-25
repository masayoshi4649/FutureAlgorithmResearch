"""既知12入口と、入口ATRを変えない追跡専用ATR列を損益前に監査する。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
V27, V30, V31 = (HERE.parent / folder for folder in ('wave_v27', 'wave_v30', 'wave_v31'))
IDS = [f'H{i:03d}' for i in (3, 11, 19, 27, 35, 43, 51, 59, 67, 75, 83, 91)]
sys.dont_write_bytecode = True
sys.path.insert(0, str(V27))
import hierarchy_signals as SIGNALS


def read(path: Path):
    """機能: 指定されたJSONをUTF-8で読む。

    引数: path (Path)。返り値: JSON内容 (dict|list)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """機能: 新作業領域へ日本語の監査記録を保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(path: Path) -> str:
    """機能: 読取り専用資料をブロック単位で指紋化する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    state = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            state.update(block)
    return state.hexdigest()


def array_hash(values: dict) -> str:
    """機能: キーと配列内容を含む安定した指紋を作る。

    引数: values (dict)。返り値: SHA256 (str)。
    """
    state = hashlib.sha256()
    for key in sorted(values):
        state.update(str(key).encode('utf-8'))
        state.update(values[key].tobytes())
    return state.hexdigest()


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: APIを含むネットワーク接続を拒否する。

    引数: args/kwargs (object)。返り値: なし (None)。常に例外を送出する。
    """
    raise AssertionError('入力監査ではAPIと外部通信を禁止します')


def _past(times: np.ndarray, values: np.ndarray, seconds: float, initial: float | int) -> tuple[np.ndarray, np.ndarray]:
    """機能: 同一セッション内の公開済み原本列だけを過去参照する。

    引数: times/values (ndarray)、seconds (float)、initial (float|int)。
    返り値: 参照値と元原本行 (tuple[ndarray,ndarray])。0秒は同値時刻の後続行へ飛ばずidentity。
    """
    times, values = np.asarray(times, float), np.asarray(values)
    assert times.ndim == values.ndim == 1 and len(times) == len(values) and len(times) > 0
    assert np.isfinite(times).all() and np.all(np.diff(times) >= 0)
    assert np.isfinite(seconds) and seconds >= 0
    if seconds == 0:
        return values.copy(), np.arange(len(times), dtype=np.int64)
    source = np.searchsorted(times, times - seconds, side='right').astype(np.int64) - 1
    valid = source >= 0
    assert np.all(source[valid] < np.flatnonzero(valid))
    assert np.all(times[source[valid]] <= times[valid] - seconds)
    output = np.full(values.shape, initial, dtype=values.dtype)
    output[valid] = values[source[valid]]
    return output, source


def make_tracking_atr(ready: dict, delay_seconds: float = 0) -> tuple[np.ndarray, np.ndarray]:
    """機能: 初期注文用ready['atr']を変更せず、追跡幅専用ATR列を生成する。

    引数: ready (dict)、delay_seconds (float) は通常0又は診断300秒。
    返り値: float64の追跡候補ATRと参照原本行 (tuple[ndarray,ndarray])。
    欠測はNaNのまま返す。欠測保持・初期A0への代替・下限は注文器が保有状態に対して適用する。
    """
    return _past(ready['time_s'], np.asarray(ready['atr'], np.float64), delay_seconds, np.nan)


def make_entry(ready: dict, base_entry: np.ndarray, delay_seconds: float = 0) -> tuple[np.ndarray, np.ndarray]:
    """機能: 入口だけの15秒遅延対照を作り、ATRと価格を変更しない。

    引数: ready (dict)、base_entry (ndarray[int8])、delay_seconds (float)。
    返り値: int8入口と参照原本行 (tuple[ndarray,ndarray])。参照前は中立0。
    """
    assert base_entry.dtype == np.int8 and np.isin(base_entry, (-1, 0, 1)).all()
    return _past(ready['time_s'], base_entry, delay_seconds, 0)


def load_entries(inputs: dict) -> dict:
    """機能: 旧12入口を読取り、v27/v30/v31の基準列が全区間で同一か検査する。

    引数: inputs (dict[(session,symbol),ready])。返り値: ID別入口辞書 (dict[str,dict])。
    売買成績は読まない。原本順の入口列だけを使用する。
    """
    output = {}
    assert len(inputs) == 26
    keys = {'|'.join(k) for k in inputs}
    for identifier in IDS:
        paths = [V27 / 'directions' / (identifier + '.npz'), V30 / 'directions' / (identifier + '.npz'),
                 V31 / 'directions' / (identifier + '__V000.npz')]
        with np.load(paths[0]) as earliest, np.load(paths[1]) as source, np.load(paths[2]) as preserved:
            assert set(source.files) == set(earliest.files) == set(preserved.files) == keys
            output[identifier] = {}
            for key, ready in inputs.items():
                values = source['|'.join(key)]
                assert values.dtype == np.int8 and values.shape == ready['last'].shape
                assert np.isin(values, (-1, 0, 1)).all()
                np.testing.assert_array_equal(values, earliest['|'.join(key)])
                np.testing.assert_array_equal(values, preserved['|'.join(key)])
                output[identifier][key] = values
    return output


def five_rows(session: str, symbol: str) -> list[dict]:
    """機能: 固定78原本に含まれる5分足CSVだけを読む。

    引数: session/symbol (str)。返り値: 元行辞書 (list[dict])。ライブへの例外経路を持たない。
    """
    relative = f'candle_5min/{symbol}/{session}.csv'
    expected = read(OLD / '入力確認.json')['原本SHA256']
    assert relative in expected
    path = ROOT / relative
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def atr_events(rows: list[dict], tick: float) -> tuple[np.ndarray, np.ndarray]:
    """機能: 確定5分足から公開時刻と平滑ATRを独立の逐次式で計算する。

    引数: rows (list[dict])、tick (float)。返り値: 開始+360秒の公開時刻とATR (tuple[ndarray,ndarray])。
    TRは高安差・前終値差の最大、α1/12、実在3本以上、下限2呼値。pandasの旧ATR関数は呼ばない。
    """
    closed = [r for r in rows if str(r['closed']).lower() == 'true']
    closed.sort(key=lambda r: datetime.fromisoformat(r['time']).timestamp())
    released, values = [], []
    previous_close = state = np.nan
    for index, row in enumerate(closed):
        moment = datetime.fromisoformat(row['time']).timestamp() + 360.
        high, low, close = (float(row[k]) for k in ('high', 'low', 'close'))
        assert np.isfinite([high, low, close]).all() and high >= low and low > 0
        tr = high - low
        if np.isfinite(previous_close):
            tr = max(tr, abs(high - previous_close), abs(low - previous_close))
        state = tr if index == 0 else state * (11. / 12.) + tr / 12.
        previous_close = close
        released.append(moment)
        values.append(max(state, 2 * tick) if index >= 2 else np.nan)
    assert len(released) < 2 or np.all(np.diff(released) > 0), '公開足の重複・逆順を拒否'
    return np.asarray(released, float), np.asarray(values, float)


def expand_events(events: np.ndarray, values: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """機能: 公開済み足だけを原本時刻へ対応させ、欠測・未公開はNaNとする。

    引数: events/values/targets (ndarray)。返り値: ATRと参照足行 (tuple[ndarray,ndarray])。
    """
    source = np.searchsorted(events, targets, side='right') - 1
    valid = source >= 0
    output = np.full(len(targets), np.nan)
    output[valid] = values[source[valid]]
    assert np.all(events[source[valid]] <= targets[valid])
    return output, source


def sequential_past(times: np.ndarray, values: np.ndarray, delay: float, initial: float | int) -> tuple[np.ndarray, np.ndarray]:
    """機能: 二ポインタで過去列を独立生成し、検索版の参照行を検算する。

    引数: times/values (ndarray)、delay (float)、initial (float|int)。返り値: 値と参照行 (tuple)。
    """
    output = np.full(values.shape, initial, dtype=values.dtype)
    indices = np.full(len(times), -1, np.int64)
    at = -1
    for i, moment in enumerate(times):
        if delay == 0:
            output[i], indices[i] = values[i], i
            continue
        while at + 1 < i and times[at + 1] <= moment - delay:
            at += 1
        if at >= 0:
            output[i], indices[i] = values[at], at
    return output, indices


def same(left: tuple, right: tuple, name: str) -> None:
    """機能: 値・参照行・NaN位置の一致を検査する。

    引数: left/right (tuple)、name (str)。返り値: なし (None)。
    """
    for a, b in zip(left, right):
        np.testing.assert_array_equal(a, b, err_msg=name)


def synthetic() -> dict:
    """機能: 同時刻行・欠測保持前・足公開境界・最少3本・下限を人工値で確認する。

    引数: なし。返り値: 合成検査結果 (dict)。売買再生は行わない。
    """
    times = np.array([0., 0., 1., 15., 15., 300., 300., 301., 600.])
    atr = np.array([np.nan, 2., np.inf, -1., 4., 8., np.nan, 16., 32.])
    entry = np.array([0, 1, -1, 1, 0, -1, 1, 0, 1], np.int8)
    ready = dict(time_s=times, atr=atr)
    frozen = atr.copy()
    for delay in (0., 300.):
        same(make_tracking_atr(ready, delay), sequential_past(times, atr, delay, np.nan), '追跡遅延の独立比較')
        for cut in range(1, len(times) + 1):
            part = dict(time_s=times[:cut], atr=atr[:cut])
            same(make_tracking_atr(part, delay), tuple(v[:cut] for v in make_tracking_atr(ready, delay)), '同時刻を含むprefix')
    same(make_entry(ready, entry, 0), (entry, np.arange(len(times), dtype=np.int64)), '0秒identity')
    same(make_entry(ready, entry, 15), sequential_past(times, entry, 15, 0), '入口15秒')
    np.testing.assert_array_equal(atr, frozen)
    rows = [dict(time=f'2026-09-21T08:{m:02d}:00+09:00', high=100., low=100., close=100., closed=True)
            for m in (45, 50, 55)]
    events, values = atr_events(rows, .5)
    assert np.isnan(values[:2]).all() and values[2] == 1.
    boundary = np.array([events[2] - 1e-3, events[2], events[2] + 1e-3])
    actual, _ = expand_events(events, values, boundary)
    assert np.isnan(actual[0]) and np.array_equal(actual[1:], [1., 1.])
    changed = [dict(r) for r in rows]
    changed += [dict(rows[-1], time='2026-09-21T09:00:00+09:00', high=10000, closed=False)]
    same(atr_events(changed, .5), (events, values), '未確定足除外')
    return dict(合成合格=True, 同時刻0秒identity=True, 同時刻prefix=True, 過去参照二ポインタ一致=True,
                入口ATR不変=True, 先頭NaN=True, 非有限と非正値の代替はengine責任=True,
                最少3本=True, 下限2呼値=True, 公開360秒の直前直後=True, 未確定足除外=True)


def audit_atr(inputs: dict) -> dict:
    """機能: 全26原本ATR・追跡専用5分過去参照・未来切断とATR変更を監査する。

    引数: inputs (dict)。返り値: 原本区間別の監査証跡 (dict)。
    """
    records, tracking, maximum_error = [], {0: {}, 300: {}}, 0.
    for key, ready in inputs.items():
        raw_rows = five_rows(*key)
        events, values = atr_events(raw_rows, ready['tick'])
        reconstructed, source = expand_events(events, values, ready['time_s'])
        np.testing.assert_allclose(reconstructed, ready['atr'], atol=1e-9, rtol=1e-12, equal_nan=True)
        finite = np.isfinite(reconstructed)
        assert np.all(reconstructed[finite] >= 2 * ready['tick'])
        error = float(np.max(np.abs(reconstructed[finite] - ready['atr'][finite]))) if finite.any() else 0.
        maximum_error = max(maximum_error, error)
        original = ready['atr'].copy()
        columns = {}
        for delay in (0, 300):
            columns[delay] = make_tracking_atr(ready, delay)
            tracking[delay][key] = columns[delay][0]
            same(columns[delay], sequential_past(ready['time_s'], ready['atr'], delay, np.nan), '全原本追跡ATR二ポインタ')
        for fraction in (.37, .73):
            count = max(2, int(len(ready['last']) * fraction))
            cutoff = ready['time_s'][count - 1]
            known = events <= cutoff
            prefix, _ = expand_events(events[known], values[known], ready['time_s'][:count])
            np.testing.assert_array_equal(prefix, reconstructed[:count])
            altered_rows = [dict(r) for r in raw_rows]
            for row in altered_rows:
                if datetime.fromisoformat(row['time']).timestamp() + 360 > cutoff:
                    row['high'], row['low'], row['close'] = 1200000., 1000000., 1100000.
            altered_events, altered_values = atr_events(altered_rows, ready['tick'])
            changed, _ = expand_events(altered_events, altered_values, ready['time_s'])
            np.testing.assert_array_equal(changed[:count], reconstructed[:count])
            partial = dict(ready, time_s=ready['time_s'][:count], atr=ready['atr'][:count])
            changed_atr = ready['atr'].copy(); changed_atr[count:] = 1000000.
            future = dict(ready, atr=changed_atr)
            for delay in (0, 300):
                same(make_tracking_atr(partial, delay), tuple(v[:count] for v in columns[delay]), '追跡ATR切断')
                same(tuple(v[:count] for v in make_tracking_atr(future, delay)),
                     tuple(v[:count] for v in columns[delay]), '未来ATR改変')
        np.testing.assert_array_equal(ready['atr'], original)
        records.append(dict(session=key[0], symbol=key[1], 原本行数=len(ready['last']),
                            公開足数=len(events), 有効ATR行数=int(finite.sum()), 先頭等欠測行数=int((~finite).sum()),
                            同値時刻行数=int(np.count_nonzero(np.diff(ready['time_s']) == 0)),
                            独立逐次式との最大差=error, 入口ATR不変=True, 公開時刻下限一致=True,
                            追跡ATR2列独立生成一致=True, prefix2点一致=True, 未来足ATR2点改変一致=True))
    return dict(ATR構造監査合格=True, 対象入力数=len(records), 原本行数=sum(r['原本行数'] for r in records),
                ATR再計算最大誤差=maximum_error, 追跡ATR配列SHA256={str(d): array_hash(v) for d, v in tracking.items()},
                rows=records)


def audit_entries(inputs: dict, features: dict, entries: dict) -> dict:
    """機能: 旧12入口を再生成し、両市場切断・未来ATR変更と15秒列を監査する。

    引数: inputs/features/entries (dict)。返り値: 全12×26の監査証跡 (dict)。
    """
    catalog = {s['id']: s for s in SIGNALS.catalog()}
    specs = [catalog[name] for name in IDS]
    expected = [s['id'] for s in SIGNALS.catalog() if s['params']['entry_kind'] == 'short_price' and s['params']['peer_confirm']]
    assert expected == IDS
    assert [s['id'] for s in read(V30 / '探索条件の固定.json')['signals']] == IDS
    assert [s['id'] for s in read(V31 / '探索条件の固定.json')['signals']] == IDS
    records = []
    for spec in specs:
        SIGNALS.clear_cache()
        generated = SIGNALS.build(spec, inputs, features)
        for key, ready in inputs.items():
            np.testing.assert_array_equal(generated[key], entries[spec['id']][key])
            columns = make_entry(ready, generated[key], 15)
            same(columns, sequential_past(ready['time_s'], generated[key], 15, 0), '入口15秒二ポインタ')
            records.append(dict(id=spec['id'], session=key[0], symbol=key[1],
                                v27_v30_v31同一=True, 再生成一致=True, 入口15秒独立参照一致=True))
    counters = dict(prefix比較数=0, 未来ATR改変比較数=0, 入口15秒prefix比較数=0)
    for fraction in (.37, .73):
        counts = {}
        for session in sorted({k[0] for k in inputs}):
            peers = [r for k, r in inputs.items() if k[0] == session]
            start = min(r['start'] for r in peers)
            cutoff = start + fraction * (min(r['time_s'][-1] for r in peers) - start)
            for key in inputs:
                if key[0] == session:
                    counts[key] = int(np.searchsorted(inputs[key]['time_s'], cutoff, side='right'))
        partial, sliced_features, changed = {}, {}, {}
        for key, ready in inputs.items():
            count = counts[key]
            assert count > 0
            partial[key] = {name: value[:count] if isinstance(value, np.ndarray) and len(value) == len(ready['last']) else value
                            for name, value in ready.items()}
            frame = features[key]
            sliced_features[key] = frame.loc[(frame.time_s <= partial[key]['time_s'][-1]) &
                                             (frame.seq <= partial[key]['seq'][-1])].copy()
            future = ready['atr'].copy(); future[count:] = 1000000.
            changed[key] = dict(ready, atr=future)
        for spec in specs:
            SIGNALS.clear_cache()
            prefix = SIGNALS.build(spec, partial, sliced_features)
            SIGNALS.clear_cache()
            future = SIGNALS.build(spec, changed, features)
            for key, ready in inputs.items():
                count = counts[key]
                original = entries[spec['id']][key]
                np.testing.assert_array_equal(prefix[key], original[:count])
                np.testing.assert_array_equal(future[key][:count], original[:count])
                same(make_entry(partial[key], prefix[key], 15),
                     tuple(v[:count] for v in make_entry(ready, original, 15)), '15秒入口prefix')
                counters['prefix比較数'] += 1
                counters['未来ATR改変比較数'] += 1
                counters['入口15秒prefix比較数'] += 1
    SIGNALS.clear_cache()
    return dict(入口構造監査合格=True, 全入口数=12, 全区間数=312,
                入口SHA256={name: array_hash(values) for name, values in entries.items()}, rows=records, **counters)


def main() -> None:
    """機能: 新損益を読まず入力全件の因果性と固定指紋を確認する。

    引数: --synthetic-only (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--synthetic-only', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    tests = synthetic()
    save(HERE / 'input_synthetic_audit.json', tests)
    if args.synthetic_only:
        print('入力合成監査合格。売買再生なし。', flush=True)
        return
    original = read(OLD / '入力確認.json')['原本SHA256']
    assert len(original) == 78
    for name, value in original.items():
        assert name.split('/')[0] in ('book', 'candle_1min', 'candle_5min')
        assert digest(ROOT / name) == value, name
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    features = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    assert len(inputs) == len(features) == 26
    sessions = sorted({k[0] for k in inputs})
    assert len(sessions) == 13
    source_files = [Path(__file__), OLD / 'inputs.pkl', OLD / 'features_depth.pkl', OLD / '入力確認.json',
                    OLD / 'signals.py', V27 / 'hierarchy_signals.py', V27 / 'hierarchy_design_fixed.json',
                    V30 / '探索条件の固定.json', V31 / '探索条件の固定.json']
    for identifier in IDS:
        source_files += [V27 / 'directions' / (identifier + '.npz'), V30 / 'directions' / (identifier + '.npz'),
                         V31 / 'directions' / (identifier + '__V000.npz')]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in source_files}
    entries = load_entries(inputs)
    atr = audit_atr(inputs)
    print('全26原本ATRの公開・下限・未来・追跡専用5分参照を確認。', flush=True)
    entry = audit_entries(inputs, features, entries)
    assert before == {name: digest(ROOT / name) for name in before}
    assert original == {name: digest(ROOT / name) for name in original}
    result = dict(構造監査合格=True, 全監査完了=True, 新損益読取=False, 売買再生=False,
                  API取得数=0, 現在保存物使用=False, 対象入口ID=IDS,
                  全セッション=sessions, 初期6セッション=sessions[:6], 共通評価7セッション=sessions[6:],
                  合成=tests, ATR=atr, 入口=entry, 参照SHA256=before, 原本78SHA256=original,
                  注意='原本時刻はCurrentPriceTime代理。受信時刻の完全再現を保証しない。入力の因果性であり収益性ではない。')
    save(HERE / 'input_causality_before_pnl.json', result)
    save(HERE / 'input_audit.json', result)
    (HERE / 'input_audit.md').write_text('\n'.join([
        '# 保有ATR比較の入力監査', '',
        '- 旧12入口×26区間はv27/v30/v31で同一。旧定義からの再生成とも一致。',
        '- ATRは固定78原本内の確定5分足だけで独立再計算。開始＋360秒公開、最少3本、下限2呼値。',
        '- 入口ATRは不変。追跡専用0秒／300秒列は独立二ポインタ参照と一致。先頭欠測はNaNで注文器へ渡す。',
        '- 0秒は同時刻後続行を拾わないidentity。15秒入口も同じ過去参照契約。',
        f'- 全12入口のprefix・未来ATR改変・遅延入口prefixは各{entry["prefix比較数"]}件一致。',
        '- 全26ATRの2切断点で未公開足と未来ATRを改変し、過去列の不変を確認。',
        '- 全13と後半7を区別。新損益・API・現在保存物を使用せず、原本と旧実装は前後指紋不変。', '',
        '欠測保持・A0代替・追跡だけの幅適用は注文器側の別監査対象。']) + '\n', encoding='utf-8')
    print(dict(構造監査合格=True, 入口区間数=312, ATR区間数=26, **{k: entry[k] for k in ('prefix比較数', '未来ATR改変比較数')}), flush=True)


if __name__ == '__main__':
    main()
