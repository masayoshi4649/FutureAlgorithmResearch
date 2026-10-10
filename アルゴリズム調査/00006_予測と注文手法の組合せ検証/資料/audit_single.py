"""成行・固定逆指値・時間返済・目標返済を独立の小さな気配列で手計算照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import single

OUT = Path(__file__).resolve().parent


def fixture(bids: list[float], seconds: list[float] | None = None, side: int = 1) -> dict:
    """機能: 一定 ATR とスプレッドを持つ既知の気配・信号を構成する。

    引数: bids (list[float])、seconds (list[float]|None)、side (int)。
    返り値: dict。単建玉再生用の準備済み入力。
    """
    count = len(bids)
    base = pd.Timestamp("2026-09-22T17:20:00+09:00").timestamp()
    b = np.array(bids, dtype=float)
    a = b + 10.
    if side < 0:
        b, a = 2000. - a, 2000. - b
    t = base + np.array(seconds if seconds is not None else list(range(count)), dtype=float)
    tape = dict(seq=np.arange(1, count + 1), time_s=t, bid=b, ask=a,
                bid_qty=np.full(count, 5.), ask_qty=np.full(count, 5.), atr=np.full(count, 100.))
    events = pd.DataFrame([dict(family="監査", event_id="監査_１", seq=1, source_last_seq=0,
                                time_s=t[0], atr=100., side=side, deadline_time_s=t[0] + 600.)])
    return single.prepare(tape, events, "2026-09-22_Night", "NK225")


def config(**changes: object) -> dict:
    """機能: 固定時間だけで返済する予測主導の基本条件に変更を加える。

    引数: changes (dict[str, object]) は個別の設定。
    返り値: dict。共通の成行新規・無限ストップを持つ条件。
    """
    value = dict(id="独立監査", family="監査", entry_mode=1., entry_offset=0.,
                 warmup_min=0., cooldown_min=0., initial_stop_atr=np.inf, trail_atr=np.inf,
                 max_age_min=10.)
    value.update(changes)
    return value


def check(name: str, ready: dict, condition: dict, expected: dict | None, output: list[dict],
          delay: str = "次行") -> None:
    """機能: 手計算と最大順行を照合し、全ての短い入力末尾で確定売買の不変性を確認する。

    引数: name (str)、ready/condition (dict)、expected (dict|None)、output (list[dict])、delay (str)。
    返り値: None。照合結果を output に追加する。
    """
    full = single.simulate(ready, condition, delay)
    if expected is None:
        assert full == [], (name, full)
    else:
        assert len(full) == 1, (name, full)
        for key, value in expected.items():
            assert full[0][key] == value, (name, key, full[0][key], value)
    for trade in full:
        entry = int(np.searchsorted(ready["seq"], trade["entry_seq"]))
        end = int(np.searchsorted(ready["seq"], trade["exit_seq"])) if trade["closed"] else len(ready["seq"]) - 1
        quotes = ready["bid"][entry:end + 1] if trade["side"] > 0 else ready["ask"][entry:end + 1]
        maximum = max(0., float(np.max(trade["side"] * (quotes - trade["entry_price"]))))
        assert trade["max_favorable"] == maximum, (name, "全保有期間の最大順行", maximum, trade["max_favorable"])
    comparisons = 0
    for count in range(1, len(ready["seq"]) + 1):
        short = dict(ready)
        for key in ("seq", "time_s", "bid", "ask", "bid_qty", "ask_qty", "atr", "board_side", "trend_side"):
            short[key] = ready[key][:count]
        wanted = [trade for trade in full if trade["closed"] and trade["exit_seq"] <= count]
        observed = [trade for trade in single.simulate(short, condition, delay) if trade["closed"]]
        assert observed == wanted, (name, count)
        comparisons += 1
    output.append(dict(検査=name, 手計算=expected, 取引=full, 打切り照合数=comparisons))


def main() -> None:
    """機能: 新しい単建玉の注文方式を小さな既知ケースで検査する。

    引数: なし。
    返り値: None。独立手計算の JSON を保存する。
    """
    output = []
    for side in (1, -1):
        label = "買い" if side > 0 else "売り"
        ready = fixture([990, 1000, 1060, 1030], side=side)
        check(label + "成行は次の気配、目標成立行も最大順行へ含む", ready, config(target_atr=.5),
              dict(condition_seq=1, trigger_seq=1, entry_seq=2, exit_trigger_seq=3, exit_seq=4,
                   closed=True, net_points=0., max_favorable=50., exit_reason="目標利益の条件成立"), output)
        ready = fixture([990, 1000, 1020, 1040, 1030], seconds=[0, 1, 60, 61, 62], side=side)
        check(label + "約定から１分で返済要求して次行約定", ready, config(holding_min=1.),
              dict(entry_seq=2, exit_trigger_seq=4, exit_seq=5, closed=True, net_points=0.,
                   max_favorable=30., exit_reason="固定時間で返済"), output)
        ready = fixture([990, 1000, 1000, 1060, 1250, 1030], side=side)
        check(label + "二行遅延の返済待ちでも最大順行を記録", ready, config(target_atr=.5),
              dict(entry_seq=3, exit_trigger_seq=4, exit_seq=6, closed=True, net_points=0., max_favorable=240.),
              output, "２行後")
        ready = fixture([990, 1000, 1060, 1210], side=side)
        check(label + "返済約定行の順行も記録", ready, config(target_atr=.5),
              dict(closed=True, net_points=180., max_favorable=200.), output)

    # ----------------------------------------
    # 固定した逆指値と、安値を追う新規トレーリングを同じ気配列で比較する。
    ready = fixture([990, 900, 910, 1000, 1050, 1100, 1090])
    check("固定逆指値は安値で閾値を動かさない", ready, config(entry_mode=2., entry_offset=1.),
          dict(closed=False, trigger_seq=6, entry_seq=7, entry_price=1100.), output)
    check("追跡新規は安値へ追随する", ready, config(entry_mode=0., entry_offset=1.),
          dict(closed=False, trigger_seq=4, entry_seq=5, entry_price=1060.), output)
    ready = fixture([990, 1000, 1060])
    check("目標成立が最終行なら未返済", ready, config(target_atr=.5),
          dict(closed=False, pending_exit="目標利益の条件成立", max_favorable=50.), output)
    ready = fixture([990, 1000, 1020, 1060, 1030], seconds=[0, 1, 60, 61, 62])
    check("目標と時間が同じ行なら事前に固定した時間理由", ready, config(target_atr=.5, holding_min=1.),
          dict(closed=True, exit_reason="固定時間で返済", exit_trigger_seq=4), output)
    ready = fixture([990, 1000, 1060, 1030])
    ready["us_open"] = ready["time_s"][0]
    check("予定された新規停止中は成行要求しない", ready,
          config(us_mode="新規停止", us_before_min=0.), None, output)
    ready["us_open"] = ready["time_s"][1]
    check("停止前に受け付けた成行は次行で約定", ready,
          config(us_mode="新規停止", us_before_min=0.), dict(entry_seq=2, closed=False), output)
    single.save(OUT / "単建玉の独立手計算監査.json", dict(
        実装SHA256=hashlib.sha256(Path(single.__file__).read_bytes()).hexdigest(),
        手計算件数=len(output), 全打切り照合数=sum(row["打切り照合数"] for row in output),
        最大順行の成立行待機行約定行を含む独立再計算一致=True, 検査=output))
    print(f"単建玉の手計算 {len(output)} 件・全途中打切り・全保有期間最大順行が一致しました。", flush=True)


if __name__ == "__main__":
    main()
