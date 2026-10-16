"""全18台帳会計と少数代表の独立出口を、人工と正式共通の保存終端で検算する。"""

import argparse
import hashlib
from pathlib import Path

import numpy as np

import common
import independent

common.module('protocol', common.ROOT / 'work/wave_v95/audit/protocol.py')
MATH = common.module('旧94の純会計のみ読取96', common.ROOT / 'work/wave_v94/audit/full.py')
REPLAY_IDS = ('S10_M1_UNL', 'S40_M0_H30', 'S10_M2_UNL')


def array_sha(value: np.ndarray) -> str:
    """
    機能: 保存台帳の全原板配列指紋を独立再計算する。
    引数: value(ndarray)は再構成値。
    返り値: str。原バイトのSHA256。
    """
    return hashlib.sha256(value.tobytes()).hexdigest()


def verify_account(key: tuple[str, str], value: dict, config: dict, ledger: dict,
                   replay_exit: bool) -> tuple[dict, dict]:
    """
    機能: 全実注文から次BBO、料金、親、全原板時価、枚数を独立計算する。
    引数: key(tuple[str,str])、value/config/ledger(dict)、replay_exit(bool)は独立売買再生の有無。
    返り値: tuple[dict,dict]。独立場会計と実照合件数。
    """
    record, signal = value['record'], value['signal']
    n = len(record['time_s'])
    quantity, unit, fee_unit, cap = (8, 1000., 41.8, 10) if key[1] == 'TOPIX' else (16, 10., 11., 20)
    orders = np.asarray(ledger['orders'], float).reshape(-1, 17)
    trades = np.asarray(ledger['trades'], float).reshape(-1, 16)
    events = np.asarray(ledger['events'], float).reshape(-1, 12)
    assert np.isfinite(orders).all() and np.isfinite(trades).all()
    assert len(orders) == 2 * len(trades) and ledger['input_rows'] == n
    assert (np.diff(orders[:, 0]) >= 0).all() and not np.any(np.asarray(ledger['slots'])[:, 0])
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    good = np.flatnonzero(qok)
    fee = int(np.floor(quantity * fee_unit + 1e-8))
    opened, rebuilt = {}, []
    for order in orders:
        row, decision, parent, source, action, qty = map(int, order[:6])
        price, new, reason, paid, dclock, fillclock = order[6:12]
        assert 0 <= decision < row < n and source == 0 and qty == quantity <= cap and action in (-1, 1)
        assert row == good[np.searchsorted(good, decision, side='right')], ('次の正常BBOでない', key, parent)
        assert price == (record['ask'][row] if action == 1 else record['bid'][row]) and paid == fee
        assert fillclock == record['time_s'][row] and order[14] == 0
        if reason == 4 and dclock == record['limit'] - 60.:
            assert record['time_s'][decision] < dclock <= fillclock
        else:
            assert dclock == record['time_s'][decision]
        if new:
            assert parent not in opened and action == int(order[15]) and reason == 10
            assert record['start'] + 300. <= dclock < record['limit'] - 300.
            assert fillclock < record['limit'] - 300. and signal['event'][decision] == action
            assert signal['quality'][decision] and not signal['reset'][decision] and qok[decision]
            opened[parent] = order
        else:
            entry = opened.pop(parent)
            assert action == -int(entry[4]) and order[15] == entry[4]
            assert qty == entry[5] and order[13] == entry[13] and reason in (1, 2, 3, 4)
            gross = entry[4] * (price - entry[6]) * qty * unit
            rebuilt.append([parent, 0, entry[0], row, entry[4], qty, entry[6], price,
                            entry[9], paid, gross, gross - entry[9] - paid, entry[8], reason,
                            entry[13], entry[1]])
    assert not opened
    common.exact(trades, np.asarray(rebuilt, float).reshape(-1, 16), '全実決済親')
    # ----------------------------------------
    # 全原板時価は既存の独立vector式だけを再利用し、旧account/management/mainは呼ばない。
    curve, source_curve, positions, cash = MATH.curves(record, orders)
    trace = MATH.expand(np.asarray(ledger['trace_changes']), n)
    assert array_sha(curve) == ledger['curve_SHA256']
    assert array_sha(source_curve) == ledger['source_curve_SHA256']
    assert array_sha(trace) == ledger['target_trace_SHA256']
    common.exact(trace[:, 0], np.maximum(positions, 0).sum(axis=1))
    common.exact(trace[:, 1], np.maximum(-positions, 0).sum(axis=1))
    assert (trace >= 0).all() and trace[:, 2:4].max(initial=0) <= cap
    assert not trace[-1].any() and not positions[-1].any()
    common.money(curve[-1], trades[:, 11].sum(), '親netと全玉終端')
    assert len(ledger['trend_parent_diagnostics']) == len(trades)
    diag = np.asarray(ledger['trend_parent_diagnostics'], float).reshape(-1, 27)
    common.exact(diag[:, :6], trades[:, [0, 2, 3, 4, 5, 6]], '親診断の実fill対応')
    common.exact(diag[:, 23:26], trades[:, [13, 7, 11]], '親診断の実返済とnet')
    initial, trail, protected = independent.widths(record, config, value['reference_open'])
    common.exact(diag[:, 6], np.full(len(diag), initial), '初期幅')
    common.exact(diag[:, 7], np.full(len(diag), trail), '追尾幅')
    common.exact(diag[:, 8], np.full(len(diag), 2 * initial), '始動幅')
    common.exact(diag[:, 9], trades[:, 6] - trades[:, 4] * initial, '初期線')
    common.exact(diag[:, 10], trades[:, 6] + trades[:, 4] * protected, '費用床')
    dense = MATH.expand(np.asarray(ledger['trend_exit_state_changes']), n)
    assert dense.shape == (n, 23) and array_sha(dense) == ledger['trend_exit_state_SHA256']
    if replay_exit:
        actual = dict(orders=orders, trades=trades, curve=curve, target_trace=trace,
                      trend_exit_state_trace=dense, trend_parent_diagnostics=diag)
        independent.compare(record, signal, config, value['reference_open'], actual)
    row = dict(session=key[0], symbol=key[1], **MATH.totals(trades), **MATH.path(curve))
    row['sources'] = {name: dict(**MATH.totals(trades[trades[:, 1] == source]), **MATH.path(source_curve[:, source]))
                      for source, name in enumerate(('J2', 'O06'))}
    row['directions'] = {name: MATH.totals(trades[trades[:, 4] == side]) for name, side in (('買い', 1), ('売り', -1))}
    row['maximums'] = {name: int(trace[:, i].max(initial=0)) for i, name in enumerate(ledger['trace_columns'])}
    instant = MATH.maxima(events)
    for i, name in enumerate(ledger['trace_columns'][:4]):
        row['maximums'][name] = int(instant[i])
    row['event_counts'] = {str(int(code)): int((events[:, 3] == code).sum()) for code in np.unique(events[:, 3])}
    stats = np.asarray(ledger['stats'])
    common.exact(stats[:4], instant[:4])
    common.exact(stats[8], instant[4])
    common.exact(stats[4:8], trace[-1, [0, 1, 4, 5]])
    common.exact(stats[9:15], [int(((events[:, 3] == 6) & (events[:, 2] == 1)).sum()),
                             int((events[:, 3] == 7).sum()), int(((events[:, 3] == 9) & (events[:, 2] == 0)).sum()),
                             int(((events[:, 3] == 9) & (events[:, 2] == 1)).sum()),
                             int(((events[:, 3] == 1) & (events[:, 2] == 0)).sum()),
                             int(((events[:, 3] == 1) & (events[:, 2] == 1)).sum())])
    common.money(stats[15], float(cash[-1].sum()))
    row['stats'] = {name: float(stats[i]) for i, name in enumerate(ledger['stat_columns'])}
    return row, dict(口座=1, 注文=len(orders), 決済親=len(trades), 全原板会計=n,
                     独立最初出口と23状態及び27親=1 if replay_exit else 0)


