"""過去完了セッションだけから、公開区間の板圧力を推定する。売買は行わない。"""

from __future__ import annotations

import hashlib
import json

import numpy as np

import release_minutes


RIDGE_ALPHA = 0.01
COMMON_LAG = 6
MIN_HISTORY = 2
MIN_TRAIN_ROWS = 40
RMS_FLOOR = 1e-6


def specification() -> dict:
    """機能: 成績から調整しない学習仕様を返す。

    引数: なし。返り値: 固定された学習・評価仕様 (dict)。
    """
    return dict(lags=[1, 3, 6], common_lag=COMMON_LAG, alpha=RIDGE_ALPHA,
        min_history=MIN_HISTORY, min_train_rows=MIN_TRAIN_ROWS, rms_floor=RMS_FLOOR,
        objective='mean((y-intercept-X_standardized@coef)^2)+0.01*sum(coef^2)',
        intercept_penalized=False, standard_deviation_ddof=0,
        zero_standard_deviation_replacement=1., target='公開区間の規格化OFIの符号付きlog1p',
        raw_ofi_scale='同じ規格化OFIの訓練RMS。予測成分を除かない尺度であり、原枚数ではない',
        residual_scale='同じ過去学習標本に当てはめた残差RMS。未学習誤差の推定値とは呼ばない')


