"""市場データを使わず、日中核の旧版同値と夜間注文・会計を独立検査する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parent.parent
OLD = ROOT / "work/stability126_20261019/engine/bbo_next/core126.py"
sys.path.insert(0, str(WORK))


def load(path, name):
    """
    機能: 指定した数値源を別名で読み込む。
    引数: path(Path)は数値源、name(str)は衝突しないモジュール名。
    返り値: moduleは読み込んだ数値源。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # ----------------------------------------
    # 人工は子関数も純Pythonに固定し、別名importのJITキャッシュに依存しない。
    for field in ("execute", "repay"):
        value = getattr(module, field, None)
        if value is not None and hasattr(value, "py_func"):
            setattr(module, field, value.py_func)
    return module


def day_fixture(prices, quantity=5, reflected=False, good=None, exit_row=7):
    """
    機能: 昼用の人工通知と実気配を作る。
    引数: prices(list[float])はbid列、quantity(int)、reflected(bool)、good(list[bool]|None)、exit_row(int)。
    返り値: tupleは旧核引数と追加引数。
    """
    bid = np.asarray(prices, float)
    ask = bid+1.
    side = -1 if reflected else 1
    if reflected:
        bid, ask = 200.-ask, 200.-bid
    mid = (bid+ask)/2.
    n = len(mid)
    times = np.arange(n, dtype=float)*301.
    feed = np.asarray([[1,0,0,side,quantity,mid[1],20,1,0,4],
                       [exit_row,exit_row-1,0,-side,quantity,mid[exit_row],9,0,0,4]], float)
    market = np.full((n,12), np.nan)
    market[:,11] = 0.
    policy = np.asarray([0.,.5,0.,0.])
    qok = np.ones(n, bool) if good is None else np.asarray(good, bool)
    old = (times,mid,bid,ask,qok,feed,times[-1]+1000.,quantity*2,market,policy)
    new = (np.full(n,4.),np.full((n,15),np.nan),0)
    return old, new


def night_fixture(prices, quantity=5, multiplier=1000., fee=418, reflected=False,
                  good=None, end=None, us_open=1.e9):
    """
    機能: 帯外から帯内へ反発する人工入力を作る。
    引数: prices(list[float])は中心価格、数量/倍率/料率(int|float)、反射(bool)、資格(list|None)、終了時計(float|None)、米開始(float)。
    返り値: tupleは夜間核の全引数。
    """
    price = np.asarray(prices, float)
    n = len(price)
    times = np.arange(n, dtype=float)*60.
    bid, ask = price-.5, price+.5
    history = np.zeros((n,15),float)
    history[:,0] = 104.
    history[:,1] = 105.
    history[:,2] = 2.
    history[:,3] = 110.
    history[:,4] = 100.
    history[:,5] = .2
    history[:,6:8] = 1.
    history[:,8] = 103.
    history[:,9] = times-60.
    history[:,10:12] = 1.
    history[:,12] = .2
    history[:,13] = 1.
    history[:,14] = times-120.
    market = np.zeros((n,12),float)
    market[:,0] = price
    market[:,1] = 200.
    market[:,2:4] = 4.
    market[:,4:8] = 1.
    market[:,8:11] = times[:,None]-1.
    market[:,11] = 1.
    if reflected:
        price = 200.-price
        bid, ask = 200.-ask, 200.-bid
        history[:,[0,1,8]] = 200.-history[:,[0,1,8]]
        hi = history[:,3].copy()
        history[:,3] = 200.-history[:,4]
        history[:,4] = 200.-hi
        history[:,[6,7,10,11,13]] *= -1.
        market[:,0] = price
        market[:,4:8] *= -1.
    good = np.ones(n,bool) if good is None else np.asarray(good,bool)
    end = times[-2] if end is None else end
    params = np.asarray([1.,1.,1.,.75,0.,300.,.25,900.,.35,.25])
    return (times,price,bid,ask,good,np.full(n,4.),history,market,0.,float(end),
            us_open,.5,quantity,multiplier,fee,params)


