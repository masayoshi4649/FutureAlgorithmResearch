"""サイクル返済後の新規停止と現金移動会計を独立に監査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import reference
import risk_guard

OUT = Path(__file__).resolve().parent


def leg(cycle: int, slot: int, side: int, start: int, end: int, entry: float, exit_price: float,
        atr: float = 100., complete: bool = True) -> np.ndarray:
    """機能: 手計算可能な独立脚を作る。

    引数: cycle/slot/side/start/end (int)、entry/exit_price/atr (float)、complete (bool)。
    返り値: ndarray: 22列の脚。
    """
    row = np.zeros(22)
    row[[0,1,2,4,5,6,7,8,9,13,14,15,20,21]] = [cycle,slot,side,max(0,start-1),start,end,atr,entry,exit_price,1,int(complete),side*(exit_price-entry),start,end]
    return row


def independent_account(raw: np.ndarray, prices: np.ndarray) -> tuple:
    """機能: 現金差分を使わず各行・各脚の保有損益を直接合計する。

    引数: raw/prices (ndarray)。返り値: tuple: 評価・ATR換算・枚数・確定・DDと最大DD。
    """
    price = prices.copy().astype(float)
    previous = 0.
    for i in range(len(price)):
        previous = price[i] if np.isfinite(price[i]) else previous
        price[i] = previous
    equity, normalized, gross, realized = (np.zeros(len(price)) for _ in range(4))
    for row in raw:
        start, end, side = int(row[5]), int(row[6]), row[2]
        complete = bool(row[14])
        until = end if complete else len(price)
        equity[start:until] += side*(price[start:until]-row[8])
        normalized[start:until] += side*(price[start:until]-row[8])/row[7]
        gross[start:until] += 1
        if complete:
            pnl = side*(row[9]-row[8])
            equity[end:] += pnl
            normalized[end:] += pnl/row[7]
            realized[end:] += pnl
    dd = np.maximum.accumulate(np.maximum.accumulate(np.r_[0.,equity])[1:]-equity)
    normalized_dd = np.maximum.accumulate(np.r_[0.,normalized])[1:]-normalized
    return equity, normalized, gross, realized, dd, float(dd.max()), float(normalized_dd.max())


def account_equal(raw: np.ndarray, prices: np.ndarray) -> None:
    """機能: 間引かない全価格行について二つの異なる会計を照合する。

    引数: raw/prices (ndarray)。返り値: None: 不一致時は例外。
    """
    for expected, actual in zip(independent_account(raw,prices),risk_guard.account_arrays(raw,prices)):
        np.testing.assert_allclose(expected,actual,rtol=1e-8,atol=1e-6)


def hand_cases() -> int:
    """機能: 両建て・異なるATR・含み損と停止条件を手計算で確認する。

    引数: なし。返り値: int: 独立ケース数。
    """
    prices = np.array([95.,100.,110.,90.,120.,100.])
    raw = np.array([leg(0,0,1,1,4,100,120),leg(0,1,-1,2,5,110,100,50)])
    actual = risk_guard.account_arrays(raw,prices)
    np.testing.assert_allclose(actual[0],[0,0,10,10,10,30])
    np.testing.assert_allclose(actual[1],[0,0,.1,.3,0,.4],atol=1e-12)
    np.testing.assert_allclose(actual[2],[0,1,2,2,1,0])
    np.testing.assert_allclose(actual[3],[0,0,0,0,20,30])
    np.testing.assert_allclose(actual[5:], [0,.3],atol=1e-12)
    account_equal(raw,prices)
    open_raw = np.array([leg(0,0,1,1,4,100,110),leg(0,1,-1,2,5,110,100,50,False)])
    account_equal(open_raw,prices)
    assert risk_guard.account_arrays(open_raw,prices)[0][-1] == 20
    raw = np.array([leg(i,0,1,1+i*3,2+i*3,1000,1000+pnl) for i,pnl in enumerate([-50,-50,100,-100,-100])])
    expected_stops = {'G1':1,'G2':None,'G3':4,'G4':None,'G5':1}
    for guard in risk_guard.GUARDS:
        kept, audit = risk_guard.filter_raw(raw,dict(max_legs=1,guard=guard))
        cycle = expected_stops[guard['code']]
        assert audit['stopped'] == (cycle is not None)
        if cycle is not None:
            assert audit['cycle'] == cycle and len(kept) == cycle+1
    open_last = raw.copy()
    open_last[1,14] = 0
    open_last = open_last[:2]
    assert not risk_guard.filter_raw(open_last,dict(max_legs=1,guard=risk_guard.GUARDS[0]))[1]['stopped']
    reset = np.array([leg(i,0,1,1+i*3,2+i*3,1000,1000+pnl) for i,pnl in enumerate([-50,0,-50,50,-50])])
    assert not risk_guard.filter_raw(reset,dict(max_legs=1,guard=risk_guard.GUARDS[0]))[1]['stopped']
    net_loss = np.array([leg(i,0,1,1+i*3,2+i*3,1000,1000+pnl) for i,pnl in enumerate([500,-100,-100,-100])])
    assert not risk_guard.filter_raw(net_loss,dict(max_legs=1,guard=risk_guard.GUARDS[2]))[1]['stopped']
    return 10


def truncate(raw: np.ndarray, count: int, prices: np.ndarray) -> np.ndarray:
    """機能: 完成売買の末尾を当時未返済の評価へ置き換える。

    引数: raw/prices (ndarray)、count (int): 残す価格行数。返り値: ndarray: 当時見えた全脚。
    """
    result = raw[raw[:,5] < count].copy()
    for row in result:
        if row[6] >= count:
            row[6], row[9], row[13], row[14], row[21] = count-1,prices[count-1],0,0,count-1
            row[15] = row[2]*(row[9]-row[8])
    return result


def main() -> None:
    """機能: 手計算・保存原本の会計・未来打切りで停止器を確認する。

    引数: なし。返り値: None: 新規停止の独立監査.jsonを保存する。通信なし。
    """
    manual = hand_cases()
    with (OUT/'既知入力.pkl').open('rb') as stream:
        prepared = pickle.load(stream)
    configurations = json.loads((OUT.parent/'wave_v13/条件一覧.json').read_text(encoding='utf-8'))
    eligible = [cfg for cfg in configurations if risk_guard.eligible_base(cfg)]
    selected = [eligible[i] for i in np.linspace(0,len(eligible)-1,8).astype(int)]
    cells = list(prepared.items())
    cells = [cells[i] for i in [0,3,10,15]]
    account_count, prefix_count = 0,0
    for key,ready in cells:
        for config in selected:
            base = reference.engine.simulate(ready,config['family'],config)
            for variant in risk_guard.variants(config):
                raw, audit = risk_guard.filter_raw(base['raw'],variant)
                account_equal(raw,ready['last'])
                if audit['stopped']:
                    values = risk_guard.account_arrays(raw,ready['last'])
                    assert np.all(values[2][audit['row']:] == 0)
                    np.testing.assert_allclose(values[0][audit['row']:],values[0][audit['row']])
                account_count += 1
                for proportion in [.317,.613,.887]:
                    count = int(len(ready['last'])*proportion)
                    visible = truncate(base['raw'],count,ready['last'])
                    prefix_kept, prefix_audit = risk_guard.filter_raw(visible,variant)
                    expected = truncate(raw,count,ready['last'])
                    np.testing.assert_allclose(prefix_kept,expected,equal_nan=True)
                    if audit['stopped'] and audit['row'] < count:
                        assert prefix_audit == audit
                    else:
                        assert not prefix_audit['stopped']
                    prefix_count += 1
    result = dict(成功=True,手計算ケース数=manual,保存セル数=len(cells),基条件数=len(selected),
                  停止方式数=5,全行会計比較数=account_count,未来打切り比較数=prefix_count,
                  API取得数=0,実現損失の定義='利益も相殺したセッション累積確定収支。負け脚の絶対額累計ではない。',
                  risk_guard_SHA256=hashlib.sha256((OUT/'risk_guard.py').read_bytes()).hexdigest())
    (OUT/'新規停止の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
