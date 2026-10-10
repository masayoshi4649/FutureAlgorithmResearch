"""旧期間の順位だけで代表を固定し、追加夜間の価格・板24系統を比較する。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
PREVIOUS = ROOT / "work" / "wave_v2"
sys.path.insert(0, str(PREVIOUS))
import research_v2 as frozen


SESSION = "2026-09-22_Night"
CUTOFF = pd.Timestamp("2026-09-23T00:28:00+09:00")
FREEZE_FILE = OUT / "固定系統比較_代表設定.json"


def sha256(path: Path) -> str:
    """機能: ファイル内容の同一性を検証する識別子を得る。

    引数: path (Path) は対象ファイル。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_representatives() -> list[dict]:
    """機能: 保存済み旧順位で各系統の最上位を選び、新結果を見る前に保存する。

    引数: なし。返り値: 旧順位と固定設定の一覧 (list[dict])。
    既存の固定記録があれば入力ハッシュと設定が同じことを必須とする。
    """
    ranking_path = PREVIOUS / "比較_全条件.csv"
    ranking = pd.read_csv(ranking_path)
    ranking["previous_rank"] = range(1, len(ranking) + 1)
    assert len(ranking) == 864
    representatives = []
    for row in ranking.drop_duplicates("family", keep="first").sort_values("family").itertuples():
        cfg = frozen.Config(int(row.family), float(row.threshold), int(row.confirm),
                            float(row.trail), int(row.exit_multiplier))
        assert cfg.key == row.config
        representatives.append(dict(
            config=asdict(cfg), key=cfg.key, name=frozen.FAMILIES[cfg.family],
            previous_rank=int(row.previous_rank),
            previous_target_pass=int(row.target_pass),
            previous_frequency_ok=bool(row.frequency_ok),
            previous_count=int(row.count),
        ))
    assert {r["config"]["family"] for r in representatives} == set(range(1, 25))
    record = dict(
        source=str(ranking_path.relative_to(ROOT)), source_sha256=sha256(ranking_path),
        code_sha256=sha256(PREVIOUS / "research_v2.py"),
        rule="前回保存された864条件の並び順で、各系統の先頭１条件を採用。今回の成績による変更なし。",
        note="追加夜間は00:28まで前回既知。夜間全体を未使用の検証とは呼ばない。",
        representatives=representatives,
    )
    if FREEZE_FILE.exists():
        assert json.loads(FREEZE_FILE.read_text(encoding="utf-8")) == record
    else:
        frozen.save_json(FREEZE_FILE, record)
    fixed = json.loads((PREVIOUS / "固定設定.json").read_text(encoding="utf-8"))
    assert record["code_sha256"] == fixed["code_sha256"]
    return representatives


def additional_data() -> dict:
    """機能: 保存済み追加夜間の確定足と生板由来の特徴を読み込む。

    引数: なし。返り値: 銘柄とセッションをキーに持つ入力 (dict)。
    """
    data = {}
    for symbol in frozen.SYMBOLS:
        one = frozen.read_candle(ROOT / "candle_1min" / symbol / f"{SESSION}.csv")
        five = frozen.read_candle(ROOT / "candle_5min" / symbol / f"{SESSION}.csv")
        book_path = OUT / f"板特徴_{symbol}_{SESSION}.csv"
        if not book_path.exists():
            raise FileNotFoundError(f"板特徴の完成待ち: {book_path}")
        features = frozen.price_features(one, five, frozen.TICKS[symbol])
        features = frozen.attach_book(features, book_path)
        assert "book_present" in features
        assert features.book_present.sum() > 0
        data[(SESSION, symbol)] = (one, features)
    return data


def summarize(trades: list[dict], symbol: str) -> dict:
    """機能: 同じ銘柄の取引数・確定損益・継続時間を集計する。

    引数: trades (list[dict])、symbol (str)。返り値: 集計値 (dict)。
    """
    selected = [trade for trade in trades if trade["symbol"] == symbol]
    closed = [trade for trade in selected if trade["closed"]]
    duration = pd.Series([trade["duration_min"] for trade in closed], dtype=float)
    return dict(
        count=len(selected), closed=len(closed), wins=sum(trade["net_points"] > 0 for trade in closed),
        net_points=sum(trade["net_points"] for trade in closed),
        stress_points=sum(trade["stress_points"] for trade in closed),
        median_duration_min=float(duration.median()) if len(duration) else None,
        duration_20min_count=int((duration >= 20).sum()),
        duration_60min_count=int((duration >= 60).sum()),
    )


