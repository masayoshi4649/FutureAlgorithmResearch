"""階層化した方向信号を、未来情報・方向反射・状態撤回に対して独立に監査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np
import pandas as pd


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / "wave_v23"
sys.path.insert(0, str(HERE))
import hierarchy_signals as SIGNALS


def digest(path: Path) -> str:
    """機能: ソースと原本の不変性を照合する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bars(root: Path, key: tuple, frame: pd.DataFrame) -> None:
    """機能: 作業領域の監査複写にだけ1分足を書き込む。

    引数: root (Path)、key (tuple)、frame (DataFrame)。返り値: なし (None)。
    """
    destination = (root / "candle_1min" / key[1] / f"{key[0]}.csv").resolve()
    if not destination.is_relative_to((HERE / "audit_candles").resolve()):
        raise ValueError("原本への足書込みは禁止です")
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False, encoding="utf-8")


def copied_root(keys: list[tuple], name: str, cutoff: float | None = None, pivots: dict | None = None) -> Path:
    """機能: 未来だけ改変、または価格を反射した監査用足を作る。

    引数: keys (list[tuple])、name (str)、cutoff (float|None)、pivots (dict|None)。
    返り値: set_rootへ渡す作業領域の根 (Path)。
    """
    root = HERE / "audit_candles" / name
    for key in keys:
        frame = pd.read_csv(ROOT / "candle_1min" / key[1] / f"{key[0]}.csv")
        if cutoff is not None:
            release = pd.to_datetime(frame.time).dt.as_unit("ns").astype("int64").to_numpy(float) / 1e9 + 120
            future = release > cutoff
            for column in ("open", "high", "low", "close"):
                frame[column] = frame[column].astype(float)
                frame.loc[future, column] = frame.loc[future, column] * 1.5 + 7000
            frame["volume"] = frame.volume.astype(float)
            frame.loc[future, "volume"] = frame.loc[future, "volume"] * 1000000 + 1000000
            frame.loc[future, "volume_complete"] = True
            frame.loc[future, "closed"] = True
        if pivots is not None:
            pivot = pivots[key]
            high, low = frame.high.copy(), frame.low.copy()
            for column in ("open", "close"):
                frame[column] = 2 * pivot - frame[column]
            frame["high"], frame["low"] = 2 * pivot - low, 2 * pivot - high
        write_bars(root, key, frame)
    return root


def shorter_inputs(inputs: dict, features: dict, cutoff: float) -> tuple[dict, dict]:
    """機能: 原本列と解放特徴を切断して将来情報を除去する。

    引数: inputs/features (dict)、cutoff (float)。返り値: 切断入力と特徴 (tuple[dict,dict])。
    """
    output, frames = {}, {}
    for key, ready in inputs.items():
        count = np.searchsorted(ready["time_s"], cutoff, side="right")
        total = len(ready["seq"])
        output[key] = {name: value[:count].copy() if isinstance(value, np.ndarray) and value.ndim and len(value) == total else value for name, value in ready.items()}
        frame = features[key]
        frames[key] = frame.loc[(frame.time_s <= output[key]["time_s"][-1]) & (frame.seq <= output[key]["seq"][-1])].copy()
    return output, frames


def future_inputs(inputs: dict, features: dict, cutoff: float) -> tuple[dict, dict]:
    """機能: 未来の原本価格・ATR・板値を大きく変え、時刻と行順は保つ。

    引数: inputs/features (dict)、cutoff (float)。返り値: 未来改変入力と特徴 (tuple[dict,dict])。
    """
    output, frames = {}, {}
    for key, ready in inputs.items():
        modified = dict(ready)
        future = ready["time_s"] > cutoff
        for column in ("last", "atr"):
            modified[column] = ready[column].copy()
            modified[column][future] = modified[column][future] * 1.5 + 700
        output[key] = modified
        frame = features[key].copy()
        mask = frame.time_s > cutoff
        for column in frame.select_dtypes(include="number").columns:
            if "seq" in column or "time" in column:
                continue
            frame[column] = frame[column].astype(float)
            frame.loc[mask, column] = frame.loc[mask, column] * 1.5 + 700
        frames[key] = frame
    return output, frames


