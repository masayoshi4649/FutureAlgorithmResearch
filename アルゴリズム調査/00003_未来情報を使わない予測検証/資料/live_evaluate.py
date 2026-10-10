"""事前凍結した方式だけを、一度取得した未使用セッションへ適用する。"""

from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import pandas as pd

from research import OUT, ROOT, SYMBOLS, MULTIPLIER, TICKS, RULES, config, load_data, make_dataset, mechanical_signals, metrics, accuracy, save, simulate, sign_schedule


def check_freeze() -> dict:
    """機能: 取得前に固定された実装と学習モデルの指紋を確認する。

    引数: なし。返り値: 固定条件 (dict)。不一致時は中止する。
    """
    frozen = json.loads((OUT / '凍結記録.json').read_text(encoding='utf-8'))
    for name, expected in frozen['files_sha256'].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        assert actual == expected, name
    return frozen


def run(action: str) -> None:
    """機能: 新セッションの入力作成または固定方式の成績評価を行う。

    引数: action (str)。返り値: なし (None)。再学習や条件選択は行わない。
    """
    frozen = check_freeze()
    live = OUT / 'live'
    sessions = sorted(path.stem for path in (live / 'candle_1min' / SYMBOLS[0]).glob('*.csv'))
    assert len(sessions) == 1, sessions
    assert sessions[0] not in frozen['known_sessions'], '既知セッションなので未使用とは扱えません'
    data = load_data(live, sessions, live=True)
    dataset = make_dataset(data, live / 'dataset.npz', sessions)
    if action == 'dataset':
        print(json.dumps({'未使用セッション': sessions[0], '特徴行数': len(dataset['X'])}, ensure_ascii=False))
        return
    ml = np.load(live / 'live_predict.npz', allow_pickle=False)
    for field in ['time_ns', 'session_idx', 'symbol_idx']:
        assert np.array_equal(ml[field], dataset[field]), f'予測の行対応が不一致: {field}'
    signs = mechanical_signals(data)
    for model in ['logistic', 'lstm']:
        name = f'{model}_60'
        prob = ml[name]
        direction = np.where(np.isfinite(prob), np.where(prob >= .5, 1, -1), 0)
        direction[~dataset['valid']] = 0
        signs[name] = {}
        offset = 0
        for key, item in data.items():
            count = len(item['z'])
            signs[name][key] = direction[offset:offset+count]
            offset += count
    cells, all_trades, forecasts = [], [], {}
    for method in frozen['live_methods']:
        name, exit_name = method.split('/')
        group = signs[name]
        forecasts[name] = np.concatenate(list(group.values()))
        for key, item in data.items():
            family = int(name[2:]) if name.startswith('機械') else 9
            trades = simulate(item, sign_schedule(group[key]), config(family), RULES[exit_name])
            cell = metrics(trades, *key, method)
            last = item['one'].iloc[-1]
            floating = sum((t['side']*(float(last.close)-t['entry_price'])-2*TICKS[key[1]])*MULTIPLIER[key[1]] for t in trades if not t['closed'])
            cell.update(観測最終足=str(item['one'].index[-1]), 未返済評価損益円=float(floating), 確定と評価の合計円=cell['収支円']+float(floating))
            cells.append(cell)
            for trade in trades:
                all_trades.append(dict(方式=method, **trade))
    result = dict(区分='取得前に全条件と学習済みモデルを固定した、未使用セッションの一回照合。取得後の未来は未観測。', セッション=sessions[0], セッション収支=cells, 予測成績=accuracy(dataset, forecasts, [0]), 取引=all_trades, 凍結時刻=frozen['fixed_at'])
    save(live / '未使用セッション結果.json', result)
    pd.DataFrame(cells).to_csv(live / '未使用セッション収支.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(result['予測成績']).to_csv(live / '未使用セッション予測.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(all_trades).to_csv(live / '未使用セッション取引.csv', index=False, encoding='utf-8-sig')
    print(json.dumps({'セッション': sessions[0], '方式数': len(frozen['live_methods']), '確定取引数': sum(c['取引数'] for c in cells), '未返済数': sum(c['未返済数'] for c in cells)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['dataset', 'evaluate'])
    run(parser.parse_args().action)
