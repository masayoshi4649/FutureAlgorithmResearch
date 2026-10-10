"""主方向を維持し、反対の根拠を連続確認した場合だけ切り替える三つの因果的状態。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SYMBOLS = ['NK225', 'TOPIX']
STATE_NAMES = {'M1': '確定足の持続方向', 'M2': '板注文フローと価格の一致', 'M3': '両銘柄の持続方向一致'}
FEATURE_COLUMNS = ['time_s', 'seq', 'source_time_s', 'source_first_seq', 'source_last_seq',
                   'source_mid_last', 'ofi_signed', 'ofi_abs']


def descriptions() -> dict[str, str]:
    """機能: 損益を見る前に固定する主方向の定義を返す。

    引数: なし。返り値: 系統別の日本語説明 (dict[str, str])。
    """
    return {
        'M1': '確定１分足のEMA8−EMA30が±0.15ATR以上、EMA30の３本変化が同方向0.03ATR以上。２本連続で一致すると主方向を設定・反転する。弱まるだけなら従来の主方向を維持する。足開始＋120秒で解放。',
        'M2': '解放済み板の過去300秒OFI合計／絶対OFI合計が±0.05以上、同じ５分の中値変化が同方向0.3ATR以上。１分ごとの２回確認で主方向を設定・反転する。弱まるだけなら従来の主方向を維持する。',
        'M3': '自銘柄M1と60秒遅らせた相手銘柄M1が同方向。１分ごとの２回確認で主方向を設定・反転する。一時的な不一致では従来の主方向を維持する。',
    }


def load_inputs() -> dict:
    """機能: 前作業の保存済み入力20セルを読取専用で読み込む。

    引数: なし。返り値: (セッション, 銘柄) をキーとする入力 (dict)。通信・旧成果への書込は行わない。
    """
    result = {}
    for name in ['development', 'holdout']:
        with (ROOT / 'work/wave_v16' / f'入力_{name}.pkl').open('rb') as stream:
            loaded = pickle.load(stream)
        assert not set(result).intersection(loaded)
        result.update(loaded)
    assert len(result) == 20
    return result


def feature_path(session: str, symbol: str) -> Path:
    """機能: 完全原本から抽出された板特徴の保存先を決める。

    引数: session/symbol (str)。返り値: 読取対象CSV (Path)。
    """
    folder = 'wave_v16' if session >= '2026-09-24_Night' else 'wave_v13'
    path = ROOT / 'work' / folder / 'features' / f'{symbol}_{session}.csv'
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def read_features(ready: dict) -> pd.DataFrame:
    """機能: 入力末尾までに解放された板特徴だけを返す。

    引数: ready (dict)。返り値: 原本順の特徴表 (DataFrame)。
    """
    frame = pd.read_csv(feature_path(ready['session'], ready['symbol']), usecols=FEATURE_COLUMNS)
    return frame.loc[(frame.seq <= ready['seq'][-1]) & (frame.time_s <= ready['time_s'][-1])].copy()


def confirmed_states(candidates: np.ndarray, times: np.ndarray, confirmations: int = 2) -> np.ndarray:
    """機能: 異なる連続する観測で確認した方向だけを採用し、弱化時は主方向を維持する。

    引数: candidates (ndarray)、times (ndarray)、confirmations (int)。返り値: -1/0/+1 の状態列 (ndarray)。
    """
    states = np.zeros(len(candidates), dtype=np.int8)
    state, pending, count, last_time = 0, 0, 0, -np.inf
    for i, (candidate, stamp) in enumerate(zip(candidates, times)):
        candidate = int(candidate)
        if stamp - last_time > 90:
            pending, count = 0, 0
        if candidate == 0:
            pending, count = 0, 0
        elif candidate == pending:
            count += 1
        else:
            pending, count = candidate, 1
        if count >= confirmations:
            state = pending
        states[i], last_time = state, float(stamp)
    return states


def expand_states(event_times: np.ndarray, event_states: np.ndarray, target_times: np.ndarray) -> np.ndarray:
    """機能: 各時点で最後に公開済みの状態を過去方向の対応だけで配列化する。

    引数: event_times/event_states/target_times (ndarray)。返り値: target_times と同じ長さの状態列 (ndarray)。
    """
    result = np.zeros(len(target_times), dtype=np.int8)
    positions = np.searchsorted(event_times, target_times, side='right') - 1
    valid = positions >= 0
    result[valid] = event_states[positions[valid]]
    return result


def minute_model(ready: dict) -> dict:
    """機能: 未来の足を除いてからEMAを最初から計算し、主方向M1を返す。

    引数: ready (dict)。返り値: 公開時刻・状態・指標を持つ辞書 (dict)。
    """
    frame = pd.read_csv(ROOT / 'candle_1min' / ready['symbol'] / f"{ready['session']}.csv")
    available = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120.
    valid = frame.closed.astype(str).str.lower().eq('true').to_numpy() & (available <= ready['time_s'][-1])
    valid &= available >= ready['start'] + 120.
    frame, available = frame.loc[valid].copy(), available[valid]
    assert np.all(np.diff(available) > 0)
    close = frame.close.astype(float).reset_index(drop=True)
    fast = close.ewm(span=8, adjust=False, min_periods=8).mean()
    slow = close.ewm(span=30, adjust=False, min_periods=30).mean()
    positions = np.searchsorted(ready['time_s'], available, side='right') - 1
    atr = np.full(len(frame), np.nan)
    have = positions >= 0
    atr[have] = ready['atr'][positions[have]]
    gap = (fast - slow).to_numpy(float) / atr
    slope = slow.diff(3).to_numpy(float) / atr
    candidates = np.zeros(len(frame), dtype=np.int8)
    candidates[(gap >= .15) & (slope >= .03)] = 1
    candidates[(gap <= -.15) & (slope <= -.03)] = -1
    candidates[available < ready['start'] + 20 * 60] = 0
    states = confirmed_states(candidates, available)
    return dict(time_s=available, states=states, candidates=candidates, gap=gap, slope=slope)


def minute_checks(ready: dict) -> np.ndarray:
    """機能: セッション開始20分後から各分の最初の有効原本行を選ぶ。

    引数: ready (dict)。返り値: 原本入力配列内の行位置 (ndarray)。
    """
    targets = np.arange(ready['start'] + 20 * 60, ready['time_s'][-1] + 1e-8, 60.)
    positions = np.searchsorted(ready['time_s'], targets, side='left')
    return np.unique(positions[positions < len(ready['time_s'])])


def board_model(ready: dict, features: pd.DataFrame | None = None) -> dict:
    """機能: 公開済み板だけでOFIと中値の５分方向を求め、１分ごとにM2を更新する。

    引数: ready (dict)、features (DataFrame|None) は途中打切り監査用の再抽出特徴。
    返り値: 原本行位置・状態・根拠を持つ辞書 (dict)。
    """
    frame = read_features(ready) if features is None else features[FEATURE_COLUMNS].copy()
    frame = frame.loc[(frame.seq <= ready['seq'][-1]) & (frame.time_s <= ready['time_s'][-1])].reset_index(drop=True)
    if len(frame):
        assert np.all(frame.source_last_seq.to_numpy() < frame.seq.to_numpy())
        assert np.all(frame.source_time_s.to_numpy() < frame.time_s.to_numpy())
        assert np.all(np.diff(frame.seq.to_numpy()) > 0)
        assert np.all(np.diff(frame.time_s.to_numpy()) > 0)
    indices = minute_checks(ready)
    times = ready['time_s'][indices]
    candidates = np.zeros(len(indices), dtype=np.int8)
    flow, movement = np.full(len(indices), np.nan), np.full(len(indices), np.nan)
    release_seq = frame.seq.to_numpy(np.int64)
    release_times = frame.time_s.to_numpy(float)
    pick = np.searchsorted(release_seq, ready['seq'][indices], side='right') - 1
    signed = np.r_[0., np.cumsum(frame.ofi_signed.to_numpy(float))]
    absolute = np.r_[0., np.cumsum(frame.ofi_abs.to_numpy(float))]
    mid = frame.source_mid_last.to_numpy(float)
    for j, k in enumerate(pick):
        if k < 0 or times[j] - release_times[k] > 60:
            continue
        assert release_times[k] <= times[j]
        past = int(np.searchsorted(release_times, release_times[k] - 300., side='right')) - 1
        if past < 0:
            continue
        denominator = absolute[k + 1] - absolute[past + 1]
        if denominator <= 0 or not np.isfinite(ready['atr'][indices[j]]):
            continue
        flow[j] = (signed[k + 1] - signed[past + 1]) / denominator
        movement[j] = (mid[k] - mid[past]) / ready['atr'][indices[j]]
        if flow[j] >= .05 and movement[j] >= .3:
            candidates[j] = 1
        elif flow[j] <= -.05 and movement[j] <= -.3:
            candidates[j] = -1
    states = confirmed_states(candidates, times)
    return dict(indices=indices, time_s=times, states=states, candidates=candidates,
                flow=flow, movement=movement, source_feature_positions=pick)


def build_states(ready: dict, peer_ready: dict, features: pd.DataFrame | None = None) -> dict[str, np.ndarray]:
    """機能: 同一セッションの保存データから三系統の主方向を原本各行へ対応する。

    引数: ready/peer_ready (dict)、features (DataFrame|None)。返り値: M1/M2/M3 の状態配列 (dict[str, ndarray])。
    注意: 現在行で状態を更新する。これを用いた新注文は呼出側で必ず次行以降に有効とする。
    """
    if ready['session'] != peer_ready['session'] or ready['symbol'] == peer_ready['symbol']:
        raise ValueError('同一セッションの異なる２銘柄が必要です')
    own = minute_model(ready)
    peer = minute_model(peer_ready)
    board = board_model(ready, features)
    result = dict(M1=expand_states(own['time_s'], own['states'], ready['time_s']))
    board_dense = np.zeros(len(ready['seq']), dtype=np.int8)
    event_number = np.searchsorted(board['indices'], np.arange(len(ready['seq'])), side='right') - 1
    valid = event_number >= 0
    board_dense[valid] = board['states'][event_number[valid]]
    result['M2'] = board_dense
    # ----------------------------------------
    # 他銘柄は完全な現セッション末尾に依存せず、各自時点より60秒古い公開状態だけ参照する。
    checks = minute_checks(ready)
    check_times = ready['time_s'][checks]
    peer_values = expand_states(peer['time_s'] + 60., peer['states'], check_times)
    own_values = result['M1'][checks]
    agree = np.where((own_values == peer_values) & (own_values != 0), own_values, 0).astype(np.int8)
    states = confirmed_states(agree, check_times)
    dense = np.zeros(len(ready['seq']), dtype=np.int8)
    event_number = np.searchsorted(checks, np.arange(len(ready['seq'])), side='right') - 1
    valid = event_number >= 0
    dense[valid] = states[event_number[valid]]
    result['M3'] = dense
    assert all(len(value) == len(ready['seq']) and np.isin(value, [-1, 0, 1]).all() for value in result.values())
    return result


def truncate_input(ready: dict, cutoff: float, inclusive_rows: int | None = None) -> dict:
    """機能: 未来行を物理的に除いた入力コピーを作る。

    引数: ready (dict)、cutoff (float)、inclusive_rows (int|None)。返り値: 切断済み入力 (dict)。
    """
    count = int(np.searchsorted(ready['time_s'], cutoff, side='right')) if inclusive_rows is None else inclusive_rows
    if count < 1:
        raise ValueError('切断後の原本が空です')
    return {key: value[:count].copy() if isinstance(value, np.ndarray) and len(value) == len(ready['seq']) else value
            for key, value in ready.items() if key != 'families'}


def digest(path: Path) -> str:
    """機能: 読取対象の固定ハッシュを計算する。

    引数: path (Path)。返り値: SHA256文字列 (str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            result.update(chunk)
    return result.hexdigest()


def run_audit(raw_audit: bool = False) -> dict:
    """機能: 20セルの状態を保存し、各入力を途中で切って最初から再計算して一致を監査する。

    引数: raw_audit (bool) は原本JSONLからの板特徴再抽出も行う指定。返り値: 監査記録 (dict)。
    """
    inputs, states, records, feature_records = load_inputs(), {}, [], []
    inventory = json.loads((ROOT / 'work/wave_v16/データ棚卸し.json').read_text(encoding='utf-8'))
    raw_hashes = {(row['セッション'], row['銘柄']): row['生板']['SHA256'] for row in inventory['原本']}
    for key, ready in inputs.items():
        peer = inputs[(key[0], SYMBOLS[1 - SYMBOLS.index(key[1])])]
        states[key] = build_states(ready, peer)
        assert all(np.count_nonzero(value) > 0 for value in states[key].values()), f'全中立の系統があります: {key}'
        feature = read_features(ready)
        source_path = feature_path(*key)
        source_audit = json.loads(source_path.with_name(source_path.stem + '_audit.json').read_text(encoding='utf-8'))
        assert source_audit['原本SHA256'] == raw_hashes[key]
        assert source_audit['特徴CSV_SHA256'] == digest(source_path)
        feature_records.append(dict(セッション=key[0], 銘柄=key[1], 特徴CSV=str(source_path.relative_to(ROOT)),
                                    特徴SHA256=digest(source_path), 特徴行数=len(feature),
                                    原本ハッシュは週データと一致=True, 特徴CSVハッシュ一致=True,
                                    参照原本行は解放行より過去=bool((feature.source_last_seq < feature.seq).all()),
                                    参照時刻は解放時刻より過去=bool((feature.source_time_s < feature.time_s).all())))
        for elapsed in [65 * 60 + 17, 125 * 60 + 31, 245 * 60 + 11]:
            cutoff = ready['start'] + elapsed
            own_cut, peer_cut = truncate_input(ready, cutoff), truncate_input(peer, cutoff)
            partial = build_states(own_cut, peer_cut)
            matches = {method: bool(np.array_equal(value, states[key][method][:len(own_cut['seq'])])) for method, value in partial.items()}
            assert all(matches.values()), (key, cutoff, matches)
            records.append(dict(セッション=key[0], 銘柄=key[1], 開始後秒=elapsed, 原本行数=len(own_cut['seq']), 全状態一致=matches))
    # ----------------------------------------
    # 単なる生成済み状態の切断ではなく、原本JSONLの先頭だけから板特徴も再抽出する。
    raw_records = []
    if raw_audit:
        source = ROOT / 'work/wave_v8/raw_features.py'
        spec = importlib.util.spec_from_file_location('v17_signal_raw_features', source)
        extractor = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = extractor
        spec.loader.exec_module(extractor)
        for session in ['2026-09-21_Day', '2026-09-24_Night', '2026-09-25_Night']:
            for symbol in SYMBOLS:
                ready = inputs[(session, symbol)]
                peer = inputs[(session, SYMBOLS[1 - SYMBOLS.index(symbol)])]
                count = int(np.searchsorted(ready['time_s'], ready['start'] + 125 * 60 + 31, side='right'))
                own_cut = truncate_input(ready, 0, count)
                peer_cut = truncate_input(peer, own_cut['time_s'][-1])
                feature, audit = extractor.extract_features(ROOT / 'book' / symbol / f'{session}.jsonl', symbol, session,
                                                            max_rows=int(own_cut['seq'][-1]) + 1)
                expected = read_features(own_cut)
                pd.testing.assert_frame_equal(expected[FEATURE_COLUMNS].reset_index(drop=True), feature[FEATURE_COLUMNS].reset_index(drop=True),
                                              check_dtype=False, check_exact=False, rtol=1e-12, atol=1e-10)
                partial = build_states(own_cut, peer_cut, features=feature)
                matches = {method: bool(np.array_equal(value, states[(session, symbol)][method][:count])) for method, value in partial.items()}
                assert all(matches.values())
                raw_records.append(dict(セッション=session, 銘柄=symbol, 読取原本行数=audit['読取行数'], 原本有効行数=count,
                                        再生成特徴行数=len(feature), 特徴全列一致=True, 全状態一致=matches))
                print(json.dumps(raw_records[-1], ensure_ascii=False), flush=True)
    result = dict(合格=True, API取得数=0, 既知データのみ=True, 条件定義=descriptions(),
                  系統数=3, 入力セル数=len(inputs), 入力原本有効行数=sum(len(value['seq']) for value in inputs.values()),
                  未来打切りケース数=len(records), 未来打切り一致状態値数=sum(row['原本行数'] * 3 for row in records),
                  原本再抽出ケース数=len(raw_records), 原本再抽出=raw_records, 未来打切り=records, 特徴公開順監査=feature_records,
                  注文タイミング='状態は現行の観測後に更新。新注文は次の原本行以降のみ有効。',
                  時刻の限界='受信時刻がなくCurrentPriceTimeを時刻の代理にする。板は同時刻ブロックを次時刻まで封印し、他銘柄はさらに60秒遅延。',
                  入力SHA256={name: digest(ROOT / 'work/wave_v16' / name) for name in ['入力_development.pkl', '入力_holdout.pkl']},
                  状態集計=[dict(セッション=key[0], 銘柄=key[1], 系統=method, 状態変更数=int(np.count_nonzero(np.diff(value))),
                                正方向行数=int(np.count_nonzero(value == 1)), 負方向行数=int(np.count_nonzero(value == -1)))
                            for key, item in states.items() for method, value in item.items()])
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / '主方向状態.pkl').open('wb') as stream:
        pickle.dump(states, stream, protocol=pickle.HIGHEST_PROTOCOL)
    (OUT / '主方向信号の因果性監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# 主方向信号の定義と因果性監査', '', '保存データのみ。新たなAPI取得なし。３候補の閾値は損益計算前に固定。', '']
    lines.extend(f'- **{key} {STATE_NAMES[key]}**：{text}' for key, text in descriptions().items())
    lines.extend(['', '方向が弱くなっただけでは中立・反転させない。２回連続の反対根拠で主方向を反転する。建玉の停止・カバー・反転は別の注文器で管理する。',
                  '', f'20セルを各３時点で途中打切りし、足指標・板集計・主方向を最初から再生成した{len(records)}ケースが全一致。',
                  f'このうち別途{len(raw_records)}ケースは原本JSONLを途中打切りして板特徴から再抽出し、状態も全一致。',
                  '', '板の特徴解放行 seq より source_last_seq は厳密に小さい。主方向とATRを使った注文は次行以降に有効とする。',
                  '', '受信時刻がないため CurrentPriceTime を代理時刻に使用。保存データの再現性監査であり、実配信の遅延・順序まで保証するものではない。'])
    (OUT / '主方向信号の説明.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='主方向信号を生成して途中打切りを監査する')
    parser.add_argument('--raw-audit', action='store_true')
    result = run_audit(parser.parse_args().raw_audit)
    print(json.dumps({key: value for key, value in result.items() if key not in ['原本再抽出', '未来打切り', '特徴公開順監査', '状態集計']}, ensure_ascii=False), flush=True)
