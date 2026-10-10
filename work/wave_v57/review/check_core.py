"""補充周期・壁の状態機械・約定評価の独立合成監査。"""

from pathlib import Path
import hashlib
import importlib.util
import json
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE))
import features as f
import signals as s
import engine as e


def snap(bid: float = 100., ask: float = 102., quantity: float = 100., volume: float = 0., turnover: float = 0.) -> f.Snapshot:
    """機能: 完全10段の合成板を作る。

    引数: bid/ask/quantity/volume/turnover(float)。返り値: 板状態(Snapshot)。
    """
    return f.Snapshot(bid, ask, quantity, quantity,
                      {bid-i: quantity for i in range(10)}, {ask+i: quantity for i in range(10)},
                      (bid+ask)/2, volume, turnover)


def episode_checks() -> list:
    """機能: 数量保存、閾値、期限、未知と不連続の状態消去を確認する。

    引数: なし。返り値: 合格項目(list)。
    """
    checks = []
    state = f.ReplenishmentState(1.)
    before = {100.-i: 100. for i in range(10)}
    after = dict(before, **{})
    after[100.] = 50.
    assert not state.process_side(before, after, 1, 100., 1, 1., 1)
    recovery = after.copy(); recovery[100.] = 89.
    assert not state.process_side(after, recovery, 1, 50., 2, 2., 2)
    complete = recovery.copy(); complete[100.] = 90.
    result = state.process_side(recovery, complete, 1, 89., 3, 3., 3)
    assert len(result) == 1 and result[0][5] == 40. and result[0][8] == 50. and result[0][9] == 100.
    added = complete.copy(); added[100.] = 300.
    assert not state.process_side(complete, added, 1, 90., 4, 4., 4)
    checks.append('80%境界・開始時最良量固定・完了後の再使用なし')
    # ----------------------------------------
    for later_seq, later_time, should_complete in ((501, 31., True), (502, 31., False), (501, 31.01, False)):
        state = f.ReplenishmentState(1.)
        state.process_side(before, after, 1, 100., 1, 1., 1)
        result = state.process_side(after, before, 1, 50., later_seq, later_time, 2)
        assert bool(result) == should_complete
    state = f.ReplenishmentState(1.)
    little = before.copy(); little[100.] = 80.
    state.process_side(before, little, 1, 100., 1, 1., 1)
    assert not state.process_side(little, before, 1, 80., 2, 2., 2)
    assert state.episodes[1][100.][4] == 20.
    checks.append('30秒500原本行の両期限・25%閾値・回復数量上限')
    # ----------------------------------------
    state = f.ReplenishmentState(1.)
    state.process_side(before, after, 1, 100., 1, 1., 1)
    outside = {120.-i: 100. for i in range(10)}
    assert not state.process_side(after, outside, 1, 50., 2, 2., 2)
    assert 100. not in state.episodes[1]
    state = f.ReplenishmentState(1.)
    old = snap(); dropped = snap(99., 102.)
    state.process_side(old.bid_book, dropped.bid_book, 1, 100., 1, 1., 1)
    result = state.process_side(dropped.bid_book, old.bid_book, 1, 100., 2, 2., 2)
    assert len(result) == 1 and result[0][4] == 100. and result[0][5] == 100.
    checks.append('遠方不明の破棄・最良消失既知0の回復')
    # ----------------------------------------
    for changed, seq, stamp, bit in ((snap(), 3, 2., 2), (snap(), 2, -1., 8), (snap(volume=0.), 2, 2., 16)):
        state = f.ReplenishmentState(1.)
        state.step(snap(volume=10.), 0, 0., 0)
        lower = snap(volume=10.); lower.bid_book[100.] = 50.; lower.bid_qty = 50.
        state.step(lower, 1, 1., 1)
        row, events = state.step(changed, seq, stamp, 2)
        assert row['reset_reason'] & bit and not events and not state.episodes[1]
    state = f.ReplenishmentState(1.)
    state.step(snap(volume=10., turnover=1000.), 0, 0., 0)
    row, _ = state.step(snap(volume=12., turnover=1204.), 1, 1., 1)
    assert row['exec_buy_qty'] == 2. and row['exec_mean_price'] == 102.
    row, _ = state.step(snap(volume=13., turnover=1305.), 2, 2., 2)
    assert row['exec_unknown_qty'] == 1.
    checks.append('原本不連続・時計逆行・出来高リセット・代金平均による代理分類')
    return checks


