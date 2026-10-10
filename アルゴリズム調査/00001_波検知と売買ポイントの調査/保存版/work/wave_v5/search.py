"""全波捕捉を要求せず、入口・細かい波・出口とセッション収支を比較する。"""

from __future__ import annotations

from dataclasses import asdict
import itertools
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
V4 = OUT.parent / "wave_v4"
sys.path.insert(0, str(V4))
from research import schedule_for, save_json
from signals import FAMILIES

sys.path.insert(0, str(OUT))
from data import load_data_v5
from exits import ConfigV5, simulate_exit


def configurations() -> list[ConfigV5]:
    """機能: 波ラベルを使わず比較する条件を重複なしで事前列挙する。

    引数: なし。返り値: 固定条件一覧 (list[ConfigV5])。
    """
    result = []
    for family, p, entry, trail, warmup, cooldown, basis in itertools.product(
            range(1, 25), (.75, 1., 1.25), ("signal_limit", "stop", "pullback", "trail"),
            (1.5, 2.5, 4.), (15, 45), (15, 45), ("entry", "current")):
        result.append(ConfigV5(family, p, entry, .5, trail, cooldown, trail_basis=basis, warmup=warmup))
    # ----------------------------------------
    # 入口幅だけを変える対照。検知即時の価格許容指値は幅の影響を受けないので重複させない。
    for family, p, entry, trail, warmup, cooldown, basis, offset in itertools.product(
            (1, 3, 9, 14, 18, 23), (.75, 1., 1.25), ("stop", "pullback", "trail"),
            (1.5, 2.5, 4.), (15, 45), (15, 45), ("entry", "current"), (.25, 1.)):
        result.append(ConfigV5(family, p, entry, offset, trail, cooldown, trail_basis=basis, warmup=warmup))
    # ----------------------------------------
    # 初期損切りを小さくして固定利確または追跡返済へつなぐIFD相当の対照。
    for family, entry, stop, width, warmup, mode in itertools.product(
            range(1, 25), ("signal_limit", "stop", "pullback", "trail"), (.5, 1., 1.5),
            (2., 3., 4.), (15, 45), ("fixed_bracket", "small_stop_trail")):
        result.append(ConfigV5(family, 1., entry, .5, width, 30, trail_basis="entry", warmup=warmup,
                               exit_mode=mode, stop_loss=stop, take_profit=width))
    # ----------------------------------------
    # 以前の候補を比較の基準として保持する。新しい保存データで事後の成績を表示する。
    previous = json.loads((V4 / "固定設定.json").read_text(encoding="utf-8"))
    result.extend(ConfigV5(**item["config"]) for item in previous["candidates"])
    return list({cfg.key: cfg for cfg in result}.values())


def cell_metrics(trades: list[dict], session: str, symbol: str) -> dict:
    """機能: 利益・損失・費用・微小往復を別々に集計する。

    引数: trades (list[dict])、session/symbol (str)。返り値: セッション銘柄別指標 (dict)。
    """
    closed = [t for t in trades if t["closed"]]
    net = np.array([t["net_points"] for t in closed], dtype=float)
    gross = np.array([t["gross_points"] for t in closed], dtype=float)
    stress = np.array([t["stress_points"] for t in closed], dtype=float)
    atr = np.array([t["atr"] for t in closed], dtype=float)
    duration = np.array([t["duration_min"] for t in closed], dtype=float)
    equity = np.r_[0., np.cumsum(net)]
    eq_atr = np.r_[0., np.cumsum(net / atr)]
    tick = 10. if symbol == "NK225" else .5
    return dict(session=session, symbol=symbol, count=len(trades), closed=len(closed),
                profit=float(net[net > 0].sum()), loss=float(-net[net < 0].sum()), net=float(net.sum()),
                gross_profit=float(gross[gross > 0].sum()), gross_loss=float(-gross[gross < 0].sum()),
                cost=float(2 * tick * len(closed)), stress=float(stress.sum()),
                net_atr=float((net / atr).sum()), stress_atr=float((stress / atr).sum()),
                wins=int((net > 0).sum()), losses=int((net < 0).sum()),
                dd=float((np.maximum.accumulate(equity) - equity).max()),
                dd_atr=float((np.maximum.accumulate(eq_atr) - eq_atr).max()),
                median_minutes=float(np.median(duration)) if len(duration) else None,
                micro5_count=int((duration <= 5).sum()), micro15_count=int((duration <= 15).sum()),
                micro15_net=float(net[duration <= 15].sum()),
                ambiguous=sum(bool(t.get("ambiguous_entry", False) or t.get("ambiguous_exit", False)) for t in trades))


def evaluate(data: dict, cfg: ConfigV5, schedules: dict | None = None) -> tuple[list, list]:
    """機能: 同一条件を全セッションへ適用し、取引とセルを返す。

    引数: data (dict)、cfg (ConfigV5)、schedules (dict | None)。返り値: 取引とセル (tuple[list,list])。
    """
    schedules = schedule_for(data, cfg) if schedules is None else schedules
    trades, cells = [], []
    for key, item in data.items():
        ts = simulate_exit(item, schedules[key], cfg)
        trades.extend(ts)
        cells.append(cell_metrics(ts, *key))
    return trades, cells


