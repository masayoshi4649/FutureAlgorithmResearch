"""固定分布閾値ではなく当場過去の相対尺度で、価格拒否後の板確認を待つ。"""

import numpy as np
import pandas as pd

from board_signals import make_features


def candidates(board: pd.DataFrame, ready: dict, opening: float, p2: np.ndarray) -> dict[str, np.ndarray]:
    """機能: P2候補後に新鮮な板を待ち、過去20分で相対化した支持を確認する。

    引数: board(pd.DataFrame)、ready(dict)、opening(float)、p2(ndarray)。
    返り値: 即時/鮮度/表示変化/近接量確認のNx3候補(dict[str,np.ndarray])。
    120秒又は5000原本行を越えた確認は破棄し、未来の確認を過去へ戻さない。
    """
    frame = make_features(board, ready)
    clock = pd.to_datetime(frame['time_s'].to_numpy(), unit='s', utc=True)
    for name in ('display_flow', 'near_balance'):
        prior = frame[name].abs().set_axis(clock).rolling('20min', closed='left', min_periods=60).quantile(.75)
        frame[f'{name}_scale'] = prior.to_numpy()
    seqs, times = frame['seq'].to_numpy(), frame['time_s'].to_numpy()
    result = {'P2': p2.copy()}
    found = {'WAIT': [], 'FLOW': [], 'DEPTH': []}
    for candidate in p2:
        origin, side, width = int(candidate[0]), int(candidate[1]), float(candidate[2])
        source_seq, source_time = ready['seq'][origin], ready['time_s'][origin]
        start = int(np.searchsorted(seqs, source_seq, side='left'))
        # 原候補時点の中値を、相対する現在板の原本行から厳密に取り出す。
        same = start < len(frame) and seqs[start] == source_seq
        if not same:
            # P2は分の先頭公開行なので通常一致。不明なら別行の中値で補わない。
            continue
        initial_mid = float(frame.iloc[start]['mid'])
        selected = {'WAIT': False, 'FLOW': False, 'DEPTH': False}
        for j in range(start, len(frame)):
            row = frame.iloc[j]
            if times[j] - source_time > 120. or seqs[j] - source_seq > 5000:
                break
            if side * (row['mid'] - initial_mid) < -.5 * width:
                break
            if not row['valid'] or row['ask'] - row['bid'] > .15 * width:
                continue
            eligibility = {'WAIT': True,
                'FLOW': (row['display_flow_scale'] > 0 and side * row['display_flow'] >= row['display_flow_scale']
                         and side * row['near_balance'] >= 0 and side * (row['mid'] - initial_mid) >= ready['tick']),
                'DEPTH': (row['near_balance_scale'] > 0 and side * row['near_balance'] >= row['near_balance_scale']
                          and side * row['display_flow'] >= 0 and side * (row['mid'] - initial_mid) >= ready['tick'])}
            for name in found:
                if not selected[name] and eligibility[name]:
                    found[name].append((int(row['i']), side, width))
                    selected[name] = True
            if all(selected.values()):
                break
    for name, rows in found.items():
        grouped = {}
        for index, side, width in rows:
            grouped.setdefault(index, []).append((side, width))
        chosen = [(index, values[0][0], values[0][1]) for index, values in sorted(grouped.items())
                  if len({side for side, _ in values}) == 1]
        result[name] = np.asarray(chosen, float).reshape(-1, 3)
    return result


def methods() -> list[dict]:
    """機能: 固定24条件の事前一覧を作る。

    引数: なし。
    返り値: 四入口×三出口×二約定方式の一覧(list[dict])。
    """
    return [dict(id=f'R3_{family}_{exit_id}_{"passive" if passive else "quote"}', family=family,
                 exit_mode=mode, exit_id=exit_id, minutes=60, fraction=.001, initial_fraction=.5,
                 pyramid=False, cooldown_minutes=10, passive_entry=passive, primary=False,
                 reference_only=passive, name=f'{family}・出口{exit_id}・新規{"指値仮定" if passive else "成行"}')
            for family in ('P2', 'WAIT', 'FLOW', 'DEPTH') for exit_id, mode in (('T', 0), ('C', 1), ('R', 2))
            for passive in (False, True)]
