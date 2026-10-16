"""反転後も買いは売気配、売りは買気配で執行する境界を検査する。"""

from context import *
from independent import account, compare


def main() -> None:
    """機能: 人工価格と方向で、成行恒等式と上限非対称を確かめる。

    引数: なし。返り値: なし(None)。証跡は監査領域だけに保存する。
    """
    counts = dict(人工組合せ=0, 成行恒等式決済組=0, 独立会計口座=0, 会計照合項目=0)
    examples = []
    for symbol,qty,value,fee in [('TOPIX',10,1000.,41.8),('NK225',20,10.,11.)]:
        for delay in [0,1,5]:
            for mode in [0,1]:
                for exit_mode in [0,1,2]:
                    for repair in [0,1]:
                        times = np.r_[np.arange(251.),[251.,251.,252.,260.,300.]]
                        bids = 100 + 3*np.sin(times/11.) + np.floor(times/37.)
                        asks = bids + np.where((times//13)%2,1.,2.)
                        states = np.where((times//19)%2,-1,1).astype(np.int8)
                        a = synthetic(times,bids,states,asks=asks,quantity=qty,value=value,fee_unit=fee,
                            latency=delay,entry_mode=mode,exit_mode=exit_mode,repair=repair)
                        a[26] = np.where((times//23)%2,-1,1).astype(np.int8)
                        a[33] = a[26]
                        a[27][(times>=30)&(times<34)] = False
                        a[28][(times>=50)&(times<54)] = False
                        before = [x.copy() if isinstance(x,np.ndarray) else x for x in a]
                        b = opposite(a)
                        f,r = engine.simulate.py_func(*a), engine.simulate.py_func(*b)
                        for aa,bb in zip(a,before):
                            np.testing.assert_array_equal(aa,bb)
                        for args,out in [(a,f),(b,r)]:
                            actual,_ = account(('人工',symbol),args,ledger(out))
                            counts['会計照合項目'] += compare(actual,research.previous.study.accounting.account(('人工',symbol),args,out))
                            counts['独立会計口座'] += 1
                        if mode == 0:
                            check = mirrored(ledger(f),ledger(r),a)
                            counts['成行恒等式決済組'] += check['決済組数']
                        counts['人工組合せ'] += 1
    # ----------------------------------------
    # 小さい変動では元も逆も赤字、十分な外れなら逆だけ黒字となる。
    for name,last,expected in [('無変動は両赤字',100.,False),('費用超過の下落なら逆だけ黒字',90.,True)]:
        a = synthetic([0,5,10,15,240,245],[100,100,last,last,last,last],[1,1,0,0,0,0])
        f,r = engine.simulate.py_func(*a),engine.simulate.py_func(*opposite(a))
        check = mirrored(ledger(f),ledger(r),a)
        assert check['元収支']<0 and (check['逆収支']>0)==expected
        examples.append(dict(検査=name,**check))
    # ----------------------------------------
    # 同じ価格急騰で元ロングは上限不成立、逆ショートは成立する。
    a = synthetic([0,5,10,15,240,245],[100,104,104,104,104,104],[1,1,0,0,0,0],entry_mode=1)
    f,r = engine.simulate.py_func(*a),engine.simulate.py_func(*opposite(a))
    assert f[3][6]>=1 and r[3][6]==0 and f[0][0,0]!=r[0][0,0]
    examples.append(dict(検査='不利1呼値上限は反転側で再判定',元最初約定行=int(f[0][0,0]),逆最初約定行=int(r[0][0,0]),
        元不成立=int(f[3][6]),逆不成立=int(r[3][6]),恒等式適用=False))
    result = dict(合格=True,**counts,具体例=examples,旧エンジンSHA256=digest(OLD/'engine.py'),
        反証='元の損失額全てを利益と読み替える処理ではない。元も逆も費用を支払い、上限付きは経路そのものが変わる。')
    save('売買反転の人工境界と独立会計監査.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
