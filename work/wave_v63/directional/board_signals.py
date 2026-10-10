"""同じ銘柄の過去公開板だけから、供給確認と価格維持の候補を作る。"""

import numpy as np
import pandas as pd

from signals import width_of


def make_features(board: pd.DataFrame, ready: dict) -> pd.DataFrame:
    """機能: 公開済み板ブロックを60秒集計し、執行代理・表示変化・気配方向を分ける。

    引数: board(pd.DataFrame)、ready(dict)。
    返り値: 因果的な同銘柄の公開特徴(pd.DataFrame)。last/ATR列を参照しない。
    """
    cols = ['exec_buy', 'exec_sell', 'exec_unknown', 'noexec_bid_add', 'noexec_bid_remove',
            'noexec_ask_add', 'noexec_ask_remove', 'refill_bid', 'refill_ask', 'both_up', 'both_down',
            'valid_events', 'continuity_resets', 'depth_disordered_events', 'depth_duplicate_events',
            'depth_incomplete_events', 'volume_resets']
    clock = pd.to_datetime(board['time_s'].to_numpy(), unit='s', utc=True)
    sums = board[cols].set_axis(clock).rolling('60s', closed='both', min_periods=3).sum().reset_index(drop=True)
    out = board[['seq', 'time_s', 'source_last_seq', 'source_age', 'bid', 'ask', 'mid']].reset_index(drop=True).copy()
    out['i'] = np.searchsorted(ready['seq'], out['seq'])
    np.testing.assert_array_equal(ready['seq'][out['i']], out['seq'])
    assert (out['source_last_seq'] < out['seq']).all()
    volume = sums['exec_buy'] + sums['exec_sell'] + sums['exec_unknown']
    out['pressure'] = (sums['exec_buy'] - sums['exec_sell']) / volume.where(volume > 0)
    out['known_fraction'] = (sums['exec_buy'] + sums['exec_sell']) / volume.where(volume > 0)
    total_change = sums[['noexec_bid_add', 'noexec_bid_remove', 'noexec_ask_add', 'noexec_ask_remove']].sum(axis=1)
    out['display_flow'] = (sums['noexec_bid_add'] - sums['noexec_bid_remove']
                           - sums['noexec_ask_add'] + sums['noexec_ask_remove']) / total_change.where(total_change > 0)
    near_total = board['supply_bid_near'].to_numpy() + board['supply_ask_near'].to_numpy()
    out['near_balance'] = (board['supply_bid_near'].to_numpy() - board['supply_ask_near'].to_numpy()) / np.where(near_total > 0, near_total, np.nan)
    refill = sums['refill_bid'] + sums['refill_ask']
    out['refill_balance'] = (sums['refill_bid'] - sums['refill_ask']) / refill.where(refill > 0)
    out['quote_direction'] = sums['both_up'] - sums['both_down']
    prior = np.searchsorted(out['time_s'].to_numpy(), out['time_s'].to_numpy() - 60., side='right') - 1
    out['ret60'] = np.where(prior >= 0, out['mid'].to_numpy() - out['mid'].to_numpy()[np.maximum(prior, 0)], np.nan)
    bad = sums[['continuity_resets', 'depth_disordered_events', 'depth_duplicate_events',
                'depth_incomplete_events', 'volume_resets']].sum(axis=1)
    out['valid'] = (out['source_age'].between(0, 5) & out['time_s'].ge(ready['start'] + 120)
                    & sums['valid_events'].gt(0) & bad.eq(0) & out['ret60'].notna())
    return out


def candidates(board: pd.DataFrame, ready: dict, opening: float, p2: np.ndarray) -> dict[str, np.ndarray]:
    """機能: P2への同価格供給ゲートと板固有の継続/維持候補を作る。

    引数: board(pd.DataFrame)、ready(dict)、opening(float)、p2(ndarray)。
    返り値: 五入口のNx3配列(dict[str,np.ndarray])。受信順は同銘柄の原本seqだけで決める。
    """
    frame = make_features(board, ready)
    width = width_of(opening, ready['tick'])
    found = {'P2': p2.copy()}
    pos = np.searchsorted(frame['seq'].to_numpy(), ready['seq'][p2[:, 0].astype(int)], side='right') - 1
    valid = pos >= 0
    chosen = np.maximum(pos, 0)
    valid &= frame['valid'].to_numpy()[chosen]
    valid &= ready['time_s'][p2[:, 0].astype(int)] - frame['time_s'].to_numpy()[chosen] <= 10.
    found['P2D'] = p2[valid & (frame['near_balance'].to_numpy()[chosen] * p2[:, 1] >= .2)]
    found['P2F'] = p2[valid & (frame['display_flow'].to_numpy()[chosen] * p2[:, 1] >= .25)
                       & (frame['quote_direction'].to_numpy()[chosen] * p2[:, 1] >= 0)]
    gate = frame['valid'] & (frame['ask'] - frame['bid']).le(.15 * width) & frame['known_fraction'].ge(.5)
    masks = {
        'B1': (gate & frame['pressure'].ge(.25) & frame['display_flow'].ge(0)
                & frame['quote_direction'].ge(2) & frame['ret60'].ge(2 * ready['tick']),
                gate & frame['pressure'].le(-.25) & frame['display_flow'].le(0)
                & frame['quote_direction'].le(-2) & frame['ret60'].le(-2 * ready['tick'])),
        'B2': (gate & frame['pressure'].le(-.5) & frame['ret60'].ge(0)
                & frame['refill_balance'].ge(.4) & frame['near_balance'].ge(.2),
                gate & frame['pressure'].ge(.5) & frame['ret60'].le(0)
                & frame['refill_balance'].le(-.4) & frame['near_balance'].le(-.2))}
    for name, (buy, sell) in masks.items():
        raw_side = np.where(buy & ~sell, 1, np.where(sell & ~buy, -1, 0))
        fresh = (raw_side != 0) & (raw_side != np.r_[0, raw_side[:-1]])
        found[name] = np.column_stack((frame.loc[fresh, 'i'], raw_side[fresh], np.full(int(fresh.sum()), width))).astype(float)
    return found


def methods() -> list[dict]:
    """機能: 板確認五入口・三出口・二新規約定の30条件を固定列挙する。

    引数: なし。
    返り値: 条件一覧(list[dict])。passiveは通過約定の追加仮定として主quoteから分ける。
    """
    return [dict(id=f'R2_{family}_{exit_id}_{"passive" if passive else "quote"}', family=family,
                 exit_mode=mode, exit_id=exit_id, minutes=60, fraction=.001, initial_fraction=.5,
                 pyramid=False, cooldown_minutes=10, passive_entry=passive, primary=False,
                 reference_only=passive, name=f'{family}・出口{exit_id}・新規{"指値仮定" if passive else "成行"}')
            for family in ('P2', 'P2D', 'P2F', 'B1', 'B2') for exit_id, mode in (('T', 0), ('C', 1), ('R', 2))
            for passive in (False, True)]
