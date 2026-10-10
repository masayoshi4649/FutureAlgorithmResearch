"""二銘柄の過去方向結合と、原本を別々に打ち切った売買の独立監査。"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

import model
import raw_features
import cross_research as cross


OUT = Path(__file__).resolve().parent


def manual_alignment(own: dict, peer: dict, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """検索関数を使わず、逐次ポインターで利用可能な相手行を求める。

    引数: own/peer（dict）各銘柄入力。lag（int）相手特徴の追加待機秒。
    返り値: tuple[ndarray, ndarray]。行番号と有効性。
    """
    own_frame, peer_frame = own["features"], peer["features"]
    own_times = own_frame.time_s.to_numpy(float)
    peer_times = peer_frame.time_s.to_numpy(float)
    result = np.full(len(own_times), -1, dtype=int)
    valid = np.zeros(len(own_times), dtype=bool)
    cursor = -1
    for index, stamp in enumerate(own_times):
        while cursor + 1 < len(peer_times) and peer_times[cursor + 1] <= stamp - lag:
            cursor += 1
        result[index] = cursor
        if cursor >= 0:
            age = stamp - peer_times[cursor]
            valid[index] = (lag <= age <= lag + 120
                            and peer_frame.block_delay_seconds.iloc[cursor] <= 60
                            and own_frame.block_delay_seconds.iloc[index] <= 60)
    return result, valid


def selected_configs() -> list[dict]:
    """板一致・価格混合・逆向き除外・相手のみの16注文条件を選ぶ。

    引数: なし。
    返り値: list[dict]。結果を見ずに選んだ代表条件。
    """
    return [config for config in cross.configs() if config["family"] in ("C03", "C07", "C09", "C11")]


def build_input(frame: pd.DataFrame, quotes: list[dict], session: str, symbol: str) -> dict:
    """原本の途中打切りから再抽出した板・気配に、過去の足だけを結合する。

    引数: frame（DataFrame）板特徴。quotes（list[dict]）気配。session/symbol（str）。
    返り値: dict。二銘柄モデルへ入力できる単銘柄状態。
    """
    # 実際のresearch.loadと同じCSV保存・再読込みを通して浮動小数の桁をそろえる。
    frame = pd.read_csv(io.StringIO(frame.to_csv(index=False)))
    quote_frame = pd.DataFrame(quotes)
    tape = {key: quote_frame[key].to_numpy() for key in quote_frame.columns}
    atr, price = model.price_features(session, symbol, frame.time_s.to_numpy(float), cutoff=float(tape["time_s"][-1]))
    signals, pressure = model.directions(frame, price)
    return dict(features=frame, tape=tape, signals=signals, atr=atr, pressure=pressure)


def before_time(own: dict, cutoff: float) -> dict:
    """相手原本を切る監査用に、自銘柄観測を比較可能な過去区間へ限定する。

    引数: own（dict）全量入力。cutoff（float）最終約定時計の上限。
    返り値: dict。自銘柄の既知部分。
    """
    mask = own["features"].time_s.to_numpy(float) <= cutoff
    quote_mask = own["tape"]["time_s"] <= cutoff
    return dict(
        features=own["features"].loc[mask].reset_index(drop=True),
        tape={key: value[quote_mask] for key, value in own["tape"].items() if key != "tick"},
        signals={key: value[mask] for key, value in own["signals"].items()},
        atr=own["atr"][mask], pressure=own["pressure"][mask],
    )


def replay(own: dict, peer: dict, signals: dict, alignment: dict, config: dict, session: str, symbol: str) -> list[dict]:
    """途中区間にも使用できる売買再生を行い、相手参照証跡を付ける。

    引数: own/peer/signals/alignment/config（dict）、session/symbol（str）。
    返り値: list[dict]。確定・未確定取引。
    """
    trades = model.simulate(own["tape"], own["features"], signals[config["family"]], own["atr"], own["pressure"], config, session, symbol)
    return [cross.enrich_trade(trade, own, peer, alignment, 60) for trade in trades]


def assert_prefix(own: dict, peer: dict, expected_signals: dict, full_trades: dict, session: str, symbol: str, kind: str, cut: int) -> list[dict]:
    """過去方向全12系統と、参照証跡付き確定取引全属性の一致を検査する。

    引数: own/peer/expected_signals/full_trades（dict）、session/symbol/kind（str）、cut（int）。
    返り値: list[dict]。16条件ごとの照合結果。
    """
    signals, alignment = cross.cross_directions(own, peer)
    for family in signals:
        np.testing.assert_array_equal(signals[family], expected_signals[family][:len(own["features"])])
    records = []
    last_seq = int(own["tape"]["seq"][-1])
    for config in selected_configs():
        observed = [trade for trade in replay(own, peer, signals, alignment, config, session, symbol) if trade["closed"]]
        expected = [trade for trade in full_trades[config["id"]] if trade["closed"] and trade["exit_seq"] <= last_seq]
        assert observed == expected, f"クロス確定取引不一致: {session} {symbol} {kind} {cut} {config['id']}"
        records.append(dict(銘柄=symbol, セッション=session, 打切り対象=kind, 原本打切り数=cut,
                            条件=config["id"], 全12方向一致=True, 特徴照合行数=len(own["features"]),
                            確定取引照合数=len(observed), 取引属性照合数=sum(len(row) for row in observed), 一致=True))
    return records


def main() -> None:
    """二銘柄を別々に打ち切り、待機時刻の独立照合と取引不変性を記録する。

    引数: なし。
    返り値: None。監査JSONを保存する。
    """
    tracked = [Path(module.__file__) for module in (model, raw_features, cross)]
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    sources = {(symbol, session): path for path, symbol, session in raw_features.sources()}
    all_records, all_alignments = [], []
    for session in model.SESSIONS:
        inputs = {symbol: cross.load(session, symbol) for symbol in model.SYMBOLS}
        full_signals, full_trades = {}, {}
        for symbol in model.SYMBOLS:
            peer_symbol = model.SYMBOLS[1 - model.SYMBOLS.index(symbol)]
            own, peer = inputs[symbol], inputs[peer_symbol]
            for lag in (60, 120, 300):
                observed_indices, observed_valid, _ = cross.aligned_peer(own, peer, lag)
                expected_indices, expected_valid = manual_alignment(own, peer, lag)
                np.testing.assert_array_equal(observed_indices, expected_indices)
                np.testing.assert_array_equal(observed_valid, expected_valid)
                all_alignments.append(dict(セッション=session, 銘柄=symbol, 待機秒=lag, 全特徴行数=len(observed_indices), 有効行数=int(observed_valid.sum()), 一致=True))
            signals, alignment = cross.cross_directions(own, peer)
            full_signals[symbol] = signals
            full_trades[symbol] = {config["id"]: replay(own, peer, signals, alignment, config, session, symbol) for config in selected_configs()}

        # ----------------------------------------
        # 同じ原本prefixを、自銘柄の打切りと相手銘柄の打切りの双方に使う。
        for cut_symbol in model.SYMBOLS:
            path = sources[(cut_symbol, session)]
            audit = json.loads((OUT / "features" / f"{cut_symbol}_{session}_audit.json").read_text(encoding="utf-8"))
            peer_symbol = model.SYMBOLS[1 - model.SYMBOLS.index(cut_symbol)]
            for fraction in (0.33337, 0.66671):
                cut = max(1, int(audit["読取行数"] * fraction))
                quotes = []
                prefix, _ = raw_features.extract_features(path, cut_symbol, session, max_rows=cut, quotes=quotes)
                cut_input = build_input(prefix, quotes, session, cut_symbol)
                all_records.extend(assert_prefix(cut_input, inputs[peer_symbol], full_signals[cut_symbol], full_trades[cut_symbol], session, cut_symbol, "自銘柄", cut))
                comparable_time = float(prefix.time_s.iloc[-1]) + 60
                own_known = before_time(inputs[peer_symbol], comparable_time)
                all_records.extend(assert_prefix(own_known, cut_input, full_signals[peer_symbol], full_trades[peer_symbol], session, peer_symbol, "他銘柄", cut))
        print(f"二銘柄独立打切り一致: {session}", flush=True)
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    result = dict(コードSHA256=before, 監査中コード変更なし=before == after,
                  時刻対応独立照合=all_alignments, 打切り照合=all_records,
                  照合セル数=len(all_records), 確定取引照合延べ数=sum(row["確定取引照合数"] for row in all_records),
                  取引属性照合延べ数=sum(row["取引属性照合数"] for row in all_records),
                  限界="受信時刻と銘柄共通の行順がないため、60秒待機はモデル仮定。原本を別々に途中で切った過去非依存の検査は、当時の実受信済みを証明しない。")
    (OUT / "二銘柄_独立因果監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert before == after, "監査中に対象コードが変更されたため再実行が必要"
    print("二銘柄の時刻結合・別々の原本打切り・確定取引が一致しました。", flush=True)


if __name__ == "__main__":
    main()
