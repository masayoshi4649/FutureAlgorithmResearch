"""方法①の入口を固定し、利益の返却と出口条件を比較する。"""

from __future__ import annotations

from dataclasses import asdict
import itertools
import json
import time

import numpy as np
import pandas as pd

from shared import OUT, SESSIONS, SYMBOLS, MULTIPLIERS, TICKS, load_inputs, normalize, save_json


def configurations() -> list[dict]:
    """機能: 結果を読む前に10系統の改善出口と基準を固定する。

    引数: なし。
    返り値: 出口設定の一覧 (list[dict])。
    """
    rules = [dict(kind="baseline")]
    rules += [dict(kind="fixed_trail", width=w) for w in (.75, 1, 1.5, 2, 2.5, 3, 4)]
    rules += [dict(kind="current_atr", width=w) for w in (1.5, 2, 2.5, 3, 4)]
    rules += [dict(kind="breakeven", trigger=t) for t in (.75, 1, 1.5, 2, 3)]
    rules += [dict(kind="stepped", trigger=t, width=w) for t, w in itertools.product((1, 1.5, 2, 2.5, 3), (.5, .75, 1, 1.5, 2, 2.5))]
    rules += [dict(kind="profit_lock", trigger=t, retain=r) for t, r in itertools.product((1, 1.5, 2, 2.5, 3), (.4, .5, .6, .7, .8))]
    rules += [dict(kind="progressive", trigger=t, width=w) for t, w in itertools.product((.75, 1, 1.5, 2), (.5, .75, 1, 1.5))]
    rules += [dict(kind="structure", trigger=t, window=n, width=w) for t, n, w in itertools.product((1, 1.5, 2, 3), (3, 5, 10, 15, 20), (0, .25, .5))]
    rules += [dict(kind="stagnation", trigger=t, window=n) for t, n in itertools.product((.75, 1, 1.5, 2), (5, 10, 15, 20, 30))]
    rules += [dict(kind="reversal", trigger=t, window=n) for t, n in itertools.product((0, 1, 1.5, 2), (1, 3, 5, 10))]
    rules += [dict(kind="target", width=w) for w in (1, 1.5, 2, 2.5, 3, 4, 5)]
    return rules


def freeze_plan() -> dict:
    """機能: 比較条件と選び方を探索開始前に保存する。

    引数: なし。
    返り値: 固定した計画 (dict)。既存と違う計画を黙って上書きしない。
    """
    plan = dict(対象セッション=list(SESSIONS), 固定入口="保存主候補のCUSUM・1ATR追跡新規・45分待機と再開",
                条件=configurations(), 初期損切り="全条件2.5注文作成時ATR、呼値丸めあり",
                評価方法=["元12入口を独立に固定し出口だけ比較。再新規なしの診断", "入口ルール固定、出口変更後の45分待機と再新規を全て再生"],
                選定期間=list(SESSIONS[:4]), 確認期間=SESSIONS[4],
                注意="9/23を見て出口改善を発案しているため、順位計算から外しても新たな未使用期間ではない",
                選定条件="訓練の両銘柄が各々費用倍収支>0、基準費用倍収支の90%以上、各銘柄4取引以上、セル最大12取引以下。baseline除外",
                選定得点="訓練の銘柄別費用倍収支/基準費用倍収支の小さい方＋0.25×平均−0.15×元入口固定での利益返却合計/基準同合計。大きい順。適格なしは制約未達と明示した参考順位",
                感度="選定出口の保護更新・失速返済を追加1足と2足遅らせ、費用2tick/4tickを表示",
                禁止="将来極値での返済、9/23の時刻を返済条件へ埋め込むこと、現在API再取得")
    path = OUT / "出口比較計画.json"
    if path.exists():
        assert json.loads(path.read_text(encoding="utf-8")) == plan
    else:
        save_json(path, plan)
    return plan


