"""原候補・自己原板・公開peerから初回待機と全玉の保有管理を独立再生する。"""

import math
from fractions import Fraction
import numpy as np

import compare_utils as checks
import math_oracle as money
import support
import watch


def observation(record: dict, signal: dict, row: int, latest: int, side: int) -> dict:
    """
    機能: 自己実原行と、その判断まで公表済み格子のpeerだけを独立観測にする。
    引数: record/signal(dict)、row/latest/side(int)。
    返り値: dict。実sourceと代理clock。未知/未来peerを正常資格へ救済しない。
    """
    stamp = record['time_s'][row]
    own = np.array([row,record['seq'][row],stamp,record['bid'][row],record['ask'][row]],float)
    fresh = bool(latest >= 0 and stamp-signal['grid'][latest] <= 10.+1e-8)
    peer = signal['entry_peer_bbo'][latest,:5].copy() if latest >= 0 else np.full(5,np.nan)
    qok = bool(record['quote_valid'][row] and np.isfinite(own[3:5]).all() and 0 < own[3] < own[4])
    return dict(own=own,peer=peer,side=side,qok=qok,quality=bool(signal['quality'][row]),
        reset=bool(signal['reset'][row]),fresh=fresh,peer_valid=bool(fresh and signal['entry_peer_bbo'][latest,5]),
        j2_allowed=bool(fresh and signal['entry_j2_long' if side == 1 else 'entry_j2_short'][latest]),
        opposite=bool(fresh and signal['wait_opposite_long' if side == 1 else 'wait_opposite_short'][latest]),
        gap=stamp-record['time_s'][row-1] if row else 0.,grid_index=latest)


def pair(seen: dict) -> bool:
    """
    機能: 現在の正常自己と公開peerの全BBO源・有限時計・未来時計上限を確認する。
    引数: seen(dict)は現在判断の原源。
    返り値: bool。異なる商品の原seqを同じ受信時計と呼ばない。
    """
    own,peer = seen['own'],seen['peer']
    return bool(seen['qok'] and seen['fresh'] and seen['peer_valid']
        and np.isfinite(own).all() and np.isfinite(peer).all()
        and (own[:2] >= 0).all() and (peer[:2] >= 0).all()
        and 0 < peer[3] < peer[4] and peer[2] <= own[2]+1e-8)


def updated(anchor: np.ndarray | None, seen: dict, phase_time: float,
            tick: float, peer_tick: float) -> tuple[bool,bool]:
    """
    機能: 実fill基準の後に両市場のindex/seq/各時計が進み両bid/askが順行したか判定する。
    引数: anchor(ndarray|None)、seen(dict)、phase_time/tick/peer_tick(float)。
    返り値: tuple[bool,bool]。新源及び同判断での双方進行。別時点Trueを足さない。
    """
    if anchor is None or not pair(seen):
        return False,False
    own,peer = seen['own'],seen['peer']
    fresh = all(current[0] > old[0] and current[1] > old[1]
                and current[2] > phase_time and current[2] > old[2]
                for current,old in ((own,anchor[:5]),(peer,anchor[5:])))
    side = seen['side']
    progresses = (side*(own[3:5]-anchor[3:5]),side*(peer[3:5]-anchor[8:10]))
    progress = bool(fresh and (progresses[0] >= tick-tick*1e-8).all()
                    and (progresses[1] >= peer_tick-peer_tick*1e-8).all())
    return bool(fresh),progress


def widths(record: dict, config: dict, reference: float) -> tuple:
    """
    機能: 既知始値から旧初期幅Sと旧Dを独立算定する。
    引数: record/config(dict)、reference(float)。
    返り値: tuple[Fraction,Fraction]。旧幅だけの1e-10丸め仕様を保持する。
    """
    tick = record['tick']
    initial = max(2,math.ceil(reference*config['trend_initial_stop_bp']/10000./tick-1e-10))*tick
    trail = max(2,math.ceil(reference*.004/tick-1e-10))*tick
    checks.exact(trail,record.get('expected_trail',trail))
    return money.rational(initial),money.rational(trail)


