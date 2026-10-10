"""独立抽出した最良気配を、公開ブロックの現在気配と全数で突き合わせる。"""

from __future__ import annotations

import pickle

import numpy as np

from extract import HERE, save_json


def main() -> None:
    """機能: 公開行の時刻・最良気配・中値を2つの抽出経路で比較する。

    引数: なし。返り値: なし(None)。売買成績も将来価格も参照しない。
    """
    quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    features = pickle.loads((HERE / 'features.pkl').read_bytes())
    assert set(quotes) == set(features)
    records = []
    for key, frame in features.items():
        values = quotes[key]
        index = np.searchsorted(values['seq'], frame.seq.to_numpy())
        np.testing.assert_array_equal(values['seq'][index], frame.seq.to_numpy())
        for name in ('time_s', 'bid', 'ask', 'mid'):
            np.testing.assert_array_equal(values[name][index], frame[name].to_numpy())
        records.append(dict(セッション=key[0], 銘柄=key[1], 一致公開行数=len(frame)))
    save_json(HERE / '気配の抽出経路照合.json', dict(合格=True, 口座数=len(records),
              一致公開行数=sum(row['一致公開行数'] for row in records), 原本別=records))


if __name__ == '__main__':
    main()
