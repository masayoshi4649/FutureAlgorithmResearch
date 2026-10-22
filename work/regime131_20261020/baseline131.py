"""旧核の保存実注文を指紋照合し、意思決定の再生なしに円会計を構成する。"""

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
source_map = {
    "day": {
        "path": "work/visual_pdca129_20261020/day_round2/全条件の会計.json",
        "sha256": "be6f16089e2d718114c89ccc5be6fef407e2a391ed52f0e15754e46f62616e9c",
    },
    "night_base": {
        "path": "work/visual_pdca129_20261020/round1/全条件の会計.json",
        "sha256": "f99b7015dae12e3e7bbdf087eec60e4db8e842fd89fade6e7cbe79f283701375",
    },
    "night_retest": {
        "path": "work/visual_pdca129_20261020/round7/全条件の会計.json",
        "sha256": "9745f76c472d6c79052d8e88cf58bd2001a5da6cdf524405ff8f9cd4f691f469",
    },
    "night_activity": {
        "path": "work/night_why130_20261020/round2/全条件の会計.json",
        "sha256": "865aad2401ec185e21b75478e7aa2a0204b48254a8988f87f3ef910f5105c992",
    },
}


def _verified_bytes(reference):
    """
    機能: 指定指紋と一致する既存資料だけを読み込む。
    引数: reference(dict)は相対pathとsha256。
    返り値: bytesは一致した資料。上書きは行わない。
    """
    path = (ROOT/reference["path"]).resolve()
    assert path.is_relative_to(ROOT)
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == reference["sha256"], path
    return content


@lru_cache(maxsize=4)
def _account(name):
    """
    機能: 固定した旧会計表を読み込み、プロセス内に保持する。
    引数: name(str)はsource_mapのキー。
    返り値: dictは指紋が一致する保存会計。
    """
    return json.loads(_verified_bytes(source_map[name]).decode("utf-8-sig"))


def _ledger(orders, n, multiplier, fee):
    """
    機能: 原注文を親別FIFOで積み、実現・在庫・費用の原行差分を作る。
    引数: orders(ndarray[n注文,8])、n(int)は原行数、multiplier/fee(float)は倍率・片道単価。
    返り値: dictは親会計・原行会計。価格判断と新規注文の生成は行わない。
    """
    orders = np.asarray(orders, dtype=float)
    assert orders.ndim == 2 and orders.shape[1] == 8
    assert n > 0 and multiplier > 0 and fee >= 0
    tenths = int(round(fee*10))
    assert np.isclose(tenths/10., fee)
    long_delta = np.zeros(n, dtype=np.int64)
    short_delta = np.zeros(n, dtype=np.int64)
    trade_cash_delta = np.zeros(n)
    gross_delta = np.zeros(n)
    fee_delta = np.zeros(n)
    closing_fee_delta = np.zeros(n)
    entry_delta = np.zeros(n, dtype=np.int64)
    parents = {}
    previous_row = -1
    for order in orders:
        row, source, cid, side, qty = (int(x) for x in order[:5])
        price, reason, new = order[5], int(order[6]), int(order[7])
        assert np.array_equal(order[[0,1,2,3,4,6,7]], order[[0,1,2,3,4,6,7]].astype(np.int64))
        assert 0 <= source < row < n and row >= previous_row
        assert side in (-1,1) and qty > 0 and new in (0,1) and np.isfinite(price) and price > 0
        previous_row = row
        paid = qty*tenths//10
        fee_delta[row] += paid
        trade_cash_delta[row] -= side*qty*price*multiplier + paid
        if new:
            assert cid not in parents, "旧核の1親1新規を前提にする。複数新規親は別の接続が必要"
            parents[cid] = dict(parent_id=cid, side=side, quantity=qty, entry_row=row,
                                entry_source=source, entry_price=price, exit_row=-1,
                                gross=0., fees=float(paid), net=0., remaining=qty,
                                exit_reason=0)
            (long_delta if side > 0 else short_delta)[row] += qty
            closing_fee_delta[row] += qty*tenths//10
            entry_delta[row] += 1
        else:
            assert cid in parents
            parent = parents[cid]
            assert parent["side"] == -side and 0 < qty <= parent["remaining"]
            before = parent["remaining"]
            gain = parent["side"]*(price-parent["entry_price"])*qty*multiplier
            parent["gross"] += gain
            parent["fees"] += paid
            parent["remaining"] -= qty
            parent["exit_row"] = row
            parent["exit_reason"] = reason
            gross_delta[row] += gain
            (long_delta if parent["side"] > 0 else short_delta)[row] -= qty
            closing_fee_delta[row] += parent["remaining"]*tenths//10 - before*tenths//10
    result_parents = []
    for parent in parents.values():
        assert parent["remaining"] == 0, "保存対象は場内全返済のみ"
        parent["net"] = parent["gross"]-parent["fees"]
        result_parents.append(parent)
    parent_nets = np.array([p["net"] for p in result_parents], dtype=float)
    longs, shorts = np.cumsum(long_delta), np.cumsum(short_delta)
    fees = np.cumsum(fee_delta)
    realized = np.cumsum(gross_delta)-fees
    check_net = float(parent_nets.sum())
    assert longs[-1] == shorts[-1] == 0 and np.all(longs >= 0) and np.all(shorts >= 0)
    assert np.isclose(realized[-1], check_net)
    return dict(
        long_quantity=longs, short_quantity=shorts, position=longs-shorts,
        trade_cash=np.cumsum(trade_cash_delta), realized_cash=realized,
        paid_fees=fees, estimated_close_fee=np.cumsum(closing_fee_delta),
        entries_so_far=np.cumsum(entry_delta), parents=result_parents,
        parent_nets=parent_nets, gross=float(gross_delta.sum()), fees=float(fees[-1]),
        net=check_net, profit=float(parent_nets[parent_nets > 0].sum()),
        loss=float(-parent_nets[parent_nets < 0].sum()), entries=len(result_parents),
        quantity=sum(p["quantity"] for p in result_parents),
        parent_wins=int((parent_nets > 0).sum()), parent_losses=int((parent_nets < 0).sum()),
    )


