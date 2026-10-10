"""条件付き短縮と米国開始切替を、小さな気配列で独立に手計算照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT))
import engine


def fixture(bids: list[float], seconds: list[float] | None = None, side: int = 1,
            reverse_index: int | None = None, board: list[int] | None = None,
            trend: list[int] | None = None, event_deadline: float = 600.) -> dict:
    """機能: 既知価格・一定スプレッド・既知 ATR の最小入力を構成する。

    引数: bids (list[float])、seconds (list[float]|None)、side (int)、
        reverse_index (int|None)、board/trend (list[int]|None)、event_deadline (float)。
    返り値: dict。注文再生器の準備済み入力。
    """
    session = "2026-09-22_Night"
    start = pd.Timestamp("2026-09-22T17:20:00+09:00").timestamp()
    count = len(bids)
    values = np.array(bids, dtype=float)
    original_ask = values + 10.0
    if side < 0:
        values, original_ask = 2000.0 - original_ask, 2000.0 - values
    times = start + np.array(seconds if seconds is not None else list(range(count)), dtype=float)
    tape = {
        "seq": np.arange(1, count + 1), "time_s": times,
        "bid": values, "ask": original_ask,
        "bid_qty": np.full(count, 5.0), "ask_qty": np.full(count, 5.0),
        "atr": np.full(count, 100.0),
    }
    events = [dict(family="監査", event_id="監査_初回", seq=1, source_last_seq=0,
                   time_s=times[0], side=side, atr=100., deadline_time_s=times[0] + event_deadline)]
    if reverse_index is not None:
        events.append(dict(family="監査", event_id="監査_逆転", seq=reverse_index + 1,
                           source_last_seq=reverse_index, time_s=times[reverse_index], side=-side,
                           atr=100., deadline_time_s=times[reverse_index] + 600.))
    state = {
        "board_side": np.array(board if board is not None else [side] * count),
        "trend_side": np.array(trend if trend is not None else [side] * count),
    }
    return engine.prepare(tape, pd.DataFrame(events), session, "NK225", state)


def configuration(**changes: object) -> dict:
    """機能: 入口の待ち幅をゼロにした対照条件へ、対象の出口変更だけを加える。

    引数: changes (dict[str, object]) は個別条件。
    返り値: dict。入口・初期ストップを共通にした条件。
    """
    return dict(id="監査", family="監査", group="独立手計算", entry_offset=0.,
                warmup_min=0., cooldown_min=0., initial_stop_atr=2., trail_atr=2., **changes)


def check(name: str, prepared: dict, config: dict, expected: dict | None, records: list[dict]) -> None:
    """機能: 売買列の先頭取引を手計算値と照合し、短い原本の全打切りも確認する。

    引数: name (str)、prepared/config (dict)、expected (dict|None)、records (list[dict])。
    返り値: None。結果を records に追加する。
    """
    trades = engine.simulate(prepared, config)
    if expected is None:
        assert not trades, (name, trades)
    else:
        assert trades, name
        for key, value in expected.items():
            assert trades[0][key] == value, (name, key, trades[0][key], value)
    cuts = 0
    for count in range(1, len(prepared["seq"]) + 1):
        short = dict(prepared)
        for key in ("seq", "time_s", "bid", "ask", "bid_qty", "ask_qty", "atr", "board_side", "trend_side"):
            short[key] = prepared[key][:count]
        short["families"] = {}
        for family, values in prepared["families"].items():
            keep = values["indices"] < count
            short["families"][family] = {key: ([row for row, accepted in zip(value, keep) if accepted]
                                                       if key == "rows" else value[keep])
                                                for key, value in values.items()}
        observed = [trade for trade in engine.simulate(short, config) if trade["closed"]]
        wanted = [trade for trade in trades if trade["closed"] and trade["exit_seq"] <= short["seq"][-1]]
        assert observed == wanted, (name, count, observed, wanted)
        cuts += 1
    records.append(dict(検査=name, 手計算=expected, 取引=trades, 全打切り照合数=cuts))


def main() -> None:
    """機能: 条件付き短縮・時間帯切替・非遡及約定の独立手計算例を実行する。

    引数: なし。
    返り値: None。全検査結果を JSON に保存する。
    """
    records = []
    for side in (1, -1):
        label = "ロング" if side > 0 else "ショート"
        value = fixture([990, 1000, 1000, 1110, 1050, 1040], side=side)
        check(label + "利益到達で短縮", value, configuration(tighten_trigger_atr=1., tighten_width_atr=.5),
              dict(closed=True, entry_seq=3, exit_trigger_seq=5, exit_seq=6, net_points=10., max_favorable=100.), records)
        value = fixture([990, 1000, 1000, 1110, 1030, 1010], side=side)
        check(label + "建値保護でも飛び越え損失", value, configuration(breakeven_trigger_atr=1.),
              dict(closed=True, exit_trigger_seq=5, exit_seq=6, net_points=-20.), records)
        value = fixture([990, 1000, 1000, 1210, 1100, 1090], side=side)
        check(label + "最大順行の半分を保護", value, configuration(protect_trigger_atr=1., protect_fraction=.5),
              dict(closed=True, exit_trigger_seq=5, exit_seq=6, net_points=60., max_favorable=200.), records)

    # ----------------------------------------
    # 現在行で短縮したストップが現在気配を超えても、次の行まで条件成立を待つ。
    value = fixture([990, 1000, 1000, 1110, 1050, 1040, 1030], reverse_index=4)
    check("反対イベント短縮は次行から", value, configuration(opposite_width_atr=.5),
          dict(closed=True, exit_trigger_seq=6, exit_seq=7, net_points=0.), records)
    value = fixture([990, 1000, 1000, 1110, 1050, 1040, 1030], board=[1, 1, 1, 1, -1, -1, -1])
    check("板反転短縮は次行から", value, configuration(weak_width_atr=.5, state_trigger_atr=1.),
          dict(closed=True, exit_trigger_seq=6, exit_seq=7, net_points=0.), records)
    check("利益到達前の板反転では短縮しない", value, configuration(weak_width_atr=.5, state_trigger_atr=1.5),
          dict(closed=False, stop=910.), records)
    value = fixture([990, 1000, 1000, 1050, 1040, 1020, 1010], seconds=[0, 1, 2, 3, 6, 7, 8])
    check("時間経過かつ進展不足で短縮", value,
          configuration(time_tighten_min=.05, time_width_atr=.25, time_min_progress_atr=.5),
          dict(closed=True, exit_trigger_seq=6, exit_seq=7, net_points=-20.), records)
    value = fixture([990, 1000, 1000, 1110, 1040, 1020, 1010], seconds=[0, 1, 2, 3, 6, 7, 8])
    check("十分進展した場合は時間短縮しない", value,
          configuration(time_tighten_min=.05, time_width_atr=.25, time_min_progress_atr=.5),
          dict(closed=False, stop=910.), records)

    # ----------------------------------------
    # 米国開始の窓に入る前の建玉、窓を出た後の建玉、新規停止の区別を確認する。
    value = fixture([990, 1000, 1000, 1110, 1050, 1040, 1030])
    value["us_open"] = value["time_s"][4]
    check("米国窓の幅短縮は次行から", value,
          configuration(us_mode="幅変更", us_before_min=0., us_width_atr=.5),
          dict(closed=True, exit_trigger_seq=6, exit_seq=7, net_points=0.), records)
    check("米国窓では保有を返済", value, configuration(us_mode="返済", us_before_min=0.),
          dict(closed=True, exit_trigger_seq=5, exit_seq=6, net_points=10., exit_reason="米国開始前後の返済"), records)
    value = fixture([990, 1000, 1000, 1110, 1100, 1090, 1050, 1040], seconds=[0, 1, 2, 3, 4, 8, 9, 10])
    value["us_open"] = value["time_s"][4]
    check("米国窓の終了後もストップを緩めない", value,
          configuration(us_mode="幅変更", us_before_min=0., us_after_min=.05, us_width_atr=.5),
          dict(closed=True, exit_trigger_seq=7, exit_seq=8, net_points=10., stop=1060.), records)
    value = fixture([990, 1000, 1000, 1110, 1100, 1090])
    value["us_open"] = value["time_s"][0]
    check("米国窓で新規停止", value, configuration(us_mode="新規停止", us_before_min=0.), None, records)
    value = fixture([990, 1000, 1000, 1110, 1110, 1110], trend=[0, 0, 0, 1, 1, 1])
    value["us_open"] = value["time_s"][0]
    check("米国窓は順行確認後に新規条件作成", value,
          configuration(us_mode="順行確認", us_before_min=0.),
          dict(closed=False, condition_seq=4, trigger_seq=5, entry_seq=6), records)
    value = fixture([990, 1000, 1000, 1110, 1050, 1040])
    value["us_open"] = value["time_s"][1]
    check("既知の新規停止予定は未成立注文を取り消す", value,
          configuration(us_mode="新規停止", us_before_min=0.), None, records)
    value["us_open"] = value["time_s"][2]
    check("停止窓より前に成立済みの注文は次行で約定", value,
          configuration(us_mode="新規停止", us_before_min=0.),
          dict(closed=False, trigger_seq=2, entry_seq=3), records)

    # ----------------------------------------
    # 有効期限、固定 ATR、末尾の未返済、夏時間の換算を確認する。
    value = fixture([990, 1000, 1000, 1110, 1050, 1040], event_deadline=2.)
    config = configuration()
    config["entry_offset"] = 1.
    check("イベント期限を過ぎた反発を採用しない", value, config, None, records)
    value = fixture([990, 1000, 1000, 1110, 1050, 1040])
    value["atr"][2:] = 1000.
    check("注文設定時のATRを固定", value,
          configuration(tighten_trigger_atr=1., tighten_width_atr=.5),
          dict(closed=True, atr=100., net_points=10.), records)
    value = fixture([990, 1000, 1000, 1110, 1050])
    check("末尾で成立しても返済行がなければ未返済", value,
          configuration(tighten_trigger_atr=1., tighten_width_atr=.5),
          dict(closed=False, pending_exit="追跡ストップ"), records)
    assert pd.Timestamp(value["us_open"], unit="s", tz="Asia/Tokyo").strftime("%H:%M") == "22:30"
    output = {
        "実装SHA256": hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        "独立手計算件数": len(records),
        "全打切り照合数": sum(row["全打切り照合数"] for row in records),
        "保存期間の米国現物開始JST": "22:30",
        "検査": records,
    }
    (OUT / "新注文手計算監査.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"新注文の独立手計算 {len(records)} 件と全打切り照合が一致しました。", flush=True)


if __name__ == "__main__":
    main()
