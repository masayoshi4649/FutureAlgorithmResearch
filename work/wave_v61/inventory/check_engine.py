"""場内在庫の期限・手数料・再参加・追加・未来非参照を人工経路で検査する。"""

import json
from pathlib import Path

import numpy as np

from accounting import check_accounting
from engine import replay, oldest_opposite
from backtest import account, summarize


HERE = Path(__file__).resolve().parent


def fixture(prices: list, events: list | None = None, times: list | None = None) -> dict:
    """機能: 最後に場内清算判断と次行を置いた人工板列を作る。

    引数: prices(list)、events/times(list|None)。返り値: 売買器引数(dict)。
    """
    mid = np.asarray(prices, float)
    clocks = np.asarray(times, float) if times is not None else np.r_[np.arange(len(mid)-2), 10000., 10001.]
    return dict(times=clocks, seqs=np.arange(len(mid), dtype=np.int64), mid=mid, bid=mid-1., ask=mid+1.,
        sessions=np.zeros(len(mid), np.int64), limits=np.array([10060.]),
        events=np.asarray(events if events is not None else [[0., 0., 0., 1.]], float))


def run(data: dict, family: int = 0, mode: int = 0, minutes: int = 5,
        cooldown_seconds: int = 0, finish: bool = True) -> tuple:
    """機能: 間隔10・上限10・5段という既知単位で人工経路を再生する。

    引数: data(dict)、family/mode/minutes/cooldown_seconds(int)、finish(bool)。返り値: 再生結果(tuple)。
    """
    return replay(**data, family=family, mode=mode, minutes=minutes, cooldown_seconds=cooldown_seconds,
        steps=5, cap=10, value=1000., tick=1., fee_tenths=418, fraction=.001, finish=finish)