def matrix(events: dict, lag: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """機能: 比較する全ラグで最大6区間の共通有効行を用いる。

    引数: events (dict[str, ndarray])、lag (int: 1/3/6)。
    返り値: 説明行列・現在OFI・共通マスク (tuple[ndarray, ndarray, ndarray])。
    元イベントを削除してからラグを作ることはない。
    """
    if lag not in (1, 3, 6):
        raise ValueError('lagは1/3/6だけを許可する')
    x, y, own = release_minutes.model_rows(events, lag)
    _, _, common = release_minutes.model_rows(events, COMMON_LAG)
    assert np.all(~common | own), '共通有効集合が個別有効集合の部分集合ではない'
    assert np.isfinite(x[common]).all() and np.isfinite(y[common]).all()
    return x, y, common.copy()


def fit(x: np.ndarray, y: np.ndarray) -> dict:
    """機能: 訓練内だけで標準化・ridge係数・過去RMSを求める。

    引数: x (2次元ndarray)、y (1次元ndarray)。最低40の有限標本を要求する。
    返り値: 標準化値・係数・切片・尺度 (dict)。切片は罰則に含めない。
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.ndim != 2 or y.ndim != 1 or len(x) != len(y) or len(y) < MIN_TRAIN_ROWS:
        raise ValueError('有限の対応行列と最低40標本が必要')
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('訓練に非有限値が含まれている')
    mean = np.mean(x, axis=0)
    standard = np.std(x, axis=0, ddof=0)
    standard = np.where(standard > 0, standard, 1.)
    z = (x - mean) / standard
    intercept = float(np.mean(y))
    coefficients = np.linalg.solve(z.T @ z / len(y) + RIDGE_ALPHA*np.eye(x.shape[1]),
        z.T @ (y - intercept) / len(y))
    residual = y - (intercept + z @ coefficients)
    return dict(mean=mean.tolist(), standard=standard.tolist(),
        coefficients=coefficients.tolist(), intercept=intercept, training_rows=len(y),
        residual_rms=max(RMS_FLOOR, float(np.sqrt(np.mean(residual**2)))),
        raw_ofi_rms=max(RMS_FLOOR, float(np.sqrt(np.mean(y**2)))))


def predict(model: dict, x: np.ndarray) -> np.ndarray:
    """機能: セッション開始前に固定した係数で公開区間のOFIを推定する。

    引数: model (dict)、x (2次元ndarray)。返り値: OFI推定配列 (ndarray)。
    """
    return model['intercept'] + ((np.asarray(x, float)-np.asarray(model['mean'])) /
        np.asarray(model['standard'])) @ np.asarray(model['coefficients'])


def _fingerprint(model: dict) -> str:
    """機能: 学習履歴と係数の内容指紋を作る。

    引数: model (dict)。返り値: SHA256 (str)。現在区間の将来分布は含めない。
    """
    payload = json.dumps(model, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def build(events_by_key: dict, inputs: dict, lag: int = 3) -> tuple[dict, dict]:
    """機能: 銘柄別に過去完了セッションだけを学習し、各区間の推定を返す。

    引数: events_by_key/inputs (dict[(session, symbol), dict])、lag (int: 1/3/6)。
    返り値: 公開イベント別推定と、対象セッション別学習履歴 (tuple[dict, dict])。
    最初の2完了セッション又は40標本に満たない場合、予測値は欠測のまま。
    """
    if set(events_by_key) != set(inputs):
        raise ValueError('入力と公開イベントのキー集合が異なる')
    prepared = {key: matrix(events, lag) for key, events in events_by_key.items()}
    outputs, models = {}, {}
    ordered = sorted(inputs, key=lambda key: (float(inputs[key]['start']), key))
    for key in ordered:
        session, symbol = key
        ready, events = inputs[key], events_by_key[key]
        start = float(ready['start'])
        x, observed, common = prepared[key]
        assert len(observed) == len(events['time_s'])
        assert np.all(np.asarray(events['seq']) <= np.asarray(ready['seq'])[-1])
        history = [old for old in ordered if old[1] == symbol and old != key
            and float(inputs[old]['start']) < start
            and float(inputs[old]['time_s'][-1]) > float(inputs[old]['limit'])
            and float(inputs[old]['time_s'][-1]) < start]
        records = []
        train_x, train_y = [], []
        for old in history:
            old_x, old_y, old_mask = prepared[old]
            train_x.append(old_x[old_mask]); train_y.append(old_y[old_mask])
            old_events = events_by_key[old]
            assert np.all(np.asarray(old_events['time_s'])[old_mask] < start)
            assert np.all(np.asarray(old_events['seq']) <= np.asarray(inputs[old]['seq'])[-1])
            records.append(dict(session=old[0], symbol=old[1],
                completed_at=float(inputs[old]['time_s'][-1]),
                training_rows=int(np.sum(old_mask)),
                last_training_release_time=(float(np.asarray(old_events['time_s'])[old_mask][-1])
                    if np.any(old_mask) else None),
                last_training_release_seq=(int(np.asarray(old_events['seq'])[old_mask][-1])
                    if np.any(old_mask) else None)))
        count = sum(item['training_rows'] for item in records)
        available = len(history) >= MIN_HISTORY and count >= MIN_TRAIN_ROWS
        model = dict(session=session, symbol=symbol, lag=lag, common_lag=COMMON_LAG,
            training_cutoff=start, available=available, training_sessions=records,
            training_rows=count, specification=specification(),
            unavailable_reason=('' if available else '過去完了セッション2未満' if len(history) < MIN_HISTORY
                else '共通有効訓練標本40未満'))
        estimated = np.full(len(observed), np.nan)
        residual = np.full(len(observed), np.nan)
        residual_rms = np.full(len(observed), np.nan)
        raw_ofi_rms = np.full(len(observed), np.nan)
        if available:
            model.update(fit(np.concatenate(train_x), np.concatenate(train_y)))
            estimated[common] = predict(model, x[common])
            residual[common] = observed[common] - estimated[common]
            residual_rms[:] = model['residual_rms']
            raw_ofi_rms[:] = model['raw_ofi_rms']
        model['model_sha256'] = _fingerprint(model)
        models[key] = model
        outputs[key] = dict(indices=np.asarray(events['indices']).copy(),
            seq=np.asarray(events['seq']).copy(), time_s=np.asarray(events['time_s']).copy(),
            minute=np.asarray(events['minute']).copy(), observed=observed.copy(),
            prediction=estimated, residual=residual, residual_rms=residual_rms,
            raw_ofi_rms=raw_ofi_rms, common_valid=common,
            forecast_valid=common & available)
    return outputs, models
