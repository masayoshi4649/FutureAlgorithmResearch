"""T/R入口と、公開済み相場状態・完了済み影口座による共通要求を生成する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V25, V27, V30 = (HERE.parent / name for name in ('wave_v25', 'wave_v27', 'wave_v30'))
for folder in (V25, V27):
    sys.path.insert(0, str(folder))
import hierarchy_signals as HIERARCHY
sys.path.insert(0, str(V25))
import d016_price_control as PRICE
import discovery_signals as DISCOVERY

SYMBOLS = ('TOPIX', 'NK225')
BRANCHES = ('T', 'R')
QUANTITY = {'TOPIX': 5, 'NK225': 10}
MULTIPLIER = {'TOPIX': 1000., 'NK225': 10.}
INPUTS, FEATURES = {}, {}


def clear_cache() -> None:
    """機能: 旧ソースを変更せず、足・板の計算キャッシュを破棄する。

    引数: なし。返り値: なし (None)。
    """
    HIERARCHY.clear_cache()
    DISCOVERY.clear_cache()


def set_root(path: Path | str) -> None:
    """機能: 因果監査で足の複写を使用できるよう参照根を明示する。

    引数: path (Path|str)。返り値: なし (None)。原本は書き換えない。
    """
    global ROOT
    ROOT = Path(path).resolve()
    HIERARCHY.set_root(ROOT)
    DISCOVERY.LEGACY.ROOT = ROOT
    clear_cache()


def initialize(inputs: dict, features: dict) -> None:
    """機能: 呼出側が読んだ保存済み入力を登録する。通信や損益再生は行わない。

    引数: inputs/features (dict)。返り値: なし (None)。
    """
    global INPUTS, FEATURES
    INPUTS, FEATURES = inputs, features
    clear_cache()


def build_entries(inputs: dict | None = None, features: dict | None = None) -> dict:
    """機能: 凍結H019と、凍結P02の価格だけの撤回版を原仕様で再生成する。

    引数: inputs/features (dict|None) は省略時に登録済み入力。返り値: T/Rの方向辞書 (dict)。
    P02の観測時計は元の板イベント由来。板数量・OFIを判断に使う別版と区別する。
    """
    inputs = INPUTS if inputs is None else inputs
    features = FEATURES if features is None else features
    assert inputs and set(inputs) <= set(features)
    spec = next(s for s in HIERARCHY.catalog() if s['id'] == 'H019')
    trend = HIERARCHY.build(spec, inputs, features)
    fixed = json.loads((V25 / 'd016_price_control_fixed.json').read_text(encoding='utf-8'))
    params = deepcopy(fixed['規則']['元信号']['params'])
    models = {key: {name: np.asarray(model[name]).copy() for name in PRICE.FIELDS}
              for key, ready in inputs.items() for model in [DISCOVERY._book(ready, features[key], params['seconds'])]}
    reversal, _ = PRICE.build(inputs, models, params, 'P02', veto_mode='price')
    for outputs in (trend, reversal):
        assert set(outputs) == set(inputs)
        assert all(v.dtype == np.int8 and len(v) == len(inputs[k]['seq']) and np.isin(v, [-1, 0, 1]).all() for k, v in outputs.items())
    return {'T': trend, 'R': reversal}


def _sessions(inputs: dict) -> list[tuple[str, float, float, float]]:
    """機能: 両市場の同一開始時刻を確認し、時刻順のセッション時計を作る。

    引数: inputs (dict)。返り値: 名前・開始・共通終了・観測末尾 (list[tuple])。
    """
    output = []
    for session in sorted({k[0] for k in inputs}):
        assert {(s, y) for s, y in inputs if s == session} == {(session, symbol) for symbol in SYMBOLS}
        pair = [inputs[session, symbol] for symbol in SYMBOLS]
        assert pair[0]['start'] == pair[1]['start']
        for ready in pair:
            assert len(ready['time_s']) > 0 and np.isfinite(ready['time_s']).all()
            assert np.all(np.diff(ready['time_s']) >= 0)
        output.append((session, float(pair[0]['start']), min(float(r['limit']) for r in pair),
                       max(float(r['time_s'][-1]) for r in pair)))
    return sorted(output, key=lambda row: (row[1], row[0]))


def _clock(start: float, limit: float, observed: float) -> np.ndarray:
    """機能: 開始30分後から場末未満の固定30分時計を作る。

    引数: start/limit/observed (float)。返り値: 観測末尾以下の時計 (ndarray[float])。
    """
    last = min(np.nextafter(limit, -np.inf), observed)
    count = max(0, int(np.floor((last - start) / 1800.)))
    return start + np.arange(1, count + 1, dtype=float) * 1800.


def _expand_requests(inputs: dict, session: str, events: list[dict]) -> dict:
    """機能: 共通要求イベントを各市場の原本行へ過去asofで展開する。

    引数: inputs (dict)、session (str)、events (list[dict])。返り値: 両市場の要求列 (dict)。
    """
    stamps = np.asarray([r['timestamp'] for r in events], float)
    values = np.asarray([r['request'] for r in events], np.int8)
    assert np.all(np.diff(stamps) > 0)
    output = {}
    for symbol in SYMBOLS:
        key = (session, symbol)
        indices = np.searchsorted(stamps, inputs[key]['time_s'], side='right') - 1
        out = np.ones(len(indices), np.int8)
        valid = indices >= 0
        out[valid] = values[indices[valid]]
        output[key] = out
    return output


def _er_models(inputs: dict, window: int) -> dict:
    """機能: 確定足始+120秒公開にさらに60秒を加えたERを両市場同じ時計で作る。

    引数: inputs (dict)、window (int)。返り値: 公開時刻・足時刻・ERの辞書 (dict)。
    """
    assert isinstance(window, int) and window >= 1
    result = {}
    for key, ready in inputs.items():
        bars = HIERARCHY.LEGACY._bars(ready)
        close = pd.Series(np.asarray(bars['close'], float))
        travel = close.diff().abs().rolling(window, min_periods=window).sum()
        displacement = close.diff(window).abs()
        value = (displacement / travel.replace(0., np.nan)).to_numpy(float, copy=True)
        zero = travel.to_numpy(float) == 0.
        value[zero] = 0.
        published = np.asarray(bars['time_s'], float)
        result[key] = {'published': published + 60., 'foot_time': published - 120., 'er': value}
    return result


def _state_events(session: str, start: float, limit: float, observed: float, models: dict) -> list[dict]:
    """機能: 二市場のER同意を別足で2回確認し、欠測時は連続確認だけを解除する。

    引数: session (str)、start/limit/observed (float)、models (dict)。返り値: 全時計の判断ログ (list[dict])。
    """
    current, pending, streak = 1, 0, 0
    previous_feet = {symbol: None for symbol in SYMBOLS}
    events = [dict(session=session, timestamp=start, request=1, candidate=0, streak=0, reason='場初T', foot_time={}, er={})]
    for clock_id, stamp in enumerate(_clock(start, limit, observed), 1):
        feet, ratios, fresh = {}, {}, True
        for symbol in SYMBOLS:
            model = models[session, symbol]
            row = int(np.searchsorted(model['published'], stamp, side='right')) - 1
            foot = None if row < 0 else float(model['foot_time'][row])
            er = None if row < 0 or not np.isfinite(model['er'][row]) else float(model['er'][row])
            feet[symbol], ratios[symbol] = foot, er
            fresh &= foot is not None and (previous_feet[symbol] is None or foot > previous_feet[symbol])
        valid = all(ratios[symbol] is not None for symbol in SYMBOLS)
        candidate = 0
        reason = '中間又は両市場不一致'
        if not valid:
            reason = '足又はER履歴不足'
        elif not fresh:
            reason = '両市場の別公開足が揃わない'
        elif all(ratios[symbol] >= .35 for symbol in SYMBOLS):
            candidate, reason = 1, '両市場ER高位'
        elif all(ratios[symbol] <= .20 for symbol in SYMBOLS):
            candidate, reason = 2, '両市場ER低位'
        if candidate:
            streak = min(2, streak + 1) if candidate == pending else 1
            pending = candidate
            if streak >= 2:
                current = candidate
        else:
            pending, streak = 0, 0
        events.append(dict(session=session, timestamp=float(stamp), clock_index=clock_id, request=current,
                           candidate=candidate, streak=streak, reason=reason, foot_time=feet, er=ratios))
        previous_feet = feet
    return events


def build_state_requests(inputs: dict, window: int = 30) -> tuple[dict, list[dict]]:
    """機能: 損益を使わず、両市場のERからAの共通要求列を作る。

    引数: inputs (dict)、window (int)。返り値: 原本行要求と全時計ログ (tuple[dict,list[dict]])。
    """
    models = _er_models(inputs, window)
    output, logs = {}, []
    for session, start, limit, observed in _sessions(inputs):
        events = _state_events(session, start, limit, observed, models)
        logs.extend(events)
        output.update(_expand_requests(inputs, session, events))
    return output, logs


def reference_r(inputs: dict, session: str) -> dict | None:
    """機能: 影口座と無関係な開始20分後最初の有効ATRから共通基準Rを作る。

    引数: inputs (dict)、session (str)。返り値: 両市場のATR/R/参照行 (dict|None)。
    """
    output = {}
    for symbol in SYMBOLS:
        key = (session, symbol)
        if key not in inputs:
            return None
        ready = inputs[key]
        valid = (ready['time_s'] >= ready['start'] + 1200.) & (ready['time_s'] < ready['limit'])
        valid &= np.isfinite(ready['atr']) & (ready['atr'] > 0)
        rows = np.flatnonzero(valid)
        if not len(rows):
            return None
        row = int(rows[0])
        atr = float(ready['atr'][row])
        output[symbol] = dict(row=row, seq=int(ready['seq'][row]), timestamp=float(ready['time_s'][row]),
                              atr=atr, quantity=QUANTITY[symbol], multiplier=MULTIPLIER[symbol],
                              risk_yen=atr * QUANTITY[symbol] * MULTIPLIER[symbol])
    return output


def _shadow_index(shadow_rows: list[dict]) -> dict:
    """機能: 影口座の一意性と値を検査し、session・市場・枝で索引する。

    引数: shadow_rows (list[dict])。返り値: 行の辞書 (dict)。
    """
    output = {}
    for row in shadow_rows:
        key = (row['session'], row['symbol'], row['branch'])
        assert key not in output and row['symbol'] in SYMBOLS and row['branch'] in BRANCHES
        assert type(row['complete']) is bool
        assert np.isfinite(row['net_yen']) and np.isfinite(row['completed_at'])
        output[key] = row
    return output


def build_past_requests(inputs: dict, shadow_rows: list[dict], window: int = 6,
                        gap: float = .25) -> tuple[dict, list[dict]]:
    """機能: 当該区間を両市場とも除外し、過去完了区間の共通R成績だけでBを選ぶ。

    引数: inputs (dict)、shadow_rows (list[dict])、window (int)、gap (float)。
    返り値: 原本行要求と場初の判断ログ (tuple[dict,list[dict]])。
    """
    assert isinstance(window, int) and window > 0 and np.isfinite(gap) and gap >= 0
    sessions = _sessions(inputs)
    indexed = _shadow_index(shadow_rows)
    references = {session: reference_r(inputs, session) for session, *_ in sessions}
    current, output, logs = 1, {}, []
    for session, start, _, _ in sessions:
        eligible = []
        for old, old_start, _, _ in sessions:
            if old == session or old_start >= start or references[old] is None:
                continue
            rows = [indexed.get((old, symbol, branch)) for symbol in SYMBOLS for branch in BRANCHES]
            valid = all(row is not None and row['complete'] and row['completed_at'] <= start for row in rows)
            if valid:
                for symbol in SYMBOLS:
                    ready = inputs[old, symbol]
                    valid &= ready['time_s'][-1] > ready['limit']
                    for branch in BRANCHES:
                        row = indexed[old, symbol, branch]
                        valid &= ready['limit'] < row['completed_at'] <= ready['time_s'][-1]
            if valid:
                eligible.append(old)
        chosen = eligible[-window:]
        scores, means = {}, {}
        if len(chosen) < window:
            current, reason = 1, '必要な過去完了区間不足でT'
        else:
            for branch in BRANCHES:
                means[branch] = {symbol: float(np.mean([np.clip(indexed[old, symbol, branch]['net_yen'] /
                    references[old][symbol]['risk_yen'], -3., 3.) for old in chosen])) for symbol in SYMBOLS}
                scores[branch] = min(means[branch].values())
            own, other = BRANCHES[current - 1], BRANCHES[2 - current]
            if scores[other] > scores[own] + gap:
                current, reason = 3 - current, '別枝が現枝を固定差より大きく上回る'
            else:
                reason = '同点又は差不足で維持'
        event = dict(session=session, timestamp=start, request=current, eligible_sessions=eligible,
                     training_sessions=chosen, scores=scores, symbol_means=means, reason=reason,
                     reference_r={old: references[old] for old in chosen}, window=window, gap=gap)
        logs.append(event)
        output.update(_expand_requests(inputs, session, [event]))
    return output, logs


def _coin(mode: str, seed: int, session: str, clock_index: int | None = None) -> int:
    """機能: セッション共通・末尾長非依存の公平二択を固定文字列から作る。

    引数: mode/session (str)、seed (int)、clock_index (int|None)。返り値: T=1又はR=2 (int)。
    """
    text = f'v32-selector-{mode}|{seed}|{session}'
    if clock_index is not None:
        text += f'|{clock_index}'
    return 1 + (int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], 'little') & 1)


def random_requests(inputs: dict, mode: str, seed: int) -> tuple[dict, list[dict]]:
    """機能: 相場状態や将来切替頻度を渡さず、要求IDだけを固定64seedで無作為化する。

    引数: inputs (dict)、mode (str) はA/B、seed (int) は0..63。
    返り値: 両市場共通要求と時計ログ (tuple[dict,list[dict]])。
    """
    assert mode in ('A', 'B') and isinstance(seed, int) and 0 <= seed < 64
    sessions = _sessions(inputs)
    output, logs = {}, []
    for session, start, limit, observed in sessions:
        if mode == 'A':
            current, pending, streak = 1, 0, 0
            events = [dict(session=session, timestamp=start, request=1, candidate=0, streak=0, reason='場初T')]
            for k, stamp in enumerate(_clock(start, limit, observed), 1):
                candidate = _coin(mode, seed, session, k)
                streak = min(2, streak + 1) if candidate == pending else 1
                pending = candidate
                if streak >= 2:
                    current = candidate
                events.append(dict(session=session, timestamp=float(stamp), request=current, candidate=candidate,
                                   streak=streak, clock_index=k, reason='固定時計の公平二択'))
        else:
            completed = [old for old, old_start, _, _ in sessions if old_start < start and all(
                inputs[old, symbol]['limit'] < inputs[old, symbol]['time_s'][-1] <= start for symbol in SYMBOLS)]
            current = 1 if len(completed) < 6 else _coin(mode, seed, session)
            events = [dict(session=session, timestamp=start, request=current, completed_sessions=completed,
                           reason='初6完了区間はT' if len(completed) < 6 else '場初の公平二択')]
        output.update(_expand_requests(inputs, session, events))
        logs.extend(events)
    return output, logs


def delay_columns(inputs: dict, columns: dict, seconds: float, initial: int = 0) -> dict:
    """機能: 入口又は要求を同セッション過去原本行へ遅延させ、同時刻の先取りを防ぐ。

    引数: inputs/columns (dict)、seconds (float)、initial (int)。
    返り値: 遅延列 (dict)。0秒はidentity、入口先頭0・要求先頭1を呼出側が明示する。
    """
    assert np.isfinite(seconds) and seconds >= 0 and initial in (0, 1)
    assert set(columns) == set(inputs)
    output = {}
    for key, ready in inputs.items():
        values, times = columns[key], ready['time_s']
        assert len(values) == len(times) and values.dtype == np.int8
        assert np.all(np.diff(times) >= 0)
        if seconds == 0:
            output[key] = values.copy()
            continue
        indices = np.searchsorted(times, times - seconds, side='right') - 1
        valid = indices >= 0
        assert np.all(indices[valid] < np.flatnonzero(valid))
        result = np.full(len(times), initial, np.int8)
        result[valid] = values[indices[valid]]
        output[key] = result
    return output
