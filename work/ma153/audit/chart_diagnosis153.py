"""保存済みM09の損失上位場を独立原板照合と画像で調べる。売買の再生はしない。"""
from pathlib import Path
import json, math, csv
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'work/ma153'
OUT=BASE/'audit/charts'
JST=timezone(timedelta(hours=9))
plt.rcParams.update({'font.family':'Meiryo','figure.facecolor':'#101723','axes.facecolor':'#172131','axes.edgecolor':'#8391a5','axes.labelcolor':'#dce5f2','xtick.color':'#cbd5e1','ytick.color':'#cbd5e1','text.color':'#e5edf6','grid.color':'#334155','savefig.facecolor':'#101723','font.size':10})


def dt(ts):
    """機能: 秒時計を日本時刻へ変換する。引数: ts(float)。返り値: datetime。"""
    return datetime.fromtimestamp(ts,JST)


def raw_observations(scene,case):
    """機能: 原板を全行読取り、保存約定を照合し時間積分を独立作成する。引数: scene/case(dict)。返り値: dict。売買判断は作らない。"""
    checks={}
    for e in case['Events']:
        o=e['Order']
        checks[o['DecisionLine']]=(o['DecisionIndex'],o['DecisionTime'],o['DecisionBid'],o['DecisionAsk'])
        checks[e['FillLine']]=(e['FillIndex'],e['FillTime'],e['FillBid'],e['FillAsk'])
    points={};ends=[];areas=[];known=[]
    prior=scene['start'];start=None;lasttime=0;good=False;value=0;area=0;seconds=0;idx=0;matched=0;invalid=0
    def interval(end,isgood):
        """機能: 直前価格の区間積分を記録する。引数: end(float),isgood(bool)。返り値: なし。"""
        nonlocal area,seconds
        begin=ends[-1] if ends else start
        if end<=begin:return
        if isgood:area+=(end-begin)*value;seconds+=end-begin
        ends.append(end);areas.append(area);known.append(seconds)
    with Path(scene['books']['NK225']).open('rb') as stream:
        for line,b in enumerate(stream,1):
            q=json.loads(b);stamp=q.get('CurrentPriceTime')
            if stamp is None:continue
            try:at=datetime.fromisoformat(stamp).timestamp()
            except (TypeError,ValueError):continue
            if at<scene['start'] or at>scene['end'] or at>=scene['cutoff'] or at<prior:continue
            prior=at;bid=float(q.get('Buy1',{}).get('Price') or 0);ask=float(q.get('Sell1',{}).get('Price') or 0)
            okay=math.isfinite(bid) and math.isfinite(ask) and 0<bid<ask
            if line in checks:
                want=checks[line];assert (idx,at,bid,ask)==want,(scene['session'],line,want,(idx,at,bid,ask));matched+=1
            if start is None:start=lasttime=at
            if at>lasttime:
                if good:interval(min(at,lasttime+120),True)
                interval(at,False)
            good=okay;lasttime=at
            if okay:
                value=(bid+ask)/2
                points[at]=(bid,ask,value)
            else:invalid+=1
            idx+=1
    assert matched==len(checks),(matched,len(checks))
    ends=np.array([start]+ends);areas=np.array([0.]+areas);known=np.array([0.]+known)
    clocks=np.array(sorted(points));prices=np.array([points[x] for x in clocks])
    def avg(at,window):
        """機能: 完全既知窓の平均を補間積分から求める。引数: at(array),window(float)。返り値: array。"""
        a=np.interp(at,ends,areas);b=np.interp(at-window,ends,areas)
        k=np.interp(at,ends,known)-np.interp(at-window,ends,known)
        return np.where((at-window>=start)&(abs(k-window)<1e-6),(a-b)/window,np.nan)
    ma=avg(clocks,180);old=avg(clocks-30,180);slope=10000*(ma/old-1)*2
    # ----------------------------------------
    # 保存当時MAと独立積分の一致を検査する。未来の売買判断には使わない。
    for e in case['Events']:
        o=e['Order'];f=o['Feature']
        if not f['Known']:continue
        at=np.array([o['DecisionTime']]);m=avg(at,180)[0];p=avg(at-30,180)[0]
        assert abs(m-f['MA'])<1e-6 and abs(p-f['Previous'])<1e-6,(scene['session'],o['ID'],m,f)
    return {'times':clocks,'prices':prices,'ma':ma,'slope':slope,'matched':matched,'accepted':idx,'invalid':invalid}


