"""同時の価格RANGEと予定料込RRから、R又は旧Cを一口座に選ぶ。"""

from copy import deepcopy
import math

import numpy as np

import features


MULTIPLIER={'TOPIX':1000.,'NK225':10.}
FEE={'TOPIX':41.8,'NK225':11.}


def range_arrays(prepared: dict, measured: dict, config: dict) -> dict:
    """
    機能: 各normal当行の境界反発へ、固定停止/中心と予定料込RRだけを適用する。
    引数: prepared/measured/config(dict)は旧正常入力と当時six点、新24設定。
    返り値: dictは採否と価格線。実fill時の悪化を架空取消してはならない。
    """
    record=prepared['record'];symbol=record['symbol'];tick=record['tick'];qty=config['quantity'][symbol]
    sample=measured['sample_tables']['own'];index=measured['normal_sample_index'];event=measured['boundary_events'][str(config['range_er'])]
    side=event.astype(float);centre,low,high=(sample[k][index] for k in ('centre','low','high'))
    margin=config['margin_ticks']*tick
    stop=np.where(event==1,np.floor((low-margin)/tick+1e-10)*tick,np.ceil((high+margin)/tick-1e-10)*tick)
    target=np.where(event==1,np.floor(centre/tick+1e-10)*tick,np.ceil(centre/tick-1e-10)*tick)
    if config['range_entry']=='MARKET':
        planned=np.where(event==1,record['ask'],record['bid'])
    else:
        assert config['range_entry']=='LIMIT'
        planned=np.where(event==1,record['bid'],record['ask'])
    fees=2*math.floor(qty*FEE[symbol]+1e-8)
    risk=side*(planned-stop)*qty*MULTIPLIER[symbol]+fees
    profit=side*(target-planned)*qty*MULTIPLIER[symbol]-fees
    clearance=side*(planned-stop)/tick;candidate=event!=0
    reason=np.zeros(len(event),np.int8)
    reason[candidate&(~np.isfinite(stop)|~np.isfinite(target)|~np.isfinite(planned)|(stop<=0)|(target<=0))]=1
    reason[candidate&(reason==0)&(clearance<2.-1e-10)]=2
    reason[candidate&(reason==0)&(side*(target-planned)<=0)]=3
    reason[candidate&(reason==0)&(risk<=0)]=4
    reason[candidate&(reason==0)&(profit<1.25*risk)]=5
    allowed=candidate&(reason==0)
    return dict(event=event,allowed=allowed,rejection=reason,stop=stop,target=target,planned_entry=planned,
        planned_net_profit=profit,planned_net_loss=risk,stop_clearance_ticks=clearance,
        roundtrip_fees=fees,centre=centre,low=low,high=high)


def build(packet: dict, symbol: str, config: dict) -> dict:
    """
    機能: R_ONLY又はRANGE先のAUTOで、価格反発と元Cpulseを排他的に選択する。
    引数: packet(dict)、symbol(str)、config(dict)は新入力と事前24条件。
    返り値: dictはnormal_case。Cの支持/episodeは保持し、Rに架空板episodeを作らない。
    """
    prepared=packet['prepared'][symbol];record=prepared['record'];measured=packet['measured'][symbol]
    original=packet['cases'][symbol]['C_OWN'];n=len(record['seq']);state=measured['states'][str(config['range_er'])]
    R=range_arrays(prepared,measured,config);cmeta={int(d['row']):d for d in original['decisions']}
    normal=dict(entry_id=config['id'],event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),
        entry_quality=original['entry_quality'].copy(),entry_reset=original['entry_reset'].copy(),
        execution_to_raw_index=original['execution_to_raw_index'],decisions=[],
        entry_families=np.zeros(n,np.int8),target_prices=np.full(n,np.nan),entry_stop_prices=np.full(n,np.nan),
        entry_limit_prices=np.full(n,np.nan),entry_modes=np.zeros(n,np.int8),
        range_pending_trend=(state==2)|(state==-2),
        quiet=packet['quiet'][symbol]['active'] if 'quiet' in packet else np.zeros(n,bool),
        quiet_start_s=packet['quiet'][symbol]['start_s'] if 'quiet' in packet else np.full(n,np.nan))
    if config['mode']=='AUTO':
        c=((state==2)&(original['event']==1))|((state==-2)&(original['event']==-1))
        normal['event'][c]=original['event'][c];normal['support_price'][c]=original['support_price'][c]
        normal['entry_families'][c]=1;normal['entry_modes'][c]=1
        for row in np.flatnonzero(c):
            normal['decisions'].append(deepcopy(cmeta[int(row)]))
    else:
        assert config['mode']=='R_ONLY'
    event_rows=np.flatnonzero(R['allowed'])
    for row_value in event_rows:
        row=int(row_value);side=int(R['event'][row]);assert normal['event'][row]==0 and state[row]==1
        normal['event'][row]=side;normal['support_price'][row]=R['stop'][row]
        normal['entry_quality'][row]=True;normal['entry_reset'][row]=False
        normal['entry_families'][row]=2;normal['target_prices'][row]=R['target'][row]
        normal['entry_stop_prices'][row]=R['stop'][row];normal['entry_modes'][row]=1 if config['range_entry']=='MARKET' else 2
        if config['range_entry']=='LIMIT':
            normal['entry_limit_prices'][row]=R['planned_entry'][row]
        index=int(measured['normal_sample_index'][row]);own=features.at_row(measured['sample_tables']['own'],index,
            bool(measured['own_known'][row]),int(measured['own_reason'][row]))
        peer=features.at_row(measured['sample_tables']['peer'],index)
        raw_row=int(normal['execution_to_raw_index'][row]);seq=int(record['seq'][row])
        normal['decisions'].append(dict(row=row,normal_row=row,raw_row=raw_row,raw_seq=seq,side=side,
            support_price=float(R['stop'][row]),stop_price=float(R['stop'][row]),target_price=float(R['target'][row]),
            price_time=float(record['time_s'][row]),entry_mode=config['range_entry'],
            reference_kind='純価格範囲外停止',selected_support_roots=[],
            episode=('R_PRICE',side,seq),own_six=own,peer_six=peer,
            fixed_high=float(R['high'][row]),fixed_low=float(R['low'][row]),fixed_centre=float(R['centre'][row]),
            planned_entry=float(R['planned_entry'][row]),planned_net_profit=float(R['planned_net_profit'][row]),
            planned_net_loss=float(R['planned_net_loss'][row]),stop_clearance_ticks=float(R['stop_clearance_ticks'][row]),
            fee_included_ratio=float(R['planned_net_profit'][row]/R['planned_net_loss'][row]),
            prior_quote_row=int(measured['previous_normal_row'][row]),反発原seq=seq,
            量根拠='使用しない純価格反発。旧C量根拠は不変更'))
    normal['decisions'].sort(key=lambda d:int(d['row']))
    return normal
