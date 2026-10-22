"""第一巡の日中を期限参加・追随・回帰に分解する。保存注文以外の取引は作らない。"""

import hashlib
import json
import pickle
import sys
from pathlib import Path
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
sys.path.insert(0,str(WORK))
import features131
from diagnose_day131 import clock, clean, candles

METHODS=("R01","R05","R09")
PLOTS={("2026-09-24_Day","TOPIX"),("2026-10-13_Day","TOPIX"),
       ("2026-10-19_Day","TOPIX"),("2026-10-09_Day","NK225"),("2026-10-02_Day","NK225")}
READS=[]


def fixed(ref):
    """
    機能: 保存資料のSHA256を照合して内容を読む。
    引数: ref(dict)はpathとsha256。
    返り値: bytesは元内容。
    """
    raw=(ROOT/ref["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==ref["sha256"]
    READS.append(ref)
    return raw


def summary(rows):
    """
    機能: 保存親の入口別寄与と順行の不足を集計する。
    引数: rows(list[dict])は保存親。
    返り値: dictは件数・収支・費用・損失親の順行分類。
    """
    loss=[r for r in rows if r["net"]<0]
    return dict(parents=len(rows),net=sum(r["net"] for r in rows),gross=sum(r["gross"] for r in rows),
        fees=sum(r["fees"] for r in rows),wins=sum(r["net"]>0 for r in rows),losses=len(loss),
        loss_without_positive_excursion=sum(r["mfe"]<=0 for r in loss),
        loss_before_one_R=sum(r["mfe"]<r["R"] for r in loss),
        loss_mfe_at_most_quarter_R=sum(r["mfe"]<=.25*r["R"] for r in loss),
        entry_against_own20=sum(r["side"]*r["own20"]<0 for r in rows),
        entry_against_peer20=sum(r["side"]*r["peer20"]<0 for r in rows))


def snapshot(ready,q,h,m,order,trade):
    """
    機能: 実新規の判断行と保存親を対応し、その時点で既知だった特徴を記録する。
    引数: ready/q(dict)、h/m/order/trade(ndarray)は保存原行と親。
    返り値: dictは当時値と、明確に分離した事後成績。
    """
    source=int(order[1]);entry=int(trade[1]);exit_row=int(trade[2])
    return dict(parent=int(trade[0]),side=int(trade[3]),quantity=int(trade[4]),
        source_row=source,entry_row=entry,exit_row=exit_row,
        decision_time=clock(ready["time_s"][source]),entry_time=clock(ready["time_s"][entry]),
        exit_time=clock(ready["time_s"][exit_row]),entry=float(trade[5]),exit=float(trade[6]),
        gross=float(trade[7]),fees=float(trade[8]),net=float(trade[9]),R=float(trade[10]),
        mfe=float(trade[11]),mae=float(trade[12]),phase=int(trade[13]),mode=int(trade[14]),
        entry_reason=int(trade[15]),exit_reason=int(trade[16]),
        own_atr=float(ready["atr"][source]),own_mid=float((q["bid"][source]+q["ask"][source])*.5),
        own5=float(h[source,6]),own20=float(h[source,7]),peer5=float(h[source,10]),peer20=float(h[source,11]),
        mean5=float(h[source,0]),mean20=float(h[source,1]),std20=float(h[source,2]),
        high20=float(h[source,3]),low20=float(h[source,4]),efficiency20=float(h[source,5]),
        peer_efficiency20=float(h[source,12]),own120=float(m[source,5]),peer120=float(m[source,7]),
        market_known=bool(m[source,11]==1),history_time=clock(h[source,9]),
        peer_history_time=clock(h[source,14]))


def draw(inputs,packet,history,results,scene,symbol,cutoff=None):
    """
    機能: 三条件の実売買と実停止床を同じ価格経路へ並べる。
    引数: inputs/packet/history/results(dict)、scene/symbol(str)、cutoff(int又はNone)。
    返り値: strは新画像位置。接頭表示はその原行までの価格と軸だけを使用する。
    """
    own=inputs[scene,symbol];other="NK225" if symbol=="TOPIX" else "TOPIX"
    peer=inputs[scene,other];q=packet["quotes"][scene,symbol]
    end=cutoff+1 if cutoff is not None else len(own["time_s"])
    now=own["time_s"][end-1]
    fig,axes=plt.subplots(4,1,figsize=(16,13),sharex=True)
    fig.patch.set_facecolor("#101722")
    for ax in axes:
        ax.set_facecolor("#172336");ax.tick_params(colors="#d7e6f7")
        ax.yaxis.label.set_color("#d7e6f7");ax.grid(color="#3f4c63",alpha=.45)
        for spine in ax.spines.values():spine.set_color("#4e607b")
    valid=np.isfinite(own["last"][:end])
    bars=candles(own["time_s"][:end][valid],own["last"][:end][valid],own["start"])
    for ax,method in zip(axes[:3],METHODS):
        ax.plot(bars[:,0]+.5,bars[:,4],color="#c2d5ed",lw=.8,label="正常気配中値の1分終値")
        ix=np.searchsorted(own["time_s"],own["start"]+bars[:,0]*60,side="right")-1
        ax.plot(bars[:,0],history[scene,symbol][np.maximum(ix,0),1],color="#bca879",lw=.8,label="当時公開済み20分平均")
        result=results[method];orders=result["orders"];trades=result["trades"]
        for trade in trades:
            entry,exit_row=int(trade[1]),int(trade[2])
            if entry>=end:continue
            row=orders[(orders[:,2]==trade[0]) & (orders[:,7]==0)][0]
            decision=int(row[1]);direction=int(trade[3])
            until=min(exit_row,end-1);indices=np.arange(entry,until+1)
            # ----------------------------------------
            # 保存返済判断後の床は動かさず、返済気配までの損益変動と分ける。
            good=q["quote_valid"][indices] & np.isfinite(q["bid"][indices]) & np.isfinite(q["ask"][indices])
            good &= (q["ask"][indices]>q["bid"][indices]) & (q["bid"][indices]>0)
            mark=q["bid" if direction>0 else "ask"][indices]
            move=direction*(mark-trade[5])
            peaks=np.maximum.accumulate(np.where(good & (indices<=decision),np.maximum(0,move),0))
            width=trade[10];floor=np.where(peaks>=width,np.maximum(-width,peaks-.75*width),-width)
            floor_price=trade[5]+direction*floor
            ax.plot((own["time_s"][indices]-own["start"])/60,floor_price,color="#eea26e",lw=.8,ls=":")
        for order in orders:
            index=int(order[0])
            if index>=end:continue
            side=int(order[3]);is_entry=order[7]==1
            x=(own["time_s"][index]-own["start"])/60
            ax.scatter(x,order[5],marker=("^" if side>0 else "v") if is_entry else "x",
                       color="#6bd8ae" if side>0 else "#f19aa6",s=32,zorder=5)
            if is_entry:
                ax.annotate(clock(own["time_s"][index])[:5]+"/"+str(int(order[6])),(x,order[5]),
                    xytext=(2,8),textcoords="offset points",color="#e5eaf0",fontsize=7)
        ax.set_ylabel(method)
        if cutoff is None:
            ax.text(.01,.95,f"保存収支 {trades[:,9].sum():+,.0f}円",transform=ax.transAxes,
                    va="top",color="#edecdf",fontsize=9)
    limit=np.searchsorted(peer["time_s"],now,side="left")
    good=np.isfinite(peer["last"][:limit])
    b=candles(peer["time_s"][:limit][good],peer["last"][:limit][good],own["start"])
    axes[-1].plot(b[:,0]+.5,b[:,4],color="#92b9ff",lw=.9)
    axes[-1].set_ylabel(other)
    for ax in axes:
        for minute in (15,165,225,400):
            if minute<(now-own["start"])/60:ax.axvline(minute,color="#586a83",lw=.6,ls="--")
    axes[-1].set_xlim(0,(now-own["start"])/60+1)
    axes[-1].xaxis.set_major_locator(MultipleLocator(30))
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda v,_:clock(own["start"]+v*60)[:5]))
    suffix="全経路" if cutoff is None else "判断まで_"+clock(now).replace(":","")
    fig.suptitle(scene+" "+symbol+" "+suffix+"\n80=追随・81=回帰・82=期限参加／三角=新規・×=返済／点線=当時の停止床",
                 color="#e7eef7",fontsize=14)
    fig.tight_layout(rect=(0,0,1,.945))
    folder=HERE/"第一巡画像";folder.mkdir(exist_ok=True)
    target=folder/(scene+"_"+symbol+"_"+suffix+".png")
    fig.savefig(target,dpi=125,facecolor=fig.get_facecolor());plt.close(fig)
    return target.relative_to(ROOT).as_posix()


