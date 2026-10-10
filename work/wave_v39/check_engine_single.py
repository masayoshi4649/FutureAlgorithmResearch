"""1枚共通出口の価格・予約・会計を人工系列で独立検査する。"""

from pathlib import Path
import hashlib
import json
import numpy as np
import engine_single as engine

HERE = Path(__file__).resolve().parent


def fixture(n: int = 2200, limit: float = 2100.) -> dict:
    """機能: 場末までの価格一定な人工原本を作る。

    引数: n (int)、limit (float)。返り値: 時刻・価格・ATR等 (dict)。
    """
    return dict(seq=np.arange(n,dtype=np.int64), time_s=np.arange(n,dtype=float),
        last=np.full(n,100.), atr=np.full(n,2.), tick=1., limit=limit,session_close=limit+600.)


def cash_audit(ready: dict, result: dict, pulses: np.ndarray, delay: float) -> None:
    """機能: 注文だけを積算し、全行損益・保有と返済の根拠を照合する。

    引数: ready/result (dict)、pulses (ndarray)、delay (float)。返り値: なし (None)。
    """
    n = len(ready['seq'])
    changes = np.zeros((n,2))
    for row,source,d,q,p,reason,opening in result['orders']:
        row,source = int(row),int(source)
        assert source < row and ready['time_s'][row] >= ready['time_s'][source]+delay
        assert ready['time_s'][row] < ready['session_close'] and q == 1 and d in (-1,1)
        if opening:
            assert pulses[source] == d and reason == 0
        changes[row] += [-d*q*p,d*q]
    amounts = changes.cumsum(axis=0)
    equity = amounts[:,0]+amounts[:,1]*ready['last']
    realized = np.zeros(n)
    for trade in result['trades']:
        entered,exited,d,entry,exit_price,risk,pnl,reason,decision,exit_decision = trade
        assert pnl == d*(exit_price-entry) and risk >= 2*ready['tick']
        assert risk == np.ceil(max(ready['atr'][int(decision)],2*ready['tick'])/ready['tick'])*ready['tick']
        realized[int(exited)] += pnl
    realized = realized.cumsum()
    expected = np.column_stack([realized,equity,amounts[:,1],np.maximum.accumulate(np.maximum(equity,0))-equity])
    np.testing.assert_allclose(result['curve'], expected,rtol=0,atol=1e-12)
    assert (abs(amounts[:,1]) <= 1).all()
    assert result['stats'][0] == realized[-1]
    assert result['stats'][1] == expected[:,3].max()


def main() -> None:
    """機能: 約定価格、IFD遅延、場末、過去不変、反射を反証する。

    引数: なし。返り値: なし (None)。実相場の成績を見ずに実行する。
    """
    checks = []
    for observed in (False,True):
        for direction in (-1,1):
            for kind, move in (('損切り',-5.),('利確',7.)):
                r = fixture(); pulse = np.zeros(len(r['seq']),np.int8);pulse[100] = direction
                r['last'][102:] += direction*move
                result = engine.run(r,pulse,observed=observed)
                cash_audit(r,result,pulse,0.)
                trade = result['trades'][0]
                assert (trade[0],trade[1]) == (101,102)
                expected = move if observed else (-2. if move < 0 else 4.)
                assert trade[6] == expected
                checks.append(kind+'上下・約定方式')
    # ----------------------------------------
    # 新規の遅延と返済子注文の遅延を別々に確認する。
    for delay in (1.,5.,15.):
        r = fixture(); pulse = np.zeros(len(r['seq']),np.int8);pulse[100] = 1
        entry_row = 100+int(delay)
        r['last'][entry_row+1:] = 95.
        result = engine.run(r,pulse,delay=delay)
        cash_audit(r,result,pulse,delay)
        assert result['trades'][0,0] == entry_row
        assert result['trades'][0,1] == entry_row+int(delay)
        checks.append('新規とOCOの各伝達時間')
    r = fixture(); pulse = np.zeros(len(r['seq']),np.int8);pulse[100] = 1
    result = engine.run(r,pulse)
    assert tuple(result['trades'][0,[0,1,7,9]]) == (101,1902,3,1901)
    cash_audit(r,result,pulse,0.)
    checks.append('30分到達判断の次行返済')
    r = fixture(n=1100,limit=1000); pulse = np.zeros(len(r['seq']),np.int8);pulse[100] = -1
    result = engine.run(r,pulse)
    assert tuple(result['trades'][0,[1,7,9]]) == (1001,4,1000)
    cash_audit(r,result,pulse,0.)
    checks.append('安全返済判断の次行返済')
    # ----------------------------------------
    # 同秒の次行はδ0だけで成立し、返済も新規の後行でのみ有効化する。
    r = fixture(); r['time_s'][101:104] = 100.
    pulse = np.zeros(len(r['seq']),np.int8);pulse[100] = 1;r['last'][102:] = 105.
    result = engine.run(r,pulse)
    assert tuple(result['trades'][0,[0,1]]) == (101,102)
    cash_audit(r,result,pulse,0.);checks.append('同秒次行の公開順')
    # 再現可能な往復人工で過去部分・未来差替・上下反射を照合する。
    generator = np.random.default_rng(39)
    for delay in (0.,1.,5.,15.):
        for observed in (False,True):
            r = fixture(n=4200,limit=4000);r['last']=100.+np.cumsum(generator.choice([-1.,0.,1.],4200))
            r['last'] += max(0.,10.-r['last'].min())
            pulse = np.zeros(4200,np.int8);pulse[100:3500:65] = generator.choice([-1,1],len(pulse[100:3500:65]))
            result = engine.run(r,pulse,delay,observed);cash_audit(r,result,pulse,delay)
            for end in (400,1700):
                part = {k:(v[:end].copy() if isinstance(v,np.ndarray) else v) for k,v in r.items()}
                limited = engine.run(part,pulse[:end],delay,observed,False)
                np.testing.assert_array_equal(limited['curve'],result['curve'][:end])
                np.testing.assert_array_equal(limited['orders'],result['orders'][result['orders'][:,0] < end])
                np.testing.assert_array_equal(limited['trades'],result['trades'][result['trades'][:,1] < end])
                future = {k:(v.copy() if isinstance(v,np.ndarray) else v) for k,v in r.items()}
                future['last'][end:] += 17
                future['atr'][end:] *= 3
                changed_pulse = pulse.copy();changed_pulse[end:] *= -1
                changed = engine.run(future,changed_pulse,delay,observed)
                np.testing.assert_array_equal(changed['curve'][:end],result['curve'][:end])
                np.testing.assert_array_equal(changed['orders'][changed['orders'][:,0]<end],limited['orders'])
            mirror = dict(r);mirror['last']=2*(float(r['last'].max())+10)-r['last']
            reflected = engine.run(mirror,-pulse,delay,observed)
            np.testing.assert_allclose(reflected['curve'][:,[0,1,3]],result['curve'][:,[0,1,3]],atol=1e-12)
            checks.append('往復の会計・途中切断・未来改変・上下反射')
    report = dict(全合格=True, 人工検査数=len(checks), 検査=checks, 実相場損益未実施=True,
        SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(engine.__file__),Path(__file__))})
    (HERE/'単発出口の人工検査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(全合格=True, 人工検査数=len(checks)),ensure_ascii=False))


if __name__ == '__main__':
    main()
