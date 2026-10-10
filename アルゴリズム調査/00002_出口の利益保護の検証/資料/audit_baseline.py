"""保存版の元方式１２取引について、観測できた最大利益からの減少を独立集計する。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SAVED = ROOT / "アルゴリズム調査" / "保存版"
TICK = {"NK225": 10.0, "TOPIX": 0.5}
MULTIPLIER = {"NK225": 1000.0, "TOPIX": 10000.0}


def read_candles(path: Path) -> pd.DataFrame:
    """機能: 保存版の確定１分足を時刻順に読み込む。

    引数: path (Path) は読取対象の保存済みＣＳＶ。
    返り値: 時刻を索引とする確定足 (DataFrame)。
    """
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame["time"])
    frame = frame[frame["closed"].astype(str).str.lower().eq("true")]
    frame = frame.set_index("time").sort_index()
    assert not frame.index.duplicated().any(), "確定足の時刻が重複しています。"
    return frame


def audit_trade(trade: dict, candles: pd.DataFrame, number: int) -> dict:
    """機能: １取引の含み益の最大値と確定利益との差を計算する。

    引数: trade (dict) は元取引、candles (DataFrame) は同セッション確定足、number (int) は連番。
    返り値: 金額を円に統一した利益返却指標 (dict)。
    """
    symbol, side = trade["symbol"], int(trade["side"])
    entry, exit_time = pd.Timestamp(trade["entry_time"]), pd.Timestamp(trade["exit_time"])
    price, final = float(trade["entry_price"]), float(trade["exit_price"])
    atr, tick, multiplier = float(trade["atr"]), TICK[symbol], MULTIPLIER[symbol]
    assert trade["closed"] and entry <= exit_time
    assert entry in candles.index and exit_time in candles.index
    cost = 2 * tick * multiplier
    observations = [(0.0, entry.isoformat(), entry.isoformat(), "新規約定価格")]
    for moment, row in candles.loc[(candles.index >= entry) & (candles.index < exit_time)].iterrows():
        observations.append((side * (float(row["close"]) - price) * multiplier,
                             (moment + pd.Timedelta(minutes=1)).isoformat(), moment.isoformat(), "確定１分終値"))
    final_gross = side * (final - price) * multiplier
    observations.append((final_gross, exit_time.isoformat(), exit_time.isoformat(), "返済約定価格・足内の秒不明"))
    peak = max(observations, key=lambda value: value[0])
    maximum_gross = peak[0]
    maximum_net, final_net = maximum_gross - cost, final_gross - cost
    giveback = maximum_gross - final_gross
    assert abs(final_net - float(trade["net_points"]) * multiplier) < 1e-7

    # ----------------------------------------
    middle = candles.loc[(candles.index > entry) & (candles.index < exit_time)]
    including_entry = candles.loc[(candles.index >= entry) & (candles.index < exit_time)]
    favourable = "high" if side == 1 else "low"
    middle_values = side * (middle[favourable] - price) * multiplier
    including_entry_values = side * (including_entry[favourable] - price) * multiplier
    bar_core_maximum = max(maximum_gross, float(middle_values.max())) if len(middle) else maximum_gross
    bar_entry_maximum = max(maximum_gross, float(including_entry_values.max())) if len(including_entry) else maximum_gross
    raw_stop = price - side * 2.5 * atr
    stop = (math.floor(raw_stop / tick) if side == 1 else math.ceil(raw_stop / tick)) * tick
    return dict(
        取引番号=number, 銘柄=symbol, セッション=trade["session"], 売買="買い" if side == 1 else "売り",
        新規時刻=entry.isoformat(), 返済時刻=exit_time.isoformat(), 新規価格=price, 返済価格=final,
        基準A価格幅=atr, 基準A金額円=atr * multiplier,
        初期損切価格=stop, 初期損切幅円=abs(price - stop) * multiplier,
        追跡4A価格幅=4 * atr, 追跡4A金額円=4 * atr * multiplier,
        往復費用円=cost, 最大含み益費用前円=maximum_gross, 最大含み益費用後円=maximum_net,
        最終利益費用前円=final_gross, 最終利益費用後円=final_net,
        利益返却円=giveback,
        利益返却率費用前=giveback / maximum_gross if maximum_gross > 0 else None,
        利益返却率費用後=giveback / maximum_net if maximum_net > 0 else None,
        残存率費用後=final_net / maximum_net if maximum_net > 0 else None,
        最大含み益観測時刻=peak[1], 最大含み益足始値時刻=peak[2], 最大含み益観測種類=peak[3],
        足高安参考最大益費用前円=bar_core_maximum,
        新規足高安を含む参考最大益費用前円=bar_entry_maximum,
        返済理由=trade["reason"],
    )


def summarize(rows: list[dict]) -> dict:
    """機能: 取引ごとの最大利益と確定利益を合算する。

    引数: rows (list[dict]) は独立集計済み取引。
    返り値: 各取引最大値の合計であることを明記した集計 (dict)。
    """
    fields = ("最大含み益費用前円", "最大含み益費用後円", "最終利益費用前円", "最終利益費用後円", "利益返却円", "往復費用円")
    result = {field: sum(row[field] for row in rows) for field in fields}
    result["取引数"] = len(rows)
    result["残存率費用後"] = result["最終利益費用後円"] / result["最大含み益費用後円"]
    result["利益返却率費用後"] = result["利益返却円"] / result["最大含み益費用後円"]
    return result


def run() -> None:
    """機能: 保存済み取引を監査し、再計算可能な集計と日本語説明を保存する。

    引数: なし。
    返り値: なし (None)。原本や過去調査は変更せず、通信も行わない。
    """
    source = SAVED / "work" / "wave_v5" / "方向主候補.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    files = {source}
    cache, rows = {}, []
    for number, trade in enumerate(data["trades"], 1):
        key = trade["symbol"], trade["session"]
        if key not in cache:
            path = SAVED / "candle_1min" / key[0] / f"{key[1]}.csv"
            files.add(path)
            cache[key] = read_candles(path)
        rows.append(audit_trade(trade, cache[key], number))
    assert len(rows) == 12
    sums = {symbol: summarize([row for row in rows if row["銘柄"] == symbol]) for symbol in MULTIPLIER}
    sums["両銘柄合計"] = summarize(rows)
    result = dict(
        定義="１分終値による各取引の最大利益と最終利益の差。新規足は終値のみ、返済足は返済価格のみ。費用はラージ１枚往復２ティック。",
        注意="最大利益合計は各取引で異なる時刻の最大値の合計。全て天底で返済できる実現可能利益ではなく、同時の口座最大資産でもない。",
        時刻="足始値時刻と、１分後の確定終値観測時刻を併記。返済時刻は約定した足の始値時刻であり、足内の秒は不明。",
        参考高安="足高安参考は新規足・返済足の両方を除外した高安と確定終値・約定価格の最大値。新規足高安を含む別欄は約定前の高安を含む可能性があり参考限定。どちらも返済足の高安は除外。",
        集計=sums, 取引=rows,
        入力指紋={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)},
    )
    OUT.mkdir(exist_ok=True)
    (OUT / "元方式の利益返却.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    pd.DataFrame(rows).to_csv(OUT / "元方式の利益返却.csv", index=False, encoding="utf-8-sig")
    lines = ["# 元方式の利益返却", "", result["定義"], "", result["注意"], "", result["時刻"], "",
             "|銘柄|取引数|最大利益合計・費用後|最終利益合計・費用後|返却額|残存率|",
             "|---|---:|---:|---:|---:|---:|"]
    for symbol, total in sums.items():
        lines.append(f'|{symbol}|{total["取引数"]}|{total["最大含み益費用後円"] / 10000:.2f}万円|{total["最終利益費用後円"] / 10000:.2f}万円|{total["利益返却円"] / 10000:.2f}万円|{total["残存率費用後"]:.1%}|')
    lines += ["", "|銘柄|セッション|新規|返済|最大利益・費用後|最終利益・費用後|返却|残存率|最大利益の観測時刻|",
              "|---|---|---|---|---:|---:|---:|---:|---|"]
    for row in rows:
        lines.append(f'|{row["銘柄"]}|{row["セッション"]}|{row["新規時刻"][11:16]}|{row["返済時刻"][11:16]}|{row["最大含み益費用後円"] / 10000:.2f}万円|{row["最終利益費用後円"] / 10000:.2f}万円|{row["利益返却円"] / 10000:.2f}万円|{row["残存率費用後"]:.1%}|{row["最大含み益観測時刻"]}|')
    example = next(row for row in rows if row["銘柄"] == "NK225" and row["セッション"] == "2026-09-23_Day")
    lines += ["", "## ９月２３日・日経２２５の具体例", "",
              f'売り新規 {example["新規価格"]:,.0f}円、基準A {example["基準A価格幅"]:.6f}円幅、初期損切り {example["初期損切価格"]:,.0f}円、追跡幅 {example["追跡4A価格幅"]:.6f}円幅。', "",
              f'費用後の最大利益 {example["最大含み益費用後円"] / 10000:.2f}万円から、最終利益 {example["最終利益費用後円"] / 10000:.2f}万円へ低下。返却額 {example["利益返却円"] / 10000:.2f}万円、返却率 {example["利益返却率費用後"]:.1%}。', "", result["参考高安"], "",
              "最大含み益からの減少は、後から見た反転点の情報を使った診断値であり、同額を将来必ず防げるという意味ではない。価格幅と価格は銘柄の元単位、金額欄はすべて円で保存した。現在セッションAＰＩは取得していない。", ""]
    (OUT / "元方式の利益返却.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(dict(集計=sums, 九月二十三日ＮＫ=example), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
