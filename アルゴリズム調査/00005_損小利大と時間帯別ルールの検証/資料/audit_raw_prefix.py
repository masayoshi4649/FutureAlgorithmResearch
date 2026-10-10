"""原本の読み込みを途中で止め、新信号・出口状態・確定売買の未来非依存を検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import engine
import signals

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SPEC = importlib.util.spec_from_file_location("独立原本抽出_v10", ROOT / "work" / "wave_v8" / "raw_features.py")
RAW = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RAW
SPEC.loader.exec_module(RAW)


def clean(value: object) -> object:
    """機能: 欠測値と NumPy 数値を、同一性の比較が可能な形へ変換する。

    引数: value (object) は比較対象。
    返り値: object。欠測値を None とした比較対象。
    """
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main() -> None:
    """機能: 全１２原本を２地点で切り、主要条件の確定済み取引を全量再生と照合する。

    引数: なし。
    返り値: None。原本打切り監査の JSON を保存する。
    """
    final = json.loads((OUT / "最終選択.json").read_text(encoding="utf-8"))
    conditions = final["固定条件"]
    inventory = json.loads((OUT / "入力原本確認.json").read_text(encoding="utf-8"))["銘柄セッション"]
    source = {(row["セッション"], row["銘柄"]): row for row in inventory}
    tracked = [Path(module.__file__) for module in (engine, signals, RAW)]
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    inputs = signals.load_inputs()
    records, state_records, event_records = [], [], []
    for (session, symbol), item in inputs.items():
        full = engine.prepare(item["tape"], item["events"], session, symbol, item["state"])
        full_trades = {config["id"]: engine.simulate(full, config) for config in conditions}
        info = source[(session, symbol)]
        for fraction in (.4137, .9713):
            cut = int(info["原本行数"] * fraction)
            quotes = []
            features, _ = RAW.extract_features(ROOT / info["原本"], symbol, session, max_rows=cut, quotes=quotes)
            features = pd.read_csv(io.StringIO(features.to_csv(index=False)))
            quote_frame = pd.DataFrame(quotes)
            tape = {column: quote_frame[column].to_numpy() for column in quote_frame}
            cutoff, last_seq = float(tape["time_s"][-1]), int(tape["seq"][-1])
            tape["atr"] = signals.atr_at(session, symbol, tape["time_s"], cutoff=cutoff)
            peer = item["peer_features"].loc[item["peer_features"]["time_s"] + 60 <= cutoff]
            events, _ = signals.build_events(session, symbol, features, peer, cutoff=cutoff)
            expected_events = item["events"].loc[item["events"]["seq"] <= last_seq]
            assert clean(events.to_dict("records")) == clean(expected_events.to_dict("records")), (session, symbol, cut, "転換")
            event_records.append(dict(セッション=session, 銘柄=symbol, 原本打切り行数=cut,
                                      転換イベント数=len(events), 全属性一致=True))
            z = signals.price_grid(session, symbol, cutoff)
            state = signals.state_at(tape, features, z)
            full_mask = item["tape"]["seq"] <= last_seq
            assert np.array_equal(tape["seq"], item["tape"]["seq"][full_mask])
            for key in state:
                assert np.allclose(state[key], item["state"][key][full_mask], equal_nan=True), (session, symbol, cut, key)
            state_records.append(dict(セッション=session, 銘柄=symbol, 原本打切り行数=cut,
                                      気配行数=len(tape["seq"]), 状態配列数=len(state), 一致=True))
            ready = engine.prepare(tape, events, session, symbol, state)
            for config in conditions:
                trades = engine.simulate(ready, config)
                observed = [trade for trade in trades if trade["closed"]]
                expected = [trade for trade in full_trades[config["id"]]
                            if trade["closed"] and trade["exit_seq"] <= last_seq]
                assert clean(observed) == clean(expected), (session, symbol, cut, config["id"])
                records.append(dict(セッション=session, 銘柄=symbol, 原本打切り行数=cut, 方式=config["id"],
                                    確定取引照合数=len(observed), 属性照合数=sum(len(trade) for trade in observed), 一致=True))
        print(f"原本打切りの転換・出口状態・確定売買が一致: {session} {symbol}", flush=True)
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    assert before == after
    output = dict(実装SHA256=before, 監査中コード変更なし=True,
                  条件=[config["id"] for config in conditions], 原本打切り回数=len(event_records),
                  売買照合セル数=len(records), 確定取引照合延べ数=sum(row["確定取引照合数"] for row in records),
                  属性照合延べ数=sum(row["属性照合数"] for row in records),
                  転換イベント照合=event_records, 状態照合=state_records, 確定売買照合=records,
                  限界="延べ照合数は独立した取引機会数ではない。保存順の因果性の検査であり、実受信時計や本番約定の検証ではない。")
    (OUT / "原本打切り独立監査.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
