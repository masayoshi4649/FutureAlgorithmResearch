"""旧核会計接続を、別の単位玉台帳と手計算値で独立に検査する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
sys.path.insert(0, str(TASK))
import baseline131


def reference(path):
    """
    機能: 入力証拠と監査源の指紋を記録する。
    引数: path(Path)はプロジェクト内ファイル。
    返り値: dict[str,str]は位置とＳＨＡ２５６。
    """
    return dict(path=path.relative_to(ROOT).as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def charge(quantity, fee):
    """
    機能: 十進表現による一注文の切捨て料金を独立計算する。
    引数: quantity(int)は枚数、fee(float)は一枚料金。
    返り値: intはその注文の円料金。
    """
    return int((Decimal(str(fee))*quantity).to_integral_value(rounding=ROUND_FLOOR))


def fixture():
    """
    機能: 部分返済・同時両建て・同一原行複数親・異常気配を含む資料を作る。
    引数: なし。
    返り値: tuple[ndarray,...]は時計・買気配・売気配・正常旗・保存注文。
    """
    times = np.arange(14, dtype=float)
    bid = np.array([100., 100., 101., np.nan, 102., 103., 104., np.nan,
                    105., 106., 107., 108., 109., 110.])
    ask = bid+1.
    good = np.isfinite(bid)
    orders = np.array([
        [1, 0, 7, 1, 5, 101., 80, 1],
        [2, 1, 42, -1, 4, 101., 80, 1],
        [4, 2, 7, -1, 2, 102., 70, 0],
        [5, 4, 99, 1, 3, 104., 80, 1],
        [6, 5, 42, 1, 1, 105., 70, 0],
        [8, 6, 7, -1, 3, 105., 70, 0],
        [9, 8, 99, -1, 3, 106., 70, 0],
        [10, 9, 42, 1, 3, 108., 70, 0],
        [11, 10, 77, -1, 2, 108., 80, 1],
        [11, 10, 88, 1, 1, 109., 80, 1],
        [12, 11, 77, 1, 2, 110., 70, 0],
        [13, 12, 88, -1, 1, 110., 93, 0],
    ])
    return times, bid, ask, good, orders


def independent_values(times, bid, ask, qok, orders, multiplier, fee):
    """
    機能: 一枚ずつの建玉簿から各原行の実現額と清算価値を再計算する。
    引数: times/bid/ask/qok/orders(ndarray)、multiplier/fee(float)は人工資料。
    返り値: dictは独立算出したオンライン配列と親損益。
    """
    n = len(times)
    arrays = {name: np.zeros(n) for name in (
        "long_quantity", "short_quantity", "position", "trade_cash", "realized_cash",
        "paid_fees", "estimated_close_fee", "entries_so_far", "liquidation_equity")}
    inventory, parent = {}, {}
    realized, totalfees, entries = 0., 0., 0
    lastbid, lastask = np.nan, np.nan
    for row in range(n):
        if qok[row] and np.isfinite(bid[row]) and np.isfinite(ask[row]) and 0 < bid[row] < ask[row]:
            lastbid, lastask = bid[row], ask[row]
        for order in orders[orders[:, 0] == row]:
            cid, side, qty = int(order[2]), int(order[3]), int(order[4])
            price = order[5]
            paid = charge(qty, fee)
            totalfees += paid
            realized -= paid
            if order[7]:
                inventory[cid] = [(side, price)]*qty
                parent[cid] = {"gross": 0., "fees": paid}
                entries += 1
            else:
                gains = sum(s*(price-p)*multiplier for s, p in inventory[cid][:qty])
                inventory[cid] = inventory[cid][qty:]
                realized += gains
                parent[cid]["gross"] += gains
                parent[cid]["fees"] += paid
        longs = sum(s > 0 for lots in inventory.values() for s, p in lots)
        shorts = sum(s < 0 for lots in inventory.values() for s, p in lots)
        basis = sum(s*p*multiplier for lots in inventory.values() for s, p in lots)
        floating = sum(s*((lastbid if s > 0 else lastask)-p)*multiplier
                       for lots in inventory.values() for s, p in lots)
        estimated = sum(charge(len(lots), fee) for lots in inventory.values())
        values = (longs, shorts, longs-shorts, realized-basis, realized,
                  totalfees, estimated, entries, realized+floating-estimated)
        for name, value in zip(arrays, values):
            arrays[name][row] = value
    nets = {cid: p["gross"]-p["fees"] for cid, p in parent.items()}
    arrays["parents"] = parent
    arrays["parent_nets"] = nets
    return arrays


def check_case(args, multiplier, fee, checks, label):
    """
    機能: 新会計接続を独立台帳へ全行比較する。
    引数: args(tuple)、multiplier/fee(float)、checks(list)、label(str)は人工例。
    返り値: dictは接続実装の結果。検査記録をchecksへ追記する。
    """
    result = baseline131.revalue(*args, multiplier, fee)
    expected = independent_values(*args, multiplier, fee)
    for name in expected:
        if name in ("parents", "parent_nets"):
            continue
        assert np.allclose(result[name], expected[name], rtol=0., atol=1e-7), (label, name)
        checks.append(label+":"+name)
    observed = {p["parent_id"]: p for p in result["parents"]}
    assert set(observed) == set(expected["parents"])
    for cid, values in expected["parents"].items():
        assert observed[cid]["remaining"] == 0
        for name in ("gross", "fees"):
            assert abs(observed[cid][name]-values[name]) < 1e-7, (label, cid, name)
        assert abs(observed[cid]["net"]-expected["parent_nets"][cid]) < 1e-7
    checks.append(label+":親集合と各親の部分返済会計")
    equity = expected["liquidation_equity"]
    peak, drawdown = 0., 0.
    expected_dd = []
    for value in equity:
        peak = max(peak, value)
        drawdown = max(drawdown, peak-value)
        expected_dd.append(drawdown)
    assert np.allclose(result["curve"][:, 3], expected_dd, rtol=0., atol=1e-7)
    assert np.array_equal(result["curve"][:, 4], np.zeros(len(equity)))
    assert result["net"] == sum(expected["parent_nets"].values())
    assert result["profit"] == sum(max(0, v) for v in expected["parent_nets"].values())
    assert result["loss"] == -sum(min(0, v) for v in expected["parent_nets"].values())
    assert result["max_long"] == expected["long_quantity"].max()
    assert result["max_short"] == expected["short_quantity"].max()
    checks.append(label+":最大下落幅・利益損失・両方向上限")
    return result


def rejects(args, multiplier, fee, checks, label):
    """
    機能: 不正保存注文を接続が拒否することを確かめる。
    引数: args(tuple)、multiplier/fee(float)、checks(list)、label(str)は不正人工例。
    返り値: None。拒否されない時はAssertionError。
    """
    try:
        baseline131.revalue(*args, multiplier, fee)
    except (AssertionError, ValueError, OverflowError):
        checks.append(label+":拒否")
        return
    raise AssertionError("拒否されなかった:"+label)


def main():
    """
    機能: 作者と異なる人工台帳で会計接続を監査し、指紋付き証拠を保存する。
    引数: なし。
    返り値: None。旧107商品場は既存作者証拠を参照し金融再生は行わない。
    """
    source_before = reference(TASK / "baseline131.py")
    checks = []
    args = fixture()
    base = check_case(args, 1000., 41.8, checks, "部分返済と両建て")
    hardcoded = {7: 13583., 42: -25333., 99: 5750., 77: -4166., 88: 918.}
    assert {p["parent_id"]: p["net"] for p in base["parents"]} == hardcoded
    assert base["net"] == -9248. and base["fees"] == 1248.
    assert base["long_quantity"][2] == 5 and base["short_quantity"][2] == 4
    assert base["position"][2] == 1
    assert base["liquidation_equity"][3] == base["liquidation_equity"][2]
    assert base["estimated_close_fee"][4] == charge(3, 41.8)+charge(4, 41.8)
    checks += ["親別損益の手計算値", "片側在庫を相殺せず保持", "異常気配で正常値持越し",
               "部分返済後の各親返済手数料丸め"]
    # ----------------------------------------
    # 商品倍率・料金と上下反転は、同じ独立台帳を基準に確認する。
    check_case(args, 10., 11., checks, "日経マイクロ倍率と手数料")
    for fee in (0., .1, .8, 27.5, 38.5, 41.8):
        check_case(args, 10., fee, checks, "料金"+str(fee))
    times, bid, ask, qok, orders = args
    mirrored = orders.copy()
    mirrored[:, 3] *= -1
    mirrored[:, 5] = 1000.-mirrored[:, 5]
    reverse = check_case((times, 1000.-ask, 1000.-bid, qok, mirrored), 1000., 41.8,
                         checks, "上下反転")
    assert np.array_equal(reverse["position"], -base["position"])
    assert np.array_equal(reverse["long_quantity"], base["short_quantity"])
    assert np.array_equal(reverse["short_quantity"], base["long_quantity"])
    assert np.allclose(reverse["liquidation_equity"], base["liquidation_equity"], rtol=0., atol=1e-7)
    checks.append("上下反転で損益同値")
    # ----------------------------------------
    # 未完結prefixは契約外。完結する未来だけを変え、観測時点以前の配列が不変か検査する。
    later_bid, later_ask = bid.copy(), ask.copy()
    later_bid[6:] += 40.
    later_ask[6:] += 40.
    suffix = orders.copy()
    suffix[suffix[:, 0] >= 6, 5] += 40.
    suffix[suffix[:, 2] == 77, 2] = 177
    suffix[suffix[:, 2] == 88, 2] = 188
    extra = np.array([[12., 11., 1000., 1., 1., later_ask[12], 80., 1.],
                      [13., 12., 1000., -1., 1., later_bid[13], 70., 0.]])
    suffix = np.vstack((suffix, extra))
    suffix = suffix[np.argsort(suffix[:, 0], kind="stable")]
    later_times = times.copy()
    later_times[6:] += 100000.
    future = check_case((later_times, later_bid, later_ask, qok, suffix), 1000., 41.8,
                        checks, "未来の価格・時計・新親を変更")
    for name in ("curve", "long_quantity", "short_quantity", "paid_fees", "trade_cash",
                 "realized_cash", "estimated_close_fee", "entries_so_far", "liquidation_equity"):
        assert np.array_equal(future[name][:6], base[name][:6]), name
        checks.append("未来変更の接頭不変:"+name)
    assert future["net"] != base["net"] and future["entries"] == base["entries"]+1
    checks.append("未来変更が事後採点だけに反映")
    # ----------------------------------------
    # 空口座、同時計の後続行、正常旗欠落の持越しも確認する。
    check_case((times, bid, ask, qok, np.zeros((0, 8))), 1000., 41.8, checks, "無注文")
    same_times = np.zeros(len(times))
    check_case((same_times, bid, ask, qok, orders), 1000., 41.8, checks, "同時計の原行順")
    flagged_bid, flagged_ask, flagged = bid.copy(), ask.copy(), qok.copy()
    flagged_bid[3], flagged_ask[3], flagged[3] = 999., 1000., False
    held = check_case((times, flagged_bid, flagged_ask, flagged, orders), 1000., 41.8,
                      checks, "数値だけ正常で正常旗なし")
    assert held["liquidation_equity"][3] == base["liquidation_equity"][3]
    # ----------------------------------------
    # 次正常行・親関係・数量を壊した資料は受け付けない。
    corruptions = [
        ("次正常行を飛ばす", 0, 0, 2.),
        ("売買気配の誤側", 0, 5, 100.),
        ("親を重複新規", 3, 2, 7.),
        ("別親を返済", 2, 2, 42.),
        ("過剰返済", 2, 4, 6.),
        ("小数枚数", 0, 4, 5.5),
        ("判断と同じ原行", 0, 1, 1.),
    ]
    for label, row, col, value in corruptions:
        broken = orders.copy()
        broken[row, col] = value
        rejects((times, bid, ask, qok, broken), 1000., 41.8, checks, label)
    rejects((times, bid, ask, qok, orders[:-1]), 1000., 41.8, checks, "未返済親のまま終了")
    backwards = times.copy()
    backwards[2] = -1
    rejects((backwards, bid, ask, qok, orders), 1000., 41.8, checks, "原時計逆行")
    # ----------------------------------------
    # 旧107商品場は作者の既存証拠を読み、当監査で再生したと誤記しない。
    evidence_path = TASK / "audit/旧核円会計接続の作者人工と107商品場_1792502540335407400.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    assert evidence["passed"]
    assert reference(TASK / "baseline131.py") == source_before
    output = dict(passed=True, financial_replays=0, real_orders=0, market_API=0,
                  check_count=len(checks), checks=checks,
                  source=source_before, checker=reference(Path(__file__).resolve()),
                  author_107_accounts_evidence_reused=reference(evidence_path),
                  hand_calculation_parent_nets=hardcoded,
                  hand_calculation_total_net=-9248., hand_calculation_total_fees=1248.,
                  limitations="parentsと合計損益は事後採点専用。参加判断に使うオンライン配列の接頭だけを未来変更で検査した。途中未返済のordersは現契約の対象外で拒否。",
                  source_unchanged=True)
    target = HERE / ("旧核円会計接続の独立人工_"+str(time.time_ns())+".json")
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n",
                      encoding="utf-8")
    print(target.as_posix(), "独立検査", len(checks), "合格", flush=True)


if __name__ == "__main__":
    main()
