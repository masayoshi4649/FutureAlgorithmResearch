"""検証済みの入口を保持したまま、出口比較の核を新しい版として生成する。"""

from common130 import HERE, PREV


def replace_once(source, before, after):
    """
    機能: 指定箇所が一つだけ存在することを確認して置換する。
    引数: source/before/after(str)は原文・置換前・置換後。
    返り値: strは置換済みの新しい文章。
    """
    assert source.count(before) == 1, before[:100]
    return source.replace(before, after, 1)


def main():
    """
    機能: 旧入口を複製し、連続的な床・部分返済とその会計だけを追加する。
    引数: なし。旧00129の完成源は読み取り専用として扱う。
    返り値: None。新源作成のみで、金融再生を行わない。
    """
    source = (PREV / "night_retest129c.py").read_text(encoding="utf-8")
    source = replace_once(source, '"""再試験の発注候補で強逆流があれば、古い準備を破棄する比較を追加する。"""',
                          '"""起動前の損失縮小と、一部返済後も伸びを残す夜間の出口比較。"""')
    source = replace_once(source, '"出口理由", "入口型")', '"出口理由", "入口型", "親番号")')
    source = replace_once(source, "parameters, retest_mode=0):", "parameters, retest_mode=0, exit_style=0):")
    source = replace_once(source, "retest_mode(int)は0で旧互換、1で固定突破線の再試験。",
        "retest_mode(int)は0で旧入口、1で再試験。exit_style(int)は0旧出口、1連続床、2部分返済、3両方。")
    source = replace_once(source, "n = len(times)", "assert exit_style >= 0 and exit_style <= 3\n    n = len(times)")
    source = replace_once(source, "trades = np.zeros((n, 14))", "trades = np.zeros((n, 15))")
    source = replace_once(source, "tc = 0\n    position = 0", """tc = 0
    parent_count = 0
    active_parent = -1
    held = 0
    pending_quantity = 0
    entry_fee_total = 0
    entry_fee_remaining = 0
    parent_net = 0.
    partial_done = False
    position = 0""")
    source = replace_once(source, "position = pending\n                entry =", """position = pending
                held = quantity
                active_parent = parent_count
                parent_count += 1
                partial_done = False
                entry =""")
    source = replace_once(source, """cash -= one_fee
                fees += one_fee
                orders[oc] = np.array([i, pending_source, tc, position, quantity, entry, 1., 1.])""",
        """cash -= one_fee
                fees += one_fee
                entry_fee_total = one_fee
                entry_fee_remaining = one_fee
                parent_net = -float(one_fee)
                orders[oc] = np.array([i, pending_source, active_parent, position, quantity, entry, 1., 1.])""")
    source = replace_once(source, """gross = position * (fill-entry) * quantity * multiplier
                one_fee = quantity * fee_tenths // 10
                cash += gross - one_fee
                fees += one_fee
                orders[oc] = np.array([i, pending_source, tc, -position, quantity, fill, pending_reason, 0.])
                oc += 1
                trades[tc] = np.array([entry_row,i,position,quantity,entry,fill,gross,
                    2*one_fee,gross-2*one_fee,peak,adverse,width,pending_reason,entry_mode])
                tc += 1
                if gross-2*one_fee < 0. and rearm > 0.:
                    slot = 0 if position > 0 else 1
                    failed_price[slot] = entry
                    failed_width[slot] = width
                position = 0
                ready_after = t + cooldown
                arm = 0""", """closed = min(held, pending_quantity)
                assert closed > 0
                gross = position * (fill-entry) * closed * multiplier
                one_fee = closed * fee_tenths // 10
                assigned = entry_fee_remaining if closed == held else entry_fee_total * closed // quantity
                entry_fee_remaining -= assigned
                cash += gross - one_fee
                parent_net += gross - one_fee
                fees += one_fee
                orders[oc] = np.array([i, pending_source, active_parent, -position, closed, fill, pending_reason, 0.])
                oc += 1
                trade_fee = assigned + one_fee
                trades[tc] = np.array([entry_row,i,position,closed,entry,fill,gross,
                    trade_fee,gross-trade_fee,peak,adverse,width,pending_reason,entry_mode,active_parent])
                tc += 1
                held -= closed
                if held == 0:
                    if parent_net < 0. and rearm > 0.:
                        slot = 0 if position > 0 else 1
                        failed_price[slot] = entry
                        failed_width[slot] = width
                    position = 0
                    ready_after = t + cooldown
                    arm = 0""")
    source = replace_once(source, """if peak >= activation*width:
                floor = max(floor, peak-trail*width)""", """if exit_style == 1 or exit_style == 3:
                # 起動前に損失床を据え置かず順行に応じて上げる。1Rでの0.25R上昇は残る。
                floor = max(floor, peak-stop*width)
            if peak >= activation*width:
                floor = max(floor, peak-trail*width)""")
    source = replace_once(source, """pending_reason = reason
        # ----------------------------------------
        # 入り直し""", """pending_reason = reason
                pending_quantity = held
            elif not pending and (exit_style == 2 or exit_style == 3) and not partial_done:
                # 全返済の条件が先。半分の利益を残し、残玉には従来の出口を継続する。
                if quantity >= 2 and peak >= .5*width and movement <= peak-.25*width:
                    pending = -position
                    pending_source = i
                    pending_reason = 76
                    pending_quantity = quantity // 2
                    partial_done = True
        # ----------------------------------------
        # 入り直し""")
    source = replace_once(source, """pending = arm
                        pending_source = i""", """pending = arm
                        pending_quantity = quantity
                        pending_source = i""")
    source = replace_once(source, "unrealized = position * (mark-entry) * quantity * multiplier",
                          "unrealized = position * (mark-entry) * held * multiplier")
    source = replace_once(source, "curve[i] = np.array([cash+unrealized, position*quantity, fees, cash])",
                          "curve[i] = np.array([cash+unrealized, position*held, fees, cash])")
    source = replace_once(source, "assert position == 0 and pending == 0",
                          "assert position == 0 and pending == 0 and held == 0 and entry_fee_remaining == 0")
    path = HERE / "night_exit130.py"
    assert not path.exists()
    path.write_text(source, encoding="utf-8")
    print("新しい出口比較源を作成。金融再生なし。", flush=True)


if __name__ == "__main__":
    main()