def metrics(trades: list[dict], session: str, symbol: str) -> dict:
    """機能: 費用後の利益損失と、保有中の最大含み益からの返却を集計する。

    引数: trades (list[dict]) は同じセッション銘柄の取引、session/symbol (str) は識別子。
    返り値: １セルの指標 (dict)。円換算と元の価格幅を区別する。
    """
    assert all(t["closed"] for t in trades)
    values = np.array([t["net_points"] for t in trades], dtype=float)
    stress = np.array([t["stress_points"] for t in trades], dtype=float)
    giveback = sum(t["giveback_points"] for t in trades)
    maximum = sum(t["mfe_close_points"] for t in trades)
    multiplier = MULTIPLIERS[symbol]
    equity = np.r_[0., values.cumsum()]
    intervals = [(pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])) for t in trades]
    overlaps = sum(start < oldend for j, (start, end) in enumerate(intervals) for oldstart, oldend in intervals[:j])
    return dict(session=session, symbol=symbol, count=len(trades), profit=float(values[values > 0].sum()),
                loss=float(-values[values < 0].sum()), net=float(values.sum()), stress=float(stress.sum()),
                profit_yen=float(values[values > 0].sum())*multiplier, loss_yen=float(-values[values < 0].sum())*multiplier,
                net_yen=float(values.sum())*multiplier, stress_yen=float(stress.sum())*multiplier,
                giveback_points=float(giveback), giveback_yen=float(giveback)*multiplier,
                mfe_close_points=float(maximum), mfe_close_yen=float(maximum)*multiplier,
                wins=int((values > 0).sum()), losses=int((values < 0).sum()),
                time_exits=sum(t["reason"] == "セッション内の時刻返済" for t in trades),
                micro15_count=sum(t["duration_min"] <= 15 for t in trades),
                realized_dd_yen=float((np.maximum.accumulate(equity)-equity).max())*multiplier,
                overlapping_anchors=overlaps)


def evaluate(data: dict, schedules: dict, cfg: object, rule: object, primary: dict,
             anchored: bool, trace: bool = False) -> tuple[list[dict], list[dict]]:
    """機能: 同じ出口を５セッション両銘柄へ適用する。

    引数: data/schedules/primary (dict)、cfg/rule (object)、anchored/trace (bool)。
    返り値: 全取引とセル集計 (tuple[list[dict],list[dict]])。
    """
    from exit_engine import simulate
    trades, cells = [], []
    for key, item in data.items():
        anchors = [t for t in primary["trades"] if (t["session"], t["symbol"]) == key] if anchored else None
        result = simulate(item, schedules[key], cfg, rule, anchors=anchors, trace=trace)
        trades.extend(result)
        cells.append(metrics(result, *key))
    return trades, cells


def rank(full: list[dict], anchored: list[dict], baseline: list[dict], train: tuple[str, ...]) -> dict:
    """機能: 指定訓練セッションだけを使って出口条件へ点数を付ける。

    引数: full/anchored/baseline (list[dict]) はセル指標、train (tuple[str,...]) は選定範囲。
    返り値: 適格性・比率・得点 (dict)。確認期間の収支は参照しない。
    """
    ratios, eligible = [], True
    for symbol in SYMBOLS:
        cells = [r for r in full if r["session"] in train and r["symbol"] == symbol]
        bases = [r for r in baseline if r["session"] in train and r["symbol"] == symbol]
        value, reference = sum(r["stress_yen"] for r in cells), sum(r["stress_yen"] for r in bases)
        ratio = value/reference
        eligible &= value > 0 and ratio >= .9 and sum(r["count"] for r in cells) >= len(train) and max(r["count"] for r in cells) <= 12
        ratios.append(ratio)
    giveback = sum(r["giveback_yen"] for r in anchored if r["session"] in train)
    previous = sum(r["giveback_yen"] for r in baseline if r["session"] in train)
    retained_ratio = giveback/previous if previous else 0.
    return dict(eligible=bool(eligible), NK_ratio=ratios[0], TOP_ratio=ratios[1],
                giveback_ratio=retained_ratio, score=min(ratios)+.25*sum(ratios)/2-.15*retained_ratio)


def is_baseline(rule: object) -> bool:
    """機能: 元方式と同じ固定４ATRという別名も基準として識別する。

    引数: rule (object) は出口設定。
    返り値: 基準と意味が同じか (bool)。改善候補の順位からは除外する。
    """
    return rule.kind == "baseline" or (rule.kind == "fixed_trail" and rule.width == 4)


