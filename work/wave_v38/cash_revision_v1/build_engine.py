"""旧版の複写へ注文伝達遅延・R切替・復元選択を追加する生成器。"""

from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'wave_v37'


def build_shadow() -> dict:
    """機能: 旧影の会計と準備を保持し、成熟済み計画による注文執行を追加する。

    引数: なし。返り値: 生成元・新ソースの内容指紋 (dict)。
    """
    source = PRIOR / 'engine_shadow_plan.py'
    original = source.read_bytes()
    text = original.decode('utf-8-sig').replace('\r\n', '\n')

    def change(before: str, after: str) -> None:
        """機能: 一意の位置だけを変更する。

        引数: before/after (str)。返り値: なし (None)。
        """
        nonlocal text
        assert text.count(before) == 1, before
        text = text.replace(before, after)

    change('cap, width_mode, observed_fill, prepare_allow):',
           'cap, width_mode, observed_fill, prepare_allow, min_delay_seconds, session_close):')
    change('    plans=np.full((n,37),np.nan)',
           '    plans=np.full((n,37),np.nan)\n'
           '    execution_plans=np.full((n,37),np.nan); mature_row=-1')
    start = text.index('        # 前行で決めた市場返済と方向転換を先に処理する。')
    finish = text.index('        # 返済、カバー昇格、新規約定。', start)
    block = '''        # 最新の成熟済み計画だけを受信する。未成熟更新で旧有効線を失わない。
        while mature_row+1<i and time[mature_row+1]<=t-min_delay_seconds+1e-9:
            mature_row+=1
        effective=np.full(37,np.nan)
        if mature_row>=0 and np.isfinite(plans[mature_row,33]):
            candidate=plans[mature_row]
            if int(candidate[1])==campaign and int(candidate[0])==d:
                effective=candidate.copy()
                # 在庫変化はローカル約定結果。古い部分利確注文は二重執行しない。
                effective[7]=inv[0];effective[8]=realized;effective[9]=base
                if split_done:
                    effective[14]=np.nan;effective[17]=0.
                effective[11]=int(split_done)
        if t>=session_close:
            if d!=0:
                raise ValueError('終場までに有効な全返済行がありません')
            effective[:]=np.nan
        execution_plans[i,:]=effective
        if np.isfinite(effective[33]):
            order_source=i-1 if min_delay_seconds==0 else int(effective[33])
            if d!=0 and int(effective[18])!=0:
                reason=int(effective[18]);fill=p;order_source=int(effective[19])
                close_role=-1;close_qty=100000;pending_action=0
            elif d!=0:
                # 共通D273の停止・追跡・元部分利確だけを同じ優先順で判定する。
                best=1e100;event=0;level=0.;prior=price[i-1] if i else p
                for z in range(3):
                    value=effective[12+z];side=d if z==2 else -d
                    flag=bool(effective[15+z])
                    if not np.isfinite(value) or (not flag and side*(p-value)<-1e-8):
                        continue
                    distance=0. if flag else max(0.,side*(value-prior))
                    if distance<best-1e-9:
                        best=distance;event=z+1;level=p if flag else value
                if event:
                    fill=p if observed_fill else level
                    reason=int(effective[20]) if event==1 else (2 if event==2 else 7)
                    close_role=-1 if event!=3 else 0
                    close_qty=100000 if event!=3 else max(1,int(inv[0]/2))
                    if event==3:split_done=True
            elif int(effective[21]) and not bool(effective[30]) and t<effective[23] and t<end-par[31]*60:
                pd=int(effective[21]);market=bool(effective[26])
                if market or pd*(p-effective[22])>=-1e-8:
                    d=pd;a=effective[24];effective_qty=int(effective[25])
                    risk=effective_qty*par[2]*a;campaign+=1;campaign_side=d
                    base=realized;peak=0.;anchor=p if (observed_fill or market) else effective[22];extreme=anchor
                    protected_floor=-risk;main_floor=np.nan
                    current_atr=a;current_atr_source=-1;trail_source=-1
                    entry_row=i;entry_t=t;cycle_gross=0.;cycle_net=0.;split_done=False
                    fill=anchor;open_side=d;open_qty=effective_qty;open_role=0;reason=20
                    order_source=int(effective[27])
                    if entry_prepare_count>=len(entry_preparations):
                        raise ValueError('約定元準備の記録上限を超えました')
                    entry_preparations[entry_prepare_count,:]=np.array([campaign,i,effective[28],effective[29]])
                    entry_prepare_count+=1
                    pending_d=0;next_add=anchor+d*par[5]*a*(-1 if int(par[4])==2 else 1)
                    cover_anchor=0.;next_cover=0.
        # ----------------------------------------
'''
    text = text[:start] + block + text[finish:]
    change('entry_preparations[:entry_prepare_count],plans\n',
           'entry_preparations[:entry_prepare_count],plans,execution_plans\n')
    change('trail_atr: np.ndarray | None=None, prepare_allow: np.ndarray | None=None) -> dict:',
           'trail_atr: np.ndarray | None=None, prepare_allow: np.ndarray | None=None,\n'
           '        min_delay_seconds: float=0.) -> dict:')
    change('    n=len(ready[\'last\'])',
           "    n=len(ready['last'])\n"
           "    if len(ready['time_s'])!=n or not np.isfinite(ready['time_s']).all() or (np.diff(ready['time_s'])<0).any():\n"
           "        raise ValueError('時刻は原本行対応の有限・非減少列が必要です')\n"
           "    if isinstance(min_delay_seconds,(bool,np.bool_)) or min_delay_seconds not in (0.,1.,5.,15.):\n"
           "        raise ValueError('注文伝達遅延は0/1/5/15秒に限ります')\n"
           "    session_close=float(ready.get('session_close',ready['limit']+600.))\n"
           "    if not np.isfinite(session_close) or session_close<=ready['limit']:\n"
           "        raise ValueError('終場時刻は安全返済判断時刻より後に限ります')\n")
    change('width_mode,observed_fill,prepare_allow)\n',
           'width_mode,observed_fill,prepare_allow,float(min_delay_seconds),session_close)\n')
    change("'prepare_events','entry_preparations','plans'],values))",
           "'prepare_events','entry_preparations','plans','execution_plans'],values))")
    change('    返り値: 旧6結果とprepare_events、entry_preparationsの辞書 (dict)。旧6結果の列・単位は不変。',
           '    min_delay_seconds(float)は公開から有効化までの0/1/5/15秒。入力情報の遅延ではない。\n'
           '    返り値: 旧6結果、準備2、行後plans、行前execution_plansの辞書(dict)。旧列・単位は不変。\n'
           '    execution_plansは現在価格を約定判定する前に、成熟済みの計画と既約定状態だけで決める。\n'
           '    元返済時刻の事後コピーではなく、実口座も同じ計画を現在価格へ適用する。')
    target = HERE / 'engine_shadow_plan.py'
    target.write_text(text, encoding='utf-8', newline='\n')
    assert source.read_bytes() == original
    return dict(元=str(source),元SHA256=hashlib.sha256(original).hexdigest(),新=str(target),新SHA256=hashlib.sha256(target.read_bytes()).hexdigest())