def main() -> None:
    """
    機能: 人工と正式で同じ検算関数を使い、全会計比較と終端保存まで実行する。
    引数: CLI --artificial又は--formal。正式は凍結後に根が明示許可した場合だけ。
    返り値: None。不一致は例外。実P/Lの新規生成、現在API、実注文を行わない。
    """
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--artificial', action='store_true')
    group.add_argument('--formal', action='store_true')
    args = parser.parse_args()
    catalog = common.module('96正式独立条件', common.BASE / 'catalog.py')
    conditions = catalog.catalog()
    code_paths = [common.HERE / name for name in ('common.py', 'independent.py', 'full.py')]
    code_paths += [common.BASE / name for name in ('catalog.py', 'research.py', 'accounting.py', 'engine.py', 'strategy.py')]
    code_paths += [common.ROOT / 'work/wave_v94/audit/full.py', common.ROOT / 'work/wave_v95/audit/protocol.py']
    fingerprints = common.fingerprint(code_paths)
    counts, all_rows = {}, {}
    if args.artificial:
        import artificial
        engine = common.module('96独立人工本体', common.BASE / 'engine.py')
        research = common.module('96CLI根保存', common.BASE / 'research.py')
        accounts = common.module('96CLI根会計', common.BASE / 'accounting.py')
        for config in conditions:
            rows = []
            saved_ledgers = {}
            for symbol in catalog.SYMBOLS:
                record, signal, reference = artificial.fixture(symbol, 1, '費用床と次気配gap', config)
                record['session'] = '2099-01-01_Day'
                key = record['session'], symbol
                value = dict(record=record, signal=signal, reference_open=reference)
                output = engine.execute(record, signal, config)
                saved_ledgers[key] = research.ledger(output)
                row, checked = verify_account(key, value, config, saved_ledgers[key], True)
                common.same(row, accounts.account(key, output), '人工根会計')
                rows.append(row)
                for name, amount in checked.items():
                    counts[name] = counts.get(name, 0) + amount
            path = common.HERE / 'cli_fixture' / (config['id'] + '.pkl')
            research.save(path, saved_ledgers)
            loaded = common.read(path)
            for key in loaded:
                common.exact(loaded[key]['orders'], saved_ledgers[key]['orders'])
            all_rows[config['id']] = rows
            fingerprints.update(common.fingerprint([path]))
        destination = common.HERE / '人工1場36口座の独立本番CLIと根台帳及び会計の保存終端.json'
        assert counts['口座'] == 36
    else:
        fixed_path = common.BASE / '事前固定.json'
        fixed = common.read(fixed_path)
        assert fixed['条件'] == conditions and fixed['全31既知'] and fixed['新未見確認場数'] == 0
        for relative, expected in fixed['SHA256'].items():
            assert common.sha(common.ROOT / relative) == expected, relative
        data = common.module('96正式独立入力', common.BASE / 'data.py')
        strategy = common.module('96正式独立準備', common.BASE / 'strategy.py')
        material = data.load_inputs()
        prepared = strategy.prepare(material, conditions[0])
        analysis_path = common.BASE / 'analysis/比較結果.json'
        analysis = common.read(analysis_path)
        periods = {key: fixed[key] for key in ('全31', '前16', '後15', '旧30', '後14', '追加1')}
        periods.update(デイ=[key for key in fixed['全31'] if key.endswith('_Day')],
                       ナイト=[key for key in fixed['全31'] if key.endswith('_Night')])
        for config in conditions:
            rows, ledgers, part_results = [], {}, {}
            for part in ('front', 'back'):
                result_path = common.BASE / part / 'results' / (config['id'] + '.json')
                ledger_path = common.BASE / part / 'ledgers' / (config['id'] + '.pkl')
                result = common.read(result_path)
                assert result['config'] == config and common.sha(ledger_path) == result['ledger_SHA256']
                part_results[part] = result
                ledgers.update(common.read(ledger_path))
                fingerprints.update(common.fingerprint([result_path, ledger_path]))
            assert set(ledgers) == set(prepared)
            for key in sorted(ledgers):
                row, checked = verify_account(key, prepared[key], config, ledgers[key], config['id'] in REPLAY_IDS)
                rows.append(row)
                for name, amount in checked.items():
                    counts[name] = counts.get(name, 0) + amount
            for part, period in (('front', '前16'), ('back', '後15')):
                common.same([row for row in rows if row['session'] in fixed[period]], part_results[part]['rows'], config['id'] + '/' + period)
            result = dict(config=config, rows=rows,
                periods={name: {symbol: MATH.aggregate(rows, symbol, sessions) for symbol in catalog.SYMBOLS}
                         for name, sessions in periods.items()},
                stability={name: MATH.stability(rows, config, material['prices'], sessions) for name, sessions in periods.items()})
            common.same(result, analysis['results'][config['id']], config['id'] + '/全8期間')
            all_rows[config['id']] = result
            print(config['id'] + ': 全台帳と全原板会計及び代表出口が一致', flush=True)
        assert counts['口座'] == 1116 and counts['独立最初出口と23状態及び27親'] == 186
        counts['商品期間'] = len(conditions) * len(periods) * 2
        assert counts['商品期間'] == 288
        for relative, expected in fixed['SHA256'].items():
            assert common.sha(common.ROOT / relative) == expected, relative
        fingerprints.update(common.fingerprint([fixed_path, analysis_path]))
        destination = common.HERE / '全18全31の全台帳会計と3代表の独立出口及び全原板の検算.json'
    for relative, expected in common.fingerprint(code_paths).items():
        assert fingerprints[relative] == expected, relative
    common.save(destination, dict(合格=True, 人工専用=args.artificial, 検査件数=counts,
        全会計=all_rows, 独立売買再生の範囲='人工全18。本番は主/旧対照/S10_M2_UNLの3代表で62口座ずつ。',
        全台帳の範囲='全18の全決済親、料金、次BBO、全原板時価、全31会計。その他15のfirsttrigger全経路は独立再生していない。',
        全31既知=True, 未見場数=0, 新正式売買生成=0, API取得=0, 実注文=0, SHA256=fingerprints))
    print('独立CLIの全比較及び終端保存/再読込: 合格', flush=True)


if __name__ == '__main__':
    main()
