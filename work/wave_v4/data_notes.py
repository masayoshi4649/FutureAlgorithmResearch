"""保存データの構成と指定夜間の逆行幅を診断し、注文検証の前提を記録する。"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from raw_execution import read_observations


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def inventory() -> list[dict]:
    """保存足のセッション範囲と確定状態を確認する。

    引数: なし。
    返り値: list[dict]。元ファイルを変更しないファイル別診断。
    """
    result = []
    for kind in ("candle_1min", "candle_5min"):
        step = 1 if kind == "candle_1min" else 5
        for path in sorted((ROOT / kind).glob("*/*.csv")):
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            stamps = [datetime.fromisoformat(row["time"]) for row in rows]
            result.append({
                "instrument": path.parent.name, "session": path.stem, "minutes": step,
                "source": str(path.relative_to(ROOT)), "rows": len(rows),
                "first": min(stamps).isoformat(), "last": max(stamps).isoformat(),
                "duplicate_time_rows": len(stamps) - len(set(stamps)),
                "not_closed_rows": sum(row["closed"].lower() != "true" for row in rows),
                "incomplete_volume_rows": sum(row["volume_complete"].lower() != "true" for row in rows),
                "missing_minutes_or_bars": int((max(stamps) - min(stamps)).total_seconds() / (60 * step)) + 1 - len(set(stamps)),
                "raw_source_exists": (ROOT / "book" / path.parent.name / (path.stem + ".jsonl")).exists(),
            })
    return result


def maximum_drawdown(points: list[tuple[datetime, float]]) -> dict:
    """指定順序の価格列から先行高値に対する最大の下落幅を診断する。

    引数: points（list[tuple[datetime, float]]）時刻と価格の保存順序列。
    返り値: dict。最大下落幅、高値と安値の時刻および価格。
    """
    peak_time, peak = points[0]
    result = {"points": 0.0, "peak_time": peak_time.isoformat(), "peak": peak,
              "trough_time": peak_time.isoformat(), "trough": peak}
    for stamp, price in points:
        if price > peak:
            peak_time, peak = stamp, price
        if peak - price > result["points"]:
            result = {"points": peak - price, "peak_time": peak_time.isoformat(), "peak": peak,
                      "trough_time": stamp.isoformat(), "trough": price}
    return result


def wave_diagnostic(symbol: str) -> dict:
    """指定された夜間上昇の逆行幅を事後診断し、細い追跡幅の限界を示す。

    引数: symbol（str）NK225またはTOPIX。
    返り値: dict。価格変化、最大逆行、開始直前ＡＴＲ。アルゴ条件には使用しない。
    """
    session = "2026-09-22_Night"
    begin = datetime.fromisoformat("2026-09-23T00:40:00+09:00")
    end = datetime.fromisoformat("2026-09-23T03:21:00+09:00")
    tick = 10.0 if symbol == "NK225" else .5
    one = pd.read_csv(ROOT / "candle_1min" / symbol / (session + ".csv"))
    one["time"] = pd.to_datetime(one["time"])
    part = one[(one["time"] >= begin) & (one["time"] < end)]
    close_points = [(row.time.to_pydatetime(), float(row.close)) for row in part.itertuples()]
    pessimistic_points = [(row.time.to_pydatetime(), float(price)) for row in part.itertuples()
                          for price in (row.open, row.high, row.low, row.close)]
    events = read_observations(OUT / f"生板観測_{symbol}_{session}.csv")
    trade_points = [(event["source_trade_time"], event["last_price"]) for event in events
                    if begin <= event["source_trade_time"] < end and event["last_price"] is not None]
    bid_points = [(event["source_trade_time"], event["bid"]) for event in events
                  if begin <= event["source_trade_time"] < end and event["quote_valid"]]
    five = pd.read_csv(ROOT / "candle_5min" / symbol / (session + ".csv"))
    five["time"] = pd.to_datetime(five["time"])
    true_range = pd.concat([(five.high - five.low), (five.high - five.close.shift()).abs(),
                            (five.low - five.close.shift()).abs()], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / 12, adjust=False, min_periods=3).mean()
    atr_before = float(atr[(five.time + pd.Timedelta(minutes=5)) <= begin].iloc[-1])
    drawdown = maximum_drawdown(trade_points)
    return {
        "instrument": symbol, "session": session, "begin": begin.isoformat(),
        "end_exclusive": end.isoformat(), "diagnostic_only": True,
        "first_open": float(part.iloc[0].open), "last_close": float(part.iloc[-1].close),
        "open_to_close_points": float(part.iloc[-1].close - part.iloc[0].open),
        "bars": len(part), "max_high": float(part.high.max()), "min_low": float(part.low.min()),
        "drawdown_close": maximum_drawdown(close_points),
        "drawdown_ohlc_high_before_low": maximum_drawdown(pessimistic_points),
        "drawdown_raw_last_trade": drawdown, "drawdown_raw_bid": maximum_drawdown(bid_points),
        "atr_before_begin": atr_before, "raw_drawdown_in_atr_before_begin": drawdown["points"] / atr_before,
        "raw_drawdown_ticks": drawdown["points"] / tick,
        "note": "指定区間を最後まで見た事後診断。開始点や追跡幅をこの値へ合わせるための最適化には用いない。",
    }


def write_report(record: dict) -> None:
    """データの限界と注文手法の対応を日本語で保存する。

    引数: record（dict）ファイル監査と波の診断。
    返り値: None。自領域の注文仕様ＭａｒｋｄｏｗｎとＪＳＯＮを生成する。
    """
    (OUT / "データと注文仕様.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 保存データと注文検証の前提", "",
        "この監査は保存ファイルだけを読み、元データ、過去の研究成果物、外部ＡＰＩを変更・取得していない。", "",
        "## データ範囲", "",
        "調査時点の保存対象は 2026-09-21_Day、2026-09-21_Night、2026-09-22_Day、2026-09-22_Night の四セッション、二銘柄。2026-09-23_Day は保存フォルダに存在しない。新規日中は親処理の固定後答え合わせと区別する。", "",
        "保存足には実約定がない分の行が存在しないことがある。特徴量用の価格前方補完はできるが、補完した分の価格を約定価格に使わない。出来高不完全な先頭足を完全な通常足と同じ重みで出来高指標に入れない。日中・夜間の状態を独立して初期化し、セッションをまたぐ約定や強制決済は禁止する。", "",
        "## 利用できる注文手法", "",
        "AGENTS.md の market は返済専用。成行新規を存在するＡＰＩとして扱わない。検知直後の仮想新規は、実装時に stop、limit、trail のどれで条件成立させるかを別途対応させる必要がある。", "",
        "|方式|新規の条件|返済との対応|", "|---|---|---|",
        "|stop|買いは検知後の上方条件、売りは下方条件に到達|新規の実約定数量に対し追跡条件を設定する。ギャップは不利側価格を使う|",
        "|trail|買いは検知後の追跡安値から反発、売りは追跡高値から反落|新規の追跡極値と保有中の返済追跡極値は独立して管理する|",
        "|limit|買いは指定価格以下、売りは指定価格以上の押し目・戻り条件|条件成立時の実約定は保証されない。価格接触だけで確実に約定したとしない|",
        "|ifd / ifd_oco|新規の実約定分に対して返済条件一つまたは二つを置く|仕様記載だけではトレーリング幅の更新方法や部分約定中の注文変更は確定しない|",
        "|oco|同方向の二条件から先に成立したものを発注|取消・照合・残数量切替の遅延はデータから再現できない|",
        "|market|新規には使えない|返済およびセッション終了前の強制返済に利用できる|", "",
        "AGENTS.md は条件の方向を定義するが、判定参照が約定値・気配のどれか、条件成立後の発注価格・スリッページ・待ち行列・部分約定・取消遅延を定義していない。検証モデルの仮定を実際の注文ＡＰＩ仕様と同一視しない。", "",
        "## 一分足の同足順序", "",
        "開始時点の既存ストップを先に判定する。足の高値でトレーリング幅を更新し、その同じ足の安値も到達した場合、高値が先だったかは一分足では不明である。新規トリガーと返済条件の同足接触も同じ問題がある。OHLC の二経路（始値→高値→安値→終値、始値→安値→高値→終値）で分岐を明示し、不利な条件成立を採るか、確定終値だけで次足の追跡水準を更新する方式を明示する。後者は実際の瞬間高安を追うトレーリングとは別の方式となる。", "",
        "stop 新規のギャップは買い max(始値, 指定値)、売り min(始値, 指定値)。逆指値返済も不利側の始値で評価する。買い・売りを同足で都合よく往復させない。トレーリング条件成立後の約定は保証されないため、通常コストと追加スリッページ条件を併記する。", "",
        "## 生板の実行順序監査", "",
        "raw_execution.py は保存順序を保持し、同じ CurrentPriceTime の連続ブロックを次の異なる約定時刻で解放する。受信時刻がないため CurrentPriceTime を板更新時刻として使わない。末尾の未解放ブロックは捨てる。売気配は Sell1、買気配は Buy1。最良数量が正で売値が買値を上回る板だけを有効とする。連続して価格・最良板・累積出来高が全て同じ観測は重複として除く。", "",
        "利用可能時刻と元約定時刻、元行番号、同時刻内の解放順序をＣＳＶへ保存した。read_observations で読み込み、quote_near_time で新規・返済直前に既知だった気配、fixed_trail_observation で指定時刻後の固定追跡幅の条件成立順序を確認できる。最後の関数は条件成立の監査であり、実約定のバックテストではない。", "",
        "この系列は古い板を遅延して観測する近似であり、解放時刻にその板で売買できたと保証しない。板の遅延値は次の約定までの間隔であり通信遅延ではない。現在値の履歴と板の保存順があることで一分足より順序を詳しく確認できるが、受信時刻欠如を解消できない。", "",
        "|銘柄|出力観測数|次約定待ち中央値秒|95％秒|最大秒|無効板|", "|---|---:|---:|---:|---:|---:|",
    ]
    for audit in record["raw_execution_audits"]:
        lines.append(f"|{audit['instrument']}|{audit['observations']}|{audit['delay_median_seconds']}|{audit['delay_p95_seconds']}|{audit['delay_max_seconds']}|{audit['invalid_quotes']}|")
    lines.extend(["", "## 指定夜間上昇の事後診断", "",
                  "対象は 2026-09-23 00:40 以上 03:21 未満（03:20開始足まで）。以下は区間全体を見た診断であり、この幅へストップを合わせる最適化には使用しない。先行高値からの押し戻しがあるため、短い追跡幅は上昇途中で返済される。", "",
                  "|銘柄|始値→最終終値|変化幅|一分終値の最大押し戻し|生の最終約定値の最大押し戻し|気配買値の最大押し戻し|開始直前の五分足ＡＴＲ|", "|---|---|---:|---:|---:|---:|---:|"])
    for wave in record["night_wave"]:
        lines.append(f"|{wave['instrument']}|{wave['first_open']:g}→{wave['last_close']:g}|{wave['open_to_close_points']:g}|{wave['drawdown_close']['points']:g}|{wave['drawdown_raw_last_trade']['points']:g}|{wave['drawdown_raw_bid']['points']:g}|{wave['atr_before_begin']:.2f}|")
    lines.extend(["", "ＮＫ２２５の価格幅は円幅、ＴＯＰＩＸは指数ポイント。ＡＴＲは真の値幅の指数平均（係数1/12）を開始前に確定済みの五分足だけで計算した診断値。", "",
                  "## 再現", "", "`python -X utf8 work/wave_v4/raw_execution.py` で新夜間の観測列を生成し、`python -X utf8 work/wave_v4/data_notes.py` で本資料を再生成する。基本試験は `raw_execution.py --self-test`。", ""])
    (OUT / "データと注文仕様.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """保存ファイルと生板観測の品質、注文仮定、指定波の診断を保存する。

    引数: なし。
    返り値: None。
    """
    record = {
        "api_requested": False, "data_inventory": inventory(),
        "raw_execution_audits": json.loads((OUT / "生板観測監査_2026-09-22_Night.json").read_text(encoding="utf-8")),
        "night_wave": [wave_diagnostic(symbol) for symbol in ("NK225", "TOPIX")],
    }
    write_report(record)
    print(json.dumps(record["night_wave"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
