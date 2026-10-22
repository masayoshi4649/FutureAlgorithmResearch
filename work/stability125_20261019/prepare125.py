"""保存済みの採用価格気配から、確定分足と厳密先行の相手特徴を作る。"""

from io import BytesIO
from pathlib import Path
import hashlib
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
FEATURE_COLUMNS=("closed_last","prev_closed_last","range15_high","range15_low","mean15","er15","change15","scale","peer_dir","peer_er","peer_age","peer_change15")


def digest(path: Path) -> str:
    """
    機能: 保存済み入力の内容を識別する。
    引数: path(Path)は読取対象。
    返り値: strはSHA256。入力の変更は行わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounds(scene: str) -> tuple:
    """
    機能: 名前で示された日本時間の場開始・終了を返す。
    引数: scene(str)は日付_Day又は日付_Night。
    返り値: tuple[float,float]は絶対秒。
    """
    from datetime import datetime,timedelta,timezone
    date,kind=scene.split("_")
    day=datetime.fromisoformat(date).replace(tzinfo=timezone(timedelta(hours=9)))
    if kind=="Day":
        return day.replace(hour=8,minute=45).timestamp(),day.replace(hour=15,minute=45).timestamp()
    assert kind=="Night"
    return day.replace(hour=17).timestamp(),(day+timedelta(days=1)).replace(hour=6).timestamp()


def bars(quotes: dict,start: float,end: float,tick: float) -> dict:
    """
    機能: 正常気配資格を通ったLastだけから、欠測を埋めない確定足を作る。
    引数: quotes(dict[str,ndarray])は採用列、start/end/tick(float)は場と観測刻み。
    返り値: dict[str,ndarray]は一分公開時刻、七状態列及び尺度。
    """
    n=int((end-start)//60)
    times=quotes["time"]
    indices=np.floor((times-start)/60).astype(np.int64)
    valid=(indices>=0)&(indices<n)
    indices=indices[valid];prices=quotes["last"][valid]
    high=np.full(n,-np.inf);low=np.full(n,np.inf);close=np.full(n,np.nan)
    np.maximum.at(high,indices,prices);np.minimum.at(low,indices,prices)
    if len(indices):
        ends=np.r_[np.flatnonzero(np.diff(indices)!=0),len(indices)-1]
        close[indices[ends]]=prices[ends]
    high[~np.isfinite(high)]=np.nan;low[~np.isfinite(low)]=np.nan
    result=np.full((n,8),np.nan)
    for j in range(n):
        result[j,0]=close[j]
        if j:result[j,1]=close[j-1]
        if j<15 or not np.isfinite(close[j-15:j+1]).all():continue
        deltas=np.diff(close[j-15:j+1]);path=np.abs(deltas).sum();change=close[j]-close[j-15]
        result[j,2]=np.max(high[j-14:j+1]);result[j,3]=np.min(low[j-14:j+1])
        result[j,4]=np.mean(close[j-14:j+1]);result[j,5]=abs(change)/path if path>0 else 0.
        result[j,6]=change;result[j,7]=max(8*tick,3*np.quantile(np.abs(deltas),.75))
    return dict(minute=start+60*np.arange(1,n+1),values=result)


def features(quotes: dict,own: dict,peer: dict) -> tuple:
    """
    機能: 自市場の足公開を次の観測原行へ写し、相手は更に一分先行した足まで参照する。
    引数: quotes(dict)は自市場、own/peer(dict)は確定足。
    返り値: tuple[ndarray,ndarray]は厳密増加のfeature_rowsと12状態列。空分を補完しない。
    """
    source_rows=[];source_values=[]
    for j,minute in enumerate(own["minute"]):
        i=int(np.searchsorted(quotes["time"],minute,side="left"))
        if i>=len(quotes["row"]):break
        value=np.full(12,np.nan);value[:8]=own["values"][j]
        k=int(np.searchsorted(peer["minute"],minute-60,side="right"))-1
        if k>=0:
            age=minute-peer["minute"][k]
            pv=peer["values"][k]
            if age<=120 and np.isfinite(pv[5:7]).all():
                value[8]=np.sign(pv[6]);value[9]=pv[5];value[10]=age;value[11]=pv[6]
        raw=int(quotes["row"][i])
        if source_rows and raw==source_rows[-1]:source_values[-1]=value
        else:source_rows.append(raw);source_values.append(value)
    return np.array(source_rows,dtype=np.int64),np.array(source_values,dtype=np.float64).reshape((-1,12))


def execute() -> None:
    """
    機能: 124の所有済み入力82個から、再利用可能な125入力を一度だけ保存する。
    引数: なし。
    返り値: None。金融再生・原本・API・注文を使わない。
    """
    refs=json.loads((ROOT/"work/stability124_20261019/保存気配八十入力と追加一場の参照.json").read_text(encoding="utf-8"))
    result_path=ROOT/"work/stability124_20261019/grid/十二IV条件の全四十一場と旧十九条件の追加一場.json"
    result=json.loads(result_path.read_text(encoding="utf-8"))
    inputs={(r["session"],r["symbol"]):r for r in refs["inputs"]}
    for row in result["cache"]:inputs[row["session"],row["symbol"]]=row
    out=HERE/"prepared";assert not out.exists();out.mkdir()
    records=[]
    for scene in refs["sessions"]:
        start,end=bounds(scene);quote={};made={};sources={}
        for symbol,tick in (("TOPIX",.5),("NK225",10.)):
            meta=inputs[scene,symbol];payload=(ROOT/meta["path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest()==meta["sha256"]
            with np.load(BytesIO(payload),allow_pickle=False) as saved:
                q={key:saved["quotes__"+key].copy() for key in ("row","time","last","bid","ask")}
            assert len(q["row"]) and np.all(np.diff(q["row"])>0) and np.all(np.diff(q["time"])>=0)
            assert all(np.isfinite(v).all() for v in q.values())
            assert np.all((q["bid"]>0)&(q["ask"]>q["bid"]))
            quote[symbol]=q;made[symbol]=bars(q,start,end,tick);sources[symbol]=meta
        for symbol in ("TOPIX","NK225"):
            peer="NK225" if symbol=="TOPIX" else "TOPIX"
            fr,fv=features(quote[symbol],made[symbol],made[peer])
            path=out/(symbol+"_"+scene+".npz")
            np.savez_compressed(path,**quote[symbol],feature_rows=fr,features=fv)
            records.append(dict(session=scene,symbol=symbol,path=path.relative_to(ROOT).as_posix(),sha256=digest(path),source=sources[symbol],peer_source=sources[peer],quote_rows=len(quote[symbol]["row"]),feature_rows=len(fr),valid_features=int(np.isfinite(fv[:,:8]).all(axis=1).sum()),start=start,end=end))
        print(scene,"二商品入力保存",flush=True)
    assert len(records)==82
    proof=dict(passed=True,inputs=records,sessions=refs["sessions"],feature_columns=FEATURE_COLUMNS,financial_replays=0,original_market_reads=0,API=0,real_orders=0,source_sha256=digest(Path(__file__)),contract="足は正常BBO価格採用行から作り、空分補完なし。相手は一分厳密先行。受信時計を再現した証拠ではない。")
    (HERE/"保存済み気配と先行確定足の八十二入力.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":execute()
