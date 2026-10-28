"""保存売買の全行診断から、原因別の反証と可視化を作る。金融再生なし。"""

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import gzip
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = ZoneInfo("Asia/Tokyo")


def main():
    """
    機能: 当時の保存売買と事後の値動き分類を分け、全件集計と四場の原板根拠を保存する。
    引数: なし。
    返り値: None。事後分類・極値を新しい売買判断へ投入しない。
    """
    data = json.loads((HERE/"保存TG04の全場利益返し診断.json").read_text(encoding="utf-8"))
    charts = json.loads((HERE/"全場1分気配と保存約定.json").read_text(encoding="utf-8"))
    scenes, parents = data["sessions"], data["parents"]
    median_range = float(np.median([x["minute_range"] for x in scenes]))
    median_eff = float(np.median([x["efficiency"] for x in scenes]))
    groups = []
    for high in (False, True):
        for directional in (False, True):
            chosen = [x for x in scenes if (x["minute_range"] >= median_range) == high and (x["efficiency"] >= median_eff) == directional]
            groups.append(dict(range="大" if high else "小", directionality="強" if directional else "弱", count=len(chosen),
                gross=sum(x["gross"] for x in chosen), red=sum(x["gross"]<0 for x in chosen)))
    daynight=[]
    thirds=[]
    for kind in ("Day","Night"):
        cohort=[x for x in scenes if x["session"].endswith(kind)]
        threshold=float(np.median([x["minute_range"] for x in cohort]))
        for high in (False,True):
            chosen=[x for x in cohort if (x["minute_range"]>=threshold)==high]
            daynight.append(dict(kind=kind,threshold=threshold,high=high,count=len(chosen),gross=sum(x["gross"] for x in chosen),red=sum(x["gross"]<0 for x in chosen)))
        range_limits=np.quantile([x["minute_range"] for x in cohort],[1/3,2/3])
        efficiency_limits=np.quantile([x["efficiency"] for x in cohort],[1/3,2/3])
        for range_group in range(3):
            for efficiency_group in range(3):
                chosen=[x for x in cohort if int(np.searchsorted(range_limits,x["minute_range"],side="right"))==range_group
                        and int(np.searchsorted(efficiency_limits,x["efficiency"],side="right"))==efficiency_group]
                names={x["session"] for x in chosen}
                selected_parents=[x for x in parents if x["session"] in names]
                profit=sum(x["gross"] for x in selected_parents if x["gross"]>0)
                loss=-sum(x["gross"] for x in selected_parents if x["gross"]<0)
                thirds.append(dict(kind=kind,range_group=("小","中","大")[range_group],efficiency_group=("弱","中","強")[efficiency_group],
                    count=len(chosen),parents=len(selected_parents),profit=profit,loss=loss,pf=profit/loss if loss else None,
                    net=profit-loss,red=sum(x["gross"]<0 for x in chosen),
                    peak_giveback=sum(x["peak_to_final_giveback"] for x in selected_parents),
                    sessions=sorted(names),range_limits=range_limits.tolist(),efficiency_limits=efficiency_limits.tolist()))
    summary=dict(sessions=len(scenes),parents=len(parents),rows=data["raw_rows"],gross=sum(x["gross"] for x in scenes),
        corr_range_gross=float(np.corrcoef([x["minute_range"] for x in scenes],[x["gross"] for x in scenes])[0,1]),
        corr_range_giveback=float(np.corrcoef([x["minute_range"] for x in scenes],[x["peak_giveback"] for x in scenes])[0,1]),
        median_range=median_range,median_efficiency=median_eff,groups=groups,daynight=daynight,thirds=thirds,
        positive_peak_parents=sum(x["peak_gross_equity"]>0 for x in parents),positive_peak_then_loss=sum(x["peak_gross_equity"]>0 and x["gross"]<0 for x in parents),
        largest_givebacks=sorted(parents,key=lambda x:x["peak_to_final_giveback"],reverse=True)[:12])
    (HERE/"保存TG04の事後分類集計.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    # ----------------------------------------
    # AIが図を読む四場では、約定・極値の対応行を原文から直接抽出して時計を照合する。
    chosen=[("2026-10-13_Day",0),("2026-10-20_Day",0),("2026-10-19_Day",10_000_000),("2026-10-15_Day",0)]
    snapshots=[]
    for scene, parent in chosen:
        record=next(p for p in parents if p["session"]==scene and p["parent"]==parent)
        targets={record["peak_raw_line"]:record["peak_time"]}
        for order in record["orders"]:
            targets[order["decision_raw_line"]]=order["decision_time"]
            targets[order["fill_raw_line"]]=order["fill_time"]
        source=ROOT.parent/"JP_OSE_Data/future/NK225"/scene/"book.jsonl.gz"
        with gzip.open(source,"rt",encoding="utf-8") as f:
            for number,line in enumerate(f,1):
                if number not in targets:
                    continue
                raw=json.loads(line)
                assert datetime.fromisoformat(raw["CurrentPriceTime"]).timestamp()==datetime.fromisoformat(targets[number]).timestamp()
                snapshots.append(dict(session=scene,parent=parent,line=number,raw=raw))
    (HERE/"四場の原板原文抜粋.json").write_text(json.dumps(snapshots,ensure_ascii=False,indent=2),encoding="utf-8")
    plt.rcParams.update({"font.family":["Yu Gothic","Meiryo","DejaVu Sans"],"font.size":10,"figure.facecolor":"#0c1523", "axes.facecolor":"#132034", "text.color":"#dfe7f2", "axes.labelcolor":"#dfe7f2", "xtick.color":"#c3cede", "ytick.color":"#c3cede", "axes.edgecolor":"#56657b"})
    fig, axes=plt.subplots(2,2,figsize=(17,10))
    for ax,(scene,parent) in zip(axes.ravel(),chosen):
        record=next(p for p in parents if p["session"]==scene and p["parent"]==parent)
        chart=charts[scene]
        dates=[datetime.fromisoformat(t) for t in chart["times"]]
        ax.plot(dates,chart["mid"],color="#99c4ec",lw=1,label="1分末の原板中値")
        for order in record["orders"]:
            t=datetime.fromisoformat(order["fill_time"])
            entry=order["action"]=="新規"
            ax.scatter(t,order["price"],color="#68d4b0" if entry else "#f5bf70",s=60,marker="v" if order["side"]=="売り" else "^",zorder=5)
            ax.annotate(f'{order["action"]}{order["quantity"]}枚',xy=(t,order["price"]),xytext=(4,12 if entry else -18),textcoords="offset points",fontsize=8)
        peak=datetime.fromisoformat(record["peak_time"])
        ax.axvline(peak,color="#e3899a",ls=":",label="保有中の最高評価価値")
        ax.set_title(f'{scene} {record["owner"]} {record["side"]}\n最高評価 {record["peak_gross_equity"]:,.0f}円 → 最終粗損益 {record["gross"]:,.0f}円')
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=JST));ax.grid(alpha=.13);ax.legend(loc="upper right",fontsize=8)
    fig.suptitle("TG04：利益を戻した例と、戻りを許しながら大きく取れた例",fontsize=17)
    fig.text(.5,.015,"保存売買は変更していません。ラージ気配によるmini代理・費用0の事後診断。最高値を事前に知って利確できるという意味ではありません。",ha="center",fontsize=10)
    fig.tight_layout(rect=(0,.04,1,.95))
    fig.savefig(HERE/"利益返しと継続成功の四場.png",dpi=140)
    print(json.dumps({k:v for k,v in summary.items() if k not in ("largest_givebacks",)},ensure_ascii=False))


if __name__=="__main__":
    main()
