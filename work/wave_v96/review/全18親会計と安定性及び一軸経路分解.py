"""根の全31完了許可後だけ、全1116口座の会計・安定性・同一親経路を検算する。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R

OLD = R.OLD / '全53親会計と安定性及び一軸経路分解.py'
A = R.module('旧94独立会計関数を96へ接続', OLD)


def daily_change(first: dict, second: dict, sessions: list[str]) -> dict:
    """
    機能: 既存赤字の救済と無取引化、新赤字、新活動を場ごとに区別する。
    引数: first/second(dict)は期間別結果、sessions(list[str])は指定場。
    返り値: dictは商品別の遷移一覧。無取引を黒字へ数えない。
    """
    answer = {}
    for symbol in R.SYMBOLS:
        old = {row['session']: row for row in first['rows'] if row['symbol'] == symbol}
        new = {row['session']: row for row in second['rows'] if row['symbol'] == symbol}
        details = []
        for session in sessions:
            a, b = old[session], new[session]
            details.append(dict(場=session, 元親数=a['campaigns'], 新親数=b['campaigns'],
                元収支円=a['net'], 新収支円=b['net'], 差円=b['net'] - a['net'],
                既存赤字から黒字=a['net'] < 0 < b['net'],
                既存赤字から無取引=a['net'] < 0 and b['campaigns'] == 0,
                既存黒字から赤字=b['net'] < 0 < a['net'],
                無取引から新赤字=a['campaigns'] == 0 and b['net'] < 0,
                無取引から新黒字=a['campaigns'] == 0 and b['net'] > 0,
                既存赤字の損失額縮小=a['net'] < b['net'] < 0,
                既存赤字の損失額増加=b['net'] < a['net'] < 0))
        flags = ('既存赤字から黒字', '既存赤字から無取引', '既存黒字から赤字',
                 '無取引から新赤字', '無取引から新黒字', '既存赤字の損失額縮小', '既存赤字の損失額増加')
        answer[symbol] = dict(各場=details, 分類={name: [row['場'] for row in details if row[name]] for name in flags})
    return answer


def compare(first: str, second: str, ledgers: dict, fixed: dict, results: dict) -> dict:
    """
    機能: 同判断管理差・回避又は逸失・新固有親を恒等分解し、安定性の変化を添える。
    引数: first/second(str)、ledgers/fixed/results(dict)。
    返り値: dictは同一入口と経路変更を混同しない一軸差。
    """
    value = A.compare(first, second, ledgers, fixed)
    same_quantity = results[first]['config']['trend_budget'] == results[second]['config']['trend_budget']
    for symbol in R.SYMBOLS:
        value[symbol]['期間別安定性差'] = {}
        for period in R.partitions(fixed['全31']):
            a = results[first]['stability'][period][symbol]
            b = results[second]['stability'][period][symbol]
            fields = ('active_sessions', 'no_trade_sessions', 'losing_sessions', 'mean_losing_session_yen',
                      'worst_session_loss_yen', 'downside_rms_units', 'positive_session_rate',
                      'worst_intraday_drawdown_units')
            value[symbol]['期間別安定性差'][period] = {name: dict(元=a[name], 新=b[name],
                差=b[name] - a[name] if a[name] is not None and b[name] is not None else None) for name in fields}
    return dict(親会計恒等分解=value, 同数量=True if same_quantity else None,
        全31場別遷移=daily_change(results[first], results[second], fixed['全31']))


def main() -> None:
    """
    機能: 全18正式結果を独立検算し、評価・選定・経路原因の証跡を保存する。
    引数: --根許可後(bool)は必須。rootの全31正式完了通知後のみ実行する。
    返り値: None。正式売買や新候補の再生は行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    material = R.material()
    ledgers, checks, stable, fingerprints = {}, {}, {}, {}
    results = assembled['results']
    for config in fixed['条件']:
        ident = config['id']
        result = results[ident]
        ledgers[ident] = R.load_ledgers(ident)
        checks[ident] = R.BASE.check(result, ledgers[ident], fixed)
        stable[ident] = {}
        for period, sessions in R.partitions(fixed['全31']).items():
            for symbol in R.SYMBOLS:
                trades = np.concatenate([ledgers[ident][session, symbol]['trades'] for session in sessions])
                metric = result['periods'][period][symbol]
                for source, label in enumerate(('J2', 'O06')):
                    R.equal(R.totals(trades[trades[:, 1] == source]), metric['sources'][label])
                for side, label in ((1, '買い'), (-1, '売り')):
                    R.equal(R.totals(trades[trades[:, 4] == side]), metric['directions'][label])
            values = A.stability(result['rows'], config, material['prices'], sessions)
            A.verify_nested(values, result['stability'][period])
            stable[ident][period] = values
        for stage in ('front', 'back'):
            for folder, suffix in (('results', 'json'), ('ledgers', 'pkl')):
                path = R.WORK / stage / folder / f'{ident}.{suffix}'
                fingerprints[str(path.relative_to(R.ROOT))] = R.digest(path)
        ledgers[ident] = {key: {'trades': ledger['trades']} for key, ledger in ledgers[ident].items()}
        print(f'{ident}: 全62親会計・8期間安定性を独立照合', flush=True)
    pairs = [(reference, ident) for ident, references in assembled['comparison_pairs'].items() for reference in references]
    pairs += [(f'S{stop}_M1_{hold}',f'S{stop}_M2_{hold}') for stop in (10,20,40) for hold in ('H30','UNL')]
    pairs += [(f'S20_M{mode}_{hold}',f'S10_M{mode}_{hold}') for mode in (0,1,2) for hold in ('H30','UNL')]
    pairs = list(dict.fromkeys(pairs))
    differences = {f'{a}→{b}': compare(a, b, ledgers, fixed, results) for a, b in pairs}
    selected = A.selection(results, fixed, stable)
    both80 = [ident for ident, result in results.items() if all(
        result['periods']['全31'][symbol]['profit_share'] is not None
        and result['periods']['全31'][symbol]['profit_share'] >= .8 for symbol in R.SYMBOLS)]
    active80 = [ident for ident in both80 if all(results[ident]['periods']['全31'][symbol]['campaigns'] >= 20
        and results[ident]['periods']['全31'][symbol]['active_sessions'] >= 8 for symbol in R.SYMBOLS)]
    assert both80 == assembled['both80']
    assert active80 == assembled['活動充足の両80']
    R.save('全18条件全31の独立親会計と安定性及び一軸経路分解.json', dict(
        全合格=True, 条件数=18, 口座=18 * 62, 場数=31, 主=fixed['主'],
        注文=sum(row['注文'] for row in checks.values()), 親=sum(row['親'] for row in checks.values()),
        商品期間群=18 * 8 * 2, 会計照合=checks, 全清算時価重複再算定=False,
        独立安定性=stable, 一軸比較=differences, 前16固定参考=selected,
        両商品金額80=both80, 活動充足両80=active80,
        同一判断キー=['session', 'symbol', 'source', 'decisionrow', 'side'],
        注意=['厳密同一新規の出口管理差と、旧固有/新固有親による経路差を分ける。入口は全18で固定。',
            '無取引への変更を赤字救済と呼ばない。小数量による円損失縮小と入口改善は区別する。',
            '最大総益による事後選び直しはしない。全31は既知。'],
        正式結果SHA256=fingerprints, 計算コードSHA256=R.digest(Path(__file__)),
        旧再利用コードSHA256=R.digest(OLD), **R.provenance()))
    print('全18親会計・安定性・同一入口と固有経路を独立検算しました。', flush=True)


if __name__ == '__main__':
    main()
