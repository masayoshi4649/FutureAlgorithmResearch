"""旧E01の二つの入口時点を、104と同じ公開価格窓で事後分類する。"""

import numpy as np


WINDOWS = (10, 30, 60)
UNKNOWN_NAMES = {1: '過去基準なし', 2: '公表終点の資格またはBBO不明',
    4: '過去基準の資格またはBBO不明', 8: '基準の経過超過',
    16: '区間内の価格reset・不正気配・原seq断裂', 32: '公表時計間隔15秒超'}


def public_windows(raw: dict, public: dict, tick: float, policy: dict) -> dict:
    """
    機能: 104の10/30秒と同じ資格・基準式で、追加60秒も測る。
    引数: raw/public/policy(dict)、tick(float)は保存原行と公開規則。
    返り値: dictは窓別のBBO変化・未知・曖昧・系譜。新注文を生成しない。
    """
    assert tick > 0 and policy['max_public_gap_seconds'] == policy['baseline_extra_age_seconds'] == 15.
    rows, times = public['rows'], public['times']; n, count = len(raw['raw_seq']), len(rows)
    bad = ~raw['bbo_valid'] | ~np.isfinite(raw['price_time_s']) | (raw['price_reset_reason'] != 0)
    if n > 1:
        bad[1:] |= raw['raw_seq'][1:] != raw['raw_seq'][:-1]+1
        bad[1:] |= raw['price_time_s'][1:] < raw['price_time_s'][:-1]
    bad_prefix = np.r_[0, np.cumsum(bad.astype(np.int64))]
    gap = np.zeros(count, bool)
    if count > 1:
        gap[1:] = np.diff(times) > 15.
    gap_prefix = np.r_[0, np.cumsum(gap.astype(np.int64))]
    result = {}
    for window in WINDOWS:
        index = np.searchsorted(times, times-window, side='right')-1; available = index >= 0
        ref = np.full(count, -1, np.int64); ref[available] = rows[index[available]]
        ref_seq = np.full(count, -1, np.int64); ref_seq[available] = raw['raw_seq'][ref[available]]
        ref_time, db, da, ref_spread = (np.full(count, np.nan) for _ in range(4))
        ref_time[available] = raw['price_time_s'][ref[available]]
        spread = (raw['ask'][rows]-raw['bid'][rows])/tick
        db[available] = (raw['bid'][rows[available]]-raw['bid'][ref[available]])/tick
        da[available] = (raw['ask'][rows[available]]-raw['ask'][ref[available]])/tick
        ref_spread[available] = (raw['ask'][ref[available]]-raw['bid'][ref[available]])/tick
        reasons = np.zeros(count, np.uint16)
        reasons[~available] |= 1
        reasons[~(raw['qualified'][rows] & raw['bbo_valid'][rows])] |= 2
        reference_ok = np.zeros(count, bool)
        reference_ok[available] = raw['qualified'][ref[available]] & raw['bbo_valid'][ref[available]]
        reasons[available & ~reference_ok] |= 4
        reasons[available & (times-ref_time > window+15.)] |= 8
        positions = np.flatnonzero(available)
        reasons[positions[(bad_prefix[rows[available]+1]-bad_prefix[ref[available]]) > 0]] |= 16
        reasons[positions[(gap_prefix[positions+1]-gap_prefix[index[available]+1]) > 0]] |= 32
        known = reasons == 0
        spread_ambiguous = spread > np.maximum(policy['spread_max_ticks'], ref_spread+policy['spread_increment_ticks'])
        sign_ambiguous = ((db > 0) & (da < 0)) | ((db < 0) & (da > 0))
        ambiguous = known & (spread_ambiguous | sign_ambiguous)
        direction = np.full(count, 3, np.int8); ordinary = known & ~ambiguous
        direction[ordinary] = 0; direction[ordinary & (db >= 1) & (da >= 1)] = 1
        direction[ordinary & (db <= -1) & (da <= -1)] = -1; direction[ambiguous] = 2
        result[str(window)] = dict(window_seconds=window, public_rows=rows, source_raw_seq=public['raw_seq'],
            source_time_s=times, reference_public_index=index, reference_raw_row=ref,
            reference_raw_seq=ref_seq, reference_time_s=ref_time, bid_change_ticks=db, ask_change_ticks=da,
            current_spread_ticks=spread, reference_spread_ticks=ref_spread, unknown_reason=reasons,
            ambiguous=ambiguous, ambiguous_spread=known & spread_ambiguous,
            ambiguous_sign=known & sign_ambiguous, direction_t1=direction)
    return dict(windows=result, public=public, raw_bad_prefix=bad_prefix)


def quote(raw: dict, row: int) -> dict:
    """
    機能: 原行の整数seq・価格代理時計・BBOを小辞書へ抜き出す。
    引数: raw(dict)、row(int)は既存原行の位置。
    返り値: dictは当時の価格。欠測を0や後続正常行で補完しない。
    """
    return dict(raw_row=row, raw_seq=int(raw['raw_seq'][row]),
        price_time_s=float(raw['price_time_s'][row]) if np.isfinite(raw['price_time_s'][row]) else None,
        bid=float(raw['bid'][row]) if np.isfinite(raw['bid'][row]) else None,
        ask=float(raw['ask'][row]) if np.isfinite(raw['ask'][row]) else None)


