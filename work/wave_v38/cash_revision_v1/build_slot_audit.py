"""旧独立枠監査を新領域へ複写し、遅延・予算切替・分岐の独立式を追加する。"""

from pathlib import Path

HERE=Path(__file__).resolve().parent


def build() -> None:
    """機能: 旧監査を変更せず新版の枠監査を生成する。

    引数: なし。返り値: なし(None)。
    """
    text=(HERE.parent/'wave_v37/partial_slot_audit.py').read_text(encoding='utf-8')

    def replace(before: str,after: str) -> None:
        """機能: 一意の置換箇所を確認する。

        引数: before/after(str)。返り値: なし(None)。
        """
        nonlocal text
        assert text.count(before)==1,before
        text=text.replace(before,after)

    replace('import numpy as np','import numpy as np\nimport adaptive_shadow_oracle as shadow_oracle')
    replace('          good: np.ndarray, good_source: np.ndarray, good_valid: np.ndarray, curves: dict) -> dict:',
            '          good: np.ndarray, good_source: np.ndarray, good_valid: np.ndarray, curves: dict, *,\n'
            '          state: np.ndarray, budget_enabled: bool=True, min_delay_seconds: float=0., observed_fill: bool=False,\n'
            '          branch_direction: np.ndarray | None=None, branch_source: np.ndarray | None=None,\n'
            '          branch_valid: np.ndarray | None=None, branch_mode: str="fixed",\n'
            '          branch_choice: np.ndarray | None=None, branch_seed: int | None=None) -> dict:')
    replace("    events, adjustments, budgets = (result[k] for k in ('slot_events', 'adjustment_events', 'budget_events'))",
            '''    events, adjustments, budgets = (result[k] for k in ('slot_events', 'adjustment_events', 'budget_events'))
    transmitted=shadow_oracle.audit(ready,original,config,state,min_delay_seconds,observed_fill)
    raw_source=original['execution_plans'][:,33]
    effective_source=np.where(np.isfinite(raw_source),raw_source,-1).astype(np.int64)
    restore_code={'none':0,'signal':1,'timer':2}[policy['restore_mode']]
    branch_codes={'fixed':0,'adverse_signal':1,'reverse':2,'random':3}
    modes=np.full(n,restore_code,np.int64)
    expected_branch_curve=np.tile(np.asarray([restore_code,-1,-1,0.]),(n,1))
    marks={int(c[1]):np.asarray([restore_code,-1,-1,0.]) for c in cycles}
    branch_expected=[]
    directions={int(c[0]):int(c[8]) for c in cycles}
    branch_number={}
    if branch_mode!='fixed':
        for event in adjustments[(adjustments[:,2]==2)&(adjustments[:,3]==-1)]:
            row,campaign=int(event[0]),int(event[1]);d=directions[campaign]
            valid=bool(branch_valid[row]);direction_at=int(branch_direction[row]);source=int(branch_source[row])
            assert -1<=source<=row and (not valid or source>=0)
            classification=0 if not valid else 1 if direction_at==0 else 2 if direction_at==d else 3
            adverse=valid and direction_at==-d
            signal=adverse if branch_mode=='adverse_signal' else not adverse if branch_mode=='reverse' else bool(branch_choice[row])
            mode=1 if signal else 2;branch_number[campaign]=branch_number.get(campaign,0)+1
            branch_expected.append([row,campaign,branch_number[campaign],mode,direction_at,source,int(valid),classification,
                                   branch_codes[branch_mode],-1 if branch_seed is None else branch_seed])
            marks[row]=np.asarray([mode,row,source,classification])
    for row in sorted(marks):
        expected_branch_curve[row:]=marks[row]
    close(result['branch_events'],np.asarray(branch_expected,dtype=float).reshape((-1,10)),'全分岐の独立判断')
    close(result['branch_curve'],expected_branch_curve,'全行の分岐保持')
    modes=expected_branch_curve[:,0].astype(np.int64)''')
    replace("a = float(original['plans'][start-1, 24]); risk = q0*a",
            "a = float(original['execution_plans'][start,24]); risk = q0*a")
    text=text.replace("original['plans'][row-1,33]",'effective_source[row]')
    replace('            assert plan_row == effective_source[row] and plan_row < row',
            '            assert plan_row == effective_source[row] and -1 <= plan_row < row')
    replace('        if len(breaches):','        if budget_enabled and len(breaches):')
    replace('            next_row = first+1\n            while (campaign,next_row,7) in original_actions: next_row += 1\n            assert end == next_row, \'予算は元部分利確以外で遅らせない\'',
            '''            next_row=max(first+1,int(np.searchsorted(times,times[first]+min_delay_seconds,side='left')))
            while (campaign,next_row,7) in original_actions:next_row+=1
            original_full=[r for cid,r,reason in original_actions if cid==campaign and first<r and reason in (1,2,8,9)]
            expected_end=min([next_row]+original_full)
            assert end==expected_end,'成熟予算又は先行元全返済で終了する' ''')
    replace("                assert kind == 1 and policy['restore_mode'] != 'none' and empty.any() and good_source[row] == evidence",
            "                assert kind == 1 and modes[row]!=0 and empty.any() and good_source[row] == evidence")
    replace("                if policy['restore_mode'] == 'signal': assert good[row] == d",
            "                if modes[row]==1: assert good[row] == d and (branch_mode=='fixed' or good_valid[row])")
    replace('            assert resolution == row+1 and outcome[3] == kind and outcome[5] == evidence and outcome[6] == qty and outcome[8] == mask',
            '''            mature=max(row+1,int(np.searchsorted(times,times[row]+min_delay_seconds,side='left')))
            original_next=[r for cid,r,code in original_actions if cid==campaign and r>row and 1<=code<=14]
            budget_cancel=[int(b[0]) for b in requests if row<b[0]<mature]
            expected_resolution=min([mature]+original_next+budget_cancel)
            assert resolution==expected_resolution and outcome[3] == kind and outcome[5] == evidence and outcome[6] == qty and outcome[8] == mask
            assert saved_count==int(np.sum((ca[:,2]==2)&(ca[:,3]==-1)&(ca[:,0]<row)))
            assert outcome[9]==int(np.sum((ca[:,2]==2)&(ca[:,3]==-1)&(ca[:,0]<=resolution)))''')
    replace("        if policy['restore_mode'] != 'none':", "        if np.any(modes!=0):")
    replace("            if policy['restore_mode'] == 'signal': restore &= good == direction\n            else:\n                deadline = times[np.maximum(0,latest_reduction)] + policy['restore_seconds']\n                restore &= good_valid & (times >= deadline) & (times[np.maximum(0,good_source)] >= deadline)",
            '''            deadline=times[np.maximum(0,latest_reduction)]+policy['restore_seconds']
            signal=(modes==1)&(good==direction)
            if branch_mode!='fixed':signal &= good_valid
            timer=(modes==2)&good_valid&(times>=deadline)&(times[np.maximum(0,good_source)]>=deadline)
            restore &= signal|timer''')
    replace("    close(control[:,5], ((slots&2)!=0).sum(axis=1).astype(float), '全行実保有枚数')",
            '''    # 全予約の保持・取消も約定ログと独立の区間で復元する。
    expected_pending=np.zeros((n,3));expected_pending[:,1:]=-1
    for reservation in decisions:
        row=int(reservation[0]);campaign=int(reservation[1])
        outcome=adjustments[(adjustments[:,1]==campaign)&(adjustments[:,4]==row)&np.isin(adjustments[:,2],(2,3))]
        finish=int(outcome[0,0]);expected_pending[row:finish]=[reservation[3],row,reservation[5]]
    close(control[:,8:11],expected_pending,'全行の調整予約保持')
    phase=np.where(active,np.where(debt_count>0,2,0),0)
    phase[expected_pending[:,0]<0]=1;phase[expected_pending[:,0]>0]=3
    close(control[:,2],phase,'全行の減量状態')
    close(control[:,15],(~active).astype(float),'全行の組終了状態')
    for order in result['orders']:
        row,source=int(order[0]),int(order[1])
        assert source<row and times[row]>=times[source]+min_delay_seconds-1e-8
        assert times[row]<ready.get('session_close',ready['limit']+600.)
    close(control[:,5], ((slots&2)!=0).sum(axis=1).astype(float), '全行実保有枚数')''')
    replace("    return dict(全枠会計一致=True, 全予約と新根拠一致=True, 元終了以前=True,",
            "    return dict(影の独立公開と執行=transmitted,全分岐独立一致=True,全伝達遅延一致=True,\n        全枠会計一致=True, 全予約と新根拠一致=True, 元終了以前=True,")
    (HERE/'adaptive_slot_audit.py').write_text(text,encoding='utf-8',newline='\n')


if __name__=='__main__':build()