def frame(n: int = 15) -> dict:
    """機能: 入口規則用の合成原本列を作る。

    引数: n(int)。返り値: 特徴列(dict)。
    """
    return dict(time_s=np.arange(n, dtype=float)+120., seq=np.arange(n),
                bid=np.full(n, 100.), ask=np.full(n, 102.), mid=np.full(n, 101.),
                bid_far=np.full(n, 91.), ask_far=np.full(n, 111.), valid=np.ones(n, bool),
                reset=np.zeros(n, bool), exec_buy_qty=np.zeros(n), exec_sell_qty=np.zeros(n))


def events(rows: list, data: dict) -> np.ndarray:
    """機能: 合成補充完了行を公開列へ変換する。

    引数: rows(list)、data(dict)。返り値: イベント列(ndarray)。
    """
    return np.array([(i, i, data['time_s'][i], side, price, 50., i-1, data['time_s'][i]-1., 50., 100.)
                     for i, side, price in rows], dtype=f.EVENT_DTYPE)


def signal_checks() -> list:
    """機能: 三入口・圧力不足・突破時計・鏡像と未来不変を検査する。

    引数: なし。返り値: 合格項目(list)。
    """
    checks = []
    a = frame(); a['exec_sell_qty'][1] = 10.; a['exec_buy_qty'][5] = 20.
    for col, value in (('bid', 101.), ('ask', 103.), ('mid', 102.)):
        a[col][5:] = value
    ev = events([(2, 1, 100.), (4, 1, 100.), (7, 1, 100.)], a)
    out = s.candidates(a, ev, 2, 1., 0.)
    np.testing.assert_array_equal(out['R1'], [[5., 1., 99., 100.]])
    no_pressure = {k: v.copy() for k, v in a.items()}; no_pressure['exec_sell_qty'][:] = 0.
    assert not len(s.candidates(no_pressure, ev, 2, 1., 0.)['R1'])
    checks.append('R1の圧力と値戻り・初認定時圧力不足の後追い禁止')
    b = frame(); b['exec_buy_qty'][1] = 10.
    b['bid'][5:] = 102.; b['ask'][5:] = 103.; b['mid'][5:] = 102.5
    bev = events([(2, -1, 102.), (4, -1, 102.)], b)
    np.testing.assert_array_equal(s.candidates(b, bev, 2, 1., 0.)['R2'], [[7., 1., 101., 102.]])
    b['bid'][6] = 101.
    np.testing.assert_array_equal(s.candidates(b, bev, 2, 1., 0.)['R2'], [[9., 1., 101., 102.]])
    checks.append('R2の連続2秒・補充後3秒・1行崩れで時計再開始')
    c = frame(); c['bid'][6:] = 101.; c['ask'][6:] = 103.; c['mid'][6:] = 102.
    cev = events([(2, 1, 100.), (4, 1, 100.), (6, 1, 101.), (8, 1, 101.)], c)
    np.testing.assert_array_equal(s.candidates(c, cev, 2, 1., 0.)['R3'], [[8., 1., 100., 101.]])
    checks.append('R3の異価格壁と反対気配の同方向移動')
    # ----------------------------------------
    for data, ev in ((a, ev), (b, bev), (c, cev)):
        full = s.candidates(data, ev, 2, 1., 0.)
        for cut in range(2, len(data['seq'])):
            prefix = s.candidates({k: v[:cut] for k, v in data.items()}, ev[ev['i'] < cut], 2, 1., 0.)
            for family in full:
                np.testing.assert_array_equal(prefix[family], full[family][full[family][:, 0] < cut])
        mirror = {k: v.copy() for k, v in data.items()}
        for dst, src in (('bid', 'ask'), ('ask', 'bid'), ('mid', 'mid'), ('bid_far', 'ask_far'), ('ask_far', 'bid_far')):
            mirror[dst] = 300.-data[src]
        mirror['exec_buy_qty'], mirror['exec_sell_qty'] = data['exec_sell_qty'], data['exec_buy_qty']
        mirrored_events = ev.copy(); mirrored_events['side'] *= -1; mirrored_events['price'] = 300.-ev['price']
        other = s.candidates(mirror, mirrored_events, 2, 1., 0.)
        for family, rows in full.items():
            expected = rows.copy(); expected[:, 1] *= -1; expected[:, 2:] = 300.-expected[:, 2:]
            np.testing.assert_array_equal(other[family], expected)
    checks.append('買い売り完全鏡像・各切断点で将来を参照しない')
    return checks


