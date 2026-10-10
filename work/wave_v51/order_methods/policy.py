"""未来の配列を受け取らず、原本一行ずつを処理する注文管理ポリシー。"""
from __future__ import annotations
import numpy as np
from numba import njit

# 状態: 開始/返済期限/段階/再開時刻/組開始/準備seq/上値/下値/準備ATR/組数/乱数/実現/最高資産/最大下落。
# 脚: 枚数/新規値/新規時刻/新規seq/ATR/最良値/保留注文/判断時刻/判断seq/理由。
# 条件: 系統/選択肢/休止分/組期限分/出口/損切/追跡開始/追跡幅/枚数/円倍率。


@njit(cache=True)
def on_tick_step(now: float, seq: int, price: float, atr: float, state: np.ndarray,
                 legs: np.ndarray, params: np.ndarray, orders_out: np.ndarray, trades_out: np.ndarray) -> tuple:
    """機能: 現在一件と保有状態だけから約定・次注文を処理する。

    引数: now/price/atr(float)、seq(int)、状態・条件・当行出力器(ndarray)。
    返り値: 当行注文数・返済数・合算資産(tuple[int,int,float])。
    市場の未来配列は引数にも状態にも含めない。
    """
    no=nt=0
    if not np.isfinite(price) or price<=0:return no,nt,state[14]
    # ----------------------------------------
    # 前回までに判断した注文だけを現在の観測価格で約定する。
    for slot in range(2):
        leg=legs[slot];side=1 if slot==0 else -1
        if leg[6]==1:
            leg[0]=params[8];leg[1]=price;leg[2]=now;leg[3]=seq;leg[4]=state[8];leg[5]=price
            orders_out[no]=np.array([leg[7],now,leg[8],float(seq),1.,float(side),leg[0],price,0.,0.]);no+=1
            leg[6]=0
        elif leg[6]==2:
            pnl=side*(price-leg[1])*leg[0]*params[9]
            orders_out[no]=np.array([leg[7],now,leg[8],float(seq),2.,float(-side),leg[0],price,pnl,leg[9]]);no+=1
            trades_out[nt]=np.array([leg[2],now,float(side),leg[0],leg[1],price,pnl,leg[9],leg[4],params[0]+1,leg[7],leg[3],float(seq),leg[8],side*(leg[5]-leg[1])/leg[4],(now-leg[2])/60]);nt+=1
            state[11]+=pnl;leg[0]=0;leg[6]=0
    if state[2]==2 and legs[0,0]==0 and legs[1,0]==0 and legs[0,6]==0 and legs[1,6]==0:
        state[2]=0;state[3]=now+params[2]*60
    equity=state[11]
    for slot in range(2):
        side=1 if slot==0 else -1
        equity+=side*(price-legs[slot,1])*legs[slot,0]*params[9]
    state[12]=max(state[12],equity);state[13]=max(state[13],state[12]-equity)
    state[14]=equity
    # ----------------------------------------
    # 保有は同じ組時計で管理し、損益は片脚ごとに記録して全て合算する。
    for slot in range(2):
        leg=legs[slot];side=1 if slot==0 else -1
        if leg[0]<=0:continue
        leg[5]=max(leg[5],price) if side==1 else min(leg[5],price)
        progress=side*(price-leg[1])/leg[4];best=side*(leg[5]-leg[1])/leg[4]
        age=(now-leg[2])/60;width=params[7]
        if params[4]==1:width=max(.25,width-age/60)
        reason=0
        if now>=state[1]:reason=8
        elif progress<=-params[5]:reason=1
        elif best>=params[6] and side*(leg[5]-price)/leg[4]>=width:reason=2
        elif params[4]==1 and age>=15 and best<.25:reason=3
        elif now-state[4]>=params[3]*60:reason=5
        if reason:
            leg[6]=2;leg[7]=now;leg[8]=seq;leg[9]=reason
    # ----------------------------------------
    # 予測なし。OCOの成立、又は新しい注文組を準備する。
    if state[2]==1:
        if now>=state[1]-300 or now-state[4]>=params[3]*60:
            state[2]=0;state[3]=now+params[2]*60
        elif seq>state[5]:
            slot=-1
            if price>=state[6]:slot=0
            elif price<=state[7]:slot=1
            if slot>=0:
                state[2]=2;legs[slot,6]=1;legs[slot,7]=now;legs[slot,8]=seq
    elif state[2]==0 and now>=state[3] and now>=state[0]+1200 and now<state[1]-300 and np.isfinite(atr) and atr>0:
        state[4]=now;state[5]=seq;state[8]=atr;state[9]+=1
        if params[0]==0:
            state[2]=1;state[6]=price+params[1]*atr;state[7]=price-params[1]*atr
        else:
            state[2]=2
            if params[0]==1:
                legs[0,6]=1;legs[0,7]=now;legs[0,8]=seq
                legs[1,6]=1;legs[1,7]=now;legs[1,8]=seq
            else:
                if params[1]==0:
                    seed=int(state[10]);seed^=seed<<13;seed&=0xffffffff;seed^=seed>>17;seed^=seed<<5;seed&=0xffffffff
                    state[10]=seed;slot=seed%2
                else:slot=int(state[9]-1)%2
                legs[slot,6]=1;legs[slot,7]=now;legs[slot,8]=seq
    return no,nt,equity


