"""生板内の注文順序、トレーリング、取消競合、締切を手計算と照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import execution


OUT = Path(__file__).resolve().parent
SESSION = "2026-09-23_Day"
NOW = pd.Timestamp("2026-09-23T09:30:00+09:00").timestamp()


def inputs(side: int, bids: list[float], times: list[float] | None = None) -> tuple[dict, pd.DataFrame]:
    """方向対称の人工気配と転換イベント一件を作る。

    引数: side（int）方向。bids（list[float]）ロング基準気配。times（list[float]|None）時刻。
    返り値: tuple[dict, DataFrame]。気配配列とイベント。
    """
    bid = np.asarray(bids, dtype=float)
    ask = bid + 10
    if side < 0:
        bid, ask = 132000 - ask, 132000 - bid
    count = len(bid)
    tape = dict(seq=np.arange(10, 10 + count), time_s=np.full(count, NOW) if times is None else np.asarray(times),
                bid=bid, ask=ask, bid_qty=np.ones(count), ask_qty=np.ones(count), atr=np.full(count, 20.))
    events = pd.DataFrame([dict(event_id="監査転換1", family="T01", seq=10, source_last_seq=9,
                                time_s=NOW, side=side, atr=10., deadline_time_s=NOW+600, reason={"監査": "手計算"})])
    return tape, events


def config(exit_name: str = "追跡1ATR", entry: str = "初動逆指値") -> dict:
    """本番定義の設定辞書を条件名で一つ抽出する。

    引数: exit_name/entry（str）出口と入口名。
    返り値: dict。本番と同一の設定辞書。
    """
    return next(value for value in execution.configs() if value["family"] == "T01" and value["entry"] == entry and value["exit"] == exit_name)


def verify_trailing(side: int, exit_name: str) -> dict:
    """全行同時刻の約定と三種類の追跡出口を手計算する。

    引数: side（int）方向。exit_name（str）出口方式。
    返り値: dict。照合された取引と確認事項。
    """
    tape, events = inputs(side, [66000, 66000, 66000, 66050, 66040, 66020, 66000, 65980])
    tape["atr"][2:] = 1000.
    trades = execution.simulate(tape, events, config(exit_name), SESSION, "NK225")
    assert len(trades) == 1 and trades[0]["closed"]
    trade = trades[0]
    trigger, fill, points = {"追跡1ATR": (15, 16, -30.), "追跡2ATR": (16, 17, -50.), "順行1ATRで保護": (14, 15, -10.)}[exit_name]
    assert trade["condition_seq"] == 10 and trade["trigger_seq"] == 11 and trade["entry_seq"] == 12
    assert trade["entry_price"] == (66010. if side > 0 else 65990.)
    assert trade["exit_trigger_seq"] == trigger and trade["exit_seq"] == fill
    assert trade["max_favorable"] == 40.
    assert trade["net_points"] == points
    assert trade["atr"] == 20. and trade["event_atr"] == 10.
    return dict(方向="ロング" if side > 0 else "ショート", 出口=exit_name, 全行最終約定時刻が同一=True,
                発注成立約定を別行に分離=True, 価格飛びを次行気配で評価=True, 発注時ATRを固定=True, 取引=trade)


def verify_race(side: int) -> dict:
    """旧逆指値成立と反対イベントが同時に観測される例を検査する。

    引数: side（int）古い注文の方向。
    返り値: dict。旧注文の成立が取消より先に扱われた記録。
    """
    tape, events = inputs(side, [66000, 66000, 66000, 66050, 66040, 66020, 66000])
    second = events.iloc[0].to_dict()
    second.update(event_id="監査転換2", seq=11, source_last_seq=10, side=-side)
    events = pd.concat([events, pd.DataFrame([second])], ignore_index=True)
    trade = execution.simulate(tape, events, config(), SESSION, "NK225")[0]
    assert trade["side"] == side and trade["event_id"] == "監査転換1"
    assert trade["trigger_seq"] == 11 and trade["entry_seq"] == 12
    assert trade["closed"] and trade["exit_reason"] == "追跡ストップ"
    return dict(古い方向=side, 旧閾値成立を優先=True, 受付後の逆情報で遡及取消なし=True, 取引=trade)


def verify_close(side: int) -> dict:
    """返済締切とその途中打切りを比較する。

    引数: side（int）方向。
    返り値: dict。締切返済と未返済評価を区別した記録。
    """
    limit = pd.Timestamp("2026-09-23T15:35:00+09:00").timestamp()
    tape, events = inputs(side, [66000, 66000, 66000, 66000, 65970], [NOW, NOW, NOW, limit, limit+1])
    closed = execution.simulate(tape, events, config(), SESSION, "NK225")[0]
    assert closed["exit_reason"] == "セッション内返済" and closed["exit_in_session"]
    assert closed["exit_trigger_seq"] == 13 and closed["exit_seq"] == 14
    assert closed["net_points"] == -60.
    prefix_tape = {key: value[:4] for key, value in tape.items()}
    open_trade = execution.simulate(prefix_tape, events, config(), SESSION, "NK225")[0]
    assert not open_trade["closed"] and open_trade["pending_exit"] == "セッション内返済"
    return dict(方向=side, 締切次行で返済=True, 途中打切りで人工返済なし=True, 確定取引=closed, 途中評価=open_trade)


def main() -> None:
    """方向対称の10例を実行し、注文再生監査を保存する。

    引数: なし。
    返り値: None。日本語JSONを書き出す。
    """
    code_hash = hashlib.sha256(Path(execution.__file__).read_bytes()).hexdigest()
    result = dict(実装SHA256=code_hash,
                  追跡手計算=[verify_trailing(side, name) for side in (1, -1) for name in ("追跡1ATR", "追跡2ATR", "順行1ATRで保護")],
                  取消成立競合=[verify_race(side) for side in (1, -1)],
                  セッション内返済=[verify_close(side) for side in (1, -1)])
    result["監査中実装変更なし"] = code_hash == hashlib.sha256(Path(execution.__file__).read_bytes()).hexdigest()
    assert result["監査中実装変更なし"]
    (OUT / "注文再生手計算監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("両方向の追跡・取消競合・セッション返済10例が手計算と一致しました。", flush=True)


if __name__ == "__main__":
    main()
