"""公開済みの確定足と板から、追従・反復・中立を因果的に区分する。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pickle

import numpy as np
import pandas as pd
from numba import njit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIELDS = ('mode', 'trend', 'range_side', 'book_score', 'book_valid', 'absorb_side',
          'support20', 'resistance20', 'center20')
DEFINITION = {
    '版': 2,
    '追加理由': '損益評価前のユーザー追加指定により当セッション内の支持抵抗20実分を追加。既存閾値は不変。',
    '追従': {'EMA': [15, 60], '傾き本数': 3, '間隔ATR下限': .15, '傾きATR下限': .02,
             '両市場ER20下限': .35, '方向保持なし': True},
    '反復': {'自市場ER20上限': .30, '相手ER20上限': .40, 'ATR比範囲': [.6, 1.5],
             'EMA間隔ATR絶対上限': 1., '20分高低幅ATR範囲': [1.5, 6.], '平均乖離ATR下限': .75},
    '公開': {'足開始から秒': 120, '相手追加遅延秒': 60, '主指標公開後鮮度秒': 120,
             '同方向同模式継続秒': 60, '原本時刻空白リセット秒': 60},
    '実時間窓': {'ER秒': 1200, '範囲秒': 1200, 'ATR中央値秒': 3600,
                  'ATR中央値必要有限足数': 30, 'ATR履歴必要経過秒': 3600},
    '板': {'OFI秒': 60, '距離変化秒': 30, '補充秒': 30, '推定成行秒': 60,
            'OFI重み': .5, '近傍変化重み': .3, '補充重み': .2,
            '元時刻鮮度秒': 20, '気配差呼値上限': 3, '推定成行逆行下限': .1, '補充支持下限': .1},
    'ER定義': '実20分前以前の最後の公開終値から現在公開終値までの純変化絶対値÷同区間の終値差絶対和。分母ゼロは0。',
    '範囲平均定義': '直近実20分(左開右閉)の公開確定足の高値最大・安値最小・終値単純平均。',
    'ATR比定義': '現在原本行までに公開されたATR÷直近実60分の公開足対応ATR中央値。',
    '板加重': 'OFIは符号和÷絶対和、dflow_nearはvalid_event_count加重平均、補充と推定成行は数量差÷和。窓は公開イベント時刻、同秒はseq順を維持。',
    '反射': '価格上下反射でmode/book_valid不変、trend/range_side/book_score/absorb_sideは符号反転。',
    '対象': '保存済み全16セッション32市場、費用・売買結果・将来の場ラベルを参照しない。'
}


def save(path: Path, value: dict) -> None:
    """機能: 新作業領域だけへ有限JSONを保存する。

    引数: path(Path)、value(dict)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def freeze() -> None:
    """機能: 損益計算より前に特徴の数式と閾値を固定する。

    引数: なし。返り値: なし(None)。既存の異なる定義を拒否する。
    """
    path = HERE / '特徴定義.json'
    if path.exists():
        current = json.loads(path.read_text(encoding='utf8'))
        if current.get('版') == 1:
            previous = dict(DEFINITION)
            previous['版'] = 1
            del previous['追加理由']
            assert current == previous and not (HERE / '特徴監査.json').exists()
            save(HERE / '特徴定義_支持抵抗追加前.json', current)
            save(path, DEFINITION)
        else:
            assert current == DEFINITION
    else:
        save(path, DEFINITION)


def load_inputs() -> tuple[dict, dict]:
    """機能: 既存14場と追加2場を読み、全16場を返す。

    引数: なし。返り値: 原本行入力、板公開特徴(tuple[dict,dict])。
    """
    inputs, features = {}, {}
    for folder, ipath, fpath in (
        (ROOT / 'work/wave_v47', 'inputs.pkl', 'features_depth.pkl'),
        (ROOT / 'work/wave_v48/update_20260930', 'new_inputs.pkl', 'new_features_depth.pkl'),
        (ROOT / 'work/wave_v48/update_20261001', 'new_inputs.pkl', 'new_features_depth.pkl')):
        current = pickle.loads((folder / ipath).read_bytes())
        board = pickle.loads((folder / fpath).read_bytes())
        assert not (set(current) & set(inputs))
        inputs.update(current)
        features.update(board)
    assert len(inputs) == len(features) == 32 and set(inputs) == set(features)
    assert len({key[0] for key in inputs}) == 16
    return inputs, features


def asof(events: np.ndarray, values: np.ndarray, targets: np.ndarray, default: float = np.nan) -> np.ndarray:
    """機能: 指定時点以前の最後の値だけを対応させる。

    引数: events/values/targets(ndarray)、default(float)。返り値: 過去対応値(ndarray)。
    """
    positions = np.searchsorted(events, targets, side='right') - 1
    result = np.full(len(targets), default, dtype=float)
    valid = positions >= 0
    result[valid] = np.asarray(values)[positions[valid]]
    return result


