"""小幅回収の売買器を損益探索と独立した人工経路で点検する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
SPEC = importlib.util.spec_from_file_location('engine', HERE.parent / 'engine.py')
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)


def fixture(prices: list, times: list | None = None, side: int = 1,
            lower: float = np.nan, upper: float = np.nan, regime: int = 0) -> tuple:
    """機能: 中値の人工経路と非連続原本行番号を持つ入力を組み立てる。

    引数: prices/times(list)、side/regime(int)、lower/upper(float)。
    返り値: 価格入力・気配・入口配列(tuple)。side=-1では価格経路と境界を鏡像化する。
    """
    mids = np.asarray(prices, dtype=float)
    if side < 0:
        mids = 200. - mids
        lower, upper = 200. - upper, 200. - lower
    stamp = np.asarray(times if times is not None else np.arange(len(mids)), dtype=float)
    seq = np.arange(len(mids), dtype=np.int64) * 3 + 11
    ready = dict(time_s=stamp, seq=seq, last=mids.copy(), start=0., limit=2000.,
                 tick=1., session='合成', symbol='名称は判定に使わない')
    quotes = dict(time_s=stamp, seq=seq, mid=mids, bid=mids-.5, ask=mids+.5)
    signals = np.array([[0., side, 4., lower, upper, regime]])
    return ready, quotes, signals


def check_account(account: dict, ready: dict, quotes: dict, qty: int = 5, value: float = 10.) -> None:
    """機能: 人工口座の原本順・現金・数量・気配差を独立に照合する。

    引数: account/ready/quotes(dict)、qty(int)、value(float)。
    返り値: なし(None)。不整合時はAssertionError。
    """
    orders = np.asarray(account['orders']).reshape(-1, 13)
    trades = np.asarray(account['trades']).reshape(-1, 16)
    cash = position = 0.
    expected = np.zeros(len(ready['seq']))
    marks = {}
    for order in orders:
        i = int(np.where(ready['seq'] == order[3])[0][0])
        d = int(np.where(ready['seq'] == order[2])[0][0])
        assert i == d + 1
        assert order[0] == ready['time_s'][d] and order[1] == ready['time_s'][i]
        assert order[7] == quotes['mid'][i]
        marks.setdefault(i, []).append(order)
    for i, mid in enumerate(quotes['mid']):
        for order in marks.get(i, []):
            cash -= order[5] * order[6] * order[7] * value
            position += order[5] * order[6]
        assert abs(position) <= qty
        expected[i] = cash + position * mid * value
    np.testing.assert_allclose(expected, account['curve'], atol=1e-8)
    assert position == 0
    pnls = trades[:, 2] * (trades[:, 5]-trades[:, 4]) * qty * value
    np.testing.assert_array_equal(pnls, trades[:, 6])
    assert cash == sum(pnls) == account['net']
    # ----------------------------------------
    # 各片道の気配幅0.5なので、1往復当たり1.0×枚数×倍率だけ悪化する。
    assert account['sensitivity']['売買気配']['net'] == account['net']-len(trades)*qty*value


def main() -> None:
    """機能: 出口、鏡像、時刻、境界、将来切断の合成検査を保存する。

    引数: なし。
    返り値: なし(None)。実際のセッション損益は読まない。
    """
    cases = [
        ('X1利確', 1, [100,100,104,103], None, np.nan,np.nan,0,False,2),
        ('X1損切り', 1, [100,100,96,95], None, np.nan,np.nan,0,False,1),
        ('X2半幅後追跡', 2, [100,100,102,101,100,99], None, np.nan,np.nan,0,False,3),
        ('X2利確', 2, [100,100,106,105], None, np.nan,np.nan,0,False,2),
        ('X3即時追跡', 3, [100,100,103,100,99,98], None, np.nan,np.nan,0,False,3),
        ('箱逸脱', 1, [100,100,102,103], None,99.,101.,0,False,5),
        ('箱逸脱利確同時', 1, [100,100,104,103], None,99.,103.,0,False,5),
        ('10分経過', 1, [100,100,101,100], [0,1,601,602],np.nan,np.nan,0,False,4),
        ('場末優先', 1, [100,100,95,94], [0,1,2000,2001],np.nan,np.nan,0,False,6),
        ('自動追従はX3', 1, [100,100,101,105,101,100], [0,1,601,602,603,604],np.nan,np.nan,1,True,3),
        ('次行境界外', 1, [100,103,104], None,99.,101.,0,False,5),
        ('同時計も原本順', 1, [100,100,104,103], [0,0,0,0],np.nan,np.nan,0,False,2),
    ]
    completed = []
    prefix_checks = 0
    for name, mode, prices, times, lower, upper, regime, automatic, reason in cases:
        for side in (1,-1):
            ready, quotes, signals = fixture(prices,times,side,lower,upper,regime)
            account = ENGINE.execute(ready,quotes,signals,5,10.,mode,automatic)
            assert len(account['trades']) == 1 and account['trades'][0][7] == reason, name
            check_account(account,ready,quotes)
            for size in range(1,len(prices)):
                part = {k:(v[:size] if isinstance(v,np.ndarray) else v) for k,v in ready.items()}
                partq = {k:v[:size] for k,v in quotes.items()}
                actual = ENGINE.execute(part,partq,signals[signals[:,0]<size],5,10.,mode,automatic,False)
                prior = [o for o in account['orders'] if o[3] <= part['seq'][-1]]
                np.testing.assert_array_equal(np.array(actual['orders']).reshape(-1,13),np.array(prior).reshape(-1,13))
                mutated = {k:v.copy() for k,v in quotes.items()}
                for k in ('mid','bid','ask'):
                    mutated[k][size:] += 17.
                future = ENGINE.execute(ready,mutated,signals,5,10.,mode,automatic,False)
                past = [o for o in future['orders'] if o[3] <= part['seq'][-1]]
                np.testing.assert_array_equal(np.array(actual['orders']).reshape(-1,13),np.array(past).reshape(-1,13))
                prefix_checks += 1
            completed.append({'検査':name,'方向':side,'合格':True})
    # ----------------------------------------
    # 保有中の反対候補と60秒未満の候補を破棄し、60秒ちょうどは再度建てられる。
    ready,quotes,_ = fixture([100,100,101,104,103,102,100,99,104,103],
                             [0,1,2,3,4,63,64,65,66,67])
    signals = np.array([[i,s,4,np.nan,np.nan,0] for i,s in ((0,1),(2,-1),(5,1),(6,1))])
    account = ENGINE.execute(ready,quotes,signals,5,10.,1)
    assert account['candidate_audit'] == dict(consumed=4,accepted=2,occupied=1,cutoff=0,cooldown=1,unreached=0)
    check_account(account,ready,quotes)
    evidence = {'合格':True,'出口と鏡像検査':completed,'接頭辞と未来改変比較数':prefix_checks,
                '保有と休止境界':True,'実データ損益参照':False,
                'engine_SHA256':hashlib.sha256((HERE.parent/'engine.py').read_bytes()).hexdigest()}
    (HERE/'独立合成監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'合格':True,'出口鏡像':len(completed),'未来比較':prefix_checks,'休止境界':True},ensure_ascii=False))


if __name__ == '__main__':
    main()
