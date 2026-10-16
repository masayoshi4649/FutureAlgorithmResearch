"""当時状態からC/Rの原候補を一つのイベント列へ統合する。"""

from copy import deepcopy

import numpy as np

import features


def build(prepared: dict, cases: dict, measured: dict, config: dict) -> tuple[dict,list]:
    """
    機能: RANGE先の共通分類で、候補rowのC/Rを排他的に一回選ぶ。
    引数: prepared/cases/measured/config(dict)は同normal入力、C/R旧候補、当時特徴と固定条件。
    返り値: tuple[dict,list]は統合normalと全候補の採否。旧金融の取引結果は使用しない。
    """
    c,r=cases['C_OWN'],cases['R_OWN'];n=len(c['event'])
    for name in ('entry_quality','entry_reset','execution_to_raw_index'):
        np.testing.assert_array_equal(c[name],r[name],err_msg=name)
    normal=dict(entry_id=config['entry_id'],event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),
        entry_quality=c['entry_quality'],entry_reset=c['entry_reset'],execution_to_raw_index=c['execution_to_raw_index'],
        decisions=[],entry_families=np.zeros(n,np.int8),target_prices=np.full(n,np.nan))
    metadata={fam:{int(v['row']):v for v in case['decisions']} for fam,case in (('C',c),('R',r))}
    diagnostic=[];mode=config['mode'];q=config['quantity'][prepared['record']['symbol']]
    candidates=np.flatnonzero((c['event']!=0)|(r['event']!=0))
    assert set(candidates)==set(measured)
    for row in candidates:
        row=int(row);pair=measured[row];state=features.classify(pair,config['trend_bp'],config['range_er'])
        chosen=None;reason=state;order=None
        if state=='RANGE':
            if mode=='C_ONLY':reason='modeでRを使わない'
            elif not r['event'][row]:reason='RANGEだが新R候補なし'
            else:
                order=features.range_order(prepared,r,row,pair['own'],q)
                if order['allowed']:chosen='R';reason='RANGEでR許可'
                else:reason=order['reason']
        elif state in ('TREND_UP','TREND_DOWN'):
            direction=1 if state=='TREND_UP' else -1
            if mode=='R_ONLY':reason='modeでCを使わない'
            elif int(c['event'][row])!=direction:reason='共通方向に一致する新C候補なし'
            else:chosen='C';reason='双方進行でC許可'
        diagnostic.append(dict(row=row,raw_seq=int(prepared['record']['seq'][row]),state=state,
            C_event=int(c['event'][row]),R_event=int(r['event'][row]),chosen=chosen,reason=reason,range_order=order,
            observed_pair=pair))
        if chosen is None:continue
        original=c if chosen=='C' else r;normal['event'][row]=original['event'][row]
        normal['support_price'][row]=original['support_price'][row]
        normal['entry_families'][row]=1 if chosen=='C' else 2
        if chosen=='R':normal['target_prices'][row]=order['target']
        decision=deepcopy(metadata[chosen][row]);decision.update(chosen_family=chosen,
            regime=state,regime_own=pair['own'],regime_peer=pair['peer'],fixed_target=order['target'] if chosen=='R' else None,
            planned_range_order=order if chosen=='R' else None)
        normal['decisions'].append(decision)
    return normal,diagnostic