def bar_model(ready: dict, root: Path) -> dict:
    """機能: 公開済み確定足からEMA・実時間ER・範囲を計算する。

    引数: ready(dict)、root(Path)。返り値: 公開時刻別の指標(dict)。
    """
    frame = pd.read_csv(root / 'candle_1min' / ready['symbol'] / f"{ready['session']}.csv")
    release = pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120
    valid = frame.closed.astype(str).str.lower().eq('true').to_numpy(copy=True)
    # 相手の最終原本時刻と足の公開時計は別。全足の過去依存指標を作り、
    # 実使用は build 内の公開時刻 asof で制限する。相手板の疎な時刻で公開足を欠落させない。
    valid &= release >= ready['start'] + 120
    frame, release = frame.loc[valid].reset_index(drop=True), release[valid]
    assert len(release) and np.all(np.diff(release) > 0)
    close = frame.close.to_numpy(float)
    fast = pd.Series(close).ewm(span=15, adjust=False, min_periods=15).mean().to_numpy()
    slow = pd.Series(close).ewm(span=60, adjust=False, min_periods=60).mean()
    atr = asof(ready['time_s'], ready['atr'], release)
    gap = (fast - slow.to_numpy()) / atr
    slope = slow.diff(3).to_numpy() / atr
    fresh = np.where((gap > .15) & (slope > .02), 1,
                     np.where((gap < -.15) & (slope < -.02), -1, 0)).astype(np.int8)
    old = np.searchsorted(release, release - 1200, side='right') - 1
    changes = np.r_[0., np.cumsum(np.abs(np.diff(close)))]
    er = np.full(len(close), np.nan)
    enough = old >= 0
    denominator = changes[enough] - changes[old[enough]]
    er[enough] = np.divide(np.abs(close[enough] - close[old[enough]]), denominator,
                           out=np.zeros(np.count_nonzero(enough)), where=denominator > 0)
    times = pd.to_datetime(release, unit='s')
    high = pd.Series(frame.high.to_numpy(float), index=times).rolling('1200s').max().to_numpy()
    low = pd.Series(frame.low.to_numpy(float), index=times).rolling('1200s').min().to_numpy()
    mean = pd.Series(close, index=times).rolling('1200s').mean().to_numpy()
    median = pd.Series(atr, index=times).rolling('3600s', min_periods=30).median().to_numpy(copy=True)
    median[release < ready['start'] + 3600] = np.nan
    return dict(time_s=release, fresh=fresh, gap=gap, slope=slope, er=er,
                range_width=high - low, range_mean=mean, median_atr=median, close=close,
                support20=low, resistance20=high, center20=mean)


