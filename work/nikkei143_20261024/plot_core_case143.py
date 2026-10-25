"""同じ反発で変動平均と固定水準の判断が分かれた原板例を図にする。"""

from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import common143 as shared


def main():
    """
    機能: 10月22日日中の価格と公開平均、既知の実約定だけを図示する。
    引数: なし。
    返り値: None。売買を再生せず原資料と保存通知を描画する。
    """
    packets, cache, _ = shared.material()
    scene = '2026-10-22_Day'
    packet = shared.packet_from(next(x for x in packets if x['session']==scene))
    prepared, _, _, history = shared.previous.prepared(packet)
    data = prepared['NK225']; times=data['ready']['time_s']; mid=data['features'][:,10]
    base, _, _ = shared.sources(scene, cache)
    orders = base[base[:,2]==0]
    first = orders[orders[:,7]==1][0]
    anchor = float(history[scene,'NK225'][int(first[1]),1])
    tz = ZoneInfo('Asia/Tokyo')
    dates = [datetime.fromtimestamp(t,tz) for t in times]
    plt.rcParams.update({'font.family':'Yu Gothic','font.size':10,'axes.facecolor':'#111e30',
        'figure.facecolor':'#0c1523','text.color':'#dfe7f2','axes.labelcolor':'#dfe7f2',
        'xtick.color':'#c3cede','ytick.color':'#c3cede','axes.edgecolor':'#56657b'})
    fig, axes = plt.subplots(1,2,figsize=(16,6))
    for ax,begin,end,title in zip(axes,('09:45','09:55'),('14:05','10:35'),('その後の下落までの全体','早退を判断した付近')):
        lo=datetime.fromisoformat(f'2026-10-22T{begin}:00+09:00').timestamp()
        hi=datetime.fromisoformat(f'2026-10-22T{end}:00+09:00').timestamp()
        idx=np.flatnonzero((times>=lo)&(times<=hi)&np.isfinite(mid))
        sampled=idx[::max(1,len(idx)//12000)]
        ax.plot([dates[i] for i in sampled],mid[sampled],color='#91b7db',lw=.7,label='原板の中値')
        ax.plot([dates[i] for i in sampled],history[scene,'NK225'][sampled,1],color='#ebbf63',lw=1.2,label='当時公開済みの移動MA20')
        ax.axhline(anchor,color='#6ad0b1',ls='--',label=f'入口時の固定MA20 {anchor:,.1f}')
        old=datetime.fromisoformat('2026-10-22T10:17:15+09:00')
        ax.axvline(old,color='#ef7d8e',lw=1,ls=':')
        ax.scatter([old],[64485],color='#ef7d8e',marker='x',s=70,zorder=5)
        for order in orders:
            row=int(order[0]); t=times[row]
            if lo<=t<=hi:
                ax.scatter([dates[row]],[order[5]],marker='v' if order[7] else '^',
                    s=60,color='#72d5bb' if order[7] else '#c4a7ff',zorder=6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=tz))
        ax.set_title(title);ax.grid(alpha=.12);ax.legend(fontsize=8,loc='lower left')
    fig.suptitle('10月22日デイ：短い反発で「下落の根拠が崩れた」と誤認しない',fontsize=16)
    fig.text(.5,.02,'旧O03は10:17に返済して −50,384円。固定水準と20分方向を分けたO17は元の売買を保持し +323,616円。\n価格時計・ラージ気配による日経mini代理。未来の下落は事後の図示だけに使用。',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.10,1,.94))
    fig.savefig(shared.HERE/'固定平均と移動平均の反例143.png',dpi=150)


if __name__=='__main__':
    main()
