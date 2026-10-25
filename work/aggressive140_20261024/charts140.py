"""追加取引が負けた局面と勝った局面を、原気配と時点までの図で比較する。"""

import pickle
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as md
import run140_v2 as r


def observed_rows(ready, quotes, start, decision_index, decision_time, own_market, before):
    """
    機能: 左図では自市場の原行順と他市場の厳密過去を守って描画行を選ぶ。
    引数: ready/quotes(dict)、start/decision_time(float)、decision_index(int)、own_market/before(bool)。
    返り値: ndarray[int]は観測可能な原行番号。右図は当該市場の事後全経路を返す。
    """
    times = np.asarray(ready['time_s'])
    mask = np.asarray(quotes['quote_valid'], dtype=bool) & (times >= start)
    if before:
        mask &= np.arange(len(times)) <= decision_index if own_market else times < decision_time
    rows = np.flatnonzero(mask)
    if len(rows):
        sampled = rows[::max(1, len(rows)//1800)]
        rows = np.unique(np.r_[sampled, rows[-1]])
    if before and len(rows):
        assert np.all(rows <= decision_index) if own_market else np.all(times[rows] < decision_time)
    return rows


def order_markers(ax, orders, times, quotes, decision_index, before, color, label):
    """
    機能: 実行済みの約定と、判断済み・未約定の新規を分けて描く。
    引数: ax(Axes)、orders/times(ndarray)、quotes(dict)、decision_index(int)、before(bool)、color/label(str)。
    返り値: None。未約定新規の星は判断行の中値であり、将来の約定価格を参照しない。
    """
    if not len(orders):
        return
    fill_rows = orders[:, 0].astype(int)
    decision_rows = orders[:, 1].astype(int)
    visible = fill_rows <= decision_index if before else np.ones(len(orders), dtype=bool)
    groups = ((1, 1, '^', '買い新規'), (1, -1, 'v', '売り新規'), (0, 0, 'x', '返済'))
    for new, side, marker, suffix in groups:
        mask = visible & (orders[:, 7] == new)
        if side:
            mask &= orders[:, 3] == side
        subset = orders[mask]
        if len(subset):
            rows = subset[:, 0].astype(int)
            assert not before or np.all(rows <= decision_index)
            when = [datetime.fromtimestamp(v, ZoneInfo('Asia/Tokyo')) for v in times[rows]]
            ax.scatter(when, subset[:, 5], c=color, marker=marker, s=35, label=label+'・'+suffix)
    # ----------------------------------------
    # 同一時刻でも後続原行の約定は左図へ入れず、当時の新規判断だけを星にする。
    if before:
        pending = (orders[:, 7] == 1) & (decision_rows <= decision_index) & (fill_rows > decision_index)
        for side, suffix in ((1, '買い判断'), (-1, '売り判断')):
            rows = decision_rows[pending & (orders[:, 3] == side)]
            if not len(rows):
                continue
            middle = (np.asarray(quotes['bid'])[rows]+np.asarray(quotes['ask'])[rows])*.5
            assert np.isfinite(middle).all(), '未約定の新規判断行の中値が欠測'
            when = [datetime.fromtimestamp(v, ZoneInfo('Asia/Tokyo')) for v in times[rows]]
            ax.scatter(when, middle, c=color, marker='*', s=130, edgecolors='#ffffff',
                       linewidths=.6, zorder=5, label=label+'・'+suffix+'（未約定）')


def draw():
    """
    機能: 追加による増減の大きい既知場を、両市場と注文位置の画像へ保存する。
    引数: なし。
    返り値: None。未来側の図は事後診断として明示し、入口の根拠へ流用しない。
    """
    plt.rcParams['font.family']='Meiryo'
    plt.style.use('dark_background')
    cases=[('TOPIX','C33','2026-10-06_Day'),('TOPIX','C33','2026-10-21_Day'),
           ('NK225','C36','2026-10-13_Day'),('NK225','C36','2026-10-20_Night')]
    manifest=r.read(r.HERE/'known_manifest140.json')
    directory=r.HERE/'charts';directory.mkdir(exist_ok=True)
    for symbol,method,scene in cases:
        item=next(x for x in manifest['packets'] if x['session']==scene)
        packet=pickle.loads((r.ROOT/item['path']).read_bytes());key=scene,symbol
        ready=packet['inputs'][key];q=packet['quotes'][key];ts=ready['time_s']
        with np.load(r.HERE/'known/measurement'/f'{symbol}_{scene}.npz') as f:
            base=f['B5'];actual=f[method]
        new=actual[actual[:,2]>=3_000_000]
        first=int(new[new[:,7]==1][:,1].min()) if len(new) else int(base[:,1].min())
        decision_time=float(ts[first])
        peer='TOPIX' if symbol=='NK225' else 'NK225';pk=scene,peer
        fig,axes=plt.subplots(2,2,figsize=(15,8),gridspec_kw={'width_ratios':[1,2]})
        for col in range(2):
            before=col==0
            for row,target in enumerate((symbol,peer)):
                rr=packet['inputs'][(scene,target)];qq=packet['quotes'][(scene,target)]
                ix=observed_rows(rr,qq,ready['start'],first,decision_time,target==symbol,before)
                dt=[datetime.fromtimestamp(v,ZoneInfo('Asia/Tokyo')) for v in rr['time_s'][ix]]
                ax=axes[row,col]
                ax.plot(dt,(qq['bid'][ix]+qq['ask'][ix])/2.,color='#79c5ff',linewidth=1)
                ax.set_ylabel(target);ax.grid(alpha=.15)
                ax.xaxis.set_major_formatter(md.DateFormatter('%H:%M',tz=ZoneInfo('Asia/Tokyo')))
                if row==0:
                    for orders,color,label in ((base,'#a4adb9','現行対照'),(new,'#ffce58','追加担当')):
                        order_markers(ax,orders,ts,q,first,before,color,label)
                    if ax.get_legend_handles_labels()[0]:
                        ax.legend(fontsize=7,loc='best')
            stamp=datetime.fromtimestamp(decision_time,ZoneInfo('Asia/Tokyo')).strftime('%H:%M:%S')
            axes[0,col].set_title(f'最初の追加判断 {stamp} まで（未来行を除外）' if before else '事後の全経路（予測には不使用）')
        fig.suptitle(f'{scene}　{symbol} / {method}　原板中値と約定位置')
        fig.text(.5,.012,'現行対照は独立運転の比較用であり、併用時の実採用を意味しません。星は未約定の判断中値です。',ha='center',fontsize=9,color='#c1cbd6')
        fig.tight_layout(rect=(0,.04,1,.96));fig.savefig(directory/f'{symbol}_{scene}_{method}.png',dpi=140);plt.close(fig)
    print('診断画像4件',flush=True)


if __name__=='__main__':draw()
