"""旧数値核を所有域へ複製し、日中専用の二種類の出口だけを追加する。"""

from common128 import HERE, OLD, reference, save


def main():
    """
    機能: 凍結済み気配会計に差分が明示された日中出口を生成する。
    引数: なし。
    返り値: None。金融再生を行わず、旧源を書き換えない。
    """
    source = OLD / "engine/bbo_next/core126.py"
    text = source.read_text(encoding="utf-8")
    old = "def simulate(times, prices, bid, ask, qok, feed, end, cap, market, policy):"
    new = "def simulate(times, prices, bid, ask, qok, feed, end, cap, market, policy, current_atr, history, exit_rule):"
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = "            reason = 0\n            if campaign_equity <= -risk: reason = 32"
    new = """            # ----------------------------------------
            # 日中の値幅収縮／中期失敗を、当行までの資料だけで判断する。
            effective_risk = risk
            if exit_rule == 1 and np.isfinite(current_atr[i]) and current_atr[i] > 0.:
                effective_risk = risk * max(.5, min(1., current_atr[i] / atr))
            if exit_rule == 2 and guard_peak >= .5 * risk:
                failed = np.isfinite(history[i, 1]) and np.isfinite(history[i, 10])
                failed = failed and side * (prices[i] - history[i, 1]) < 0. and side * history[i, 10] < 0.
                if failed:
                    guard_floor = max(guard_floor, .5 * guard_peak)
            reason = 0
            if campaign_equity <= -effective_risk: reason = 32
            elif exit_rule == 2 and np.isfinite(guard_floor) and campaign_equity <= guard_floor: reason = 70"""
    assert text.count(old) == 1
    text = text.replace(old, new)
    target = HERE / "day_core128.py"
    assert not target.exists()
    target.write_text(text, encoding="utf-8")
    kernel = OLD / "engine/bbo_next/bbo_order_kernel126.py"
    (HERE / kernel.name).write_bytes(kernel.read_bytes())
    save(HERE / "日中核の複製差分.json", dict(source=reference(source),
        result=reference(target), kernel=reference(kernel),
        changes=["追加引数current_atr/history/exit_rule", "値幅収縮による0.5～1Rの損失予約",
                 "0.5R到達後、中期失敗時だけ半益床を引上げ"], financial_replays=0))


if __name__ == "__main__":
    main()