def engine_checks() -> list:
    """機能: 次原本約定・中値保護線・別価格経路同値と未決済切断を検査する。

    引数: なし。返り値: 合格項目(list)。
    """
    checks = []
    mid = np.array([100., 100., 101., 104., 103., 102., 101., 101.])
    times = np.arange(len(mid), dtype=float)+120.; seqs = np.arange(len(mid))*2
    sig = np.array([[0., 1., 2., 98., 99.]])
    last = mid+np.array([1., -1., 1., -1., 1., -1., 1., -1.])
    orders, legs, groups = e.drive(times, seqs, last, mid, sig, 5, 1000., 1000., True)
    assert orders[0, 3] == seqs[1] and orders[1, 2] == seqs[5] and orders[1, 3] == seqs[6]
    assert legs[0, 6] == (last[6]-last[1])*5000.
    assert groups[0, 7] == 2. and groups[0, 8] == 0.
    for prices in (mid, mid+.5, mid-.5, last+10):
        alternative = e.drive(times, seqs, prices, mid, sig, 5, 1000., 1000., True)
        np.testing.assert_array_equal(alternative[0][:, [0,1,2,3,4,5,6,9,10,11,12]], orders[:, [0,1,2,3,4,5,6,9,10,11,12]])
    # 売買気配の別経路も、予定注文方向による気配を原本列へ設定し、独立再生する。
    executable = mid.copy()
    for order in orders:
        idx = np.where(seqs == order[3])[0][0]
        executable[idx] = mid[idx]+.5*order[5]
    quote_orders, quote_legs, _ = e.drive(times, seqs, executable, mid, sig, 5, 1000., 1000., True)
    assert quote_legs[0, 6] == (mid[6]-.5-(mid[1]+.5))*5000.
    np.testing.assert_array_equal(quote_orders[:, [0,1,2,3,4,5,6,9,10,11,12]], orders[:, [0,1,2,3,4,5,6,9,10,11,12]])
    checks.append('次の有効原本行約定・中値トレール・last/mid/気配で注文経路不変')
    for cut in range(2, len(mid)):
        short = e.drive(times[:cut], seqs[:cut], last[:cut], mid[:cut], sig, 5, 1000., 1000., False)
        np.testing.assert_array_equal(short[0], orders[orders[:, 3] <= seqs[cut-1]])
    # 新規約定行で構造線を跨いでいても、同じ行の架空返済はせず次原本へ予約する。
    crossing = mid.copy(); crossing[1:3] = 97.
    wall_orders, wall_legs, _ = e.drive(times, seqs, last, crossing, sig, 5, 1000., 1000., True)
    assert wall_orders[1, 2] == seqs[1] and wall_orders[1, 3] == seqs[2] and wall_legs[0, 7] == 3
    checks.append('途中切断の注文一致・新規約定時の壁割れを直後行へ返済')
    reflected_sig = sig.copy(); reflected_sig[:, 1] *= -1; reflected_sig[:, 3:] = 300.-reflected_sig[:, 3:]
    reflected = e.drive(times, seqs, 300.-last, 300.-mid, reflected_sig, 5, 1000., 1000., True)
    np.testing.assert_array_equal(reflected[1][:, 6], legs[:, 6])
    checks.append('上下反転の損益対称')
    return checks


def main() -> None:
    """機能: 損益計算前の独立合成監査とコード識別子を保存する。

    引数: なし。返り値: なし(None)。
    """
    report = dict(合格=True, 補充=episode_checks(), 入口=signal_checks(), 売買=engine_checks(),
                  コードSHA256={name: hashlib.sha256((BASE/name).read_bytes()).hexdigest()
                              for name in ('features.py', 'signals.py', 'engine.py')}, 損益結果参照=False)
    (HERE/'独立合成監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
