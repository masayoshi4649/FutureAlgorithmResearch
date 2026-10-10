"""両建ての全セルから、指定された収支基準で代表と期間外成績を整理する。"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
SESSIONS = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night", "2026-09-23_Day")


def rank(cells: pd.DataFrame, sessions: tuple[str, ...]) -> pd.DataFrame:
    """機能: 指定期間だけの費用後収支・頻度・実現損失で注文条件を順位付けする。

    引数: cells (DataFrame) は全セル、sessions (tuple[str, ...]) は選定に使う期間。
    返り値: 両銘柄費用後正・組数制約の適格フラグを持つ順位表 (DataFrame)。
    """
    rows = []
    for key, group in cells[cells.session.isin(sessions)].groupby("config"):
        symbols = group.groupby("symbol").agg(stress=("stress_points", "sum"), mean_atr=("stress_atr", "mean"), mean_cycles=("cycle_count", "mean"))
        eligible = bool(symbols.stress.gt(0).all() and symbols.mean_cycles.ge(1).all() and group.cycle_count.max() <= 12)
        score = float(symbols.mean_atr.min() + .25 * symbols.mean_atr.mean() + .25 * group.stress_atr.min() - .25 * group.realized_dd_atr.mean())
        rows.append(dict(config=key, eligible=eligible, score=score, max_cycle_count=float(group.cycle_count.max()),
                         NK225_stress=float(symbols.loc["NK225", "stress"]), TOPIX_stress=float(symbols.loc["TOPIX", "stress"])))
    return pd.DataFrame(rows).sort_values(["eligible", "score", "config"], ascending=[False, False, True])


def run() -> None:
    """機能: 両建て・100種平均コイントスの代表と時間順・一期間除外比較を保存する。

    引数: なし。返り値: なし (None)。全探索後の解析で、乱数種を選び直さない。
    """
    frames = {"両建て": pd.read_csv(OUT / "両建て_セル.csv"), "コイントス平均": pd.read_csv(OUT / "コイントス_セッション平均.csv")}
    selected, held_out = {}, []
    folds = [("時間順３→４", SESSIONS[:3], (SESSIONS[3],)), ("時間順４→５", SESSIONS[:4], (SESSIONS[4],))]
    folds += [(f"一期間除外_{session}", tuple(value for value in SESSIONS if value != session), (session,)) for session in SESSIONS]
    for name, frame in frames.items():
        ranking = rank(frame, SESSIONS)
        ranking.to_csv(OUT / f"{name}_収支順位.csv", index=False, encoding="utf-8-sig")
        best = ranking.iloc[0].to_dict()
        selected[name] = best
        frame[frame.config.eq(best["config"])].to_csv(OUT / f"{name}_代表セッション表.csv", index=False, encoding="utf-8-sig")
        for fold, training, testing in folds:
            chosen = rank(frame, training).iloc[0].to_dict()
            for row in frame[frame.config.eq(chosen["config"]) & frame.session.isin(testing)].to_dict("records"):
                held_out.append(dict(method=name, fold=fold, training_sessions="/".join(training), training_eligible=chosen["eligible"], training_score=chosen["score"], **row))
    pd.DataFrame(held_out).to_csv(OUT / "両建てコイントス_期間外比較.csv", index=False, encoding="utf-8-sig")
    found = set()
    with gzip.open(OUT / "両建てとコイントス_全取引.pkl.gz", "rb") as stream:
        while len(found) < len(frames):
            try:
                record = pickle.load(stream)
            except EOFError:
                break
            cfg = record["cells"][0]["config"]
            for name in frames:
                expected_seed = None if name == "両建て" else 260925000
                if name not in found and cfg == selected[name]["config"] and record["seed"] == expected_seed:
                    pd.DataFrame(record["trades"]).to_csv(OUT / f"{name}_代表取引.csv", index=False, encoding="utf-8-sig")
                    found.add(name)
    (OUT / "両建て_代表と期間外.json").write_text(json.dumps(dict(
        selected=selected, held_out=[{key: None if isinstance(value, float) and not np.isfinite(value) else value for key, value in row.items()} for row in held_out],
        note="選定は組数で頻度判定し、指定波を使用しない。コイントスは100種平均で条件を選び、取引表示だけ事前固定種260925000を用いる。期間外比較でtraining_eligible=falseなら適格候補なしの参考結果。全５期間代表は保存内の探索結果で未使用検証ではない。",
    ), ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    print(json.dumps(selected, ensure_ascii=False), flush=True)


def write_summary() -> None:
    """機能: 保存済みの代表と期間外比較を、セッションごとの利益・損失・収支で表示する。

    引数: なし。返り値: なし (None)。探索・選定・価格再生は繰り返さない。
    """
    meta = json.loads((OUT / "両建て_代表と期間外.json").read_text(encoding="utf-8"))
    lines = ["# 両建て代表のセッション別収支", "",
             "全５セッションを使った収支順位の代表は、開始45分後以降に買売１枚ずつ、小さい損切り1.5ATR、片脚だけ残った後の追跡4ATR、両脚返済後15分待機となった。これは保存内で選んだ代表である。合計利益が出ても毎セッション利益になるわけではなく、以下に損失を含めて全件を示す。", "",
             "|セッション|銘柄|組数|脚数|利益合計|損失合計|差引収支|４ティック／脚控除後|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    hedge = pd.read_csv(OUT / "両建て_代表セッション表.csv")
    for row in hedge.to_dict("records"):
        lines.append(f'|{row["session"]}|{row["symbol"]}|{row["cycle_count"]}|{row["count"]}|{row["profit_points"]:.2f}|{row["loss_points"]:.2f}|{row["net_points"]:+.2f}|{row["stress_points"]:+.2f}|')
    lines.extend(["", "利益・損失は各脚の往復２ティック控除後で分けており、差引収支＝利益合計−損失合計。NK225は円幅、TOPIXはポイントである。", "", "## 未使用セッションを選定から外した比較", "", "各１セッションを除外して残り４セッションだけで条件を選ぶ比較では、両建ての合計はNK225 ＋540円幅（４ティックでは＋60）、TOPIX ＋4.5ポイント（同−13.5）だった。保存全体の代表の成績をそのまま次の相場へ期待できる結果ではない。", "", "|時間順検証|銘柄|選定期間に適格条件あり|検証セッション|差引収支|４ティック／脚控除後|", "|---|---|---|---|---:|---:|"])
    held = pd.read_csv(OUT / "両建てコイントス_期間外比較.csv")
    for row in held[held.method.eq("両建て") & held.fold.str.startswith("時間順")].to_dict("records"):
        lines.append(f'|{row["fold"]}|{row["symbol"]}|{row["training_eligible"]}|{row["session"]}|{row["net_points"]:+.2f}|{row["stress_points"]:+.2f}|')
    lines.extend(["", "適格条件がなかった３→４の数値は、収支順位の最高点を便宜的に再生した参考結果であり、採用可能な条件が選べたとは扱わない。", "", "## コイントスの100種平均", "", "片側コイントスは100種平均の４ティック控除後収支が両銘柄で正となる適格条件がなかった。以下は最高点の参考条件で、利益が出た乱数種を選んだ結果ではない。開始45分、小損切り1.5ATR、追跡4ATR、返済後60分待機。", "", "|セッション|銘柄|平均取引数|平均利益|平均損失|平均差引収支（１枚）|２枚換算収支|", "|---|---|---:|---:|---:|---:|---:|"])
    coin = pd.read_csv(OUT / "コイントス平均_代表セッション表.csv")
    for row in coin.to_dict("records"):
        lines.append(f'|{row["session"]}|{row["symbol"]}|{row["count"]:.2f}|{row["profit_points"]:.3f}|{row["loss_points"]:.3f}|{row["net_points"]:+.3f}|{row["equivalent_two_contract_net_points"]:+.3f}|')
    lines.extend(["", "２枚換算は総絶対枚数だけを揃える。回転数、価格感応度、必要証拠金、片脚約定の危険まで等しくなるわけではない。代表取引CSVは事前固定種260925000を表示するため、100種平均の収支とは一致しない。", "", "`ambiguous` フィールドは同じ足でSL・TP両方の水準に触れた件数である。始値で先着が既知のケースも含むため、純粋な順序不明件数とは読み替えない。実際の損益計算は既存脚の始値SL・始値TPを足内の後続接触より優先している。", ""])
    (OUT / "両建て_代表比較.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run()
    write_summary()
