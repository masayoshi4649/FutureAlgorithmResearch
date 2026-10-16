"""実cohortの全25列と親の物理会計を、原板時計及び実注文へ独立に戻す。"""

import math
import numpy as np

import compare_utils as checks
import math_oracle as money


def verify(value: dict, config: dict, output: dict, complete: bool = True) -> dict:
    """
    機能: cohortの源・時計・UID・固定R0と親初回/全量返済・観測超過を原板から再構成する。
    引数: value/config/output(dict)、complete(bool)は完了場か未完接頭か。
    返り値: dict。cohort全列と親の物理22列を検算。親active/finalstopの数理は別の代表管理oracle。
    """
    record = value['record']
    symbol = record['symbol']
    v,u = (1000,41.8) if symbol == 'TOPIX' else (10,11.)
    initial_q = money.quantity_for(config,symbol)
    tick = record['tick']
    width = max(2,math.ceil(value['reference_open']*config['trend_initial_stop_bp']/10000./tick-1e-10))*tick
    orders = np.asarray(output['orders'])
    cohorts = np.asarray(output['growth_cohorts'])
    ci = {name:i for i,name in enumerate(output['growth_cohort_columns'])}
    assert cohorts.shape[1] == 25
    expected = np.full(cohorts.shape,np.nan)
    parents = np.asarray(output['growth_parent_diagnostics'])
    pi = {name:i for i,name in enumerate(output['growth_parent_columns'])}
    assert parents.shape[1] == 24
    parent_checks = 0
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    for parent in sorted(set(cohorts[:,ci['parent_id']])):
        entries = orders[(orders[:,2] == parent) & (orders[:,7] == 1)]
        exits = orders[(orders[:,2] == parent) & (orders[:,7] == 0)]
        selected = np.flatnonzero(cohorts[:,ci['parent_id']] == parent)
        assert len(entries) == len(selected) > 0 and entries[0,5] == initial_q
        assert (np.diff(entries[:,0]) > 0).all() and len(exits) <= 1
        first = entries[0]
        items = [money.Cohort(i+1,int(order[5]),money.rational(order[6]),int(order[9]))
                 for i,order in enumerate(entries)]
        risk = money.fixed_risk(items[0],width,v,u)
        facts = money.completed_cohorts(items,exits[0,6],int(first[4]),v,u) if len(exits) else None
        final_quantity = sum(item.quantity for item in items)
        for ordinal,(position,order) in enumerate(zip(selected,entries),1):
            row,decision = int(order[0]),int(order[1])
            physical = dict(parent_id=parent,cohort_id=ordinal,source=order[3],side=order[4],quantity=order[5],
                decision_row=decision,decision_seq=record['seq'][decision],decision_time=order[10],
                entry_row=row,entry_seq=record['seq'][row],entry_time=record['time_s'][row],entry_price=order[6],
                entry_fee=order[9],order_uid=order[16],risk_budget=float(risk),initial_quantity=initial_q,
                entry_kind=0 if ordinal == 1 else 1)
            if facts is not None:
                last = exits[0]
                exit_row = int(last[0])
                gross = int(first[4])*items[ordinal-1].quantity*(money.rational(last[6])-items[ordinal-1].price)*v
                physical.update(exit_row=exit_row,exit_seq=record['seq'][exit_row],exit_time=record['time_s'][exit_row],
                    exit_price=last[6],exit_fee_share=facts['close_fees'][ordinal],gross=float(gross),
                    net=float(facts['nets'][ordinal]),parent_final_quantity=final_quantity)
            for name,wanted in physical.items():
                expected[position,ci[name]] = wanted
        if facts is None:
            assert not complete
            continue
        diagonal = parents[parents[:,pi['parent_id']] == parent]
        assert len(diagonal) == 1
        diagonal = diagonal[0]
        total = money.totals(items,v,u)
        first_row,last_row = int(first[0]),int(exits[0,0])
        rows = np.flatnonzero(qok[first_row:last_row])+first_row
        positions = np.searchsorted(entries[:,0],rows,side='right')-1
        quantities = np.cumsum(entries[:,5])[positions]
        cash = np.cumsum(entries[:,5]*entries[:,6]*v)[positions]
        entry_fees = np.cumsum(entries[:,9])[positions]
        quotes = record['bid'][rows] if first[4] == 1 else record['ask'][rows]
        nets = first[4]*(quantities*quotes*v-cash)-entry_fees-np.floor(quantities*u+1e-8)
        realized_excess = max(0.,-float(facts['parent_net'])-float(risk))
        observed_excess = max(realized_excess,float(np.maximum(-nets-float(risk),0.).max(initial=0.)))
        physical = dict(parent_id=parent,side=first[4],first_fill_row=first_row,
            first_fill_time=record['time_s'][first_row],first_fill_price=first[6],initial_quantity=initial_q,
            final_quantity=final_quantity,risk_budget=float(risk),entry_cash=float(total['E']),
            entry_fees=total['entry_fee'],exit_fee=exits[0,9],weighted_entry=float(total['weighted_entry']),
            exit_row=last_row,exit_seq=record['seq'][last_row],exit_time=record['time_s'][last_row],exit_price=exits[0,6],
            gross=float(facts['parent_net']+total['F']),net=float(facts['parent_net']),
            realized_budget_excess=realized_excess,maximum_observed_budget_excess=observed_excess,
            cohort_count=len(entries),deadline=record['time_s'][first_row]+config['trend_hold_seconds'] if config['trend_hold_seconds'] else 0.)
        for name,wanted in physical.items():
            if name in ('gross','net','maximum_observed_budget_excess'):
                checks.money(diagonal[pi[name]],wanted,'親の独立物理/'+name)
            else:
                checks.exact(diagonal[pi[name]],wanted,'親の独立物理/'+name)
        parent_checks += 1
    strict = [i for name,i in ci.items() if name not in ('gross','net')]
    checks.exact(cohorts[:,strict],expected[:,strict],'全cohortの原板源と時計・固定予算')
    checks.money(cohorts[:,[ci['gross'],ci['net']]],expected[:,[ci['gross'],ci['net']]],'全cohortの独立損益')
    assert len(parents) == parent_checks
    return dict(cohort全25列=len(cohorts),親物理22列=parent_checks)
