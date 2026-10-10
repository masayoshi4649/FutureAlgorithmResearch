"""通信をせず、現在照合器の境界評価を切断再生と比較する。"""

from __future__ import annotations

from datetime import datetime

import numpy as np

import live_check
import research
import signals


def main() -> None:
    """機能: 14種類の単建玉・複数建玉を、２境界・２銘柄で切断比較する。

    引数: なし。返り値: なし (None)。API・凍結記録の生成は行わない。
    """
    inputs = signals.load_inputs([signals.SESSIONS[-1]])
    all_configs = live_check.configuration_map()
    ids = ['P_P01_15', 'H_P07_E1_X1_Z0', 'M_P12_O07_G0_X0', 'M_P13_O08_G0_X0']
    ids += [f'O{i:02d}_G0_X0' for i in range(1, 11)]
    checks = []
    for key, item in inputs.items():
        ready = research.prepared_inputs({key: item})[key]
        for text in ['2026-09-23T23:00:00+09:00', '2026-09-23T23:30:00+09:00']:
            cutoff = datetime.fromisoformat(text).timestamp()
            mask = item['tape']['time_s'] < cutoff
            tape = {name: value[mask] if value.ndim and len(value) == len(mask) else value
                    for name, value in item['tape'].items()}
            events = item['events'].loc[item['events'].seq <= tape['seq'][-1]]
            state = {name: value[mask] for name, value in item['state'].items()}
            short = research.single.prepare(tape, events, key[0], key[1], state)
            for condition in ids:
                config = all_configs[condition]
                full_row, full_raw, _ = research.run_one(ready, config)
                full_trades = research.trade_records(ready, config, full_raw)
                boundary = live_check.liquidation_at(ready, full_trades, cutoff)
                prefix_row, prefix_raw, curve = research.run_one(short, config)
                assert np.isclose(boundary['清算価値円'], curve[-1, 2]), (key, condition, text)
                assert np.isclose(boundary['費用倍清算価値円'], curve[-1, 3]), (key, condition, text, '費用倍')
                assert np.isclose(boundary['清算価値円'], prefix_row['収支円']+prefix_row['評価損益円'])
                checks.append(dict(session=key[0], symbol=key[1], condition=condition, cutoff=text,
                                   清算価値円=boundary['清算価値円'], 返済数=boundary['返済数'],
                                   未返済数=boundary['未返済数'], 切断再生一致=True))
    research.save(signals.OUT/'照合器_通信なし監査.json', dict(検査数=len(checks), 全件一致=True, 今回API取得数=0, 検査=checks))
    print(f'{len(checks)}箇所で全建玉の境界清算価値が切断再生と一致しました。通信なし。')


if __name__ == '__main__':
    main()
