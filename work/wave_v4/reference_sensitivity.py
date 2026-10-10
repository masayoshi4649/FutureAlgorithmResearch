"""事前固定の参考候補について、保存データだけで近傍感度を確認する。"""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import pandas as pd

from diagnostics import stress_evaluate
from engine import Config
from research import evaluate_by_symbol, load_data, save_json
from targets import target_metrics


OUT = Path(__file__).resolve().parent
KEYS = (
    "009_0.75_stop_0.5_2.5_60_cooldown_1_0_271828_entry_45",
    "018_1.25_trail_0.5_4_30_cooldown_1_0_271828_current_45",
)
VARIANTS = (
    ("基準", None, 1.0, 0),
    ("追加１分遅延", None, 1.0, 1),
    ("追加２分遅延", None, 1.0, 2),
    ("信号閾値90%", "param", 0.9, 0),
    ("信号閾値110%", "param", 1.1, 0),
    ("新規幅80%", "offset", 0.8, 0),
    ("新規幅120%", "offset", 1.2, 0),
    ("追跡幅80%", "trail", 0.8, 0),
    ("追跡幅120%", "trail", 1.2, 0),
)


def summarize(data: dict, cfg: Config, trades: list, name: str, original: str) -> tuple[list, list]:
    """機能: 取引件数・費用別の勝率と指定波判定を銘柄ごとに集計する。

    引数: data (dict) は保存再生入力、cfg (Config) は診断条件、trades (list) は取引、
        name/original (str) は感度名と変更前候補識別子。
    返り値: 集計行と費用別指定波一覧 (tuple[list, list])。
    """
    rows, targets = [], []
    for symbol in ("NK225", "TOPIX"):
        closed = [trade for trade in trades if trade["symbol"] == symbol and trade["closed"]]
        if len(closed) != len([trade for trade in trades if trade["symbol"] == symbol]):
            raise AssertionError("保存済み完全セッションに未返済があります。")
        row = dict(候補=original, 系統=cfg.family, 感度=name, 銘柄=symbol, 条件=cfg.key, 件数=len(closed))
        counts = [sum(trade["session"] == key[0] for trade in closed) for key in data if key[1] == symbol]
        row.update(最少セッション件数=min(counts), 最多セッション件数=max(counts), 頻度基準=all(1 <= value <= 6 for value in counts))
        for cost, points in ((2, "net_points"), (4, "stress_points")):
            labels = []
            for key, item in data.items():
                if key[1] == symbol:
                    labels.extend(target_metrics(item["one"], trades, symbol, key[0], round_trip_ticks=cost))
            row[f"{cost}tick利益件数"] = sum(trade[points] > 0 for trade in closed)
            row[f"{cost}tick勝率"] = row[f"{cost}tick利益件数"] / len(closed) if closed else None
            row[f"{cost}tick純損益"] = sum(trade[points] for trade in closed)
            row[f"{cost}tick新規検知合格"] = sum(label["passed"] for label in labels)
            row[f"{cost}tick時間値幅合格"] = sum(label["coverage_pass"] for label in labels)
            for label in labels:
                targets.append(dict(候補=original, 系統=cfg.family, 感度=name, 往復控除tick=cost, **label))
        rows.append(row)
    return rows, targets


