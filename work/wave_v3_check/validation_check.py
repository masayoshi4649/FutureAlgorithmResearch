"""追加夜間セッションを用いた固定検知器の因果性と返済境界の独立監査。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = OUT.parent / "wave_v2"
sys.path.insert(0, str(OLD))
import research_v2 as r
import replay
from clock_features import price_features_until

SESSION = "2026-09-22_Night"


def normalized(value: object) -> object:
    """機能: 比較用に時刻と数値をJSON互換値へ変換する。

    引数: value (object)。返り値: JSON互換値 (object)。
    """
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def features(frames: dict) -> dict:
    """機能: 読み込んだ確定足から銘柄ごとの特徴量を生成する。

    引数: frames (dict[str, dict[int, DataFrame]])。返り値: 評価用入力 (dict)。
    """
    return {(SESSION, symbol): (bars[1], r.price_features(bars[1], bars[5], r.TICKS[symbol]))
            for symbol, bars in frames.items()}


def common_features(frames: dict, cutoff: pd.Timestamp) -> dict:
    """機能: 両指数を同じ確定時刻まで進め、実在足と特徴量を別々に返す。

    引数: frames (dict)、cutoff (Timestamp)。返り値: 評価用入力 (dict)。
    """
    end = cutoff.floor("min") - pd.Timedelta(minutes=1)
    return {(SESSION, symbol): (bars[1], price_features_until(bars[1], bars[5], r.TICKS[symbol], end))
            for symbol, bars in frames.items()}


def truncated(frames: dict, cutoff: pd.Timestamp) -> dict:
    """機能: 指定時刻までに確定していた足だけを残す。

    引数: frames (dict)、cutoff (Timestamp)。返り値: 切断後の確定足 (dict)。
    """
    return {symbol: {minutes: bars[bars.index + pd.Timedelta(minutes=minutes) <= cutoff].copy()
                     for minutes, bars in periods.items()} for symbol, periods in frames.items()}


def signals(data: dict, cfg: r.Config) -> dict:
    """機能: 各銘柄の固定設定方向信号を算出する。

    引数: data (dict)、cfg (Config)。返り値: 銘柄別信号 (dict[str, Series])。
    """
    result = {}
    for symbol in r.SYMBOLS:
        peer = "TOPIX" if symbol == "NK225" else "NK225"
        result[symbol] = r.score(data[(SESSION, symbol)][1], data[(SESSION, peer)][1], cfg.family, cfg.threshold)
    return result


def compare_prefix(data: dict, prefix: dict, cfg: r.Config, full_signals: dict, full_trades: list) -> dict:
    """機能: 切断入力の信号・新規約定・確定済み返済が全期間入力と一致するか照合する。

    引数: data/prefix (dict)、cfg (Config)、full_signals (dict)、full_trades (list)。
    返り値: 銘柄別の照合結果 (dict)。観測途中の取引の将来返済は比較しない。
    """
    prefix_signals = signals(prefix, cfg)
    prefix_trades = r.evaluate(prefix, cfg)[0]
    entry_keys = ("symbol", "side", "signal_time", "entry_time", "entry_price", "atr")
    result = {}
    for symbol in r.SYMBOLS:
        series = prefix_signals[symbol]
        expected = full_signals[symbol].reindex(series.index)
        difference = series.ne(expected)
        last = prefix[(SESSION, symbol)][0].index[-1]
        actual_trades = [t for t in prefix_trades if t["symbol"] == symbol]
        expected_trades = [t for t in full_trades if t["symbol"] == symbol and t["entry_time"] <= last]
        entry_match = normalized([{k: t[k] for k in entry_keys} for t in actual_trades]) == normalized(
            [{k: t[k] for k in entry_keys} for t in expected_trades])
        closed_match = normalized([t for t in actual_trades if t["closed"]]) == normalized(
            [t for t in expected_trades if t["closed"] and t["exit_time"] <= last])
        result[symbol] = dict(最終観測=last, 信号一致=not difference.any(),
                             信号不一致時刻=list(series.index[difference]), 新規一致=entry_match,
                             確定済返済一致=closed_match)
    return result


def mutate_future(frames: dict, cutoff: pd.Timestamp, target: str) -> dict:
    """機能: 一方の銘柄の未確定足と未来足を大幅変更した入力を作る。

    引数: frames (dict)、cutoff (Timestamp)、target (str)。返り値: 変更済入力 (dict)。
    """
    changed = {symbol: {minutes: bars.copy() for minutes, bars in periods.items()}
               for symbol, periods in frames.items()}
    for minutes, bars in changed[target].items():
        future = bars.index + pd.Timedelta(minutes=minutes) > cutoff
        bars.loc[future, ["open", "high", "low", "close"]] *= 2
        bars.loc[future, "volume"] *= 7
    return changed


def main() -> None:
    """機能: 新セッションの複数切断・未来改変・同セッション返済を検査し保存する。

    引数: なし。返り値: なし (None)。旧成果物・元データの変更と通信は行わない。
    """
    fixed = json.loads((OLD / "固定設定.json").read_text(encoding="utf-8"))
    cfg = r.Config(**fixed["config"])
    code_hash = hashlib.sha256((OLD / "research_v2.py").read_bytes()).hexdigest()
    frames = {symbol: {minutes: r.read_candle(ROOT / f"candle_{minutes}min" / symbol / f"{SESSION}.csv")
                       for minutes in (1, 5)} for symbol in r.SYMBOLS}
    data = features(frames)
    full_signals = signals(data, cfg)
    full_trades, _, _ = r.evaluate(data, cfg)

    # ----------------------------------------
    # 五分ごとの終端に重要時刻を加え、最終足の不一致を含む再生を検査する。
    cutoffs = list(pd.date_range("2026-09-22T18:00:00+09:00", "2026-09-23T05:55:00+09:00", freq="5min"))
    cutoffs.extend(pd.Timestamp(t) for t in ("2026-09-23T00:28:00+09:00", "2026-09-23T01:18:00+09:00",
                                          "2026-09-23T05:51:00+09:00", "2026-09-23T05:54:00+09:00"))
    cutoffs.extend(pd.date_range("2026-09-23T03:56:00+09:00", "2026-09-23T04:11:00+09:00", freq="min"))
    prefix_results, common_results = [], []
    for cutoff in sorted(set(cutoffs)):
        prefix_frames = truncated(frames, cutoff)
        prefix = features(prefix_frames)
        prefix_results.append(dict(切断時刻=cutoff, 照合=compare_prefix(data, prefix, cfg, full_signals, full_trades)))
        common = common_features(prefix_frames, cutoff)
        common_results.append(dict(切断時刻=cutoff, 照合=compare_prefix(data, common, cfg, full_signals, full_trades)))

    # ----------------------------------------
    # 未来変更は両銘柄それぞれで行い、未確定５分足の高安も変更対象にする。
    mutation_results = []
    for text in ("2026-09-22T18:04:00+09:00", "2026-09-22T21:28:00+09:00", "2026-09-23T00:28:00+09:00",
                 "2026-09-23T01:18:00+09:00", "2026-09-23T03:33:00+09:00", "2026-09-23T05:48:00+09:00"):
        cutoff = pd.Timestamp(text)
        for target in r.SYMBOLS:
            changed = features(mutate_future(frames, cutoff, target))
            changed_signals = signals(changed, cfg)
            changed_trades = r.evaluate(changed, cfg)[0]
            symbol_rows = []
            for symbol in r.SYMBOLS:
                eligible = full_signals[symbol].index + pd.Timedelta(minutes=1) <= cutoff
                same_signal = full_signals[symbol][eligible].equals(changed_signals[symbol][eligible])
                old_entries = [{k: t[k] for k in ("symbol", "side", "entry_time", "entry_price", "atr")}
                               for t in full_trades if t["symbol"] == symbol and t["entry_time"] < cutoff]
                new_entries = [{k: t[k] for k in ("symbol", "side", "entry_time", "entry_price", "atr")}
                               for t in changed_trades if t["symbol"] == symbol and t["entry_time"] < cutoff]
                old_closed = [t for t in full_trades if t["symbol"] == symbol and t["closed"] and t["exit_time"] < cutoff]
                new_closed = [t for t in changed_trades if t["symbol"] == symbol and t["closed"] and t["exit_time"] < cutoff]
                symbol_rows.append(dict(銘柄=symbol, 信号一致=same_signal, 新規一致=normalized(old_entries)==normalized(new_entries),
                                        確定済返済一致=normalized(old_closed)==normalized(new_closed)))
            mutation_results.append(dict(切断時刻=cutoff, 改変銘柄=target, 照合=symbol_rows))

    # ----------------------------------------
    # キャッシュ照合と、返済期限の実在足・同セッション価格制約を検査する。
    cache = replay.cached_data()
    cache_comparison = compare_prefix(data, cache, cfg, full_signals, full_trades)
    exits, boundaries = [], []
    for symbol in r.SYMBOLS:
        one, z = data[(SESSION, symbol)]
        limit = r.deadline(one.index)
        trades = [t for t in full_trades if t["symbol"] == symbol]
        exits.append(dict(銘柄=symbol, 予定返済時刻=limit, 予定時刻の足あり=limit in one.index,
                          予定時刻以後の最初の足=one.index[one.index >= limit][0],
                          実際の返済時刻=[t["exit_time"] for t in trades], 全件返済済み=all(t["closed"] for t in trades),
                          全返済が実在足=all(t["exit_time"] in one.index for t in trades),
                          全返済が同セッション=all(t["exit_time"] < limit + pd.Timedelta(minutes=5) for t in trades),
                          期限３０分前から新規なし=all(t["entry_time"] < limit-pd.Timedelta(minutes=30) for t in trades)))
        for added_time in (limit+pd.Timedelta(minutes=5), limit.normalize()+pd.Timedelta(hours=8, minutes=45)):
            row = one.iloc[[-1]].copy()
            row.index = pd.DatetimeIndex([added_time])
            contaminated = pd.concat([one, row]).sort_index()
            rejected = False
            reason = None
            try:
                r.simulate(contaminated, z, full_signals[symbol], cfg, symbol, SESSION)
            except ValueError as error:
                rejected, reason = True, str(error)
            boundaries.append(dict(銘柄=symbol, 混入時刻=added_time, 拒否=rejected, 理由=reason))

    prefix_failures = [row for row in prefix_results if any(not x["信号一致"] or not x["新規一致"] or not x["確定済返済一致"] for x in row["照合"].values())]
    mutation_failures = [row for row in mutation_results if any(not x["信号一致"] or not x["新規一致"] or not x["確定済返済一致"] for x in row["照合"])]
    common_failures = [row for row in common_results if any(not x["信号一致"] or not x["新規一致"] or not x["確定済返済一致"] for x in row["照合"].values())]

    # ----------------------------------------
    # 共通終端による検算が既存３セッションと今回の完全再生結果を変えないことも検査する。
    full_comparisons = []
    for session in (*r.SESSIONS, SESSION):
        original, aligned = {}, {}
        source = {symbol: {minutes: r.read_candle(ROOT / f"candle_{minutes}min" / symbol / f"{session}.csv")
                           for minutes in (1, 5)} for symbol in r.SYMBOLS}
        end = max(bars[1].index[-1] for bars in source.values())
        for symbol, bars in source.items():
            original[(session, symbol)] = (bars[1], r.price_features(bars[1], bars[5], r.TICKS[symbol]))
            aligned[(session, symbol)] = (bars[1], price_features_until(bars[1], bars[5], r.TICKS[symbol], end))
        signal_match = True
        for symbol in r.SYMBOLS:
            peer = "TOPIX" if symbol == "NK225" else "NK225"
            old_signal = r.score(original[(session, symbol)][1], original[(session, peer)][1], cfg.family, cfg.threshold)
            new_signal = r.score(aligned[(session, symbol)][1], aligned[(session, peer)][1], cfg.family, cfg.threshold)
            signal_match = signal_match and old_signal.equals(new_signal.reindex(old_signal.index))
        old_result, new_result = r.evaluate(original, cfg), r.evaluate(aligned, cfg)
        full_comparisons.append(dict(セッション=session, 元の全期間信号と一致=signal_match,
                                     全取引一致=normalized(old_result[0])==normalized(new_result[0]),
                                     指定波集計一致=normalized(old_result[1])==normalized(new_result[1]),
                                     セッション集計一致=normalized(old_result[2])==normalized(new_result[2])))

    # ----------------------------------------
    # 04:01の新規判定には04:00締切の信号だけを使い、後続足による再計算を許さない。
    decision_cutoff = pd.Timestamp("2026-09-23T04:00:00+09:00")
    execution_time = decision_cutoff + pd.Timedelta(minutes=1)
    decision_frames = truncated(frames, decision_cutoff)
    execution_audit = []
    for label, variant in (("元の銘柄別終端", features(decision_frames)),
                           ("共通の観測終端", common_features(decision_frames, decision_cutoff))):
        strength = signals(variant, cfg)["TOPIX"]
        one = frames["TOPIX"][1]
        execution_one = one[one.index <= execution_time]
        result_trades = r.simulate(execution_one, variant[(SESSION, "TOPIX")][1], strength, cfg, "TOPIX", SESSION)
        execution_audit.append(dict(方式=label, 判断締切=decision_cutoff, 執行時刻=execution_time,
                                   三時五十九分の方向=float(strength.loc[decision_cutoff-pd.Timedelta(minutes=1)]),
                                   当該時刻の返済=[dict(方向=t["side"], 理由=t["reason"]) for t in result_trades if t["exit_time"]==execution_time],
                                   当該時刻の新規=[dict(方向=t["side"], 価格=t["entry_price"]) for t in result_trades if t["entry_time"]==execution_time]))
    result = dict(記録時刻=pd.Timestamp.now(tz="Asia/Tokyo"), 固定設定=cfg.key,
                  固定コードハッシュ一致=code_hash==fixed["code_sha256"], 通信回数=0,
                  共通終端コードSHA256=hashlib.sha256((OUT / "clock_features.py").read_bytes()).hexdigest(),
                  監査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  切断時点数=len(prefix_results), 切断検査不一致数=len(prefix_failures), 切断検査不一致=prefix_failures,
                  共通終端検算不一致数=len(common_failures), 共通終端検算不一致=common_failures,
                  共通終端での全保存セッション照合=full_comparisons,
                  端点差による当時判断の違い=execution_audit,
                  未来改変組数=len(mutation_results), 未来改変不一致数=len(mutation_failures), 未来改変検査=mutation_results,
                  既知キャッシュ照合=cache_comparison, 返済検査=exits, セッション外混入検査=boundaries,
                  全切断検査=prefix_results, 共通終端の全切断検査=common_results)
    r.save_json(OUT / "検証監査.json", result)
    lines = ["# 追加データの固定検知器監査", "", f"固定設定 `{cfg.key}`。コードハッシュ一致: {code_hash==fixed['code_sha256']}。通信0回。",
             f"確定足を時刻で切断した{len(prefix_results)}時点の検査で、元実装の不一致は{len(prefix_failures)}時点。共通観測終端へ修正後の不一致は{len(common_failures)}時点。",
             f"未来の一分足・未確定五分足を大幅変更した{len(mutation_results)}組の検査で、不一致は{len(mutation_failures)}組。", "",
             "## セッション内返済", "", "予定時刻以後の最初の実在足始値で返済する仕様を、その足の有無と分けて確認した。"]
    for row in exits:
        lines.append(f"- {row['銘柄']}: 05:50足あり={row['予定時刻の足あり']}、05:50以後の初足={row['予定時刻以後の最初の足']}。全件返済={row['全件返済済み']}、同セッション={row['全返済が同セッション']}。")
    lines += ["", "05:55と翌日08:45の別セッション価格を追加した4ケースは全て拒否した。",
              "この検査は保存足に基づくシミュレーターの整合性を確認するもので、実注文の約定保証ではない。", "",
              "## 判定資料", "", "細目は `検証監査.json` に全切断時点・未来改変・キャッシュ照合を保存した。"]
    if prefix_failures:
        lines += ["", "## 観測終端の不一致と別ファイルによる検算", "",
                  "元の特徴量関数は銘柄ごとの最終実在足で時刻軸を終える。04:00時点ではNK225の最終足が03:56、TOPIXは03:59のため、TOPIXから参照するNK225の03:59特徴量が末尾切断入力で欠ける。",
                  "全期間再生では後続足があるため既知のNK225価格を03:59まで持ち越せるが、逐次切断の元関数ではこの行が存在しない。未来価格を使用する誤りとは異なるものの、実時間でそのまま使うと信号の時刻と方向が変わる実装上の不備である。",
                  "別ファイル `clock_features.py` の `price_features_until` は特徴量計算だけの終端を両銘柄共通の観測時刻に延ばし、実在足・経過時間は保持する。約定用の一分足へ仮の行は追加しない。凍結済み検知器は変更していない。",
                  f"同じ{len(common_results)}切断時点で共通終端を使った検算の不一致は{len(common_failures)}件。既存３セッションと今回夜間の全期間信号・全取引・指定波・セッション集計も別途照合した。",
                  "04:00までに確定した信号だけを使い04:01の実在足で執行する具体例では、元関数はTOPIXを中立としロング返済だけを行う。共通終端と全期間再生はショート信号となり、同時刻にロングを返済してショートを新規に行う。この違いは実注文判断へ影響する。後続足が届いてから過去信号を再計算すると差が消えるので、単なる確定取引一覧の比較だけでは検出できない。",
                  "共通終端を明示する前処理を実時間利用の必要条件とする。旧関数単独の切断再生は無条件の合格とは扱わない。"]
    (OUT / "検証監査.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps(normalized({k: v for k, v in result.items() if k not in ("全切断検査", "未来改変検査", "共通終端の全切断検査")}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
