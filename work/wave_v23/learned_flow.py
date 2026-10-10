"""過去セッションだけで板と価格反応の関係を学習する、小規模な線形予測対照。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
NAMES = []


def catalog() -> list[dict]:
    """機能: 事前固定する２予測時間と２新規閾値を返す。

    引数: なし。返り値: 候補一覧 (list[dict])。
    """
    return [dict(id=f'L{i:02d}', name=f'板から{h}分先を過去学習・閾値{threshold}', family='過去だけで学習する板予測',
                 description='過去の完了セッションだけで板フローと価格反応を線形学習。現在セッションの将来ラベルを使わない。',
                 params=dict(horizon=h, threshold=threshold, ridge=10.0, min_sessions=2))
            for i, (h, threshold) in enumerate([(5, .15), (5, .35), (15, .15), (15, .35)])]


def events(ready: dict, frame: pd.DataFrame) -> dict:
    """機能: 解放済み板だけから１分ごとの方向性特徴を生成する。

    引数: ready (dict)、frame (DataFrame)。返り値: 行位置・特徴行列等 (dict)。
    """
    global NAMES
    times = ready['time_s']
    # 毎分境界の観測を末尾にしても、全長再生と同じイベントをその行で確定する。
    indices = np.searchsorted(times, np.arange(ready['start'] + 1200, times[-1] + 60, 60), side='left')
    indices = np.unique(indices[indices < len(times)])
    frame = frame.loc[(frame.seq <= ready['seq'][-1]) & (frame.time_s <= times[-1])].copy()
    frame.index = pd.to_datetime(frame.time_s, unit='s')
    columns, names = [], []
    selected = np.searchsorted(frame.seq.to_numpy(), ready['seq'][indices], side='right') - 1
    valid = selected >= 0
    for seconds in [60, 300, 900]:
        sums = frame[['ofi_signed', 'ofi_abs', 'trade_pos', 'trade_neg', 'added_bid', 'removed_bid', 'added_ask', 'removed_ask']].rolling(f'{seconds}s').sum()
        signed = [sums.ofi_signed / (sums.ofi_abs + 1),
                  (sums.trade_pos - sums.trade_neg) / (sums.trade_pos + sums.trade_neg + 1),
                  (sums.added_bid - sums.removed_bid - sums.added_ask + sums.removed_ask) / (sums.added_bid + sums.removed_bid + sums.added_ask + sums.removed_ask + 1)]
        for name, series in zip(['注文フロー', '推定約定方向', '補充差'], signed):
            value = np.zeros(len(indices))
            value[valid] = series.to_numpy()[selected[valid]]
            columns.append(value)
            names.append(f'{seconds}秒{name}')
        lag = np.searchsorted(times, times[indices] - seconds, side='right') - 1
        move = (ready['last'][indices] - ready['last'][np.maximum(lag, 0)]) / ready['atr'][indices]
        columns += [move, np.asarray(columns[-3]) - np.tanh(move)]
        names += [f'{seconds}秒価格変化', f'{seconds}秒フローに対する価格反応差']
    for name in ['imb1', 'imb5', 'imb10', 'micro_bias', 'pressure_near', 'pressure_far', 'dflow_near', 'dflow_far']:
        if name not in frame:
            continue
        values = frame[name].rolling('60s').mean().to_numpy()
        value = np.zeros(len(indices))
        value[valid] = values[selected[valid]]
        columns.append(value)
        names.append(name)
    if 'refill_bid' in frame:
        values = (frame.refill_bid - frame.refill_ask).rolling('60s').sum() / ((frame.refill_bid + frame.refill_ask).rolling('60s').sum() + 1)
        value = np.zeros(len(indices))
        value[valid] = values.to_numpy()[selected[valid]]
        columns.append(value)
        names.append('同価格補充差')
    matrix = np.nan_to_num(np.column_stack(columns), nan=0.0, posinf=0.0, neginf=0.0)
    NAMES = names
    return dict(indices=indices, time_s=times[indices], X=np.clip(matrix, -8, 8), price=ready['last'][indices], atr=ready['atr'][indices])


def build_all(inputs: dict, features: dict) -> tuple[list[dict], dict]:
    """機能: ２セッション以上の過去だけで回帰し、その次のセッションを予測する。

    引数: inputs/features (dict)。返り値: 候補一覧と原本行方向列 (tuple[list,dict])。
    """
    sessions = sorted({key[0] for key in inputs})
    data = {key: events(ready, features[key]) for key, ready in inputs.items()}
    base_names = list(NAMES)
    own_matrices = {key: value['X'].copy() for key, value in data.items()}
    for key, value in data.items():
        peer_key = (key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225')
        peer = data[peer_key]
        lookup = np.searchsorted(peer['time_s'] + 60, value['time_s'], side='right') - 1
        other = np.zeros_like(value['X'])
        valid = lookup >= 0
        other[valid] = own_matrices[peer_key][lookup[valid]]
        value['X'] = np.column_stack([value['X'], other])
    result, audit = {}, []
    for spec in catalog():
        by_key = {}
        horizon = spec['params']['horizon'] * 60
        past_x, past_y = [], []
        for i, session in enumerate(sessions):
            weights, scale = None, None
            if i >= 2:
                x, y = np.concatenate(past_x), np.concatenate(past_y)
                scale = np.maximum(np.sqrt(np.mean(x * x, axis=0)), .03)
                z = np.clip(x / scale, -8, 8)
                weights = np.linalg.solve(z.T @ z + np.eye(z.shape[1]) * spec['params']['ridge'], z.T @ y)
                audit.append(dict(id=spec['id'], 適用セッション=session, 学習末尾=sessions[i - 1], 学習行数=len(y),
                                  係数=weights.tolist(), 特徴名=base_names + ['相手60秒遅延_' + n for n in base_names]))
            for symbol in ['TOPIX', 'NK225']:
                key = (session, symbol)
                ready, value = inputs[key], data[key]
                predictions = np.zeros(len(value['X'])) if weights is None else np.clip(value['X'] / scale, -8, 8) @ weights
                candidates = np.where(predictions >= spec['params']['threshold'], 1, np.where(predictions <= -spec['params']['threshold'], -1, 0)).astype(np.int8)
                confirmed = np.zeros_like(candidates)
                confirmed[1:] = np.where(candidates[1:] == candidates[:-1], candidates[1:], 0)
                picks = np.searchsorted(value['indices'], np.arange(len(ready['time_s'])), side='right') - 1
                dense = np.zeros(len(picks), dtype=np.int8)
                valid = picks >= 0
                dense[valid] = confirmed[picks[valid]]
                by_key[key] = dense
                # ----------------------------------------
                # このセッションのラベルは予測後に追加し、次セッション以降にしか使わない。
                future = np.searchsorted(ready['time_s'], value['time_s'] + horizon, side='left')
                valid_y = (future < len(ready['time_s'])) & np.isfinite(value['atr']) & (value['atr'] > 0)
                labels = (ready['last'][future[valid_y]] - value['price'][valid_y]) / value['atr'][valid_y]
                past_x.append(value['X'][valid_y])
                past_y.append(np.clip(labels, -8, 8))
            # 同一セッションの相手銘柄ラベルが予測に混入しないよう、係数は上の外側でのみ更新する。
        result[spec['id']] = by_key
    (OUT / '学習の時系列記録.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    return catalog(), result