def mirrored_inputs(inputs: dict, features: dict) -> tuple[dict, dict, dict]:
    """機能: 両市場の価格を初期値で左右反射し、売買側を入れ替える。

    引数: inputs/features (dict)。返り値: 反射入力・反射板特徴・反射基準価格 (tuple[dict,dict,dict])。
    """
    output, frames, pivots = {}, {}, {}
    for key, ready in inputs.items():
        pivot = float(ready["last"][0])
        pivots[key] = pivot
        output[key] = dict(ready, last=2 * pivot - ready["last"])
        frame = features[key].copy()
        for bid, ask in (("bid", "ask"), ("source_bid_last", "source_ask_last")):
            frame[bid], frame[ask] = 2 * pivot - features[key][ask], 2 * pivot - features[key][bid]
        for column in ("mid", "source_mid_last"):
            frame[column] = 2 * pivot - features[key][column]
        for column in ("imb1", "imb5", "imb10", "micro_bias", "ofi_signed", "quote_move_ticks", "dflow_near", "dflow_far", "pressure_near", "pressure_far"):
            if column in frame:
                frame[column] = -features[key][column]
        for first, second in (("bid_qty", "ask_qty"), ("quote_up", "quote_down"), ("added_bid", "added_ask"),
                              ("removed_bid", "removed_ask"), ("trade_pos", "trade_neg"), ("refill_bid", "refill_ask")):
            if first in frame:
                frame[first], frame[second] = features[key][second].copy(), features[key][first].copy()
        frames[key] = frame
    return output, frames, pivots


def logical_checks() -> dict:
    """機能: 主方向の撤回・入口復活禁止・準備と発火・相手遅延の境界を検査する。

    引数: なし。返り値: 機械的状態遷移と遅延の監査結果 (dict)。
    """
    seq = np.arange(5, dtype=np.int64)
    times = np.arange(5, dtype=float)
    output, _, _ = SIGNALS._entry_filter(seq, times, np.array([1, 1, 0, 1, 1], dtype=np.int8),
                                        np.array([0, 4]), np.array([0., 4.]), np.array([1, 1]), np.array([.1, 0.]), np.ones(2), 1, 1.)
    np.testing.assert_array_equal(output, [1, 1, 0, 0, 0])
    output, used, fired = SIGNALS._entry_filter(seq, times, np.array([1, 0, 1, 1, 1], dtype=np.int8),
                                              np.array([0, 4]), np.array([0., 4.]), np.array([1, 1]), np.array([-.2, .1]), np.ones(2), 3, 1.)
    np.testing.assert_array_equal(output, np.zeros(5))
    np.testing.assert_array_equal(fired, np.zeros(2))
    output, used, fired = SIGNALS._entry_filter(seq, times, np.ones(5, dtype=np.int8),
                                              np.array([0, 4]), np.array([0., 4.]), np.array([1, 1]), np.array([-.2, .1]), np.ones(2), 3, 1.)
    np.testing.assert_array_equal(output, [0, 0, 0, 0, 1])
    assert used[1] == 0 and used[1] < 4
    output, _, _ = SIGNALS._entry_filter(np.arange(4), np.array([0., 100., 120., 121.]), np.ones(4, dtype=np.int8),
                                        np.array([0]), np.array([0.]), np.array([1]), np.array([.1]), np.ones(1), 1, 1.)
    np.testing.assert_array_equal(output, [1, 1, 1, 0])
    model = {("検査", "TOPIX"): dict(time_s=np.array([0.]), direction=np.array([1])),
             ("検査", "NK225"): dict(time_s=np.array([0., 100.]), direction=np.array([-1, 1]))}
    for multiplier in (.8, 1., 1.2):
        delay = int(np.floor(60 * multiplier + .5))
        actual = SIGNALS._allowed(("検査", "TOPIX"), np.array([delay - .01, delay, 100 + delay - .01, 100 + delay]),
                                  model, dict(peer_confirm=True, peer_multiplier=multiplier))
        np.testing.assert_array_equal(actual, [0, 0, 0, 1])
    return dict(板イベント間の主方向撤回で入口解除=True, 主方向再開で旧入口は復活しない=True,
                押し戻り準備も撤回で解除=True, 準備と発火は別イベント=True, 入口TTL120秒を原本時刻で解除=True,
                相手60秒と48秒72秒の解放境界を照合=True)


