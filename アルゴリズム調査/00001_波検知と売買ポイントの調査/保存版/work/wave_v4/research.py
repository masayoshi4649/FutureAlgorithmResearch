"""保存済み四セッションで信号と注文方法を比較する。現在データには接続しない。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from engine import Config, TICKS, prepare, sign_schedule, simulate
from signals import FAMILIES, PARAMETERS, build_features, get_signals
from targets import target_metrics

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SESSIONS = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night")
SYMBOLS = ("NK225", "TOPIX")
ORDER_FAMILIES = {101: "注文のみ・30分固定コイントス", 102: "注文のみ・60分交互方向", 103: "注文のみ・上下逆指値",
                  104: "注文のみ・上下反発追跡", 105: "基準・ロング固定", 106: "基準・ショート固定"}


def save_json(path: Path, value: object) -> None:
    """機能: 再現可能な日本語JSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def read_candle(path: Path) -> pd.DataFrame:
    """機能: 重複のない確定足を読み込む。

    引数: path (Path)。返り値: 時刻索引の足 (DataFrame)。
    """
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame.time)
    frame = frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
    if frame.index.duplicated().any():
        raise ValueError("重複した足があります")
    return frame


def load_data(sessions: tuple[str, ...] = SESSIONS, cutoff: pd.Timestamp | None = None) -> dict:
    """機能: 開発用保存データを共通観測時刻まで読み込む。

    引数: sessions (tuple[str,...])、cutoff (Timestamp | None)。返り値: 再生入力 (dict)。
    """
    result = {}
    for session in sessions:
        frames = {}
        for symbol in SYMBOLS:
            one = read_candle(ROOT / "candle_1min" / symbol / f"{session}.csv")
            five = read_candle(ROOT / "candle_5min" / symbol / f"{session}.csv")
            if cutoff is not None:
                one = one[one.index + pd.Timedelta(minutes=1) <= cutoff]
                five = five[five.index + pd.Timedelta(minutes=5) <= cutoff]
            frames[symbol] = one, five
        end = cutoff.floor("min") - pd.Timedelta(minutes=1) if cutoff is not None else max(one.index[-1] for one, five in frames.values())
        for symbol, (one, five) in frames.items():
            book_dir = OUT.parent / ("wave_v3_check" if session == "2026-09-22_Night" else "wave_v2")
            path = book_dir / f"板特徴_{symbol}_{session}.csv"
            z = build_features(one, five, path, TICKS[symbol], end)
            result[(session, symbol)] = prepare(one, z, symbol, session)
    return result