def decorate(ax):
    """機能: 日本時刻の目盛と暗色グリッドを揃える。引数: ax(Axes)。返り値: なし。"""
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=JST));ax.grid(alpha=.4)


def draw(scene,case,raw,zoom):
    """機能: 全場と具体的失敗区間を画像化する。引数: scene/case/raw(dict),zoom(tuple)。返り値: list[Path]。"""
    events=case['Events'];times=np.array([dt(x) for x in raw['times']]);prices=raw['prices'];parents={p['ID']:p for p in case['Parents']}
    paths=[]
    for detail in (False,True):
        fig,axs=plt.subplots(3,1,figsize=(16,10),sharex=True,gridspec_kw={'height_ratios':[3,1.3,1.4]})
        lower,upper=zoom if detail else (scene['start'],scene['end'])
        mask=(raw['times']>=lower)&(raw['times']<=upper);ts=times[mask];p=prices[mask]
        axs[0].plot(ts,p[:,2],color='#d3e4ff',linewidth=.8,label='正常原板中値（同秒最後）')
        if detail:axs[0].fill_between(ts,p[:,0],p[:,1],color='#94a3b8',alpha=.22,label='買気配〜売気配')
        axs[0].plot(ts,raw['ma'][mask],color='#eebc64',linewidth=1.5,label='原板の時間加重3分MA')
        for e in events:
            at=e['FillTime']
            if not lower<=at<=upper:continue
            order=e['Order'];new=order['Action']=='new';side=order['Side'];color='#55dba9' if new and side>0 else '#ff8792' if new else '#7bb6ff'
            marker='^' if new and side>0 else 'v' if new else 'x'
            axs[0].scatter([dt(at)],[e['Price']],color=color,marker=marker,s=18+order['Quantity']*3 if detail else 14,alpha=.9,zorder=5)
            if detail and new:
                par=parents.get(order['ParentID']);label=f"{'買' if side>0 else '売'}{order['Quantity']}枚"
                if par:label+=f"\n{par['Realized']/10000:+.1f}万円"
                axs[0].annotate(label,(dt(at),e['Price']),xytext=(0,12 if side>0 else -25),textcoords='offset points',fontsize=7,ha='center',color=color)
        axs[0].set_ylabel('日経先物価格（pt）');axs[0].legend(loc='upper left',fontsize=9)
        axs[1].plot(ts,raw['slope'][mask],color='#eebc64',linewidth=.8);axs[1].axhline(0,color='#cbd5e1',linewidth=.6)
        for v in (-2.5,2.5):axs[1].axhline(v,color='#ef8796',linestyle='--',linewidth=.7)
        axs[1].set_ylabel('MA傾き\nbp/分');axs[1].text(.01,.92,'点線：初回10枚となる強さ ±2.5',transform=axs[1].transAxes,fontsize=8,va='top')
        et=[scene['start']];pl=[0.];gross=0
        for e in events:
            gross+=e['Gross'];et.append(e['FillTime']);pl.append(gross/10000)
        axs[2].step([dt(x) for x in et],pl,where='post',color='#aa9cff');axs[2].set_ylabel('累計確定収支\n万円');axs[2].axhline(0,color='#94a3b8',linewidth=.7)
        for ax in axs:decorate(ax);ax.set_xlim(dt(lower),dt(upper))
        title=f"日経 M09 / {scene['session']} / 収支 {case['Gross']/10000:+,.1f}万円 / 新規{case['NewOrders']}回"
        fig.suptitle(title+(" — 具体的な失敗区間" if detail else " — 全場"),fontsize=15)
        fig.text(.02,.015,'緑▲：買い新規、赤▼：売り新規、青×：返済。MA・数量は当時情報。線は描画用に同秒最後へ集約、約定は原行順。手数料0・ラージBBO代理。',fontsize=9)
        fig.tight_layout(rect=[0,.035,1,.96]);path=OUT/(scene['session']+('_拡大' if detail else '_全場')+'.png');fig.savefig(path,dpi=150);plt.close(fig);paths.append(path)
    return paths


