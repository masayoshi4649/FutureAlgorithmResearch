"""今回ナイトの価格と候補1の新規・確定損益を同一時計で図解する。"""

from datetime import timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=ROOT/'work/wave_v48/update_20261001'
OUT=ROOT/'アルゴリズム調査/00043_赤字原因とエントリー見送り'
JST=timezone(timedelta(hours=9))
SESSION='2026-09-30_Night'


def main() -> None:
    """機能: 過去の価格と実際の注文記録だけを暗色の図へ変換する。

    引数: なし。返り値: なし(None)。売買判定や既存結果を変更しない。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    inputs=pickle.loads((SOURCE/'new_inputs.pkl').read_bytes())
    ledgers=json.loads(gzip.decompress((SOURCE/'ledgers/F50_NONE__E11.json.gz').read_bytes()))
    plt.rcParams.update({'font.family':'Meiryo','font.size':10,'axes.unicode_minus':False,
        'figure.facecolor':'#0b121b','axes.facecolor':'#101d2d','axes.edgecolor':'#4c647d',
        'axes.labelcolor':'#dceafb','xtick.color':'#b8cbe1','ytick.color':'#b8cbe1',
        'text.color':'#e3edf8','grid.color':'#364b63','svg.fonttype':'path'})
    fig,axes=plt.subplots(3,1,figsize=(15,11),sharex=True,gridspec_kw={'height_ratios':[1,1,.7]})
    references={};rows=[]
    for ax,symbol,color in zip(axes[:2],('TOPIX','NK225'),('#7ddce1','#f8c07b')):
        ready=inputs[SESSION,symbol]
        ledger=next(r for r in ledgers if r['symbol']==symbol)
        path=ROOT/'candle_5min'/symbol/(SESSION+'.csv')
        references[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        bars=pd.read_csv(path)
        stamps=pd.to_datetime(bars['time'])
        x=mdates.date2num(stamps.dt.to_pydatetime())
        for xi,bar in zip(x,bars.itertuples()):
            tint='#68caa2' if bar.close>=bar.open else '#f08798'
            ax.vlines(xi,bar.low,bar.high,color=tint,linewidth=.7)
            height=max(abs(bar.close-bar.open),ready['tick']*.15)
            ax.add_patch(Rectangle((xi-1.9/1440,min(bar.close,bar.open)),3.8/1440,height,
                facecolor=tint,edgecolor=tint,linewidth=.4))
        times=np.asarray(ready['time_s'])
        for order in ledger['orders']:
            if order[6]!=20 or order[7]!=1:continue
            index,cid,side,price=int(order[0]),int(order[2]),int(order[3]),order[5]
            instant=pd.Timestamp(times[index],unit='s',tz='UTC').tz_convert(JST)
            xi=mdates.date2num(instant.to_pydatetime())
            marker='^' if side>0 else 'v';tint='#9dcfff' if side>0 else '#ffc878'
            ax.scatter([xi],[price],marker=marker,c=tint,s=50,edgecolors='#07101c',linewidths=.7,zorder=4)
            ax.annotate(str(cid+1),(xi,price),xytext=(3,9 if side>0 else -17),textcoords='offset points',
                fontsize=9,color=tint)
            rows.append(dict(銘柄=symbol,組=cid+1,新規=instant.isoformat(),方向='買' if side>0 else '売',価格=price))
        # ----------------------------------------
        # 損失の一組は背景を淡く塗り、下段には返済時点の確定損益だけを積み上げる。
        for cycle in ledger['cycles']:
            if cycle[3]>=0:continue
            begin,end=(pd.Timestamp(times[int(cycle[i])],unit='s',tz='UTC').tz_convert(JST) for i in (1,2))
            ax.axvspan(begin,end,color='#f27e97',alpha=.065,linewidth=0)
        trades=sorted(ledger['trades'],key=lambda t:t[7])
        closes=[pd.Timestamp(ready['start'],unit='s',tz='UTC').tz_convert(JST)]
        pnl=[0.]
        for trade in trades:
            closes.append(pd.Timestamp(times[int(trade[7])],unit='s',tz='UTC').tz_convert(JST))
            pnl.append(pnl[-1]+trade[10]*ledger['config']['point_value'])
        closes.append(pd.Timestamp(times[-1],unit='s',tz='UTC').tz_convert(JST));pnl.append(pnl[-1])
        axes[2].step(closes,pnl,where='post',color=color,linewidth=1.6,label=f'{symbol} 最終 {pnl[-1]:+,.0f}円')
        ax.set_ylabel(symbol+' 価格');ax.grid(alpha=.35)
    axes[2].axhline(0,color='#9badc0',linewidth=.7)
    axes[2].set_ylabel('確定損益（円）');axes[2].grid(alpha=.35)
    axes[2].legend(facecolor='#182b40',edgecolor='#4c647d',loc='lower left')
    axes[2].xaxis.set_major_locator(mdates.HourLocator(interval=1,tz=JST))
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=JST))
    axes[2].set_xlabel('日本時間：9/30夕方〜10/1早朝。番号は各銘柄の新規順。')
    fig.suptitle('9月30日ナイト｜候補1の入口と確定損益',fontsize=17,y=.985)
    axes[0].set_title('5分足：緑＝上昇足、赤＝下落足 ／ ▲買い新規・▼売り新規 ／ 薄い赤背景＝赤字の取引組',fontsize=10)
    fig.tight_layout(rect=[0,0,1,.97])
    for suffix in ('png','svg'):fig.savefig(OUT/('今回ナイトの売買図.'+suffix),dpi=135)
    plt.close(fig)
    payload=dict(元資料SHA256=references,新規一覧=rows,損益種別='返済時点の確定損益。含み損益ではない。',
        方式='F50_NONE__E11',描画='確定済みの過去の売買図。見送り判断には使わない。')
    (HERE/'chart_data.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('候補1の両市場5分足・新規18組・確定損益の図を保存。',flush=True)


if __name__=='__main__':main()