def falling_market() -> tuple[Path, dict, dict]:
    """機能: 両市場で一方向に下がり続ける合成足と板を作業領域に作る。

    引数: なし。返り値: 足参照根・原本入力・解放特徴 (tuple[Path,dict,dict])。
    """
    root = HERE / "audit_candles" / "継続下落"
    start = pd.Timestamp("2026-09-22T09:00:00+09:00").timestamp()
    inputs, features = {}, {}
    for symbol, anchor, step, atr, tick in (("TOPIX", 5000., 1., 2., .5), ("NK225", 70000., 10., 20., 5.)):
        key = ("監査用_継続下落", symbol)
        minute = np.arange(360)
        opening = anchor - minute * step
        closing = opening - step
        bars = pd.DataFrame(dict(time=[pd.Timestamp(start + value * 60, unit="s", tz="UTC").tz_convert("Asia/Tokyo").isoformat() for value in minute],
                                 open=opening, high=opening + .1 * step, low=closing - .1 * step, close=closing,
                                 volume=np.full(360, 100.), volume_complete=True, closed=True))
        write_bars(root, key, bars)
        raw = np.arange(21601)
        times = start + raw
        inputs[key] = dict(time_s=times, seq=raw, last=anchor - raw / 60 * step, atr=np.full(len(raw), atr), tick=tick,
                           start=start, limit=start + 21600, us_open=start + 100000, session=key[0], symbol=symbol)
        release = np.arange(10, 21601, 10)
        midpoint = anchor - (release - 1) / 60 * step
        count = len(release)
        features[key] = pd.DataFrame(dict(time_s=start + release, seq=release, source_time_s=start + release - 1,
                                         source_last_seq=release - 1, source_mid_last=midpoint, bid_qty=np.full(count, 100.), ask_qty=np.full(count, 200.),
                                         ofi_signed=np.full(count, -10.), ofi_abs=np.full(count, 10.), quote_up=np.zeros(count), quote_down=np.ones(count),
                                         imb5=np.full(count, -.3), micro_bias=np.full(count, -.15), trade_pos=np.zeros(count), trade_neg=np.ones(count),
                                         raw_event_count=np.ones(count)))
    return root, inputs, features


def volume_checks(inputs: dict) -> dict:
    """機能: VWAPがその時点までに解放した出来高完全な足だけの累積か検算する。

    引数: inputs (dict)。返り値: VWAP独立計算の一致件数 (dict)。
    """
    count, ignored = 0, 0
    for key, ready in inputs.items():
        source = pd.read_csv(ROOT / "candle_1min" / key[1] / f"{key[0]}.csv")
        times = pd.to_datetime(source.time).dt.as_unit("ns").astype("int64").to_numpy(float) / 1e9 + 120
        chosen = source.closed.astype(str).str.lower().eq("true").to_numpy(copy=True)
        chosen &= (times >= ready["start"] + 120) & (times <= ready["time_s"][-1])
        source = source.loc[chosen]
        complete = source.volume_complete.astype(str).str.lower().eq("true").to_numpy()
        numerator, denominator = 0., 0.
        expected = []
        for index, (_, row) in enumerate(source.iterrows()):
            volume = max(0., float(row.volume)) if complete[index] else 0.
            numerator += (float(row.high) + float(row.low) + float(row.close)) / 3 * volume
            denominator += volume
            expected.append(numerator / denominator if denominator else np.nan)
        bars = SIGNALS.LEGACY._bars(ready)
        np.testing.assert_allclose(bars["vwap"], expected, atol=1e-9, rtol=1e-12, equal_nan=True)
        count += len(expected)
        ignored += int(np.count_nonzero(~complete))
    return dict(累積VWAP独立一致足数=count, 不完全出来高を重み0にした足数=ignored)


