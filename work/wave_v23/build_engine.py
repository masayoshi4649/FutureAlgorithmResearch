"""監査済み次行執行器を、新規の管理条件を持つ別ファイルへ複製する。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
text = (ROOT / 'work/wave_v19/engine.py').read_text(encoding='utf-8-sig')
text = text.replace('M3逆A00の入口・出口を、元と同じ原本行順で比較する状態機械。',
                    '任意の因果的方向信号を、原本行順・次行執行で比較する建玉管理器。')
text = text.replace("'after_open_factor']", "'after_open_factor','entry_cutoff_min','warmup_min','max_same_losses',\n          'rearm_atr','session_budget_r','risk_yen','point_value','session_budget_yen',\n          'max_reversals']")
text = text.replace("13:'方向状態の撤回'}", "13:'方向状態の撤回',14:'セッション損失予算'}")
text = text.replace('protected_floor=-1e100;main_floor=np.nan;pending_extreme=0.',
'''protected_floor=-1e100;main_floor=np.nan;pending_extreme=0.
    effective_qty=int(par[0]);pending_qty=int(par[0]);pending_market=False
    loss_streak=np.zeros(2,dtype=np.int64);blocked=np.zeros(2,dtype=np.bool_)
    blocked_price=np.zeros(2);blocked_atr=np.ones(2);campaign_side=0
    session_halted=False;session_budget=np.nan
    if par[38]>0:
        session_budget=par[38]/par[37]''')
text = text.replace('elif pending_d and t<pending_until and t<end-1800',
                    'elif pending_d and not session_halted and t<pending_until and t<end-par[31]*60')
text = text.replace('and pending_d*(p-pending_level)>=-1e-8:',
                    'and (pending_market or pending_d*(p-pending_level)>=-1e-8):')
text = text.replace('d=pending_d;a=pending_atr;risk=par[0]*par[2]*a;campaign+=1',
                    'd=pending_d;a=pending_atr;effective_qty=pending_qty;risk=effective_qty*par[2]*a;campaign+=1;campaign_side=d')
text = text.replace('base=realized;peak=0.;anchor=pending_level;extreme=anchor',
                    'base=realized;peak=0.;anchor=p if pending_market else pending_level;extreme=anchor')
text = text.replace('open_qty=int(par[0]);open_role=0;reason=20',
                    'open_qty=effective_qty;open_role=0;reason=20')
text = text.replace('max(0,int(par[0]-inv[0]))', 'max(0,int(effective_qty-inv[0]))')
text = text.replace('floor=max(floor,par[0]*par[22]*a)', 'floor=max(floor,effective_qty*par[22]*a)')
text = text.replace('floor=max(floor,-par[0]*par[25]*a)', 'floor=max(floor,-effective_qty*par[25]*a)')
text = text.replace('            d=0;last_exit=t;pending_action=0;pending_d=0;neutral_since=-1.',
'''            ix=0 if campaign_side>0 else 1
            if realized-base<-.00000001:
                loss_streak[ix]+=1
                if par[33]>0 and loss_streak[ix]>=int(par[33]):
                    blocked[ix]=True;blocked_price[ix]=p;blocked_atr[ix]=a
            else:
                loss_streak[ix]=0
            d=0;last_exit=t;pending_action=0;pending_d=0;neutral_since=-1.''')
text = text.replace('        if detail:\n            curve[i,:]',
'''        # 固定予算を割った時点から、返済だけを許し当該セッションの再開を禁止する。
        if np.isfinite(session_budget) and equity<=-session_budget+1e-8:
            session_halted=True;pending_d=0
        if detail:
            curve[i,:]''')
text = text.replace('            if e<=floor-1e-8:',
'''            if t>=end:
                pending_action=9;action_row=i
            elif session_halted:
                pending_action=14;action_row=i
            elif e<=floor-1e-8:''')
text = text.replace('            elif t>=end:\n                pending_action=9;action_row=i\n', '')
text = text.replace('elif state[i]==-d and int(par[12])>0 and (',
                    'elif state[i]==-d and int(par[12])>0 and reversals<int(par[39]) and (')
text = text.replace('if int(par[4])>0 and inv[0]<cap and state[i]==d:',
                    'if int(par[4])>0 and inv[0]<cap and state[i]==d and e>0 and d*(p-anchor)>0:')
text = text.replace('if int(par[17])==1 and t>=us_open-900 and t<us_open+1800:',
                    'if int(par[17])==1 and t<end and not session_halted and t>=us_open-900 and t<us_open+1800:')
text = text.replace('if par[16]>0 and t-neutral_since>=par[16]*60:',
                    'if par[16]>0 and t<end and not session_halted and t-neutral_since>=par[16]*60:')
text = text.replace('        else:\n            if pending_d and (t>=pending_until',
'''        else:
            # 連敗後は同じ方向の小戻りを買い直さず、反対根拠か新値を待つ。
            for bx in range(2):
                bd=1 if bx==0 else -1
                if blocked[bx] and (state[i]==-bd or bd*(p-blocked_price[bx])>=par[34]*blocked_atr[bx]):
                    blocked[bx]=False;loss_streak[bx]=0
            if pending_d and (t>=pending_until''')
text = text.replace('if not pending_d and t>=start+1200 and t<end-1800 and t>=last_exit+par[26]*60 and not paused:',
                    'if not pending_d and not session_halted and t>=start+par[32]*60 and t<end-par[31]*60 and t>=last_exit+par[26]*60 and not paused:')
text = text.replace('if state[i]!=0 and np.isfinite(atr[i]) and atr[i]>0:',
                    'if state[i]!=0 and not blocked[0 if state[i]>0 else 1] and np.isfinite(atr[i]) and atr[i]>0:')
text = text.replace('                    pending_until=t+par[27];pending_row=i;pending_extreme=p',
'''                    pending_until=t+par[27];pending_row=i;pending_extreme=p
                    pending_qty=int(par[0])
                    if par[36]>0:
                        per_contract_risk=np.ceil(pending_atr*par[2]/tick-1e-9)*tick*par[37]
                        pending_qty=min(cap,int(np.floor(par[36]/per_contract_risk)))
                    pending_market=int(par[28])==2 or pending_d*(p-pending_level)>=-1e-8
                    if pending_qty<1:
                        pending_d=0
                    elif not np.isfinite(session_budget) and par[35]>0:
                        session_budget=par[35]*pending_qty*par[2]*pending_atr''')
text = text.replace("    par=np.array([config[k] for k in PARAMS],dtype=float)",
'''    if len(state)!=len(ready['last']):
        raise ValueError('方向信号と原本行の長さが一致しません')
    if np.any((state < -1) | (state > 1)):
        raise ValueError('方向信号は -1、0、1 に限ります')
    if config['initial_qty']<1 or config['initial_qty']>config['audit_cap']:
        raise ValueError('初期枚数が片方向上限の範囲外です')
    par=np.array([config[k] for k in PARAMS],dtype=float)''')
(ROOT / 'work/wave_v23/engine.py').write_text(text, encoding='utf-8')
