"""追加保存データを前回固定した検知器で再生する。外部通信は行わない。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = OUT.parent / "wave_v2"
sys.path.insert(0, str(OLD))
import research_v2 as r
from replay import cached_data
from clock_features import price_features_until

SESSION = "2026-09-22_Night"
CUTOFF = pd.Timestamp("2026-09-23T00:28:00+09:00")


def plain(value: object) -> object:
    """機能: 時刻を含む計算結果を保存済み形式へ変換する。

    引数: value (object)。返り値: 比較可能な値 (object)。
    """
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def digest(path: Path) -> str:
    """機能: ファイルの同一性を検証する値を求める。

    引数: path (Path)。返り値: SHA256値 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_data(cutoff: pd.Timestamp | None = None) -> dict:
    """機能: 新しい夜間セッションを始めから指定時点まで読み込む。

    引数: cutoff (Timestamp | None) は確定足の締切。返り値: 再生用データ (dict)。
    """
    frames_by_symbol = {}
    for symbol in r.SYMBOLS:
        frames = {}
        for minutes in (1, 5):
            frame = r.read_candle(ROOT / f"candle_{minutes}min" / symbol / f"{SESSION}.csv")
            if cutoff is not None:
                frame = frame[frame.index + pd.Timedelta(minutes=minutes) <= cutoff]
            frames[minutes] = frame
        frames_by_symbol[symbol] = frames
    end = cutoff.floor("min") - pd.Timedelta(minutes=1) if cutoff is not None else max(frames[1].index[-1] for frames in frames_by_symbol.values())
    data = {}
    for symbol, frames in frames_by_symbol.items():
        data[(SESSION, symbol)] = (frames[1], price_features_until(frames[1], frames[5], r.TICKS[symbol], end))
    return data


def totals(trades: list[dict], label: str) -> list[dict]:
    """機能: 単位を混ぜず、銘柄別に取引数・損益・保有時間を集計する。

    引数: trades (list[dict])、label (str)。返り値: 銘柄別の集計 (list[dict])。
    """
    rows = []
    for symbol in r.SYMBOLS:
        selected = [t for t in trades if t["symbol"] == symbol]
        closed = [t for t in selected if t["closed"]]
        lengths = [t["duration_min"] for t in closed]
        wins = sum(t["net_points"] > 0 for t in closed)
        rows.append(dict(区分=label, 銘柄=symbol, 検知数=len(selected), 返済数=len(closed),
                         利益件数=wins, 利益割合=wins / len(closed) if closed else None,
                         通常損益=sum(t["net_points"] for t in closed),
                         厳格損益=sum(t["stress_points"] for t in closed),
                         保有時間中央値=float(np.median(lengths)) if lengths else None,
                         保有20分以上=sum(n >= 20 for n in lengths), 保有60分以上=sum(n >= 60 for n in lengths),
                         単位="円幅" if symbol == "NK225" else "ポイント"))
    return rows


def cohort(trade: dict, boundary: pd.Timestamp) -> str:
    """機能: 前回までの既決済・継続建玉・境界後の新規を区別する。

    引数: trade (dict)、boundary (Timestamp)。返り値: 区分名 (str)。
    境界時刻以後に始まる足の情報は前半へ含めない。
    """
    if trade["entry_time"] >= boundary:
        return "境界以後の新規"
    if trade["closed"] and trade["exit_time"] < boundary:
        return "境界前に返済済み"
    return "境界時点の継続建玉"


def split_marked_profit(trades: list[dict], data: dict, boundary: pd.Timestamp) -> list[dict]:
    """機能: 境界時点の既知終値から後半の評価差額を集計する。

    引数: trades (list[dict])、data (dict)、boundary (Timestamp)。返り値: 銘柄別明細 (list[dict])。
    継続建玉は追加の新規約定と扱わず、残り１ティックだけを後半へ配賦する。
    """
    rows = []
    for symbol in r.SYMBOLS:
        one = data[(SESSION, symbol)][0]
        known = one[one.index + pd.Timedelta(minutes=1) <= boundary]
        mark = float(known.close.iloc[-1])
        selected = [t for t in trades if t["symbol"] == symbol]
        before, after, carry = 0.0, 0.0, []
        for t in selected:
            category = cohort(t, boundary)
            if category == "境界前に返済済み":
                before += t["net_points"]
            elif category == "境界以後の新規":
                after += t["net_points"]
            else:
                left = t["side"] * (mark - t["entry_price"]) - r.TICKS[symbol]
                right = t["side"] * (t["exit_price"] - mark) - r.TICKS[symbol]
                assert abs(left + right - t["net_points"]) < 1e-8
                before += left
                after += right
                carry.append(dict(新規時刻=t["entry_time"], 返済時刻=t["exit_time"], 前半評価損益=left, 後半評価損益=right))
        full = sum(t["net_points"] for t in selected)
        assert abs(before + after - full) < 1e-8
        rows.append(dict(銘柄=symbol, 境界=boundary, 境界直前の足=known.index[-1], 評価価格=mark,
                         前半評価損益=before, 後半評価損益=after, 全体通常損益=full, 継続建玉=carry))
    return rows