def observe(raw: dict, features: dict, candidate_time: float, window: int,
            candidate_row: int | None = None, strictpast: bool = True) -> dict:
    """
    機能: 候補当時のfirst-newmax価格窓を選び、自己・厳密過去相手を区別する。
    引数: raw/features(dict)、candidate_time(float)、window(int)、candidate_row(int|None)、strictpast(bool)。
    返り値: dictは当時状態と基準BBO。自己の同時計後半は公表窓へ混ぜない。
    """
    assert window in WINDOWS
    result = dict(known=False, state='UNKNOWN', window_seconds=window, selection_unknown_reason=0,
        unknown_reason=None, ambiguous=False, own_tail_unknown=False,
        direction=None, source=None, reference=None, age_seconds=None,
        bid_change_ticks=None, ask_change_ticks=None, reference_age_seconds=None)
    if not np.isfinite(candidate_time):
        result['selection_unknown_reason'] = 1
        return result
    public = features['public']; position = int(np.searchsorted(public['times'], candidate_time,
        side='left' if strictpast else 'right')-1)
    if candidate_row is not None:
        position = min(position, int(np.searchsorted(public['rows'], candidate_row, side='right')-1))
    if position < 0:
        result['selection_unknown_reason'] = 1
        return result
    source_row = int(public['rows'][position]); value = features['windows'][str(window)]
    age = float(candidate_time-value['source_time_s'][position])
    fresh = (0 < age <= 15.) if strictpast else (0 <= age <= 15.)
    source = quote(raw, source_row); ref_row = int(value['reference_raw_row'][position])
    result.update(source=source, reference=quote(raw, ref_row) if ref_row >= 0 else None,
        age_seconds=age, unknown_reason=int(value['unknown_reason'][position]),
        ambiguous=bool(value['ambiguous'][position]), selection_unknown_reason=0 if fresh else 2,
        bid_change_ticks=float(value['bid_change_ticks'][position]) if np.isfinite(value['bid_change_ticks'][position]) else None,
        ask_change_ticks=float(value['ask_change_ticks'][position]) if np.isfinite(value['ask_change_ticks'][position]) else None,
        reference_age_seconds=float(candidate_time-value['reference_time_s'][position]) if ref_row >= 0 else None)
    if candidate_row is not None:
        assert source_row <= candidate_row
        tail_bad = (features['raw_bad_prefix'][candidate_row+1]-features['raw_bad_prefix'][source_row]) > 0
        result['own_tail_unknown'] = bool(tail_bad)
    if not fresh or result['unknown_reason'] or result['own_tail_unknown']:
        return result
    if result['ambiguous']:
        result['state'] = 'AMBIGUOUS'
        return result
    direction = int(value['direction_t1'][position]); assert direction in (-1, 0, 1)
    result.update(known=True, direction=direction, state={-1:'DOWN', 0:'NEUTRAL', 1:'UP'}[direction])
    if strictpast:
        assert source['price_time_s'] < candidate_time
    else:
        assert source['price_time_s'] <= candidate_time and source_row <= candidate_row
    return result


def acceptance(own: dict, peer: dict, side: int, mode: str) -> tuple[bool, str]:
    """
    機能: 相手反対なしと両市場支持を、未知・曖昧を救済せず分類する。
    引数: own/peer(dict)は観測状態、side(int)は元新規方向、mode(str)はNまたはP。
    返り値: tuple[bool,str]は静的採否と理由。最終利益を条件へ渡さない。
    """
    assert side in (-1, 1) and mode in ('N', 'P')
    required = [peer] if mode == 'N' else [own, peer]
    if any(x['state'] == 'UNKNOWN' for x in required):
        return False, 'UNKNOWN'
    if any(x['state'] == 'AMBIGUOUS' for x in required):
        return False, 'AMBIGUOUS'
    assert all(x['known'] for x in required)
    if mode == 'N':
        return (True, '採用') if peer['direction'] != -side else (False, '相手逆方向')
    return (True, '採用') if own['direction'] == peer['direction'] == side else (False, '同方向支持なし')


def compare_legacy(features: dict, legacy: dict) -> int:
    """
    機能: 追加60秒以外の10/30秒全列を、不変104保存窓と完全照合する。
    引数: features/legacy(dict)は新分類窓と保存104peer_features。
    返り値: intは同値列数。不一致なら分類実行を失敗として保持する。
    """
    count = 0
    for window in ('10', '30'):
        for key, expected in legacy['windows'][window].items():
            if key == 'direction_t2':
                continue
            actual = features['windows'][window][key]
            if isinstance(expected, np.ndarray):
                np.testing.assert_array_equal(actual, expected, err_msg=window+'/'+key)
            else:
                assert actual == expected
            count += 1
    return count