def cohort(trade: dict) -> str:
    """機能: 既知区間・境界保有・追加区間新規を区別する。

    引数: trade (dict)。返り値: 区分名 (str)。
    """
    if trade["entry_time"] >= CUTOFF:
        return "00:28以後に新規"
    if trade["exit_time"] is not None and trade["exit_time"] < CUTOFF:
        return "00:28前に返済"
    return "00:28時点の保有を完結"


def report(rows: list[dict], trade_rows: list[dict], representatives: list[dict]) -> str:
    """機能: 再選択を避けた比較結果を日本語で説明する。

    引数: rows/trade_rows/representatives (list[dict])。返り値: Markdown (str)。
    """
    lines = [
        "# 追加夜間の固定24系統比較", "",
        "対象は保存済みの2026-09-22夜間。前回の864条件ランキングだけから各系統の最上位１条件を機械的に取り出し、24設定を変更せず再生した。追加データで閾値の探索や採用条件の切替はしていない。比較の採用条件は引き続き24系統の `24_0.25_1_4_1`。", "",
        "旧期間は2026-09-21日中・同夜間・2026-09-22日中の３セッション。追加夜間の17:00〜翌00:28は前回の現在セッション保存データで既知であり、夜間全体を未使用検証とは呼ばない。00:28で状態を初期化せず、セッション開始から連続再生した。旧期間の指定４波合格数は代表選択時の成績であり、新夜間には正解波の事前ラベルを追加していない。", "",
        "標準損益は各往復２ティック、ストレス損益は各往復４ティックの控除後。NK225は円幅、TOPIXはポイントで、両銘柄の数値は合算しない。表の勝率は控除後の利益が正の決済取引割合であり、波ラベルへの検知正答率とは区別する。取引数０もそのまま記録する。", "",
        "## 銘柄別の全セッション結果", "",
        "|系統|固定条件|旧４波合格|銘柄|旧３セッション 件数/純損益|追加夜間 件数/勝数|追加純損益|追加４ティック控除|継続中央値 分|", 
        "|---:|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        duration = "―" if row["median_duration_min"] is None else f"{row['median_duration_min']:g}"
        lines.append(f"|{row['family']}|{row['config']}|{row['previous_target_pass']}/4|{row['symbol']}|{row['previous_count']} / {row['previous_net_points']:+g}|{row['count']} / {row['wins']}|{row['net_points']:+g}|{row['stress_points']:+g}|{duration}|")
    # ----------------------------------------
    lines.extend(["", "## 追加部分の扱い", "",
        "取引の明細には `cohort` として「00:28前に返済」「00:28時点の保有を完結」「00:28以後に新規」を付記した。既知足は00:27開始分までなので、00:28始値での執行は追加区間に含む。「00:28時点の保有を完結」はエントリーが既知期間の取引なので、その取引全体の利益を後半だけの新規検知成績として扱わない。", "",
        "## 生板の位置付け", "",
        "11〜17系統は生板由来の信号、18〜20系統は価格と板、または複数の板特徴の併用。板時刻は次の異なる約定時刻ブロックを観測して初めて利用できる方式を維持し、末尾の未確定ブロックは使わない。16系統の約定方向は価格変化からの推定であり、実際の成行売買方向を直接観測した値ではない。", "",
    ])
    board = [row for row in rows if 11 <= row["family"] <= 20]
    for symbol in frozen.SYMBOLS:
        subset = [row for row in board if row["symbol"] == symbol]
        positive = sum(row["net_points"] > 0 for row in subset)
        stress_positive = sum(row["stress_points"] > 0 for row in subset)
        zero = sum(row["count"] == 0 for row in subset)
        lines.append(f"- {symbol}: 生板を使う10代表中、標準控除後プラス{positive}条件、４ティック控除後プラス{stress_positive}条件、無取引{zero}条件。")
    lines.extend(["", "今回の１セッションの結果だけで比較中の系統へ切り替えると追加データへの選び直しになる。勝敗の偏りや生板条件の有効性は、今後保存される複数セッションで同じ設定のまま確認する。", ""])
    return "\n".join(lines)


def main() -> None:
    """機能: 旧順位の代表固定と追加夜間24条件の評価を実行する。

    引数: コマンドライン (list[str])。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description="旧順位のまま追加夜間24系統を比較")
    parser.add_argument("--freeze-only", action="store_true", help="追加データを読まず代表設定だけ保存")
    args = parser.parse_args()
    representatives = fixed_representatives()
    if args.freeze_only:
        print("旧順位から24系統の代表設定を固定しました。追加データは未読です。")
        return

    # ----------------------------------------
    old_cells = pd.read_csv(PREVIOUS / "比較_全セル.csv")
    data = additional_data()
    rows, trade_rows, cohort_rows = [], [], []
    for representative in representatives:
        cfg = frozen.Config(**representative["config"])
        trades, targets, cells = frozen.evaluate(data, cfg)
        assert not targets
        assert all(trade["closed"] for trade in trades)
        for trade in trades:
            one = data[(SESSION, trade["symbol"])][0]
            assert trade["entry_time"] >= one.index[0]
            assert trade["exit_time"] <= one.index[-1]
            assert trade["exit_time"] >= trade["entry_time"]
            trade_rows.append(dict(**trade, family=cfg.family, name=representative["name"], cohort=cohort(trade)))
        for symbol in frozen.SYMBOLS:
            previous = old_cells[(old_cells.config == cfg.key) & (old_cells.symbol == symbol)]
            assert len(previous) == 3
            row = dict(family=cfg.family, name=representative["name"], config=cfg.key,
                       previous_rank=representative["previous_rank"],
                       previous_target_pass=representative["previous_target_pass"],
                       symbol=symbol, session=SESSION,
                       previous_count=int(previous["count"].sum()),
                       previous_net_points=float(previous.net_points.sum()),
                       previous_stress_points=float(previous.stress_points.sum()),
                       **summarize(trades, symbol))
            expected = next(cell for cell in cells if cell["symbol"] == symbol)
            assert row["count"] == expected["count"]
            assert abs(row["net_points"] - expected["net_points"]) < 1e-8
            rows.append(row)
            for label in ("00:28前に返済", "00:28時点の保有を完結", "00:28以後に新規"):
                cohort_rows.append(dict(family=cfg.family, config=cfg.key, symbol=symbol, cohort=label,
                                        **summarize([trade for trade in trades if cohort(trade) == label], symbol)))
    assert len(rows) == 48
    frozen.save_json(OUT / "固定系統比較_集計.json", rows)
    frozen.save_json(OUT / "固定系統比較_取引.json", trade_rows)
    frozen.save_json(OUT / "固定系統比較_区分別.json", cohort_rows)
    for suffix, records in (("集計", rows), ("取引", trade_rows), ("区分別", cohort_rows)):
        pd.DataFrame(records).to_csv(OUT / f"固定系統比較_{suffix}.csv", index=False, encoding="utf-8-sig")
    (OUT / "固定系統比較.md").write_text(report(rows, trade_rows, representatives), encoding="utf-8")
    frozen.save_json(OUT / "固定系統比較_検証記録.json", dict(
        conditions=24, cells=48, trades=len(trade_rows), all_closed=True,
        source_ranking_sha256=sha256(PREVIOUS / "比較_全条件.csv"),
        frozen_code_sha256=sha256(PREVIOUS / "research_v2.py"),
        inputs={str(path.relative_to(ROOT)): sha256(path)
                for symbol in frozen.SYMBOLS
                for path in (ROOT / "candle_1min" / symbol / f"{SESSION}.csv",
                             ROOT / "candle_5min" / symbol / f"{SESSION}.csv",
                             OUT / f"板特徴_{symbol}_{SESSION}.csv")},
    ))
    print(json.dumps(dict(比較条件=24, 銘柄別セル=48, 全取引=len(trade_rows),
                          全件セッション内返済=True), ensure_ascii=False))


if __name__ == "__main__":
    main()