def schedule_for(data: dict, cfg: Config) -> dict:
    """機能: 価格・板または固定種コイントスの因果的方向を作る。

    引数: data (dict)、cfg (Config)。返り値: セッション・銘柄ごとの方向と継続回数 (dict)。
    """
    result = {}
    for key, item in data.items():
        session, symbol = key
        z = item["z"]
        if cfg.family < 100:
            peer = data[(session, "TOPIX" if symbol == "NK225" else "NK225")]["z"]
            values = get_signals(z, peer, cfg.family, cfg.param).to_numpy()
        else:
            age = z.age.to_numpy(int)
            if cfg.family == 101:
                salt = int(hashlib.sha256(f"{session}/{symbol}".encode()).hexdigest()[:8], 16)
                rng = np.random.default_rng(cfg.seed + salt)
                choices = rng.choice([-1, 1], size=int(age.max() // 30 + 1))
                values = choices[age // 30]
            elif cfg.family == 102:
                values = np.where((age // 60) % 2 == 0, 1, -1)
            else:
                values = np.full(len(age), -1 if cfg.family == 106 else 1)
            values = np.where(z.atr.notna() & z.stale_minutes.le(10) & z.age.ge(14), values, 0)
        result[key] = sign_schedule(values)
    return result


def evaluate(data: dict, cfg: Config, schedules: dict | None = None) -> tuple[list, list, list]:
    """機能: 条件を全入力に適用し、指定波と銘柄別損益を分ける。

    引数: data (dict)、cfg (Config)、schedules (dict | None)。返り値: 取引・指定波・セル (tuple)。
    """
    schedules = schedule_for(data, cfg) if schedules is None else schedules
    trades, targets, cells = [], [], []
    for key, item in data.items():
        result = simulate(item, schedules[key], cfg)
        trades.extend(result)
        targets.extend(target_metrics(item["one"], result, key[1], key[0]))
        closed = [trade for trade in result if trade["closed"]]
        pnl = [trade["net_points"] for trade in closed]
        equity = np.r_[0, np.cumsum(pnl)]
        cells.append(dict(session=key[0], symbol=key[1], count=len(result), closed=len(closed),
                          net_points=sum(pnl), stress_points=sum(trade["stress_points"] for trade in closed),
                          net_atr=sum(trade["net_atr"] for trade in closed),
                          wins=sum(value > 0 for value in pnl), win_rate=sum(value > 0 for value in pnl)/len(pnl) if pnl else None,
                          max_drawdown_points=float((np.maximum.accumulate(equity)-equity).max()),
                          median_duration=float(np.median([t["duration_min"] for t in closed])) if closed else None,
                          ambiguous=sum(t["ambiguous_entry"] for t in result)))
    return trades, targets, cells


def evaluate_by_symbol(data: dict, configs: dict[str, dict]) -> tuple[list, list, list]:
    """機能: 事前固定した銘柄別条件を使い、それぞれの成績だけを結合する。

    引数: data (dict)、configs (dict[str,dict])。返り値: 取引・指定波・セル (tuple)。
    他指数を参照する特徴には両指数を渡すが、異なる条件の取引を二重計上しない。
    """
    trades, targets, cells = [], [], []
    for symbol, values in configs.items():
        result = evaluate(data, Config(**values))
        trades.extend(t for t in result[0] if t["symbol"] == symbol)
        targets.extend(t for t in result[1] if t["symbol"] == symbol)
        cells.extend(t for t in result[2] if t["symbol"] == symbol)
    return trades, targets, cells


def configuration_grid() -> list[Config]:
    """機能: 結果を見る前に固定した価格・板・注文単独の比較条件を列挙する。

    引数: なし。返り値: 条件一覧 (list[Config])。
    """
    configs = []
    for family, param, entry, trail, cooldown, rearm in itertools.product(range(1, 25), PARAMETERS,
            ("signal_limit", "stop", "pullback", "trail"), (1.5, 2.5, 4.0, 6.0), (5, 20), ("cooldown", "opposite")):
        configs.append(Config(family, param, entry, 0.5, trail, cooldown, rearm))
    # ----------------------------------------
    # 同じ指標を逆方向へ使う逆張り仮説と、方向予測を使わない注文だけの基準。
    for family, entry, trail, cooldown in itertools.product((1, 3, 8, 11, 20, 21), ("signal_limit", "pullback", "trail"), (1.5, 2.5, 4.0), (5, 20)):
        configs.append(Config(family, 1.0, entry, 0.5, trail, cooldown, "cooldown", reverse=True))
    for family in ORDER_FAMILIES:
        entries = ("straddle_stop",) if family == 103 else ("straddle_trail",) if family == 104 else ("signal_limit", "stop", "pullback", "trail")
        for entry, offset, trail, cooldown in itertools.product(entries, (0.25, 0.5, 1.0), (1.5, 2.5, 4.0, 6.0), (5, 20, 40)):
            if entry == "signal_limit" and offset != 0.5:
                continue
            configs.append(Config(family, 1.0, entry, offset, trail, cooldown))
    return configs


def summary(cfg: Config, trades: list, targets: list, cells: list) -> dict:
    """機能: 六つの指定波・検知頻度・費用感応度を選択表にまとめる。

    引数: cfg (Config)、trades/targets/cells (list)。返り値: 比較行 (dict)。
    """
    counts = [cell["count"] for cell in cells]
    row = dict(config=cfg.key, name=FAMILIES.get(cfg.family, ORDER_FAMILIES.get(cfg.family)), **asdict(cfg),
               target_pass=sum(t["passed"] for t in targets), frequency_ok=all(1 <= count <= 6 for count in counts),
               min_count=min(counts), max_count=max(counts), zero_cells=sum(count == 0 for count in counts),
               count=len(trades), max_opposite=max(t["opposite_coverage"] for t in targets),
               min_coverage=min(t["correct_coverage"] for t in targets), min_capture=min(t["capture_ratio"] for t in targets),
               total_net_atr=sum(cell["net_atr"] for cell in cells), ambiguous=sum(cell["ambiguous"] for cell in cells))
    for symbol in SYMBOLS:
        subset = [cell for cell in cells if cell["symbol"] == symbol]
        row[f"{symbol}_net"] = sum(cell["net_points"] for cell in subset)
        row[f"{symbol}_stress"] = sum(cell["stress_points"] for cell in subset)
        row[f"{symbol}_wins"] = sum(cell["wins"] for cell in subset)
        row[f"{symbol}_count"] = sum(cell["count"] for cell in subset)
    row["both_stress_positive"] = row["NK225_stress"] > 0 and row["TOPIX_stress"] > 0
    row["score"] = min(row["min_capture"], 1) + row["min_coverage"] - row["max_opposite"] + .01 * np.clip(row["total_net_atr"], -100, 100)
    return row


def ranked(rows: list[dict]) -> pd.DataFrame:
    """機能: 指定波・頻度・両銘柄費用後損益を順に比較する。

    引数: rows (list[dict])。返り値: 順位表 (DataFrame)。
    """
    table = pd.DataFrame(rows)
    table["family_median_score"] = table.groupby(["family", "reverse"]).score.transform("median")
    table["robust_score"] = .9*table.score + .1*table.family_median_score
    return table.sort_values(["target_pass", "frequency_ok", "both_stress_positive", "max_opposite", "robust_score", "config"], ascending=[False, False, False, True, False, True])


def search() -> None:
    """機能: 事前列挙条件を全保存セッションで比較し、探索結果だけを保存する。

    引数: なし。返り値: なし (None)。採用凍結と現在データ評価は別手順にする。
    """
    data = load_data()
    configs = configuration_grid()
    save_json(OUT / "探索計画.json", dict(開始=pd.Timestamp.now(tz="Asia/Tokyo"), 条件数=len(configs),
               対象=SESSIONS, 未取得答え合わせ="2026-09-23_Day", 条件=[asdict(c) for c in configs],
               選択順="六波合格数、全セル1〜6回、両銘柄の4ティック控除後正、逆方向保有最少、近傍代表得点"))
    rows, cache = [], {}
    started = time.monotonic()
    for i, cfg in enumerate(configs, 1):
        cache_key = cfg.family, cfg.param, cfg.seed
        if cache_key not in cache:
            cache[cache_key] = schedule_for(data, cfg)
        trades, targets, cells = evaluate(data, cfg, cache[cache_key])
        rows.append(summary(cfg, trades, targets, cells))
        if i % 250 == 0:
            pd.DataFrame(rows).to_csv(OUT / "探索途中.csv", index=False, encoding="utf-8-sig")
            print(json.dumps(dict(完了=i, 全条件=len(configs), 秒=round(time.monotonic()-started), 最多合格=max(x["target_pass"] for x in rows)), ensure_ascii=False), flush=True)
    table = ranked(rows)
    table.to_csv(OUT / "全条件比較.csv", index=False, encoding="utf-8-sig")
    table.groupby(["family", "reverse"], sort=False).head(1).to_csv(OUT / "系統代表比較.csv", index=False, encoding="utf-8-sig")
    for position, row in enumerate(table.head(12).to_dict("records"), 1):
        cfg = Config(**{field: row[field] for field in Config.__dataclass_fields__})
        trades, targets, cells = evaluate(data, cfg, cache[(cfg.family, cfg.param, cfg.seed)])
        save_json(OUT / f"候補{position:02d}.json", dict(config=asdict(cfg), summary=row, trades=trades, targets=targets, cells=cells))
    print(table.head(8).to_json(orient="records", force_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="保存データだけによる注文方法の探索")
    parser.add_argument("mode", choices=("search",))
    args = parser.parse_args()
    search()
