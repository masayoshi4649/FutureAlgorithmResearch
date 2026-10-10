"""前半だけの機構別選定と、後半・価格感度による再確認を保存する。"""

import json
from pathlib import Path

import study

HERE = Path(__file__).resolve().parent


def choose(packets: list[dict], family: int) -> dict:
    """機能: 事前の活動基準を満たす同機構の弱い銘柄の平均呼値利益で選ぶ。

    引数: packets(list[dict])、family(int)。返り値: 選定証跡(dict)。
    """
    group = [p for p in packets if p['config']['family']==family]
    candidates = [p for p in group if all(a['trades']>=20 and a['active_sessions']>=8 for a in p['periods']['前16'].values())]
    assert candidates,('事前活動基準に該当なし',family)
    candidates.sort(key=lambda p:(-min(a['mean_net_ticks'] for a in p['periods']['前16'].values()),p['config']['id']))
    best = candidates[0]
    eligible = all(a['net']>0 and a['payoff'] is not None and a['payoff']>1 for a in best['periods']['前16'].values())
    return dict(family=family,id=best['config']['id'],eligible=eligible,
        status='前半有望基準合格' if eligible else '比較用上位・有望判定未達',
        mean_worst_ticks=min(a['mean_net_ticks'] for a in best['periods']['前16'].values()),
        candidate_count=len(candidates),front_rank=[p['config']['id'] for p in candidates],
        later_used_for_selection=False)


def main() -> None:
    """機能: 全192条件を確認し、4機構の固定規則上位と単独黒字の活動量を記録する。

    引数: なし。返り値: なし(None)。
    """
    fixed = study.read(HERE/'事前固定.json')
    packets = [study.read(HERE/'results'/(c['id']+'.json')) for c in fixed['条件']]
    assert len(packets)==192 and all(len(p['rows'])==56 for p in packets)
    selected = [choose(packets,f) for f in (1,2,3,4)]
    simultaneous = [dict(id=p['config']['id'],accounts=p['periods']['全28']) for p in packets if all(a['net']>0 for a in p['periods']['全28'].values())]
    result = dict(選定=selected,全28同時黒字=simultaneous,
        黒字条件数={s:sum(p['periods']['全28'][s]['net']>0 for p in packets) for s in study.SYMBOLS},
        全192条件=True,後半選び直し=False,全28既知=True)
    study.save(HERE/'機構別の前半選定.json',result)
    for r in selected:
        p = next(p for p in packets if p['config']['id']==r['id'])
        print(r['id'],r['status'],[(s,round(p['periods']['全28'][s]['profit']),round(p['periods']['全28'][s]['loss']),round(p['periods']['全28'][s]['net']),p['periods']['全28'][s]['trades']) for s in study.SYMBOLS])
    print('両銘柄同時黒字:',[(r['id'],[(s,round(a['net']),a['trades'],a['active_sessions']) for s,a in r['accounts'].items()]) for r in simultaneous])


if __name__=='__main__':
    main()
