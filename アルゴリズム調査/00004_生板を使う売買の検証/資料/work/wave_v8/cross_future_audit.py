"""相手銘柄の未来生板を改変しても、自銘柄の過去売買が変わらないことを調べる。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import model
import raw_features
import cross_research as cross
import cross_causal_audit as causal


OUT = Path(__file__).resolve().parent


def change_future(source: Path, destination: Path, cut: int) -> None:
    """指定行より後の板価格と数量だけを改変した監査用コピーを作る。

    引数: source/destination（Path）原本と監査用コピー。cut（int）未来改変の先頭行。
    返り値: None。原本の時刻・保存順・過去行を保持する。
    """
    with source.open(encoding="utf-8") as incoming, destination.open("w", encoding="utf-8", newline="\n") as outgoing:
        for seq, line in enumerate(incoming):
            if seq < cut:
                outgoing.write(line)
                continue
            row = json.loads(line)
            for side, multiplier in (("Buy", 7), ("Sell", 2)):
                for level in range(1, 11):
                    item = row.get(f"{side}{level}") or {}
                    if isinstance(item.get("Price"), (int, float)):
                        item["Price"] += 100
                    if isinstance(item.get("Qty"), (int, float)):
                        item["Qty"] *= multiplier
            if isinstance(row.get("CurrentPrice"), (int, float)):
                row["CurrentPrice"] += 100
            outgoing.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    """TOPIXの未来改変をNK225の過去判定へ伝えないことを検査する。

    引数: なし。
    返り値: None。監査用コピーを消去し、検査結果JSONを保存する。
    """
    session, own_symbol, peer_symbol = "2026-09-23_Day", "NK225", "TOPIX"
    source = raw_features.ROOT / "book" / peer_symbol / f"{session}.jsonl"
    audit = json.loads((OUT / "features" / f"{peer_symbol}_{session}_audit.json").read_text(encoding="utf-8"))
    cut = int(audit["読取行数"] * 0.50003)
    temporary = OUT / "他銘柄未来改変_監査専用.jsonl"
    change_future(source, temporary, cut)
    altered_quotes = []
    altered_features, _ = raw_features.extract_features(temporary, peer_symbol, session, quotes=altered_quotes)
    altered_peer = causal.build_input(altered_features, altered_quotes, session, peer_symbol)
    own, peer = cross.load(session, own_symbol), cross.load(session, peer_symbol)
    unchanged_features = peer["features"].loc[peer["features"].seq < cut].reset_index(drop=True)
    observed_features = altered_peer["features"].loc[altered_peer["features"].seq < cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(observed_features, unchanged_features, check_exact=True)
    changed_count = sum(int((value != altered_peer["signals"][key]).sum()) for key, value in peer["signals"].items())
    assert changed_count > 0, "未来の方向を実際に変える改変になっていない"
    boundary = float(unchanged_features.time_s.iloc[-1]) + 60
    own_known = causal.before_time(own, boundary)
    original_signals, original_alignment = cross.cross_directions(own_known, peer)
    altered_signals, altered_alignment = cross.cross_directions(own_known, altered_peer)
    for family in original_signals:
        np.testing.assert_array_equal(original_signals[family], altered_signals[family])
    checks = []
    for config in causal.selected_configs():
        original = [row for row in causal.replay(own_known, peer, original_signals, original_alignment, config, session, own_symbol) if row["closed"]]
        altered = [row for row in causal.replay(own_known, altered_peer, altered_signals, altered_alignment, config, session, own_symbol) if row["closed"]]
        assert altered == original, f"未来相手改変で過去取引が変化: {config['id']}"
        checks.append(dict(条件=config["id"], 確定取引照合数=len(original), 一致=True))

    # ----------------------------------------
    # 相手銘柄が一行も届いていない起動状態でも、全方向を中立にする。
    empty_peer = dict(peer)
    empty_peer["features"] = peer["features"].iloc[:0].copy()
    empty_peer["signals"] = {key: value[:0] for key, value in peer["signals"].items()}
    empty_signals, empty_alignment = cross.cross_directions(own_known, empty_peer)
    assert all(np.count_nonzero(value) == 0 for value in empty_signals.values())
    assert not empty_alignment["valid"].any()
    temporary.unlink()
    result = dict(
        セッション=session, 自銘柄=own_symbol, 改変対象=peer_symbol, 未来改変開始seq=cut,
        未来改変で変化した相手方向延べセル数=changed_count,
        過去方向照合行数=len(own_known["features"]), 過去12方向一致=True,
        過去確定取引照合=checks, 相手未到着で全方向ゼロ=True,
        コードSHA256={Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in (model, raw_features, cross)},
    )
    (OUT / "二銘柄_未来改変監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("相手銘柄の未来改変と未到着の独立監査に合格しました。", flush=True)


if __name__ == "__main__":
    main()
