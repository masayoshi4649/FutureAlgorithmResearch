"""20入口の旧条件同一性と、未来を切り落としたときの一致を監査する。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import signals as s


def plain(value):
    """機能: 非有限数を空値へ統一し、同一性比較可能なJSON値を作る。

    引数: value (object)。返り値: JSON互換値 (object)。
    """
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def canonical(frame: pd.DataFrame) -> str:
    """機能: イベント全属性を順序付き日本語JSONへ変換する。

    引数: frame (DataFrame)。返り値: 安定したJSON文字列 (str)。
    """
    return json.dumps(plain(frame.to_dict('records')), ensure_ascii=False, sort_keys=True, allow_nan=False)


def main() -> None:
    """機能: 12入力の旧６条件・20条件打切り・出口状態打切りを検査する。

    引数: なし。返り値: なし (None)。
    """
    inputs = s.load_inputs()
    baseline_records, prefix_records, state_records, atr_records = [], [], [], []
    mapping = {'T01': 'S01', 'T02': 'S03', 'T03': 'S05', 'T06': 'S06', 'T12': 'S09', 'T13': 'S17'}
    for (session, symbol), item in inputs.items():
        f, peer, full = item['features'], item['peer_features'], item['events']
        old_root = s._old.ROOT
        try:
            s._old.ROOT = s.ROOT/'work'/'wave_v9'/'live' if session == s.SESSIONS[-1] else s.ROOT
            old, _ = s._old.build_events(session, symbol, f, peer)
        finally:
            s._old.ROOT = old_root
        for old_id, new_id in mapping.items():
            actual = full.loc[full.family.eq(new_id)].reset_index(drop=True)
            expected = old.loc[old.family.eq(old_id)].copy().reset_index(drop=True)
            expected['family'] = new_id
            expected['event_id'] = expected.event_id.str.replace(':'+old_id+':', ':'+new_id+':', regex=False)
            assert canonical(actual) == canonical(expected), (session, symbol, new_id)
            baseline_records.append(dict(セッション=session, 銘柄=symbol, 旧信号=old_id, 新信号=new_id,
                                         イベント数=len(actual), 全属性完全一致=True))

        # ----------------------------------------
        # 最終結果を含む未来の特徴・板を読めない状態でも、確定済みイベントと出口状態は同じになる。
        tape = item['tape']
        for fraction in [.35, .7]:
            end = int(len(tape['seq'])*fraction)
            short_tape = {key: value[:end] if np.ndim(value) else value for key, value in tape.items()}
            last_seq, last_time = int(short_tape['seq'][-1]), float(short_tape['time_s'][-1])
            own_short = f.loc[f.seq <= last_seq]
            peer_short = peer.loc[peer.time_s+60 <= last_time]
            for mode, supplied_peer in [('自銘柄打切り', peer), ('両銘柄打切り', peer_short)]:
                actual, _ = s.build_events(session, symbol, own_short, supplied_peer, cutoff=last_time)
                expected = full.loc[full.seq <= last_seq].reset_index(drop=True)
                assert canonical(actual) == canonical(expected), (session, symbol, fraction, mode)
                prefix_records.append(dict(セッション=session, 銘柄=symbol, 打切比率=fraction, モード=mode,
                                           最終生板行=last_seq, イベント数=len(actual), 全属性完全一致=True))
            z = s.price_grid(session, symbol, last_time)
            state = s.state_at(short_tape, own_short, z)
            for key in state:
                assert np.allclose(state[key], item['state'][key][:end], equal_nan=True), (session, symbol, fraction, key)
            state_records.append(dict(セッション=session, 銘柄=symbol, 打切比率=fraction, 比較配列数=len(state),
                                      生板行数=end, 全属性完全一致=True))
            atr = s.atr_at(session, symbol, short_tape['time_s'], cutoff=last_time)
            assert np.allclose(atr, short_tape['atr'], equal_nan=True)
            atr_records.append(dict(セッション=session, 銘柄=symbol, 打切比率=fraction, 一致=True))
        empty, _ = s.build_events(session, symbol, f.iloc[:0], peer)
        assert empty.empty
        no_peer, _ = s.build_events(session, symbol, f)
        assert not no_peer.family.isin(['S16', 'S17', 'S18']).any()
        assert np.isfinite(tape['atr']).sum() > 0

    payload = dict(旧条件一致=baseline_records, 時間打切り一致=prefix_records,
                   出口状態一致=state_records, ATR打切り一致=atr_records,
                   全条件数=20, イベント総数=sum(len(item['events']) for item in inputs.values()),
                   空入力と他銘柄欠損確認=True, 今回API取得回数=0,
                   限界='保存済み特徴の原本SHA一致を前提とする。受信時刻の正確性・実約定は検証していない。')
    (s.OUT/'信号打切り監査.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(旧条件比較=len(baseline_records), 打切り比較=len(prefix_records),
                          状態比較=len(state_records), 結果='一致'), ensure_ascii=False))


if __name__ == '__main__':
    main()
