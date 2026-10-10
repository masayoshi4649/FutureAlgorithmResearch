"""N17 の末尾依存を、取引実装を変更せず入力上限だけの診断実験で切り分ける。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import reference

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def iso(value: float) -> str:
    """機能: 秒時刻を日本時間の文字列へ変換する。

    引数: value (float)。返り値: ISO 時刻 (str)。
    """
    return pd.Timestamp(value, unit='s', tz='UTC').tz_convert('Asia/Tokyo').isoformat()


def main() -> None:
    """機能: 旧短区間・全体・足上限だけ訂正した診断再生成の N17/N18 信号を比較する。

    引数: なし。返り値: なし (None)。ソース改変・売買・損益計算は行わない。
    """
    session, symbol, peer_symbol = '2026-09-24_Night', 'NK225', 'TOPIX'
    with (ROOT/'work/wave_v15/現在入力.pkl').open('rb') as stream:
        old = pickle.load(stream)[(session, symbol)]
    own = pd.read_csv(OUT/'features'/f'{symbol}_{session}.csv')
    peer = pd.read_csv(OUT/'features'/f'{peer_symbol}_{session}.csv')
    cutoff = float(old['time_s'][-1])
    own_cut, peer_cut = own[own.time_s <= cutoff].copy(), peer[peer.time_s <= cutoff].copy()
    last_own_feature = float(own_cut.time_s.iloc[-1])
    last_peer_feature = float(peer_cut.loc[peer_cut.time_s+60 <= last_own_feature, 'time_s'].iloc[-1])
    base = reference.previous.data.signals_module()
    base.CANDLE_OVERRIDES[session] = ROOT
    base.FEATURE_OVERRIDES[session] = OUT/'features'
    signals = reference.previous.new_signals
    signals.configure(base)
    whole, _ = signals.build_events(session, symbol, own, peer)
    original, _ = signals.build_events(session, symbol, own_cut, peer_cut)
    original_grid = base.price_grid
    before_grid = original_grid(session, peer_symbol, last_peer_feature)
    after_grid = original_grid(session, peer_symbol, last_own_feature-60)

    def diagnostic_grid(target_session: str, target_symbol: str, last_time: float) -> pd.DataFrame:
        """機能: 診断中だけ他銘柄足の読み込み上限を自銘柄時刻から60秒前に置く。

        引数: target_session/target_symbol (str)、last_time (float)。返り値: 足特徴 (DataFrame)。
        """
        horizon = last_own_feature-60 if target_symbol == peer_symbol else last_time
        return original_grid(target_session, target_symbol, horizon)

    try:
        base.price_grid = diagnostic_grid
        corrected, _ = signals.build_events(session, symbol, own_cut, peer_cut)
    finally:
        base.price_grid = original_grid
    records = []
    for family in ['N17', 'N18']:
        full_rows = whole.loc[(whole.family == family) & (whole.time_s <= cutoff)]
        old_rows = original[original.family == family]
        diagnostic_rows = corrected[corrected.family == family]
        cols = ['seq', 'side', 'time_s']
        full_values = full_rows[cols].to_numpy()
        diagnostic_values = diagnostic_rows[cols].to_numpy()
        np.testing.assert_array_equal(full_values, diagnostic_values)
        old_keys, full_keys = set(old_rows.seq), set(full_rows.seq)
        records.append(dict(系統=family, 旧打切り信号数=len(old_rows), 全体計算の既知信号数=len(full_rows),
                            診断再生成信号数=len(diagnostic_rows), 診断再生成と全体一致=True,
                            旧打切りだけの公開時刻=[iso(t) for t in old_rows.loc[old_rows.seq.isin(old_keys-full_keys), 'time_s']]))
    result = dict(原因切分け合格=True, API取得数=0, 損益計算=False, ソース変更=False,
                  自銘柄の最後の特徴時刻=iso(last_own_feature), 他銘柄の最後の利用可能特徴時刻=iso(last_peer_feature),
                  旧上限の他銘柄最終足利用可能時刻=iso(float(before_grid.available_time_s.iloc[-1])),
                  自銘柄から60秒前を上限にした最終足利用可能時刻=iso(float(after_grid.available_time_s.iloc[-1])),
                  原因='短い入力では他銘柄の板特徴の最終時刻が足の利用時刻より早くなる。旧実装はそこまで足も切り、既に利用可能な他銘柄１分足を省く。一方、長い入力ではその足が存在するため、末尾の N17 残差条件が変わる。',
                  選択への扱い='N17/N18 は同じ上限処理を共有するため今回の採用候補から除外。これは損益による除外ではない。診断用上限変更を取引計算には適用していない。', 比較=records)
    (OUT/'N17末尾依存の原因切分け.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
