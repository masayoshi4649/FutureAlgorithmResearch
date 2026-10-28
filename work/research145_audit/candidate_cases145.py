"""保存済み候補から改善例と反例の原時刻・板・図を作る。売買は再生成しない。"""

import gzip
import json
from datetime import datetime
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = ZoneInfo('Asia/Tokyo')


def stamp(value):
    """
    機能: 保存原行の価格時計を日本時間表記へ変換する。
    引数: value(float)はUNIX秒。
    返り値: strはISO形式の日本時間。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def main():
    """
    機能: 四つの事前診断・反例を図示し、新判断時点の既知特徴と原板を保存する。
    引数: なし。
    返り値: None。既存約定を参照し、金融再生・新規条件選択は行わない。
    """
    minute = json.loads((HERE/'全場1分気配と保存約定.json').read_text(encoding='utf-8'))
    cases = [('2026-10-13_Day',0,'利益を守れた例'), ('2026-10-20_Day',0,'急反転で残玉を守れた例'),
             ('2026-09-28_Day',1,'早い返済で再下落を逃す反例'), ('2026-10-16_Night',10000003,'短い上昇を買い転換とする反例')]
    plt.style.use('dark_background')
    plt.rcParams['font.family'] = ['Meiryo', 'Yu Gothic', 'DejaVu Sans']
    fig, axes = plt.subplots(2,2,figsize=(17,11),layout='constrained')
    output=[]
    for ax, (scene,parent,title) in zip(axes.flat,cases):
        with (ROOT/'work/research145_engine/cache'/f'{scene}.pkl').open('rb') as stream:
            _,data,*_=pickle.load(stream)
        ready = data['ready']
        with np.load(ROOT/'work/research145_engine/measurement'/f'NK225_{scene}.npz') as archive:
            old=archive['V00']
        with np.load(ROOT/'work/research145_report/combined_orders'/f'{scene}.npz') as archive:
            new=archive['C02']
        m=minute[scene]
        x=[datetime.fromisoformat(value) for value in m['times']]
        ax.plot(x,m['mid'],color='#9daec3',linewidth=1)
        ax.set_title(scene+' / '+title,fontsize=12)
        selected_new=new[new[:,2]==parent]
        selected_old=old[old[:,2]==parent]
        if scene.endswith('_Night'):
            selected_old=old[(old[:,2]==10000002)]
            selected_new=new[(new[:,2]>=10000002)&(new[:,2]<20000000)]
            begin, end = datetime(2026,10,17,2,0,tzinfo=JST), datetime(2026,10,17,5,55,tzinfo=JST)
            ax.set_xlim(begin,end)
            visible = [price for time,price in zip(x,m['mid']) if begin <= time <= end]
            ax.set_ylim(min(visible)-40,max(visible)+40)
        for orders,label,color,marker in ((selected_old,'元TG04','#ffcf80','o'),(selected_new,'C02','#5fceff','x')):
            for row in orders:
                time=datetime.fromtimestamp(float(ready['time_s'][int(row[0])]),JST)
                ax.scatter([time],[row[5]],color=color,marker=marker,s=48,zorder=4)
            if len(orders):
                ax.scatter([],[],color=color,marker=marker,label=label)
        ax.grid(alpha=.16)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=JST))
        ax.legend(loc='best')
        ax.set_ylabel('日経ラージ気配 pt')
        block=dict(session=scene,parent=parent,title=title,orders={})
        wanted={}
        for orders,label in ((selected_old,'V00'),(selected_new,'C02')):
            block['orders'][label]=[]
            for row in orders:
                decision,fill=int(row[1]),int(row[0])
                item=dict(decision_time=stamp(ready['time_s'][decision]),fill_time=stamp(ready['time_s'][fill]),
                    parent=int(row[2]),action='新規' if row[7] else '返済',side='買い' if row[3]>0 else '売り',
                    quantity=int(row[4]),price=float(row[5]),reason=int(row[6]),
                    decision_line=int(ready['seq'][decision])+1,fill_line=int(ready['seq'][fill])+1)
                block['orders'][label].append(item)
                if label=='C02' and (row[6]==14531 or (scene.endswith('_Night') and row[6]==14513 and row[3]>0)):
                    a=data['features'][decision]
                    item['known_features']={name:float(a[col]) for col,name in ((2,'40分効率'),(3,'5分差'),(4,'40分差'),
                        (5,'5分平均'),(6,'40分平均'),(9,'R'),(10,'中値'),(11,'短期ATR'),(12,'30秒変化R'),
                        (13,'120秒変化R'),(24,'自己OFI'),(26,'相手OFI'),(30,'20分平均'))}
                    wanted[item['decision_line']]=item
        raw_path=ROOT.parent/'JP_OSE_Data/future/NK225'/scene/'book.jsonl.gz'
        if wanted:
            with gzip.open(raw_path,'rt',encoding='utf-8') as stream:
                for number,line in enumerate(stream,1):
                    if number in wanted:
                        raw=json.loads(line)
                        assert raw['CurrentPriceTime']==wanted[number]['decision_time']
                        wanted[number]['decision_raw']=raw
                    if number>=max(wanted):break
        output.append(block)
    fig.suptitle('部分利確後の利益保護は改善と取り逃しを併せ持つ / 保存約定による比較',fontsize=15)
    fig.savefig(HERE/'新候補C02の改善と反例.png',dpi=150)
    (HERE/'新候補C02の具体判断と原板145.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('改善2例・反例2例の保存約定図と、当時の原板4行を保存')


if __name__=='__main__':
    main()
