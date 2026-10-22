"""前完了場の保存提供 IV を次場の固定尺度へ変換する。金融再生は行わない。"""

from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import math
import pathlib
import statistics
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent
SOURCE = OUT.parent / "inventory/オプション保存608ファイルの境界目録.json"
SOURCE_SHA = "28f4fe9f7e0c0a6e9f6890737cb4ede6cf187c84fef9d42ad79dd10f906ea9a6"
JST = dt.timezone(dt.timedelta(hours=9))


def session_times(session: str) -> tuple[dt.datetime, dt.datetime]:
    """
    機能: 保存セッション名から取引開始と終了の日本時間を求める。
    引数: session (str) 日付_Day または 日付_Night。
    返り値: tuple[datetime, datetime] 開始時刻、終了時刻。
    """
    day_text, kind = session.split("_")
    day = dt.date.fromisoformat(day_text)
    if kind == "Day":
        start = dt.datetime.combine(day, dt.time(8, 45), JST)
        end = dt.datetime.combine(day, dt.time(15, 45), JST)
    elif kind == "Night":
        start = dt.datetime.combine(day, dt.time(17), JST)
        end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(6), JST)
    else:
        raise ValueError("セッション種別が不正です。")
    return start, end


def select_features(boundaries: list[dict[str, Any]], sessions: list[str]) -> list[dict[str, Any]]:
    """
    機能: 直前一場の末尾だけから、次場固定 IV を選ぶ。
    引数: boundaries (list[dict]) 所有済み境界目録、sessions (list[str]) 昇順の先物セッション。
    返り値: list[dict] 各場の既知・不明区分、固定 IV、原標本の参照。
    """
    if sessions != sorted(set(sessions)):
        raise ValueError("セッション順が重複または逆順です。")
    files_by_session = collections.defaultdict(list)
    for file in boundaries:
        files_by_session[file["session"]].append(file)
    features = []
    for index, session in enumerate(sessions):
        start, _ = session_times(session)
        previous = sessions[index - 1] if index else None
        previous_end = session_times(previous)[1] if previous else None
        if previous_end is not None and previous_end > start:
            raise ValueError("前場が当場の開始以前に完了していません。")
        base = {"session": session, "previous_session": previous, "session_starts_at": start.isoformat(), "available_at": previous_end.isoformat() if previous_end else None, "known": False, "reason": None, "month": None, "call_count": 0, "put_count": 0, "iv_median_percent": None, "selected": [], "source_clock": "前場の所属は受信時刻起点。個別payloadの受信時刻とIV計算時刻は不明。"}
        if previous is None:
            base["reason"] = "先物一覧に直前場がない"
            features.append(base)
            continue
        previous_files = files_by_session.get(previous, [])
        if not previous_files:
            base["reason"] = "直前場のオプション保存がない"
            features.append(base)
            continue
        current_month = start.strftime("%Y%m")
        months = sorted({str(file["限月"]) for file in previous_files if str(file["限月"]) > current_month})
        if not months:
            base["reason"] = "直前場に当場年月より後の保存限月がない"
            features.append(base)
            continue
        month = months[0]
        base["month"] = month
        eligible = {"C": [], "P": []}
        for file in previous_files:
            if str(file["限月"]) != month or file["種別"] not in eligible or not file["samples"]:
                continue
            sample = max(file["samples"], key=lambda row: row["offset"])
            fields = sample["fields"]
            iv = fields.get("IV")
            delta = fields.get("Delta")
            if not isinstance(iv, (int, float)) or isinstance(iv, bool) or not math.isfinite(iv) or not 1 <= iv <= 200:
                continue
            if not isinstance(delta, (int, float)) or isinstance(delta, bool) or not math.isfinite(delta):
                continue
            side = file["種別"]
            if (side == "C" and delta <= 0) or (side == "P" and delta >= 0) or not 0.25 <= abs(delta) <= 0.75:
                continue
            eligible[side].append({"path": file["path"], "session": previous, "month": month, "side": side, "strike": file["権利行使価格"], "offset": sample["offset"], "sha256": sample["sha256"], "fraction": sample["fraction"], "distance_from_abs_delta_half": abs(abs(delta) - 0.5), "fields": fields})
        selected_c = sorted(eligible["C"], key=lambda row: (row["distance_from_abs_delta_half"], row["path"], row["offset"]))[:3]
        selected_p = sorted(eligible["P"], key=lambda row: (row["distance_from_abs_delta_half"], row["path"], row["offset"]))[:3]
        base.update({"call_count": len(selected_c), "put_count": len(selected_p), "call_eligible": len(eligible["C"]), "put_eligible": len(eligible["P"]), "selected": selected_c + selected_p})
        if not selected_c or not selected_p:
            base["reason"] = "指定IV・Delta条件でコールまたはプットが欠測"
        else:
            base["known"] = True
            base["reason"] = "直前完了場の保存提供IVを次場で固定利用"
            base["iv_median_percent"] = statistics.median(row["fields"]["IV"] for row in base["selected"])
        features.append(base)
    return features