def main() -> None:
    """機能: 全96条件の方向・状態遷移・未来非参照・左右対称性を監査し保存する。

    引数: なし。返り値: なし (None)。損益と現在APIを扱わない。
    """
    started = time.perf_counter()
    inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    features = pickle.loads((OLD / "features_depth.pkl").read_bytes())
    specs = SIGNALS.catalog()
    paths = [HERE / "hierarchy_signals.py", HERE / "hierarchy_design_fixed.json", OLD / "signals.py"]
    paths += [ROOT / "candle_1min" / key[1] / f"{key[0]}.csv" for key in inputs]
    hashes = {str(path): digest(path) for path in paths}
    SIGNALS.set_root(ROOT)
    logic = logical_checks()
    volume = volume_checks(inputs)
    original_count, only_count, seen, duplicate = 0, 0, {}, []
    for spec in specs:
        direction = SIGNALS.build(spec, inputs, features)
        main_direction = SIGNALS.main_directions(spec, inputs)
        hasher = hashlib.sha256()
        for key, values in sorted(direction.items()):
            assert len(values) == len(inputs[key]["seq"]) and values.dtype == np.int8 and np.isin(values, [-1, 0, 1]).all()
            assert np.all((values == 0) | (values == main_direction[key]))
            if spec["params"]["entry_kind"] == "direction":
                np.testing.assert_array_equal(values, main_direction[key])
                only_count += 1
            original_count += 1
            hasher.update(repr(key).encode("utf-8"))
            hasher.update(values.tobytes())
        fingerprint = hasher.hexdigest()
        if fingerprint in seen:
            duplicate.append(dict(id=spec["id"], same_as=seen[fingerprint]))
        else:
            seen[fingerprint] = spec["id"]
    print(f"全96条件×26入力を生成。主方向のみ{only_count}比較が一致", flush=True)

    # ----------------------------------------
    # 足原本を変更せず、未来OHLC/出来高と原本・板の将来部分を同時に改変する。
    indices = [main * 16 + time_scale * 8 + entry * 2 + ((main + time_scale + entry) % 2)
               for main in range(6) for time_scale in range(2) for entry in range(4)]
    cases = [specs[index] for index in indices]
    for main in range(6):
        parent = specs[main * 16 + 5]
        cases.extend(item for item in SIGNALS.neighbor_specs(parent) if item["applied"])
    prefix_count, future_count, mirror_count, compared = 0, 0, 0, 0
    sessions = ("2026-09-22_Night", "2026-09-29_Day")
    for session in sessions:
        pair = {key: value for key, value in inputs.items() if key[0] == session}
        frames = {key: features[key] for key in pair}
        SIGNALS.set_root(ROOT)
        full = {case["id"]: SIGNALS.build(case, pair, frames) for case in cases}
        start = max(value["time_s"][0] for value in pair.values())
        end = min(value["time_s"][-1] for value in pair.values())
        for fraction in (.27, .63):
            cutoff = float(np.floor((start + (end - start) * fraction) / 60) * 60)
            short, short_frames = shorter_inputs(pair, frames, cutoff)
            SIGNALS.set_root(ROOT)
            for case in cases:
                partial = SIGNALS.build(case, short, short_frames)
                for key in pair:
                    count = len(short[key]["seq"])
                    np.testing.assert_array_equal(full[case["id"]][key][:count], partial[key], err_msg=f"prefix {case['id']}/{key}")
                    prefix_count += 1
                    compared += count
            changed, changed_frames = future_inputs(pair, frames, cutoff)
            future_root = copied_root(list(pair), f"未来改変_{session}_{int(fraction * 100)}", cutoff=cutoff)
            SIGNALS.set_root(future_root)
            for case in cases:
                modified = SIGNALS.build(case, changed, changed_frames)
                for key in pair:
                    count = len(short[key]["seq"])
                    np.testing.assert_array_equal(full[case["id"]][key][:count], modified[key][:count], err_msg=f"future {case['id']}/{key}")
                    future_count += 1
                    compared += count
        SIGNALS.set_root(ROOT)
        all_original = {case["id"]: SIGNALS.build(case, pair, frames) for case in specs}
        mirrored, mirrored_frames, pivots = mirrored_inputs(pair, frames)
        mirror_root = copied_root(list(pair), f"価格反射_{session}", pivots=pivots)
        SIGNALS.set_root(mirror_root)
        for case in specs:
            reflected = SIGNALS.build(case, mirrored, mirrored_frames)
            for key in pair:
                np.testing.assert_array_equal(-all_original[case["id"]][key], reflected[key], err_msg=f"mirror {case['id']}/{key}")
                mirror_count += 1
        print(f"{session}: 未来削除・未来値改変・売買反射が一致", flush=True)

    # ----------------------------------------
    # 継続下落で主方向を買いへ固定する誤りと、短期条件の未発火を区別する。
    down_root, down_inputs, down_features = falling_market()
    SIGNALS.set_root(down_root)
    down_count = 0
    for spec in specs:
        output = SIGNALS.build(spec, down_inputs, down_features)
        for key, values in output.items():
            assert not (values > 0).any(), f"継続下落なのに買い: {spec['id']}/{key}"
            if spec["params"]["entry_kind"] != "pullback_resume":
                assert (values < 0).any(), f"継続下落の売りを全く出せない: {spec['id']}/{key}"
            down_count += 1
    SIGNALS.set_root(ROOT)
    assert hashes == {str(path): digest(path) for path in paths}
    report = dict(条件数=96, 新損益閲覧計算=False, API取得数=0, 全入力生成件数=original_count,
                  主方向のみの同値件数=only_count, 全入口は主方向に従う=True, 一意方向数=len(seen), 重複方向=duplicate,
                  状態論理検査=logic, 出来高VWAP検査=volume, prefix比較数=prefix_count, 未来改変比較数=future_count,
                  prefix未来の比較方向要素=compared, 価格と板の左右反射一致数=mirror_count, 継続下落検査件数=down_count,
                  原本と凍結候補コード不変=True, SHA256=hashes, 実行秒=round(time.perf_counter() - started, 3),
                  制約=["内部では中期方向と短期入口を分離するが、管理器へ渡るのは最終入口方向1列。主方向専用の退出入力は渡していない。",
                      "signal_exitとneutral管理は最終入口方向で反応する。主方向反転時に反対入口が未成立なら、即時反転退出を保証しない。",
                      "VWAPは当該セッションの累積。市場参加者の建玉や注文意図を推定していない。",
                      "CurrentPriceTimeは受信時刻ではなく、記録に対する因果性と実受信順は別である。"])
    (HERE / "hierarchy_signal_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# v27 方向信号の独立監査", "", "新しい損益を読まず、未来除去・未来価格/出来高改変・方向反射・継続下落を検査した。実装と原本の不変性も照合した。", "",
             f"- 96条件×26入力、{original_count}方向列を生成。主方向だけの24条件は{only_count}入力で入口前の方向と一致。",
             f"- 全6主方向・両時間倍率・全4入口を含む条件と有効近傍で、prefix {prefix_count}比較、未来改変 {future_count}比較が一致。未来足のOHLCと出来高100万倍も過去を変えない。",
             f"- 実データの価格と買い/売りの板を反射し、全96条件の{mirror_count}入力で方向が完全反転。",
             f"- 継続下落の{down_count}入力で買いは一度も出ない。主方向/短期順行/OFI順行は売りを出し、逆行後再開条件は逆行がないので入らなくても矛盾ではない。",
             "- 主方向撤回は板の次更新を待たず原本行で入口を解除。主方向が同じ側へ戻っても古い入口や押し戻り準備は復活しない。",
             "- 相手確認は公開時刻＋60秒。48/72秒の近傍も、境界の直前と同時刻で確認。", "", "## 設計の限界", ""]
    lines += [f"- {item}" for item in report["制約"]]
    (HERE / "hierarchy_signal_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("prefix比較数", "未来改変比較数", "価格と板の左右反射一致数", "継続下落検査件数", "実行秒")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
