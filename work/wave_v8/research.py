"""事前記載した108条件を保存生板で比較し、時間順選択と感度を保存する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from model import OUT, SESSIONS, SYMBOLS, configs, directions, metrics, price_features, save, simulate


def load(session: str, symbol: str) -> dict:
    """機能: 保存済み板特徴と全気配を読み、過去だけの判定を用意する。

    引数: session/symbol (str)。返り値: 再生入力 (dict)。
    """
    frame = pd.read_csv(OUT / 'features' / f'{symbol}_{session}.csv')
    tape = dict(np.load(OUT / 'features' / f'約定系列_{symbol}_{session}.npz', allow_pickle=False))
    assert np.all(frame.source_last_seq < frame.seq)
    assert np.all(np.diff(tape['seq']) > 0) and np.all(np.diff(tape['time_s']) >= 0)
    atr, price = price_features(session, symbol, frame.time_s.to_numpy())
    signals, pressure = directions(frame, price)
    return dict(tape=tape, features=frame, signals=signals, atr=atr, pressure=pressure)


def choose(cells: pd.DataFrame, group: str, train_sessions: list[str]) -> dict:
    """機能: 過去のみの追加費用倍条件で両銘柄に取引する条件を選ぶ。

    引数: cells (DataFrame)、group (str)、train_sessions (list[str])。返り値: 採用記録 (dict)。
    """
    subset = cells[cells.群.eq(group) & cells.セッション.isin(train_sessions)]
    choices = []
    for method, rows in subset.groupby('方式'):
        counts = rows.groupby('銘柄').取引数.sum()
        if len(counts) < 2 or (counts < 1).any():
            continue
        scores = rows.groupby('銘柄').費用倍ATR収支.sum()
        choices.append(dict(方式=method, 全セル取引=bool((rows.取引数 >= 1).all()),
                            最小銘柄得点=float(scores.min()), 合計得点=float(scores.sum())))
    choices.sort(key=lambda x: (not x['全セル取引'], -x['最小銘柄得点'], -x['合計得点'], x['方式']))
    if not choices:
        return dict(群=group, 学習=train_sessions, 採用=None, 理由='両銘柄で取引する候補なし')
    return dict(群=group, 学習=train_sessions, 採用=choices[0], 全順位=choices)


def main() -> None:
    """機能: 全条件、過去選択、約定遅延比較を一括実行する。

    引数: なし。返り値: なし (None)。
    """
    started = time.monotonic()
    conditions = configs()
    save(OUT / '条件一覧.json', conditions)
    save(OUT / '実行前記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')),
         条件数=len(conditions), API取得=False, 既知データのみ=True,
         SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [OUT/'検証計画.md', OUT/'model.py', OUT/'research.py']}))
    cells, trades, inputs = [], [], {}
    for session in SESSIONS:
        for symbol in SYMBOLS:
            item = load(session, symbol)
            inputs[(session, symbol)] = item
            for config in conditions:
                signal = item['signals'][(config['family'], config['window'])]
                results = simulate(item['tape'], item['features'], signal, item['atr'], item['pressure'], config, session, symbol)
                cells.append(metrics(results, session, symbol, config))
                for row in results:
                    trades.append(dict(方式=config['id'], 群=config['group'], セッション=session, 銘柄=symbol, **row))
                    assert row['source_last_seq'] < row['signal_seq'] <= row['trigger_seq'] < row['entry_seq']
                    if row['closed']:
                        assert row['entry_seq'] <= row['exit_trigger_seq'] < row['exit_seq']
                        assert row['exit_in_session']
                if session != SESSIONS[-1]:
                    assert all(r['closed'] for r in results), f'完全セッションの未返済: {session} {symbol} {config}'
            print(f'{session} {symbol}: 108条件完了、累計{time.monotonic()-started:.1f}秒', flush=True)
    frame = pd.DataFrame(cells)
    frame.to_csv(OUT / '全条件セッション集計.csv', index=False, encoding='utf-8-sig')
    save(OUT / '全取引.json', trades)
    pd.DataFrame(trades).to_csv(OUT / '全取引.csv', index=False, encoding='utf-8-sig')
    # ----------------------------------------
    # 既知期間でも、次に試す条件の選択には直前までのセッションだけを使う。
    selections, forward = [], []
    for test_idx in range(2, len(SESSIONS)):
        train = SESSIONS[:test_idx]
        for group in ['価格のみ', '板のみ', '価格と板']:
            selected = choose(frame, group, train)
            selected['評価セッション'] = SESSIONS[test_idx]
            selections.append(selected)
            if selected['採用']:
                rows = frame[frame.方式.eq(selected['採用']['方式']) & frame.セッション.eq(SESSIONS[test_idx])]
                forward.extend(rows.to_dict('records'))
    save(OUT / '時間順選択.json', selections)
    pd.DataFrame(forward).to_csv(OUT / '時間順セッション集計.csv', index=False, encoding='utf-8-sig')
    # ----------------------------------------
    # 全期間の探索候補も掲載し、時間順選択と混同しない。
    finalists = {g: choose(frame, g, SESSIONS[:5]) for g in ['価格のみ', '板のみ', '価格と板']}
    save(OUT / '既知５セッション選択.json', finalists)
    targets = {s['採用']['方式'] for s in selections if s['採用']}
    targets |= {v['採用']['方式'] for v in finalists.values() if v['採用']}
    targets |= {'P00_0_追跡1ATR_利益保護'}
    sensitivity = []
    for session in SESSIONS:
        for symbol in SYMBOLS:
            item = inputs[(session, symbol)]
            for config in conditions:
                if config['id'] not in targets:
                    continue
                signal = item['signals'][(config['family'], config['window'])]
                for delay in ['２行後', '次時刻']:
                    result = simulate(item['tape'], item['features'], signal, item['atr'], item['pressure'], config, session, symbol, delay)
                    sensitivity.append(metrics(result, session, symbol, config, delay))
    pd.DataFrame(sensitivity).to_csv(OUT / '約定遅延感度.csv', index=False, encoding='utf-8-sig')
    save(OUT / '完了記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')),
         経過秒=time.monotonic()-started, 条件数=len(conditions), 集計セル数=len(cells), 取引記録数=len(trades),
         新規実API取得回数=0, 感度条件数=len(targets), 確定取引数=sum(t['closed'] for t in trades)))
    print('全条件・時間順・遅延感度の保存完了', flush=True)


if __name__ == '__main__':
    main()
