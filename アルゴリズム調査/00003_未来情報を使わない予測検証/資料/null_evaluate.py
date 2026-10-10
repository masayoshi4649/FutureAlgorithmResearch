"""方向を当てない対照を固定した100乱数で再生する。"""

from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd

from research import OUT, SESSIONS, RULES, config, load_data, metrics, save, sign_schedule, simulate


def run() -> None:
    """機能: 30分ごとのコイントスを100通り実行し、全結果と分布を保存する。

    引数: なし。返り値: なし (None)。良い乱数だけを選ばない。
    """
    data = load_data()
    rows = []
    for seed in range(100):
        for key, item in data.items():
            salt = int(hashlib.sha256('/'.join(key).encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(20260923 + seed + salt)
            age = item['z'].age.to_numpy(int)
            signs = rng.choice([-1, 1], int(age.max() // 30 + 1))[age // 30]
            for exit_name, rule in RULES.items():
                trades = simulate(item, sign_schedule(signs), config(), rule)
                rows.append(dict(seed=seed, **metrics(trades, *key, f'乱数/{exit_name}')))
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / 'コイントス100通り.csv', index=False, encoding='utf-8-sig')
    forward = frame[frame['セッション'].isin(SESSIONS[2:])]
    totals = forward.groupby(['方式', '銘柄', 'seed'])[['収支円', '費用倍収支円', '取引数']].sum().reset_index()
    output = []
    for (method, symbol), group in totals.groupby(['方式', '銘柄']):
        output.append(dict(方式=method, 銘柄=symbol, 平均収支円=float(group['収支円'].mean()), 中央値円=float(group['収支円'].median()), 下側5パーセント円=float(group['収支円'].quantile(.05)), 上側95パーセント円=float(group['収支円'].quantile(.95)), 平均費用倍収支円=float(group['費用倍収支円'].mean()), 平均取引数=float(group['取引数'].mean())))
    save(OUT / 'コイントス対照.json', dict(対象=SESSIONS[2:], 乱数数=100, 分布=output, 全合計=totals.to_dict('records')))
    print('コイントス100通りの対照が完了しました')


if __name__ == '__main__':
    run()
