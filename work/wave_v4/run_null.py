"""開発データだけで、無作為方向と反転価格経路の対照を実行する。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import time

import pandas as pd

from engine import Config, TICKS, prepare, simulate
from null_checks import DIRECTION_SEEDS, PATH_SEEDS, rebuild_five, reflect_paths, summarize_runs
from research import load_data, save_json, schedule_for
from signals import build_features


OUT = Path(__file__).resolve().parent


def cells_only(data: dict, cfg: Config | dict[str, Config]) -> list[dict]:
    """機能: ラベルを使わず、固定条件の銘柄・セッション別損益を測る。

    引数: data (dict) は再生入力、cfg (Config | dict[str, Config]) は共通または銘柄別固定条件。
    返り値: 完結取引だけの損益と取引数 (list[dict])。
    """
    configs = cfg if isinstance(cfg, dict) else {symbol: cfg for symbol in TICKS}
    schedules = {}
    cells = []
    for key, item in data.items():
        candidate = configs[key[1]]
        if candidate.key not in schedules:
            schedules[candidate.key] = schedule_for(data, candidate)
        trades = simulate(item, schedules[candidate.key][key], candidate)
        closed = [trade for trade in trades if trade["closed"]]
        cells.append(dict(session=key[0], symbol=key[1], count=len(trades), closed=len(closed),
                          net_points=sum(trade["net_points"] for trade in closed),
                          stress_points=sum(trade["stress_points"] for trade in closed),
                          net_atr=sum(trade["net_atr"] for trade in closed)))
    return cells


def totals(cells: list[dict]) -> dict[str, float]:
    """機能: 損益を異なる銘柄間で混ぜず合計する。

    引数: cells (list[dict]) はセル集計。
    返り値: 銘柄別損益 (dict[str, float])。
    """
    return {symbol: sum(cell["net_points"] for cell in cells if cell["symbol"] == symbol) for symbol in TICKS}


def prepared_paths(candles: dict) -> dict:
    """機能: 反転１分足から５分足を再構築し、板を使わない特徴へ変換する。

    引数: candles (dict) はセッション・銘柄ごとの１分足。
    返り値: 共通時計で揃えた再生入力 (dict)。
    """
    result = {}
    sessions = sorted({key[0] for key in candles})
    for session in sessions:
        end = max(one.index[-1] for key, one in candles.items() if key[0] == session)
        for symbol in TICKS:
            one = candles[(session, symbol)]
            five = rebuild_five(one)
            z = build_features(one, five, None, TICKS[symbol], end)
            result[(session, symbol)] = prepare(one, z, symbol, session)
    return result


def row_config(row: dict) -> Config:
    """機能: 比較表の行から再現可能な条件を取り出す。

    引数: row (dict) は比較表の行。
    返り値: 固定条件 (Config)。
    """
    return Config(**{field: row[field] for field in Config.__dataclass_fields__ if field in row and not pd.isna(row[field])})


def run(selected_path: Path) -> None:
    """機能: 固定採用条件を読み、再選択せず無作為方向と 100 価格経路を実行する。

    引数: selected_path (Path) は config を持つ保存済み条件ファイル。
    返り値: なし (None)。結果は新規の帰無検証資料へ保存する。
    """
    saved = json.loads(selected_path.read_text(encoding="utf-8"))
    cfg = Config(**saved["config"])
    configs = {symbol: Config(**saved["symbol_configs"][symbol]) for symbol in TICKS} if "symbol_configs" in saved else {symbol: cfg for symbol in TICKS}
    table_path = OUT / "統合全条件比較.csv"
    table = pd.read_csv(table_path if table_path.exists() else OUT / "全条件比較.csv")
    price = table[(table.family <= 14) & ~table.reverse.astype(bool)].iloc[0].to_dict()
    order = table[table.family.between(101, 104)].iloc[0].to_dict()
    path_configs = {
        "価格条件代表": {symbol: candidate if candidate.family <= 14 else row_config(price) for symbol, candidate in configs.items()},
        "注文単独代表": {symbol: row_config(order) for symbol in TICKS},
    }
    data = load_data()
    observed_cells = cells_only(data, configs)
    observed = totals(observed_cells)
    entry_atr_control = {symbol: replace(candidate, trail_basis="entry") for symbol, candidate in configs.items()}
    entry_atr_cells = cells_only(data, entry_atr_control)
    direction_variants = [(entry, None, entry) for entry in ("signal_limit", "stop", "pullback", "trail")]
    direction_variants.append((None, None, "銘柄別の採用新規方法"))
    if any(candidate.trail_basis != "entry" for candidate in configs.values()):
        direction_variants.append((None, "entry", "新規ATR固定・採用新規方法"))
    plan = dict(
        採用ファイル=str(selected_path), 採用条件=asdict(cfg),
        銘柄別採用条件={symbol: asdict(candidate) for symbol, candidate in configs.items()},
        方向種=DIRECTION_SEEDS, 価格経路種=PATH_SEEDS,
        方向比較="採用の返済幅・待機時間を固定し、新規４方式で各100種。現在ATR追跡の採用時は、新規ATR固定の同じ新規方法も100種追加。銘柄・セッションごとの乱数塩を研究本体と共有。",
        方向条件=[dict(entry=entry, trail_basis=basis, group=name) for entry, basis, name in direction_variants],
        価格経路条件={name: {symbol: asdict(candidate) for symbol, candidate in values.items()} for name, values in path_configs.items()},
        選択バイアス="全条件探索後の代表比較であり、探索全体の多重比較を補正した検定ではない。",
        対象="保存４セッションだけ。現在APIにはアクセスしない。",
    )
    save_json(OUT / "帰無検証計画.json", plan)
    direction_samples, direction_summary = [], []
    started = time.monotonic()
    for entry, basis, name in direction_variants:
        values = []
        for seed in DIRECTION_SEEDS:
            candidates = {symbol: replace(original, family=101, param=1.0, entry=entry or original.entry, reverse=False, seed=seed, trail_basis=basis or original.trail_basis) for symbol, original in configs.items()}
            for cell in cells_only(data, candidates):
                row = dict(cell, seed=seed, group=name)
                values.append(row)
                direction_samples.append(row)
        direction_summary.extend(dict(row, group=name) for row in summarize_runs(values, observed))
        print(json.dumps(dict(完了="方向100種", 方式=name, 秒=round(time.monotonic()-started)), ensure_ascii=False), flush=True)
    pd.DataFrame(direction_samples).to_csv(OUT / "無作為方向_全種.csv", index=False, encoding="utf-8-sig")
    save_json(OUT / "無作為方向_集計.json", direction_summary)

    # ----------------------------------------
    candles = {key: item["one"] for key, item in data.items()}
    real_rebuilt = prepared_paths(candles)
    reference = {name: totals(cells_only(real_rebuilt, candidate)) for name, candidate in path_configs.items()}
    native_reference = {name: totals(cells_only(data, candidate)) for name, candidate in path_configs.items()}
    path_samples = []
    for position, seed in enumerate(PATH_SEEDS, 1):
        artificial = prepared_paths(reflect_paths(candles, seed))
        for name, candidate in path_configs.items():
            path_samples.extend(dict(cell, seed=seed, group=name) for cell in cells_only(artificial, candidate))
        if position % 10 == 0:
            print(json.dumps(dict(完了="反転価格経路", 本数=position, 秒=round(time.monotonic()-started)), ensure_ascii=False), flush=True)
    path_summary = []
    for name in path_configs:
        sample = [row for row in path_samples if row["group"] == name]
        path_summary.extend(dict(row, group=name) for row in summarize_runs(sample, reference[name]))
    pd.DataFrame(path_samples).to_csv(OUT / "反転価格経路_全種.csv", index=False, encoding="utf-8-sig")
    save_json(OUT / "反転価格経路_集計.json", path_summary)
    save_json(OUT / "帰無検証結果.json", dict(
        plan=plan, selected_cells=observed_cells, selected_totals=observed,
        entry_atr_control_config={symbol: asdict(candidate) for symbol, candidate in entry_atr_control.items()}, entry_atr_control_cells=entry_atr_cells,
        reconstructed_five_reference=reference, original_five_reference=native_reference,
        direction_summary=direction_summary, path_summary=path_summary,
        elapsed_seconds=time.monotonic()-started,
    ))
    lines = [
        "# 注文単独とコイントス仮説の検証", "",
        f"採用条件を変えず、同じ保存４セッションで方向だけを無作為にする{len(direction_variants)}条件×100種と、１分足の符号を反転した100経路を調べた。現在セッションは使用していない。", "",
        "採用条件のATR参照を新規時に固定し直した対照の損益は、" + "、".join(f"{symbol} {value:+.2f}" for symbol, value in totals(entry_atr_cells).items()) + "。条件を再最適化せず、他の設定は採用条件と揃えた。", "",
        "## 無作為方向", "",
        "新規方法だけを４方式に変える対照と、各銘柄の採用新規方法をそのまま使う対照を用意し、銘柄別採用条件の返済幅・待機時間等を維持する。方向は30分ごとの公平なコイントスである。参考順位の比較対象は銘柄別採用条件の損益。", "",
        "|新規方法|銘柄|平均損益|中央値|5〜95百分位|利益となった種|平均取引数|採用損益以上の種|", "|---|---|---:|---:|---|---:|---:|---:|",
    ]
    for row in direction_summary:
        lines.append(f'|{row["group"]}|{row["symbol"]}|{row["mean"]:.2f}|{row["median"]:.2f}|{row["percentile_05"]:.2f}〜{row["percentile_95"]:.2f}|{row["profitable_seed_fraction"]:.0%}|{row["mean_count"]:.2f}|{row["at_least_observed_count"]}/100|')
    lines.extend(["", "## 価格の持続性を壊した対照", "", "１分足のギャップと高安を含む動きを足単位で1/2の確率で反転し、同時刻の両銘柄には共通の符号を使った。５分足は変換後の１分足から再構築した。実価格の比較対象も同じ再構築を使い、元の５分足との違いを結果JSONに残した。", "", "|条件|銘柄|実価格損益|反転平均|5〜95百分位|利益となった経路|実価格以上の経路|", "|---|---|---:|---:|---|---:|---:|"])
    for row in path_summary:
        lines.append(f'|{row["group"]}|{row["symbol"]}|{row["observed_net_points"]:.2f}|{row["mean"]:.2f}|{row["percentile_05"]:.2f}〜{row["percentile_95"]:.2f}|{row["profitable_seed_fraction"]:.0%}|{row["at_least_observed_count"]}/100|')
    lines.extend(["", "NK225は円幅、TOPIXはポイント。全て往復２ティック控除後である。種間の標準偏差やモンテカルロ標準誤差はJSONへ保存した。これらは同じ市場期間上の乱数変動であり、100の独立した市場期間から求めた信頼区間ではない。", "", "代表条件は全条件探索後に選ばれている。各反転経路で全条件探索を繰り返していないため、採用条件の参考順位を、探索全体についての統計的優位や将来利益の保証へ読み替えてはいけない。板の数量と注文フローを整合する形で反転できないため、価格経路の対照は価格条件と注文単独だけに限った。", ""])
    if len({candidate.entry for candidate in configs.values()}) == 1:
        lines.extend(["『銘柄別の採用新規方法』は両銘柄で同じ新規方法のため、対応行の再掲であり追加の独立実験ではない。", ""])
    if all(candidate.trail_basis == "entry" for candidate in configs.values()):
        lines.extend(["採用はもともと新規ATR固定であり、ATR参照を新規時へ固定する対照は採用そのものと同じである。", ""])
    lines.extend(["反転経路は１分終値の方向の連続性を壊す代理実験である。足内形状やギャップと足内変動の関係は残っており、全ての時点で完全に公平な価格過程を作ったとまでは主張しない。", ""])
    (OUT / "コイントス対照結果.md").write_text("\n".join(lines), encoding="utf-8")
    from bracket_checks import run_brackets
    run_brackets(data, configs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="固定条件の方向・価格経路対照")
    parser.add_argument("selected", type=Path)
    arguments = parser.parse_args()
    run(arguments.selected)
