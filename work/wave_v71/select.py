"""前半だけで入口強化と幅拡大の比較代表を選び、後半と追加場で入れ替えない。"""

from pathlib import Path

import study

HERE = Path(__file__).resolve().parent


def enough(result: dict) -> bool:
    """機能: 前16の両銘柄で比較に必要な組数・活動場数があるか判断する。

    引数: result(dict)。返り値: 最低数の充足(bool)。
    """
    return all(result['periods']['前16'][s]['campaigns']>=20 and result['periods']['前16'][s]['active_sessions']>=8 for s in study.SYMBOLS)


def score(result: dict) -> float:
    """機能: 両銘柄の弱い方の前半1組平均呼値収支を採点する。

    引数: result(dict)。返り値: 最小の呼値平均(float)。
    """
    return min(result['periods']['前16'][s]['mean_net_ticks'] for s in study.SYMBOLS)


def main() -> None:
    """機能: 固定選定規則から代表と同じ入口部品の2×2対照を保存する。

    引数: なし。返り値: なし(None)。後半と追加場の収支を採点に使用しない。
    """
    results=[study.load(p) for p in sorted((HERE/'results').glob('*.json'))]
    assert len(results)==432
    candidates=[r for r in results if r['config']['method']=='H' and r['config']['gate_level'] in (1,2) and r['config']['width_id']!='W0']
    qualified=[r for r in candidates if enough(r)]
    samples=qualified or [r for r in candidates if all(r['periods']['前16'][s]['campaigns']>0 for s in study.SYMBOLS)]
    assert samples,'両銘柄とも入口がある比較条件がない'
    samples.sort(key=lambda r:(-score(r),r['config']['id']))
    best=samples[0];c=best['config'];source=c['source'];gate=c['gate_level'];width=c['width_id']
    eligible=enough(best) and all(best['periods']['前16'][s]['net']>0 and (best['periods']['前16'][s]['campaign_payoff'] or 0)>1 for s in study.SYMBOLS)
    methods=[dict(id=f'{source}_G{gate}_W0_H',label='入口だけ確認を増やす'),
             dict(id=f'{source}_G0_{width}_H',label='トレーリングだけ広げる'),
             dict(id=c['id'],label='入口確認と幅拡大を組み合わせる')]
    study.save(HERE/'前半選定.json',dict(比較代表=c['id'],代表=methods,基準=f'{source}_G0_W0_H',
        主選定条件数=len(candidates),最低数充足候補数=len(qualified),最低数充足=enough(best),採用条件充足=eligible,
        前半スコア=score(best),前半候補順位=[r['config']['id'] for r in samples],
        G3主選定除外=True,後半再選定=False,追加場再選定=False,
        説明='前半のみから共通比較例を選ぶ。最低数・黒字・損小利大が未達なら非採用例として表示する。'))
    print('前半の比較代表:',c['id'],'最低数:',enough(best),'採用条件:',eligible)


if __name__=='__main__':
    main()