def window_sum(times: np.ndarray, values: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 同秒の未来イベントを含めず実時間の左開窓を集計する。

    引数: times/values(ndarray)、seconds(float)。返り値: 各公開行までの合計(ndarray)。
    """
    left = np.searchsorted(times, times - seconds, side='right')
    cumulative = np.r_[0., np.cumsum(values)]
    return cumulative[np.arange(len(times)) + 1] - cumulative[left]


def safe_ratio(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    """機能: 分母が正の場合だけ比率を返す。

    引数: top/bottom(ndarray)。返り値: 有限比率(ndarray)、分母ゼロは0。
    """
    return np.divide(top, bottom, out=np.zeros(len(top)), where=bottom > 0)


def board_model(frame: pd.DataFrame) -> dict:
    """機能: 公開済み板ブロックの流れ・補充・推定売買をまとめる。

    引数: frame(DataFrame)。返り値: 原本公開seqに対応する特徴(dict)。
    """
    seq = frame.seq.to_numpy(np.int64)
    times = frame.time_s.to_numpy(float)
    assert np.all(np.diff(seq) > 0) and np.all(np.diff(times) >= 0)
    assert np.all(frame.source_last_seq.to_numpy(np.int64) < seq)
    assert np.all(frame.source_time_s.to_numpy(float) <= times)
    ofi = safe_ratio(window_sum(times, frame.ofi_signed.to_numpy(float), 60),
                     window_sum(times, frame.ofi_abs.to_numpy(float), 60))
    count = frame.valid_event_count.to_numpy(float)
    near = safe_ratio(window_sum(times, frame.dflow_near.to_numpy(float) * count, 30),
                      window_sum(times, count, 30))
    refill_bid = window_sum(times, frame.refill_bid.to_numpy(float), 30)
    refill_ask = window_sum(times, frame.refill_ask.to_numpy(float), 30)
    refill = safe_ratio(refill_bid - refill_ask, refill_bid + refill_ask)
    buy = window_sum(times, frame.trade_pos.to_numpy(float), 60)
    sell = window_sum(times, frame.trade_neg.to_numpy(float), 60)
    trade = safe_ratio(buy - sell, buy + sell)
    score = .5 * ofi + .3 * near + .2 * refill
    return dict(seq=seq, time_s=times, source_time=frame.source_time_s.to_numpy(float),
                spread=frame.spread_ticks.to_numpy(float), score=score, near=near, refill=refill, trade=trade)


@njit(cache=True)
def confirmed(times: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    """機能: 同じ模式・方向が60秒続いてから有効化し、無効で即解除する。

    引数: times/candidate(ndarray)。返り値: 確認済み符号付き模式(ndarray[int8])。
    """
    out = np.zeros(len(times), dtype=np.int8)
    previous = 0
    started = 0.
    for i in range(len(times)):
        current = int(candidate[i])
        if current == 0 or current != previous or (i > 0 and times[i] - times[i - 1] > 60):
            started = times[i]
        if current != 0 and times[i] - started >= 60:
            out[i] = current
        previous = current
    return out


def build(inputs: dict, features: dict, root: Path = ROOT) -> dict:
    """機能: 原本の各行で追従・反復・中立と板の確認値を返す。

    引数: inputs/features(dict)、root(Path)。返り値: 銘柄場ごとの9配列(dict)。
    """
    models = {key: bar_model(ready, Path(root)) for key, ready in inputs.items()}
    result = {}
    for key, ready in inputs.items():
        peer_key = (key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225')
        assert peer_key in inputs and key in features
        times = ready['time_s']
        own, peer = models[key], models[peer_key]
        here = {name: asof(own['time_s'], value, times) for name, value in own.items() if name != 'time_s'}
        there = {name: asof(peer['time_s'] + 60, peer[name], times) for name in ('fresh', 'er')}
        own_age = times - asof(own['time_s'], own['time_s'], times)
        peer_age = times - asof(peer['time_s'] + 60, peer['time_s'] + 60, times)
        finite = np.isfinite(here['er']) & np.isfinite(there['er']) & np.isfinite(here['gap'])
        finite &= np.isfinite(ready['atr']) & (ready['atr'] > 0) & (own_age <= 120) & (peer_age <= 120)
        trend_ok = finite & (here['fresh'] != 0) & (here['fresh'] == there['fresh'])
        trend_ok &= (here['er'] >= .35) & (there['er'] >= .35)
        atr_ratio = ready['atr'] / here['median_atr']
        range_width = here['range_width'] / ready['atr']
        range_ok = finite & (here['er'] <= .30) & (there['er'] <= .40)
        range_ok &= (atr_ratio >= .6) & (atr_ratio <= 1.5) & (np.abs(here['gap']) <= 1)
        range_ok &= (range_width >= 1.5) & (range_width <= 6.)
        candidate = np.zeros(len(times), np.int8)
        candidate[trend_ok] = here['fresh'][trend_ok].astype(np.int8)
        candidate[range_ok] = 2
        agreed = confirmed(times, candidate)
        mode = np.where(np.abs(agreed) == 1, 1, np.where(agreed == 2, 2, 0)).astype(np.int8)
        trend = np.where(mode == 1, agreed, 0).astype(np.int8)
        distance = (here['close'] - here['range_mean']) / ready['atr']
        range_side = np.where((mode == 2) & (distance < -.75), 1,
                              np.where((mode == 2) & (distance > .75), -1, 0)).astype(np.int8)
        board = board_model(features[key])
        mapped = {name: asof(board['seq'], value, ready['seq']) for name, value in board.items() if name != 'seq'}
        book_valid = np.isfinite(mapped['score']) & (times - mapped['source_time'] <= 20)
        book_valid &= (times >= mapped['time_s']) & (mapped['spread'] > 0) & (mapped['spread'] <= 3)
        score = np.where(book_valid, mapped['score'], 0.)
        absorb = book_valid & (range_side != 0) & (range_side * mapped['trade'] < -.1)
        absorb &= (range_side * mapped['refill'] > .1) & (range_side * mapped['near'] > 0)
        absorb_side = np.where(absorb, range_side, 0).astype(np.int8)
        result[key] = dict(mode=mode, trend=trend, range_side=range_side, book_score=score,
                           book_valid=book_valid, absorb_side=absorb_side,
                           support20=here['support20'], resistance20=here['resistance20'], center20=here['center20'])
        assert all(len(value) == len(times) for value in result[key].values())
        assert np.isfinite(score).all() and np.max(np.abs(score)) <= 1 + 1e-9
    return result


if __name__ == '__main__':
    freeze()
    print('追従・反復・板特徴の数式と閾値を固定しました。')
