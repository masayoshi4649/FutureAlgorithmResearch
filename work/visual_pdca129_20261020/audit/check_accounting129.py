"""00129の保存注文から全気配会計を独立集計する。"""

import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parent.parent


def read(path):
    """
    機能: UTF-8の保存JSONを読む。
    引数: path(Path)は読取位置。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    """
    機能: 元資料の内容指紋を返す。
    引数: path(Path)は読取位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(row, orders, trades, curve, ready, quote):
    """
    機能: 実注文からFIFOと会計を独立に再構成し保存値を検査する。
    引数: row/ready/quote(dict)、orders/trades/curve(ndarray|None)は保存会計と原入力。
    返り値: dictは検査件数と再集計金額。売買条件の再生は行わない。
    """
    n=len(ready["time_s"])
    bid,ask=quote["bid"],quote["ask"]
    good=quote["quote_valid"] & np.isfinite(bid) & np.isfinite(ask) & (0<bid) & (bid<ask)
    valid_rows=np.flatnonzero(good)
    mult,rate=(1000.,418) if row["symbol"]=="TOPIX" else (10.,110)
    cap=5 if row["symbol"]=="TOPIX" else 10
    inventory=0
    parent={}
    ticket=None
    expected=[]
    delta_cash=np.zeros(n)
    delta_qty=np.zeros(n,dtype=np.int64)
    delta_fee=np.zeros(n)
    realized=np.zeros(n)
    for order in orders:
        fill,source,cid,side,qty=map(int,order[:5])
        assert 0<=source<fill<n
        assert valid_rows[np.searchsorted(valid_rows,source,side="right")]==fill
        assert order[5]==(ask[fill] if side>0 else bid[fill])
        assert side in (-1,1) and 0<qty<=cap
        fee=qty*rate//10
        delta_cash[fill]-=side*qty*order[5]*mult
        delta_fee[fill]+=fee
        delta_qty[fill]+=side*qty
        record=parent.setdefault(cid,dict(gross=0.,fees=0.,held=0))
        record["fees"]+=fee
        if order[7]==1:
            assert inventory==0 and 0<qty<=cap
            ticket=order.copy()
        else:
            assert inventory*side<0 and abs(inventory)>=qty
            assert ticket is not None and ticket[2]==cid
            gain=-side*qty*(order[5]-ticket[5])*mult
            record["gross"]+=gain
            realized[fill]+=gain
            expected.append((cid,-side,qty,ticket[5],order[5],ticket[0],fill,order[6],gain))
        inventory+=side*qty
        record["held"]+=side*qty
        assert abs(inventory)<=cap
    assert inventory==0 and all(v["held"]==0 for v in parent.values())
    totals=np.asarray([v["gross"]-v["fees"] for v in parent.values()])
    computed=dict(profit=float(totals[totals>0].sum()),loss=float(-totals[totals<0].sum()),
                  net=float(totals.sum()),gross=float(sum(v["gross"] for v in parent.values())),
                  fees=int(delta_fee.sum()),entries=int((orders[:,7]==1).sum()),
                  quantity=int(orders[orders[:,7]==1,4].sum()),
                  max_quantity=int(orders[orders[:,7]==1,4].max()) if (orders[:,7]==1).any() else 0)
    for name,value in computed.items():
        assert np.isclose(value,row[name],rtol=0,atol=1e-7),(name,value,row[name])
    assert len(expected)==len(trades)
    if row["kind"]=="Day":
        for e,t in zip(expected,trades):
            np.testing.assert_allclose(
                [e[0],e[1],e[2],e[3],e[4],e[5],e[6],e[7],e[8]],
                [t[0],t[2],t[3],t[4],t[5],t[6],t[7],t[9],t[10]*mult],
                rtol=0,atol=1e-7)
    else:
        for e,t in zip(expected,trades):
            np.testing.assert_allclose(
                [e[5],e[6],e[1],e[2],e[3],e[4],e[8],e[7]],
                [t[0],t[1],t[2],t[3],t[4],t[5],t[6],t[12]],
                rtol=0,atol=1e-7)
            fee=e[2]*rate//10*2
            assert t[7]==fee and np.isclose(t[8],e[8]-fee)
            a,b=int(t[0]),int(t[1])
            good_segment=good[a:b+1]
            exit_side=bid[a:b+1] if t[2]>0 else ask[a:b+1]
            movement=t[2]*(exit_side[good_segment]-t[4])
            assert np.isclose(t[9],max(0.,movement.max()))
            assert np.isclose(t[10],min(0.,movement.min()))
    curve_rows=0
    if curve is not None:
        inv=np.cumsum(delta_qty)
        cash=np.cumsum(delta_cash)
        fees=np.cumsum(delta_fee)
        known=np.maximum.accumulate(np.where(good,np.arange(n),-1))
        held=inv!=0
        assert (known[held]>=0).all()
        liquidation=np.zeros(n)
        longs=inv>0
        shorts=inv<0
        liquidation[longs]=inv[longs]*bid[known[longs]]*mult
        liquidation[shorts]=inv[shorts]*ask[known[shorts]]*mult
        equity=cash+liquidation
        if row["kind"]=="Day":
            np.testing.assert_allclose(curve[:,0]*mult,equity,atol=1e-6,rtol=0)
            np.testing.assert_allclose(curve[:,1]*mult,np.cumsum(realized),atol=1e-6,rtol=0)
            np.testing.assert_array_equal(curve[:,2],np.maximum(0,inv))
            np.testing.assert_array_equal(curve[:,3],np.maximum(0,-inv))
            np.testing.assert_allclose(curve[:,5]*mult,cash,atol=1e-6,rtol=0)
        else:
            np.testing.assert_allclose(curve[:,0],equity-fees,atol=1e-6,rtol=0)
            np.testing.assert_array_equal(curve[:,1],inv)
            np.testing.assert_array_equal(curve[:,2],fees)
            np.testing.assert_allclose(curve[:,3],np.cumsum(realized)-fees,atol=1e-6,rtol=0)
        curve_rows=n
    return dict(method=row["method"],session=row["session"],symbol=row["symbol"],
                passed=True,orders=len(orders),trades=len(trades),curve_rows=curve_rows,
                source_alias=row.get("origin", "00129の新規保存"),computed=computed)