def check_night_account(args, result):
    """
    機能: 注文から独立に在庫・全行時価・手数料を作り直す。
    引数: args(tuple)は人工夜間入力、result(tuple)は注文・取引・曲線。
    返り値: None。差異は例外にする。
    """
    times,price,bid,ask,qok = args[:5]
    quantity,multiplier,fee = args[12:15]
    orders,trades,curve = result
    cash = 0.
    inventory = 0
    cost = 0.
    entry = None
    gross_total = 0.
    fees_total = 0.
    markbid = np.nan
    markask = np.nan
    completed = []
    for i in range(len(times)):
        if qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0 < bid[i] < ask[i]:
            markbid,markask = bid[i],ask[i]
        for row in orders[orders[:,0] == i]:
            fill, source, side, qty = row[0],row[1],int(row[3]),int(row[4])
            assert 0 <= source < fill
            assert qok[i] and bid[i] > 0 and ask[i] > bid[i]
            assert row[5] == (ask[i] if side > 0 else bid[i])
            assert all(not(qok[j] and np.isfinite(bid[j]) and np.isfinite(ask[j]) and 0 < bid[j] < ask[j])
                       for j in range(int(source)+1,i))
            one_fee = qty*fee//10
            fees_total += one_fee
            cash -= one_fee
            if row[7] == 1:
                assert inventory == 0
                inventory = side*qty
                cost = row[5]
                entry = row
            else:
                assert inventory*side < 0 and abs(inventory) == qty
                gross = (row[5]-cost)*inventory*multiplier
                gross_total += gross
                cash += gross
                completed.append([entry[0],i,-side,qty,cost,row[5],gross,2*one_fee,gross-2*one_fee])
                inventory = 0
            assert abs(inventory) <= quantity
        liquidation = inventory*((markbid if inventory > 0 else markask)-cost)*multiplier if inventory else 0.
        np.testing.assert_allclose(curve[i],[cash+liquidation,inventory,fees_total,cash],atol=1e-9,rtol=0)
    assert inventory == 0
    np.testing.assert_allclose(trades[:,:9],np.asarray(completed).reshape(-1,9),atol=1e-9,rtol=0)
    assert np.isclose(curve[-1,0],gross_total-fees_total)


