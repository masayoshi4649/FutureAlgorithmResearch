"""第一段階の凍結済み再生器から、利確後だけ再参加する別実装を作る。"""
from pathlib import Path

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'engine.py'


def replace_once(text,old,new):
    """
    機能: 期待した接続箇所だけを変更する。
    引数: text/old/new(str)。
    返り値: str の別実装。
    """
    assert text.count(old)==1,(old,text.count(old))
    return text.replace(old,new,1)


def build():
    """
    機能: 損切り後は通常影を残し、親組黒字終了だけ実返済時計へ切り替える。
    引数: なし。
    返り値: str の出力パス。第一段階の実装は変更しない。
    """
    text=SOURCE.read_text(encoding='utf-8')
    text=replace_once(text,'cooldown_seconds):','cooldown_seconds, profit_fast_enabled):')
    text=replace_once(text,'    ns_dynamic_events =',
        '    ns_ready_after=-np.inf\n    xs_ready_after=-np.inf\n    profit_restart_pending=False\n    profit_reentry_events=np.zeros((12000,7))\n    profit_reentry_count=0\n    ns_dynamic_events =')
    text=replace_once(text,'        ns_allow[i] = closed',
        '        ns_allow[i] = closed and (not profit_restart_pending or (not quiet[i] and not quiet_force[i]))')
    for prefix in ('ns_','xs_'):
        text=replace_once(text,f'            {prefix}last_exit = time[feedback_row]',
            f'            {prefix}last_exit = time[feedback_row]\n            {prefix}ready_after=time[feedback_row]+cooldown_seconds')
        text=replace_once(text,f'                {prefix}last_exit = {prefix}t',
            f'                {prefix}last_exit = {prefix}t\n                {prefix}ready_after={prefix}t+300.')
        text=replace_once(text,f'({prefix}t >= {prefix}last_exit + {prefix}par[26] * 60)',
            f'({prefix}t >= {prefix}ready_after)')
    # ----------------------------------------
    # 赤字終了で通常影を切らない。元の通常影は静観窓を含めて観測を続ける。
    start=text.index('        for ns_once in range(1):')
    end=text.index('        xs_allow[i]',start)
    original=text[start:end]
    adjusted=original.replace('quiet_force[i]','False').replace('quiet_not_before[i]','-np.inf').replace('quiet[i]','False')
    text=text[:start]+adjusted+text[end:]
    text=replace_once(text,'        if feedback_row >= 0:\n            if reentry_count',
        '        if feedback_row >= 0:\n            profit_restart_pending=True\n            if reentry_count')
    text=replace_once(text,'        xs_allow[i] = ns_prepare_count > 0 and ns_prepare_events[ns_prepare_count - 1, 1] == i',
        '        xs_allow[i] = ns_prepare_count > 0 and ns_prepare_events[ns_prepare_count - 1, 1] == i\n        if xs_allow[i]: profit_restart_pending=False')
    text=replace_once(text,'        if closed_now:\n            feedback_row = i\n            feedback_price = fill',
        '        if closed_now:\n            # ----------------------------------------\n            # 料金後親組の円額で判定し、最後の返済脚や理由名では判定しない。\n            realized_yen=net_campaign*losspar[13]\n            use_fast=profit_fast_enabled and realized_yen>1e-7\n            if profit_reentry_count>=len(profit_reentry_events): raise ValueError("利確再参加証跡の上限です")\n            profit_reentry_events[profit_reentry_count,:]=np.array([i,campaign,realized_yen,int(use_fast),t+cooldown_seconds if use_fast else np.nan,ns_d,ns_entry_row])\n            profit_reentry_count+=1\n            if use_fast:\n                feedback_row = i\n                feedback_price = fill')
    text=replace_once(text,'gate_arm_rows, gate_armed, gate_eligible)',
        'gate_arm_rows, gate_armed, gate_eligible, profit_reentry_events[:profit_reentry_count])')
    text=text.replace('実全返済の次行から両影を再準備する。','料金後黒字の実全返済だけ、次行から両影を再準備する。赤字・ゼロは元通常影の終了を待つ。')
    text=text.replace('通常影・改修出口影・実玉を同一原本行で更新する生成済み再生器。','料金後に親組黒字となった全返済だけ、早期再参加を許す別生成器。')
    target=HERE/'engine.py'
    target.write_text(text,encoding='utf-8')
    return str(target)


if __name__=='__main__': print(build())
