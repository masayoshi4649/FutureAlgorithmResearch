"""ティックIFDエンジンを人工経路と将来改変で独立検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import numba
import numpy as np

from child_oracle import first_child_decision, following_fill
from independent_account import reconstruct, fee, save


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
numba.config.CACHE_DIR = str(HERE / "numba_cache")
SPEC = importlib.util.spec_from_file_location("tick69_independent_audit_engine", WORK / "engine.py")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)


def run(bids: np.ndarray, asks: np.ndarray | None = None, times: np.ndarray | None = None,
    side: int = 1, signal: np.ndarray | None = None, reset: np.ndarray | None = None,
    **changes: object) -> tuple:
    """機能: 独立監査専用の固定設定で人工経路を被検査エンジンへ与える。

    引数: bids/asks/times/signal/reset(np.ndarray)、side(int)、changes(dict)。
    返り値: 注文、決済、曲線、統計、原本、設定(tuple)。
    """
    n = len(bids)
    asks = bids + 1 if asks is None else asks
    times = 300 + np.arange(n, dtype=float) if times is None else times
    signal = np.concatenate(([side], np.zeros(n-1, dtype=np.int8))) if signal is None else signal
    reset = np.zeros(n, dtype=bool) if reset is None else reset
    parameters = dict(tick=1., start=0., limit=2000., quantity=5, value=1000., fee_unit=41.8,
        entry_type=0, entry_width=2., initial_stop=8., activation=4., trail_width=4.,
        hold_seconds=1000., parent_ttl=120., cooldown=30.)
    parameters.update(changes)
    result = ENGINE.simulate(times, bids, asks, signal, reset, **parameters)
    data = dict(bid=bids, ask=asks, last=(bids+asks)/2, time_s=times, seq=np.arange(n))
    return (*result, data, parameters)


def check_closed(result: tuple, symbol: str = "TOPIX") -> dict:
    """機能: 人工経路の注文・料金・FIFO曲線を別会計器に照合する。

    引数: result(tuple)、symbol(str)。返り値: 独立会計指標(dict)。
    """
    orders, trades, curve, counters, data, parameters = result
    assert counters[0] == 0
    ledger = dict(symbol=symbol, session="人工", orders=orders,
        fees=[fee(symbol, int(o[4])) for o in orders])
    account, other = reconstruct(data, ledger)
    np.testing.assert_array_equal(other, curve)
    expected = np.asarray([[t["campaign"], t["entry_row"], t["exit_row"], t["side"], t["quantity"],
        t["entry"], t["exit"], fee(symbol, t["quantity"]), fee(symbol, t["quantity"]), t["gross"], t["net"]]
        for t in account["details"]], dtype=float).reshape((-1, 11))
    np.testing.assert_array_equal(expected, trades)
    return account


def synthetic() -> list[dict]:
    """機能: 子作成順序・気配往復・OCO・各期限・gap・無効気配を人工経路で検査する。

    引数: なし。返り値: 合格した経路の記録(list[dict])。
    """
    records = []
    path = np.array([100., 100., 89., 100., 105., 109., 105., 100., 100., 100.])
    original = run(path)
    orders, trades, curve, counters, data, parameters = original
    assert orders[0, 0] == 2 and orders[0, 1] == 1 and orders[0, 5] == 90
    expected = first_child_decision(data["time_s"], data["bid"], data["ask"], np.ones(len(path), bool),
        2, 1, 101., 8., 4., 4., 1000., 1940.)
    assert expected == (6, 2)
    assert orders[1, 1] == expected[0] and orders[1, 0] == following_fill(np.ones(len(path), bool), expected[0])
    assert orders[1, 6] == expected[1]
    account = check_closed(original)
    records.append(dict(経路="新規約定当行の急落を先取りせず、開始幅一致とトレール一致", 収支=account["net"]))

    # ----------------------------------------
    # 買いと売り、bidとaskを反射して同じ経路・損益となることを確認する。
    reflection = run(300.-data["ask"], 300.-data["bid"], side=-1)
    other = check_closed(reflection)
    assert other["net"] == account["net"]
    np.testing.assert_array_equal(original[0][:, :3], reflection[0][:, :3])
    np.testing.assert_array_equal(original[2], reflection[2])
    records.append(dict(経路="ロング／ショート反射", 収支=other["net"]))

    gap = np.array([100., 100., 100., 104., 108., 91., 89., 89., 89., 89.])
    stopped = run(gap)
    assert stopped[0][1, 1] == 5 and stopped[0][1, 0] == 6 and stopped[0][1, 6] == 1
    assert stopped[0][1, 5] == 89
    result = check_closed(stopped)
    records.append(dict(経路="同時stop／trailはstop優先、停止線を飛び越えた次行で約定", 収支=result["net"]))

    invalid_bid = gap.copy()
    invalid_ask = gap+1
    invalid_bid[6] = np.nan
    invalid_ask[6] = np.nan
    delayed = run(invalid_bid, invalid_ask)
    assert delayed[0][1, 1] == 5 and delayed[0][1, 0] == 7
    result = check_closed(delayed)
    records.append(dict(経路="条件成立を固定し、無効気配は最後の有効気配で評価・次有効行へ約定遅延", 収支=result["net"]))

    pure = run(np.array([100., 100., 100., 101., 105., 104., 101., 100., 100., 100.]), initial_stop=0., activation=0.)
    assert pure[0][1, 1] == 6 and pure[0][1, 6] == 2
    records.append(dict(経路="IFD純トレールの開始と追従一致", 収支=check_closed(pure)["net"]))

    flat = run(np.full(12, 100.), initial_stop=0., activation=0., hold_seconds=3.)
    assert flat[0][1, 1] == 5 and flat[0][1, 0] == 6 and flat[0][1, 6] == 3
    result = check_closed(flat)
    assert result["net"] == -5418
    records.append(dict(経路="中値不変の板往復でもスプレッド・料金を支払い、保有期限で返済", 収支=result["net"]))

    session = run(np.full(7, 100.), times=np.array([300., 302., 305., 637., 639., 640., 642.]), limit=700.)
    assert session[0][1, 1] == 5 and session[0][1, 0] == 6 and session[0][1, 6] == 4
    records.append(dict(経路="既知の場内終了時計で返済", 収支=check_closed(session)["net"]))

    trailing = run(np.array([100., 100., 96., 97., 98., 105., 100., 105., 101., 100., 100.]), entry_type=1)
    assert trailing[0][0, 1] == 4 and trailing[0][0, 0] == 5
    assert trailing[0][0, 5] == 106
    assert trailing[0][1, 1] == 8 and trailing[0][1, 6] == 2
    records.append(dict(経路="親トレールは次観測から初期化、子の絶対価格は親約定gapで移動しない", 収支=check_closed(trailing)["net"]))

    timed_out = run(np.full(5, 100.), times=np.array([300., 301., 419., 420., 421.]), entry_type=1)
    assert len(timed_out[0]) == 0 and timed_out[3][5] == 1
    check_closed(timed_out)
    records.append(dict(経路="親TTL120秒一致で未成立予約取消", 収支=0))

    reset = np.zeros(8, bool)
    reset[1] = True
    canceled = run(np.full(8, 100.), reset=reset)
    assert len(canceled[0]) == 0 and canceled[3][5] == 1
    check_closed(canceled)
    records.append(dict(経路="品質resetで未成立親のみ取消", 収支=0))

    same_time = run(path, times=np.full(len(path), 300.))
    np.testing.assert_array_equal(same_time[0], original[0])
    np.testing.assert_array_equal(same_time[2], original[2])
    check_closed(same_time)
    records.append(dict(経路="同秒原本を順序通り別のPUSHとして処理", 収支=account["net"]))

    micro = run(path, quantity=10, value=10., fee_unit=11.)
    records.append(dict(経路="日経マイクロ枚数・倍率・両側料金", 収支=check_closed(micro, "NK225")["net"]))
    return records


def causality() -> list[dict]:
    """機能: 人工ランダム経路の将来変更と途中切断で約定・曲線が不変か確認する。

    引数: なし。返り値: 合格した条件の記録(list[dict])。
    """
    random = np.random.default_rng(69)
    records = []
    for entry_type in (0, 1):
        for child in ((0., 0., 4.), (8., 4., 4.), (16., 8., 8.), (8., 4., 2.)):
            for hold in (5., 30., 60.):
                n = 140
                bid = 1000.+np.cumsum(random.integers(-4, 5, n)).astype(float)
                ask = bid+random.integers(1, 4, n)
                signal = np.zeros(n, dtype=np.int8)
                signal[::5] = random.choice(np.array([-1, 1], dtype=np.int8), len(signal[::5]))
                reset = np.zeros(n, dtype=bool)
                config = dict(entry_type=entry_type, initial_stop=child[0], activation=child[1],
                    trail_width=child[2], hold_seconds=hold)
                normal = run(bid, ask, signal=signal, reset=reset, **config)
                for cut in (27, 58, 93):
                    prefix = run(bid[:cut], ask[:cut], signal=signal[:cut], reset=reset[:cut], **config)
                    np.testing.assert_array_equal(normal[0][normal[0][:, 0] < cut], prefix[0])
                    np.testing.assert_array_equal(normal[1][normal[1][:, 2] < cut], prefix[1])
                    np.testing.assert_array_equal(normal[2][:cut], prefix[2])
                    changed_bid, changed_ask, changed_signal, changed_reset = bid.copy(), ask.copy(), signal.copy(), reset.copy()
                    changed_bid[cut:] = 1200.+np.arange(n-cut)*3
                    changed_ask[cut:] = changed_bid[cut:]+9
                    changed_signal[cut:] *= -1
                    changed_reset[cut:] = True
                    changed = run(changed_bid, changed_ask, signal=changed_signal, reset=changed_reset, **config)
                    np.testing.assert_array_equal(normal[0][normal[0][:, 0] < cut], changed[0][changed[0][:, 0] < cut])
                    np.testing.assert_array_equal(normal[1][normal[1][:, 2] < cut], changed[1][changed[1][:, 2] < cut])
                    np.testing.assert_array_equal(normal[2][:cut], changed[2][:cut])
                records.append(dict(親=entry_type, 子=list(child), 保有秒=hold, 途中切断と未来変更=3))
    return records


def main() -> None:
    """機能: 人工経路と全24出口親条件の因果検査を実行し監査結果を保存する。

    引数: なし。返り値: なし(None)。
    """
    cases = synthetic()
    prefix = causality()
    paths = [WORK/"engine.py", Path(__file__), HERE/"child_oracle.py", HERE/"independent_account.py"]
    save(HERE/"人工経路と因果検査.json", dict(合格=True, 人工経路数=len(cases), 人工経路=cases,
        親出口保有条件数=len(prefix), 因果検査=prefix,
        SHA256={str(p.relative_to(WORK)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))
    print("人工経路", len(cases), "条件別途中切断・将来改変", len(prefix), "合格", flush=True)


if __name__ == "__main__":
    main()
