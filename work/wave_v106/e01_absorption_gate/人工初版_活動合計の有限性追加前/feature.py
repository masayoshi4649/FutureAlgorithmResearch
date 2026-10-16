"""公開済み自己原行だけで、同価格逆板の表示維持と方向更新の不一致を測る。"""

import math

import catalog


def number(value: object) -> bool:
    """
    機能: 有限な正の観測数値を判定する。
    引数: value(object)は原観測値。
    返り値: boolは有効な正数か。不明を0へ補完しない。
    """
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def measure(raw: dict, context: dict, row: int, side: int, base: dict) -> dict:
    """
    機能: 公開原行までの末尾同価格区間の表示維持・支持非進行・反復接触を測る。
    引数: raw/context/base(dict)は原配列・不変票数学の接頭・保存W60票、row/side(int)は公開原行と入口側。
    返り値: dictは適用資格、既知/未知、成立及び原行由来。損益と金融を使用しない。
    """
    assert side in (-1, 1)
    n = len(raw['raw_seq'])
    assert 0 <= row < n
    assert all(len(raw[name]) == n for name in catalog.FIELDS if name != 'execution_to_raw_index')
    output = dict(eligible=False, known=False, hit=None, reason=0,
                  candidate_raw_row=row, candidate_raw_seq=int(raw['raw_seq'][row]),
                  side=side, base_known=bool(base['known']),
                  base_direction_votes=base.get('direction_votes'),
                  episode_start_raw_row=None, episode_start_raw_seq=None,
                  opposite_price=None, initial_quantity=None, minimum_quantity=None,
                  support_price=None, maximum_support_advance=None,
                  touch_rows=[], touch_raw_seq=[], touch_count=None,
                  touch_activity_volume=None, touch_activity_to_initial_ratio=None,
                  window_seconds=catalog.WINDOW, first_window_raw_row=base.get('first_vote_raw_row'))
    if not base['known']:
        output['reason'] = 100+int(base['reason'])
        return output
    if base['direction_votes'] < 2:
        output.update(known=True, hit=False, reason=200)
        return output
    output['eligible'] = True
    assert base['window_seconds'] == catalog.WINDOW
    assert base['candidate_raw_row'] == row
    assert base['candidate_raw_seq'] == int(raw['raw_seq'][row])
    assert base['candidate_price_time_s'] == float(raw['price_time_s'][row])
    first = int(base['first_vote_raw_row'])
    assert 0 <= first <= row
    opposite_name, quantity_name, support_name = (
        ('ask', 'ask_qty', 'bid') if side > 0 else ('bid', 'bid_qty', 'ask'))
    p = raw[opposite_name][row]
    if not number(p):
        output['reason'] = 301
        return output
    # ----------------------------------------
    # 末尾同価格区間を、公開済み原行だけから決める。外側数量は境界判定に使わない。
    begin = row
    while begin > first:
        previous_price = raw[opposite_name][begin-1]
        if not number(previous_price):
            output['reason'] = 302
            return output
        if float(previous_price) != float(p):
            break
        begin -= 1
    output.update(episode_start_raw_row=begin,
                  episode_start_raw_seq=int(raw['raw_seq'][begin]), opposite_price=float(p))
    reasons = 0
    for j in range(begin, row+1):
        bid, ask = raw['bid'][j], raw['ask'][j]
        if not (number(bid) and number(ask) and float(bid) < float(ask)):
            reasons |= 1
        if not (number(raw['bid_qty'][j]) and number(raw['ask_qty'][j])
                and bool(raw['best_quantity_valid'][j]) and bool(raw['price_row_valid'][j])):
            reasons |= 2
        if not math.isfinite(float(raw['price_time_s'][j])) or context['clock_reverse'][j]:
            reasons |= 4
        if (not bool(raw['volume_delta_usable'][j]) or int(raw['volume_reset_reason'][j]) != 0
                or not math.isfinite(float(raw['volume_delta'][j])) or float(raw['volume_delta'][j]) < 0):
            reasons |= 8
        if j > begin:
            if (int(raw['raw_seq'][j]) != int(raw['raw_seq'][j-1])+1
                    or float(raw['price_time_s'][j]) < float(raw['price_time_s'][j-1])
                    or not bool(raw['price_transition_valid'][j])):
                reasons |= 16
        assert float(raw[opposite_name][j]) == float(p)
    if reasons:
        output['reason'] = 400+reasons
        return output
    # ----------------------------------------
    # 表示数量と支持気配の過去最大を固定初期値へ比べる。将来の回復を参照しない。
    initial = float(raw[quantity_name][begin])
    minimum = min(float(raw[quantity_name][j]) for j in range(begin, row+1))
    support = float(raw[support_name][begin])
    advance = max(side*(float(raw[support_name][j])-support) for j in range(begin, row+1))
    touches = []
    for j in range(begin+1, row+1):
        positive = math.isfinite(float(raw['volume_delta'][j])) and float(raw['volume_delta'][j]) > 0
        if (positive and int(context['direction'][j]) == side
                and number(raw['last'][j]) and float(raw['last'][j]) == float(p)):
            touches.append(j)
    activity = sum(float(raw['volume_delta'][j]) for j in touches)
    hit = (minimum >= initial and advance <= 0 and len(touches) >= catalog.MINIMUM_TOUCHES
           and activity >= initial*catalog.MINIMUM_ACTIVITY_RATIO)
    output.update(known=True, hit=bool(hit), initial_quantity=initial, minimum_quantity=minimum,
                  support_price=support, maximum_support_advance=advance,
                  touch_rows=touches, touch_raw_seq=[int(raw['raw_seq'][j]) for j in touches],
                  touch_activity_volume=activity, touch_activity_to_initial_ratio=activity/initial,
                  touch_count=len(touches), reason=0)
    return output
