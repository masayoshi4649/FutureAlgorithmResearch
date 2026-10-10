"""全90方向判定の対応比較を記述し、主仮説の差替に使わない。"""

from __future__ import annotations

import band_runner as runner
import band_assessment as assessment


def main() -> None:
    """機能: 追加情報36組、基本90の作動・感度を全件記録する。

    引数: なし。返り値: なし (None)。結果後の取引条件変更・採用は行わない。
    """
    fixed = runner.prepare()
    values = runner.read(runner.HERE / '全条件の期間集計.json.gz')
    assert len(values) == 364 and len({r['id'] for r in values}) == 364
    index = {r['id']: r for r in values}
    catalog = runner.design.catalog()
    pairs, candidates = [], []
    for signal in catalog:
        identifier, params = signal['id'], signal['params']
        base = index[identifier + '__V000']
        rows = runner.read(runner.HERE / 'sessions' / (identifier + '__V000.json.gz'))
        basic = {}
        for period, names in (('all_symbols', fixed['全セッション']), ('symbols', fixed['後半7セッション'])):
            basic[period] = {symbol: assessment.basic(base[period][symbol],
                [r for r in rows if r['symbol'] == symbol and r['session'] in names], period == 'symbols')
                for symbol in runner.SYMBOLS}
        clocks = {}
        for variant in ('C080', 'C120'):
            changed = index[identifier + '__' + variant]
            sessions = runner.read(runner.HERE / 'sessions' / (changed['id'] + '.json.gz'))
            clocks[variant] = {symbol: assessment.basic(changed['symbols'][symbol],
                [r for r in sessions if r['symbol'] == symbol and r['session'] in fixed['後半7セッション']], True)
                for symbol in runner.SYMBOLS}
        candidates.append(dict(id=identifier, params=params, 基礎=basic, 窓感度=clocks,
            基礎全通過=all(r['合格'] for p in basic.values() for r in p.values()),
            窓基礎全通過=all(r['合格'] for p in clocks.values() for r in p.values()),
            指定波=base['wave_passes'], 追加方向対照='Q034だけ実施。他IDへ結果を流用しない。'))
        if params['proxy'] != 'stable_volume':
            continue
        controls = {}
        for proxy in ('price', 'all_volume'):
            expected = dict(params, proxy=proxy, volume_threshold=0. if proxy == 'price' else params['volume_threshold'])
            matches = [r for r in catalog if r['params'] == expected]
            assert len(matches) == 1
            counterpart = index[matches[0]['id'] + '__V000']
            controls[proxy] = dict(id=counterpart['id'], **assessment.relation(base, counterpart))
        pairs.append(dict(id=identifier, params=params, 対応比較=controls))
    assert len(pairs) == 36 and len(candidates) == 90
    summary = {}
    for proxy in ('price', 'all_volume'):
        summary[proxy] = {label: sum(r['対応比較'][proxy]['関係'] == label for r in pairs)
            for label in ('同値', '同時改善', '対照優位', '交換又は混在')}
    value = dict(全90条件=candidates, 追加情報の全36対応=pairs, 関係集計=summary,
        基礎全通過IDs=[r['id'] for r in candidates if r['基礎全通過']],
        基礎と窓全通過IDs=[r['id'] for r in candidates if r['基礎全通過'] and r['窓基礎全通過']],
        異なる台帳数=len({r['ledger_hash'] for r in values}), 総条件数=364,
        基本91の異なる台帳数=len({r['ledger_hash'] for r in values if r['spec']['variant_id'] == 'V000'}),
        主仮説変更=False, 採用判定への追加条件なし=True,
        解釈='全格子の記述。基礎を通る他IDも既知の探索候補に留め、Q034の方向対照や追加価値の検査を流用しない。',
        期間集計SHA256=runner.digest(runner.HERE / '全条件の期間集計.json.gz'), 実装SHA256=runner.digest(__import__('pathlib').Path(__file__)))
    runner.save(runner.HERE / '全格子の機序診断.json', value)
    print({k: value[k] for k in ('関係集計', '基礎全通過IDs', '基礎と窓全通過IDs', '異なる台帳数')}, flush=True)


if __name__ == '__main__':
    main()