def main():
    """
    機能: 第一巡三条件の全22日中を保存親単位で分類し、最悪場と反例を画像化する。
    引数: なし。
    返り値: None。条件・金融核・旧根拠を変更しない。
    """
    plt.rcParams["font.family"]=["Yu Gothic","Meiryo","DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"]=False
    account_path=WORK/"round1_final/全条件の会計.json"
    account=json.loads(account_path.read_text(encoding="utf-8"))
    manifest=json.loads((ROOT/"work/daynight128_20261020/入力準備.json").read_text(encoding="utf-8"))
    caches={(r["session"],r["symbol"]):r for r in account["cache"]}
    parents=[];images=[];summaries=[];cases=[]
    for ref in manifest["packets"]:
        scene=ref["session"]
        if not scene.endswith("_Day"):continue
        packet=pickle.loads(fixed(ref))
        inputs,markets,histories,_=features131.build(packet)
        for symbol in ("TOPIX","NK225"):
            rd=inputs[scene,symbol];q=packet["quotes"][scene,symbol]
            cache=caches[scene,symbol]
            with np.load(BytesIO(fixed(cache))) as z:
                results={m:{f:z[m+"__"+f].copy() for f in ("orders","trades")} for m in METHODS}
            for method in METHODS:
                result=results[method];entries=result["orders"][result["orders"][:,7]==1]
                group=[]
                for trade in result["trades"]:
                    order=entries[entries[:,2]==trade[0]][0]
                    value=snapshot(rd,q,histories[scene,symbol],markets[scene,symbol],order,trade)
                    value.update(scene=scene,symbol=symbol,method=method,
                        posthoc_rise=bool(packet["inputs"][scene,symbol]["last"][-1]>packet["inputs"][scene,symbol]["last"][0]))
                    group.append(value);parents.append(value)
                row=next(r for r in account["rows"] if r["method"]==method and r["symbol"]==symbol and r["session"]==scene)
                assert abs(sum(r["net"] for r in group)-row["net"])<.001
                cases.append(dict(method=method,symbol=symbol,scene=scene,net=row["net"],parents=group))
            if (scene,symbol) in PLOTS:
                images.append(draw(inputs,packet,histories,results,scene,symbol))
                if scene=="2026-10-19_Day":
                    target=next(v for v in parents if v["scene"]==scene and v["symbol"]==symbol and v["method"]=="R09" and v["entry_reason"]==81)
                    images.append(draw(inputs,packet,histories,results,scene,symbol,target["source_row"]))
        print(scene,"保存親分類",flush=True)
    for method in METHODS:
        for symbol in ("TOPIX","NK225"):
            ps=[r for r in parents if r["method"]==method and r["symbol"]==symbol]
            entry={str(reason):summary([r for r in ps if r["entry_reason"]==reason]) for reason in (80,81,82)}
            rising=[r for r in ps if r["posthoc_rise"]]
            summaries.append(dict(method=method,symbol=symbol,**summary(ps),entry_reasons=entry,
                rising_buy=summary([r for r in rising if r["side"]>0]),rising_sell=summary([r for r in rising if r["side"]<0]),
                worst_sessions=sorted([r for r in cases if r["method"]==method and r["symbol"]==symbol],key=lambda x:x["net"])[:3],
                winning_counterexamples=sorted(ps,key=lambda x:x["net"],reverse=True)[:3]))
    result=dict(passed=True,summary=summaries,parents=parents,images=images,reads=READS,
        account_source=dict(path=account_path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(account_path.read_bytes()).hexdigest()),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),financial_replays=0,
        scope="三条件×二商品×22日中の保存注文を分類。特徴再計算は因果入力の診断だけで金融核を呼ばない。",
        limitation="MFE/MAE・上昇場・親収支は事後分類。入口に未来の場方向や山谷を渡していない。")
    (HERE/"第一巡日中の期限参加と通常入口の損失分解.json").write_text(
        json.dumps(clean(result),ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print("保存診断完了。新金融0。",flush=True)


if __name__=="__main__":
    main()
