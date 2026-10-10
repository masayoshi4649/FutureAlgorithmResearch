"""保存足を時刻ごとに切り直し、特徴・方向の未来参照がないことを独立監査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
ARCHIVE = ROOT / "アルゴリズム調査" / "00001_波検知と売買ポイントの調査" / "保存版"
V4 = ARCHIVE / "work" / "wave_v4"
sys.dont_write_bytecode = True
sys.path.insert(0, str(V4))

from engine import TICKS, prepare, sign_schedule
from signals import build_features, get_signals


SESSIONS = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night", "2026-09-23_Day")
SYMBOLS = ("NK225", "TOPIX")


def read_frame(path: Path) -> pd.DataFrame:
    """機能: 確定済みの保存足を時刻順に読み込む。

    引数: path (Path) は読み取り専用の元CSV。
    返り値: 開始時刻を索引とする確定足 (DataFrame)。
    """
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame.time)
    frame = frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
    assert not frame.index.duplicated().any()
    return frame


def online_values(one: pd.DataFrame, five: pd.DataFrame, index: pd.DatetimeIndex, tick: float) -> tuple:
    """機能: 到着した確定足だけでATRと累積和方向を逐次更新する。

    引数: one/five (DataFrame) は足、index (DatetimeIndex) は１分格子、tick (float) は呼値。
    返り値: 独立計算のATR列・方向列・入力時刻監査件数 (tuple)。
    ATRの内部状態を下限で切らず、出力値だけ２呼値へ切り上げる。
    """
    five_rows = list(five.itertuples())
    five_position, five_count = 0, 0
    average = np.nan
    previous_five_close = np.nan
    previous_close = np.nan
    last_observed = None
    close = np.nan
    positive, negative, side = 0.0, 0.0, 0
    atr_values, sides, timing_count = [], [], 0
    for age, feature_time in enumerate(index):
        available_at = feature_time + pd.Timedelta(minutes=1)
        while five_position < len(five_rows) and five_rows[five_position].Index + pd.Timedelta(minutes=5) <= available_at:
            row = five_rows[five_position]
            true_range = row.high - row.low
            if np.isfinite(previous_five_close):
                true_range = max(true_range, abs(row.high - previous_five_close), abs(row.low - previous_five_close))
            average = true_range if five_count == 0 else average * (11 / 12) + true_range / 12
            previous_five_close = row.close
            five_count += 1
            five_position += 1
            timing_count += 1
        atr = max(2 * tick, average) if five_count >= 3 else np.nan
        if feature_time in one.index:
            assert feature_time + pd.Timedelta(minutes=1) <= available_at
            close = float(one.loc[feature_time, "close"])
            last_observed = feature_time
            timing_count += 1
        stale = np.inf if last_observed is None else (feature_time - last_observed).total_seconds() / 60
        valid = age >= 14 and np.isfinite(atr) and stale <= 10
        delta = (close - previous_close) / atr if np.isfinite(atr) else np.nan
        if valid and np.isfinite(delta):
            positive = max(0.0, positive + delta - 0.025)
            negative = min(0.0, negative + delta + 0.025)
            if positive >= 0.6375:
                side, positive, negative = 1, 0.0, 0.0
            elif negative <= -0.6375:
                side, positive, negative = -1, 0.0, 0.0
        previous_close = close
        atr_values.append(atr)
        sides.append(side if valid else 0)
    return np.array(atr_values), np.array(sides, dtype=np.int8), timing_count


def cut_times(one: pd.DataFrame, five: pd.DataFrame, end: pd.Timestamp) -> list:
    """機能: ５分足確定境界の直前・当該時刻・直後を含む監査時刻を選ぶ。

    引数: one/five (DataFrame) は足、end (Timestamp) は全期間格子の最終時刻。
    返り値: 重複のない打切り時刻 (list[Timestamp])。
    """
    candidates = five.index[2:-1] + pd.Timedelta(minutes=5)
    chosen = candidates[np.unique(np.linspace(0, len(candidates) - 1, 8, dtype=int))]
    times = {value + pd.Timedelta(minutes=delta) for value in chosen for delta in (-1, 0, 1)}
    return sorted(value for value in times if one.index[0] + pd.Timedelta(minutes=1) <= value <= end)


def poison_future(frame: pd.DataFrame, minutes: int, cutoff: pd.Timestamp) -> pd.DataFrame:
    """機能: 打切り時点で未確定の全OHLCと出来高を大きく変更する。

    引数: frame (DataFrame) は元足、minutes (int) は足長、cutoff (Timestamp) は判断時刻。
    返り値: 過去の確定行を変更していない独立コピー (DataFrame)。
    """
    changed = frame.copy()
    mask = changed.index + pd.Timedelta(minutes=minutes) > cutoff
    for column in ("open", "high", "low", "close"):
        changed.loc[mask, column] = changed.loc[mask, column] * 7 + 123456
    changed.loc[mask, "volume"] = changed.loc[mask, "volume"] * 31 + 98765
    return changed


def main() -> None:
    """機能: 元CSV打切り・未来改変・独立逐次計算を実データに適用して保存する。

    引数: なし。
    返り値: なし (None)。不一致を検知した場合は例外で停止する。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    original_audit = json.loads((ARCHIVE / "work" / "wave_v5" / "データ監査.json").read_text(encoding="utf-8"))
    expected_hashes = {name.replace("\\", "/"): value for name, value in original_audit["source_sha256"].items()}
    file_checks, cells, cuts = [], [], []
    all_frames = {}
    for session in SESSIONS:
        for symbol in SYMBOLS:
            parts = []
            for minutes in (1, 5):
                relative = f"candle_{minutes}min/{symbol}/{session}.csv"
                path = ARCHIVE / relative
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                assert digest == expected_hashes[relative]
                file_checks.append(dict(ファイル=relative, SHA256=digest, 保存時と一致=True))
                parts.append(read_frame(path))
            all_frames[session, symbol] = parts

    # ----------------------------------------
    # 同じ元足から全期間版と各時刻までの限定版をそれぞれ新規構築する。
    for session in SESSIONS:
        end = max(all_frames[session, symbol][0].index[-1] for symbol in SYMBOLS)
        for symbol in SYMBOLS:
            one, five = all_frames[session, symbol]
            tick = TICKS[symbol]
            full = build_features(one, five, None, tick, end)
            signs = get_signals(full, full, 9, 0.75)
            data = prepare(one, full, symbol, session)
            online_atr, online_signs, input_count = online_values(one, five, full.index, tick)
            np.testing.assert_allclose(online_atr, full.atr.to_numpy(), rtol=1e-12, atol=1e-12, equal_nan=True)
            np.testing.assert_array_equal(online_signs, signs.to_numpy())
            maximum_error = float(np.nanmax(np.abs(online_atr - full.atr.to_numpy())))
            usable_positions = data["positions"] >= 0
            positions = data["positions"][usable_positions]
            execution_times = one.index[usable_positions]
            np.testing.assert_array_equal(full.index[positions] + pd.Timedelta(minutes=2), execution_times)
            assert ((full.index[positions] + pd.Timedelta(minutes=1)) < execution_times).all()

            # ----------------------------------------
            # 未来の削除と未来の大幅改変の両方で過去出力の不変性を確認する。
            for cutoff in cut_times(one, five, end):
                limited_one = one.loc[one.index + pd.Timedelta(minutes=1) <= cutoff].copy()
                limited_five = five.loc[five.index + pd.Timedelta(minutes=5) <= cutoff].copy()
                prefix_end = cutoff - pd.Timedelta(minutes=1)
                prefix = build_features(limited_one, limited_five, None, tick, prefix_end)
                expected = full.loc[:prefix_end]
                pd.testing.assert_frame_equal(prefix, expected, check_exact=False, rtol=1e-12, atol=1e-12)
                prefix_signs = get_signals(prefix, prefix, 9, 0.75)
                pd.testing.assert_series_equal(prefix_signs, signs.loc[:prefix_end], check_exact=True)
                for actual_array, expected_array in zip(sign_schedule(prefix_signs.to_numpy()), sign_schedule(signs.loc[:prefix_end].to_numpy())):
                    np.testing.assert_array_equal(actual_array, expected_array)
                prefix_data = prepare(limited_one, prefix, symbol, session)
                np.testing.assert_array_equal(prefix_data["positions"], data["positions"][:len(limited_one)])
                poisoned = build_features(poison_future(one, 1, cutoff), poison_future(five, 5, cutoff), None, tick, end)
                pd.testing.assert_frame_equal(poisoned.loc[:prefix_end], expected, check_exact=False, rtol=1e-12, atol=1e-12)
                poisoned_signs = get_signals(poisoned, poisoned, 9, 0.75)
                pd.testing.assert_series_equal(poisoned_signs.loc[:prefix_end], signs.loc[:prefix_end], check_exact=True)
                cuts.append(dict(セッション=session, 銘柄=symbol, 判断時刻=str(cutoff),
                                 使用可能な最終１分足開始=str(limited_one.index[-1]),
                                 使用可能な最終５分足開始=str(limited_five.index[-1]),
                                 比較行数=len(prefix), 特徴列数=len(prefix.columns), 元足打切り一致=True,
                                 未来改変後も一致=True, 方向一致=True, 注文参照位置一致=True))
            cells.append(dict(セッション=session, 銘柄=symbol, 特徴行数=len(full),
                              元１分足数=len(one), 元５分足数=len(five), 独立逐次ATR最大絶対誤差=maximum_error,
                              独立逐次方向一致=True, 注文参照時刻件数=int(usable_positions.sum()),
                              逐次確定足入力件数=input_count, 打切り検証時刻数=len(cut_times(one, five, end))))
            print(f"{session} {symbol}: 元足打切り・未来改変・逐次ATR/方向の一致を確認", flush=True)

    # ----------------------------------------
    # 監査の射程と過去データでの条件選択の限界を結果と一緒に保存する。
    result = dict(
        合否="合格", 現在API取得=False, 原本変更=False, 保存足照合=file_checks,
        対象="手法①のATR・価格CUSUM・新規注文への参照時刻。利益保護候補も同じ入口を使用。",
        機械学習="推論・学習・LSTMを使用しない決定的な逐次計算。価格CUSUMは状態更新である。",
        時刻規則={"１分足": "開始+１分に確定・参照可能", "５分足": "開始+５分に確定・参照可能",
                  "特徴の行時刻": "１分足開始時刻。ATRの５分足開始+４分配置は当該１分足終了時に利用可能という表現。",
                  "注文判断": "開始時刻tの約定再生はt-２分の特徴行を参照。その行の確定時刻はt-１分。"},
        比較仕様={"元足打切り": "各判断時刻で未確定の１分・５分足を除去して全特徴を再構築。事前計算特徴の切断ではない。",
                  "未来改変": "未確定足の全OHLCを７倍+123456、出来高を31倍+98765へ変更して全期間再計算。",
                  "独立逐次": "１分ごとに到着済み足だけ処理し、ATR状態とCUSUMの正負累積・方向状態を保持。",
                  "ATR許容誤差": "絶対1e-12・相対1e-12。方向は完全一致。",
                  "未来削除と改変の監査時刻数": len(cuts), "特徴比較総行数": sum(row["比較行数"] for row in cuts),
                  "逐次比較総行数": sum(row["特徴行数"] for row in cells)},
        ラベル監査={"ATR方向の入力": "１分OHLCV・５分OHLC・呼値・セッション開始経過・観測欠損状態のみ。",
                    "未来波ラベル": "build_features→get_signalsの手法９→sign_schedule→prepareの経路へ入力されていない。",
                    "出口": "固定倍率と保有後の確定足極値による。実行可能性の判定は全再エントリー方式を対象とし、元12入口固定anchorsは事後診断として区別する。",
                    "探索バイアス": "合格は時間方向の情報漏洩がないことを示す。全データで選んだ倍率や手法の将来収益性を証明しない。"},
        限界=["保存CSVは確定足の最終値である。当時の配信遅延や事後訂正が無かったことまではこの監査だけでは保証できない。",
              "本監査は保存５セッションの手法①と同じ価格入口が対象。全24系統・生板特徴を一括で合格とはしていない。",
              "価格の未来を確実に当てる証明ではない。新規の未使用期間にルールを凍結して前進検証する必要がある。"],
        各セッション=cells, 全打切り検査=cuts,
        監査コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        対象コードSHA256={str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in (V4 / "signals.py", V4 / "engine.py")},
    )
    (OUT / "因果性監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# 元足からの因果性監査", "", "**判定: 合格。** ATRと価格CUSUMは、当時までに確定した足だけで逐次計算でき、LSTMは不要。", "",
             f"保存済み20足をハッシュ照合し、両銘柄５セッション・{len(cuts)}時刻で未来足を削除して特徴を再構築した。全特徴、方向、連続方向回数、注文の参照位置が一致した。",
             "同じ時刻で未来の未確定足のOHLCと出来高を大幅に書き換えても、過去の特徴と方向は変わらなかった。APIの取得と原本変更は行っていない。", "",
             "| セッション | 銘柄 | 逐次照合行数 | 打切り時刻数 | ATR最大絶対誤差 |", "|---|---|---:|---:|---:|"]
    lines.extend(f"| {row['セッション']} | {row['銘柄']} | {row['特徴行数']} | {row['打切り検証時刻数']} | {row['独立逐次ATR最大絶対誤差']:.3g} |" for row in cells)
    lines += ["", "１分足は開始+１分、５分足は開始+５分で初めて使用。注文はさらに１分の余裕を取り、開始時刻tにt-２分の特徴行（t-１分に確定）を参照する。",
              "ATRは12期間EWMA、３本の５分足から出力し、２呼値の下限を適用する。CUSUMは正負累積、直前終値、方向を持つだけの状態更新である。", "",
              "将来確定する波ラベルは、検証した入口の計算経路へ入っていない。出口の元12入口固定比較は、将来の入口時刻を固定する診断であり、運用可能な全再エントリー結果とは分ける。", "",
              "**この合格は、入口の特徴・方向計算に時間方向のカンニングが無いことを確認した結果であり、将来の利益を保証しない。** 条件を全期間から選んだことによる選択バイアスは別問題で、未使用期間に事前固定したルールを検証する必要がある。保存足の配信遅延や事後訂正の有無も別途確認が必要。", "",
              "対象は手法①および同じ入口を使う利益保護候補。全24系統や全生板特徴への合格を意味しない。", "",
              "再現: `python -X utf8 work/wave_v7/audit_causality.py`", "", "詳細は同じフォルダの `因果性監査.json` を参照。"]
    (OUT / "因果性監査.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"因果性監査: {len(cuts)}時刻、{sum(row['特徴行数'] for row in cells)}逐次行を照合して合格", flush=True)


if __name__ == "__main__":
    main()
