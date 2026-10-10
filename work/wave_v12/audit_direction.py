"""方向反転の固定時間会計と、最悪条件選択の未来結果不使用を独立に確認する。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import direction


def fixed_time_identity(trades: list[dict]) -> list[dict]:
    """機能: 固定時間返済では同時点の反対売買になり、両方向損益和が費用になることを確かめる。

    引数: trades (list[dict])。返り値: 方式・データ区間・銘柄別の会計内訳 (list[dict])。
    """
    rows = [trade for trade in trades if trade['方式'].startswith('P_')]
    originals = {(trade['データ区分'], trade['方式'], trade['セッション'], trade['銘柄'], trade['event_id']): trade
                 for trade in rows if trade['方向'] == '元の方向'}
    records = []
    for reverse in rows:
        if reverse['方向'] != '予測方向反転':
            continue
        key = (reverse['データ区分'], reverse['方式'], reverse['セッション'], reverse['銘柄'], reverse['event_id'])
        original = originals.pop(key)
        assert reverse['side'] == -original['side']
        assert reverse['entry_seq'] == original['entry_seq']
        assert reverse['closed'] == original['closed']
        if reverse['closed']:
            assert reverse['exit_seq'] == original['exit_seq']
        else:
            assert reverse['mark_time_s'] == original['mark_time_s']
        symbol = reverse['銘柄']
        multiplier, tick = direction.single.MULTIPLIERS[symbol], direction.single.TICKS[symbol]
        entry_spread = original['entry_spread']
        exit_spread = (original['exit_spread'] if reverse['closed']
                       else abs(reverse['mark_price'] - original['mark_price']))
        combined = original['net_points'] + reverse['net_points']
        expected = -(entry_spread + exit_spread + 4*tick)
        assert np.isclose(combined, expected), (key, combined, expected)
        records.append(dict(データ区分=key[0], 方式=key[1], セッション=key[2], 銘柄=symbol,
                            返済済み=reverse['closed'], 元収支円=original['net_points']*multiplier,
                            逆収支円=reverse['net_points']*multiplier,
                            元中値変化円=(original['net_points']-reverse['net_points'])*multiplier/2,
                            各方向気配差負担円=(entry_spread+exit_spread)*multiplier/2,
                            各方向追加費用円=2*tick*multiplier, 対応脚数=1))
    assert not originals
    group = ['データ区分', '方式', 'セッション', '銘柄', '返済済み']
    return pd.DataFrame(records).groupby(group, as_index=False).sum().to_dict('records')


def future_mutation() -> list[dict]:
    """機能: 選択時点より未来の全損益を極端値に変えても採用結果が変わらないことを確かめる。

    引数: なし。返り値: 学習区間別検査結果 (list[dict])。
    """
    frame = pd.read_csv(direction.V11 / '全条件_セッション集計.csv')
    mapping = {cfg['id']: cfg for cfg in direction.catalog.configs()}
    choices = direction.select_worst(frame, mapping)
    checks = []
    for n in [2, 3, 4]:
        changed = frame.copy()
        outside = ~changed.セッション.isin(direction.COMPLETE[:n])
        changed.loc[outside, '収支円'] = -1e30
        changed.loc[outside, '枚数上限換算収支円'] = 1e30
        changed.loc[outside, '取引数'] = 0
        actual = [row for row in direction.select_worst(changed, mapping) if row['学習セッション数'] == n]
        expected = [row for row in choices if row['学習セッション数'] == n]
        assert actual == expected
        checks.append(dict(学習セッション数=n, 未来の損益と取引数改変=True, 変更後採用と得点不変=True, 比較選択数=len(actual)))
    return checks


def main() -> None:
    """機能: 保存済みの反転取引会計と条件選択を検査して結果を保存する。

    引数: なし。返り値: なし (None)。ネットワーク通信なし。
    """
    trades = json.loads((direction.OUT / '方向反転_全取引.json').read_text(encoding='utf-8'))
    identity = fixed_time_identity(trades)
    checks = future_mutation()
    pd.DataFrame(identity).to_csv(direction.OUT / '固定時間反転_中値と費用分解.csv', index=False, encoding='utf-8-sig')
    direction.single.save(direction.OUT / '方向反転_追加監査.json', dict(合格=True,
        固定時間元反転の会計対応脚数=sum(row['対応脚数'] for row in identity),
        会計式='元純損益＋反転純損益＝−新規気配差−返済気配差−４呼値。未返済は末尾気配で評価。',
        未来結果変更検査=checks, 現在API取得数=0))
    print('固定時間反転の気配差・費用会計と、未来結果改変の最悪選択不変を確認しました。')


if __name__ == '__main__':
    main()