def initialize(spec: dict, start: float, limit: float, symbol: str) -> tuple:
    """機能: 公開済み設定だけで注文状態と初期条件を構築する。

    引数: spec(dict)、start/limit(float)、symbol(str)。返り値: 状態/脚/条件(tuple[ndarray,...])。
    """
    if symbol not in ('TOPIX','NK225'):raise ValueError('参照商品はTOPIX又はNK225です')
    state=np.zeros(15,dtype=float);state[0]=start;state[1]=limit;state[3]=start
    state[10]=(int(start)^sum(ord(c) for c in symbol)^20261007)&0xffffffff
    if state[10]==0:state[10]=1
    e=spec['exit']
    params=np.array([spec['family'],spec['option'],spec['cooldown'],spec['cycle'],spec['exit_id'],e['stop'],e['activation'],e['width'],5 if symbol=='TOPIX' else 10,1000 if symbol=='TOPIX' else 10],dtype=float)
    return state,np.zeros((2,10),dtype=float),params


class StreamingPolicy:
    """現在一行だけを受け取る注文判断器。実API発注は行わない。"""

    def __init__(self, spec: dict, start: float, limit: float, symbol: str):
        """機能: セッション開始時に予測なし注文方式の状態を作る。

        引数: spec(dict)、start/limit(float:UTC秒)、symbol(str)。返り値: なし(None)。
        """
        self.state,self.legs,self.params=initialize(spec,start,limit,symbol)
        self.orders_out=np.zeros((2,10));self.trades_out=np.zeros((2,16))
        self.previous_seq=-1;self.previous_time=-np.inf

    def on_tick(self, now: float, seq: int, price: float, atr: float) -> dict:
        """機能: 現在の原本一行から約定と次の注文判断を進める。

        引数: now(float:UTC秒)、seq(int:原本行順)、price/atr(float:現在価格/公開済みATR)。
        返り値: 当行orders/trades、equity、建玉枚数、組番号(dict)。未約定の判断は内部状態に保持する。
        """
        if seq<=self.previous_seq or now<self.previous_time:raise ValueError('原本行順又は時刻が逆転しています')
        no,nt,equity=on_tick_step(now,seq,price,atr,self.state,self.legs,self.params,self.orders_out,self.trades_out)
        self.previous_seq=seq;self.previous_time=now
        return dict(orders=self.orders_out[:no].tolist(),trades=self.trades_out[:nt].tolist(),equity=float(equity),
                    net_positions=dict(long=int(self.legs[0,0]),short=int(self.legs[1,0])),cycle=int(self.state[9]))


@njit(cache=True)
def drive(times: np.ndarray, seqs: np.ndarray, prices: np.ndarray, atrs: np.ndarray,
          state: np.ndarray, legs: np.ndarray, params: np.ndarray, finish: bool=True) -> tuple:
    """機能: ドライバーだけが原本配列を持ち、判断器へ一件ずつ渡す。

    引数: 原本配列/状態/条件(ndarray)、finish(bool)。返り値: 決済・注文・状態・脚(tuple)。
    """
    trades=np.zeros((20000,16));orders=np.zeros((40000,10));nt=no=0
    to=np.zeros((2,16));oo=np.zeros((2,10))
    for i in range(len(prices)):
        emitted_o,emitted_t,_=on_tick_step(times[i],seqs[i],prices[i],atrs[i],state,legs,params,oo,to)
        for j in range(emitted_o):orders[no]=oo[j];no+=1
        for j in range(emitted_t):trades[nt]=to[j];nt+=1
    if finish and np.sum(legs[:,0])+np.sum(legs[:,6])!=0:raise ValueError('場内返済後の原本行が不足しています')
    return trades[:nt],orders[:no],state,legs


def execute(spec: dict, ready: dict, finish: bool=True) -> tuple:
    """機能: 保存原本を一行駆動器へ接続する。

    引数: spec/ready(dict)、finish(bool)。返り値: 再生結果(tuple)。
    """
    state,legs,params=initialize(spec,ready['start'],ready['limit'],ready['symbol'])
    return drive(ready['time_s'],ready['seq'],ready['last'],ready['atr'],state,legs,params,finish)