def load_core(scene, symbol, core_variant):
    """
    機能: 事前固定した旧核の実注文を取得し、注文由来の終端会計を旧summaryと照合する。
    引数: scene(str)は場ID、symbol(str)はTOPIX/NK225、core_variant(int)は0又は1。
          0=夜間TOPIX NV01、1=夜間TOPIX W07。日中DV07/DV05・夜間日経NV25は共通。
    返り値: dictはorders(ndarray)、summary(dict)、method(str)、source/measurement(指紋)。
            orders全体の有無を参加判断に使わず、約定原行までの接頭辞だけを消費する。
    """
    assert symbol in ("TOPIX", "NK225") and core_variant in (0,1)
    if scene.endswith("_Day"):
        name, method = "day", "DV07" if symbol == "TOPIX" else "DV05"
    else:
        assert scene.endswith("_Night")
        if symbol == "NK225":
            name, method = "night_retest", "NV25"
        else:
            name, method = ("night_base","NV01") if core_variant == 0 else ("night_activity","W07")
    account = _account(name)
    rows = [r for r in account["rows"] if r["session"] == scene and r["symbol"] == symbol and r["method"] == method]
    refs = [r for r in account["cache"] if r["session"] == scene and r["symbol"] == symbol]
    assert len(rows) == len(refs) == 1
    ref = {"path": refs[0]["path"], "sha256": refs[0]["sha256"]}
    _verified_bytes(ref)
    with np.load(ROOT/ref["path"], allow_pickle=False) as data:
        orders = data[method+"__orders"].copy()
    multiplier, fee = (1000.,41.8) if symbol == "TOPIX" else (10.,11.)
    ledger = _ledger(orders, int(orders[:,0].max())+1 if len(orders) else 1, multiplier, fee)
    for field in ("net","profit","loss","gross","fees","entries","quantity","parent_wins","parent_losses"):
        assert np.isclose(ledger[field], rows[0][field]), (scene,symbol,method,field)
    return dict(orders=orders, summary=dict(rows[0]), method=method,
                source=dict(source_map[name]), measurement=ref, multiplier=multiplier, fee=fee)


def revalue(times, bid, ask, qok, orders, multiplier, fee):
    """
    機能: 保存実注文を原行の正常BBOで照合し、各親の返済料金込み清算時価を再構成する。
    引数: times/bid/ask/qok(ndarray)は原行、orders(ndarray[n,8])は旧実注文、
          multiplier/fee(float)は商品倍率と税込片道1枚料金。
    返り値: dictはliquidation_equity、position、long_quantity、short_quantity、
            realized_cash、entries_so_far、parents、parent_nets、gross/fees/net等。
            curveはn×5[清算時価円,符号数量,実現費用後円,最大DD,0]。原金・証拠金は含めない。
    """
    times, bid, ask, qok = (np.asarray(x) for x in (times,bid,ask,qok))
    n = len(times)
    assert n and all(x.ndim == 1 and len(x) == n for x in (times,bid,ask,qok))
    assert np.isfinite(times).all() and np.all(np.diff(times) >= 0)
    good = qok.astype(bool) & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    normal_rows = np.flatnonzero(good)
    for order in orders:
        row, source, side = int(order[0]), int(order[1]), int(order[3])
        assert 0 <= source < row < n and good[row]
        first = int(np.searchsorted(normal_rows,source+1,side="left"))
        assert first < len(normal_rows) and normal_rows[first] == row, "次正常原行約定との不一致"
        expected = ask[row] if side > 0 else bid[row]
        assert np.isclose(order[5], expected, rtol=0., atol=1e-8)
    ledger = _ledger(orders, n, multiplier, fee)
    mark_row = np.maximum.accumulate(np.where(good,np.arange(n),-1))
    active = ledger["long_quantity"]+ledger["short_quantity"] > 0
    assert np.all(mark_row[active] >= 0)
    mark_value = np.zeros(n)
    mark_value[active] = multiplier*(
        ledger["long_quantity"][active]*bid[mark_row[active]]
        - ledger["short_quantity"][active]*ask[mark_row[active]])
    equity = ledger["trade_cash"]+mark_value-ledger["estimated_close_fee"]
    assert np.isclose(equity[-1], ledger["net"])
    peak = np.maximum.accumulate(np.maximum(equity,0.))
    drawdown = np.maximum.accumulate(peak-equity)
    ledger["liquidation_equity"] = equity
    ledger["curve"] = np.column_stack([equity,ledger["position"],ledger["realized_cash"],drawdown,np.zeros(n)])
    ledger["max_drawdown"] = float(drawdown[-1])
    ledger["max_long"] = int(ledger["long_quantity"].max())
    ledger["max_short"] = int(ledger["short_quantity"].max())
    return ledger
