"""固定済み出口核を変更せず、活動条件だけを入口へ加えた別核を作る。"""

from pathlib import Path


def main():
    """
    機能: 旧発注条件が全て成立した位置へ活動判定を挿入する。
    引数: なし。
    返り値: None。元の出口核は読み取り専用とする。
    """
    here = Path(__file__).resolve().parent
    source = (here / "night_exit130.py").read_text(encoding="utf8")
    source = source.replace(
        '"""起動前の損失縮小と、一部返済後も伸びを残す夜間の出口比較。"""',
        '"""旧出口を保持し、価格応答と逆向き出来高代理の活動を入口で確認する。"""', 1)
    old = "us_open, tick, quantity, multiplier, fee_tenths, parameters, retest_mode=0, exit_style=0):"
    new = ("us_open, tick, quantity, multiplier, fee_tenths, parameters, retest_mode=0, exit_style=0,\n"
           "             activity=None, activity_mode=0):")
    assert source.count(old) == 1
    source = source.replace(old, new, 1)
    old = "          retest_mode(int)は0で旧入口、1で再試験。exit_style(int)は0旧出口、1連続床、2部分返済、3両方。"
    new = old + ("\n          activity(None又はndarray[N,4])は中値差・正出来高増分・符号付き増分・既知。\n"
                 "          activity_mode(int)は0で厳密旧互換、1で価格応答と逆向き代理量を必須とする。")
    assert source.count(old) == 1
    source = source.replace(old, new, 1)
    old = "    n = len(times)\n"
    new = ("    n = len(times)\n"
           "    assert activity_mode == 0 or activity_mode == 1\n"
           "    if activity_mode == 1:\n"
           "        assert activity is not None\n"
           "        assert activity.shape[0] == n and activity.shape[1] == 4\n")
    assert source.count(old) == 1
    source = source.replace(old, new, 1)
    old = "                    if arm and trigger and quote_ok:\n                        pending = arm"
    new = """                    if arm and trigger and quote_ok and activity_mode == 1 and activity is not None:
                        # ----------------------------------------
                        # 旧発注資格の揃った当行だけで確認し、未知・不適格なら全準備を捨てる。
                        activity_ok = activity[i, 3] == 1. and np.isfinite(activity[i, :3]).all()
                        activity_ok = activity_ok and arm*activity[i, 0] > 0.
                        activity_ok = activity_ok and activity[i, 1] > 0. and arm*activity[i, 2] < 0.
                        if not activity_ok:
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
                    if arm and trigger and quote_ok:
                        pending = arm"""
    assert source.count(old) == 1
    source = source.replace(old, new, 1)
    target = here / "night_activity130.py"
    assert not target.exists()
    target.write_text(source, encoding="utf8")


if __name__ == "__main__":
    main()
