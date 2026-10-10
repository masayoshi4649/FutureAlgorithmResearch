"""候補行の入口確認を、イベント一覧と直接区間和から独立に検算する。"""

from __future__ import annotations

import numpy as np

from audit_all import read, material, ROOT, WORK, HERE
from independent_account import save


def reference_events(feature: dict, tick: float) -> tuple[dict, np.ndarray, np.ndarray]:
    """機能: 無効・reset・時計空白で区切った中値変更イベントを作る。

    引数: feature(dict)、tick(float)。返り値: 区間別原本行・有効判定・区間番号(tuple)。
    """
    times, bid, ask, mid = [np.asarray(feature[name]) for name in ("time_s", "bid", "ask", "mid")]
    good = feature["valid"] & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid) & (ask - bid <= 2 * tick + 1.e-9)
    diff = np.concatenate(([0.], np.diff(times)))
    clear = feature["reset"] | ~good | (diff < 0) | (diff > 120.)
    regime = np.cumsum(clear)
    preceding_good = np.concatenate(([False], good[:-1]))
    preceding_mid = np.concatenate(([np.nan], mid[:-1]))
    events = np.flatnonzero(good & (clear | ~preceding_good | (mid != preceding_mid)))
    changes = np.flatnonzero(np.diff(regime[events])) + 1 if len(events) else np.empty(0, int)
    return {int(regime[part[0]]): part for part in np.split(events, changes) if len(part)}, good, regime


def own_at(feature: dict, tick: float, row: int, side: int, events: dict,
    good: np.ndarray, regime: np.ndarray) -> tuple:
    """機能: 一候補の四・十六イベント確認を生区間の価格とOFIから算出する。

    引数: feature(dict)、tick(float)、row/side(int)、events(dict)、good/regime(ndarray)。
    返り値: 参照4行・参照16行・効率・OFI比・G1・G2(tuple)。
    """
    if not good[row]:
        return -1, -1, np.nan, np.nan, False, False
    series = events[int(regime[row])]
    end = np.searchsorted(series, row, side="right")
    history = series[max(0, end-17):end]
    times, bid, ask, mid = [feature[name] for name in ("time_s", "bid", "ask", "mid")]
    r4 = r16 = -1
    efficient = flow_ratio = np.nan
    one = two = False
    if len(history) >= 5 and times[row] - times[history[-5]] <= 120:
        r4 = int(history[-5])
        one = side * (bid[row] - bid[r4]) >= tick - 1.e-9 and side * (ask[row] - ask[r4]) >= tick - 1.e-9
    if len(history) == 17 and times[row] - times[history[0]] <= 120:
        r16 = int(history[0])
        length = float(np.abs(np.diff(mid[history])).sum())
        change = mid[row] - mid[r16]
        efficient = abs(change) / length if length > 0 else 0.
        interval = feature["best_ofi"][r16+1:row+1]
        if np.all(np.isfinite(interval)):
            denominator = float(np.abs(interval).sum())
            if denominator > 0:
                flow_ratio = float(interval.sum()) / denominator
                two = one and side * change >= 2 * tick - 1.e-9 and efficient >= .30 - 1.e-12 and side * flow_ratio >= .10 - 1.e-12
    return r4, r16, efficient, flow_ratio, one, two


def peer_at(peer: dict, tick: float, target: float) -> tuple:
    """機能: 同時刻先頭の相手引用と三十秒区間確認を直接検索する。

    引数: peer(dict)、tick/target(float)。返り値: 先頭・末尾・前端行・OFI比・買売許可(tuple)。
    """
    times = peer["time_s"]
    last = int(np.searchsorted(times, target - 1., side="right") - 1)
    if last < 0:
        return -1, -1, -1, np.nan, False, False
    selected = int(np.searchsorted(times, times[last], side="left"))
    old = -1
    ratio = np.nan
    if target - times[selected] > 5 + 1.e-9:
        return selected, last, old, ratio, False, False
    before = int(np.searchsorted(times, times[selected] - 30., side="right") - 1)
    if before < 0:
        return selected, last, old, ratio, False, False
    old = int(np.searchsorted(times, times[before], side="left"))
    if times[selected] - 30. - times[old] > 5 + 1.e-9:
        return selected, last, old, ratio, False, False
    interval = slice(old, selected + 1)
    if np.any(~peer["valid"][interval]) or np.any(peer["reset"][interval]) or np.any(~np.isfinite(peer["best_ofi"][interval])):
        return selected, last, old, ratio, False, False
    flow = peer["best_ofi"][old+1:selected+1]
    denominator = float(np.abs(flow).sum())
    if denominator <= 0:
        return selected, last, old, ratio, False, False
    ratio = float(flow.sum()) / denominator
    buy = peer["bid"][selected] - peer["bid"][old] >= tick - 1.e-9 and peer["ask"][selected] - peer["ask"][old] >= tick - 1.e-9 and ratio >= .05 - 1.e-12
    sell = peer["bid"][old] - peer["bid"][selected] >= tick - 1.e-9 and peer["ask"][old] - peer["ask"][selected] >= tick - 1.e-9 and -ratio >= .05 - 1.e-12
    return selected, last, old, ratio, buy, sell