def replay(value: dict, config: dict) -> dict:
    """
    機能: 実出力やlatent状態を使わず、生候補から待機・追加・停止・実fillを一行ずつ再構成する。
    引数: value(dict)は原板と独立支持素材、config(dict)は結果前条件。
    返り値: dict。期待注文17・親16・入口/追加/出口の最初判断と独立停止記憶。
    正式101損益を生成する関数ではなく、人工又は根が許可した代表接頭の監査用。
    """
    record = value['record']
    signal,allowed = support.selected(value,config)
    times,n = record['time_s'],len(record['time_s'])
    latests = np.maximum.accumulate(signal['mapped'])
    initial,trail = widths(record,config,value['reference_open'])
    checks.exact(float(trail),signal['trend_width'])
    initial_q = money.quantity_for(config,record['symbol'])
    maximum,v,u,peer_tick = (8,1000,41.8,10.) if record['symbol'] == 'TOPIX' else (16,10,11.,.5)
    tick = money.rational(record['tick'])
    hold = float(config['trend_hold_seconds'])
    protected = bool(config['trend_protection_mode'])
    growth = int(config['trend_growth_mode'])
    orders,trades,decisions,snapshots,accepted = [],[],[],[],[]
    status,side,parent,cycle = 0,0,0,0
    wait = None
    pending_entry,pending_exit,pending_add = None,None,None
    items = []
    first_order = None
    peak,line,initial_line,risk = None,None,None,None
    active = False
    last_exit = -1e30
    deadline = 0.
    anchor = None
    phase_time = -1e30
    last_fill = -1
    entry_cut,force_time = record['limit']-300.,record['limit']-60.
    closed = False
    candidate_ids = np.cumsum(signal['event'] != 0)
    for row,stamp in enumerate(times):
        if status == 0 and wait is None and not signal['event'][row]:
            # 空状態では注文・待機・時限遷移がなく、全原板時価は別の全行会計で省略なく検算する。
            continue
        seen = observation(record,signal,row,int(latests[row]),side or 1)
        qok = seen['qok']
        wait_at_start = wait is not None and wait['active']
        filled_this_row = False
        if pending_entry and stamp >= entry_cut:
            pending_entry = None
            status = 0
        if not closed and stamp >= force_time:
            closed = True
            if status == 2:
                pending_exit = dict(row=row-1,time=force_time,reason=4)
                status = 3
                decisions.append(dict(row=row,decision_row=row-1,side=side,kind='場内返済',reason=4,line=line))
        # ----------------------------------------
        # prior返済・静的期限は追加取消先。それ以外の追加成行は当前行のstopより先に実fillする。
        if pending_add:
            if closed or status != 2 or (hold > 0 and stamp >= deadline):
                decisions.append(dict(row=row,side=side,kind='追加取消',quantity=pending_add['quantity']))
                pending_add = None
            elif qok and row > pending_add['row']:
                price = record['ask'][row] if side == 1 else record['bid'][row]
                delta = pending_add['quantity']
                fee = money.order_fee(delta,u)
                order = [row,pending_add['row'],parent,0,side,delta,price,1,16,fee,
                         pending_add['time'],stamp,0,cycle,0,side,len(orders)+1]
                orders.append(order)
                items.append(money.Cohort(len(items)+1,delta,money.rational(price),fee))
                anchor = np.r_[seen['own'],seen['peer']] if pair(seen) else None
                phase_time,last_fill = stamp,row
                pending_add = None
                quote = record['bid'][row] if side == 1 else record['ask'][row]
                facts = money.liquidation(items,quote,side,v,u)
                active = active or (protected and facts['gross'] >= initial_q*2*initial*v)
                line = money.integrated_line(items,side,risk,line,initial_line,peak,trail,active,v,u,tick)['line']
                filled_this_row = True
        if status in (1,3) and qok:
            reservation = pending_entry if status == 1 else pending_exit
            if row > reservation['row']:
                is_entry = status == 1
                action = side if is_entry else -side
                quantity = initial_q if is_entry else sum(c.quantity for c in items)
                price = record['ask'][row] if action == 1 else record['bid'][row]
                fee = money.order_fee(quantity,u)
                reason = 10 if is_entry else reservation['reason']
                order = [row,reservation['row'],parent,0,action,quantity,price,int(is_entry),reason,fee,
                         reservation['time'],stamp,0,cycle,0,side,len(orders)+1]
                orders.append(order)
                if is_entry:
                    first_order = order
                    items = [money.Cohort(1,quantity,money.rational(price),fee)]
                    risk = money.fixed_risk(items[0],initial,v,u)
                    peak = money.rational(price)
                    initial_line = peak-side*initial
                    line = side*max(side*initial_line,side*peak-trail)
                    active = False
                    deadline = stamp+hold if hold else 0.
                    phase_time,last_fill = stamp,row
                    anchor = np.r_[seen['own'],seen['peer']] if pair(seen) else None
                    status,pending_entry = 2,None
                    filled_this_row = True
                else:
                    facts = money.completed_cohorts(items,price,side,v,u)
                    account = money.totals(items,v,u)
                    trades.append([parent,0,first_order[0],row,side,quantity,float(account['weighted_entry']),price,
                        account['entry_fee'],fee,float(facts['parent_net']+account['F']),float(facts['parent_net']),
                        first_order[8],reason,cycle,first_order[1]])
                    status,pending_exit,pending_add = 0,None,None
                    last_exit = stamp
        # ----------------------------------------
        # 初回fill同行は旧順どおり保有判定しない。追加fill同行は初回行より後なので判定する。
        if status == 2 and row > first_order[0]:
            reason = 0
            if closed:
                reason = 4
            elif hold and stamp >= deadline:
                reason = 3
            elif qok:
                quote = money.rational(record['bid'][row] if side == 1 else record['ask'][row])
                if side*(quote-line) <= tick*money.rational(1e-8):
                    weighted = money.totals(items,v,u)['weighted_entry']
                    reason = 1 if abs(peak-weighted) < tick*money.rational(1e-8) else 2
                else:
                    peak = side*max(side*peak,side*quote)
                    if growth:
                        facts = money.liquidation(items,quote,side,v,u)
                        active = active or (protected and facts['gross'] >= initial_q*2*initial*v)
                        line = money.integrated_line(items,side,risk,line,initial_line,peak,trail,active,v,u,tick)['line']
                    else:
                        active = active or (protected and side*(peak-items[0].price) >= 2*initial)
                        candidates = [line,peak-side*trail]
                        if active:
                            candidates.append(money.fee_line(items,side,v,u,tick))
                        line = side*max(side*c for c in candidates)
            if reason:
                pending_exit = dict(row=row,time=stamp,reason=reason)
                status,pending_add = 3,None
                decisions.append(dict(row=row,side=side,kind='返済判断',reason=reason,line=line,
                                      peak=peak,active=active,quantity=sum(c.quantity for c in items)))
        if growth and status == 2 and qok:
            new_anchor = False
            if anchor is None and pair(seen) and row > last_fill:
                anchor = np.r_[seen['own'],seen['peer']]
                new_anchor = True
            _,progress = updated(anchor,seen,phase_time,float(tick),peer_tick)
            quantity = sum(c.quantity for c in items)
            delta = min(quantity,maximum-quantity)
            if delta:
                hypothesis = money.projected_add(items,delta,record['bid'][row],record['ask'][row],
                    side,risk,line,initial_line,peak,initial,trail,active,protected,growth,v,u,tick)
                eligible = (not new_anchor and row > last_fill and pending_add is None
                    and seen['quality'] and not seen['reset'] and not closed and stamp < entry_cut
                    and seen['j2_allowed'] and progress and hypothesis['allowed'])
                if eligible:
                    pending_add = dict(row=row,time=stamp,quantity=delta)
                    decisions.append(dict(row=row,side=side,kind='追加予約',quantity=delta,
                                          risk=risk,net=hypothesis['net'],line=hypothesis['line']))
        # ----------------------------------------
        # watchが行頭にあった行は解除後も新候補を受理しない。保有中のpulseは消費する。
        event = int(signal['event'][row])
        if wait_at_start:
            observed = observation(record,signal,row,int(latests[row]),wait['side'])
            wait,decision = watch.step(wait,observed,float(tick),peer_tick,entry_cut)
            if decision['trigger']:
                parent,cycle = parent+1,cycle+1
                side,status = wait['side'],1
                pending_entry = dict(row=row,time=stamp)
                accepted.append(dict(parent=parent,candidate_row=wait['candidate_row'],trigger_row=row,
                                     side=side,quantity=initial_q,candidate_id=int(candidate_ids[wait['candidate_row']])))
            if not wait['active']:
                wait = None
        elif event and status == 0 and not closed:
            if (qok and seen['quality'] and not seen['reset'] and stamp >= record['start']+300.
                    and stamp < entry_cut and stamp-last_exit >= 30.):
                own_seen = observation(record,signal,row,int(latests[row]),event)
                wait = watch.start(own_seen,config,value['reference_open'],float(tick))
        if status == 2:
            facts = money.totals(items,v,u)
            snapshots.append(dict(row=row,parent=parent,quantity=facts['Q'],risk=risk,cash=facts['E'],
                                  entry_fees=facts['entry_fee'],weighted=facts['weighted_entry'],
                                  initial_line=initial_line,peak=peak,line=line,active=active,deadline=deadline,
                                  pending_add=pending_add.copy() if pending_add else None))
    return dict(orders=np.asarray(orders,float).reshape(-1,17),trades=np.asarray(trades,float).reshape(-1,16),
                accepted=accepted,decisions=decisions,snapshots=snapshots,status=status,
                pending_add=pending_add,pending_exit=pending_exit,pending_entry=pending_entry)


