"""主格子全309を記述し、固定主案を結果後の最良へ差し替えない。"""

from __future__ import annotations

from collections import Counter
import partial_runner as runner
import partial_assessment as assessment


def main() -> None:
    """機能: 全格子の基礎、A0対応差、台帳重複と探索内順位を保存する。

    引数: なし。返り値: なし (None)。診断順位は採用ルールではない。
    """
    fixed = runner.prepare()
    all_items = runner.read(runner.HERE/'全条件の期間集計.json.gz')
    assert len(all_items) == 363
    items = [r for r in all_items if r['spec']['role'] == 'main']
    assert len(items) == 309
    reference = next(r for r in items if r['spec']['policy']['id'] == 'A0')
    rows = []
    for item in items:
        saved = runner.read(runner.HERE/'sessions'/(item['id']+'.json.gz'))
        checks = {}
        for period,names in (('all_symbols',fixed['全セッション']),('symbols',fixed['後半7セッション'])):
            for symbol in runner.SYMBOLS:
                checks[period+'/'+symbol] = assessment.basic(item[period][symbol],
                    [r for r in saved if r['symbol'] == symbol and r['session'] in names],names,True)
        relation = assessment.relation(item,reference)
        cells = [item[p][s] for p in ('all_symbols','symbols') for s in runner.SYMBOLS]
        row = dict(id=item['id'],policy=item['spec']['policy'],基礎=checks,
            基礎全通過=all(c['合格'] for c in checks.values()), A0比較=relation, 指定波=item['wave_passes'],
            全期間=item['all_symbols'],後半=item['symbols'],台帳SHA256=item['ledger_hash'],
            最小収支下落比=min(c['net_yen']/max(1.,c['drawdown_yen']) for c in cells))
        rows.append(row)
    dynamic = [r for r in rows if r['policy']['kind'] == 'dynamic']
    # ----------------------------------------
    # 探索内の参考順位。窓感度未実施の方式を主案へ代用しない。
    ranked = sorted(dynamic,key=lambda r:(not r['基礎全通過'],-r['最小収支下落比'],r['id']))
    output = dict(主仮説変更=False,事後記述=True,全主格子数=309,動的条件数=len(dynamic),
        基礎全通過IDs=[r['id'] for r in rows if r['基礎全通過']],
        A0同時改善IDs=[r['id'] for r in rows if r['A0比較']['同時改善']],
        基礎かつA0同時改善IDs=[r['id'] for r in rows if r['基礎全通過'] and r['A0比較']['同時改善']],
        A0関係=dict(Counter(r['A0比較']['関係'] for r in rows)),
        主309の異なる台帳数=len({r['台帳SHA256'] for r in rows}),
        診断含む363の異なる台帳数=len({r['ledger_hash'] for r in all_items}),
        参考順位定義='基礎4セル合格を先に、4セル最小の収支/最大下落が大きい順、最後にID。採用順位ではない。',
        参考上位5=ranked[:5],全格子=rows,
        注意='相関した既知期間での全数記述。上位方式は主案と同じ感度検証を受けていない。固定主案の差し替えには使わない。')
    runner.save(runner.HERE/'全格子の機序診断.json',output)
    print('全309格子を診断。A0同時改善='+str(len(output['A0同時改善IDs']))+'、基礎かつ改善='+str(len(output['基礎かつA0同時改善IDs'])),flush=True)


if __name__ == '__main__':
    main()