def ranking_metrics(cells: list[dict]) -> dict:
    """機能: 指定波を使わず、費用後の収支と低調なセッションで順位を定める。

    引数: cells (list[dict])。返り値: 順位と説明指標 (dict)。
    """
    counts = [c["count"] for c in cells]
    sessions = len(cells) // 2
    totals = {symbol: {field: sum(c[field] for c in cells if c["symbol"] == symbol)
                       for field in ("count", "wins", "profit", "loss", "net", "stress", "net_atr", "stress_atr")}
              for symbol in ("NK225", "TOPIX")}
    stress_means = [values["stress_atr"] / sessions for values in totals.values()]
    eligible = all(v["count"] >= sessions and v["stress"] > 0 for v in totals.values()) and max(counts) <= 12
    score = (min(stress_means) + .25 * np.mean(stress_means) + .25 * min(c["stress_atr"] for c in cells)
             - .25 * np.mean([c["dd_atr"] for c in cells]))
    row = dict(eligible=eligible, score=float(score), count=sum(counts), min_count=min(counts), max_count=max(counts),
               zero_cells=sum(c == 0 for c in counts), positive_cells=sum(c["net"] > 0 for c in cells),
               micro15_count=sum(c["micro15_count"] for c in cells),
               micro15_rate=sum(c["micro15_count"] for c in cells) / sum(counts) if sum(counts) else 0.)
    for symbol, values in totals.items():
        row.update({f"{symbol}_{field}": value for field, value in values.items()})
    return row


def run() -> None:
    """機能: 計画を保存して全比較を行い、時系列・一セッション除外選択を再現可能にする。

    引数: なし。返り値: なし (None)。現在APIは使用しない。
    """
    data = load_data_v5()
    configs = configurations()
    sessions = sorted({key[0] for key in data})
    save_json(OUT / "方向探索計画.json", dict(開始=pd.Timestamp.now(tz="Asia/Tokyo"), 条件数=len(configs),
        対象=sessions, 波ラベルを選択に使用=False, コスト往復ティック=[2, 4],
        選択制約="両銘柄の４ティック控除後合計が正、各銘柄平均１回以上、各セル12回以下を優先。指定波の捕捉は順位に使わない。",
        得点="低い側の銘柄のセッション平均４ティック後ATR損益＋0.25×全銘柄平均＋0.25×最低セル損益−0.25×平均決済済ATRドローダウン",
        条件=[asdict(c) for c in configs]))
    rows, all_cells, cache = [], [], {}
    began = time.monotonic()
    for i, cfg in enumerate(configs, 1):
        cache_key = (cfg.family, cfg.param, cfg.seed)
        if cache_key not in cache:
            cache[cache_key] = schedule_for(data, cfg)
        trades, cells = evaluate(data, cfg, cache[cache_key])
        assert all(t["closed"] for t in trades)
        assert all(abs(c["profit"] - c["loss"] - c["net"]) < 1e-8 for c in cells)
        rows.append(dict(config=cfg.key, name=FAMILIES.get(cfg.family, "注文のみ"), **asdict(cfg), **ranking_metrics(cells)))
        all_cells.extend(dict(config=cfg.key, **cell) for cell in cells)
        if i % 1000 == 0:
            print(json.dumps(dict(完了=i, 条件数=len(configs), 経過秒=round(time.monotonic() - began)), ensure_ascii=False), flush=True)
    table = pd.DataFrame(rows).sort_values(["eligible", "score", "config"], ascending=[False, False, True])
    table.to_csv(OUT / "方向全条件比較.csv", index=False, encoding="utf-8-sig")
    cell_table = pd.DataFrame(all_cells)
    cell_table.to_csv(OUT / "方向全条件セッション.csv", index=False, encoding="utf-8-sig")
    by_key = {cfg.key: cfg for cfg in configs}
    candidates = table.groupby(["family", "reverse"], sort=False).head(1).config.to_list()
    candidates.extend(table.groupby("exit_mode", sort=False).head(1).config.to_list())
    candidates.extend(table.head(12).config.to_list())

    # ----------------------------------------
    # 各検証セッションは条件の順位計算から外す。今回すべて既知の保存データであることは変わらない。
    grouped = {key: part.to_dict("records") for key, part in cell_table.groupby("config", sort=False)}
    folds = []
    specifications = [("時系列", sessions[:i], [sessions[i]]) for i in (3, 4)]
    specifications.extend(("一セッション除外", [s for s in sessions if s != held], [held]) for held in sessions)
    for method, train, test in specifications:
        scores = [dict(config=key, **ranking_metrics([c for c in cs if c["session"] in train])) for key, cs in grouped.items()]
        chosen = sorted(scores, key=lambda x: (not x["eligible"], -x["score"], x["config"]))[0]
        cs = [c for c in grouped[chosen["config"]] if c["session"] in test]
        folds.append(dict(method=method, train=train, test=test, chosen=chosen, cells=cs, test_metrics=ranking_metrics(cs)))
        candidates.append(chosen["config"])
    save_json(OUT / "方向分割検証.json", folds)
    unique = list(dict.fromkeys(candidates))
    for key in unique:
        trades, cells = evaluate(data, by_key[key], cache[(by_key[key].family, by_key[key].param, by_key[key].seed)])
        save_json(OUT / f"方向候補_{key}.json", dict(config=asdict(by_key[key]), name=FAMILIES.get(by_key[key].family, "注文のみ"),
                                                  summary=ranking_metrics(cells), trades=trades, cells=cells))
    save_json(OUT / "方向主候補.json", json.loads((OUT / f"方向候補_{table.iloc[0].config}.json").read_text(encoding="utf-8")))
    print(table.head(6)[["name", "entry", "exit_mode", "eligible", "score", "NK225_net", "TOPIX_net", "count"]].to_json(orient="records", force_ascii=False), flush=True)


if __name__ == "__main__":
    run()
