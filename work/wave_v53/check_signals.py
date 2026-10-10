"""売買成績を読まず、入口候補と自動選択の実行・公開順・未来不変性を監査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

import signals


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wave_v52/measurement'))
from quotes import load_inputs_only


def compare(left: np.ndarray, right: np.ndarray) -> None:
    """機能: NaNの位置を含め、数値配列の完全一致を検査する。

    引数: left/right(ndarray)。返り値: なし(None)。近似誤差を許容しない。
    """
    np.testing.assert_array_equal(left, right)


def changed_future(frame: pd.DataFrame, cutoff: int) -> pd.DataFrame:
    """機能: 指定位置以後の価格と板状態だけを変更した反証用入力を作る。

    引数: frame(DataFrame)、cutoff(int)。返り値: 未来部分だけが違う表(DataFrame)。
    公開時刻・原本行といった識別情報は保持する。
    """
    changed = frame.copy(deep=True)
    suffix = changed.index[cutoff:]
    price_columns = ('open', 'high', 'low', 'close', 'prev_open', 'prev_high', 'prev_low', 'prev_close',
                     'ema8', 'ema21', 'ema21_lag5', 'prior20_high', 'prior20_low',
                     'or30_high', 'or30_low', 'swing_high', 'swing_low', 'vwap_proxy',
                     'prev_vwap_proxy', 'vwap_proxy_lag5', 'mean20', 'prev_mean20')
    for name in price_columns:
        changed.loc[suffix, name] = changed.loc[suffix, name] * 1.25 + 500.
    for name in ('execution', 'recovery', 'supply', 'withdrawal', 'addition', 'repricing'):
        changed.loc[suffix, name] = -changed.loc[suffix, name]
    changed.loc[suffix, 'can_trade'] = False
    changed.loc[suffix, 'board_valid'] = False
    return changed


def audit_account(key: tuple, frame: pd.DataFrame, ready: dict) -> dict:
    """機能: 12入口と自動選択を全行・途中切断・未来変更で検査する。

    引数: key(tuple)、frame(DataFrame)、ready(dict)。返り値: 口座ごとの証跡(dict)。
    """
    pristine = frame.copy(deep=True)
    choices, rows = signals.candidates(frame)
    pd.testing.assert_frame_equal(frame, pristine, check_exact=True)
    assert set(choices) == {row[0] for row in signals.FAMILIES}
    index = frame.ready_index.to_numpy(dtype=np.int64)
    compare(ready['seq'][index], frame.seq.to_numpy())
    compare(ready['time_s'][index], frame.time_s.to_numpy())
    assert (frame.source_last_seq < frame.seq).all()
    assert (frame.source_last_time < frame.time_s).all()
    assert (frame.source_bar_start + 60 <= frame.time_s).all()
    for side in ('high', 'low'):
        known = frame[f'swing_{side}_confirmed_seq'].notna()
        assert (frame.loc[known, f'swing_{side}_confirmed_seq'] <= frame.loc[known, 'seq']).all()
        assert (frame.loc[known, f'swing_{side}_confirmed_time'] <= frame.loc[known, 'time_s']).all()
    known = frame.peer_time_s.notna()
    assert (frame.loc[known, 'peer_time_s'] <= frame.loc[known, 'time_s'] - 60.).all()
    assert ((frame.loc[known, 'peer_age'] >= 0) & (frame.loc[known, 'peer_age'] <= 60)).all()
    candidates_count, invalidation_inside = {}, {}
    for family, values in choices.items():
        assert values.shape == (len(frame), 3)
        assert np.isin(values[:, 0], (-1, 0, 1)).all()
        assert (values[~frame.can_trade.to_numpy(), 0] == 0).all()
        active = values[:, 0] != 0
        assert np.isfinite(values[active, 1]).all()
        candidates_count[family] = int(active.sum())
        invalidation_inside[family] = int((values[active, 0] * (frame.close.to_numpy()[active] - values[active, 1]) <= 0).sum())
    families = [row[0] for row in signals.FAMILIES] + ['AUTO']
    full, counts = {}, {}
    for family in families:
        for confirmation in (False, True):
            decisions, trace = signals.make_decisions(frame, choices, rows, family, confirmation)
            assert decisions.shape == (len(frame), 11) and len(trace) == len(frame)
            compare(decisions[:, 0], index)
            assert np.isin(decisions[:, 1], (-1, 0, 1)).all()
            assert np.isin(decisions[:, 2], (-1, 0, 1)).all()
            assert ((decisions[:, 1] == 0) | (decisions[:, 1] == decisions[:, 2])).all()
            assert (decisions[~frame.can_trade.to_numpy(), 1:3] == 0).all()
            assert all(item['足の最終原本行'] < item['原本行'] for item in trace)
            full[(family, confirmation)] = decisions, trace
            counts[f'{family}_{int(confirmation)}'] = dict(候補=int(np.count_nonzero(decisions[:, 2])),
                                                           新規許可=int(np.count_nonzero(decisions[:, 1])))
    prefix_checks = []
    for fraction in (.35, .75):
        cutoff = max(1, int(len(frame) * fraction))
        partial = frame.iloc[:cutoff].copy()
        part_choices, part_rows = signals.candidates(partial)
        modified = changed_future(frame, cutoff)
        future_choices, future_rows = signals.candidates(modified)
        for family in choices:
            compare(choices[family][:cutoff], part_choices[family])
            compare(choices[family][:cutoff], future_choices[family][:cutoff])
        for family in families:
            for confirmation in (False, True):
                decisions, trace = signals.make_decisions(partial, part_choices, part_rows, family, confirmation)
                compare(full[(family, confirmation)][0][:cutoff], decisions)
                assert full[(family, confirmation)][1][:cutoff] == trace
                altered, altered_trace = signals.make_decisions(modified, future_choices, future_rows, family, confirmation)
                compare(full[(family, confirmation)][0][:cutoff], altered[:cutoff])
                assert full[(family, confirmation)][1][:cutoff] == altered_trace[:cutoff]
        prefix_checks.append(dict(比率=fraction, 特徴切断行=cutoff, 最後の原本行=int(partial.seq.iloc[-1]),
                                  候補比較数=len(choices), 判断比較数=len(families) * 2,
                                  途中切断完全一致=True, 未来価格板変更完全一致=True))
    return dict(セッション=key[0], 銘柄=key[1], 行数=len(frame), 候補数=candidates_count,
                失敗線が確定終値の利益側又は同値の候補数=invalidation_inside,
                判断数=counts, 途中切断=prefix_checks, 公開行整合=True, 元特徴不変=True)


def main() -> None:
    """機能: 全46口座を監査し、例外も含めて証跡を保存する。

    引数: なし。返り値: なし(None)。取引結果や損益ファイルを開かない。
    """
    source = HERE / 'signals.py'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    features = pickle.loads((HERE / '特徴.pkl').read_bytes())
    ready = load_inputs_only()
    reports, failures = [], []
    for key, frame in features.items():
        try:
            reports.append(audit_account(key, frame, ready[key]))
            print(key[0], key[1], '合格', flush=True)
        except Exception as error:
            failures.append(dict(セッション=key[0], 銘柄=key[1], 例外種類=type(error).__name__, 内容=str(error)))
            print(key, type(error).__name__, str(error), flush=True)
    unchanged = source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    result = dict(合格=not failures and unchanged, signalsコードSHA256=source_hash,
                   合格範囲='実行成立・列整合・公開順序・未来不変性。売買の有利さと失敗線の論理的妥当性は別評価。',
                   監査中コード不変=unchanged, 特徴SHA256=hashlib.sha256((HERE / '特徴.pkl').read_bytes()).hexdigest(),
                   口座数=len(features), 合格口座数=len(reports), 候補種類数=12,
                   判断種類数='12手法＋AUTO、各確認なし/ありの26種類',
                   全数判断実行数=len(reports) * 26,
                   途中切断判断比較数=len(reports) * 26 * 2,
                   未来変更判断比較数=len(reports) * 26 * 2,
                   約定及び損益未参照=True, signals未変更=True, 失敗=failures, 口座別=reports)
    result['失敗線の向きに関する論理点検'] = {
        family: sum(row['失敗線が確定終値の利益側又は同値の候補数'][family] for row in reports)
        for family in [item[0] for item in signals.FAMILIES]}
    (HERE / '信号監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    assert result['合格'], failures


if __name__ == '__main__':
    main()