def main():
    """
    機能: 合成反例を実行し独立会計と旧版同値の結果を保存する。
    引数: CLI第1引数(str)は保存接尾語。省略時は初回。
    返り値: None。市場や旧金融結果は読まない。
    """
    suffix = sys.argv[1] if len(sys.argv)>1 else "初回"
    sources = [OLD,WORK/"day_core128.py",WORK/"night128.py",WORK/"bbo_order_kernel126.py"]
    before = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old = load(OLD,"audit128_oldcore")
    day = load(WORK/"day_core128.py","audit128_daycore")
    night = load(WORK/"night128.py","audit128_nightcore")
    oldrun,dayrun,nightrun = old.simulate.py_func,day.simulate.py_func,night.simulate.py_func
    checks = []

    def check(name,action):
        """
        機能: 人工確認一件を例外も含めて記録する。
        引数: name(str)は確認名、action(callable)は検査関数。
        返り値: None。
        """
        try:
            action()
            checks.append(dict(確認=name,合格=True))
        except Exception as exc:
            checks.append(dict(確認=name,合格=False,内容=f"{type(exc).__name__}: {exc}"))

    for quantity in (5,10):
        for reflected in (False,True):
            for scenario,prices,good,exitrow in (
                ("通常",[100,100,100,101,102,103,104,105,106],None,7),
                ("損切り",[100,100,100,96,95,100,102,103,104],None,7),
                ("正常気配待ち",[100,100,100,101,102,103,104,105,106],
                 [True,True,False,False,True,True,True,True,True],7),
                ("約定待ち中の取消",[100,100,100,101,102,103,104,105,106],
                 [True,True,False,False,True,True,True,True,True],3),
            ):
                def equality(prices=prices,good=good,exitrow=exitrow,quantity=quantity,reflected=reflected):
                    """
                    機能: 追加出口を無効にした昼核と旧核の全返却配列を照合する。
                    引数: prices/good(list)、exitrow/quantity(int)、reflected(bool)は人工条件。
                    返り値: None。
                    """
                    args,extra = day_fixture(prices,quantity,reflected,good,exitrow)
                    a,b = oldrun(*args),dayrun(*args,*extra)
                    assert len(a) == len(b)
                    for x,y in zip(a,b):
                        np.testing.assert_array_equal(x,y)
                check(f"昼0は旧同値_{quantity}_{reflected}_{scenario}",equality)

    for quantity,multiplier,fee in ((5,1000.,418),(10,10.,110)):
        for reflected in (False,True):
            for label,prices,good in (
                ("回帰利確",[98,100,100.5,103.5,106.5,104.5,104.5,104.5,104.5],None),
                ("損切りギャップ",[98,100,100.5,96.5,80.5,81.5,81.5,81.5,81.5],None),
                ("正常気配待ち",[98,100,100.5,103.5,106.5,104.5,104.5,104.5,104.5],
                 [True,True,False,False,True,True,True,True,True]),
            ):
                def accounting(prices=prices,good=good,quantity=quantity,multiplier=multiplier,fee=fee,reflected=reflected):
                    """
                    機能: 売買両方向と商品ごとの注文会計を確認する。
                    引数: prices/good(list)、数量/倍率/料率(int|float)、reflected(bool)。
                    返り値: None。
                    """
                    args = night_fixture(prices,quantity,multiplier,fee,reflected,good)
                    result = nightrun(*args)
                    assert len(result[1]) == 1
                    check_night_account(args,result)
                check(f"夜会計_{quantity}_{reflected}_{label}",accounting)

    def mirror():
        """
        機能: 全注文の買売交換と損益の同値を確認する。
        引数: なし。
        返り値: None。
        """
        prices = [98,100,100.5,103.5,106.5,104.5,104.5,104.5,104.5]
        a=nightrun(*night_fixture(prices))
        b=nightrun(*night_fixture(prices,reflected=True))
        np.testing.assert_array_equal(a[0][:,[0,1,2,4,6,7]],b[0][:,[0,1,2,4,6,7]])
        np.testing.assert_array_equal(a[0][:,3],-b[0][:,3])
        np.testing.assert_allclose(a[0][:,5],200.-b[0][:,5],atol=0,rtol=0)
        np.testing.assert_array_equal(a[1][:,6:],b[1][:,6:])
    check("夜鏡映売買対称",mirror)

    def terminal():
        """
        機能: 既知の予定終了時計に新規待機を持ち越して建てないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=night_fixture([98,100,100.5,100.5,100.5,100.5],end=120.)
        result=nightrun(*args)
        assert len(result[0]) == 0,"予定終了行に未約定新規が実行された"
    check("夜予定終端で待機新規取消",terminal)

    def exit_extreme():
        """
        機能: 返済約定の大きな飛びを最大逆行へ含めることを確認する。
        引数: なし。
        返り値: None。
        """
        args=night_fixture([98,100,100.5,96.5,80.5,81.5,81.5,81.5,81.5])
        result=nightrun(*args)
        assert result[1][0,10] == -21.,"返済ギャップの逆行が取引診断から欠落"
    check("夜返済約定行を最大逆行へ含める",exit_extreme)

    for p in sources:
        assert before[str(p.relative_to(ROOT))] == hashlib.sha256(p.read_bytes()).hexdigest(),"監査中に数値源変更"
    result = dict(全合格=all(c["合格"] for c in checks),確認数=len(checks),確認=checks,
                  数値源SHA256=before,新金融=0,市場素材読取=0,旧金融結果読取=0)
    target = HERE/f"昼夜核の独立人工監査_{suffix}.json"
    assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