def main():
    """機能: M09赤字上位3場を原板照合して図と診断JSONを保存する。引数: なし。返り値: なし。"""
    OUT.mkdir(parents=True,exist_ok=True)
    report=json.loads((BASE/'report153.json').read_text(encoding='utf-8'));manifest=json.loads((BASE/'data/入力目録153.json').read_text(encoding='utf-8'))
    method=next(m for m in report['methods'] if m['id']=='M09' and m['symbol']=='NK225');rows=sorted(method['rows'],key=lambda x:x['net'])[:3]
    summaries=[]
    ranges={'2026-10-23_Day':('2026-10-23T09:07:00+09:00','2026-10-23T09:20:00+09:00'),'2026-10-15_Night':('2026-10-15T21:27:00+09:00','2026-10-15T21:40:00+09:00'),'2026-10-15_Day':('2026-10-15T15:24:00+09:00','2026-10-15T15:35:00+09:00')}
    for row in rows:
        scene=next(s for s in manifest['sessions'] if s['session']==row['session']);saved=json.loads((ROOT/row['source']).read_text(encoding='utf-8'));case=next(c for c in saved['cases'] if c['Config']['id']=='M09')
        raw=raw_observations(scene,case);zoom=tuple(datetime.fromisoformat(x).timestamp() for x in ranges[row['session']]);paths=draw(scene,case,raw,zoom)
        byparent=defaultdict(list)
        for e in case['Events']:byparent[e['Order']['ParentID']].append(e)
        parents=[];previous=None
        for par in case['Parents']:
            es=byparent[par['ID']];assert len(es)==2 and es[0]['Order']['Action']=='new' and es[1]['Order']['Action']=='close'
            entry,exit=es;side=par['Side'];qty=par['EntryQuantity'];emid=(entry['FillBid']+entry['FillAsk'])/2;xmid=(exit['FillBid']+exit['FillAsk'])/2
            mid=side*(xmid-emid)*qty*100;spread=((entry['FillAsk']-entry['FillBid'])+(exit['FillAsk']-exit['FillBid']))/2*qty*100
            assert abs(mid-spread-par['Realized'])<1e-6
            order=entry['Order'];dm=(order['DecisionBid']+order['DecisionAsk'])/2
            record={'id':par['ID'],'side':side,'qty':qty,'entry':dt(entry['FillTime']).isoformat(),'exit':dt(exit['FillTime']).isoformat(),'entry_price':entry['Price'],'exit_price':exit['Price'],'net':par['Realized'],'mid_path':mid,'spread_cost':spread,'entry_slope':order['Feature']['Slope'],'entry_ma':order['Feature']['MA'],'decision_mid':dm,'wrong_price_side':side*(dm-order['Feature']['MA'])<=0,'same_side_within60':bool(previous and previous['Side']==side and par['EntryTime']-previous['CloseTime']<=60),'holding_seconds':par['CloseTime']-par['EntryTime'],'peak_gain':par['PeakGain'],'reason':par['ExitReason'],'decision_line':order['DecisionLine'],'fill_line':entry['FillLine'],'exit_line':exit['FillLine']}
            parents.append(record);previous=par
        summary={'session':row['session'],'net':case['Gross'],'entries':len(parents),'mid_path':sum(p['mid_path'] for p in parents),'spread_cost':sum(p['spread_cost'] for p in parents),'matched_rows':raw['matched'],'accepted_rows':raw['accepted'],'invalid_rows':raw['invalid'],'same_side_within60_count':sum(p['same_side_within60'] for p in parents),'same_side_within60_net':sum(p['net'] for p in parents if p['same_side_within60']),'wrong_price_side_count':sum(p['wrong_price_side'] for p in parents),'wrong_price_side_net':sum(p['net'] for p in parents if p['wrong_price_side']),'zoom_parents':[p for p in parents if zoom[0]<=datetime.fromisoformat(p['entry']).timestamp()<=zoom[1]],'paths':[str(p.relative_to(ROOT)).replace('\\','/') for p in paths]}
        summaries.append(summary);(OUT/(row['session']+'_全親診断.json')).write_text(json.dumps(parents,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k not in ['zoom_parents','paths']},ensure_ascii=False),flush=True)
    (OUT/'M09赤字上位3場の独立原板診断.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
