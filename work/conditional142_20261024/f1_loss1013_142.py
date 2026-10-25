"""2026-10-13ナイトF1/J04の保存損失2親を原板と既存判定へ接続する。"""

import json
import pickle
from datetime import datetime,timezone,timedelta
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import run142
from supplement_loss_audit141 import parent_record,cash,stamp
from loss_raw141 import clean

HERE,ROOT=run142.HERE,run142.ROOT
SCENE='2026-10-13_Night'


def duration(times,mask):
    """
    機能: 15秒超の時計空白を接続せず、既存判定資格の最長継続を測る。
    引数: times(ndarray)、mask(ndarray[bool])は保存保有区間の時計と観測資格。
    返り値: dictは成立原行数と最長秒。新注文や仮想損益を作らない。
    """
    start=None;best=0.;begin=end=None
    for i,ok in enumerate(mask):
        if not ok:start=None;continue
        if start is None or (i and times[i]-times[i-1]>15.):start=times[i]
        span=times[i]-start
        if span>best:best=float(span);begin=float(start);end=float(times[i])
    return dict(rows=int(mask.sum()),max_seconds=best,begin=stamp(begin) if begin else None,end=stamp(end) if end else None)


def image(packet,history,parents):
    """
    機能: 2親それぞれの前後を、二市場の高安保持価格と公開平均で画像化する。
    引数: packet/history(dict)、parents(list[dict])は保存資料と診断。
    返り値: strは生成PNGの絶対パス。チャートは事後診断専用。
    """
    plt.rcParams['font.family']=['Yu Gothic','Meiryo','DejaVu Sans']
    fig,axes=plt.subplots(2,2,figsize=(17,8),sharex='col');fig.patch.set_facecolor('#0e1420')
    for col,p in enumerate(parents):
        first=p['orders'][0];last=p['orders'][-1]
        entry=first['fill_epoch'];end=last['fill_epoch'];origin=entry-15*60.
        for row,symbol in enumerate(('NK225','TOPIX')):
            ax=axes[row,col];ax.set_facecolor('#101c2c');ax.tick_params(colors='#cbd5e1');ax.grid(color='#385066',alpha=.3)
            r=packet['inputs'][SCENE,symbol];q=packet['quotes'][SCENE,symbol]
            valid=q['quote_valid']&(r['time_s']>=origin)&(r['time_s']<=end+10*60.)
            times=r['time_s'][valid];mid=(q['bid'][valid]+q['ask'][valid])*.5
            cells=np.floor(times/15.).astype(int);begin=np.r_[0,np.flatnonzero(np.diff(cells))+1];finish=np.r_[begin[1:]-1,len(cells)-1]
            x=(cells[begin]*15.+7.5-origin)/60.
            ax.vlines(x,np.minimum.reduceat(mid,begin),np.maximum.reduceat(mid,begin),color='#9fc8f0',linewidth=.8)
            ax.plot(x,mid[finish],color='#bfdcf6',linewidth=.85,label='15秒高安・最終中値')
            mean=history[SCENE,symbol][valid,1];ax.plot((times-origin)/60.,mean,color='#f9cf68',linewidth=.85,label='当時公開MA20')
            ax.axvspan((entry-origin)/60.,(end-origin)/60.,color='#ff6178',alpha=.15,label='日経の保有区間')
            if symbol=='NK225':
                ax.scatter([(entry-origin)/60.],[first['price']],s=55,color='#ff8794',marker='v',label='売り5枚')
                ax.scatter([(end-origin)/60.],[last['price']],s=55,color='#ffffff',marker='x',label='買い返済5枚')
            ax.set_title(f'{symbol} / {p["role"]}'+(f' / {p["net"]:+,.0f}円' if row==0 else ''),color='#e2e8f0')
            ax.xaxis.set_major_formatter(FuncFormatter(lambda m,_,o=origin:datetime.fromtimestamp(o+m*60.,timezone(timedelta(hours=9))).strftime('%H:%M')))
            ax.legend(facecolor='#182638',edgecolor='#385066',labelcolor='#d5e3f3',fontsize=8,loc='best')
    fig.suptitle('F1 / 2026-10-13 ナイト（17:00開始） / 売り2回の逆行',color='#e2e8f0',fontsize=16)
    fig.tight_layout(rect=(0,0,1,.95));target=HERE/'F1_1013夜の価格図.png';fig.savefig(target,dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
    return str(target.resolve())


def main():
    """
    機能: 保存注文・原文SHA・旧準備診断を照合し、F1の損失原因を保存する。
    引数: なし。
    返り値: None。金融エンジンを呼ばず、新規JSONとPNGだけ作成する。
    """
    packets,_,_=run142.first.material();item=next(p for p in packets if p['session']==SCENE)
    packet=pickle.loads((ROOT/item['path']).read_bytes());data,inputs,market,history=run142.prepared(packet)
    k=(SCENE,'NK225');r=inputs[k];q=packet['quotes'][k];h=history[k];m=market[k]
    raw={}
    for symbol in ('NK225','TOPIX'):
        with np.load(ROOT/'work/raw_diagnosis141_20261024/raw_features'/f'{symbol}_{SCENE}.npz') as z:raw[symbol]={key:z[key] for key in z.files}
    with np.load(HERE/'measurement'/f'NK225_{SCENE}.npz') as z:orders={key:z[key] for key in ('J04','Z04','B5','A_C13')}
    with np.load(HERE/'traces'/f'NK225_{SCENE}.npz') as z:trace=z['C13']
    assert len(orders['A_C13'])==len(trace)==0
    assert np.array_equal(orders['J04'],orders['Z04'])
    assert np.array_equal(orders['J04'][:,[0,1,3,4,5,7,9]],orders['B5'][:,[0,1,3,4,5,7,9]])
    previous=json.loads((ROOT/'work/visual_pdca129_20261020/night/強逆流準備破棄の全親差分と新準備.json').read_text(encoding='utf8'))
    previous=next(x for x in previous['rows'] if x['method']=='NV25' and x['session']==SCENE and x['symbol']=='NK225')
    parents=[]
    for pid in sorted(np.unique(orders['J04'][:,2]),key=lambda pid:orders['J04'][orders['J04'][:,2]==pid][0,0]):
        rows=orders['J04'][orders['J04'][:,2]==pid]
        p=parent_record(rows,r,q,h,m,raw['NK225'],inputs[SCENE,'TOPIX'],raw['TOPIX'])
        p['gross']=float(np.sum(-rows[:,3]*rows[:,4]*rows[:,5]*100.));p['fees']=float(rows[:,9].sum())
        p['role']='補完 Z04' if rows[0,8]==999 else '主担当 NV25'
        lo,hi=int(rows[0,0]),int(rows[-1,0]);side=int(rows[0,3]);ix=np.arange(lo,hi+1)
        normal=q['quote_valid'][ix];fresh=m[ix,11]==1.
        short=fresh&np.all(np.isfinite(m[ix,4:8]),axis=1)&np.all(side*m[ix,4:8]<0.,axis=1)
        medium=(side*h[ix,7]<0.)&(side*h[ix,11]<0.)
        strong=fresh&(side*m[ix,5]<-.25)&(side*m[ix,7]<-.25)
        p['existing_conditions']=dict(short_four_inverse=duration(r['time_s'][ix],normal&short),
            medium20_both_inverse=duration(r['time_s'][ix],normal&medium),
            Z04_exit_qualification=duration(r['time_s'][ix],normal&short&medium),
            both120_over_quarter=duration(r['time_s'][ix],normal&strong))
        for o in p['orders']:
            i=o['decision']['row'];fill=o['fill_row'];o['fill_epoch']=float(r['time_s'][fill])
            o['decision']['public_atr']=float(r['atr'][i]);o['decision']['features30']=data['NK225']['features'][i]
            o['decision']['source_path']=str(raw['NK225']['source_path'])
            o['decision']['peer_source_path']=str(raw['TOPIX']['source_path'])
            o['fill_bbo']=dict(bid=float(q['bid'][fill]),ask=float(q['ask'][fill]),seq=int(r['seq'][fill]),line_no=int(r['seq'][fill])+1)
        if rows[0,8]!=999:
            assert previous['decision_row']==int(rows[0,1]) and previous['entry']==rows[0,5] and previous['exit']==rows[-1,5]
            p['original_preparation']=previous
        parents.append(p)
    notes=json.loads((HERE/'notes'/f'NK225_{SCENE}_Z04.json').read_text(encoding='utf8'))
    for n in notes:n['価格時計表示']=stamp(n['価格時計'])
    chart=image(packet,history,parents)
    output=dict(session=SCENE,starts='2026-10-13T17:00:00+09:00',ends='2026-10-14T06:00:00+09:00',
        method='F1 = J04（夜間Z04＋追加C13）',financial_replays=0,API=0,
        profit=0.,loss=-cash(orders['J04']),net=cash(orders['J04']),gross=sum(p['gross'] for p in parents),fees=sum(p['fees'] for p in parents),
        parents=parents,notes=notes,additional_orders=0,additional_trace_rows=0,
        legacy_economic_orders_unchanged=True,chart=chart,
        limitations=['板数量の変化から参加者の意図を確定していない。','時刻は原資料の価格時計であり受信時計ではない。',
            'C13は保存注文・traceが0で実参加なし。どの未成立段階が何回あったかはこの保存traceからは確定しない。',
            '主担当準備の旧JSONはmicro10枚会計。その収支をmini5枚へ流用せず、今回保存注文から独立計算した。',
            '入口を避ければ他場も改善するという有効性は、この一場の診断だけからは主張しない。'])
    with (HERE/'F1_1013夜の損失診断.json').open('x',encoding='utf8') as f:json.dump(clean(output),f,ensure_ascii=False,indent=2,allow_nan=False)
    for p in parents:
        print(p['role'],p['net'],p['maximum_favorable_points'],p['existing_conditions'],flush=True)
    print(chart,flush=True)


if __name__=='__main__':main()
