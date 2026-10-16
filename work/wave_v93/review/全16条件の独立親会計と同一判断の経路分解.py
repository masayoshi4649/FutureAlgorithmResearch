"""全992口座の親会計と16対照の因果差を、注文条件を変えず独立検算する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R


PAIRS = [('C00', 'C01'), ('C00', 'C02'), ('C01', 'C02'), ('C01', 'C03'), ('C01', 'C04'),
         ('C02', 'C05'), ('C05', 'C06'), ('C05', 'C07'), ('C06', 'C07'),
         ('C02', 'C08'), ('C02', 'C09'), ('C02', 'C10'), ('C06', 'C11'), ('C09', 'C11'),
         ('C00', 'C11'), ('C11', 'S02'), ('S00', 'S03'), ('S01', 'S03'), ('S02', 'S03')]


def partitions(sessions: list[str]) -> dict:
    """
    機能: 全31既知場を事前固定した8期間へ分ける。
    引数: sessions (list[str]) は固定順の場名。
    返り値: dict[str,list[str]] は期間別場名。
    """
    return {'全31': sessions, '前16': sessions[:16], '後15': sessions[16:], '旧30': sessions[:-1],
            '後14': sessions[16:-1], '追加1': sessions[-1:],
            'デイ': [s for s in sessions if s.endswith('_Day')],
            'ナイト': [s for s in sessions if s.endswith('_Night')]}


def period_source_checks(result: dict, ledgers: dict, fixed: dict) -> int:
    """
    機能: 全期間の商品別源・方向会計も独立親集計へ照合する。
    引数: result/ledgers/fixed (dict)。
    返り値: int は源又は方向の照合群数。
    """
    count = 0
    for label, subset in partitions(fixed['全31']).items():
        for symbol in R.SYMBOLS:
            trades = np.concatenate([ledgers[(s, symbol)]['trades'] for s in subset])
            metric = result['periods'][label][symbol]
            for source, name in [(0, 'J2'), (1, 'O06')]:
                R.equal(R.totals(trades[trades[:, 1] == source]), metric['sources'][name])
                count += 1
            for side, name in [(1, '買い'), (-1, '売り')]:
                R.equal(R.totals(trades[trades[:, 4] == side]), metric['directions'][name])
                count += 1
    return count


def compare(base: str, changed: str, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 同じ判断の管理・入口差と元固有及び新固有親を恒等分解する。
    引数: base/changed (str)、ledgers/fixed (dict)。
    返り値: dict は商品及び源ごとの全親差分。
    """
    output = {}
    for symbol in R.SYMBOLS:
        output[symbol] = {}
        for source, source_name in [(None, '全源'), (0, 'J2'), (1, 'O06')]:
            matched, old_only, new_only = [], [], []
            for session in fixed['全31']:
                a = R.parent_map(ledgers[base][session, symbol], source)
                b = R.parent_map(ledgers[changed][session, symbol], source)
                matched.extend((session, a[k], b[k]) for k in a.keys() & b.keys())
                old_only.extend((session, a[k]) for k in a.keys() - b.keys())
                new_only.extend((session, b[k]) for k in b.keys() - a.keys())
            management = sum(float(b[11] - a[11]) for _, a, b in matched)
            old_net, new_net = sum(float(t[11]) for _, t in old_only), sum(float(t[11]) for _, t in new_only)
            full_old = sum(float(t[11]) for s in fixed['全31'] for t in ledgers[base][s, symbol]['trades']
                           if source is None or int(t[1]) == source)
            full_new = sum(float(t[11]) for s in fixed['全31'] for t in ledgers[changed][s, symbol]['trades']
                           if source is None or int(t[1]) == source)
            assert abs(full_new - full_old - management - new_net + old_net) < 1e-4
            strict = [(s, a, b) for s, a, b in matched if np.array_equal(a[[2, 4, 5, 6, 8, 15]], b[[2, 4, 5, 6, 8, 15]])]
            cohorts = {}
            for _, a, b in matched:
                tag = ('利益' if a[11] > 0 else '損失' if a[11] < 0 else 'ゼロ') + '→' + \
                    ('利益' if b[11] > 0 else '損失' if b[11] < 0 else 'ゼロ')
                item = cohorts.setdefault(tag, {'親': 0, '元収支円': 0., '新収支円': 0., '差円': 0.})
                item['親'] += 1
                item['元収支円'] += float(a[11])
                item['新収支円'] += float(b[11])
                item['差円'] += float(b[11] - a[11])
            output[symbol][source_name] = {
                '元収支円': full_old, '新収支円': full_new, '全経路差円': full_new - full_old,
                '同一判断親': len(matched), '同一判断管理及び入口差円': management,
                '同一判断で取得数量価格も一致親': len(strict),
                '厳密同一新規管理差円': sum(float(b[11] - a[11]) for _, a, b in strict),
                '同判断だが取得又は数量が異なる親': len(matched) - len(strict),
                '同一判断符号変化': cohorts, '元固有親': len(old_only), '新固有親': len(new_only),
                '逃した元固有利益円': sum(max(float(t[11]), 0.) for _, t in old_only),
                '避けた元固有損失円': -sum(min(float(t[11]), 0.) for _, t in old_only),
                '新固有利益円': sum(max(float(t[11]), 0.) for _, t in new_only),
                '新固有損失円': -sum(min(float(t[11]), 0.) for _, t in new_only),
                '元固有収支円': old_net, '新固有収支円': new_net,
                '恒等検算': True,
            }
    return output


