"""活動を待つ間の判断価格悪化を制限する別核と実行接続を生成する。"""

from pathlib import Path


WORK = Path(__file__).resolve().parent.parent


def main():
    """
    機能: 凍結済み源を変更せず、価格予算だけを追加した新しい源を保存する。
    引数: なし。
    返り値: None。売買の再生や既存ファイルの上書きは行わない。
    """
    target = WORK/"night_budget130.py"
    runner_target = WORK/"run_budget130.py"
    assert not target.exists() and not runner_target.exists()
    source = (WORK/"night_activity130.py").read_text(encoding="utf-8-sig")
    source = source.replace(
        '"""旧出口を保持し、価格応答と逆向き出来高代理の活動を入口で確認する。"""',
        '"""活動待ちで見送った最初の候補より不利な判断価格を追わない。"""')
    source = source.replace("activity=None, activity_mode=0):",
                            "activity=None, activity_mode=0, budget_mode=0):")
    source = source.replace(
        "          activity_mode(int)は0で厳密旧互換、1で価格応答と逆向き代理量を必須とする。\n",
        "          activity_mode(int)は0で厳密旧互換、1で価格応答と逆向き代理量を必須とする。\n"
        "          budget_mode(int)は0で活動入口互換、1で最初に見送った判断BBOの方向別予算を保持する。\n")
    source = source.replace(
        "    assert activity_mode == 0 or activity_mode == 1\n",
        "    assert activity_mode == 0 or activity_mode == 1\n"
        "    assert budget_mode == 0 or budget_mode == 1\n"
        "    assert budget_mode == 0 or activity_mode == 1\n")
    source = source.replace(
        "    failed_width = np.zeros(2)\n",
        "    failed_width = np.zeros(2)\n"
        "    budget_quote = np.full(2, np.nan)\n"
        "    budget_level = np.zeros(2)\n"
        "    budget_width = np.zeros(2)\n")
    source = source.replace(
        "        terminal = t >= end\n",
        """        terminal = t >= end
        if budget_mode == 1:
            # ----------------------------------------
            # 保存境界の破綻は自己の有限価格だけで解除する。既発注の予約には触れない。
            for budget_slot in range(2):
                budget_side = 1 if budget_slot == 0 else -1
                expired = quiet or terminal
                if np.isfinite(budget_quote[budget_slot]) and np.isfinite(prices[i]):
                    expired = expired or budget_side*(prices[i]-budget_level[budget_slot]) <= -.25*budget_width[budget_slot]
                if expired:
                    budget_quote[budget_slot] = np.nan
                    budget_level[budget_slot] = 0.
                    budget_width[budget_slot] = 0.
""")
    source = source.replace(
        "                    if arm and trigger and quote_ok and activity_mode == 1 and activity is not None:\n",
        """                    if arm and trigger and quote_ok and budget_mode == 1:
                        # ----------------------------------------
                        # 資格の揃った候補だけを比較する。好条件と等値は許し、保存価格は更新しない。
                        budget_slot = 0 if arm > 0 else 1
                        current_quote = ask[i] if arm > 0 else bid[i]
                        if np.isfinite(budget_quote[budget_slot]) and arm*(current_quote-budget_quote[budget_slot]) > 0.:
                            arm = 0
                            arm_level = 0.
                            arm_width = 0.
                            arm_extreme = 0.
                            arm_mode = 0
                            arm_time = 0.
                            pullback = False
                            retest_stage = 0
                            progress_row = -1
                            return_row = -1
                            return_extreme = 0.
                    if arm and trigger and quote_ok and activity_mode == 1 and activity is not None:
""")
    source = source.replace(
        "                        if not activity_ok:\n                            arm = 0\n",
        """                        if not activity_ok:
                            if budget_mode == 1:
                                budget_slot = 0 if arm > 0 else 1
                                if not np.isfinite(budget_quote[budget_slot]):
                                    budget_quote[budget_slot] = ask[i] if arm > 0 else bid[i]
                                    budget_level[budget_slot] = arm_level
                                    budget_width[budget_slot] = arm_width
                            arm = 0
""")
    assert source.count("if budget_mode == 1:") == 2
    assert "current_quote-budget_quote[budget_slot]" in source
    target.write_text(source, encoding="utf-8")
    runner = (WORK/"run_activity130.py").read_text(encoding="utf-8-sig")
    runner = runner.replace('"""固定済み原板活動を原行へ照合し、登録済み入口条件だけを再生する。"""',
                            '"""活動待ちの判断価格予算を追加した固定条件だけを再生する。"""')
    runner = runner.replace("night_activity130", "night_budget130").replace(
        "run_activity130.py", "run_budget130.py").replace("jit_activity_financial", "jit_budget_financial")
    runner = runner.replace(
        '        assert config["activity_mode"] in (0, 1)\n',
        '        assert config["activity_mode"] in (0, 1)\n'
        '        assert config["budget_mode"] in (0, 1)\n'
        '        assert config["budget_mode"] == 0 or config["activity_mode"] == 1\n')
    runner = runner.replace(
        '                        activity[symbol], config["activity_mode"])\n',
        '                        activity[symbol], config["activity_mode"], config["budget_mode"])\n')
    runner_target.write_text(runner, encoding="utf-8")
    print(target)
    print(runner_target)


if __name__ == "__main__":
    main()