def artificial_check() -> dict[str, Any]:
    """
    機能: 前場限定、末尾選択、限月、符号、欠測と中央値を人工資料で確認する。
    引数: なし。
    返り値: dict[str, Any] 確認の成否と項目。
    """
    sessions = ["2026-10-15_Day", "2026-10-15_Night", "2026-10-16_Day", "2026-10-16_Night", "2026-10-19_Day"]
    examples = []
    for side, delta, iv in [("C", 0.49, 20.0), ("P", -0.51, 40.0)]:
        examples.append({"path": side, "session": sessions[0], "限月": "202611", "種別": side, "権利行使価格": 65000, "samples": [{"fraction": 0.0, "offset": 0, "sha256": "初回", "fields": {"IV": 190.0, "Delta": delta}}, {"fraction": 0.75, "offset": 50, "sha256": "末尾", "fields": {"IV": iv, "Delta": delta}}]})
    # ----------------------------------------
    # 当場の極端なIV、前場の当月限、符号違いは選択へ混ざらない。
    for session, month, side, delta, iv in [(sessions[1], "202611", "C", 0.5, 199), (sessions[0], "202610", "C", 0.5, 150), (sessions[0], "202611", "C", -0.5, 80)]:
        examples.append({"path": session + month + side, "session": session, "限月": month, "種別": side, "権利行使価格": 65000, "samples": [{"fraction": 1.0, "offset": 100, "sha256": "除外確認", "fields": {"IV": iv, "Delta": delta}}]})
    result = select_features(examples, sessions)
    assert result[0]["known"] is False
    assert result[1]["known"] is True and result[1]["iv_median_percent"] == 30
    assert {row["sha256"] for row in result[1]["selected"]} == {"末尾"}
    assert result[2]["known"] is False and result[2]["reason"] == "指定IV・Delta条件でコールまたはプットが欠測"
    assert result[3]["known"] is False and result[3]["reason"] == "直前場のオプション保存がない"
    assert result[4]["previous_session"] == "2026-10-16_Night"
    assert result[4]["available_at"] == "2026-10-17T06:00:00+09:00"
    return {"passed": True, "確認": ["前場限定", "末尾fraction1なしでも最大offset", "当月限除外", "Delta符号", "中央値", "古い場を飛ばして埋めない", "金曜ナイトから月曜デイ"]}


def main() -> None:
    """
    機能: 所有境界目録と先物ファイル名だけを読み、41場の固定 IV を保存する。
    引数: なし。
    返り値: None。
    """
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError("境界目録が既知の固定版と一致しません。")
    boundaries = json.loads(raw)
    files = sorted((ROOT / "candle_1min/TOPIX").glob("*.csv"))
    session_manifest = [{"path": path.relative_to(ROOT).as_posix(), "session": path.stem, "bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns} for path in files]
    sessions = [row["session"] for row in session_manifest]
    proof = artificial_check()
    features = select_features(boundaries, sessions)
    for row in features:
        if row["known"]:
            assert row["selected"] and all(contract["session"] == row["previous_session"] for contract in row["selected"])
            assert dt.datetime.fromisoformat(row["available_at"]) < dt.datetime.fromisoformat(row["session_starts_at"])
    counts = collections.Counter(row["reason"] for row in features)
    result = {"目的": "前場保存提供 IV の次場固定利用。IVの当場更新や個別時刻の推定はしない。", "source_manifest": SOURCE.relative_to(ROOT).as_posix(), "source_sha256": SOURCE_SHA, "selector_source": pathlib.Path(__file__).relative_to(ROOT).as_posix(), "selector_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(), "原本追加読取": 0, "金融再生": 0, "先物一覧": session_manifest, "sessions": len(features), "known": sum(row["known"] for row in features), "unknown": sum(not row["known"] for row in features), "理由別件数": dict(counts), "人工確認": proof, "選択条件": {"前場": "先物保存セッション一覧の直前一場のみ", "限月": "直前場に存在する当場年月より後の最小の保存月", "IV_percent": [1, 200], "abs_Delta": [0.25, 0.75], "Delta_sign": "C正、P負", "優先順位": "abs(abs(Delta)-0.5)が小さい順、同順位はsource path・offset順", "各side上限": 3, "各side必要最小": 1, "代表IV": "採用全契約のIV中央値", "unknown": "古い前場を探さず不明のまま保持"}, "限界": "個別payloadの受信時刻・提供IVの計算時刻は不明。オプション市場の最新IVや正しい将来変動幅を保証する指標ではない。", "features": features}
    target = OUT / "前完了場IV固定特徴.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": target.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "sessions": result["sessions"], "known": result["known"], "unknown": result["unknown"], "理由別件数": dict(counts), "既知IV": [{"session": row["session"], "previous": row["previous_session"], "month": row["month"], "iv": row["iv_median_percent"], "call_count": row["call_count"], "put_count": row["put_count"]} for row in features if row["known"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
