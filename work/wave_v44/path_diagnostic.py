"""同じ影全組について、到達前の減量を避けた経路の損益差を分類する。"""

from __future__ import annotations

import runner

HERE = runner.HERE


def diagnose() -> dict:
    """機能: 未到達組も含め、主案と元C01の全組差を漏れなく分類する。

    引数: なし。返り値: 経路別集計(dict)。分類は追加採否に使用しない。
    """
    proof = runner.read(HERE/'完備監査.json')
    assert proof['全合格']
    runner.verify(proof['出力SHA256'])
    fixed = runner.read(HERE/'探索条件の固定.json')
    main, control, baseline = runner.design.PRIMARY, runner.design.CONTROL, runner.design.BASELINE
    ledgers = {identifier:{(r['session'],r['symbol']):r for r in
        runner.read(HERE/'ledgers'/(identifier+'.json.gz'))} for identifier in (main,control,baseline)}
    rows = []
    for key, record in ledgers[main].items():
        other, original = ledgers[control][key],ledgers[baseline][key]
        assert record['shadow_cycles']==other['shadow_cycles']==original['shadow_cycles']
        assert record['shadow_orders']==other['shadow_orders']==original['shadow_orders']
        arm = {e['campaign']:e['row'] for e in record['arm_events']}
        assert len(arm)==len(record['arm_events'])
        cycles = {identifier:{int(c[0]):c for c in ledgers[identifier][key]['cycles']}
                  for identifier in (main,control,baseline)}
        assert set(cycles[main])==set(cycles[control])==set(cycles[baseline])
        for campaign, value in cycles[main].items():
            prior,base = cycles[control][campaign],cycles[baseline][campaign]
            reductions = [o for o in other['orders'] if int(o[2])==campaign and o[6]==30]
            executed = [e for e in other['adjustment_events'] if int(e[1])==campaign and e[2]==2 and e[3]==-1]
            assert bool(reductions)==bool(executed)
            earliest_decision = min((int(o[1]) for o in reductions),default=None)
            assert earliest_decision==min((int(e[4]) for e in executed),default=None)
            assert all(0<=e[5]<=e[4]<e[0] for e in executed)
            earliest_source = min((int(e[5]) for e in executed),default=None)
            reached = campaign in arm
            category = ('未到達' if not reached else '到達前又は同じ公開で元C01が減量' if
                        earliest_source is not None and earliest_source<=arm[campaign] else '到達後に元C01が減量又は元C01減量なし')
            factor=record['config']['point_value']
            rows.append(dict(session=key[0],symbol=key[1],campaign=campaign,分類=category,
                到達行=arm.get(campaign),元C01最初減量根拠行=earliest_source,
                元C01最初減量判断行=earliest_decision,
                主案収支円=value[3]*factor,元C01収支円=prior[3]*factor,元A0収支円=base[3]*factor,
                元C01差円=(value[3]-prior[3])*factor,元A0差円=(value[3]-base[3])*factor,
                主案返済行=int(value[2]),到達前に主案返済=reached and value[2]<arm[campaign]))
    aggregates=[]
    for label,names in (('全13',fixed['全セッション']),('後7',fixed['後半7セッション'])):
        for symbol in runner.old.SYMBOLS:
            part=[r for r in rows if r['session'] in names and r['symbol']==symbol]
            grouped=[]
            for category in sorted({r['分類'] for r in part}):
                subset=[r for r in part if r['分類']==category]
                grouped.append(dict(分類=category,元組数=len(subset),改善数=sum(r['元C01差円']>0 for r in subset),
                    悪化数=sum(r['元C01差円']<0 for r in subset),同値数=sum(r['元C01差円']==0 for r in subset),
                    **{k:sum(r[k] for r in subset) for k in ('主案収支円','元C01収支円','元A0収支円','元C01差円','元A0差円')}))
            assert sum(r['元組数'] for r in grouped)==len(part)
            for identifier,field in ((main,'主案収支円'),(control,'元C01収支円'),(baseline,'元A0収支円')):
                summary=runner.read(HERE/'summaries'/(identifier+'.json'))
                expected=summary['all_symbols' if label=='全13' else 'symbols'][symbol]['net_yen']
                assert abs(sum(r[field] for r in grouped)-expected)<1e-6
            aggregates.append(dict(期間=label,銘柄=symbol,元組数=len(part),分類別=grouped))
    result=dict(全合格=True,全組数=len(rows),全元組=rows,期間別=aggregates,
        説明='同じ初回を持つ全組の経路分類。差には後続の復元・利確・予算返済の変化も含み、早い減量だけの因果効果ではない。影到達が実返済より後でも組を除かない。',
        追加採否=False,完備監査SHA256=runner.digest(HERE/'完備監査.json'),実装SHA256=runner.digest(HERE/'path_diagnostic.py'))
    runner.save(HERE/'減量時点別の全組差.json',result)
    return result


if __name__=='__main__':
    result=diagnose()
    print(f"同じ影{result['全組数']}組を未到達も含めて分類しました。",flush=True)
