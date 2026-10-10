"""前半だけで、物理保険・同判断対照・その他管理を選定する。"""

from pathlib import Path

import study

HERE = Path(__file__).resolve().parent


def scores(result: dict, baseline: dict) -> tuple:
    """機能: 同入口基準からの改善幅を呼値・一組で正規化する。

    引数: result/baseline(dict)。返り値: 弱い銘柄の改善、両銘柄平均改善、条件ID(tuple)。
    """
    deltas = []
    for symbol in study.SYMBOLS:
        a,b = result['periods']['前16'][symbol],baseline['periods']['前16'][symbol]
        assert a['campaigns']==b['campaigns']
        assert a['campaigns']>=20 and a['active_sessions']>=8
        deltas.append(a['mean_net_ticks']-b['mean_net_ticks'])
    return min(deltas),sum(deltas)/2,result['config']['id']


def main() -> None:
    """機能: 事前規則で三代表を固定し、採用条件の達成状態を記録する。

    引数: なし。返り値: なし(None)。
    """
    results = [study.load(p) for p in sorted((HERE/'results').glob('*.json'))]
    assert len(results)==192
    byid = {r['config']['id']:r for r in results}
    candidates = []
    for r in results:
        if r['config']['manager']=='B00':
            continue
        if not all(r['periods']['前16'][s]['campaigns']>=20 and r['periods']['前16'][s]['active_sessions']>=8 for s in study.SYMBOLS):
            continue
        baseline = byid[r['config']['source']+'_B00']
        candidates.append((r,scores(r,baseline)))
    hedges = sorted([(r,s) for r,s in candidates if r['config']['group']=='保険両建て'],key=lambda v:v[1],reverse=True)
    others = sorted([(r,s) for r,s in candidates if r['config']['group'] not in ('保険両建て','縮小復帰')],key=lambda v:v[1],reverse=True)
    assert hedges and others
    hedge = hedges[0][0]
    paired = byid[hedge['config']['source']+'_N'+hedge['config']['manager'][1:]]
    chosen = [hedge,paired,others[0][0]]
    selected = []
    for r in chosen:
        b = byid[r['config']['source']+'_B00']
        a = r['periods']['前16']
        eligible = all(a[s]['net']>0 and a[s]['campaign_payoff'] is not None and a[s]['campaign_payoff']>1 for s in study.SYMBOLS)
        selected.append(dict(id=r['config']['id'],baseline=b['config']['id'],eligible=eligible,
                             front_worst_delta=scores(r,b)[0],status='有望条件達成' if eligible else '改善比較・有望条件未達'))
    study.save(HERE/'前半選定.json',dict(代表=selected,物理保険順位=[r['config']['id'] for r,_ in hedges],
                                      その他管理順位=[r['config']['id'] for r,_ in others],後半選び直し=False,
                                      両銘柄全28黒字=[r['config']['id'] for r in results if all(r['periods']['全28'][s]['net']>0 for s in study.SYMBOLS)]))
    for selected in selected:
        r,b = byid[selected['id']],byid[selected['baseline']]
        print(selected)
        for symbol in study.SYMBOLS:
            a=r['periods']['全28'][symbol];base=b['periods']['全28'][symbol]
            print(symbol,'基準',base['net'],'改修',a['net'],'負組損失',base['campaign_loss'],a['campaign_loss'],
                  '勝組利益',base['campaign_profit'],a['campaign_profit'],'DD',base['drawdown'],a['drawdown'],'平均勝負比',a['campaign_payoff'])


if __name__=='__main__':
    main()