def selection(results: dict, fixed: dict) -> dict:
    """
    機能: 前16だけの参考選定を復元し、後成績で代表を変更していないか確認する。
    引数: results/fixed (dict)。
    返り値: dict は正式参考と固定採点の一致証拠。
    """
    formal = R.read(R.WORK / '前16参考代表.json')
    assert formal['固定SHA256'] == R.digest(R.WORK / '事前固定.json')
    assert formal['後15正式損益前選定'] and formal['全31既知']
    for relative, expected in formal['結果SHA256'].items():
        assert R.digest(R.ROOT / relative) == expected
    active, positive, good = [], [], []
    for ident, value in results.items():
        metrics = [value['periods']['前16'][s] for s in R.SYMBOLS]
        if all(v['campaigns'] >= 20 and v['active_sessions'] >= 8 for v in metrics):
            active.append(ident)
            if all(v['net'] > 0 for v in metrics):
                positive.append(ident)
                if all(v['payoff'] is not None and v['payoff'] > 1 for v in metrics):
                    good.append(ident)
    pool = good or positive or active or list(results)
    scores = {}
    for ident in pool:
        metrics = [results[ident]['periods']['前16'][s] for s in R.SYMBOLS]
        shares = [v['profit_share'] if v['profit_share'] is not None else -1 for v in metrics]
        rates = [v['positive_session_rate'] if v['positive_session_rate'] is not None else -1 for v in metrics]
        scores[ident] = (-min(shares), -min(rates), -sum(shares), ident)
    chosen = min(pool, key=lambda i: scores[i])
    assert chosen == formal['selected'] and set(pool) == set(formal['eligible'])
    assert formal['level'] == (0 if good else 1 if positive else 2 if active else 3)
    assert formal['primary'] == fixed['主']
    for ident in pool:
        assert list(scores[ident]) == formal['scores'][ident]
    return {'一致': True, 'selected': chosen, '主': fixed['主'], '足切り段階': formal['level'],
            '全31既知': True, '後成績で選び直し': False, '選定SHA256': R.digest(R.WORK / '前16参考代表.json')}


def main() -> None:
    """
    機能: 根の全正式完了通知後、全16条件の親会計と部品差分を保存する。
    引数: --根許可後 (bool) は必須の実行引数。
    返り値: None。売買再生・条件変更を行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    ledgers, checks, hashes = {}, {}, {}
    for config in fixed['条件']:
        ident = config['id']
        value = assembled['results'][ident]
        assert value['config'] == config
        ledgers[ident] = R.load_ledgers(ident)
        saved_rows = []
        for stage in ('front', 'back'):
            path = R.WORK / stage / 'results' / f'{ident}.json'
            result = R.read(path)
            assert result['config'] == config
            saved_rows.extend(result['rows'])
            hashes[str(path.relative_to(R.ROOT))] = R.digest(path)
            path = R.WORK / stage / 'ledgers' / f'{ident}.pkl'
            hashes[str(path.relative_to(R.ROOT))] = R.digest(path)
        assert saved_rows == value['rows']
        checks[ident] = R.BASE.check(value, ledgers[ident], fixed)
        checks[ident]['期間別源方向群'] = period_source_checks(value, ledgers[ident], fixed)
        print(f'{ident}: 全62口座と全8期間の親会計を独立照合', flush=True)
    differences = {f'{a}→{b}': compare(a, b, ledgers, fixed) for a, b in PAIRS}
    formal_reference = selection(assembled['results'], fixed)
    both80 = [i for i, value in assembled['results'].items() if all(
        (value['periods']['全31'][s]['profit_share'] or 0.) >= .8 for s in R.SYMBOLS)]
    R.save('全16条件全31の独立親会計と同一判断及び再参加経路分解.json', {
        '全合格': True, '条件数': 16, '場数': 31, '主': fixed['主'],
        '口座': sum(v['口座'] for v in checks.values()), '注文': sum(v['注文'] for v in checks.values()),
        '親': sum(v['親'] for v in checks.values()), '商品期間群': 16 * 8 * 2,
        '会計照合': checks, '部品差分': differences, '前16固定参考': formal_reference,
        '両商品金額80': both80, '全期間会計': {i: v['periods'] for i, v in assembled['results'].items()},
        '同一判断キー': ['session', 'symbol', 'source', 'decisionrow', 'side'],
        '注意': ['同一判断でも実約定行・価格・数量が異なれば純管理差ではない。厳密一致群を別に示す。',
                 '源親のG/Lを相殺しない。活動の無い場を勝ちに数えない。',
                 '全行時価及び潜在状態の全件独立復元は監査担当の証拠を参照する。'],
        '正式結果SHA256': hashes, '計算コードSHA256': R.digest(Path(__file__)), **R.provenance()})
    print('全16条件の独立親会計と部品経路の恒等分解を保存しました', flush=True)


if __name__ == '__main__':
    main()
