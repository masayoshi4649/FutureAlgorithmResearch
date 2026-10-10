"""選択後135近傍の区間合算と要約を独立検算する。"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import audit

OUT=Path(__file__).resolve().parent


def main() -> None:
    """機能: 追加診断の全区間合算・資格・要約と主候補の維持を確認する。

    引数: なし。返り値: なし (None)。追加再生や新しい選択は行わない。
    """
    records=audit.read('追加近傍診断.json')
    rows=audit.read('追加近傍セッション.json')
    summary=audit.read('追加近傍診断の要約.json')
    initial=audit.read('追加診断前の固定記録.json')
    selection=audit.read('選択結果.json')
    expected=set(itertools.product([.20,.25,.30],[.9,1.,1.1],[1.75,2.,2.25],[300.,330.,360.,390.,420.]))
    actual={(r['config']['entry_atr'],r['config']['stop_atr'],r['config']['main_trail'],r['config']['timeout_min']) for r in records}
    assert len(records)==len(actual)==135 and len(rows)==2700 and actual==expected
    additive=['gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units',
              'unit_balance','closed_units','cycles','cycle_wins','cycle_losses','net_r','order_count']
    qualified=[]
    for record in records:
        for symbol in audit.MULT:
            sample=sorted([r for r in rows if r['method_id']==record['id'] and r['symbol']==symbol],
                          key=lambda r:audit.SESSIONS.index(r['session']))
            assert len(sample)==10
            week=record['weeks'][symbol]
            derived={k:sum(r[k] for r in sample) for k in additive}
            p,l,w,d=[derived[k] for k in ['gross_profit_yen','gross_loss_yen','profit_units','loss_units']]
            best=max(sample,key=lambda r:r['net_yen'])
            kept=[r for r in sample if r['session']!=best['session']]
            derived.update(money_ratio=audit.ratio(p,l),unit_payoff=audit.ratio(p/w,l/d) if w and d else None,
                           positive_sessions=sum(r['net_yen']>0 for r in sample),active_sessions=sum(r['cycles']>0 for r in sample),
                           first_half_net=sum(r['net_yen'] for r in sample[:5]),second_half_net=sum(r['net_yen'] for r in sample[5:]),
                           day_net=sum(r['net_yen'] for r in sample if r['session'].endswith('Day')),
                           night_net=sum(r['net_yen'] for r in sample if r['session'].endswith('Night')),
                           best_session=best['session'],drop_best_session_net=sum(r['net_yen'] for r in kept),
                           drop_best_session_pf=audit.ratio(sum(r['gross_profit_yen'] for r in kept),sum(r['gross_loss_yen'] for r in kept)))
            audit.check(week,derived,f'追加近傍:{record["id"]}:{symbol}')
            audit.eq(week['drop_best_trade_net'],week['net_yen']-week['best_trade_yen'],'最大取引除外の算術')
        qualification=dict(both_positive=all(record['weeks'][s]['net_yen']>0 for s in audit.MULT),
                           both_drop_positive=all(record['weeks'][s]['drop_best_session_net']>0 for s in audit.MULT),
                           both_eligible=all(audit.eligible(record['weeks'][s]) for s in audit.MULT))
        audit.check(record,qualification,'追加近傍資格')
        qualified.append(qualification)
    totals={k:sum(q[k] for q in qualified) for k in ['both_positive','both_drop_positive','both_eligible']}
    audit.check(summary,dict(count=135,**totals),'追加近傍の要約')
    for symbol in audit.MULT:
        audit.eq(summary['minimum_net'][symbol],min(r['weeks'][symbol]['net_yen'] for r in records),'最低週収支')
        audit.eq(summary['minimum_drop_net'][symbol],min(r['weeks'][symbol]['drop_best_session_net'] for r in records),'最低除外収支')
    only=[r for r in records if r['config']['entry_atr']==.25 and r['config']['stop_atr']==1 and r['config']['main_trail']==2]
    assert [r['id'] for r in only]==summary['holding_only'] and len(only)==5
    assert all(r['both_positive'] and r['both_drop_positive'] for r in only)
    assert summary['primary']==initial['主候補']==selection['primary']=='V0800'
    result=dict(合格=True,追加条件数=len(records),区間合算数=len(rows),照合数=audit.CHECKS,
                全週黒字条件数=totals['both_positive'],最大勝ち区間除外黒字条件数=totals['both_drop_positive'],
                全資格合格条件数=totals['both_eligible'],保有時間だけ変更した5条件は両銘柄で週と除外後黒字=True,
                主候補変更なし=True,範囲='追加診断の区間集計から週合計・資格・要約を照合。追加診断の原取引台帳は未保存のため再構成対象外。',
                現在API取得数=0)
    (OUT/'audit_diagnostics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