def main():
    """
    機能: 指定巡の保存全会計を監査し結果を一度だけ保存する。
    引数: CLI第1引数(str)はround1等の保存巡。
    返り値: None。金融再生は行わない。
    """
    name=sys.argv[1] if len(sys.argv)>1 else "round1"
    source=WORK/name/"全条件の会計.json"
    output=HERE/f"{name}_全注文と全行会計の独立照合.json"
    assert not output.exists()
    data=read(source)
    manifest=read(ROOT/"work/daynight128_20261020/入力準備.json")
    packets={p["session"]:p for p in manifest["packets"]}
    grouped={}
    for row in data["rows"]:
        grouped.setdefault((row["session"],row["symbol"]),[]).append(row)
    records=[]
    saved_scene=None
    for cache in data["cache"]:
        scene,symbol=cache["session"],cache["symbol"]
        path=ROOT/cache["path"]
        assert digest(path)==cache["sha256"]
        if scene!=saved_scene:
            ref=packets[scene]
            assert digest(ROOT/ref["path"])==ref["sha256"]
            packet=pickle.loads((ROOT/ref["path"]).read_bytes())
            saved_scene=scene
        key=scene,symbol
        with np.load(path,allow_pickle=False) as archive:
            for row in grouped[key]:
                prefix=row["method"]+"__"
                curve=archive[prefix+"curve"] if prefix+"curve" in archive else None
                records.append(inspect(row,archive[prefix+"orders"],archive[prefix+"trades"],
                                       curve,packet["inputs"][key],packet["quotes"][key]))
        print(scene,symbol,len(records),flush=True)
    result=dict(passed=True,accounts=len(records),orders=sum(r["orders"] for r in records),
                trades=sum(r["trades"] for r in records),curve_rows=sum(r["curve_rows"] for r in records),
                source=dict(path=str(source.relative_to(ROOT)),sha256=digest(source)),
                auditor_sha256=digest(Path(__file__)),records=records,
                financial_replays=0,API=0,scope="保存注文から料金、FIFO、全行清算価値を独立再集計")
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="records"},ensure_ascii=False))


if __name__=="__main__":
    main()