def compare(value: dict, config: dict, actual: dict) -> dict:
    """
    機能: 独立一行再生の最初入口・追加・返済と実注文・完了親を照合する。
    引数: value/config/actual(dict)。
    返り値: dict。意味を検算した件数。全70補助flagsまで検査したとは主張しない。
    """
    expected = replay(value,config)
    checks.exact(actual['orders'],expected['orders'],'独立最初判断と次normal実注文')
    checks.exact(actual['trades'][:,[0,1,2,3,4,5,6,7,8,9,12,13,14,15]],
                 expected['trades'][:,[0,1,2,3,4,5,6,7,8,9,12,13,14,15]],'独立完了親の源/数量/weighted価格')
    checks.money(actual['trades'][:,10:12],expected['trades'][:,10:12],'独立完了親の価格損益と純損益')
    columns = {name:i for i,name in enumerate(actual['growth_state_columns'])}
    for snapshot in expected['snapshots']:
        row = snapshot['row']
        pairs = [('parent_id',snapshot['parent']),('held_quantity',snapshot['quantity']),
                 ('risk_budget',snapshot['risk']),('entry_cash',snapshot['cash']),
                 ('entry_fees',snapshot['entry_fees']),('weighted_entry',snapshot['weighted']),
                 ('initial_line',snapshot['initial_line']),('price_peak',snapshot['peak']),
                 ('effective_stop',snapshot['line']),('protection_active',snapshot['active']),
                 ('deadline',snapshot['deadline'])]
        for name,wanted in pairs:
            checks.exact(actual['growth_state_trace'][row,columns[name]],float(wanted),'独立保有数理/'+name)
    return dict(注文=len(expected['orders']),完了親=len(expected['trades']),
                最初入口=len(expected['accepted']),独立保有行=len(expected['snapshots']))
