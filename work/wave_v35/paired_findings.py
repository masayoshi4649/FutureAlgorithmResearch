"""同じ新規に対する退出差と、実際に異なる売買の数を整理する。"""

from statistics import median

import conditional_runner as runner

HERE = runner.HERE


def main() -> None:
    """機能: 凍結した全条件を比較し、採用規則を変えず結果後の会計分解を残す。

    引数: なし。返り値: なし (None)。新しい売買再生はしない。
    """
    summary = runner.read(HERE / '全条件の期間集計.json.gz')
    index = {r['id']: r for r in summary}
    selection = runner.read(HERE / '選択固定.json')['選択']
    selected = selection['selected_id']
    mode = selection['selected_exit_mode_id']
    primary = [r for r in summary if r['spec']['variant_id'] == 'V000']
    source = runner.read(HERE / 'sessions' / (selected + '.json.gz'))
    rows, conditions = [], []
    for period, sessions in (('初期6', runner.design.SESSIONS[:6]), ('後7', runner.design.SESSIONS[6:]), ('全13', runner.design.SESSIONS)):
        for symbol in runner.SYMBOLS:
            part = [r for r in source if r['symbol'] == symbol and r['session'] in sessions]
            pairs = [dict(p, session=r['session']) for r in part for p in r['exit_pairs']]
            differences = [p['difference_yen'] for p in pairs]
            counts = {'改善': sum(v > 1e-6 for v in differences), '悪化': sum(v < -1e-6 for v in differences),
                '同値': sum(abs(v) <= 1e-6 for v in differences)}
            assert sum(counts.values()) == len(pairs)
            improved = sum(v for v in differences if v > 0)
            worsened = sum(v for v in differences if v < 0)
            delta = sum(r['control']['exit_difference_yen'] for r in part)
            assert abs(improved + worsened - delta) <= 1e-6
            rows.append({'期間': period, '銘柄': symbol, '選択固定条件': selected, '全組数': len(pairs), **counts,
                '改善合計円': improved, '悪化合計円': worsened, '純差円': delta,
                '全組': sorted(pairs, key=lambda p: (p['difference_yen'], p['session'], p['campaign']))})
    for period in ('all_symbols', 'symbols'):
        for candidate_mode in runner.design.exit_modes():
            name = candidate_mode['id']
            for symbol in runner.SYMBOLS:
                deltas = [(index[f'{h}__{name}__V000'][period][symbol]['net_yen'] - index[f'{h}__A0__V000'][period][symbol]['net_yen'],
                    index[f'{h}__{name}__V000'][period][symbol]['drawdown_yen'] - index[f'{h}__A0__V000'][period][symbol]['drawdown_yen'])
                    for h in runner.design.SIGNAL_IDS]
                conditions.append({'期間': period, '方式': name, '銘柄': symbol,
                    '12入口収支差中央値円': median(v[0] for v in deltas),
                    '12入口DD差中央値円': median(v[1] for v in deltas),
                    '収支改善入口数': sum(v[0] > 1e-6 for v in deltas),
                    '収支悪化入口数': sum(v[0] < -1e-6 for v in deltas),
                    'DD改善入口数': sum(v[1] < -1e-6 for v in deltas),
                    'DD悪化入口数': sum(v[1] > 1e-6 for v in deltas)})
    value = {'目的': '結果後の会計分解。選択や採否へ使わない。', '選択': mode,
        '主条件数': len(primary), '主条件で異なる返済台帳数': len({r['ledger_hash'] for r in primary}),
        '全条件数': len(summary), '全条件で異なる返済台帳数': len({r['ledger_hash'] for r in summary}),
        '同じ新規の全組比較': rows, '全14方式の12入口対応': conditions,
        '探索固定SHA256': runner.digest(HERE / '探索条件の固定.json'),
        '選択固定SHA256': runner.digest(HERE / '選択固定.json'), '採否変更': False}
    supplement = runner.read(HERE / '補助乱数診断.json')
    risk_comparisons = []
    for period, part in supplement['集計'].items():
        for symbol, source in part.items():
            original = source['元条件']
            randoms = [r['成績'] for r in source['乱数全64']]
            risk_comparisons.append({'期間': period, '銘柄': symbol,
                '元最大下落円': original['drawdown_yen'],
                '乱数の最大下落が小さい本数': sum(r['drawdown_yen'] < original['drawdown_yen'] for r in randoms),
                '乱数の最大下落が同値の本数': sum(r['drawdown_yen'] == original['drawdown_yen'] for r in randoms),
                '元条件が収支DD同時優位の本数': sum(
                    original['net_yen'] >= r['net_yen'] and original['drawdown_yen'] <= r['drawdown_yen'] and
                    (original['net_yen'] > r['net_yen'] or original['drawdown_yen'] < r['drawdown_yen']) for r in randoms),
                '乱数が収支DD同時優位の本数': sum(
                    r['net_yen'] >= original['net_yen'] and r['drawdown_yen'] <= original['drawdown_yen'] and
                    (r['net_yen'] > original['net_yen'] or r['drawdown_yen'] < original['drawdown_yen']) for r in randoms)})
    value['乱数群の収支とリスク'] = risk_comparisons
    value['乱数比較の意味'] = '全13は選択固定条件の研究診断、後7は選択後期間。正式p値ではない。'
    inputs = runner.read(HERE / 'input_causality_before_pnl.json')['悪化']['rows']
    activity = []
    for condition in runner.design.condition_specs():
        name = condition['id']
        actual = index[f'H019__{name}__V000']['all_symbols']
        activity.append({'方式': name, '名称': condition['name'],
            '両銘柄全原本の非中立行数': sum(r['非中立行数'] for r in inputs if r['id'] == name),
            '銘柄別H019全13': {s: actual[s]['control'] for s in runner.SYMBOLS}})
    value['機序別作動量'] = activity
    runner.save(HERE / '同じ新規の退出差.json', value)
    print({k: value[k] for k in ('選択', '主条件数', '主条件で異なる返済台帳数', '全条件数', '全条件で異なる返済台帳数')})
    print([{k: r[k] for k in ('期間', '銘柄', '改善', '悪化', '同値', '純差円')} for r in rows])


if __name__ == '__main__':
    main()
