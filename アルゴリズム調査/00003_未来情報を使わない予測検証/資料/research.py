"""既知の実データを時間順に再生し、予測と注文の成績を分けて保存する。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
ARCHIVE = ROOT / 'アルゴリズム調査' / '00001_波検知と売買ポイントの調査' / '保存版'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ARCHIVE / 'work' / 'wave_v4'))
sys.path.insert(0, str(ARCHIVE / 'work' / 'wave_v5'))
sys.path.insert(0, str(ROOT / 'work' / 'wave_v6'))
from engine import TICKS, prepare, sign_schedule
from signals import FAMILIES, build_features, get_signals
from exits import ConfigV5
from exit_engine import ExitRule, simulate

SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night', '2026-09-23_Day']
SYMBOLS = ['NK225', 'TOPIX']
MULTIPLIER = {'NK225': 1000, 'TOPIX': 10000}
FEATURES = ['delta_atr', 'gap20', 'gap40', 'slope5', 'slope8', 'move5', 'move10', 'move15', 'move20', 'move30', 'move40', 'reg15', 'reg30', 'r2_15', 'r2_30', 'er20', 'rsi14', 'vwap_gap', 'vwap_slope', 'kama_gap']
HORIZONS = [30, 60, 120]
RULES = {'元4ATR': ExitRule('baseline'), '利益保護': ExitRule('stepped', trigger=2.5, width=.5)}


def save(path: Path, value: object) -> None:
    """機能: 日本語の結果をJSON保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    def convert(item):
        """機能: NumPy型と日時を保存可能な型に変換する。

        引数: item (object)。返り値: JSON互換値 (object)。
        """
        if isinstance(item, dict):
            return {str(k): convert(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [convert(v) for v in item]
        if isinstance(item, np.generic):
            item = item.item()
        if isinstance(item, float) and not np.isfinite(item):
            return None
        if isinstance(item, (pd.Timestamp, Path)):
            return str(item)
        return item
    path.write_text(json.dumps(convert(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def read_candle(path: Path) -> pd.DataFrame:
    """機能: 確定足だけを読み、順序と重複を確認する。

    引数: path (Path)。返り値: 時刻索引の足 (DataFrame)。
    """
    frame = pd.read_csv(path)
    frame['time'] = pd.to_datetime(frame.time)
    frame = frame[frame.closed.astype(str).str.lower().eq('true')].set_index('time').sort_index()
    assert not frame.index.duplicated().any()
    return frame


def load_data(root: Path = ROOT, sessions: list[str] = SESSIONS, live: bool = False) -> dict:
    """機能: 原本を読み取り、既存の因果的特徴と注文入力を作る。

    引数: root (Path)、sessions (list[str])、live (bool)。返り値: セッション銘柄別入力 (dict)。
    """
    result = {}
    for session in sessions:
        frames = {symbol: (read_candle(root / 'candle_1min' / symbol / f'{session}.csv'), read_candle(root / 'candle_5min' / symbol / f'{session}.csv')) for symbol in SYMBOLS}
        end = max(one.index[-1] for one, five in frames.values())
        for symbol, (one, five) in frames.items():
            cache = 'wave_v5' if session == SESSIONS[-1] else 'wave_v3_check' if session == SESSIONS[-2] else 'wave_v2'
            board = root / f'板特徴_{symbol}_{session}.csv' if live else ROOT / 'work' / cache / f'板特徴_{symbol}_{session}.csv'
            z = build_features(one, five, board if board.exists() else None, TICKS[symbol], end)
            result[(session, symbol)] = prepare(one, z, symbol, session)
    return result


def make_dataset(data: dict, path: Path, sessions: list[str] = SESSIONS) -> dict:
    """機能: 予測時点の特徴と、同一セッション内に満了する未来ラベルを分離する。

    引数: data (dict)、path (Path)、sessions (list[str])。返り値: モデル入力配列 (dict)。
    """
    parts = {key: [] for key in ['X', 'session_idx', 'symbol_idx', 'time_ns', 'valid', 'future_returns', 'label_end_ns', 'age']}
    for (session, symbol), item in data.items():
        z = item['z']
        times = z.index + pd.Timedelta(minutes=2)
        times_ns = times.as_unit('ns').asi8
        actual = item['one'].index.as_unit('ns').asi8
        opens = item['one'].open.to_numpy(float)
        start_pos = np.searchsorted(actual, times_ns)
        clamped = np.minimum(start_pos, len(actual) - 1)
        start_ok = (start_pos < len(actual)) & (actual[clamped] - times_ns <= 2 * 60 * 10**9)
        returns = np.full((len(z), 3), np.nan)
        ends = np.full((len(z), 3), -1, dtype=np.int64)
        for j, horizon in enumerate(HORIZONS):
            target_ns = times_ns + horizon * 60 * 10**9
            end_pos = np.searchsorted(actual, target_ns)
            end_clamped = np.minimum(end_pos, len(actual) - 1)
            ok = start_ok & (end_pos < len(actual)) & (actual[end_clamped] - target_ns <= 2 * 60 * 10**9)
            ok &= actual[end_clamped] <= item['limit'].value
            returns[ok, j] = opens[end_clamped[ok]] - opens[clamped[ok]]
            ends[ok, j] = actual[end_clamped[ok]]
        valid = z.atr.notna() & z.age.ge(43) & z.stale_minutes.le(10)
        valid &= times < item['limit'] - pd.Timedelta(minutes=30)
        parts['X'].append(z[FEATURES].to_numpy(float))
        parts['session_idx'].append(np.full(len(z), sessions.index(session)))
        parts['symbol_idx'].append(np.full(len(z), SYMBOLS.index(symbol)))
        parts['time_ns'].append(times_ns)
        parts['valid'].append(valid.to_numpy(bool))
        parts['future_returns'].append(returns)
        parts['label_end_ns'].append(ends)
        parts['age'].append(z.age.to_numpy(int))
    result = {key: np.concatenate(value) for key, value in parts.items()}
    result.update(feature_names=np.array(FEATURES), horizons=np.array(HORIZONS), sessions=np.array(sessions), symbols=np.array(SYMBOLS))
    np.savez_compressed(path, **result)
    return result


def config(family: int = 9) -> ConfigV5:
    """機能: 事前固定した入口設定を返す。

    引数: family (int)。返り値: 注文設定 (ConfigV5)。
    """
    return ConfigV5(family=family, param=.75, entry='trail', offset=1., trail=4., cooldown=45, warmup=45, stop_loss=2.5, take_profit=0.)


def mechanical_signals(data: dict) -> dict:
    """機能: 24系統と固定方向の判定を確定情報だけで計算する。

    引数: data (dict)。返り値: 方式別の銘柄セッション方向配列 (dict)。
    """
    output = {}
    for family in range(1, 25):
        output[f'機械{family:02d}'] = {}
        for key, item in data.items():
            peer = data[(key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225')]['z']
            output[f'機械{family:02d}'][key] = get_signals(item['z'], peer, family, .75).to_numpy()
    for name, sign in [('上昇固定', 1), ('下降固定', -1)]:
        output[name] = {key: np.full(len(item['z']), sign) for key, item in data.items()}
    return output


def metrics(trades: list[dict], session: str, symbol: str, method: str) -> dict:
    """機能: 確定損益と未返済を分け、費用控除後の成績を計算する。

    引数: trades (list[dict])、session/symbol/method (str)。返り値: 集計 (dict)。
    """
    closed = [t for t in trades if t['closed']]
    net = np.array([t['net_points'] * MULTIPLIER[symbol] for t in closed])
    stress = np.array([t['stress_points'] * MULTIPLIER[symbol] for t in closed])
    return dict(方式=method, セッション=session, 銘柄=symbol, 取引数=len(closed), 未返済数=len(trades)-len(closed), 勝ち数=int((net > 0).sum()), 利益円=float(net[net > 0].sum()), 損失円=float(-net[net < 0].sum()), 収支円=float(net.sum()), 費用倍収支円=float(stress.sum()), 費用倍ATR収支=float(sum(t['stress_points']/t['atr'] for t in closed)), 平均保有分=float(np.mean([t['duration_min'] for t in closed])) if closed else None)


def select_rule(cells: list[dict], train_sessions: list[str]) -> dict:
    """機能: 過去の取引だけで機械48条件の次回使用条件を選ぶ。

    引数: cells (list[dict])、train_sessions (list[str])。返り値: 選択記録 (dict)。
    """
    candidates = []
    methods = sorted({c['方式'] for c in cells if c['方式'].startswith('機械')})
    for method in methods:
        rows = [c for c in cells if c['方式'] == method and c['セッション'] in train_sessions]
        if not all(sum(c['取引数'] for c in rows if c['銘柄'] == symbol) >= 1 for symbol in SYMBOLS):
            continue
        eligible = all(c['取引数'] >= 1 for c in rows)
        totals = [sum(c['費用倍ATR収支'] for c in rows if c['銘柄'] == symbol) for symbol in SYMBOLS]
        candidates.append(dict(方式=method, 適格=eligible, 最小銘柄得点=min(totals), 合計得点=sum(totals)))
    candidates.sort(key=lambda c: (not c['適格'], -c['最小銘柄得点'], -c['合計得点'], c['方式']))
    if not candidates:
        raise ValueError('両銘柄で実際に取引した選択候補がありません')
    return dict(学習セッション=train_sessions, 採用=candidates[0], 全順位=candidates)


def accuracy(dataset: dict, predictions: dict, test_ids: list[int]) -> list[dict]:
    """機能: 未来方向の正答率と予測範囲を全標本・重複しない標本で評価する。

    引数: dataset/predictions (dict)、test_ids (list[int])。返り値: 成績一覧 (list[dict])。
    """
    rows = []
    for name, signs in predictions.items():
        for j, horizon in enumerate(HORIZONS):
            for symbol_id, symbol in enumerate(SYMBOLS):
                for spacing in [5, horizon]:
                    base = dataset['valid'] & np.isin(dataset['session_idx'], test_ids) & (dataset['symbol_idx'] == symbol_id)
                    base &= ((dataset['age'] - 45) % spacing == 0) & np.isfinite(dataset['future_returns'][:, j])
                    active = base & np.isfinite(signs) & (signs != 0)
                    change = dataset['future_returns'][:, j]
                    nonzero = active & (change != 0)
                    correct = signs[nonzero] * change[nonzero] > 0
                    up = nonzero & (change > 0)
                    down = nonzero & (change < 0)
                    balanced = .5 * (np.mean(signs[up] > 0) + np.mean(signs[down] < 0)) if up.any() and down.any() else np.nan
                    rows.append(dict(方式=name, 銘柄=symbol, 予測先分=horizon, 標本間隔分=spacing, 評価可能=int(base.sum()), 予測数=int(active.sum()), 横ばい数=int((active & (change == 0)).sum()), 方向判定数=int(nonzero.sum()), 正答数=int(correct.sum()), 正答率=float(correct.mean()) if len(correct) else None, 均衡正答率=float(balanced), 費用超過率=float(np.mean(signs[active]*change[active] > 2*TICKS[symbol])) if active.any() else None))
    return rows


def evaluate(data: dict, dataset: dict, ml_path: Path | None = None, prefix: str = '') -> dict:
    """機能: 事前固定条件を再生し、時間順選択と方向予測の成績を保存する。

    引数: data/dataset (dict)、ml_path (Path|None)、prefix (str)。返り値: 全結果 (dict)。
    """
    signals = mechanical_signals(data)
    if ml_path and ml_path.exists():
        ml = np.load(ml_path, allow_pickle=False)
        for field in ['time_ns', 'session_idx', 'symbol_idx']:
            assert np.array_equal(ml[field], dataset[field]), f'予測の行対応が不一致: {field}'
        for name in ['logistic', 'lstm']:
            for horizon in HORIZONS:
                label = f'{name}_{horizon}'
                prob = ml[label]
                full = np.where(np.isfinite(prob), np.where(prob >= .5, 1, -1), 0)
                full[~dataset['valid']] = 0
                signals[label] = {}
                offset = 0
                for key, item in data.items():
                    length = len(item['z'])
                    signals[label][key] = full[offset:offset+length]
                    offset += length
    cells, trade_rows, flat = [], [], {}
    for name, group in signals.items():
        flat[name] = np.concatenate(list(group.values()))
        for exit_name, rule in RULES.items():
            method = f'{name}/{exit_name}'
            for key, item in data.items():
                family = int(name[2:]) if name.startswith('機械') else 9
                trades = simulate(item, sign_schedule(group[key]), config(family), rule)
                for trade in trades:
                    trade_rows.append(dict(方式=method, **trade))
                cells.append(metrics(trades, *key, method))
    selections = []
    flat['過去だけで選択'] = np.zeros(len(dataset['X']))
    for fold in range(2, len(SESSIONS)):
        chosen = select_rule(cells, SESSIONS[:fold])
        chosen['評価セッション'] = SESSIONS[fold]
        selections.append(chosen)
        name = chosen['採用']['方式'].split('/')[0]
        mask = dataset['session_idx'] == fold
        flat['過去だけで選択'][mask] = flat[name][mask]
        for cell in cells.copy():
            if cell['方式'] == chosen['採用']['方式'] and cell['セッション'] == SESSIONS[fold]:
                cells.append({**cell, '方式': '過去だけで選択', '選択方式': cell['方式']})
    result = dict(方式名={f'機械{k:02d}': v for k,v in FAMILIES.items()}, セッション収支=cells, 時間順選択=selections, 全期間学習選択=select_rule(cells, SESSIONS), 予測成績=accuracy(dataset, flat, [2,3,4]), 取引=trade_rows)
    save(OUT / f'{prefix}時間順検証.json', result)
    pd.DataFrame(cells).to_csv(OUT / f'{prefix}セッション別収支.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(result['予測成績']).to_csv(OUT / f'{prefix}未来方向の予測成績.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(trade_rows).to_csv(OUT / f'{prefix}全取引.csv', index=False, encoding='utf-8-sig')
    return result


def main() -> None:
    """機能: 入力作成または固定条件の検証を実行する。

    引数: コマンドライン。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['dataset', 'evaluate'])
    args = parser.parse_args()
    data = load_data()
    dataset = make_dataset(data, OUT / 'dataset.npz')
    if args.action == 'evaluate':
        result = evaluate(data, dataset, OUT / 'ml_predictions.npz')
        print(json.dumps({'セル数': len(result['セッション収支']), '取引数': len(result['取引']), '次回機械選択': result['全期間学習選択']['採用']}, ensure_ascii=False))
    else:
        print(json.dumps({'特徴行数': len(dataset['X']), '特徴数': len(FEATURES), '有効行数': int(dataset['valid'].sum()), '未来ラベル数': np.isfinite(dataset['future_returns']).sum(axis=0).tolist()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
