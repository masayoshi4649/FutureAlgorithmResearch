"""原気配上の売買と全玉時価評価を、基準と改修案で画像比較する。"""

import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pickle
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ENGINE=ROOT/'work/research145_engine'
RESIDUAL=ROOT/'work/research145_residual'
JST=timezone(timedelta(hours=9))


def orders(method,scene):
    """
    機能: 保存注文だけを読み、新しい売買を作らない。
    引数: method(str)、scene(str)。返り値: ndarrayは全約定。
    """
    if method=='TG04Z' or method.startswith('V'):
        path=ENGINE/'measurement'/f'NK225_{scene}.npz'
    elif method.startswith('C'):
        path=HERE/'combined_orders'/f'{scene}.npz'
    elif method.startswith('D'):
        path=ROOT/'work/research145_roles/orders'/f'{scene}.npz'
    else:
        path=RESIDUAL/'orders'/f'{scene}.npz'
    with np.load(path) as data:
        return data['V00' if method=='TG04Z' else method].copy()


def equity(rows,quotes):
    """
    機能: 実現現金と全建玉の返済側気配による評価額を計算する。
    引数: rows(ndarray)、quotes(dict)。返り値: ndarrayは全行の口座評価。
    """
    n=len(quotes['bid']);cash=np.zeros(n);long=np.zeros(n);short=np.zeros(n)
    for row in rows:
        i,side,qty,price,new=int(row[0]),int(row[3]),int(row[4]),row[5],bool(row[7])
        cash[i]-=side*qty*price*100.
        position=long if (side>0 if new else side<0) else short
        position[i]+=qty if new else -qty
    cash=np.cumsum(cash);long=np.cumsum(long);short=np.cumsum(short)
    return cash+long*np.asarray(quotes['bid'])*100.-short*np.asarray(quotes['ask'])*100.


def main(method,scenes):
    """
    機能: 成功・失敗両ケースを原価格時計の画像へまとめる。
    引数: method(str)、scenes(list[str])。返り値: None。全行評価後に表示だけ間引く。
    """
    plt.rcParams['font.family']='Yu Gothic'
    plt.style.use('dark_background')
    for scene in scenes:
        with (ENGINE/'cache'/f'{scene}.pkl').open('rb') as stream:
            _,data,_,_,_=pickle.load(stream)
        q=data['quotes'];t=data['ready']['time_s']
        sample=np.unique(np.r_[np.arange(0,len(t),max(1,len(t)//3500)),len(t)-1])
        times=[datetime.fromtimestamp(float(t[i]),JST) for i in sample]
        mid=(np.asarray(q['bid'])+q['ask'])*.5
        fig,axes=plt.subplots(3,1,figsize=(14,9),sharex=True,gridspec_kw={'height_ratios':[2,2,2]})
        for ax,code,color in zip(axes[:2],['TG04Z',method],['#a1bdd7','#65dbb1']):
            rows=orders(code,scene)
            ax.plot(times,mid[sample],color='#b7bfd2',lw=.7)
            for new,marker in [(True,'^'),(False,'v')]:
                selected=rows[(rows[:,7]>0)==new]
                for side,sidecolor in [(1,'#ffb46d'),(-1,'#73baff')]:
                    chosen=selected[selected[:,3]==side]
                    ax.scatter([datetime.fromtimestamp(float(t[int(r[0])]),JST) for r in chosen],chosen[:,5],
                        s=18+chosen[:,4]*3,marker=marker,color=sidecolor,
                        label=('新規' if new else '返済')+('買い' if side>0 else '売り'),alpha=.8)
            eq=equity(rows,q)
            axes[2].plot(times,eq[sample]/10000,color=color,lw=1.2,label=code)
            ax.set_title(code+' の全約定（矢印の大きさは枚数）',loc='left',fontsize=11)
            ax.legend(loc='upper right',fontsize=8,ncol=4)
            ax.set_ylabel('日経価格')
        axes[2].set_ylabel('全玉評価込み収支（万円）');axes[2].legend()
        axes[2].axhline(0,color='#738194',lw=.6)
        axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=JST))
        for ax in axes:ax.grid(alpha=.15)
        fig.suptitle(scene+'：基準と'+method+'の比較（手数料0・ラージ気配代理）',fontsize=15)
        fig.tight_layout()
        target=HERE/f'原板上の比較_{scene}_{method}.png'
        fig.savefig(target,dpi=130);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('method')
    parser.add_argument('scenes',nargs='+')
    args=parser.parse_args();main(args.method,args.scenes)
