"""既存の比較条件を変更せず、銘柄ごとの三波と頻度で再順位付けする。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import hashlib
import io
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from engine import Config
from research import FAMILIES, ORDER_FAMILIES, evaluate, load_data, save_json, schedule_for


OUT = Path(__file__).resolve().parent
SYMBOLS = ("NK225", "TOPIX")


def config_from_row(row: dict) -> Config:
    """機能: 既存比較表の設定を、欠損した旧既定値だけ補って再構成する。

    引数: row (dict) は既存比較表の行。
    返り値: 改変しない比較条件 (Config)。
    """
    values = {}
    for field in fields(Config):
        value = row.get(field.name)
        if value is None or pd.isna(value):
            value = field.default
        if field.name in ("family", "cooldown", "confirm", "seed"):
            value = int(value)
        if field.name == "reverse":
            value = value if isinstance(value, bool) else str(value).lower() == "true"
        values[field.name] = value
    return Config(**values)


def symbol_summary(cfg: Config, trades: list[dict], targets: list[dict], cells: list[dict], symbol: str) -> dict:
    """機能: 指定された銘柄の三波・四セッションを独立に採点する。

    引数: cfg (Config)、trades/targets/cells (list[dict])、symbol (str)。
    返り値: 銘柄別の比較行 (dict)。
    """
    target = [item for item in targets if item["symbol"] == symbol]
    cell = [item for item in cells if item["symbol"] == symbol]
    counts = [item["count"] for item in cell]
    result = dict(symbol=symbol, config=cfg.key, name=FAMILIES.get(cfg.family, ORDER_FAMILIES.get(cfg.family)),
                  **asdict(cfg), target_pass=sum(item["passed"] for item in target),
                  coverage_pass=sum(item["coverage_pass"] for item in target), target_count=len(target),
                  frequency_ok=all(1 <= count <= 6 for count in counts), min_count=min(counts), max_count=max(counts),
                  zero_cells=sum(count == 0 for count in counts), count=sum(counts),
                  net_points=sum(item["net_points"] for item in cell),
                  stress_points=sum(item["stress_points"] for item in cell),
                  net_atr=sum(item["net_atr"] for item in cell), wins=sum(item["wins"] for item in cell),
                  ambiguous=sum(item["ambiguous"] for item in cell),
                  max_opposite=max(item["opposite_coverage"] for item in target),
                  min_coverage=min(item["correct_coverage"] for item in target),
                  min_capture=min(item["capture_ratio"] for item in target))
    result["stress_positive"] = result["stress_points"] > 0
    result["score"] = min(result["min_capture"], 1) + result["min_coverage"] - result["max_opposite"] + 0.01 * np.clip(result["net_atr"], -100, 100)
    return result


def run(source_name: str = "統合全条件比較.csv", append: bool = False) -> None:
    """機能: 凍結した既存条件母集団を、銘柄別設定の候補として再評価する。

    引数: source_name (str) は比較表名、append (bool) は既存検査済み条件を再利用する指定。
    返り値: なし (None)。
    元データ・共通比較表・検知条件は変更せず、外部データにも接続しない。
    """
    source = OUT / source_name
    raw = source.read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    source_frame = pd.read_csv(io.BytesIO(raw))
    configs = list({cfg.key: cfg for cfg in map(config_from_row, source_frame.to_dict("records"))}.values())
    previous_rows, previous_record = [], None
    if append:
        previous_record = json.loads((OUT / "銘柄別探索.json").read_text(encoding="utf-8"))
        previous_rows = pd.read_csv(OUT / "銘柄別探索.csv").to_dict("records")
        tested = {row["config"] for row in previous_rows}
        configs = [cfg for cfg in configs if cfg.key not in tested]
    frozen = dict(開始=pd.Timestamp.now(tz="Asia/Tokyo"), 元比較表=str(source), 元比較表SHA256=source_sha,
                  元行数=len(source_frame), 重複除外条件数=len(configs),
                  選択順="銘柄別三波の新規検知合格数、全四セル１〜６回、４ティック費用後正、逆方向保有率最小、系統中央値込み得点",
                  対象="保存済み４セッションのみ。9月23日デイは未参照。",
                  条件母体=[asdict(cfg) for cfg in configs],
                  コードSHA256={name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                              for name in ("engine.py", "signals.py", "targets.py", "research.py", "symbol_search.py")})
    if previous_record is not None:
        frozen["追加前記録"] = previous_record
        frozen["再利用既存条件数"] = len({row["config"] for row in previous_rows})
    save_json(OUT / "銘柄別探索.json", frozen)
    data = load_data()
    cache, rows = {}, previous_rows
    start = time.monotonic()
    for number, cfg in enumerate(configs, 1):
        cache_key = cfg.family, cfg.param, cfg.seed
        if cache_key not in cache:
            cache[cache_key] = schedule_for(data, cfg)
        trades, targets, cells = evaluate(data, cfg, cache[cache_key])
        for symbol in SYMBOLS:
            rows.append(symbol_summary(cfg, trades, targets, cells, symbol))
        if number % 1000 == 0:
            print(json.dumps(dict(完了=number, 全体=len(configs), 経過秒=round(time.monotonic()-start),
                                  最多合格={symbol: max(item["target_pass"] for item in rows if item["symbol"] == symbol) for symbol in SYMBOLS}),
                             ensure_ascii=False), flush=True)
    table = pd.DataFrame(rows)
    table["family_median_score"] = table.groupby(["symbol", "family", "reverse"]).score.transform("median")
    table["robust_score"] = 0.9 * table.score + 0.1 * table.family_median_score
    table = table.sort_values(["symbol", "target_pass", "frequency_ok", "stress_positive", "max_opposite", "robust_score", "config"],
                              ascending=[True, False, False, False, True, False, True])
    table.to_csv(OUT / "銘柄別探索.csv", index=False, encoding="utf-8-sig")
    selected = {}
    for symbol in SYMBOLS:
        subset = table[table.symbol == symbol]
        best = subset.iloc[0].to_dict()
        cfg = config_from_row(best)
        if (cfg.family, cfg.param, cfg.seed) not in cache:
            cache[(cfg.family, cfg.param, cfg.seed)] = schedule_for(data, cfg)
        trades, targets, cells = evaluate(data, cfg, cache[(cfg.family, cfg.param, cfg.seed)])
        selected[symbol] = dict(設定=asdict(cfg), 集計=best, 上位十件=subset.head(10).to_dict("records"),
                                三波合格数=int(subset.target_pass.eq(3).sum()),
                                三波頻度費用同時合格数=int((subset.target_pass.eq(3) & subset.frequency_ok & subset.stress_positive).sum()),
                                取引=[item for item in trades if item["symbol"] == symbol],
                                指定波=[item for item in targets if item["symbol"] == symbol],
                                セッション=[item for item in cells if item["symbol"] == symbol])
    frozen.update(終了=pd.Timestamp.now(tz="Asia/Tokyo"), 経過秒=round(time.monotonic()-start),
                  元比較表変更なし=hashlib.sha256(source.read_bytes()).hexdigest() == source_sha, 銘柄別候補=selected)
    save_json(OUT / "銘柄別探索.json", frozen)
    for symbol, item in selected.items():
        print(json.dumps(dict(銘柄=symbol, 設定=item["設定"], 集計=item["集計"],
                              三波頻度費用同時合格数=item["三波頻度費用同時合格数"]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="保存済み比較条件の銘柄別検証")
    parser.add_argument("--source", default="統合全条件比較.csv")
    parser.add_argument("--append", action="store_true")
    arguments = parser.parse_args()
    run(arguments.source, arguments.append)