def run() -> None:
    """機能: 固定済み参考２候補の近傍全条件を、選び直さず保存データで診断する。

    引数: なし。
    返り値: なし (None)。現在データには接続せず、独立した感度資料を保存する。
    """
    fixed = json.loads((OUT / "固定設定.json").read_text(encoding="utf-8"))
    for name, expected in fixed["code_sha256"].items():
        if hashlib.sha256((OUT / name).read_bytes()).hexdigest() != expected:
            raise AssertionError("凍結コードが一致しません。" + name)
    candidates = {Config(**value["config"]).key: Config(**value["config"]) for value in fixed["candidates"]}
    if not all(key in candidates for key in KEYS):
        raise AssertionError("対象候補が事前固定された一覧にありません。")
    data = load_data()
    rows, labels = [], []
    for key in KEYS:
        original = candidates[key]
        for name, field, factor, delay in VARIANTS:
            cfg = replace(original, **{field: getattr(original, field) * factor}) if field else original
            configs = {symbol: asdict(cfg) for symbol in ("NK225", "TOPIX")}
            if delay:
                trades, unused = stress_evaluate(data, configs, delay=delay)
            else:
                trades, unused, cells = evaluate_by_symbol(data, configs)
            values, targets = summarize(data, cfg, trades, name, key)
            rows.extend(values)
            labels.extend(targets)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "参考候補_保存感度.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(labels).to_csv(OUT / "参考候補_保存感度_指定波.csv", index=False, encoding="utf-8-sig")
    save_json(OUT / "参考候補_保存感度.json", dict(
        candidates={key: asdict(candidates[key]) for key in KEYS}, variants=VARIANTS,
        sessions=sorted({key[0] for key in data}), rows=rows, targets=labels,
        note="現在データを確認した後の追加診断だが、使用データは保存４セッションだけ。良い感度条件へ選び直さず全結果を記録。現在データへの再適用も行わない。",
    ))
    lines = [
        "# 参考候補の保存データ感度", "",
        "現在データの答え合わせ前に固定されていた２候補を、保存４セッションだけで追加診断した。現在データの結果を見た後の追加診断であることを区別し、設定を選び直したり、変更条件を現在データへ再適用したりしていない。", "",
        "各変更は一つずつ加え、その他を固定した。指標閾値は±10%、新規幅と追跡幅は±20%、追加遅延は１分・２分。２ティックと４ティックの往復控除で利益件数・損益・指定波合格数を計算した。１銘柄の指定波は３件である。", "",
        "|系統|感度|銘柄|件数|利益件数 2/4tick|損益 2tick|損益 4tick|新規検知合格 2/4tick|時間・値幅合格 2/4tick|", "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(f'|{row["系統"]}|{row["感度"]}|{row["銘柄"]}|{row["件数"]}|{row["2tick利益件数"]}/{row["4tick利益件数"]}|{row["2tick純損益"]:+.2f}|{row["4tick純損益"]:+.2f}|{row["2tick新規検知合格"]}/{row["4tick新規検知合格"]}|{row["2tick時間値幅合格"]}/{row["4tick時間値幅合格"]}|')
    lines.extend(["", "NK225は円幅、TOPIXはポイント。新規検知合格は時間・値幅基準に加え、波開始30分前から60分後までの新規を必要とする。時間・値幅合格は開始より前からの建玉も区間内捕捉として含む。", "", "## 基準設定が不合格となった境界", ""])
    for label in labels:
        if label["感度"] == "基準" and label["往復控除tick"] == 2 and not label["passed"]:
            entry = label["first_correct_entry_time"]
            shift = (entry - label["begin"]).total_seconds() / 60 if entry is not None else None
            lines.append(f'- 系統{label["系統"]} {label["symbol"]} {label["session"]}: 最初の20分以上重なる同方向新規 {entry}（波開始との差 {shift} 分）、時間捕捉 {label["correct_coverage"]:.3%}、値幅捕捉 {label["capture_ratio"]:.3%}、時間・値幅合格 {label["coverage_pass"]}。')
    lines.extend(["", "合格境界の数分・数パーセントの違いを見えるように記載した。境界に近いことを理由に採点基準を緩めたり、合格へ変更したりはしていない。小さな条件変更で合格数や損益が動く場合、特定設定への依存がある。保存期間は４セッションのみで、近傍の良い結果を新たな独立検証とは扱わない。", ""])
    (OUT / "参考候補_保存感度.md").write_text("\n".join(lines), encoding="utf-8")
    print(frame[["系統", "感度", "銘柄", "件数", "2tick純損益", "4tick純損益", "2tick新規検知合格"]].to_json(orient="records", force_ascii=False), flush=True)


if __name__ == "__main__":
    run()
