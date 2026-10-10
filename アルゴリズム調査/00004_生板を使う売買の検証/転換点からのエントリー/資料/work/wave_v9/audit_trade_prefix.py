"""原本の途中打切りから注文まで再計算し、確定取引の未来非依存を確認する。"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
V8 = OUT.parent / "wave_v8"
sys.dont_write_bytecode = True
sys.path.insert(0, str(V8))
import raw_features
sys.path.insert(0, str(OUT))
import execution
import turning_signals


def selected_configs() -> list[dict]:
    """結果を見ず、全15系統と両入口、三出口を含む30条件を抽出する。

    引数: なし。
    返り値: list[dict]。系統番号で出口を巡回割当した代表条件。
    """
    exits = ["追跡1ATR", "追跡2ATR", "順行1ATRで保護"]
    return [config for config in execution.configs()
            if config["exit"] == exits[(int(config["family"][1:]) + int(config["entry"] == "追跡0.25ATR")) % 3]]


def clean(value: object) -> object:
    """欠測のNaNだけを等値比較可能なNoneへそろえる。

    引数: value（object）取引属性。
    返り値: object。数値の精度を保った比較用属性。
    """
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return None
    return value


def tape_from_quotes(quotes: list[dict], session: str, symbol: str) -> dict:
    """原本から再抽出した気配へ、その時点までのATRを結合する。

    引数: quotes（list[dict]）気配。session/symbol（str）識別子。
    返り値: dict。注文再生へ渡す配列。
    """
    frame = pd.DataFrame(quotes)
    tape = {key: frame[key].to_numpy() for key in frame}
    tape["atr"] = execution.atr_at(session, symbol, tape["time_s"], cutoff=float(tape["time_s"][-1]))
    return tape


def verify_trades(tape: dict, events: pd.DataFrame, full_trades: dict, session: str, symbol: str,
                  kind: str, cut: int) -> list[dict]:
    """途中時点までに確定した取引の全属性を照合する。

    引数: tape/full_trades（dict）、events（DataFrame）、session/symbol/kind（str）、cut（int）。
    返り値: list[dict]。条件ごとの照合記録。
    """
    records = []
    last_seq = int(tape["seq"][-1])
    for config in selected_configs():
        trades = execution.simulate(tape, events, config, session, symbol)
        observed = [trade for trade in trades if trade["closed"]]
        expected = [trade for trade in full_trades[config["id"]] if trade["closed"] and trade["exit_seq"] <= last_seq]
        assert clean(observed) == clean(expected), f"確定取引不一致: {session} {symbol} {kind} {cut} {config['id']}"
        assert len({trade["event_id"] for trade in trades}) == len(trades)
        for trade in trades:
            assert trade["source_last_seq"] < trade["signal_seq"] <= trade["condition_seq"] < trade["trigger_seq"] < trade["entry_seq"]
            if trade["closed"]:
                assert trade["entry_seq"] < trade["exit_trigger_seq"] < trade["exit_seq"]
                assert trade["exit_in_session"]
        records.append(dict(セッション=session, 銘柄=symbol, 打切り対象=kind, 原本打切り行数=cut,
                            条件=config["id"], 気配行数=len(tape["seq"]), 転換イベント数=len(events),
                            確定取引照合数=len(observed), 取引属性照合数=sum(len(trade) for trade in observed), 一致=True))
    return records


def main() -> None:
    """全12原本二地点の自銘柄と相手銘柄について30条件を再生する。

    引数: なし。
    返り値: None。確定売買の監査JSONを保存する。
    """
    tracked = [Path(module.__file__) for module in (raw_features, turning_signals, execution)]
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    source_paths = {(symbol, session): path for path, symbol, session in raw_features.sources()}
    all_records = []
    configurations = selected_configs()
    assert len(configurations) == 30
    for session in execution.SESSIONS:
        frames = {symbol: pd.read_csv(V8 / "features" / f"{symbol}_{session}.csv") for symbol in execution.SYMBOLS}
        tapes, full_trades = {}, {}
        for symbol, peer_symbol in (("NK225", "TOPIX"), ("TOPIX", "NK225")):
            with np.load(V8 / "features" / f"約定系列_{symbol}_{session}.npz") as saved:
                tape = {key: saved[key] for key in saved.files if key != "tick"}
            tape["atr"] = execution.atr_at(session, symbol, tape["time_s"])
            tapes[symbol] = tape
            events, _ = turning_signals.build_events(session, symbol, frames[symbol], frames[peer_symbol])
            full_trades[symbol] = {config["id"]: execution.simulate(tape, events, config, session, symbol) for config in configurations}

        # ----------------------------------------
        # 将来の生行を読まずに作ったprefixから、イベントと実行用ATRも作り直す。
        for symbol, peer_symbol in (("NK225", "TOPIX"), ("TOPIX", "NK225")):
            audit = json.loads((V8 / "features" / f"{symbol}_{session}_audit.json").read_text(encoding="utf-8"))
            for fraction in (0.33337, 0.66671):
                cut = int(audit["読取行数"] * fraction)
                quotes = []
                prefix, _ = raw_features.extract_features(source_paths[(symbol, session)], symbol, session, max_rows=cut, quotes=quotes)
                prefix = pd.read_csv(io.StringIO(prefix.to_csv(index=False)))
                prefix_tape = tape_from_quotes(quotes, session, symbol)
                events, _ = turning_signals.build_events(session, symbol, prefix, frames[peer_symbol], cutoff=float(prefix.time_s.iloc[-1]))
                all_records.extend(verify_trades(prefix_tape, events, full_trades[symbol], session, symbol, "自銘柄", cut))

                # ----------------------------------------
                # 相手銘柄を打ち切った場合、最後に解放された相手情報が使用可能な時点までを照合する。
                cutoff = float(prefix.time_s.iloc[-1]) + 60
                own_frame = frames[peer_symbol].loc[frames[peer_symbol].time_s <= cutoff].reset_index(drop=True)
                mask = tapes[peer_symbol]["time_s"] <= cutoff
                own_tape = {key: values[mask] for key, values in tapes[peer_symbol].items()}
                own_tape["atr"] = execution.atr_at(session, peer_symbol, own_tape["time_s"], cutoff=float(own_tape["time_s"][-1]))
                events, _ = turning_signals.build_events(session, peer_symbol, own_frame, prefix, cutoff=float(own_frame.time_s.iloc[-1]))
                all_records.extend(verify_trades(own_tape, events, full_trades[peer_symbol], session, peer_symbol, "相手銘柄", cut))
            print(f"原本からの確定売買一致: {session} {symbol}", flush=True)
    final = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    result = dict(使用コードSHA256=hashes, 監査中コード変更なし=hashes == final, 条件数=len(configurations),
                  条件=[config["id"] for config in configurations], 照合セル数=len(all_records),
                  確定取引照合延べ数=sum(row["確定取引照合数"] for row in all_records),
                  取引属性照合延べ数=sum(row["取引属性照合数"] for row in all_records), 結果=all_records,
                  限界="同じ取引を複数のprefixと条件で照合するため件数は独立取引数ではない。保存順序の未来非依存と実受信順・本番約定は別問題。")
    (OUT / "確定売買原本打切り監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert hashes == final, "監査中の実装変更により再実行が必要"
    print("原本からの確定売買prefix検査に合格しました。", flush=True)


if __name__ == "__main__":
    main()
