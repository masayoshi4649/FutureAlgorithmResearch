"""第一巡の保存約定と原板を照合し、原因の三例を図示する。金融再生はしない。"""
import json,hashlib
from pathlib import Path
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from diagnose_day164 import read,raw_rows,stamp,JST,digest


def main():
    """確定結果の三例を原板へ照合する。

    引数: なし。返り値: None。
    """
    root=Path(__file__).resolve().parents[1];assert read(root/"再生全完了164.json")["completed"] is True
    cfg=[("2026-10-13_Day","NK225_D164_07","episode/1","09:49:20","09:53:00","3秒の再加速で25→88枚、買値は同じ"),
         ("2026-10-15_Day","NK225_D164_05","addon/0","09:35:20","09:49:00","同値保護後、同価格へ10→56枚で入り直す"),
         ("2026-10-19_Day","NK225_D164_06","addon/0","09:41:40","09:45:00","小さく退出し、高い価格へ増量して買い直す")]
    fonts={x.name for x in fm.fontManager.ttflist}
    for name in ("Yu Gothic","Meiryo","MS Gothic"):
        if name in fonts:plt.rcParams['font.family']=name;break
    plt.style.use('dark_background');fig,axes=plt.subplots(3,1,figsize=(13,11));proof=[]
    for ax,(session,method,parent,start,end,title) in zip(axes,cfg):
        path=next((root/"results").glob("*/"+session+".json"));data=read(path);scene=data['scene'];raw=raw_rows(scene);case=next(x for x in data['cases'] if x['config']['id']==method)
        day=session[:10];a=datetime.fromisoformat(day+'T'+start+'+09:00').timestamp();b=datetime.fromisoformat(day+'T'+end+'+09:00').timestamp();use=(raw['time']>=a)&(raw['time']<=b)&raw['valid'];ids=np.flatnonzero(use)
        times=[datetime.fromtimestamp(float(t),JST) for t in raw['time'][ids]];ax.plot(times,raw['bid'][ids],lw=.75,label='返済側Bid');ax.plot(times,raw['ask'][ids],lw=.6,alpha=.5,label='新規側Ask')
        checks=[]
        for e in case['actual']['Events'] or []:
            if e['Order']['Parent']!=parent:continue
            i=e['FillIndex'];di=e['Order']['DecisionIndex'];side=e['Order']['Side'];price=raw['ask'][i] if side>0 else raw['bid'][i];assert price==e['Price'];assert abs(raw['time'][i]-e['FillTime'])<1e-5
            rec=dict(kind=e['Order']['Kind'],reason=e['Order']['Reason'],quantity=e['Order']['Quantity'],gross=e['Gross'],decision=dict(index=di,line=int(raw['line'][di]),time=stamp(float(raw['time'][di])),bid=float(raw['bid'][di]),ask=float(raw['ask'][di])),fill=dict(index=i,line=int(raw['line'][i]),time=stamp(float(raw['time'][i])),bid=float(raw['bid'][i]),ask=float(raw['ask'][i]),price=e['Price']))
            checks.append(rec)
            if a<=e['FillTime']<=b:
                new=not e['Order'].get('Targets');t=datetime.fromtimestamp(e['FillTime'],JST);ax.scatter([t],[e['Price']],marker='^' if new else 'v',s=40,c='#66c8ff' if new else '#ffcc66',zorder=5);ax.annotate(('買' if new else '返')+str(e['Order']['Quantity']),xy=(t,e['Price']),xytext=(4,10 if new else -18),textcoords='offset points',fontsize=8)
        decisions=[x for x in case.get('decisions') or [] if x['Parent']==parent]
        proof.append(dict(session=session,method=method,parent=parent,result_sha256=digest(path),raw_sha256=raw['sha256'],orders=checks,decisions=decisions))
        ax.set_title(session+' / '+method+' / '+title,fontsize=11);ax.set_ylabel('日経ラージ価格');ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S',tz=JST));ax.grid(alpha=.22);ax.legend(loc='best',fontsize=8)
    fig.suptitle('利益保護の後に増量することが、新しい損失を作った具体例（枚数はmicro）',fontsize=13);fig.tight_layout(rect=[0,0,1,.97]);out=root/'day_design/diagnosis';fig.savefig(out/'日中の再増量と原板三例164.png',dpi=150);plt.close(fig)
    (out/'日中の原板三例照合164.json').write_text(json.dumps(dict(passed=True,new_financial_replays=0,examples=proof,image_sha256=digest(out/'日中の再増量と原板三例164.png')),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('三例の全新規返済を原板へ照合しました')

if __name__=='__main__':main()
