"""転換入口90条件を固定して、セッション別損益と時間順の評価を保存する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from execution import OUT, ROOT, SESSIONS, SYMBOLS, atr_at, configs, metrics, save, simulate
from turning_signals import FAMILIES, build_events


def load_inputs() -> dict:
    """機能: 検査済み全気配と解放済み特徴から、確定情報だけの転換イベントを作る。

    引数: なし。返り値: セッション銘柄ごとの入力 (dict)。
    """
    output = {}
    for session in SESSIONS:
        frames = {s: pd.read_csv(ROOT/'work'/'wave_v8'/'features'/f'{s}_{session}.csv') for s in SYMBOLS}
        for symbol in SYMBOLS:
            frame = frames[symbol]
            peer = frames[SYMBOLS[1-SYMBOLS.index(symbol)]]
            events, audit = build_events(session, symbol, frame, peer)
            tape = dict(np.load(ROOT/'work'/'wave_v8'/'features'/f'約定系列_{symbol}_{session}.npz', allow_pickle=False))
            tape['atr'] = atr_at(session, symbol, tape['time_s'])
            output[(session, symbol)] = dict(features=frame, peer_features=peer, tape=tape, events=events, event_audit=audit)
    return output


def choose(frame: pd.DataFrame, group: str, train: list[str]) -> dict:
    """機能: 過去期間の費用倍収支で、無取引を除外して次回の条件を選ぶ。

    引数: frame (DataFrame)、group (str)、train (list[str])。返り値: 全順位付き選択記録 (dict)。
    """
    rows = frame[frame.セッション.isin(train)]
    rows = rows[rows.系統.ne('T00')] if group == '転換方式全体' else rows[rows.群.eq(group)]
    rankings = []
    for method, part in rows.groupby('方式'):
        counts = part.groupby('銘柄').取引数.sum()
        if len(counts) != 2 or (counts < len(train)).any():
            continue
        score = part.groupby('銘柄').費用倍ATR収支.sum() - .25*(counts-6*len(train)).clip(lower=0)
        rankings.append(dict(方式=method, 最小銘柄得点=float(score.min()), 合計得点=float(score.sum()),
                             銘柄別取引数=counts.to_dict()))
    rankings.sort(key=lambda r: (-r['最小銘柄得点'], -r['合計得点'], r['方式']))
    return dict(群=group, 学習=train, 採用=rankings[0] if rankings else None, 全順位=rankings,
                不採用理由=None if rankings else '学習期間に両銘柄の最低取引数を満たす候補なし')


def main() -> None:
    """機能: 結果前記録、全条件再生、時間順選択、遅延感度を実行する。

    引数: なし。返り値: なし (None)。
    """
    started = time.monotonic()
    conditions = configs()
    for c in conditions:
        c['name'] = FAMILIES[c['family']]
        c['description'] = FAMILIES[c['family']]
    save(OUT/'条件一覧.json', conditions)
    tracked = [OUT/'検証計画.md', OUT/'execution.py', OUT/'turning_signals.py', OUT/'research.py']
    save(OUT/'実行前記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 条件数=len(conditions),
         今回API取得回数=0, SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}))
    inputs = load_inputs()
    event_rows, audits, cells, all_trades = [], [], [], []
    for (session, symbol), item in inputs.items():
        event_rows.extend(dict(セッション=session, 銘柄=symbol, **r) for r in item['events'].to_dict('records'))
        audits.append(dict(セッション=session, 銘柄=symbol, 内容=item['event_audit']))
        for config in conditions:
            trades = simulate(item['tape'], item['events'], config, session, symbol)
            cells.append(metrics(trades, session, symbol, config))
            for trade in trades:
                assert trade['source_last_seq'] < trade['signal_seq'] <= trade['condition_seq'] < trade['trigger_seq'] < trade['entry_seq']
                if trade['closed']:
                    assert trade['entry_seq'] < trade['exit_trigger_seq'] < trade['exit_seq'] and trade['exit_in_session']
                all_trades.append(dict(方式=config['id'], 群=config['group'], セッション=session, 銘柄=symbol, **trade))
            if session != SESSIONS[-1]:
                assert all(t['closed'] for t in trades), (session, symbol, config['id'])
        print(f'{session} {symbol}: 90条件完了、累計{time.monotonic()-started:.1f}秒', flush=True)
    frame = pd.DataFrame(cells)
    frame.to_csv(OUT/'全条件セッション集計.csv', index=False, encoding='utf-8-sig')
    save(OUT/'全取引.json', all_trades)
    pd.DataFrame(all_trades).to_csv(OUT/'全取引.csv', index=False, encoding='utf-8-sig')
    save(OUT/'転換イベント.json', event_rows)
    pd.DataFrame(event_rows).to_csv(OUT/'転換イベント.csv', index=False, encoding='utf-8-sig')
    save(OUT/'転換イベント作成監査.json', audits)
    # ----------------------------------------
    # 未来のセッションを選択根拠にせず、次回使用条件を過去だけから決定する。
    groups = ['転換方式全体'] + list(dict.fromkeys(c['group'] for c in conditions))
    selections, forward = [], []
    for index in range(2, len(SESSIONS)):
        for group in groups:
            selected = choose(frame, group, SESSIONS[:index])
            selected['評価セッション'] = SESSIONS[index]
            selections.append(selected)
            if selected['採用']:
                part = frame[frame.方式.eq(selected['採用']['方式']) & frame.セッション.eq(SESSIONS[index])].copy()
                part['元の群'] = part.群
                part['群'] = group
                forward.extend(part.to_dict('records'))
    finalists = {group: choose(frame, group, SESSIONS[:5]) for group in groups}
    save(OUT/'時間順選択.json', selections)
    save(OUT/'既知５セッション選択.json', finalists)
    pd.DataFrame(forward).to_csv(OUT/'時間順セッション集計.csv', index=False, encoding='utf-8-sig')
    # ----------------------------------------
    # 選択条件を変えずに観測遅延を変え、同時刻の気配への依存を調べる。
    targets = {s['採用']['方式'] for s in selections if s['採用']}
    targets |= {s['採用']['方式'] for s in finalists.values() if s['採用']}
    targets |= {f'{family}_追跡0.25ATR_追跡2ATR' for family in ['T01', 'T06', 'T12']}
    sensitivity = []
    for (session, symbol), item in inputs.items():
        for config in conditions:
            if config['id'] not in targets:
                continue
            for delay in ['２行後', '次時刻']:
                trades = simulate(item['tape'], item['events'], config, session, symbol, delay)
                sensitivity.append(metrics(trades, session, symbol, config, delay))
    pd.DataFrame(sensitivity).to_csv(OUT/'約定遅延感度.csv', index=False, encoding='utf-8-sig')
    save(OUT/'完了記録.json', dict(時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 経過秒=time.monotonic()-started,
         条件数=len(conditions), 集計セル数=len(frame), 取引記録数=len(all_trades), 転換イベント数=len(event_rows),
         今回API取得回数=0, 感度対象条件数=len(targets)))
    print('転換イベント・90条件・時間順・感度の保存完了', flush=True)


if __name__ == '__main__':
    main()
