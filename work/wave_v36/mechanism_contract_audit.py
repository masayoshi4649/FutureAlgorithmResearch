"""記述的な全格子集計を別式で照合し、条件選抜と混同しない。"""

from pathlib import Path

import band_design as design
import band_independent_statistics as equality
import report_contract_audit as report


HERE, ROOT = report.HERE, report.ROOT


def basic(rows: list[dict], later: bool) -> dict:
    """機能: 保存セッションから固定基礎条件を別式で判定する。

    引数: rows (list[dict])、later (bool)。返り値: 基礎指標 (dict)。
    """
    value = report.aggregate(rows)
    largest = max([0.] + [gain for row in rows for gain in row['two_largest_cycle_profits']])
    best = max([0.] + [row['net_yen'] for row in rows])
    active = sum(row['cycles'] > 0 for row in rows)
    checks = dict(黒字=value['net_yen'] > 0,
        金額利益損失比1超=value['money_ratio'] is not None and value['money_ratio'] > 1,
        一枚平均利益損失比1超=value['average_unit_payoff'] is not None and value['average_unit_payoff'] > 1,
        必要稼働=active >= (4 if later else 7),
        最大勝ち組除外非負=value['net_yen'] - largest >= -1e-6,
        最大黒字場除外非負=value['net_yen'] - best >= -1e-6)
    return dict(合格=all(checks.values()), 検査=checks, 金額比=value['money_ratio'],
        一枚平均比=value['average_unit_payoff'], 稼働セッション数=active,
        最大勝ち組除外円=value['net_yen'] - largest, 最大黒字場除外円=value['net_yen'] - best)


def relation(a: dict, b: dict) -> dict:
    """機能: 全13・後7の両銘柄を、全セル非悪化と一箇所以上改善で分類する。

    引数: a/b (dict)。返り値: 4セル差と分類 (dict)。
    """
    rows = [dict(期間=period, 銘柄=symbol,
        収支差円=a[period][symbol]['net_yen'] - b[period][symbol]['net_yen'],
        最大下落差円=a[period][symbol]['drawdown_yen'] - b[period][symbol]['drawdown_yen'])
        for period in ('all_symbols', 'symbols') for symbol in ('TOPIX', 'NK225')]
    better = all(row['収支差円'] >= -1e-6 and row['最大下落差円'] <= 1e-6 for row in rows)
    worse = all(row['収支差円'] <= 1e-6 and row['最大下落差円'] >= -1e-6 for row in rows)
    changed = any(abs(row[field]) > 1e-6 for row in rows for field in ('収支差円', '最大下落差円'))
    label = '同値' if not changed else '同時改善' if better else '対照優位' if worse else '交換又は混在'
    return dict(関係=label, 同時改善=better and changed, 差=rows)