def diagnostics(trades: list[dict], data: dict) -> list[dict]:
    """機能: 各取引の確定終値と返済価格から有利・不利変動を記録する。

    引数: trades (list[dict])、data (dict)。返り値: 日本語取引台帳 (list[dict])。
    返済した足の終了後の価格は集計しない。足内の最大値幅を意味しない。
    """
    rows = []
    for number, trade in enumerate(trades, 1):
        one = data[(trade["session"], trade["symbol"])][0]
        held = one[(one.index >= trade["entry_time"]) & (one.index < trade["exit_time"])]
        moves = np.r_[0.0, trade["side"] * (held.close.to_numpy() - trade["entry_price"]), trade["gross_points"]]
        rows.append(dict(番号=number, 銘柄=trade["symbol"], セッション=trade["session"],
                         方向="ロング" if trade["side"] == 1 else "ショート", 区分=cohort(trade, CUTOFF),
                         新規時刻=trade["entry_time"], 返済時刻=trade["exit_time"], 新規価格=trade["entry_price"],
                         返済価格=trade["exit_price"], 保有分=trade["duration_min"], 通常損益=trade["net_points"],
                         厳格損益=trade["stress_points"], 終値と返済価格による最大順行=float(moves.max()),
                         終値と返済価格による最大逆行=float(-moves.min()), 返済理由=trade["reason"]))
    return rows


def main() -> None:
    """機能: 凍結条件を照合し、新しい保存夜間データの結果と帰属を保存する。

    引数: なし。返り値: なし (None)。元データと前回成果物は変更しない。
    """
    OUT.mkdir(exist_ok=True)
    fixed = json.loads((OLD / "固定設定.json").read_text(encoding="utf-8"))
    assert digest(OLD / "research_v2.py") == fixed["code_sha256"]
    for path, expected in fixed["input_sha256"].items():
        assert digest(ROOT / path) == expected, path
    cfg = r.Config(**fixed["config"])
    old_data = r.load_data()
    old_trades, old_targets, old_cells = r.evaluate(old_data, cfg)
    for name, result in (("取引", old_trades), ("指定波", old_targets), ("集計", old_cells)):
        expected = json.loads((OLD / f"比較_採用{name}.json").read_text(encoding="utf-8"))
        assert plain(result) == expected, name

    # ----------------------------------------
    # 前回取得物と追加ファイルの共通部分を照合し、末尾だけを独立に切り離さず再生する。
    cached = cached_data()
    cached_trades, _, cached_cells = r.evaluate(cached, cfg)
    prefix = new_data(CUTOFF)
    prefix_trades, _, prefix_cells = r.evaluate(prefix, cfg)
    assert plain(cached_trades) == plain(prefix_trades), "前回取得物と今回保存足の取引が一致しません"
    assert plain(cached_cells) == plain(prefix_cells)
    data = new_data()
    trades, _, cells = r.evaluate(data, cfg)
    assert trades and all(t["closed"] for t in trades)
    for old in prefix_trades:
        current = next(t for t in trades if t["symbol"] == old["symbol"] and t["entry_time"] == old["entry_time"])
        if old["closed"]:
            assert plain(old) == plain(current)
        else:
            for field in ("side", "entry_price", "atr", "signal_time"):
                assert old[field] == current[field]

    # ----------------------------------------
    # 同じ取引の結果を開発期間・追加期間・境界時点の建玉へ分け、単位別に保存する。
    groups = totals(old_trades, "前回開発３セッション") + totals(trades, "追加された夜間全体")
    for label in ("境界前に返済済み", "境界時点の継続建玉", "境界以後の新規"):
        groups.extend(totals([t for t in trades if cohort(t, CUTOFF) == label], f"00:28 {label}"))
    groups.extend(totals(old_trades + trades, "全保存４セッション"))
    fixed_time = pd.Timestamp(fixed["fixed_at"])
    mark_rows = split_marked_profit(trades, data, CUTOFF) + split_marked_profit(trades, data, fixed_time)
    ledger = diagnostics(trades, data)
    duration_rows = []
    combined = old_trades + trades
    for period, subset in (("前回開発３セッション", old_trades), ("追加された夜間全体", trades), ("全保存４セッション", combined)):
        for low, high, name in ((0, 20, "20分未満"), (20, 60, "20分以上60分未満"), (60, 120, "60分以上120分未満"), (120, float("inf"), "120分以上")):
            picked = [t for t in subset if low <= t["duration_min"] < high]
            for row in totals(picked, period):
                row["保有時間区分"] = name
                duration_rows.append(row)
    outputs = (("追加_取引", trades), ("追加_セッション集計", cells), ("期間別集計", groups),
               ("境界での評価差額", mark_rows), ("保有時間別集計", duration_rows), ("追加_取引台帳", ledger),
               ("全保存_取引", combined), ("全保存_指定波", old_targets))
    for name, value in outputs:
        r.save_json(OUT / f"{name}.json", value)
    for name, value in (("追加_取引台帳", ledger), ("期間別集計", groups), ("保有時間別集計", duration_rows)):
        pd.DataFrame(value).to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")
    files = [ROOT / f"candle_{minutes}min" / symbol / f"{SESSION}.csv" for symbol in r.SYMBOLS for minutes in (1, 5)]
    manifest = dict(実行時刻=pd.Timestamp.now(tz="Asia/Tokyo"), 固定設定=cfg.key, 前回固定時刻=fixed_time,
                    新しい保存セッション=SESSION, 既知データ締切=CUTOFF, 通信回数=0,
                    旧入力18ファイル同一=True, 凍結コード同一=True, 前回開発結果完全一致=True,
                    旧取得物と今回の共通部分の取引一致=True, 指定４波合格=all(t["passed"] for t in old_targets),
                    追加取引数=len(trades), 追加取引全て返済済み=True,
                    新入力SHA256={str(path.relative_to(ROOT)): digest(path) for path in files},
                    再検証コードSHA256=digest(Path(__file__)),
                    共通観測終端前処理SHA256=digest(OUT / "clock_features.py"),
                    実装補正="特徴量を共通の観測終端まで延長。仮の約定行追加なし。閾値・返済条件の変更なし。")
    r.save_json(OUT / "再検証記録.json", manifest)
    print(json.dumps(dict(追加集計=cells, 取引=ledger, 境界評価=mark_rows), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
