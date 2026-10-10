"""新しい損益を見る前に、方向性売買器の会計と未来不変性を独立検査する。"""

import os
os.environ['NUMBA_DISABLE_JIT'] = '1'
import importlib.util
import json
import hashlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'directional'
sys.path.insert(0, str(SOURCE))


def load(name: str, filename: str):
    """機能: 指定した新コードを専用名で読み込む。

    引数: name/filename(str)。返り値: 読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = load('監査方向売買', 'engine.py')
features = load('監査方向特徴', 'features.py')
signals = load('監査方向入口', 'signals.py')


def fixture(mid: np.ndarray, symbol: str, side: int, aggression: str, mode: bool, hold: int = 5):
    """機能: 実データを使わない売買検査入力を作る。

    引数: mid(ndarray)、symbol/aggression(str)、side/hold(int)、mode(bool)。返り値: 入力4点と価格モード(tuple)。
    """
    mid = 1000. + side * (mid - 1000.)
    times = np.arange(len(mid), dtype=float) * 30.
    times[3] = times[2]
    seq = np.arange(len(mid), dtype=np.int64) * 3 + 5
    ready = dict(seq=seq, time_s=times, start=0., limit=times[-1]-240., tick=1., symbol=symbol, session='人工_Day')
    quotes = dict(seq=seq, time_s=times, mid=mid, bid=mid-.5, ask=mid+.5)
    config = dict(fraction=.01, minutes=hold, **signals.AGGRESSIONS[aggression])
    candidate = np.array([[i, side, 10.] for i in (1, 10, 20, 40) if i < len(mid)], float)
    return ready, quotes, candidate, config, mode


def independent_account(ready: dict, quotes: dict, result: dict, mode: bool) -> None:
    """機能: 注文から全行資産・数量・費用、返済玉から個別会計を再計算する。

    引数: ready/quotes/result(dict)、mode(bool)。返り値: なし(None)。不一致で停止する。
    """
    orders, trades = result['orders'], result['trades']
    value = 1000. if ready['symbol'] == 'TOPIX' else 10.
    cap = 10 if ready['symbol'] == 'TOPIX' else 20
    cash = qty = 0.
    curve, holding = [], []
    cursor = 0
    for i in range(len(ready['seq'])):
        while cursor < len(orders) and orders[cursor, 3] == ready['seq'][i]:
            order = orders[cursor]
            assert i > 0 and order[2] == ready['seq'][i-1]
            assert order[0] == ready['time_s'][i-1] and order[1] == ready['time_s'][i]
            expected = quotes['ask' if order[5] > 0 else 'bid'][i] if mode else quotes['mid'][i]
            assert order[7] == expected
            fee = int(order[6]) * (418 if ready['symbol'] == 'TOPIX' else 110) // 10
            assert order[9] == fee
            cash -= order[5]*order[6]*order[7]*value + fee
            qty += order[5]*order[6]
            assert qty == order[13] and abs(qty) <= cap
            cursor += 1
        mark = quotes['bid' if qty >= 0 else 'ask'][i] if mode else quotes['mid'][i]
        curve.append(cash + qty*mark*value)
        holding.append(qty)
    assert cursor == len(orders)
    np.testing.assert_allclose(curve[-1], result['mtm_change'], atol=1e-6)
    peak = np.maximum.accumulate(np.r_[0., curve])[1:]
    np.testing.assert_allclose(np.max(peak-curve), result['drawdown'], atol=1e-6)
    for trade in trades:
        gross = trade[2]*trade[3]*(trade[5]-trade[4])*value
        assert abs(trade[6]-gross) < 1e-8
        assert abs(trade[7]-trade[24]-trade[25]) < 1e-8
        assert abs(trade[8]-gross+trade[7]) < 1e-8
        assert trade[17] == (trade[1]-trade[0])/60.
        start, end = int(trade[19]), int(trade[20])
        marks = quotes['bid' if trade[2]>0 else 'ask'][start:end+1] if mode else quotes['mid'][start:end+1]
        distances = trade[2]*(marks-trade[4])/trade[10]
        assert abs(trade[15]-max(0., distances.max())) < 1e-8
        assert abs(trade[16]-max(0., -distances.min())) < 1e-8
    for group in np.unique(trades[:,21]):
        legs = trades[trades[:,21] == group]
        closing = orders[(orders[:,12] == group)&(orders[:,4] == 2)]
        assert len(closing) == 1
        assert legs[:,3].sum() == closing[0,6]
        assert abs(legs[:,25].sum()-closing[0,9]) < 1e-8
        assert np.all(legs[:,22] == legs[0,0])


def main() -> None:
    """機能: 鏡像・追加・期限・費用・切断・将来改変を独立の人工経路で検査する。

    引数: なし。返り値: なし(None)。新しい実データ損益は計算しない。
    """
    tests, future_checks = [], 0
    paths = {
        '横ばい': np.full(81,1000.),
        '段階順行': np.r_[np.full(3,1000.),1012.,1022.,1032.,1042.,np.full(74,1030.)],
        '急逆行': np.r_[np.full(3,1000.),np.full(78,920.)],
        '反復': 1000.+np.sin(np.arange(81)*.35)*18,
    }
    for name, path in paths.items():
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for mode in (True,False):
                    for aggression in ('A0','A1','A2'):
                        ready, quotes, candidate, config, mode = fixture(path,symbol,side,aggression,mode)
                        result = engine.execute(ready,quotes,candidate,config,mode)
                        independent_account(ready,quotes,result,mode)
                        for size in (3,7,18,43):
                            clipped = dict(ready, seq=ready['seq'][:size], time_s=ready['time_s'][:size])
                            qp = {key:val[:size] for key,val in quotes.items()}
                            cp = candidate[candidate[:,0] < size]
                            part = engine.execute(clipped,qp,cp,config,mode,False)
                            for key,col in (('orders',3),('trades',13)):
                                wanted = result[key][result[key][:,col] <= ready['seq'][size-1]]
                                np.testing.assert_allclose(part[key],wanted,atol=0,rtol=0)
                            changed = {key:val.copy() for key,val in quotes.items()}
                            for key in ('mid','bid','ask'):
                                changed[key][size:] += 333.
                            modified = engine.execute(ready,changed,candidate,config,mode)
                            for key,col in (('orders',3),('trades',13)):
                                before = modified[key][modified[key][:,col] <= ready['seq'][size-1]]
                                np.testing.assert_allclose(before,part[key],atol=0,rtol=0)
                            future_checks += 2
                        tests.append(f'{name}_{symbol}_{side}_{mode}_{aggression}')
    # ----------------------------------------
    # 5分完了前の箱・未来の極値を使わず、未完了足を削っても既公開値が一致する。
    times = np.arange(0, 12001, 30, dtype=float)
    seq = np.arange(len(times),dtype=np.int64)
    mid = 1000.+np.sin(times/400)*10+times/2000
    ready = dict(time_s=times,seq=seq,start=0.,limit=12000.,tick=1.,symbol='TOPIX',session='人工_Day')
    quotes = dict(time_s=times,seq=seq,mid=mid,bid=mid-.5,ask=mid+.5)
    frame = features.build(ready,quotes,features.SETTINGS[0])
    assert frame.loc[frame.time_s<2100.,'opening_high'].isna().all()
    assert not frame.loc[frame.time_s<2100.,'can_opening'].any()
    feature_audit = features.audit(ready,quotes,features.SETTINGS[0],frame)
    candidate = signals.candidates(frame,mid[0],1.,.001)
    candidate_checks = signals.audit(frame,mid[0],1.,.001,candidate)
    # ----------------------------------------
    # 失敗突破は突破時の固定線へ戻ること、期限と空白による失効を検証する。
    rows = pd.DataFrame(dict(source_bucket=np.arange(5),can_trade=True,prior_observed_fraction=1.,
        close=[112.,111.,108.,100.,100.],prior_high=[110.,200.,200.,200.,200.],prior_low=0.))
    np.testing.assert_array_equal(signals.failed_breakout(rows,1.),[0,0,-1,0,0])
    gap = rows.copy();gap['source_bucket']=[0,1,4,5,6]
    assert not signals.failed_breakout(gap,1.).any()
    expired=rows.copy();expired['close']=[112,112,112,112,100]
    assert not signals.failed_breakout(expired,1.).any()
    record=dict(合格=True,人工売買ケース=len(tests),未来切断改変=future_checks,
        特徴=feature_audit,入口切断=candidate_checks,失敗突破固定線期限空白=3,
        新実データ損益計算=False,コードSHA={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.glob('*.py')},
        限定='純Python合成の独立会計。Numba実行は担当側の合成と本再生で別検証する。')
    (HERE/'方向性の独立合成監査.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k!='コードSHA'},ensure_ascii=False))


if __name__=='__main__':
    main()
