"""研究仮説の信号とATRについて、後続データを除いた再計算を確認する。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import signals


def canonical(frame: pd.DataFrame) -> str:
    """機能: 欠損を含む信号表を比較可能な決定的文字列にする。

    引数: frame (DataFrame)。返り値: 正規化JSON (str)。
    """
    return json.dumps(frame.to_dict('records'), sort_keys=True, ensure_ascii=False, allow_nan=True)


def main() -> None:
    """機能: 12入力を各３箇所で打ち切り、将来を消しても過去が同じか検査する。

    引数: なし。返り値: なし (None)。
    """
    items = signals.load_inputs()
    checks = []
    for (session, symbol), item in items.items():
        f, peer = item['features'], item['peer_features']
        for fraction in [.35, .6, .85]:
            cutoff = float(f.time_s.iloc[int((len(f)-1)*fraction)])
            partial, _ = signals.build_events(session, symbol, f.loc[f.time_s <= cutoff],
                                              peer.loc[peer.time_s <= cutoff], cutoff=cutoff)
            known = item['events'].loc[item['events'].time_s <= cutoff].reset_index(drop=True)
            assert canonical(partial) == canonical(known), (session, symbol, cutoff)
            times = item['tape']['time_s']
            mask = times <= cutoff
            sliced = signals.atr_at(session, symbol, times[mask], cutoff=cutoff)
            assert np.allclose(sliced, item['tape']['atr'][mask], equal_nan=True), (session, symbol, 'ATR')
            checks.append(dict(session=session, symbol=symbol, cutoff=cutoff, events=len(partial),
                               atr_rows=int(mask.sum()), 信号一致=True, ATR一致=True))
    payload = dict(検査数=len(checks), 全件一致=True, 検査=checks,
                   説明='特徴原本はv8の既存同時刻ブロック解放済み。今回は信号計算のprefix不変性を検査。raw再抽出監査の代替ではない。')
    signals.OUT.joinpath('信号prefix監査.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(検査数=len(checks), 全件一致=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
