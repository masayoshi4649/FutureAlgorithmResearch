"""保存原本の公開済み情報だけで独立96方式を再生する実行可能な研究器。"""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import gzip
import pickle
import socket
import sys
import numpy as np
import pandas as pd
from numba import njit
from design import HERE, catalog, freeze

ROOT = HERE.parents[2]
SOURCES = ['work/wave_v47', 'work/wave_v48/update_20260930', 'work/wave_v48/update_20261001',
           'work/wave_v50/update_20261001_day', 'work/wave_v50/update_20261002_two',
           'work/wave_v50/update_20261007_added']
FIELDS = ['time_s','seq','last','atr','start','limit','session','symbol','tick']
REASONS = {1:'初期損切り',2:'利益追跡',3:'進行不足の時間切れ',4:'両市場反転',5:'保有時間上限',6:'平均回帰到達',7:'半数利確',8:'セッション返済'}


def save(name: str, value: object) -> None:
    """機能: 今回領域だけへJSONまたは圧縮JSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path=HERE/name;path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode('utf8')
    path.write_bytes(gzip.compress(data,mtime=0) if path.suffix=='.gz' else data)


def read(name: str) -> object:
    """機能: 保存済み今回成果を読む。

    引数: name(str)。返り値: 保存値(object)。
    """
    path=HERE/name;data=path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


def deny(*args, **kwargs) -> None:
    """機能: 再生時の外部接続を拒否する。

    引数: 任意の引数。返り値: なし(None)、常に例外。
    """
    raise RuntimeError('保存原本だけで実行します')


def load() -> tuple[dict,dict]:
    """機能: 46口座の最小配列と公開済み板特徴を読む。

    引数: なし。返り値: 原本入力と板特徴(tuple[dict,dict])。
    """
    inputs,frames={},{}
    for n,source in enumerate(SOURCES):
        prefix='' if n==0 else 'new_'
        found=pickle.loads((ROOT/source/(prefix+'inputs.pkl')).read_bytes())
        assert not(set(found)&set(inputs))
        inputs.update({key:{f:row[f] for f in FIELDS} for key,row in found.items()})
        frames.update(pickle.loads((ROOT/source/(prefix+'features_depth.pkl')).read_bytes()))
    assert len(inputs)==len(frames)==46
    return inputs,frames


def asof(times: np.ndarray, values: np.ndarray, targets: np.ndarray, default: float=np.nan) -> np.ndarray:
    """機能: 参照時刻以前に公開された最後の値だけを取得する。

    引数: times/values/targets(ndarray)、default(float)。返り値: 参照列(ndarray)。
    """
    pos=np.searchsorted(times,targets,side='right')-1
    result=np.full(len(targets),default,dtype=float);valid=pos>=0
    result[valid]=np.asarray(values)[pos[valid]]
    return result


def bars(ready: dict, frame: pd.DataFrame, window: int, table: pd.DataFrame|None=None) -> dict:
    """機能: 当該場の公開済み確定足と板から過去窓の指標を作る。

    引数: ready(dict)、frame(DataFrame)、window(int)、table(DataFrame|None)。返り値: 指標辞書(dict)。
    """
    if table is None:
        table=pd.read_csv(ROOT/'candle_1min'/ready['symbol']/(ready['session']+'.csv'))
    times=pd.to_datetime(table.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
    valid=table.closed.astype(str).str.lower().eq('true').to_numpy() & (times<=ready['time_s'][-1]) & (times>=ready['start']+120)
    t=times[valid];tab=table.loc[valid].reset_index(drop=True)
    close=tab.close.astype(float);high=tab.high.astype(float);low=tab.low.astype(float)
    atr=asof(ready['time_s'],ready['atr'],t)
    fast=close.ewm(span=max(3,window//3),adjust=False,min_periods=max(3,window//3)).mean()
    mean=close.ewm(span=window,adjust=False,min_periods=window).mean()
    er=close.diff(window).abs()/close.diff().abs().rolling(window,min_periods=window).sum().replace(0,np.nan)
    ft=frame.time_s.to_numpy(float)
    cumulative=np.r_[0.,frame.ofi_signed.fillna(0).to_numpy(float).cumsum()]
    absolute=np.r_[0.,frame.ofi_abs.fillna(0).to_numpy(float).cumsum()]
    left=np.searchsorted(ft,t-120,side='right');right=np.searchsorted(ft,t,side='right')
    ofi=(cumulative[right]-cumulative[left])/np.maximum(1,absolute[right]-absolute[left])
    distance=asof(ft,frame.dflow_near.to_numpy(float),t)
    model=dict(time_s=t, close=close.to_numpy(), atr=atr, er=er.to_numpy(), mean=mean.to_numpy(),
               mom=(close.diff(window)/atr).to_numpy(), short=(close.diff(3)/atr).to_numpy(),
               gap=((fast-mean)/atr).to_numpy(), slope=(mean.diff(3)/atr).to_numpy(),
               fastdev=((close-fast)/atr).to_numpy(), deviation=((close-mean)/atr).to_numpy(),
               upper=high.shift(1).rolling(window,min_periods=window).max().to_numpy(),
               lower=low.shift(1).rolling(window,min_periods=window).min().to_numpy(),
               ofi=ofi, distance=distance)
    return model


def signals(spec: dict, models: dict, key: tuple) -> np.ndarray:
    """機能: 両市場の現在公開情報から新規・途中判断・回帰目標を出力する。

    引数: spec(dict)、models(dict)、key(tuple)。返り値: 時刻/方向/局面/ATR/平均/反転方向/効率(ndarray)。
    """
    own=models[key];peer=models[(key[0],'TOPIX' if key[1]=='NK225' else 'NK225')]
    t=own['time_s'];c=spec['confirmation'];f=spec['family']
    peer_m=asof(peer['time_s'],peer['mom'],t);peer_s=asof(peer['time_s'],peer['short'],t)
    peer_er=asof(peer['time_s'],peer['er'],t)
    peer_time=asof(peer['time_s'],peer['time_s'],t)
    sign=np.sign(own['mom']);er_threshold=.25+.10*c
    trend=(np.abs(own['mom'])>.5+.25*c)&(own['er']>=er_threshold)&(own['gap']*sign>.10)&(own['slope']*sign>0)
    fresh=(own['short']*sign>.05+.10*c)&(peer_s*sign>.05+.10*c)&(peer_m*sign>.25)
    follow=trend&fresh
    side=np.zeros(len(t));mode=np.zeros(len(t))
    if f in (0,4,5):
        allow=follow.copy()
        if f==5: allow &= (own['ofi']*sign>.02)&(own['distance']*sign>0)
        side[allow]=sign[allow];mode[allow]=1
    elif f==1:
        allow=follow&(np.abs(own['fastdev'])<=.75)
        side[allow]=sign[allow];mode[allow]=1
    elif f==2:
        breakout=np.where(own['close']>own['upper']+.05*own['atr'],1,np.where(own['close']<own['lower']-.05*own['atr'],-1,0))
        allow=(breakout!=0)&(own['short']*breakout>.05+.1*c)&(peer_s*breakout>0)&(peer_m*breakout>0)
        side[allow]=breakout[allow];mode[allow]=1
    if f in (3,4):
        reverse=-np.sign(own['deviation'])
        allow=(own['er']<=.20)&(np.abs(own['deviation'])>=.8+.2*c)&(own['short']*reverse>.1+.1*c)
        allow &= ~((peer_er>=.3)&(peer_m*reverse<-.5))
        side[allow]=reverse[allow];mode[allow]=2
    invalid=(~np.isfinite(own['atr']))|(own['atr']<=0)|(~np.isfinite(peer_time))|(t-peer_time>120)|(t<t[0]+1200)
    side[invalid]=0;mode[invalid]=0
    # ----------------------------------------
    # 入口の遅い方向に拘束されず、直近三分が両市場で反対なら途中判断に渡す。
    adverse=np.where((own['short']>.25)&(peer_s>.25),1,np.where((own['short']<-.25)&(peer_s<-.25),-1,0))
    adverse[invalid]=0
    return np.column_stack([t,side,mode,own['atr'],own['mean'],adverse,own['er']])


@njit(cache=True)
def replay(time_s: np.ndarray, seq: np.ndarray, prices: np.ndarray, events: np.ndarray,
           start: float, limit: float, quantity: int, point_value: float, stop_width: float,
           activation: float, trail_width: float, max_minutes: float, cooldown: float,
           exit_id: int, finish: bool=True) -> tuple:
    """機能: 次原本行の価格約定で新規・途中・返済を一度ずつ順次処理する。

    引数: 原本時刻/行/価格と指標(ndarray)、期間/数値条件(float)、quantity/exit_id(int)、finish(bool)。
    返り値: 決済台帳・注文台帳・含み損益を含む最大下落・最終枚数(tuple)。
    """
    trades=np.zeros((50000,16));orders=np.zeros((100000,10));nt=no=0
    side=qty=0;entry=entry_t=entry_atr=extreme=target=0.;entry_i=0;entry_mode=0
    pending=0;pending_side=0;pending_reason=0;pending_qty=0;pending_decision=0.;pending_seq=0;pending_atr=0.;pending_mode=0;pending_target=0.
    current=np.zeros(7);pointer=0;realized=0.;peak=0.;drawdown=0.;cool_until=start;partial=False;campaign_profit=0.
    for i in range(len(prices)):
        now=time_s[i];price=prices[i]
        if not np.isfinite(price) or price<=0: continue
        # ----------------------------------------
        # 前行の判断を約定。新規時点の数量・ATR・局面を保持する。
        if pending==1:
            side=pending_side;qty=quantity;entry=price;entry_t=now;entry_atr=pending_atr;extreme=price
            entry_i=i;entry_mode=pending_mode;target=pending_target;partial=False;campaign_profit=0.
            orders[no]=np.array([pending_decision,now,float(pending_seq),float(seq[i]),1.,float(side),float(qty),price,0.,0.]);no+=1
            pending=0
        elif pending==2:
            closing=min(qty,pending_qty);pnl=side*(price-entry)*closing*point_value
            trades[nt]=np.array([entry_t,now,float(side),float(closing),entry,price,pnl,float(pending_reason),entry_atr,float(entry_mode),pending_decision,float(seq[entry_i]),float(seq[i]),float(pending_seq),side*(extreme-entry)/entry_atr,(now-entry_t)/60]);nt+=1
            orders[no]=np.array([pending_decision,now,float(pending_seq),float(seq[i]),2.,float(-side),float(closing),price,pnl,float(pending_reason)]);no+=1
            realized+=pnl;campaign_profit+=pnl;qty-=closing
            if qty==0:
                side=0;cool_until=now+(cooldown if campaign_profit<0 else 5.)*60
            pending=0
        while pointer<len(events) and events[pointer,0]<=now:
            current=events[pointer];pointer+=1
        equity=realized+(side*(price-entry)*qty*point_value if qty else 0.)
        peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
        if qty:
            extreme=max(extreme,price) if side==1 else min(extreme,price)
            progress=side*(price-entry)/entry_atr;best=side*(extreme-entry)/entry_atr;age=(now-entry_t)/60
            fresh=now-current[0]<=120;adverse=fresh and current[5]*side<0
            width=trail_width
            if exit_id==2: width=max(.5,trail_width-age/30.)
            if adverse: width=min(width,.5)
            reason=0;close_qty=qty
            if now>=limit:reason=8
            elif progress<=-stop_width:reason=1
            elif best>=activation and side*(extreme-price)/entry_atr>=width:reason=2
            elif entry_mode==2 and side*(price-target)>=0:reason=6
            elif exit_id==2 and age>=15 and best<.5:reason=3
            elif adverse and age>=5 and progress<.2:reason=4
            elif age>=max_minutes:reason=5
            elif exit_id==3 and not partial and progress>=1.25 and qty>1:
                reason=7;close_qty=max(1,qty//2);partial=True
            if reason:
                pending=2;pending_reason=reason;pending_qty=close_qty;pending_decision=now;pending_seq=seq[i]
        elif now>=cool_until and now<limit-300 and now-current[0]<=120 and current[1]!=0 and current[3]>0 and (current[2]!=2 or current[1]*(current[4]-price)>=.25*current[3]):
            pending=1;pending_side=int(current[1]);pending_decision=now;pending_seq=seq[i];pending_atr=current[3]
            pending_mode=int(current[2]);pending_target=current[4]
    if finish and qty:
        raise ValueError('セッション返済後の観測が不足しています')
    return trades[:nt],orders[:no],drawdown,qty


def execute(spec: dict, ready: dict, event: np.ndarray, finish: bool=True) -> tuple:
    """機能: 固定条件と実口座枚数を再生器へ渡す。

    引数: spec/ready(dict)、event(ndarray)、finish(bool)。返り値: 再生結果(tuple)。
    """
    e=spec['exit'];q=5 if ready['symbol']=='TOPIX' else 10;pv=1000 if ready['symbol']=='TOPIX' else 10
    return replay(ready['time_s'],ready['seq'],ready['last'],event,ready['start'],ready['limit'],q,pv,e['stop'],e['activation'],e['width'],e['max_minutes'],e['cooldown'],spec['exit_id'],finish)


def summary(key: tuple, trades: np.ndarray, drawdown: float) -> dict:
    """機能: 決済金額と決済枚数を会計上の同じ取引から集計する。

    引数: key(tuple)、trades(ndarray)、drawdown(float)。返り値: セッション明細(dict)。
    """
    pnl=trades[:,6];wins=pnl>0;loss=pnl<0
    return dict(session=key[0],symbol=key[1],profit=float(pnl[wins].sum()),loss=float(-pnl[loss].sum()),net=float(pnl.sum()),
                win_qty=int(trades[wins,3].sum()),loss_qty=int(trades[loss,3].sum()),flat_qty=int(trades[pnl==0,3].sum()),
                qty_net=int(trades[wins,3].sum()-trades[loss,3].sum()),trades=len(trades),wins=int(wins.sum()),losses=int(loss.sum()),
                long_net=float(pnl[trades[:,2]==1].sum()),short_net=float(pnl[trades[:,2]==-1].sum()),drawdown=float(drawdown))


def totals(rows: list[dict], sessions: list[str], symbol: str) -> dict:
    """機能: 指定期間の損益、勝敗比、活動、日次下落を集計する。

    引数: rows(list[dict])、sessions(list[str])、symbol(str)。返り値: 集計(dict)。
    """
    data=[r for r in rows if r['symbol']==symbol and r['session'] in sessions]; data.sort(key=lambda r:r['session'])
    fields=['profit','loss','net','win_qty','loss_qty','flat_qty','qty_net','trades','wins','losses','long_net','short_net']
    result={f:sum(r[f] for r in data) for f in fields};p=result['profit'];l=result['loss']
    result.update(sessions=len(data),active=sum(r['trades']>0 for r in data),winning_sessions=sum(r['net']>0 for r in data),
                  win_rate=sum(r['net']>0 for r in data)/max(1,len(data)),pf=p/l if l else None,
                  average_win=p/result['wins'] if result['wins'] else 0,average_loss=l/result['losses'] if result['losses'] else 0,
                  per_contract_win=p/result['win_qty'] if result['win_qty'] else 0,per_contract_loss=l/result['loss_qty'] if result['loss_qty'] else 0,
                  without_best=result['net']-max([r['net'] for r in data]+[0]),worst_session=min([r['net'] for r in data]+[0]),
                  max_intraday_drawdown=max([r['drawdown'] for r in data]+[0]))
    result['payoff']=result['average_win']/result['average_loss'] if result['average_loss'] else None
    result['per_contract_payoff']=result['per_contract_win']/result['per_contract_loss'] if result['per_contract_loss'] else None
    curve=np.r_[0,np.cumsum([r['net'] for r in data])];result['session_drawdown']=float(np.max(np.maximum.accumulate(curve)-curve))
    return result


def score(rows: list[dict], sessions: list[str]) -> float:
    """機能: 固定された活動条件と銘柄中立スコアで過去区間を採点する。

    引数: rows(list[dict])、sessions(list[str])。返り値: 採点(float)。
    """
    values=[totals(rows,sessions,symbol) for symbol in ('TOPIX','NK225')]
    if any(v['active']<6 or v['trades']<15 for v in values):return -100000.
    return min(v['net']/max(v['loss'],1) for v in values)+sum(v['win_rate'] for v in values)/2+.5*min(v['without_best']/max(v['loss'],1) for v in values)


def main() -> None:
    """機能: 固定96条件の計算、過去選択、詳細台帳保存を順次実行する。

    引数: なし。返り値: なし(None)。
    """
    socket.socket.connect=deny;socket.create_connection=deny;freeze()
    inputs,frames=load();names=sorted({k[0] for k in inputs});assert len(names)==23
    save('入力構成.json',dict(対象=names,原本行数=sum(len(r['seq']) for r in inputs.values()),現API取得数=0,
                            入力SHA256={str((ROOT/s/('inputs.pkl' if i==0 else 'new_inputs.pkl')).relative_to(ROOT)):hashlib.sha256((ROOT/s/('inputs.pkl' if i==0 else 'new_inputs.pkl')).read_bytes()).hexdigest() for i,s in enumerate(SOURCES)}))
    all_rows={};last_group=None
    for spec in catalog():
        group=spec['window']
        if group!=last_group:
            models={key:bars(ready,frames[key],group) for key,ready in inputs.items()};last_group=group
        rows=[];ledgers=[]
        for key,ready in sorted(inputs.items()):
            event=signals(spec,models,key);trades,orders,dd,qty=execute(spec,ready,event)
            assert qty==0
            rows.append(summary(key,trades,dd));ledgers.append(dict(session=key[0],symbol=key[1],trades=trades.tolist(),orders=orders.tolist()))
        all_rows[spec['id']]=rows
        save('sessions/'+spec['id']+'.json',rows)
        save('ledgers/'+spec['id']+'.json.gz',ledgers)
        print(spec['id']+' 再生完了',flush=True)
    periods={'開発10':names[:10],'期間外9':names[10:19],'原因既読4':names[19:],'全23':names}
    ranking=sorted([(score(rows,names[:10]),identifier) for identifier,rows in all_rows.items()],reverse=True)
    selected=[]
    for family in range(6):
        ids={s['id'] for s in catalog() if s['family']==family}
        selected.append(next(identifier for _,identifier in ranking if identifier in ids))
    result={identifier:{p:{symbol:totals(rows,chosen,symbol) for symbol in ('TOPIX','NK225')} for p,chosen in periods.items()} for identifier,rows in all_rows.items()}
    save('結果一覧.json',result);save('過去10場選択.json',dict(順位=[dict(id=i,score=s) for s,i in ranking],系統代表=selected,第一候補=ranking[0][1],真正未見=False))
    # ----------------------------------------
    # 毎回その直前の場までだけで選び直す規則を、次場へ適用する。
    walk=[]
    for index in range(10,len(names)):
        identifier=max(all_rows,key=lambda v:score(all_rows[v],names[:index]))
        walk.append(dict(session=names[index],id=identifier,参照最終=names[index-1],rows=[r for r in all_rows[identifier] if r['session']==names[index]]))
    save('過去逐次選択.json',dict(規則='先頭10場を準備として、各場前に全過去の固定スコア1位を両銘柄共通選択する。',選択=walk,
                               集計={symbol:totals([r for w in walk for r in w['rows']],names[10:],symbol) for symbol in ('TOPIX','NK225')}))
    save('完了.json',dict(全合格=True,候補数=96,口座再生数=96*46,全場数=23,API取得数=0,
                         第一候補=ranking[0][1],系統代表=selected,売買仕様='判断後次観測価格約定',真正未見=False))


if __name__=='__main__':main()
