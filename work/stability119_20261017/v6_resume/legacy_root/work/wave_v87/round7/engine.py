"""当行までの元注文だけを読む独立追加玉。元玉の状態へ書き戻さない。"""
import numpy as np
from numba import njit

EVENT_COLUMNS=['行','組','種別','根拠行','方向','枚数','線又は約定値','コア残枚数','固定ATR','理由','コア終了行','追尾始動']
REASONS={80:'独立追加新規',81:'独立追加の停止',82:'独立追加の追尾',83:'元玉全返済後の次観測返済',84:'米国静観予定',85:'場末予定'}


@njit(cache=True)
def rounded(price,tick,side):
    """
    機能: 条件が成立する方向へ価格を呼値に揃える。
    引数: price/tick(float)、side(int)。
    返り値: float。
    """
    return (np.ceil(price/tick-1e-9) if side>0 else np.floor(price/tick+1e-9))*tick


@njit(cache=True)
def simulate(times,prices,core_orders,quiet,quiet_force,end,cutoff,tick,relation,
             start_atr,stop_atr,activation_atr,trail_atr,observed):
    """
    機能: 前観測予約を先に執行し、当行コア約定をその後に取り込む。
    引数: times/prices/quiet/quiet_force(ndarray)、core_orders(ndarray9列・最後は新規時ATR)、
          end/cutoff/tick/各幅(float)、relation(int)、observed(bool)。
    返り値: tuple。追加注文8列、決済11列、時価8列、証跡12列、状態5列。
    コアの将来終了行・全組損益・将来極値は引数に含まない。
    """
    n=len(times);capacity=max(64,len(core_orders)*4+8)
    orders=np.zeros((capacity,8));trades=np.zeros((capacity,11))
    curve=np.zeros((n,8));events=np.zeros((n*3+capacity,12))
    oc=tc=ec=pointer=0
    cid=-1;core_qty=0;core_side=0;anchor=0.;atr=1.;initial=0
    pending=False;pending_row=-1;pending_market=False;level=0.;used=False
    sat_side=0;sat_qty=0;entry=0.;entry_row=-1;child_row=-1;child=0.
    child_reason=81;child_market=False;peak=0.;armed=False
    force_row=-1;core_closed=-1;cash=realized=0.;last_price=0.;peak_equity=0.;dd=0.
    maxlong=maxshort=0
    for i in range(n):
        t=times[i];p=prices[i]
        if not np.isfinite(p) or p<=0:
            if i:curve[i]=curve[i-1]
            assert pointer>=len(core_orders) or int(core_orders[pointer,0])!=i
            continue
        last_price=p
        scheduled=bool(quiet[i] or quiet_force[i] or t>=end)
        no_entry=bool(scheduled or t>=end-cutoff*60.)
        # ----------------------------------------
        # 既知の時刻予定を優先し、そのほかは前観測の注文を現在までのコア約定より先に評価。
        if pending and no_entry:
            events[ec]=np.array([i,cid,5.,pending_row,core_side*relation,initial,level,core_qty,atr,84. if scheduled and t<end else 85.,core_closed,int(armed)]);ec+=1
            pending=False;used=True
        reason=0;source=-1;fill=0.
        if sat_qty:
            if scheduled and i:
                reason=85 if t>=end else 84;source=i-1;fill=p
            elif force_row>=0 and i>force_row:
                reason=83;source=force_row;fill=p
            elif i>child_row and (child_market or -sat_side*(p-child)>=-1e-9):
                reason=child_reason;source=child_row;fill=p if observed or child_market else child
            if reason:
                assert 0<=source<i
                gain=sat_side*sat_qty*(fill-entry)
                orders[oc]=np.array([i,source,cid,-sat_side,sat_qty,fill,reason,0.]);oc+=1
                trades[tc]=np.array([cid,1.,sat_side,sat_qty,entry,fill,entry_row,i,1.,reason,gain]);tc+=1
                cash+=sat_side*sat_qty*fill;realized+=gain
                events[ec]=np.array([i,cid,4.,source,sat_side,sat_qty,fill,core_qty,atr,reason,core_closed,int(armed)]);ec+=1
                sat_qty=0;sat_side=0;force_row=-1;used=True
        if pending and not sat_qty and i>pending_row and not no_entry:
            if pending_market or core_side*(p-level)>=-1e-9:
                sat_side=core_side*relation;sat_qty=initial
                entry=p if observed or pending_market else level;entry_row=i
                cash-=sat_side*sat_qty*entry
                orders[oc]=np.array([i,pending_row,cid,sat_side,sat_qty,entry,80.,1.]);oc+=1
                events[ec]=np.array([i,cid,2.,pending_row,sat_side,sat_qty,entry,core_qty,atr,80.,core_closed,0.]);ec+=1
                pending=False;used=True;armed=False;peak=entry;force_row=-1
                width=max(tick,stop_atr*atr)
                child=rounded(entry-sat_side*width,tick,-sat_side)
                child_row=i;child_reason=81;child_market=-sat_side*(p-child)>=-1e-9
                events[ec]=np.array([i,cid,3.,i,sat_side,sat_qty,child,core_qty,atr,81.,core_closed,0.]);ec+=1
        # ----------------------------------------
        # 現在行までの実約定のみ受付。新規後ATRもこの時点で初めて状態へ取り込む。
        while pointer<len(core_orders) and int(core_orders[pointer,0])==i:
            order=core_orders[pointer];pointer+=1
            if int(order[7])==1:
                assert core_qty==0 and sat_qty==0
                cid=int(order[2]);core_side=int(order[3]);core_qty=int(order[4]);initial=core_qty
                anchor=order[5];atr=order[8]
                assert atr>0 and np.isfinite(atr)
                pending=False;used=False;core_closed=-1;force_row=-1
                events[ec]=np.array([i,cid,7.,order[1],core_side,core_qty,anchor,core_qty,atr,20.,-1.,0.]);ec+=1
            else:
                assert int(order[2])==cid
                core_qty-=int(order[4]);assert core_qty>=0
                if core_qty==0:
                    core_closed=i
                    events[ec]=np.array([i,cid,6.,i,core_side,0.,p,core_qty,atr,83.,i,int(armed)]);ec+=1
                    if pending:
                        events[ec]=np.array([i,cid,5.,i,core_side*relation,initial,level,0.,atr,83.,i,int(armed)]);ec+=1
                        pending=False;used=True
                    if sat_qty:force_row=i
        assert pointer>=len(core_orders) or int(core_orders[pointer,0])>i
        # ----------------------------------------
        # 更新線は次観測から。新しい予約を作るのはコアが現に生存する場合だけ。
        if core_qty and not used and not pending and relation and not no_entry:
            pending=True;pending_row=i
            level=rounded(anchor+core_side*start_atr*atr,tick,core_side)
            pending_market=core_side*(p-level)>=-1e-9
            events[ec]=np.array([i,cid,1.,i,core_side*relation,initial,level,core_qty,atr,80.,core_closed,0.]);ec+=1
        if sat_qty and i>entry_row and force_row<0:
            peak=max(peak,p) if sat_side>0 else min(peak,p)
            if sat_side*(peak-entry)>=activation_atr*atr-1e-9:armed=True
            if armed:
                nextline=rounded(peak-sat_side*max(tick,trail_atr*atr),tick,-sat_side)
                if sat_side*(nextline-child)>1e-9:
                    child=nextline;child_row=i;child_reason=82
                    child_market=-sat_side*(p-child)>=-1e-9
                    events[ec]=np.array([i,cid,3.,i,sat_side,sat_qty,child,core_qty,atr,82.,core_closed,1.]);ec+=1
        longqty=sat_qty if sat_side>0 else 0;shortqty=sat_qty if sat_side<0 else 0
        maxlong=max(maxlong,longqty);maxshort=max(maxshort,shortqty)
        equity=cash+sat_side*sat_qty*p;peak_equity=max(peak_equity,equity);dd=max(dd,peak_equity-equity)
        curve[i]=np.array([equity,realized,longqty,shortqty,dd,cash,sat_side*sat_qty,cid])
        assert oc<capacity-2 and tc<capacity-2 and ec<len(events)-8
    return orders[:oc],trades[:tc],curve,events[:ec],np.array([sat_qty,core_qty,int(pending),maxlong,maxshort])
