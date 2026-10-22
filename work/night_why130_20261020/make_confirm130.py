"""単なる戻りだけの部分返済を、両市場の逆行確認付きに分ける。"""

from common130 import HERE


def replace_once(source, old, new):
    """
    機能: 固定源の想定箇所だけを差し替えた新源を返す。
    引数: source/old/new(str)は本文と変更前後。
    返り値: strは新本文。想定件数が違えば停止する。
    """
    assert source.count(old) == 1, old
    return source.replace(old, new)


def main():
    """
    機能: 固定済み旧源を変更せず、第三巡用の核と実行器を作る。
    引数: なし。
    返り値: None。金融再生は行わない。
    """
    source = (HERE / "night_exit130.py").read_text(encoding="utf-8")
    source = replace_once(source, "assert exit_style >= 0 and exit_style <= 3",
                          "assert exit_style >= 0 and exit_style <= 4")
    source = replace_once(source, "2部分返済、3両方。",
                          "2部分返済、3両方、4部分返済に両市場30秒逆行を要求。")
    source = replace_once(source,
        "elif not pending and (exit_style == 2 or exit_style == 3) and not partial_done:",
        "elif not pending and (exit_style == 2 or exit_style == 3 or exit_style == 4) and not partial_done:")
    needle = "if quantity >= 2 and peak >= .5*width and movement <= peak-.25*width:"
    if needle not in source:
        raise AssertionError("部分返済の固定表記を要確認")
    source = replace_once(source, needle,
        "confirmed = exit_style != 4 or (market[i,11] == 1. and "
        "np.isfinite(market[i,4]) and np.isfinite(market[i,6]) and\n"
        "                    position*market[i,4] < 0. and position*market[i,6] < 0.)\n"
        "                if confirmed and quantity >= 2 and peak >= .5*width and movement <= peak-.25*width:")
    target = HERE / "night_confirm130.py"
    assert not target.exists()
    target.write_text(source, encoding="utf-8")
    # ----------------------------------------
    # 入力と会計は第一巡と同じまま、参照する数値核だけを分離する。
    runner = (HERE / "run130.py").read_text(encoding="utf-8")
    runner = runner.replace("night_exit130", "night_confirm130").replace('"run130.py"', '"run_confirm130.py"')
    target = HERE / "run_confirm130.py"
    assert not target.exists()
    target.write_text(runner, encoding="utf-8")


if __name__ == "__main__":
    main()