def main() -> None:
    """機能: 全90の基礎・時計、36の同仕様対照、返済台帳の異なり数を確認する。

    引数: なし。返り値: なし (None)。新規売買・採用変更を行わない。
    """
    paths = [HERE/'全格子の機序診断.json', HERE/'全条件の期間集計.json.gz',
        HERE/'探索条件の固定.json', HERE/'mechanism_diagnostics.py', HERE/'band_assessment.py',
        HERE/'band_design.py', HERE/'report_contract_audit.py', Path(__file__)]
    hashes = {path.relative_to(ROOT).as_posix(): report.digest(path) for path in paths}
    saved = report.read(paths[0]); values = report.read(paths[1]); fixed = report.read(paths[2])
    index = {row['id']: row for row in values}
    assert len(index) == len(values) == 364
    catalog = design.catalog()
    rows_by_id, aggregated = {}, {}
    for spec in design.conditions():
        path = HERE/'sessions'/(spec['id']+'.json.gz')
        hashes[path.relative_to(ROOT).as_posix()] = report.digest(path)
        rows = report.read(path)
        report.sessions_checked(rows, spec['id'], fixed['全セッション'])
        rows_by_id[spec['id']] = rows
        aggregated[spec['id']] = {period: {symbol: report.aggregate([row for row in rows
            if row['symbol'] == symbol and row['session'] in names]) for symbol in ('TOPIX', 'NK225')}
            for period, names in [('all_symbols', fixed['全セッション']), ('symbols', fixed['後半7セッション'])]}
    candidates = {row['id']: row for row in saved['全90条件']}
    assert len(candidates) == 90 and set(candidates) == {spec['id'] for spec in catalog}
    passed, robust = [], []
    for spec in catalog:
        row = candidates[spec['id']]
        assert row['params'] == spec['params']
        target = {period: {symbol: basic([item for item in rows_by_id[spec['id']+'__V000']
            if item['symbol'] == symbol and item['session'] in names], period == 'symbols')
            for symbol in ('TOPIX', 'NK225')} for period, names in
            [('all_symbols', fixed['全セッション']), ('symbols', fixed['後半7セッション'])]}
        clocks = {variant: {symbol: basic([item for item in rows_by_id[spec['id']+'__'+variant]
            if item['symbol'] == symbol and item['session'] in fixed['後半7セッション']], True)
            for symbol in ('TOPIX', 'NK225')} for variant in ('C080', 'C120')}
        equality.equal(row['基礎'], target); equality.equal(row['窓感度'], clocks)
        yes = all(value['合格'] for part in target.values() for value in part.values())
        clock_yes = all(value['合格'] for part in clocks.values() for value in part.values())
        assert row['基礎全通過'] == yes and row['窓基礎全通過'] == clock_yes
        if yes: passed.append(spec['id'])
        if yes and clock_yes: robust.append(spec['id'])
    pairs = {row['id']: row for row in saved['追加情報の全36対応']}
    assert len(pairs) == 36 and set(pairs) == {spec['id'] for spec in catalog if spec['params']['proxy'] == 'stable_volume'}
    counts = {proxy: {label: 0 for label in ('同値', '同時改善', '対照優位', '交換又は混在')}
        for proxy in ('price', 'all_volume')}
    for spec in catalog:
        if spec['id'] not in pairs: continue
        pair = pairs[spec['id']]
        assert pair['params'] == spec['params']
        for proxy in counts:
            params = dict(spec['params'], proxy=proxy,
                volume_threshold=0. if proxy == 'price' else spec['params']['volume_threshold'])
            other = [value for value in catalog if value['params'] == params]
            assert len(other) == 1
            identifier = other[0]['id']+'__V000'
            wanted = dict(id=identifier, **relation(aggregated[spec['id']+'__V000'], aggregated[identifier]))
            equality.equal(pair['対応比較'][proxy], wanted)
            counts[proxy][wanted['関係']] += 1
    assert saved['基礎全通過IDs'] == passed and saved['基礎と窓全通過IDs'] == robust
    assert saved['関係集計'] == counts
    assert saved['異なる台帳数'] == len({row['ledger_hash'] for row in values})
    assert saved['基本91の異なる台帳数'] == len({row['ledger_hash'] for row in values if row['spec']['variant_id'] == 'V000'})
    assert saved['主仮説変更'] is False and saved['採用判定への追加条件なし'] is True
    assert saved['期間集計SHA256'] == report.digest(paths[1]) and saved['実装SHA256'] == report.digest(paths[3])
    assert hashes == {path: report.digest(ROOT/path) for path in hashes}
    report.save(HERE/'mechanism_contract_audit.json', dict(全記述照合合格=True, 全基礎判定数=90*4,
        全時計判定数=90*4, 対応条件数=36, 対照組数=72, 基礎全通過IDs=passed,
        基礎と窓全通過IDs=robust, 関係集計=counts,
        改善定義='4セル全て非悪化かつ一箇所以上が厳密改善。全セル両指標の厳密改善ではない。',
        異なる台帳の定義='セッション銘柄キーと全返済明細tradesのhash。未約定準備や方向列の異なり数ではない。',
        主仮説変更=False, 新売買再生=False, API取得数=0, 参照SHA256=hashes))
    print(dict(全記述照合合格=True, 基礎全通過IDs=passed, 基礎と窓全通過IDs=robust, 関係集計=counts), flush=True)


if __name__ == '__main__':
    main()
