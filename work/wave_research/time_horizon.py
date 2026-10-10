"""指定された保存セッションで固定設定の時間軸と未来評価時間を比較する。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

import research as research


OUT = Path(__file__).resolve().parent
HORIZONS = (5, 10, 20, 30, 60, 120)
COHORTS = ("各時間の有効標本", "全６時間の共通標本")


def choose_configs() -> tuple[list[research.Config], dict[str, list[str]]]:
    """機能: 開発データで既に選ばれた代表設定と共通設定を読み取る。

    引数: なし。
    返り値: tuple は重複のない Config 配列と設定別の比較区分。
    """
    representative_path = OUT / "開発_時間軸代表.csv"
    if not representative_path.exists():
        raise FileNotFoundError("開発_時間軸代表.csv の生成完了後に実行してください。")
    configurations = {}
    roles = defaultdict(list)
    for row in pd.read_csv(representative_path).itertuples():
        fields = dict(family=int(row.family), strength=float(row.strength), confirm=int(row.confirm), trail=float(row.trail), timeframe=int(row.timeframe))
        if "cooldown" in research.Config.__dataclass_fields__:
            fields["cooldown"] = int(getattr(row, "cooldown", 20))
        cfg = research.Config(**fields)
        configurations[cfg.key] = cfg
        roles[cfg.key].append("時間軸ごとの事前選定代表")
    frozen_path = OUT / "凍結設定.json"
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        cfg = research.Config(**frozen["config"])
        configurations[cfg.key] = cfg
        roles[cfg.key].append("凍結共通設定")
        for timeframe in (1, 5, 10):
            variant = replace(cfg, timeframe=timeframe)
            configurations[variant.key] = variant
            roles[variant.key].append("共通設定の時間軸だけ変更")
    return list(configurations.values()), dict(roles)


def uniform_candidates(one: pd.DataFrame, z: pd.DataFrame, cfg: research.Config) -> list[dict]:
    """機能: 未来を参照せず、一様時刻基準の対象となる観測時刻を列挙する。

    引数: one (DataFrame) は実在１分足、z (DataFrame) は過去特徴量、cfg (Config) は設定。
    返り値: list[dict] は時刻、仮想開始価格、共通５分ＡＴＲ。
    """
    ready = z.index + pd.Timedelta(minutes=cfg.timeframe + 1)
    end = research.session_end(one.index) - pd.Timedelta(minutes=30)
    candidates = []
    cursor = -1
    for row in one.itertuples():
        moment = row.Index
        while cursor + 1 < len(ready) and ready[cursor + 1] <= moment:
            cursor += 1
        if cursor < 0 or moment >= end:
            continue
        feature = z.iloc[cursor]
        risk = float(feature.risk_atr)
        fresh = moment - ready[cursor] <= pd.Timedelta(minutes=2)
        if fresh and feature.age >= 16 + cfg.confirm and np.isfinite(feature.atr) and np.isfinite(risk) and risk > 0:
            candidates.append({"entry_time": moment, "entry_price": float(row.open), "atr": risk})
    return candidates


def score_candidates(one: pd.DataFrame, candidates: list[dict], cache: dict, session: str, symbol: str) -> list[dict]:
    """機能: 固定した一様時刻候補に対し、両方向の未来採点を付与する。

    引数: one (DataFrame)、candidates (list[dict])、cache (dict)、session/symbol (str)。
    返り値: list[dict] は未来の成功有無を含む基準候補。候補選定には未来を使わない。
    """
    scored = []
    for candidate in candidates:
        for side in (1, -1):
            key = (session, symbol, candidate["entry_time"], candidate["atr"], side)
            if key not in cache:
                cache[key] = research.label_wave(one, candidate["entry_time"], candidate["entry_price"], side, candidate["atr"])
            scored.append({**candidate, "side": side, **cache[key]})
    return scored


def is_valid(record: dict, horizon: int, cohort: str) -> bool:
    """機能: 指定評価時間と共通標本の観測可能性を判定する。

    引数: record (dict) は採点済みイベント、horizon (int) は評価分数、cohort (str) は標本区分。
    返り値: bool は採点に必要な未来区間が利用可能かどうか。
    """
    horizons = HORIZONS if cohort == "全６時間の共通標本" else (horizon,)
    return all(record.get(f"wave{value}") is not None and not pd.isna(record.get(f"wave{value}")) for value in horizons)


def wilson(successes: int, count: int) -> tuple[float | None, float | None]:
    """機能: 少数標本の不確実性を示す参考の二項区間を計算する。

    引数: successes (int) は正答数、count (int) は有効標本数。
    返り値: tuple[float | None, float | None] は９５％参考区間の下限と上限。
    """
    if count == 0:
        return None, None
    z = 1.959963984540054
    rate = successes / count
    denominator = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    radius = z / denominator * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count))
    return center - radius, center + radius


def compare_cell(records: list[dict], baseline: list[dict], cfg: research.Config, session: str, symbol: str, cohort: str, horizon: int) -> dict:
    """機能: 同じセッション内の検知を方向比率調整済み一様時刻基準と比べる。

    引数: records/baseline (list[dict])、cfg (Config)、session/symbol/cohort (str)、horizon (int)。
    返り値: dict は分母、成功率、基準率、差分などの比較結果。
    """
    valid = [record for record in records if is_valid(record, horizon, cohort)]
    candidate_keys = {(record["entry_time"], record["atr"]) for record in baseline}
    if any((record["entry_time"], record["atr"]) not in candidate_keys for record in records):
        raise ValueError("検知時刻が一様時刻基準の候補に含まれていません。")
    long_count = sum(record["side"] == 1 for record in valid)
    count = len(valid)
    successes = sum(bool(record[f"wave{horizon}"]) for record in valid)
    direction_successes = sum(record[f"forward{horizon}_atr"] > 0 for record in valid)
    rates = {}
    opportunities = {}
    for side in (1, -1):
        available = [record for record in baseline if record["side"] == side and is_valid(record, horizon, cohort)]
        opportunities[side] = len(available)
        rates[side] = (
            np.mean([record[f"wave{horizon}"] for record in available]) if available else None,
            np.mean([record[f"forward{horizon}_atr"] > 0 for record in available]) if available else None,
        )
    baseline_wave = None
    baseline_direction = None
    if count and all(opportunities[side] for side in (1, -1)):
        share = long_count / count
        baseline_wave = float(share * rates[1][0] + (1 - share) * rates[-1][0])
        baseline_direction = float(share * rates[1][1] + (1 - share) * rates[-1][1])
    lower, upper = wilson(successes, count)
    wave_rate = successes / count if count else None
    direction_rate = direction_successes / count if count else None
    return {
        "設定": cfg.key, "時間軸分": cfg.timeframe, "系統": research.NAMES[cfg.family],
        "セッション": session, "銘柄": symbol, "標本区分": cohort, "評価時間分": horizon,
        "検知総数": len(records), "採点可能数": count, "採点不能数": len(records) - count,
        "ロング数": long_count, "ショート数": count - long_count,
        "波の正答数": successes, "波の正答率": wave_rate,
        "方向の正答数": direction_successes, "方向の正答率": direction_rate,
        "基準時刻総数": len(baseline) // 2, "基準採点可能時刻数": opportunities[1],
        "方向比率調整後基準波正答率": baseline_wave,
        "方向比率調整後基準方向正答率": baseline_direction,
        "基準との差_波": wave_rate - baseline_wave if wave_rate is not None and baseline_wave is not None else None,
        "基準との差_方向": direction_rate - baseline_direction if direction_rate is not None and baseline_direction is not None else None,
        "波正答率参考区間下限": lower, "波正答率参考区間上限": upper,
    }


def aggregate(rows: list[dict], roles: dict[str, list[str]]) -> pd.DataFrame:
    """機能: 銘柄・セッション別比較を検知標本数で加重して集約する。

    引数: rows (list[dict]) はセル別比較、roles (dict) は設定の比較区分。
    返り値: DataFrame は両銘柄合計および銘柄ごとの比較。
    """
    groups = defaultdict(list)
    for row in rows:
        for symbol in (row["銘柄"], "両銘柄合計"):
            key = (row["設定"], row["標本区分"], row["評価時間分"], symbol)
            groups[key].append(row)
    summaries = []
    for (config, cohort, horizon, symbol), cells in groups.items():
        count = sum(row["採点可能数"] for row in cells)
        successes = sum(row["波の正答数"] for row in cells)
        directions = sum(row["方向の正答数"] for row in cells)
        base_count = sum(row["採点可能数"] for row in cells if row["方向比率調整後基準波正答率"] is not None)
        base_wave = sum(row["採点可能数"] * row["方向比率調整後基準波正答率"] for row in cells if row["方向比率調整後基準波正答率"] is not None) / base_count if base_count else None
        base_direction = sum(row["採点可能数"] * row["方向比率調整後基準方向正答率"] for row in cells if row["方向比率調整後基準方向正答率"] is not None) / base_count if base_count else None
        lower, upper = wilson(successes, count)
        summaries.append({
            "設定": config, "比較区分": "、".join(roles[config]), "系統": cells[0]["系統"],
            "時間軸分": cells[0]["時間軸分"], "銘柄": symbol, "標本区分": cohort, "評価時間分": horizon,
            "対象セル数": len(cells), "無検知セル数": sum(row["検知総数"] == 0 for row in cells),
            "検知総数": sum(row["検知総数"] for row in cells), "採点可能数": count,
            "採点不能数": sum(row["採点不能数"] for row in cells),
            "ロング数": sum(row["ロング数"] for row in cells), "ショート数": sum(row["ショート数"] for row in cells),
            "波の正答数": successes, "波の正答率": successes / count if count else None,
            "方向の正答数": directions, "方向の正答率": directions / count if count else None,
            "基準時刻総数": sum(row["基準時刻総数"] for row in cells),
            "基準採点可能時刻数": sum(row["基準採点可能時刻数"] for row in cells),
            "方向比率調整後基準波正答率": base_wave, "方向比率調整後基準方向正答率": base_direction,
            "基準との差_波": successes / count - base_wave if count and base_wave is not None else None,
            "基準との差_方向": directions / count - base_direction if count and base_direction is not None else None,
            "波正答率参考区間下限": lower, "波正答率参考区間上限": upper,
        })
    return pd.DataFrame(summaries)


def percent(value: float | None) -> str:
    """機能: 欠測を区別して百分率表示を作る。

    引数: value (float | None) は比率。
    返り値: str は百分率または採点不能の表示。
    """
    return "採点不能" if value is None or pd.isna(value) else f"{value * 100:.1f}％"


def write_method(summary: pd.DataFrame | None = None, stage: str = "開発") -> None:
    """機能: 比較方法と比較できる範囲を日本語で記録する。

    引数: summary (DataFrame | None) は集計済み結果、stage (str) は開発または未使用日。
    返り値: None。
    """
    lines = [
        "# 時間軸・評価時間の比較", "",
        "使用するのは９月２１日日中・夜間の開発データだけ。未使用日は別の明示実行で別表に保存する。現在セッションＡＰＩにはアクセスしない。" if stage == "開発" else "開発段階で固定した設定を９月２２日日中だけで評価した別表。設定の再選択・変更には使わない。現在セッションＡＰＩにはアクセスしない。", "",
        "## 事前に定める方法", "",
        "- １・５・１０分足の開発時選定代表３設定を再生する。凍結共通設定がある場合、その設定と時間軸だけ１・５・１０分へ変えた設定を加える。設定は重複を除く。比較結果を選定へ戻さない。",
        "- 検知後５・１０・２０・３０・６０・１２０分を採点。波の正答は、評価区間の最終終値が開始価格から方向どおり０．５ＡＴＲ以上、区間内の分末終値の６０％以上が方向どおり、最大逆行が１ＡＴＲ以内の３条件を全て満たすこと。単純方向正答は最終終値が方向どおりであること。横ばいは正答に数えない。",
        "- ＡＴＲは全時間軸で過去の確定５分足から求めた共通尺度を使用。評価時間が違ってもＡＴＲ基準は同じ。最大２分の無観測を直前終値で補完し、それを超える欠測やセッション末尾不足は採点不能として分母から除く。",
        "- 比較基準は同じ銘柄・セッション・時間軸で特徴量準備済み、連続確認本数を含む準備期間経過、ＡＴＲ利用可能、新規期限前、信号更新予定時刻から２分以内という条件を満たす実在１分足時刻を列挙する。開始価格はその足の始値。検知の有無や未来収益で候補時刻を選ばない。検知時刻が必ず基準候補に含まれることも確認する。",
        "- 基準の各時刻をロング・ショート両方向で採点し、各セルの採点可能な検知イベントと同じ方向比率を適用する。合計値はセルごとの検知標本数で加重する。基準候補の全時刻平均であり、乱数を引かないため毎回同じ結果になる。",
        "- この基準は波の方向・時刻選択の比較。検知器の保有中制約、再検知抑制、決済、クールダウンは基準へ適用しない。売買成績や同じ約定回数の取引戦略との比較ではない。",
        "- 各時間の有効標本に加え、６評価時間全てで採点可能な共通標本も計算する。共通標本では検知時刻を固定して短時間と長時間を比べられるが、長い無欠測区間に偏る。", "",
        "## 解釈の制約", "",
        "- 代表設定は開発データから選んでいるため、開発比較値は学習内成績であり、将来の正答率の推定として使えない。未使用日比較も日中１回だけの標本。時間軸代表同士では系統や閾値も異なる。時間軸の影響を見る補助として共通設定の時間軸変更を併記する。",
        "- 長時間では０．５ＡＴＲの順行に到達しやすい一方、１ＡＴＲの最大逆行条件に抵触しやすい。成功条件の時間依存性があるため、長時間の波正答率が高いだけで予測しやすいとは断定できない。方向正答率と方向比率を合わせた一様時刻基準との差も確認する。",
        "- 短い評価時間は短時間の値動きの比較であり、急騰・急落だけを別に定義して抽出した比較ではない。",
        "- 開発データは日中１回・夜間１回だけで、両指数も独立ではない。波の重なり、同一日の相場環境、候補の多数比較がある。表示する９５％二項区間は少数標本を可視化する参考値で、独立性や選択バイアスを補正した信頼区間ではない。",
        "- 夜間の欠測により長い評価時間ほど分母が減る。正答率は正答数／採点可能数と併記し、採点不能を成功にも失敗にも数えない。", "",
        "- 時間軸代表の選定条件は全銘柄・セッションの検知件数を必ず満たすとは限らない。検知ゼロのセルも詳細表へ残し、合計成績が特定セッションだけに偏っていないか確認する。", "",
    ]
    if summary is not None:
        lines.extend(["## 時間軸代表の両銘柄合計", "", "| 足の分数 | 未来分数 | 正答数／分母 | 波正答率 | 一様時刻の波正答率 | 方向正答率 | 一様時刻の方向正答率 |", "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
        selected = summary[(summary["銘柄"] == "両銘柄合計") & (summary["標本区分"] == "各時間の有効標本") & summary["比較区分"].str.contains("事前選定代表")]
        for _, row in selected.sort_values(["時間軸分", "評価時間分"]).iterrows():
            lines.append(f"| {row['時間軸分']} | {row['評価時間分']} | {row['波の正答数']}/{row['採点可能数']} | {percent(row['波の正答率'])} | {percent(row['方向比率調整後基準波正答率'])} | {percent(row['方向の正答率'])} | {percent(row['方向比率調整後基準方向正答率'])} |")
        lines.extend(["", "## 検知ゼロを含むセルの確認", "", "| 設定 | 無検知セル数／対象セル数 |", "| --- | ---: |"])
        for _, row in summary[(summary["銘柄"] == "両銘柄合計") & (summary["標本区分"] == "各時間の有効標本") & (summary["評価時間分"] == 30)].iterrows():
            lines.append(f"| {row['設定']} | {row['無検知セル数']}/{row['対象セル数']} |")
        lines.extend(["", f"全６時間共通標本、銘柄別、共通設定の時間軸変更は `時間比較_{stage}_集計.csv`、セッション別は `時間比較_{stage}_詳細.csv` を参照。", ""])
    command = "python work/wave_research/time_horizon.py" + (" --stage 未使用日" if stage == "未使用日" else "")
    lines.extend([f"再現: `{command}`。", ""])
    name = "時間比較_方法.md" if stage == "開発" else "時間比較_未使用日_方法.md"
    (OUT / name).write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """機能: 開発または事前固定設定の未使用日比較を実行して保存する。

    引数: なし。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description="固定した検知設定の時間軸・評価時間を比較する。")
    parser.add_argument("--stage", choices=("開発", "未使用日"), default="開発", help="評価対象。既定では開発セッションだけを使用する。")
    stage = parser.parse_args().stage
    write_method(stage=stage)
    if tuple(research.TRAIN) != ("2026-09-21_Day", "2026-09-21_Night"):
        raise ValueError("許可した開発セッションと一致しません。")
    if tuple(research.HOLDOUT) != ("2026-09-22_Day",):
        raise ValueError("許可した未使用セッションと一致しません。")
    sessions = research.TRAIN if stage == "開発" else research.HOLDOUT
    configs, roles = choose_configs()
    datasets = {timeframe: research.load_sessions(sessions, timeframe) for timeframe in sorted({cfg.timeframe for cfg in configs})}
    label_cache = {}
    baseline_cache = {}
    comparison_rows = []
    event_rows = []
    for cfg in configs:
        print(f"時間比較中: {cfg.key}", flush=True)
        data = datasets[cfg.timeframe]
        records, _ = research.evaluate(data, cfg)
        event_rows.extend(records)
        for (session, symbol), (one, z) in data.items():
            key = (cfg.timeframe, cfg.confirm, session, symbol)
            if key not in baseline_cache:
                candidates = uniform_candidates(one, z, cfg)
                baseline_cache[key] = score_candidates(one, candidates, label_cache, session, symbol)
            cell_records = [record for record in records if record["session"] == session and record["symbol"] == symbol]
            for cohort in COHORTS:
                for horizon in HORIZONS:
                    comparison_rows.append(compare_cell(cell_records, baseline_cache[key], cfg, session, symbol, cohort, horizon))
    detailed = pd.DataFrame(comparison_rows)
    summary = aggregate(comparison_rows, roles)
    detailed.to_csv(OUT / f"時間比較_{stage}_詳細.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT / f"時間比較_{stage}_集計.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(event_rows).to_csv(OUT / f"時間比較_{stage}_イベント.csv", index=False, encoding="utf-8-sig")
    result = {"対象セッション": sessions, "設定": [{**asdict(cfg), "区分": roles[cfg.key]} for cfg in configs], "集計": json.loads(summary.to_json(orient="records", force_ascii=False))}
    (OUT / f"時間比較_{stage}_結果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_method(summary, stage)
    print("時間比較完了", flush=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
