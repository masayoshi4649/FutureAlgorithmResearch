"""生板を途中で打ち切り、転換イベントと確定売買の未来非依存を独立に確認する。"""

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
import turning_signals


def canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """通常の特徴CSV保存・読込みと同じ数値精度を再現する。

    引数: frame（DataFrame）原本から抽出した特徴。
    返り値: DataFrame。CSVの往復を経た特徴。
    """
    return pd.read_csv(io.StringIO(frame.to_csv(index=False)))


def compare_events(observed: pd.DataFrame, expected: pd.DataFrame, label: str) -> dict:
    """転換イベントの全属性と参照順序を照合する。

    引数: observed/expected（DataFrame）比較するイベント。label（str）検査名。
    返り値: dict。照合件数と結果。
    """
    observed = observed.reset_index(drop=True)
    expected = expected.reset_index(drop=True)
    pd.testing.assert_frame_equal(observed, expected, check_exact=True, obj=label)
    if len(observed):
        assert (observed.source_last_seq < observed.seq).all(), label
        assert observed.event_id.is_unique, label
        assert (observed.deadline_time_s == observed.time_s + 600).all(), label
        if "peer_available_time_s" in observed:
            used = observed.peer_seq >= 0
            assert (observed.loc[used, "peer_available_time_s"] <= observed.loc[used, "time_s"]).all(), label
            assert (observed.loc[used, "peer_source_last_seq"] < observed.loc[used, "peer_seq"]).all(), label
    return dict(照合イベント数=len(observed), 照合属性数=len(observed.columns), 全属性一致=True)


def main() -> None:
    """全12原本を二地点ずつ打ち切り、自銘柄・相手銘柄の利用可能性を照合する。

    引数: なし。
    返り値: None。日本語の監査JSONを保存する。
    """
    tracked = [Path(raw_features.__file__), Path(turning_signals.__file__)]
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    source_paths = {(symbol, session): path for path, symbol, session in raw_features.sources()}
    sessions = list(dict.fromkeys(session for _, _, session in raw_features.sources()))
    records = []
    for session in sessions:
        frames = {symbol: pd.read_csv(V8 / "features" / f"{symbol}_{session}.csv") for symbol in ("NK225", "TOPIX")}
        full_events = {}
        for symbol, peer_symbol in (("NK225", "TOPIX"), ("TOPIX", "NK225")):
            events, _ = turning_signals.build_events(session, symbol, frames[symbol], frames[peer_symbol])
            full_events[symbol] = events
            compare_events(events, events, f"全量証跡 {session} {symbol}")

        # ----------------------------------------
        # 原本を読み切って表を切る操作ではなく、読込み自体を生行で打ち切る。
        for symbol, peer_symbol in (("NK225", "TOPIX"), ("TOPIX", "NK225")):
            source = source_paths[(symbol, session)]
            audit = json.loads((V8 / "features" / f"{symbol}_{session}_audit.json").read_text(encoding="utf-8"))
            for fraction in (0.33337, 0.66671):
                cut = int(audit["読取行数"] * fraction)
                quotes = []
                prefix, extraction = raw_features.extract_features(source, symbol, session, max_rows=cut, quotes=quotes)
                prefix = canonical_frame(prefix)
                expected_frame = frames[symbol].loc[frames[symbol].seq < cut].reset_index(drop=True)
                pd.testing.assert_frame_equal(prefix, expected_frame, check_exact=True)
                assert extraction["未解放末尾ブロック行数"] > 0
                cutoff = float(prefix.time_s.iloc[-1])
                events, _ = turning_signals.build_events(session, symbol, prefix, frames[peer_symbol], cutoff=cutoff)
                expected = full_events[symbol].loc[full_events[symbol].seq < cut]
                own = compare_events(events, expected, f"自銘柄 {session} {symbol} {cut}")
                records.append(dict(セッション=session, 銘柄=symbol, 打切り対象="自銘柄", 生行打切り数=cut,
                                    特徴照合行数=len(prefix), 気配行数=len(quotes), **own))

                # ----------------------------------------
                # 相手を打ち切る場合は、その最終解放時刻＋待機60秒までの自銘柄を照合する。
                own_frame = frames[peer_symbol].loc[frames[peer_symbol].time_s <= cutoff + 60].reset_index(drop=True)
                own_cutoff = float(own_frame.time_s.iloc[-1])
                events, _ = turning_signals.build_events(session, peer_symbol, own_frame, prefix, cutoff=own_cutoff)
                expected = full_events[peer_symbol].loc[full_events[peer_symbol].seq <= int(own_frame.seq.iloc[-1])]
                peer = compare_events(events, expected, f"相手銘柄 {session} {peer_symbol} {cut}")
                records.append(dict(セッション=session, 銘柄=peer_symbol, 打切り対象="相手銘柄", 生行打切り数=cut,
                                    特徴照合行数=len(own_frame), 相手特徴照合行数=len(prefix), **peer))
            print(f"原本打切りの転換イベント一致: {session} {symbol}", flush=True)
    final = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    result = dict(使用コードSHA256=hashes, 監査中コード変更なし=hashes == final,
                  原本変更なし=True, API取得なし=True, 照合セル数=len(records),
                  照合イベント延べ数=sum(record["照合イベント数"] for record in records), 結果=records,
                  限界="保存順序の因果性を確認する検査であり、実受信時刻や本番約定の保証ではない。相手銘柄は60秒追加待機のモデル仮定。重複照合イベント数は独立取引数ではない。")
    (OUT / "転換イベント原本打切り監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert hashes == final, "監査中に実装が変更されたため再実行が必要"
    print("全原本の転換イベントprefix検査に合格しました。", flush=True)


if __name__ == "__main__":
    main()