def build_actual() -> dict:
    """機能: 枠調整の旧実装に独立R切替・減量時分岐・予約遅延を追加する。

    引数: なし。返り値: 生成元・新ソースの内容指紋 (dict)。
    """
    source = PRIOR / 'engine_partial_restore.py'
    original = source.read_bytes()
    text = original.decode('utf-8-sig').replace('\r\n', '\n')

    def change(before: str, after: str) -> None:
        """機能: 一意の位置だけを変更する。

        引数: before/after (str)。返り値: なし (None)。
        """
        nonlocal text
        assert text.count(before) == 1, before
        text = text.replace(before, after)

    change("FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve')",
           "FIELDS = ('trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve')\n"
           "BRANCH_COLUMNS = ['row','campaign','reduction_number','restore_mode','direction','source_row','valid','classification','branch_mode','seed']\n"
           "BRANCH_CURVE_COLUMNS = ['restore_mode','selection_row','source_row','classification']\n"
           "BRANCH_NAMES = {0:'固定',1:'逆方向なら信号',2:'逆分岐',3:'固定乱数'}\n"
           "BRANCH_CLASSIFICATION = {0:'欠測',1:'有効中立',2:'有効順方向',3:'有効逆方向'}")
    change("31: '新しい肯定による数量復元'", "31: '数量復元'")
    change('def input_digest(ready: dict, state: np.ndarray, config: dict, observed_fill: bool) -> str:',
           'def input_digest(ready: dict, state: np.ndarray, config: dict, observed_fill: bool, min_delay_seconds: float=0.) -> str:')
    change('    h.update(str(bool(observed_fill)).encode())',
           "    h.update(str(bool(observed_fill)).encode())\n"
           "    h.update(repr((float(min_delay_seconds),float(ready.get('session_close',ready['limit']+600.)))).encode())")
    change('def make_shadow(ready: dict, state: np.ndarray, config: dict, observed_fill: bool = False) -> dict:',
           'def make_shadow(ready: dict, state: np.ndarray, config: dict, observed_fill: bool = False, min_delay_seconds: float=0.) -> dict:')
    change('result = shadow_engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=observed_fill)',
           'result = shadow_engine.run(ready, state, config, detail=True, width_mode=0, observed_fill=observed_fill, min_delay_seconds=min_delay_seconds)')
    change("result['input_sha256'] = input_digest(ready, state, config, observed_fill)",
           "result['input_sha256'] = input_digest(ready, state, config, observed_fill, min_delay_seconds)")
    change("    result['observed_fill'] = bool(observed_fill)",
           "    result['observed_fill'] = bool(observed_fill)\n    result['min_delay_seconds'] = float(min_delay_seconds)")
    change('def simulate(time, price, plans, shadow_atr, bad, bad_source, good, good_source, good_valid,',
           'def simulate(time, price, plans, execution_plans, shadow_atr, bad, bad_source, good, good_source, good_valid,')
    change('             observed_fill, detail):',
           '             observed_fill, detail, budget_enabled, min_delay_seconds, branch_direction,\n'
           '             branch_source, branch_valid, branch_choice, branch_mode, branch_seed):')
    change('    budgets = np.zeros((6000, 8)); bc = 0',
           '    budgets = np.zeros((6000, 8)); bc = 0\n'
           '    branch_events=np.zeros((12000,10)); brc=0\n'
           '    branch_curve=np.full((n,4),-1.) if detail else np.full((1,4),-1.)\n'
           '    chosen_restore=restore_mode;branch_row=-1;branch_evidence=-1;branch_class=0')
    change('                control[i] = control[i-1]; slot_curve[i] = slot_curve[i-1]',
           '                control[i] = control[i-1]; slot_curve[i] = slot_curve[i-1]; branch_curve[i]=branch_curve[i-1]')
    change('        if i and np.isfinite(plans[i-1, 33]):\n            plan = plans[i-1]',
           '        if i and np.isfinite(execution_plans[i, 33]):\n            plan = execution_plans[i]')
    change('            plan_row = int(plan[33]); sd = int(plan[0]); shadow_campaign = int(plan[1]); planned_qty = plan[7]',
           '            plan_row = int(plan[33]); sd = int(plan[0]); shadow_campaign = int(plan[1]); planned_qty = plan[7]\n'
           '            source=i-1 if min_delay_seconds==0 else plan_row')
    change('                    reduction_row = -1; budget = False; budget_row = -1',
           '                    reduction_row = -1; budget = False; budget_row = -1\n'
           '                    chosen_restore=restore_mode;branch_row=-1;branch_evidence=-1;branch_class=0')
    change('        elif not is_entry and not closed and budget:',
           '        elif not is_entry and not closed and budget and i>budget_row and t>=budget_time+min_delay_seconds-1e-9:')
    change('        elif not is_entry and not closed and pending:',
           '        elif not is_entry and not closed and pending and not budget and i>pending_row and t>=time[pending_row]+min_delay_seconds-1e-9:')
    change('                reduction_row = i; reduction_time = t; phase = 2',
           '''                reduction_row = i; reduction_time = t; phase = 2
                if branch_mode:
                    is_valid=bool(branch_valid[i]);bd=int(branch_direction[i])
                    branch_class=0 if not is_valid else (1 if bd==0 else (2 if bd==d else 3))
                    adverse=is_valid and bd==-d
                    choose_signal=adverse if branch_mode==1 else (not adverse if branch_mode==2 else bool(branch_choice[i]))
                    chosen_restore=1 if choose_signal else 2
                    branch_row=i;branch_evidence=int(branch_source[i])
                    if brc>=len(branch_events):raise ValueError('復元分岐の記録上限です')
                    branch_events[brc]=np.array([i,campaign,reductions,chosen_restore,bd,branch_evidence,
                        int(is_valid),branch_class,branch_mode,branch_seed]);brc+=1''')
    change('            if e <= -risk and not budget:',
           '            if budget_enabled and e <= -risk and not budget:')
    change('elif phase == 2 and restore_mode and good_source[i] > barrier and good_source[i] > reduction_row:',
           'elif phase == 2 and chosen_restore and good_source[i] > barrier and good_source[i] > reduction_row:')
    change('fresh = good[i] == d if restore_mode == 1 else (',
           'fresh = (good[i] == d and (branch_mode==0 or good_valid[i])) if chosen_restore == 1 else (')
    change('        if detail:\n            curve[i] = np.array([equity, realized, inv[4], inv[5], dd, cash, inv[2], campaign])',
           '        if detail:\n            branch_curve[i]=np.array([chosen_restore,branch_row,branch_evidence,branch_class])\n'
           '            curve[i] = np.array([equity, realized, inv[4], inv[5], dd, cash, inv[2], campaign])')
    change('control, slot_curve, slot_events[:sc], adjustment[:ac], budgets[:bc])',
           'control, slot_curve, slot_events[:sc], adjustment[:ac], budgets[:bc], branch_events[:brc], branch_curve)')
    # ----------------------------------------
    # 公開runは旧検査を保ったまま追加引数だけを検査する。
    change('good_valid: np.ndarray | None = None) -> dict:',
           'good_valid: np.ndarray | None = None, budget_enabled: bool=True,\n'
           '        branch_direction: np.ndarray | None=None, branch_source: np.ndarray | None=None,\n'
           '        branch_valid: np.ndarray | None=None, branch_mode: str="fixed",\n'
           '        branch_choice: np.ndarray | None=None, branch_seed: int | None=None,\n'
           '        min_delay_seconds: float=0.) -> dict:')
    # 下記wrapper接続は原本の現在形式を完全に一致させて置換する。
    change("    modes = {'baseline': 0, 'static_core': 1, 'static_split': 2, 'dynamic': 3}",
           """    branch_modes={'fixed':0,'adverse_signal':1,'reverse':2,'random':3}
    if branch_mode not in branch_modes:raise ValueError('復元分岐方式が不正です')
    if not isinstance(budget_enabled,(bool,np.bool_)):raise ValueError('追加R退出は真偽値です')
    if isinstance(min_delay_seconds,(bool,np.bool_)) or min_delay_seconds not in (0.,1.,5.,15.):
        raise ValueError('注文伝達遅延は0/1/5/15秒です')
    supplied=(branch_direction,branch_source,branch_valid)
    if branch_mode!='fixed' and any(value is None for value in supplied):
        raise ValueError('復元分岐にはB01方向・source・有効性が必要です')
    if branch_direction is None:branch_direction=np.zeros(n,np.int8)
    if branch_source is None:branch_source=np.full(n,-1,np.int64)
    if branch_valid is None:branch_valid=np.zeros(n,np.bool_)
    for value,dtype in ((branch_direction,np.int8),(branch_source,np.int64),(branch_valid,np.bool_)):
        if not isinstance(value,np.ndarray) or value.dtype!=dtype or value.shape!=(n,):
            raise ValueError('復元分岐列の型・長さが不正です')
    if not np.isin(branch_direction,(-1,0,1)).all() or (branch_source< -1).any() or (branch_source>np.arange(n)).any():
        raise ValueError('復元分岐列に未来source又は不正方向があります')
    if (branch_valid & (branch_source<0)).any():raise ValueError('有効分岐に公開sourceが必要です')
    if branch_mode=='random' and (type(branch_seed) is not int or not 0<=branch_seed<64 or branch_choice is None):
        raise ValueError('乱数分岐には固定seedと入力選択列が必要です')
    if branch_choice is None:branch_choice=np.zeros(n,np.int8)
    if not isinstance(branch_choice,np.ndarray) or branch_choice.dtype!=np.int8 or branch_choice.shape!=(n,) or not np.isin(branch_choice,(0,1)).all():
        raise ValueError('乱数分岐選択列はint8の0/1です')
    if branch_mode!='fixed' and policy['kind']!='dynamic':raise ValueError('復元分岐は動的数量だけに指定できます')
    modes = {'baseline': 0, 'static_core': 1, 'static_split': 2, 'dynamic': 3}""")
    change("policy.get('restore_seconds', 120.) != 120.",
           "policy.get('restore_seconds', 120.) not in (96.,120.,144.)")
    change("raise ValueError('時計復元は120秒固定です')", "raise ValueError('時計復元は96/120/144秒です')")
    change("if policy['restore_mode'] == 'timer': raise ValueError('時計復元には有効公開列が必要です')",
           "if policy['restore_mode'] == 'timer' or branch_mode!='fixed': raise ValueError('時計又は分岐復元には有効公開列が必要です')")
    change('shadow = make_shadow(ready, state, config, observed_fill)',
           'shadow = make_shadow(ready, state, config, observed_fill, min_delay_seconds)')
    change('input_digest(ready, state, config, observed_fill)',
           'input_digest(ready, state, config, observed_fill, min_delay_seconds)')
    change("ready['time_s'], ready['last'], shadow['plans'], shadow['atr_curve'],",
           "ready['time_s'], ready['last'], shadow['plans'], shadow['execution_plans'], shadow['atr_curve'],")
    change('observed_fill, detail)\n',
           'observed_fill, detail, bool(budget_enabled), float(min_delay_seconds), branch_direction, branch_source,\n'
           '        branch_valid, branch_choice, branch_modes[branch_mode], -1 if branch_seed is None else branch_seed)\n')
    change("'slot_events', 'adjustment_events', 'budget_events'), values))",
           "'slot_events', 'adjustment_events', 'budget_events', 'branch_events', 'branch_curve'), values))")
    change("    if shadow['plans'].shape != (n, len(PLAN_COLUMNS)):",
           "    if shadow['plans'].shape != (n, len(PLAN_COLUMNS)) or shadow['execution_plans'].shape != (n,len(PLAN_COLUMNS)):")
    change("    values = simulate(ready['time_s'], ready['last'], shadow['plans'], shadow['execution_plans'], shadow['atr_curve'], bad, bad_source,",
           """    execution=shadow['execution_plans'];present=np.isfinite(execution[:,33])
    references=execution[present,33];rows=np.flatnonzero(present)
    if (references!=np.floor(references)).any() or (references<0).any() or (references>=rows).any():
        raise ValueError('有効注文計画に未来又は不正な公開行があります')
    indices=references.astype(np.int64)
    if (ready['time_s'][indices]+min_delay_seconds>ready['time_s'][rows]+1e-9).any():
        raise ValueError('未成熟の注文計画があります')
    values = simulate(ready['time_s'], ready['last'], shadow['plans'], shadow['execution_plans'], shadow['atr_curve'], bad, bad_source,""")
    change('    返り値: 旧6結果、準備2、管理・枠・調整・予算証跡、独立影(dict)。損益の単位は価格×枚数。',
           '    budget_enabled(bool)は追加実損益R退出のみの有効性。min_delay_seconds(float)は注文伝達の秒数。\n'
           '    branch_direction/source/valid(ndarray|None)は選択用B01の公開方向・ready行・品質。\n'
           '    branch_mode(str)はfixed/adverse_signal/reverse/random、choice(int8列|None)は0時計/1信号。\n'
           '    branch_seed(int|None)は入力側の固定乱数種の記録。engine側では乱数を生成しない。\n'
           '    返り値: 旧6結果、準備2、旧証跡、branch_events/curve、独立影(dict)。損益は価格×枚数。')
    target = HERE / 'engine_partial_restore.py'
    target.write_text(text, encoding='utf-8', newline='\n')
    assert source.read_bytes() == original
    return dict(元=str(source),元SHA256=hashlib.sha256(original).hexdigest(),新=str(target),新SHA256=hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == '__main__':
    result=dict(影=build_shadow(),実=build_actual(),旧ファイル変更=False)
    (HERE/'engine_build.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
