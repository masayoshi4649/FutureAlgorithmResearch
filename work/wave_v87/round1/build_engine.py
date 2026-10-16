"""凍結済み利確後再参加へ、新しい根拠と高安突破の条件だけを追加する。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'wave_v86/phase2/engine.py'


def replace_once(text, old, new):
    """
    機能: 期待した一箇所だけを変更して旧研究の変更を防ぐ。
    引数: text/old/new(str)。
    返り値: str。
    """
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new, 1)


def build():
    """
    機能: 次の同方向再参加まで有効な条件を独立した再生器へ挿入する。
    引数: なし。
    返り値: str の生成先。新しい損益を計算しない。
    """
    text = SOURCE.read_text(encoding='utf-8')
    text = replace_once(text, 'cooldown_seconds, profit_fast_enabled):',
        'cooldown_seconds, profit_fast_enabled, reentry_filter):')
    text = replace_once(text, '    ns_ready_after=-np.inf', '''    restart_active = False
    restart_side = 0
    restart_row = -1
    restart_extreme = np.nan
    restart_seen_row = -1
    actual_extreme = np.nan
    restart_events = np.zeros((24000, 10))
    restart_count = 0
    ns_ready_after=-np.inf''')
    text = replace_once(text, '    for i in range(n):\n        if feedback_row >= 0:', '''    for i in range(n):
        # ----------------------------------------
        # 実組の保有中の現在値だけで極値を更新する。返済観測を含む。
        if not closed and np.isfinite(price[i]) and price[i] > 0:
            actual_extreme = max(actual_extreme, price[i]) if d > 0 else min(actual_extreme, price[i])
        # 欠測や古いEMAは非支持の観測に数えない。
        if restart_active and restart_seen_row < 0 and i > restart_row and ema_valid[i] and ema_direction[i] != restart_side and ema_source[i] > restart_row and ema_peer_source[i] > restart_row:
            restart_seen_row = i
            if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
            restart_events[restart_count,:] = np.array([i, 2, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], state[i], np.nan])
            restart_count += 1
        restart_ok = True
        if restart_active and state[i] == restart_side and reentry_filter & 1:
            restart_ok = restart_seen_row >= 0 and ema_valid[i] and ema_direction[i] == restart_side and ema_source[i] > restart_row and ema_peer_source[i] > restart_row
        if feedback_row >= 0:''')
    text = replace_once(text,
        '        ns_allow[i] = closed and (not profit_restart_pending or (not quiet[i] and not quiet_force[i]))',
        '        ns_allow[i] = closed and restart_ok and (not profit_restart_pending or (not quiet[i] and not quiet_force[i]))')
    # ----------------------------------------
    # 再突破は通常の反発追跡線へ重ねる。準備後の極値更新でも線を緩めない。
    for prefix in ('ns', 'xs'):
        old = f'                    {prefix}_changed = shadow_original.rounded({prefix}_pending_extreme + {prefix}_pending_d * {prefix}_par[1] * {prefix}_pending_atr, tick, {prefix}_pending_d)'
        new = old + f'''
                    if restart_active and reentry_filter & 2 and {prefix}_pending_d == restart_side:
                        boundary = restart_extreme + restart_side * tick
                        {prefix}_changed = max({prefix}_changed, boundary) if restart_side > 0 else min({prefix}_changed, boundary)'''
        text = replace_once(text, old, new)
        old = f'                        {prefix}_pending_level = shadow_original.rounded({prefix}_p + {prefix}_pending_d * {prefix}_par[1] * {prefix}_pending_atr, tick, {prefix}_pending_d)'
        new = old + f'''
                        if restart_active and reentry_filter & 2 and {prefix}_pending_d == restart_side:
                            boundary = restart_extreme + restart_side * tick
                            {prefix}_pending_level = max({prefix}_pending_level, boundary) if restart_side > 0 else min({prefix}_pending_level, boundary)'''
        text = replace_once(text, old, new)
    text = replace_once(text, '        if xs_allow[i]: profit_restart_pending=False', '''        if xs_allow[i]:
            profit_restart_pending=False
            if restart_active:
                if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
                restart_events[restart_count,:] = np.array([i, 3, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], state[i], ns_pending_level])
                restart_count += 1''')
    text = replace_once(text, '                    actual_anchor = fill', '''                    actual_anchor = fill
                    actual_extreme = p
                    if restart_active:
                        if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
                        restart_events[restart_count,:] = np.array([i, 4, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], d, fill])
                        restart_count += 1
                    restart_active = False''')
    text = replace_once(text, '            if use_fast:\n                feedback_row = i', '''            if use_fast:
                restart_active = True
                restart_side = int(cycles[cc - 1, 8])
                restart_row = i
                restart_extreme = actual_extreme
                restart_seen_row = -1
                if restart_count >= len(restart_events): raise ValueError('再参加条件証跡の上限です')
                restart_events[restart_count,:] = np.array([i, 1, restart_row, restart_side, restart_extreme, restart_seen_row, ema_source[i], ema_peer_source[i], state[i], np.nan])
                restart_count += 1
                feedback_row = i''')
    text = replace_once(text, 'profit_reentry_events[:profit_reentry_count])',
        'profit_reentry_events[:profit_reentry_count], restart_events[:restart_count])')
    text = text.replace('料金後に親組黒字となった全返済だけ、早期再参加を許す別生成器。',
        '料金後黒字の再参加へ、新しい同調周期と前組高安突破を加える別生成器。')
    path = HERE / 'engine.py'
    path.write_text(text, encoding='utf-8')
    return str(path)


if __name__ == '__main__':
    print(build())