def near_nan(expected: float, actual: float) -> None:
    """機能: 欠測を含む根拠実数を独立計算へ照合する。

    引数: expected/actual(float)。返り値: なし(None)。
    """
    if np.isnan(expected):
        assert np.isnan(actual)
    else:
        assert abs(expected - actual) < 1.e-10, (expected, actual)


def main() -> None:
    """機能: 全候補の根拠と入口許可を別計算し、G0一致と同期限界も保存する。

    引数: なし。返り値: なし(None)。
    """
    ready, features = material()
    signals = read(WORK / "inputs/signals.pkl")
    traces = read(WORK / "inputs/trace.pkl")
    schedules = read(WORK / "inputs/schedule.pkl")
    old_signals = read(ROOT / "work/wave_v70/inputs/signals.pkl")
    old_schedules = read(ROOT / "work/wave_v70/inputs/schedule.pkl")
    records = []
    for key in sorted(ready):
        peer_key = (key[0], "NK225" if key[1] == "TOPIX" else "TOPIX")
        f, pf = features[key], features[peer_key]
        events, good, regime = reference_events(f, ready[key]["tick"])
        cache = {}
        counts = [0, 0, 0, 0]
        ambiguity = 0
        for source in range(6):
            trace = traces[key][source]
            base = signals[key][source * 4]
            rows = np.flatnonzero(base)
            np.testing.assert_array_equal(rows, trace[:, 0].astype(int))
            np.testing.assert_array_equal(base[rows], trace[:, 1])
            for evidence in trace:
                row, side = int(evidence[0]), int(evidence[1])
                own = own_at(f, ready[key]["tick"], row, side, events, good, regime)
                if row not in cache:
                    cache[row] = peer_at(pf, ready[peer_key]["tick"], f["time_s"][row])
                peer = cache[row]
                assert own[0] == int(evidence[2]) and own[1] == int(evidence[3])
                near_nan(own[2], evidence[4])
                near_nan(own[3], evidence[5])
                assert peer[:3] == tuple(int(x) for x in evidence[6:9])
                near_nan(peer[3], evidence[9])
                passes = (True, bool(own[4]), bool(own[5]), bool(own[5] and peer[4 if side == 1 else 5]))
                assert passes[1:] == tuple(bool(x) for x in evidence[10:13])
                for gate, allowed in enumerate(passes):
                    assert signals[key][source * 4 + gate, row] == (side if allowed else 0)
                    counts[gate] += int(allowed)
                ambiguity += int(peer[0] >= 0 and peer[1] > peer[0])
            if key in old_signals:
                np.testing.assert_array_equal(base, old_signals[key][source])
                np.testing.assert_array_equal(schedules[key][source * 4], old_schedules[key][source])
            for gate in range(1, 4):
                assert np.all((signals[key][source * 4 + gate] == 0) | (signals[key][source * 4 + gate] == base))
        records.append(dict(セッション=key[0], 銘柄=key[1], 候補許可数=counts,
            相手同時計に複数更新がある候補数=ambiguity, 候補根拠一致=True, G0旧一致=key in old_signals))
        print(f"入口確認の独立根拠 {key} 合格", flush=True)
    assert len(records) == 58
    save(HERE / "入口確認の独立根拠監査.json", dict(合格=True, 口座数=58,
        独立計算="中値イベント一覧、候補行までの直接 OFI 区間和、相手同時刻先頭の直接検索",
        既知G0旧信号スケジュール一致口座=56, 未来ラベルを参照=False,
        G3限界="代理約定時計上の過去対応。共通受信時計がなく板受信順の完全同期は証明不能、主選定外",
        結果=records))


if __name__ == "__main__":
    main()
