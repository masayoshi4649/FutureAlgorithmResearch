"""全夜間の価格・公表量を時刻帯と当時状態で分類する。金融取引は生成しない。"""

import hashlib
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = ROOT/"work/daynight128_20261020"
OLD = ROOT/"work/night_why130_20261020"
JST = ZoneInfo("Asia/Tokyo")
NY = ZoneInfo("America/New_York")
PHASES = ("米開始75分前まで", "米開始75〜45分前", "米開始45〜15分前",
          "米開始前後15分", "米開始15分後〜欧州主要引け", "欧州主要引け〜米現物引け", "米現物引け以降")


def read(path: Path) -> dict:
    """
    機能: 保存済みUTF-8のJSONを読み込む。
    引数: path(Path)は対象。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf8"))


def clean(value):
    """
    機能: 観測結果の非有限値とnumpy型をJSON向けに変換する。
    引数: value(任意型)は観測値。
    返り値: 任意型は非有限をNoneにした値。
    """
    if isinstance(value,dict):
        return {k:clean(v)for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [clean(v)for v in value]
    if isinstance(value,np.ndarray):
        return clean(value.tolist())
    if isinstance(value,np.generic):
        return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 観測だけの根拠をUTF-8で保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2)+"\n",encoding="utf8")


def minute_data(packet: dict, scene: str, symbol: str) -> dict:
    """
    機能: 各分端より厳密に前の最新気配と公表出来高を用いて観測列を作る。
    引数: packet(dict)、scene/symbol(str)は保存入力・場・商品。
    返り値: dictは過去20分特徴と原行対応。未来の価格は特徴へ用いない。
    """
    rd,q=packet["inputs"][scene,symbol],packet["quotes"][scene,symbol]
    ts=rd["time_s"]
    ends=np.arange(rd["start"]+60.,rd["limit"]+0.1,60.)
    rows=np.searchsorted(ts,ends,side="left")-1
    safe=np.maximum(rows,0)
    valid=(rows>=0)&(ends-ts[safe]<=30.)&q["quote_valid"][safe]
    valid &= np.isfinite(q["bid"][safe])&np.isfinite(q["ask"][safe])
    valid &= (q["ask"][safe]>q["bid"][safe])&(q["bid"][safe]>0.)
    close=np.full(len(ends),np.nan)
    close[valid]=(q["bid"][safe[valid]]+q["ask"][safe[valid]])/2.
    spread=np.full(len(ends),np.nan)
    spread[valid]=q["ask"][safe[valid]]-q["bid"][safe[valid]]
    with np.load(OLD/"activity_raw"/f"{symbol}_{scene}.npz") as z:
        volume=z["volume"]
    reset=(~np.isfinite(volume)).astype(int)
    reset[1:] |= (np.diff(volume)<0.).astype(int)
    cumulative=np.cumsum(reset)
    vol=np.full(len(ends),np.nan)
    for i in range(1,len(ends)):
        a,b=rows[i-1],rows[i]
        if a>=0 and b>=a and np.isfinite(volume[a]) and np.isfinite(volume[b]) and cumulative[b]==cumulative[a]:
            vol[i]=volume[b]-volume[a]
    data=np.full((len(ends),11),np.nan)
    # ----------------------------------------
    # 各差の始終端は既知に限る。帯と効率には区間中の全分値を要求する。
    for i in range(20,len(ends)):
        segment=close[i-20:i+1]
        if not np.isfinite(segment).all():
            continue
        diffs=np.diff(segment)
        path=np.abs(diffs).sum()
        width=segment.max()-segment.min()
        data[i,0]=segment[-1]-segment[0]
        data[i,1]=abs(data[i,0])/path if path>0 else 0.
        data[i,2]=segment[-1]-segment[-6]
        data[i,3]=segment[-1]-segment[-2]
        data[i,4]=width
        data[i,5]=segment[:-1].max()
        data[i,6]=segment[:-1].min()
        data[i,7]=(segment[-1]-segment.min())/width if width>0 else .5
        nonzero=np.sign(diffs[diffs!=0.])
        data[i,8]=np.mean(nonzero[1:]!=nonzero[:-1]) if len(nonzero)>1 else 0.
        prior=vol[i-20:i]
        if np.isfinite(prior).all() and np.isfinite(vol[i]):
            typical=np.median(prior)
            if typical>0:
                data[i,9]=vol[i]/typical
        small=np.abs(diffs[-5:]).sum()
        data[i,10]=abs(data[i,2])/small if small>0 else 0.
    delta=ends-rd["us_open"]
    eu_close=datetime.fromisoformat(scene[:10]+"T17:30:00").replace(tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
    us_close=datetime.fromisoformat(scene[:10]+"T16:00:00").replace(tzinfo=NY).timestamp()
    phase=np.select([delta< -4500.,delta< -2700.,delta< -900.,delta<900.,ends<eu_close,ends<us_close],
        [0,1,2,3,4,5],default=6).astype(int)
    return dict(time=ends,close=close,spread=spread,volume=vol,rows=rows,features=data,phase=phase,
        us_open=rd["us_open"],eu_close=eu_close,us_close=us_close,tick=rd["tick"])


def outcome(d: dict, i: int, side: int) -> dict:
    """
    機能: 当時の20分帯の四分の一幅に対する、後20分以内の順逆先着を事後採点する。
    引数: d(dict)、i/side(int)は観測列・判断分番号・方向。
    返り値: dictは方向分類の診断値。保有時間や注文条件には使用しない。
    """
    width=max(.25*d["features"][i,4],2.*d["tick"])
    future=d["close"][i+1:min(i+21,len(d["close"]))]
    observed=0
    first=0
    for j,value in enumerate(future):
        if not np.isfinite(value):
            break
        observed+=1
        signed=side*(value-d["close"][i])
        if signed>=width or signed<=-width:
            first=1 if signed>=width else -1
            break
    if first==0 and observed<20:
        return dict(known=False,observed_minutes=observed)
    progress=side*(future-d["close"][i])
    complete=len(future)==20 and np.isfinite(future).all()
    return dict(known=True,unit=float(width),first=first,observed_minutes=observed,
        full_window=bool(complete),mfe=float(max(0.,progress.max()))if complete else None,
        mae=float(min(0.,progress.min()))if complete else None,end=float(progress[-1])if complete else None)


def summarize_events(events: list[dict]) -> list[dict]:
    """
    機能: 条件別・商品別・時刻帯別の観測分母と先着分類を集計する。
    引数: events(list[dict])は固定条件で抽出した全観測。
    返り値: list[dict]は先着率と未到達・未知を分離した統計。
    """
    summaries=[]
    for method in ("共通進行","共通方向への押戻り","外抜けから帯内復帰","公表量急増の共通進行"):
        for symbol in ("TOPIX","NK225"):
            for phase in (-1,0,1,2,3,4,5,6):
                rows=[r for r in events if r["method"]==method and r["symbol"]==symbol and (phase<0 or r["phase"]==phase)]
                known=[r for r in rows if r["outcome"]["known"]]
                up=sum(r["outcome"]["first"]==1 for r in known)
                down=sum(r["outcome"]["first"]==-1 for r in known)
                summaries.append(dict(method=method,symbol=symbol,phase="全帯" if phase<0 else PHASES[phase],
                    observations=len(rows),sessions=len({r["session"]for r in rows}),
                    outcome_known=len(known),first_favorable=up,first_adverse=down,
                    neither=len(known)-up-down,hit_fraction=up/(up+down)if up+down else None))
    return summaries


def main() -> None:
    """
    機能: 21夜間の時間帯の違いと、固定した三候補・基準の観測結果を保存する。
    引数: なし。
    返り値: None。旧入力・旧金融結果を変更せず、金融再生を実施しない。
    """
    refs=[r for r in read(BASE/"入力準備.json")["packets"]if r["session"].endswith("_Night")]
    allstats,events,clock_checks,sessionrows=[],[],[],[]
    oldparents=read(OLD/"entry_book/第二巡の入口見送り後の全親差分.json")["records"]
    finalparents=read(OLD/"entry_book/第四巡の価格記録と全親差分.json")["records"]
    for ref in refs:
        scene=ref["session"]
        packet=pickle.loads((ROOT/ref["path"]).read_bytes())
        daily={s:minute_data(packet,scene,s)for s in ("TOPIX","NK225")}
        for symbol,d in daily.items():
            date=scene[:10]
            us=datetime.fromisoformat(date+"T09:30:00").replace(tzinfo=NY).timestamp()
            assert us==d["us_open"]
            clock_checks.append(dict(session=scene,symbol=symbol,us_local=datetime.fromtimestamp(us,JST).isoformat(),
                europe_close=datetime.fromtimestamp(d["eu_close"],JST).isoformat(),
                us_close=datetime.fromtimestamp(d["us_close"],JST).isoformat()))
            peer=daily["NK225" if symbol=="TOPIX" else "TOPIX"]
            x,px=d["features"],peer["features"]
            assert np.array_equal(d["time"],peer["time"])
            method="W07" if symbol=="TOPIX" else "W12"
            parents=[r for r in (oldparents if method=="W07" else finalparents)
                if r["method"]==method and r["symbol"]==symbol and r["session"]==scene]
            for phase in range(len(PHASES)):
                ids=np.flatnonzero(d["phase"]==phase)
                good=ids[np.isfinite(x[ids,1])]
                joint=good[np.isfinite(px[good,0])]
                changes=np.abs(np.diff(d["close"]))
                chosen=changes[np.maximum(ids[ids>0]-1,0)]
                allstats.append(dict(session=scene,symbol=symbol,phase=PHASES[phase],minutes=len(ids),
                    close_known=int(np.isfinite(d["close"][ids]).sum()),state_known=len(good),
                    median_move_bp=float(np.nanmedian(chosen)/np.nanmedian(d["close"][ids])*10000.)if len(chosen)else None,
                    median_volume=float(np.nanmedian(d["volume"][ids]))if len(ids)else None,
                    median_efficiency20=float(np.nanmedian(x[good,1]))if len(good)else None,
                    median_reversal_fraction=float(np.nanmedian(x[good,8]))if len(good)else None,
                    common_direction_eligible=len(joint),
                    common_direction_fraction=float(np.mean(x[joint,0]*px[joint,0]>0.))if len(joint)else None))
            for i in range(21,len(x)-20):
                if not np.isfinite(x[i,:9]).all() or not np.isfinite(px[i,:9]).all():
                    continue
                side=int(np.sign(x[i,0]))
                common=side!=0 and side*px[i,0]>0.
                strong=common and x[i,1]>=.35 and px[i,1]>=.35
                signals=[]
                if i%5==0 and strong and side*x[i,2]>0. and side*px[i,2]>0.:
                    signals.append(("共通進行",side))
                if strong and side*x[i-1,3]<0. and side*x[i,3]>0. and side*px[i,3]>0.:
                    signals.append(("共通方向への押戻り",side))
                before=d["close"][i-21:i-1]
                if np.isfinite(before).all():
                    hi,lo=before.max(),before.min()
                    outside=1 if d["close"][i-1]>hi else -1 if d["close"][i-1]<lo else 0
                    inside=lo<=d["close"][i]<=hi
                    if outside and inside and x[i,1]<.35 and (outside*px[i,0]<=0. or px[i,1]<.35):
                        signals.append(("外抜けから帯内復帰",-outside))
                impulse=int(np.sign(x[i,3]))
                if impulse and impulse*px[i,3]>0. and x[i,10]>=.5 and px[i,10]>=.5:
                    if np.isfinite(x[i,9]) and np.isfinite(px[i,9]) and min(x[i,9],px[i,9])>=2.:
                        signals.append(("公表量急増の共通進行",impulse))
                for name,sign in signals:
                    events.append(dict(session=scene,symbol=symbol,method=name,index=i,
                        time=datetime.fromtimestamp(d["time"][i],JST).isoformat(),phase=int(d["phase"][i]),
                        side=sign,price=float(d["close"][i]),efficiency=float(x[i,1]),peer_efficiency=float(px[i,1]),
                        change20=float(x[i,0]),peer_change20=float(px[i,0]),range20=float(x[i,4]),
                        change1=float(x[i,3]),peer_change1=float(px[i,3]),
                        volume_ratio=float(x[i,9]),peer_volume_ratio=float(px[i,9]),
                        previous_method=method,previous_trade_count=len(parents),previous_net=sum(r["net"]for r in parents),
                        outcome=outcome(d,i,sign)))
            phase_net=[]
            for parent in parents:
                rowtime=datetime.fromisoformat(parent["entry_time"]).timestamp()
                difference=rowtime-d["us_open"]
                phase=(0 if difference< -4500. else 1 if difference< -2700. else 2 if difference< -900.
                    else 3 if difference<900. else 4 if rowtime<d["eu_close"] else 5 if rowtime<d["us_close"] else 6)
                phase_net.append(dict(parent=parent["parent"],entry_time=parent["entry_time"],exit_time=parent["exit_time"],
                    side=parent["side"],net=parent["net"],phase=PHASES[phase]))
            sessionrows.append(dict(session=scene,symbol=symbol,method=method,trades=len(parents),
                net=sum(r["net"]for r in parents),parents=phase_net))
            path=HERE/"minutes"/f"{symbol}_{scene}.npz"
            path.parent.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(path,**{k:v for k,v in d.items()if isinstance(v,np.ndarray)})
        print(scene,"観測統計のみ",flush=True)
    phase_summary=[]
    for symbol in ("TOPIX","NK225"):
        for phase in PHASES:
            rows=[r for r in allstats if r["symbol"]==symbol and r["phase"]==phase]
            phase_summary.append(dict(symbol=symbol,phase=phase,sessions=len(rows),
                minutes=sum(r["minutes"]for r in rows),state_known=sum(r["state_known"]for r in rows),
                median_move_bp=float(np.nanmedian([r["median_move_bp"]for r in rows])),
                median_volume=float(np.nanmedian([r["median_volume"]for r in rows])),
                median_efficiency20=float(np.nanmedian(np.array([r["median_efficiency20"]for r in rows],dtype=float))),
                median_reversal_fraction=float(np.nanmedian(np.array([r["median_reversal_fraction"]for r in rows],dtype=float)))))
    save(HERE/"全夜間の時間帯と継続往復の観測.json",dict(financial_replays=0,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),inputs=refs,clock_checks=clock_checks,
        phase_summary=phase_summary,phase_sessions=allstats,events=events,event_summary=summarize_events(events),
        old_sessions=sessionrows,
        limits="毎分の正常気配中値、分端厳密前かつ30秒以内を採用。過去20分状態は全21分値を要求。未来20分の分端観測先着は事後診断のみで、分中の先着・売買又は成功率の検証ではない。先着前に欠測なら未知、先着後の欠測は確定した先着を消さない。同条件は重なり独立でない。既知21場からの開発診断。開始75〜45分前を毎日経済指標発表とみなさない。公表量は成行主導側を表さない。終端05:50まで。"))
    print(phase_summary)
    print([r for r in summarize_events(events)if r["phase"]=="全帯"])


if __name__=="__main__":
    main()
