"""凍結済み注文器を読み取り、所有者と取消待ちを追加した別版を生成する。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
source = (HERE.parent / 'wave_v28' / 'engine_context.py').read_text(encoding='utf-8')


def replace(old: str, new: str) -> None:
    """機能: 一意の既存コード位置だけを新作業の文字列内で置換する。

    引数: old/new (str)。返り値: なし (None)。原本ファイルは書き換えない。
    """
    global source
    assert source.count(old) == 1, old[:100]
    source = source.replace(old, new)


replace('"""入口信号と保有中の主方向を分離し、原本行順・次行執行で再生する建玉管理器。"""',
        '"""共通D273の価格管理を維持し、手法選択の所有者・取消確認・再準備を追跡する。"""')
marker = '\n\n@njit(cache=True)\ndef rounded'
addition = '''

SELECTION_COLUMNS = ['request_id', 'applied_id', 'pending_owner_id', 'position_owner_id',
                     'entry_source_id', 'entry_direction', 'cancel_wait', 'cancel_source_row',
                     'pending_direction', 'pending_source_row', 'pending_entry_source_id',
                     'position_entry_source_id', 'pending_level', 'cooldown_until',
                     'pending_atr', 'pending_expiry', 'position_atr', 'stop_level',
                     'trail_level', 'position_direction']
EVENT_COLUMNS = ['row', 'phase', 'event', 'request_id', 'applied_id', 'pending_owner_id',
                 'position_owner_id', 'entry_source_id', 'source_row', 'old_id', 'new_id',
                 'direction', 'price', 'quantity', 'campaign']
EVENT_NAMES = {1: '要求更新', 2: '取消要求', 3: '取消確認', 4: '適用変更', 5: '新規準備',
               6: '追跡更新', 7: '新規約定', 8: '部分返済', 9: '完全返済',
               10: '期限又は方向で取消', 11: '保有中要求保留', 12: '切替後再準備'}
PHASE_NAMES = {0: '行先頭の取消確認', 1: '既存注文の約定', 2: '現在行の判断'}


@njit(cache=True)
def selection_record(events, count, row, phase, event, requested, applied, pending_owner,
                     position_owner, actual_source, source_row, old_id, new_id, side, level, quantity, campaign):
    """機能: 選択と注文の所有者イベントを価格台帳と別に保存する。

    引数: events (ndarray)、各ID・行・件数・数量 (int)、level (float)。返り値: 追加後件数 (int)。
    phaseにより、前行取消の確認、既存注文の約定、当該行の新しい判断を区別する。
    """
    if count >= len(events):
        raise ValueError('選択イベントの上限を超えました')
    events[count, :] = np.array([row, phase, event, requested, applied, pending_owner, position_owner,
                                actual_source, source_row, old_id, new_id, side, level, quantity, campaign])
    return count + 1
'''
replace(marker, addition + marker)
replace('def simulate(time, price, atr, state, context, tick, start, end, us_open, par, detail, cap):',
        'def simulate(time, price, atr, states, request, tick, start, end, us_open, par, detail, cap, source_override, observed_fill):')
replace('引数: time/price/atr/state/context/par (ndarray)、tick/start/end/us_open (float)、detail (bool)、cap (int)。',
        '引数: time/price/atr/states/request/par (ndarray)、tick/start/end/us_open (float)、detail/observed_fill (bool)、cap/source_override (int)。')
replace('返り値: 返済台帳、組集計、資産曲線、注文台帳、検算値 (tuple[ndarray,...])。',
        '返り値: 旧5台帳と選択イベント・選択全行曲線 (tuple[ndarray,...])。')
replace('    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))',
'''    n=len(price);pos=np.zeros((12000,5));trades=np.zeros((24000,11))
    state=np.zeros(n,dtype=np.int8);context=state
    selection_curve=np.zeros((n,20))
    selection_events=np.empty((7*n+8,15));selection_count=0
    applied=int(request[0]);seen_request=0;pending_owner=0;pending_source_id=0
    position_owner=0;position_source_id=0;cancel_wait=False;cancel_row=-1;cancel_target=0
    reprepare_due_to_switch=False''')
replace('''        p=price[i];t=time[i]
        if not np.isfinite(p) or p<=0:
            continue''', '''        p=price[i];t=time[i]
        # ----------------------------------------
        # 前行の取消を行先頭で確認し、旧注文を現在価格で約定させる前に失効させる。
        if cancel_wait:
            old_owner=pending_owner
            selection_count=selection_record(selection_events,selection_count,i,0,3,int(request[i]),applied,
                pending_owner,position_owner,pending_source_id,cancel_row,old_owner,cancel_target,
                pending_d,pending_level,pending_qty,campaign)
            pending_d=0;pending_owner=0;pending_source_id=0
            old_applied=applied;applied=cancel_target;cancel_wait=False
            selection_count=selection_record(selection_events,selection_count,i,0,4,int(request[i]),applied,
                0,position_owner,source_override if source_override else applied,cancel_row,old_applied,applied,
                0,np.nan,0,campaign)
            cancel_row=-1;cancel_target=0;reprepare_due_to_switch=True
        actual_source=position_source_id if position_owner else (source_override if source_override else applied)
        state[i]=states[i,actual_source-1]
        if not np.isfinite(p) or p<=0:
            # 価格が欠測でも既に要求した取消確認は完了する。新規判断と価格売買は旧版同様に止める。
            selection_curve[i,:]=np.array([request[i],applied,pending_owner,position_owner,actual_source,state[i],
                int(cancel_wait),cancel_row,pending_d,pending_row if pending_d else -1,pending_source_id,position_source_id,
                pending_level if pending_d else np.nan,last_exit+par[26]*60,pending_atr if pending_d else np.nan,
                pending_until if pending_d else np.nan,a if d else np.nan,stop_level,main_level,d])
            continue''')
replace('                fill=level', '                fill=p if observed_fill else level')
replace('base=realized;peak=0.;anchor=p if pending_market else pending_level;extreme=anchor',
        'base=realized;peak=0.;anchor=p if (observed_fill or pending_market) else pending_level;extreme=anchor')
replace('''            order_source=pending_row;pending_d=0;next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)''',
'''            order_source=pending_row
            position_owner=pending_owner;position_source_id=pending_source_id
            selection_count=selection_record(selection_events,selection_count,i,1,7,int(request[i]),applied,
                pending_owner,position_owner,position_source_id,order_source,pending_owner,position_owner,
                d,fill,open_qty,campaign)
            pending_d=0;pending_owner=0;pending_source_id=0
            next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)''')
replace('''            inv=inventory(pos,used);acted=True
            if promote:''', '''            inv=inventory(pos,used);acted=True
            selection_count=selection_record(selection_events,selection_count,i,1,9 if inv[0]+inv[1]<.5 else 8,
                int(request[i]),applied,pending_owner,position_owner,position_source_id,order_source,
                position_owner,0 if inv[0]+inv[1]<.5 else position_owner,-d,fill,done,campaign)
            if promote:''')
replace('''            d=0;last_exit=t;pending_action=0;pending_d=0;neutral_since=-1.''',
'''            d=0;last_exit=t;pending_action=0;pending_d=0;neutral_since=-1.
            position_owner=0;position_source_id=0;pending_owner=0;pending_source_id=0''')
replace('''        # ----------------------------------------
        # 現在行を観測して、次行以降だけで有効な注文条件を作る。''',
'''        # ----------------------------------------
        # 既存注文の約定後だけ現在要求を読む。保有中は所有者と価格出口を維持する。
        requested=int(request[i])
        changed_request=requested!=seen_request
        if changed_request:
            selection_count=selection_record(selection_events,selection_count,i,2,1,requested,applied,
                pending_owner,position_owner,position_source_id if position_owner else (source_override if source_override else applied),
                i,seen_request,requested,0,np.nan,0,campaign)
            seen_request=requested
        if d!=0:
            actual_source=position_source_id
            if changed_request and requested!=position_owner:
                selection_count=selection_record(selection_events,selection_count,i,2,11,requested,applied,
                    pending_owner,position_owner,actual_source,i,position_owner,requested,d,p,0,campaign)
        else:
            # 時間切れの注文は現在時刻では有効でないため、ID変更の取消待ちを作らない。
            if pending_d and t>=pending_until:
                selection_count=selection_record(selection_events,selection_count,i,2,10,requested,applied,
                    pending_owner,0,pending_source_id,i,pending_owner,0,pending_d,pending_level,pending_qty,campaign)
                pending_d=0;pending_owner=0;pending_source_id=0
            if requested!=applied:
                if pending_d:
                    cancel_wait=True;cancel_row=i;cancel_target=requested
                    selection_count=selection_record(selection_events,selection_count,i,2,2,requested,applied,
                        pending_owner,0,pending_source_id,i,applied,requested,pending_d,pending_level,pending_qty,campaign)
                else:
                    old_applied=applied;applied=requested
                    selection_count=selection_record(selection_events,selection_count,i,2,4,requested,applied,
                        0,0,source_override if source_override else applied,i,old_applied,applied,0,np.nan,0,campaign)
            actual_source=source_override if source_override else applied
        state[i]=states[i,actual_source-1]
        # ----------------------------------------
        # 現在行を観測して、次行以降だけで有効な注文条件を作る。''')

# ----------------------------------------
# フラット時の注文処理は取消確認待ちだけ抑止し、それ以外は旧処理順を残す。
begin = source.index('        else:\n            # 連敗後は同じ方向の小戻りを買い直さず')
end = source.index('    stats=np.array', begin)
old_flat = source[begin:end]
flat = old_flat.replace('        else:\n', '        elif not cancel_wait:\n', 1)
flat = flat.replace('''            if pending_d and (t>=pending_until or state[i]!=pending_d):pending_d=0''',
'''            if pending_d and (t>=pending_until or state[i]!=pending_d):
                selection_count=selection_record(selection_events,selection_count,i,2,10,requested,applied,
                    pending_owner,0,pending_source_id,i,pending_owner,0,pending_d,pending_level,pending_qty,campaign)
                pending_d=0;pending_owner=0;pending_source_id=0''')
flat = flat.replace('''                    pending_level=changed;pending_row=i''',
'''                    pending_level=changed;pending_row=i
                    selection_count=selection_record(selection_events,selection_count,i,2,6,requested,applied,
                        pending_owner,0,pending_source_id,i,pending_owner,pending_owner,pending_d,pending_level,pending_qty,campaign)''')
flat += '''        if d==0 and pending_d and pending_owner==0:
            pending_owner=applied;pending_source_id=source_override if source_override else applied
            selection_count=selection_record(selection_events,selection_count,i,2,12 if reprepare_due_to_switch else 5,
                requested,applied,pending_owner,0,pending_source_id,pending_row,0,pending_owner,
                pending_d,pending_level,pending_qty,campaign)
            reprepare_due_to_switch=False
        selection_curve[i,:]=np.array([requested,applied,pending_owner,position_owner,actual_source,state[i],
            int(cancel_wait),cancel_row,pending_d,pending_row if pending_d else -1,pending_source_id,position_source_id,
            pending_level if pending_d else np.nan,last_exit+par[26]*60,pending_atr if pending_d else np.nan,
            pending_until if pending_d else np.nan,a if d else np.nan,stop_level,main_level,d])
'''
replace(old_flat, flat)
replace('    return trades[:tc],cycles[:cc],curve,orders[:oc],stats',
        '    return trades[:tc],cycles[:cc],curve,orders[:oc],stats,selection_events[:selection_count].copy(),selection_curve')
source = source[:source.index('\ndef run(')] + '''
def run(ready: dict, states: np.ndarray, request: np.ndarray, config: dict, detail: bool=False,
        source_override: int=0, observed_fill: bool=False) -> dict:
    """機能: 共通D273だけで手法選択を売買へ接続し、元台帳と所有者履歴を返す。

    引数: ready/config (dict)、states (ndarray[int8], n×2) はT/R方向、request (ndarray[int8], n) は1=T/2=R。
    detail (bool)、source_override (int) は0=選択に従う/1=T固定/2=R固定、observed_fill (bool) は全価格約定を現観測値に置換。
    返り値: trades/cycles/curve/orders/statsとselection_events/selection_curveを持つ辞書 (dict)。
    selection_curveはdetailに関わらず全行。旧5結果の列と単位は変更しない。
    所有IDと実入口源は別列。固定requestかつspecifiedなら対応する旧D273と同じ売買を再現する。
    """
    n=len(ready['last'])
    if n<1 or not isinstance(states,np.ndarray) or states.dtype!=np.int8 or states.shape!=(n,2):
        raise ValueError('T/R方向は原本行数×2のndarray[int8]で指定してください')
    if not np.isin(states,(-1,0,1)).all():
        raise ValueError('T/R方向は-1/0/1に限ります')
    if not isinstance(request,np.ndarray) or request.dtype!=np.int8 or request.shape!=(n,) or not np.isin(request,(1,2)).all():
        raise ValueError('要求IDは原本行数のndarray[int8]、1=T/2=Rで指定してください')
    if type(source_override) is not int or source_override not in (0,1,2):
        raise ValueError('入口源の上書きは整数0/1/2に限ります')
    if not isinstance(observed_fill,(bool,np.bool_)):
        raise ValueError('観測約定の指定は真偽値に限ります')
    cap=config['audit_cap']
    if cap not in (10,20) or config['initial_qty']!=cap//2:
        raise ValueError('D273はTOPIX上限10/初回5、NK上限20/初回10に限定します')
    required={'entry_atr':.25,'stop_atr':1.,'main_trail':3.,'split_target':2.,
              'activation_atr':1.5,'timeout_min':360.,'cooldown_min':5.,'ttl_seconds':300.,
              'entry_mode':1,'entry_cutoff_min':5.,'warmup_min':20.,'after_open_factor':1.}
    disabled=('add_mode','add_qty','hedge_ratio','cover_add','reverse_mode','lock_fraction','neutral_min','us_mode',
              'tighten_atr','breakeven_atr','failure_min','signal_exit','max_same_losses','session_budget_r','risk_yen','session_budget_yen')
    if any(config.get(k)!=v for k,v in required.items()) or any(config.get(k)!=0 for k in disabled):
        raise ValueError('この注文器は選択以外を変えない共通D273設定に限定します')
    par=np.array([config[k] for k in PARAMS],dtype=float)
    values=simulate(ready['time_s'],ready['last'],ready['atr'],states,request,ready['tick'],
                    ready['start'],ready['limit'],ready['us_open'],par,detail,cap,source_override,observed_fill)
    return dict(zip(['trades','cycles','curve','orders','stats','selection_events','selection_curve'],values))
'''
(HERE / 'engine_selector.py').write_text(source, encoding='utf-8')
print('選択所有者付きD273注文器を新規作成。旧コード変更なし。')
