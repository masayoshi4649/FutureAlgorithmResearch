"""観測分析の現在特徴が、未来切断・未来改変で変化しないか確認する。"""

from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import analyze


def main() -> None:
    """機能: 二銘柄の観測特徴を未来切断・未来改変で検算する。

    引数: なし。返り値: なし(None)。将来ラベルは比較対象から分離する。
    """
    ready = analyze.load_ready()
    checks = []
    for symbol in ('TOPIX', 'NK225'):
        key = ('2026-09-21_Day', symbol)
        path = analyze.MEASUREMENT / 'accounts' / f'{key[0]}_{symbol}.pkl'
        full = pickle.loads(path.read_bytes())
        cut = len(full) // 2
        time = float(full.time_s.iloc[cut])
        reference, _, quality = analyze.build_account(full, ready[key])
        prefix, _, _ = analyze.build_account(full.iloc[:cut].copy(), ready[key])
        expected = reference.loc[reference.time_s < time].reset_index(drop=True)
        actual = prefix.loc[prefix.time_s < time].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        changed = full.copy()
        for column in ('mid', 'last', 'bid', 'ask'):
            changed.loc[changed.index[cut:], column] += 12345.
        for column in ('exec_buy', 'noexec_ask_remove', 'refill_bid_fixed_quote', 'supply_bid_near'):
            changed.loc[changed.index[cut:], column] *= 31.
        perturbed, _, _ = analyze.build_account(changed, ready[key])
        pd.testing.assert_frame_equal(perturbed.loc[perturbed.time_s < time].reset_index(drop=True), expected, check_exact=True)
        assert not any(name.startswith(('y60', 'y300', 'y900', 'up60', 'down60', 'max_gap')) for name in reference.columns)
        checks.append(dict(symbol=symbol, cut_public_row=cut, cut_time=time,
                           matched_observations=len(expected), quality=quality))
    analyze.save(analyze.HERE / '観測因果監査.json', dict(合格=True, 将来切断一致=True, 将来改変一致=True,
        ラベルと特徴分離=True, 検査=checks))
    print('未来切断と未来改変の観測特徴が両銘柄で完全一致しました。')


if __name__ == '__main__':
    main()
