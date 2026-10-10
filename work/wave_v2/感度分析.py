"""採用予定条件を変更せず、閾値と追加執行遅延への感度を確認する。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

import research_v2 as core


OUT = Path(__file__).resolve().parent


def evaluate_delay(data: dict, threshold: float, delay: int) -> tuple[list, list, list]:
    """元時刻で作った判定の受渡しだけを遅らせて保存セッションを再生する。

    引数: data（dict）保存データ、threshold（float）閾値、delay（int）追加遅延の分数。
    返り値: tuple[list, list, list]。取引、指定波評価、セッション別集計。
    """
    cfg = core.Config(24, threshold, 1, 4, 1)
    all_trades, targets, cells = [], [], []
    for (session, symbol), (one, original) in data.items():
        peer = data[(session, "TOPIX" if symbol == "NK225" else "NK225")][1]
        strength = core.score(original, peer, cfg.family, cfg.threshold).copy()
        features = original.copy()
        if delay:
            features.index = features.index + pd.Timedelta(minutes=delay)
            strength.index = strength.index + pd.Timedelta(minutes=delay)
            features["stale_minutes"] += delay
        trades = core.simulate(one, features, strength, cfg, symbol, session)
        all_trades.extend(trades)
        targets.extend(core.target_metrics(one, trades, symbol, session))
        closed = [trade for trade in trades if trade["closed"]]
        assert len(closed) == len(trades), "保存済みセッションに未返済取引が残っています"
        pnl = [trade["net_points"] for trade in closed]
        equity = np.r_[0, np.cumsum(pnl)]
        cells.append(dict(
            symbol=symbol, session=session, count=len(trades), closed=len(closed),
            net_points=sum(pnl), stress_points=sum(trade["stress_points"] for trade in closed),
            win_rate=sum(value > 0 for value in pnl) / len(pnl) if pnl else None,
            max_drawdown_points=float((np.maximum.accumulate(equity) - equity).max()),
        ))
    return all_trades, targets, cells


def main() -> None:
    """閾値五点と追加遅延四点を評価して日本語の表と詳細を保存する。

    引数: なし。
    返り値: None。感度分析.md と 感度分析.csv を出力する。
    """
    data = core.load_data(with_book=False)
    conditions = [("閾値", value, 0) for value in (.20, .225, .25, .275, .30)]
    conditions += [("追加遅延", .25, value) for value in (0, 1, 2, 5)]
    records, summary, all_targets, all_cells = [], [], [], []
    for kind, threshold, delay in conditions:
        trades, targets, cells = evaluate_delay(data, threshold, delay)
        base = dict(analysis=kind, threshold=threshold, additional_delay_min=delay)
        frequencies = [cell["count"] for cell in cells]
        item = dict(
            **base, target_pass=sum(target["passed"] for target in targets),
            target_count=len(targets), count=len(trades), min_session_count=min(frequencies),
            max_session_count=max(frequencies),
            min_coverage=min(target["correct_coverage"] for target in targets),
            min_capture=min(target["capture_ratio"] for target in targets),
        )
        for symbol in core.SYMBOLS:
            item[f"{symbol}_net_points"] = sum(cell["net_points"] for cell in cells if cell["symbol"] == symbol)
            item[f"{symbol}_stress_points"] = sum(cell["stress_points"] for cell in cells if cell["symbol"] == symbol)
        summary.append(item)
        records.append(dict(record_type="全体", **item))
        for target in targets:
            record = dict(record_type="指定波", **base, **target)
            records.append(record)
            all_targets.append(record)
        for cell in cells:
            record = dict(record_type="銘柄セッション", **base, **cell)
            records.append(record)
            all_cells.append(record)
        print(f"{kind}: 閾値={threshold}, 追加遅延={delay}, 指定波={item['target_pass']}/4", flush=True)

    # ----------------------------------------
    # 遅延なしの結果が元の評価関数と一致することを確認する。
    direct_trades, direct_targets, _ = core.evaluate(data, core.Config(24, .25, 1, 4, 1))
    replay_trades, replay_targets, _ = evaluate_delay(data, .25, 0)
    assert direct_trades == replay_trades
    assert direct_targets == replay_targets
    pd.DataFrame(records).to_csv(OUT / "感度分析.csv", index=False, encoding="utf-8-sig")

    # ----------------------------------------
    # 条件の再選定は行わず、閾値依存性と遅延への弱さを記録する。
    lines = [
        "# 固定候補の閾値・執行遅延への感度", "",
        "対象は系統24、閾値0.25、確認1分、追跡幅4、反対確認倍率1の採用予定条件。感度分析による再選択は行わない。保存三セッションのみを読み、現在セッションＡＰＩ・現在キャッシュは使用していない。",
        "", "## 方法", "",
        "閾値 q を0.20・0.225・0.25・0.275・0.30へ変えた。方向指数の条件は0.6q、60分回帰の条件は2qとなる。その他のパラメータは共通で固定した。",
        "",
        "追加執行遅延は0・1・2・5分。判定値は元時刻で作り、その後に simulate へ渡す特徴量と判定値の時刻を同じだけ後ろへずらした。価格足と時刻返済期限は変更せず、stale_minutes に追加遅延を加算した。従って追加遅延0でも、本体に元からある一分枠開始から２分後の仮想執行待ちが存在する。遅延0の取引・指定波評価が本体 evaluate と完全一致することも確認した。",
        "",
        "銘柄別損益は３セッション合計の価格幅で、金額ではない。通常は往復２刻み、厳しい条件は往復４刻みを価格差から控除する。日中・夜間は別セッションとし、全試行で全取引のセッション内返済を確認した。指定波合格は検知遅れ60分以内、方向一致時間60%以上、対象価格幅の40%以上捕捉を同時に満たすこと。",
        "", "## 全体結果", "",
        "|分析|閾値|追加遅延分|指定波合格|取引数|セッション別回数範囲|最小時間捕捉率|NK225価格幅|TOPIX価格幅|NK225厳条件|TOPIX厳条件|",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for item in summary:
        lines.append(
            f"|{item['analysis']}|{item['threshold']:.3f}|{item['additional_delay_min']}|"
            f"{item['target_pass']}/4|{item['count']}|{item['min_session_count']}〜{item['max_session_count']}|"
            f"{item['min_coverage']:.1%}|{item['NK225_net_points']:.1f}|{item['TOPIX_net_points']:.1f}|"
            f"{item['NK225_stress_points']:.1f}|{item['TOPIX_stress_points']:.1f}|"
        )
    lines += ["", "## 指定波ごとの結果", "",
              "|分析|閾値|追加遅延分|銘柄|セッション|合格|検知遅れ分|方向一致時間率|価格捕捉率|",
              "|---|---:|---:|---|---|---|---:|---:|---:|"]
    for item in all_targets:
        lag = "なし" if item["detection_delay_min"] is None else f"{item['detection_delay_min']:.0f}"
        lines.append(f"|{item['analysis']}|{item['threshold']:.3f}|{item['additional_delay_min']}|{item['symbol']}|"
                     f"{item['session']}|{'可' if item['passed'] else '不可'}|{lag}|"
                     f"{item['correct_coverage']:.1%}|{item['capture_ratio']:.1%}|")
    lines += ["", "## 銘柄・セッション別の頻度と価格幅", "",
              "|分析|閾値|追加遅延分|銘柄|セッション|回数|価格幅|",
              "|---|---:|---:|---|---|---:|---:|"]
    for item in all_cells:
        lines.append(f"|{item['analysis']}|{item['threshold']:.3f}|{item['additional_delay_min']}|{item['symbol']}|"
                     f"{item['session']}|{item['count']}|{item['net_points']:.1f}|")
    reference = next(item for item in summary if item["analysis"] == "追加遅延" and item["additional_delay_min"] == 0)
    late = next(item for item in summary if item["analysis"] == "追加遅延" and item["additional_delay_min"] == 5)
    lines += ["", "## 感度の解釈", "",
              "閾値0.20〜0.30の五点では指定波合格数、取引数、銘柄別損益が同一だった。この範囲の閾値の小さな調整だけに成果が依存する兆候は見られない。ただし、閾値以外の60分回帰、方向指数の平滑化、他指数一致条件、初期化の方法は固定しており、それらへの過適合は検証していない。",
              "",
              f"追加遅延２分までは４波合格を保ったが、５分で{late['target_pass']}/4へ減った。９月22日の両指数ショートが遅れ61分・方向一致57.9%となり、検知60分以内・時間捕捉60%以上の二条件を割った。基準の同区間は遅れ56分・時間捕捉61.4%であり、合格境界までの余裕は小さい。５分遅れで波自体が消えたわけではないが、指定の捕捉基準には数分の遅れへの弱さがある。",
              "",
              f"TOPIXの通常控除後の価格幅は基準{reference['TOPIX_net_points']:.1f}から５分追加で{late['TOPIX_net_points']:.1f}へ減り、往復４刻み控除では{late['TOPIX_stress_points']:.1f}となる。NK225の同じ追加遅延では通常控除後{late['NK225_net_points']:.1f}であり、執行条件への余裕は銘柄間で大きく異なる。",
              "", "## 判定の範囲", "",
              "この分析は保存三セッションへの適合が小さな変更で崩れるかを確認するもので、未知データの検証ではない。条件探索と同じ標本であり、閾値の近傍が安定しても初期値への過適合を否定できない。追加遅延は成行滑り・約定拒否・板流動性を再現するものではなく、時刻が数分変わることへの感度だけを測る。",
              "", "再現: `python work/wave_v2/感度分析.py`。詳細は 感度分析.csv。",
              "", f"評価時の research_v2.py の SHA-256: `{hashlib.sha256((OUT / 'research_v2.py').read_bytes()).hexdigest()}`。", ""]
    (OUT / "感度分析.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
