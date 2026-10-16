"""事前予定の停止境界、米国夏冬時間、旧16部品の不変性を確認する。"""

from datetime import date, datetime
import hashlib
import json
import numpy as np

import synthetic
from original import module, HERE, WORK


def timestamps(items):
    """
    機能: 時差を明示した人工日時を実数秒へ変換する。
    引数: items (list[str])。
    返り値: ndarray[float]。
    """
    return np.array([datetime.fromisoformat(s).timestamp() for s in items])


def main():
    """
    機能: 予定を過去データだけへ対応し、強制返済・古い準備拒否と無指定の同一性を試す。
    引数: なし。
    返り値: None。
    """
    time_filter = synthetic.strategy.time_filter
    old_engine = module("wave85_engine_before_hours", HERE / "engine_before_hours.py")
    current_engine = synthetic.strategy.engine
    tests = []
    for mask in range(16):
        for observed in (False, True):
            for reflected in (False, True):
                args = dict(mask=mask, observed=observed, reflected=reflected)
                original = synthetic.fixture([100, 100, 108, 103, 110, 111, 111],
                    {1: (1, 0)}, {4: (1, 0, 7), 6: (1, 0, 9)}, **args)
                try:
                    synthetic.strategy.engine = old_engine
                    before = synthetic.fixture([100, 100, 108, 103, 110, 111, 111],
                        {1: (1, 0)}, {4: (1, 0, 7), 6: (1, 0, 9)}, **args)
                finally:
                    synthetic.strategy.engine = current_engine
                for name in before:
                    np.testing.assert_array_equal(original[name], before[name], err_msg=name)
                assert not len(original["time_events"])
    tests.append(dict(検査="時間指定なしは追加前16部品×指定観測×売買反射64経路で全配列完全一致", 合格=True))
    # ----------------------------------------
    # 予定開始は元部分利確より優先。終了直後の古い準備は残さない。
    times = timestamps([f"2026-10-09T{t}:00+09:00" for t in ("08:43", "08:44", "08:45", "09:00", "09:15", "09:16", "09:17")])
    prices = [100, 100, 108, 110, 110, 100, 101]
    ready = dict(time_s=times, last=np.array(prices, float))
    quiet = time_filter.features(ready, "J")
    np.testing.assert_array_equal(quiet["active"], [False, False, True, True, False, False, False])
    assert np.flatnonzero(quiet["force"]).tolist() == [2]
    for reflected in (False, True):
        for observed in (False, True):
            result = synthetic.fixture(prices, {1: (1, 0), 3: (1, 1), 4: (1, 2), 5: (1, 3)},
                {2: (1, 0, 7), 6: (1, 3, 9)}, mask=15, reflected=reflected, observed=observed,
                time_values=times, quiet=quiet, prepare_rows={3: 2, 4: 1, 5: 4})
            synthetic.check_cash(result)
            assert result["orders"][:, 0].tolist() == [1, 2, 5, 6]
            assert result["orders"][:, 6].tolist() == [20, 71, 20, 9]
            assert result["orders"][:, 4].tolist() == [5, 5, 5, 5]
            assert result["orders"][1, 5] == result["price"][2]
            tests.append(dict(検査="08:45の全返済は元部分利確より優先、09:15の古い準備拒否、終了後新準備だけ再開",
                              観測価格=observed, ショート=reflected, 合格=True))
    # ----------------------------------------
    # 窓全体を飛び越えても、実際に得られた価格で返済する。
    times = timestamps([f"2026-10-09T{t}:00+09:00" for t in ("08:43", "08:44", "09:20", "09:26", "09:27")])
    ready = dict(time_s=times, last=np.array([100, 100, 90, 100, 100], float))
    quiet = time_filter.features(ready, "J")
    assert not quiet["active"].any() and np.flatnonzero(quiet["force"]).tolist() == [2]
    assert quiet["windows"][0]["窓終了後の初観測"]
    result = synthetic.fixture(ready["last"], {1: (1, 0), 3: (1, 1)}, {4: (1, 1, 9)},
        quiet=quiet, time_values=times, prepare_rows={3: 2})
    synthetic.check_cash(result)
    assert result["orders"][1, 6] == 71 and result["orders"][1, 5] == 90
    tests.append(dict(検査="窓終了後まで価格観測がない場合、09:20の有効価格90で返済し窓内返済と偽らない", 合格=True))
    missing = dict(time_s=timestamps([f"2026-10-09T{t}:00+09:00" for t in ("08:44", "08:45", "08:46", "09:16")]),
                   last=np.array([100., np.nan, 0., 90.]))
    q = time_filter.features(missing, "J")
    assert np.flatnonzero(q["force"]).tolist() == [3]
    tests.append(dict(検査="停止開始に欠測・不正価格しかない場合は後続最初の有効価格まで返済しない", 合格=True))
    # ----------------------------------------
    # 現地09:30を固定し、夏冬移行と休場日を別々に検査する。
    for day, expected in (("2026-01-05", "23:15"), ("2026-03-06", "23:15"), ("2026-03-09", "22:15"),
                          ("2026-10-30", "22:15"), ("2026-11-02", "23:15"), ("2026-10-09", "22:15")):
        a, b, reason = time_filter.windows(date.fromisoformat(day), "U")[0]
        assert datetime.fromtimestamp(a, time_filter.TOKYO).strftime("%H:%M") == expected
        assert b - a == 1800 and reason == "U"
        assert datetime.fromtimestamp(a + 900, time_filter.NEW_YORK).strftime("%H:%M") == "09:30"
        tests.append(dict(検査="米国現地09:30の前後15分と夏冬時間", 日付=day, JST開始=expected, 合格=True))
    for day in ("2026-07-03", "2026-09-07", "2026-10-10", "2026-12-25"):
        assert not time_filter.windows(date.fromisoformat(day), "U")
    try:
        time_filter.windows(date(2027, 1, 4), "U")
        raise AssertionError("未定義年を推測した")
    except ValueError:
        pass
    tests.append(dict(検査="NYSE保存休場日と週末はUなし、未定義年は例外", 合格=True))
    # ----------------------------------------
    # 窓の終了を将来から知っていても、強制返済の過去行は切断後も同じ。
    source = dict(time_s=timestamps([f"2026-10-09T{t}:00+09:00" for t in ("08:43", "08:44", "08:45", "09:00", "09:15", "22:14", "22:15", "22:45", "23:00")]),
                  last=np.full(9, 100.))
    full = time_filter.features(source, "JU")
    for count in range(1, 10):
        part = time_filter.features({k: v[:count] for k, v in source.items()}, "JU")
        for name in ("active", "force", "not_before"):
            np.testing.assert_array_equal(part[name], full[name][:count])
    tests.append(dict(検査="J/U全9途中切断で取引禁止・初回返済行・再準備時刻が不変", 合格=True))
    result = dict(全合格=True, 検査=tests, 旧無時間配列一致経路数=64,
        実装SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (WORK / "engine.py", WORK / "strategy.py", WORK / "catalog.py", WORK / "time_filter.py", Path(__file__))},
        旧エンジンSHA256=hashlib.sha256((HERE / "engine_before_hours.py").read_bytes()).hexdigest())
    (HERE / "時間回避境界と旧16不変の人工監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(全合格=True, 検査数=len(tests), 旧無時間一致経路数=64), ensure_ascii=False))


if __name__ == "__main__":
    from pathlib import Path
    main()