def main() -> None:
    """機能: 全系統の数量・費用・未決済・期限・時系列を人工経路で照合する。

    引数: なし。返り値: なし(None)。実データの利益による調整をしない。
    """
    checks = []
    paths = [[10000.,10000.,9990.,9989.,9990.,10001.,10002.,10000.,10000.],
             [10000.,10000.,9900.,9880.,9800.,9750.,10000.,10000.,10000.],
             [10000.,10000.,10010.,10011.,10022.,10023.,10034.,10035.,10035.]]
    for family in range(5):
        for mode in range(3):
            for pi, path in enumerate(paths):
                events = [[0.,40.,20.,1.]] if family == 3 else None
                raw = run(fixture(path, events), family, mode)
                orders, trades, curve, _, risk = raw[:5]
                assert np.all(risk[:, :2] >= 0) and np.all(risk[:, :2] <= 10)
                assert not np.any(raw[6][:, 1]) and not np.any(raw[7][:, 0])
                np.testing.assert_allclose(trades[:,18], trades[:,15]-trades[:,16]-trades[:,17], atol=1e-6)
                np.testing.assert_allclose(orders[:,13].sum(), trades[:,16:18].sum(), atol=1e-6)
                np.testing.assert_allclose(curve[-1], trades[:,18].sum(), atol=1e-6)
                assert np.all(orders[:,2] > orders[:,1])
                checks.append(dict(検査='全系統の数量と全費用会計', family=family, mode=mode, 経路=pi))
    # ----------------------------------------
    # 最初の玉の寿命と、利益条件が整うまで武装を保持する追加判断を確認する。
    data = fixture([10000.,10000.,9990.,9990.,9990.,9990.,9990.,9990.,9990.],
                   times=[0.,1.,2.,3.,100.,303.,304.,10000.,10001.])
    raw = run(data)
    expiry = raw[0][raw[0][:,15] == 11]
    assert len(expiry) == 1 and expiry[0,1] == 5 and expiry[0,2] == 6
    assert raw[1][0,22] == 301./60.
    checks.append(dict(検査='元建時刻から5分で判断し次行約定'))
    trend = fixture(paths[2], [[0.,40.,20.,1.]])
    raw = run(trend, family=3)
    entries = raw[0][raw[0][:,9] == 1]
    assert len(entries) >= 2 and np.all(np.diff(entries[:,2]) > 0)
    assert entries[1,1] == 4
    checks.append(dict(検査='利益条件と1間隔進行の成立まで追加を保留'))
    # ----------------------------------------
    # カバーで古い元玉の期限を延長しない。触値だけの指値成立を認めない。
    covered = fixture([10000.,10000.,9990.,9990.,9990.,9990.,9990.,9990.,9990.,9990.],
        [[0.,0.,0.,1.],[4.,-40.,-20.,1.]], [0.,1.,2.,3.,100.,101.,251.,252.,10000.,10001.])
    raw = run(covered, family=4)
    assert len(raw[0][raw[0][:,15] == 5]) == 1
    exits = raw[0][raw[0][:,15] == 12]
    assert len(exits) == 2 and np.all(exits[:,1] == 6) and np.all(exits[:,2] == 7)
    checks.append(dict(検査='カバー開始後H半分と元玉期限の早い方で両側解消'))
    passive = fixture([10000.,10000.,9989.,9988.,10000.,10001.,10002.,10002.,10002.])
    raw = run(passive, mode=2)
    entries = raw[0][raw[0][:,9] == 1]
    assert entries[0,2] == 3 and entries[0,12] == 9990.
    assert raw[0][raw[0][:,15] == 8][0,12] == 10000.
    checks.append(dict(検査='待機指値の触値不成立と一呼値通過'))
    pos, pending = np.zeros((11,10)), np.zeros((11,7))
    pos[0,:5] = [1.,2.,9990.,83.,3.]
    pos[1,:5] = [1.,2.,9980.,83.,5.]
    assert oldest_opposite(pos,pending,-1,10,9) == 0
    pending[0,0] = 2
    assert oldest_opposite(pos,pending,-1,10,9) == 1
    checks.append(dict(検査='FIFOは古い未返済予約玉を一度だけ選ぶ'))
    skew = fixture([10000.,10000.,9950.,9950.,9949.,9950.,9950.,9950.,9950.],
                   [[0.,0.,0.,1.],[3.,0.,0.,1.]])
    raw = run(skew, family=1)
    fifo = raw[0][raw[0][:,15] == 14]
    assert len(fifo) >= 1 and fifo[0,9] == 2 and fifo[0,10] == -1 and fifo[0,11] == 2
    assert fifo[0,1] == 5 and fifo[0,2] == 6
    assert fifo[0,13] == 83 and raw[1][raw[1][:,19] == 14][0,1] == 0
    checks.append(dict(検査='在庫中心移動後の売り到達は新規売りでなくFIFO2枚返済'))
    records, chain, balance = [], [0.], 0.
    for offset, prices in enumerate(paths[:2]):
        source = fixture(prices)
        source.update(session=f'2026-09-2{1+offset}_Day',symbol='TOPIX',week='2026-09-21')
        raw = run({k:v for k,v in source.items() if k not in ('session','symbol','week')})
        config = dict(id='人工',price_mode='quote',config=dict(minutes=5))
        records.append(account(source,raw,config))
        chain.extend((balance+raw[2]).tolist())
        balance += raw[2][-1]
    total = summarize(records)
    chain = np.asarray(chain)
    np.testing.assert_allclose(total['drawdown'],np.max(np.maximum.accumulate(chain)-chain))
    np.testing.assert_allclose(total['net'],chain[-1])
    negative = [dict(r,net=-100.) for r in records]
    assert summarize(negative)['without_best'] == -200.
    checks.append(dict(検査='全場極値から累積DDを再構築し全場赤字の大勝除外をしない'))
    # ----------------------------------------
    # 未来を消す・変える試験で、過去の注文と含み曲線が変わらないことを確認する。
    for family in range(5):
        for mode in range(3):
            data = fixture(paths[0], [[0.,40.,20.,1.]])
            full = run(data, family, mode)
            for cut in (4,6):
                short = {k:(v[:cut] if k in ('times','seqs','mid','bid','ask','sessions') else v) for k,v in data.items()}
                short['events'] = data['events'][data['events'][:,0] < cut]
                part = run(short, family, mode, finish=False)
                np.testing.assert_array_equal(part[0], full[0][full[0][:,2] < cut])
                np.testing.assert_array_equal(part[2], full[2][:cut])
                altered = {k:v.copy() for k,v in data.items()}
                for field in ('mid','bid','ask'):
                    altered[field][cut:] += 100.
                changed = run(altered,family,mode)
                np.testing.assert_array_equal(changed[0][changed[0][:,2] < cut], part[0])
                checks.append(dict(検査='未来切断と改変',family=family,mode=mode,cut=cut))
    record = dict(合格=True,件数=len(checks),手数料=check_accounting(),詳細=checks)
    (HERE/'合成検査.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(合格=True,件数=len(checks)),ensure_ascii=False))


if __name__ == '__main__':
    main()