def main() -> None:
    """機能: 固定計画で出口を比較し、訓練選定・確認・感度結果を保存する。

    引数: なし。
    返り値: なし (None)。現在API・原本更新・注文送信は行わない。
    """
    from exit_engine import ExitRule
    began = time.monotonic()
    plan = freeze_plan()
    data, schedules, cfg, primary = load_inputs()
    rules = [ExitRule(**r) for r in plan["条件"]]
    base_trades, base_cells = evaluate(data, schedules, cfg, rules[0], primary, False)
    expected = normalize(primary["trades"])
    got = normalize(base_trades)
    assert len(got) == len(expected) == 12
    assert all({key: actual[key] for key in prior} == prior for actual, prior in zip(got, expected))
    rows, all_cells, results = [], [], {}
    for i, rule in enumerate(rules):
        full_trades, full_cells = evaluate(data, schedules, cfg, rule, primary, False)
        anchor_trades, anchor_cells = evaluate(data, schedules, cfg, rule, primary, True)
        selection = rank(full_cells, anchor_cells, base_cells, SESSIONS[:4])
        row = dict(key=rule.key, **asdict(rule), **selection)
        for mode, cells in (("full", full_cells), ("anchor", anchor_cells)):
            for symbol in SYMBOLS:
                subset = [r for r in cells if r["symbol"] == symbol]
                for field in ("net_yen", "stress_yen", "giveback_yen", "profit_yen", "loss_yen", "count"):
                    row[f"{mode}_{symbol}_{field}"] = sum(r[field] for r in subset)
            all_cells.extend(dict(rule=rule.key, mode=mode, **r) for r in cells)
        rows.append(row)
        results[rule.key] = dict(rule=asdict(rule), full=full_trades, anchored=anchor_trades,
                                 full_cells=full_cells, anchored_cells=anchor_cells)
        if i % 20 == 0:
            print(f"出口比較 {i+1}/{len(rules)}", flush=True)
    table = pd.DataFrame(rows).sort_values(["eligible", "score", "key"], ascending=[False, False, True])
    table.to_csv(OUT / "出口全条件比較.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(all_cells).to_csv(OUT / "出口全条件セッション.csv", index=False, encoding="utf-8-sig")
    save_json(OUT / "出口全条件取引.json", results)
    candidates = table[~((table.kind == "baseline") | ((table.kind == "fixed_trail") & (table.width == 4)))]
    best = candidates.iloc[0]
    rule = next(r for r in rules if r.key == best.key)
    selected_trades, selected_cells = evaluate(data, schedules, cfg, rule, primary, False, trace=True)
    anchor_trades, anchor_cells = evaluate(data, schedules, cfg, rule, primary, True, trace=True)
    baseline_traces, _ = evaluate(data, schedules, cfg, rules[0], primary, False, trace=True)
    payload = dict(baseline=dict(name="元の4ATR追跡", trades=baseline_traces, cells=base_cells),
                   selected=dict(rule=asdict(rule), key=rule.key, name="訓練４セッションで選んだ出口", trades=selected_trades, cells=selected_cells),
                   fixed_entries=dict(name="元12入口を固定した出口比較", trades=anchor_trades, cells=anchor_cells),
                   selection=dict(train=list(SESSIONS[:4]), check=SESSIONS[4], eligible=bool(best.eligible), score=float(best.score)))
    save_json(OUT / "比較対象.json", payload)
    sensitivity = []
    for delay in (1, 2):
        delayed = ExitRule(**(asdict(rule) | dict(delay=delay)))
        ts, cs = evaluate(data, schedules, cfg, delayed, primary, False)
        sensitivity.append(dict(rule=asdict(delayed), trades=ts, cells=cs))
    save_json(OUT / "選定出口の遅延感度.json", sensitivity)
    # ----------------------------------------
    # 選定の安定性を、時間順のもう一つの切断と一セッション除外でも確認する。
    folds = []
    splits = [(SESSIONS[:3], (SESSIONS[3],), "時間順３→４")]
    splits += [(tuple(s for s in SESSIONS if s != test), (test,), "一セッション除外") for test in SESSIONS]
    for train, test, label in splits:
        scored = []
        for current in rules:
            if is_baseline(current):
                continue
            result = results[current.key]
            score = rank(result["full_cells"], result["anchored_cells"], base_cells, train)
            scored.append(dict(key=current.key, **score))
        pick = sorted(scored, key=lambda r: (-r["eligible"], -r["score"], r["key"]))[0]
        result = results[pick["key"]]
        folds.append(dict(label=label, train=train, test=test, selection=pick,
                          rule=result["rule"], cells=[r for r in result["full_cells"] if r["session"] in test]))
    save_json(OUT / "出口の期間分割.json", folds)
    save_json(OUT / "出口比較完了.json", dict(条件数=len(rules), 所要秒=time.monotonic()-began,
              選定=normalize(best.to_dict()), 基準12取引完全一致=True, 現在API取得=False))
    print(json.dumps(dict(条件数=len(rules), 選定=asdict(rule), 適格=bool(best.eligible)), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    import sys
    if "--plan" in sys.argv:
        print(json.dumps(freeze_plan(), ensure_ascii=False, indent=2))
    else:
        main()
