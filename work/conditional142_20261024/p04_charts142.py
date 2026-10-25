"""P04最大損失場を原行高安を保持した二市場同軸の画像へ描く。"""

import json
import pickle
from datetime import datetime,timezone,timedelta
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import run142

HERE,ROOT=run142.HERE,run142.ROOT


def draw(packet,records):
    """
    機能: 原行中値の1分高安・終値と保存約定位置を同じ時計軸に描画する。
    引数: packet(dict)は一場の原行資料、records(list[dict])は保存P04親。
    返り値: strは生成したPNG絶対パス。足集約は事後の描画専用。
    """
    scene=packet['session'];fig,axes=plt.subplots(2,1,figsize=(20,10),sharex=True)
    fig.patch.set_facecolor('#0e1420');plt.rcParams['font.family']=['Yu Gothic','Meiryo','DejaVu Sans']
    for ax,symbol in zip(axes,('NK225','TOPIX')):
        ax.set_facecolor('#101c2c');ax.tick_params(colors='#cbd5e1');ax.grid(color='#385066',alpha=.35)
        r=packet['inputs'][scene,symbol];q=packet['quotes'][scene,symbol]
        valid=q['quote_valid'];t=r['time_s'][valid];mid=(q['bid'][valid]+q['ask'][valid])*.5
        minutes=np.floor(t/60.).astype(np.int64);begin=np.r_[0,np.flatnonzero(np.diff(minutes))+1]
        finish=np.r_[begin[1:]-1,len(minutes)-1]
        hi=np.maximum.reduceat(mid,begin);lo=np.minimum.reduceat(mid,begin);x=(minutes[begin]*60.+30.-r['start'])/60.
        ax.vlines(x,lo,hi,color='#94b9df',alpha=.8,linewidth=.7,label='1分の全原行中値高安')
        ax.plot(x,mid[finish],color='#b9d8f7',linewidth=.65,label='1分最終中値')
        ps=[p for p in records if p['session']==scene and p['symbol']==symbol]
        for side,color,marker,label in ((1,'#54e3a7','^','買い新規'),(-1,'#ff8794','v','売り新規')):
            chosen=[p for p in ps if p['side']==side]
            ax.scatter([(p['entry_time']-r['start'])/60. for p in chosen],[p['entry_price'] for p in chosen],s=30,color=color,marker=marker,label=label,zorder=5)
        for p in ps:
            color='#54e3a7' if p['net']>0 else '#ff8794'
            ax.plot([(p['entry_time']-r['start'])/60.,(p['exit_time']-r['start'])/60.],[p['entry_price'],p['exit_price']],color=color,alpha=.25,linewidth=.7)
        ax.scatter([(p['exit_time']-r['start'])/60. for p in ps],[p['exit_price'] for p in ps],s=16,color='#eeeeee',marker='x',linewidths=.7,label='返済',zorder=6)
        net=sum(p['net'] for p in ps);spread=sum(p['spread_drag'] for p in ps)
        ax.set_title(f'{symbol} / {len(ps)} 親 / 純収支 {net:+,.0f}円 / 中値から気配差の負担 {spread:,.0f}円',color='#e2e8f0',fontsize=13)
        ax.legend(loc='upper left',facecolor='#182638',edgecolor='#385066',labelcolor='#d5e3f3',ncol=5,fontsize=8)
    start=float(r['start']);axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda m,_:datetime.fromtimestamp(start+m*60.,timezone(timedelta(hours=9))).strftime('%H:%M')))
    axes[-1].set_xlabel('日本時間・価格時計（受信時計とは異なる）',color='#cbd5e1')
    fig.suptitle(scene+' / P04 保存注文・各初回2枚（全セッション）',color='#e2e8f0',fontsize=16)
    fig.tight_layout(rect=(0,0,1,.96));dest=HERE/'figures'/f'P04_{scene}_二市場全景.png';dest.parent.mkdir(exist_ok=True)
    fig.savefig(dest,dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
    return str(dest.resolve())


def main():
    """
    機能: 日経の最大赤字昼2場・夜1場を描画する。
    引数: なし。
    返り値: None。新金融再生0回で画像を保存する。
    """
    plt.rcParams['font.family']=['Yu Gothic','Meiryo','DejaVu Sans']
    saved=json.loads((HERE/'P04全親の状態別と気配差分解142.json').read_text(encoding='utf8'))
    packets,_,_=run142.first.material()
    for scene in ('2026-09-29_Day','2026-10-13_Day','2026-09-28_Night'):
        item=next(p for p in packets if p['session']==scene);packet=pickle.loads((ROOT/item['path']).read_bytes())
        print(draw(packet,saved['records']),flush=True)


if __name__=='__main__':main()
