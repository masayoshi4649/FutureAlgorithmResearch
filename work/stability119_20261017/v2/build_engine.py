"""凍結済み初回源を変更せず、執行保護と二つの出口の比較源を作る。"""

from pathlib import Path


def main() -> None:
    """
    機能: 初回源に明示した差分だけを加え、別版の実装を保存する。
    引数: なし。市場データは読まない。
    返り値: None。生成後の源は実測前に別途固定する。
    """
    here = Path(__file__).resolve().parent
    text = (here.parent / 'engine119.py').read_text(encoding='utf-8')
    changes = [
        ('rows, times, bid, ask, pub_rows, pub_times,',
         'rows, times, bid, ask, last, pub_rows, pub_times,'),
        ('entry_end, close_time, order_tick=0.0):',
         'entry_end, close_time, order_tick=0.0, execution_mode=0, observed_tick=0.5):'),
        ('latest_row = -1\n    last_bar',
         'latest_row = -1\n    protected_limit = 0.0\n    protected_fallbacks = 0\n    protected_waits = 0\n    rejected_entries = 0\n    last_bar'),
        ('crossed = entry_mode == 0 or (pd == 1 and ask[i] <= plimit) or (pd == -1 and bid[i] >= plimit)',
         'crossed = (entry_mode == 0 and execution_mode == 0) or (pd == 1 and ask[i] <= plimit) or (pd == -1 and bid[i] >= plimit)'),
        ('ep = (ask[i] if pd == 1 else bid[i]) if entry_mode == 0 else plimit',
         'ep = (ask[i] if pd == 1 else bid[i]) if entry_mode == 0 else plimit'),
        ('                else:\n                    closed = min(pq, held)',
         '''                else:
                    # ----------------------------------------
                    # 返済指値は判断時Lastで固定し、期限又は場末で不可逆に成行へ戻す。
                    xp = bid[i] if direction == 1 else ask[i]
                    market_fallback = qt >= ptime + 30.0 or qt >= close_time or preason == 7
                    crosses = xp >= protected_limit if direction == 1 else xp <= protected_limit
                    if execution_mode and not market_fallback and not crosses:
                        protected_waits += 1
                    else:
                        if execution_mode and market_fallback and not crosses:
                            protected_fallbacks += 1
                        closed = min(pq, held)'''),
        ('if equity <= -3.0 * session_risk:',
         'if equity <= -(2.0 if guard == 2 else 3.0) * session_risk:'),
        ('elif equity >= 1.5 * session_risk:',
         'elif guard == 1 and equity >= 1.5 * session_risk:'),
        ('elif exit_mode == 0 and run >= .8 * risk:',
         'elif (exit_mode == 0 and run >= .8 * risk) or (exit_mode == 3 and run >= 2.0 * risk):'),
        ('elif exit_mode == 1 and peak >= risk and run <= peak - risk:',
         'elif (exit_mode == 1 and peak >= risk and run <= peak - risk) or (exit_mode == 4 and peak >= risk and run <= peak - .5 * risk):'),
        ('pending, pq, prow, ptime, preason = 2, close_qty, qr, qt, reason',
         '''pending, pq, prow, ptime, preason = 2, close_qty, qr, qt, reason
                    base = last[i] - direction * 2.0 * observed_tick
                    protected_limit = (math.ceil(base / order_tick) if direction == 1 else math.floor(base / order_tick)) * order_tick if order_tick > 0 else base'''),
        ('pending, pq, prow, ptime, preason = 2, held, pr, pt, 4',
         '''pending, pq, prow, ptime, preason = 2, held, pr, pt, 4
                base = anchor[b] - direction * 2.0 * observed_tick
                protected_limit = (math.ceil(base / order_tick) if direction == 1 else math.floor(base / order_tick)) * order_tick if order_tick > 0 else base'''),
        ('                pending, pd, prow, ptime, pbar, prisk = 1, d, pr, pt, b, widths[b]',
         '''                # ----------------------------------------
                # 発注後の悪い気配を消さず、発注時の審査と固定価格上限で保護する。
                if execution_mode:
                    fresh = math.isfinite(latest_bid) and latest_row <= pr and pt - latest_time <= 60.0
                    side_price = latest_ask if d == 1 else latest_bid
                    normal = fresh and latest_ask - latest_bid <= 2.0 * observed_tick + 1e-9
                    normal = normal and abs(side_price - anchor[b]) <= 2.0 * observed_tick + 1e-9
                    if not normal:
                        rejected_entries += 1
                        continue
                pending, pd, prow, ptime, pbar, prisk = 1, d, pr, pt, b, widths[b]'''),
        ('                if order_tick > 0:\n                    plimit',
         '''                if execution_mode and entry_mode == 0:
                    plimit = anchor[b] + d * 2.0 * observed_tick
                if order_tick > 0:
                    plimit'''),
        ('drawdown, canceled, fills, halted = result',
         'drawdown, canceled, fills, halted, protected_fallbacks, protected_waits, rejected_entries = result'),
        ('max_drawdown, canceled, fills, halted\n',
         'max_drawdown, canceled, fills, halted, protected_fallbacks, protected_waits, rejected_entries\n'),
        ("quotes['bid'], quotes['ask'],\n", "quotes['bid'], quotes['ask'], quotes['last'],\n"),
        ("settings.get('order_tick', 0.))", "settings.get('order_tick', 0.), settings.get('execution_mode', 0), settings.get('observed_tick', .5))"),
        ('halted=int(halted))',
         'halted=int(halted), protected_fallbacks=int(protected_fallbacks), protected_wait_rows=int(protected_waits), rejected_entries=int(rejected_entries))'),
    ]
    for old, new in changes:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    start = text.index('                    xp = bid[i] if direction == 1 else ask[i]\n                    gross')
    end = text.index('\n\n            equity = cash', start)
    text = text[:start] + '\n'.join('    ' + line for line in text[start:end].split('\n')) + text[end:]
    text = text.replace('"""公開足の判断と、その原行より後の正常気配約定を分ける場内売買エンジン。"""',
                        '"""初回の約定規則を対照に、事前価格制限と期限付き返済保護を加えた別版。"""')
    output = here / 'engine_v2.py'
    assert not output.exists()
    output.write_text(text, encoding='utf-8')
    print('別版の執行源を生成しました。市場読取・金融再生は0です。')


if __name__ == '__main__':
    main()
