"""既存Q01の負け・勝ち・当夜を同じ時間軸で図示する事後診断。"""

from pathlib import Path
import pickle
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from decompose_saved import HERE, OLD


def main():
    """保存約定と分末価格を重ねた図を出力する。

    引数: なし。
    返り値: None。図の極値や事後形状を売買入力には使わない。
    """
    plt.rcParams.update({'font.family':'Yu Gothic','font.size':10,'axes.unicode_minus':False})
    scenes=['2026-10-16_Night','2026-10-08_Night','2026-10-21_Night','2026-10-26_Night']
    figure,axes=plt.subplots(4,1,figsize=(14,12),sharex=True,facecolor='#101821')
    for ax,scene in zip(axes,scenes):
        with (OLD/'inputs'/f'{scene}.pkl').open('rb') as stream:
            packet=pickle.load(stream)
        data=packet['data']
        times=data['ready']['time_s']; start=float(data['ready']['start'])
        q=data['quotes']; good=q['quote_valid']; mid=(q['bid']+q['ask'])/2
        ids=np.flatnonzero(good & (times>=start) & (times<start+5.25*3600))
        buckets=((times[ids]-start)//60).astype(int)
        last=np.r_[buckets[1:]!=buckets[:-1],True]
        line=ids[last]; origin=mid[ids[0]]
        ax.set_facecolor('#101821')
        ax.plot((times[line]-start)/3600,mid[line]-origin,color='#dce6f2',lw=1)
        with np.load(OLD/'round2/orders'/f'{scene}.npz') as source:
            orders=source['Q01']
        for sign,color,label,marker in ((1,'#5ab9ef','買い新規','^'),(-1,'#ffa05b','売り新規','v')):
            rows=orders[(orders[:,7]==1)&(orders[:,3]==sign)]
            i=rows[:,0].astype(int)
            ax.scatter((times[i]-start)/3600,rows[:,5]-origin,s=35,c=color,marker=marker,label=label,zorder=3)
        ax.axhline(0,color='#536174',lw=.6)
        ax.grid(color='#293847',alpha=.7)
        ax.tick_params(colors='#dce6f2')
        for spine in ax.spines.values(): spine.set_color('#526277')
        ax.set_ylabel('最初の中値からの変化(pt)',color='#dce6f2')
        ax.set_title(scene.replace('_Night',' ナイト')+('（21:13までの途中）' if '10-26' in scene else ''),loc='left',color='#dce6f2')
    axes[0].legend(loc='upper left',facecolor='#101821',labelcolor='#dce6f2')
    axes[-1].set_xticks(np.arange(0,5.5,.5),[f'{17+int(x):02}:{30 if x%1 else 0:02}' for x in np.arange(0,5.5,.5)])
    axes[-1].set_xlabel('日本時間',color='#dce6f2')
    axes[-1].set_xlim(0,5.25)
    figure.suptitle('同じ勢い入口が選んだ場所：Q01の保存経路',color='#dce6f2',fontsize=15)
    figure.tight_layout(rect=(0,0,1,.97))
    figure.savefig(HERE/'Q01の失敗日と成功日の入口.png',dpi=140,facecolor=figure.get_facecolor())
    plt.close(figure)


if __name__=='__main__':
    main()
