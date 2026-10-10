"""全見送り方式の結果と入口根拠を別式で確認する。"""

from __future__ import annotations

import argparse
import pickle

import numpy as np

from diagnosis_check import model
from independent_audit import ROOT, SOURCES, account, read, same, save, sha


GATES = ROOT / 'work/wave_v49/gates'
NEW = '2026-09-30_Night'


def snapshot(models: dict, key: tuple, stamp: float, delay: int) -> dict:
    """機能: 公開済み足だけの独立指標を取り出す。

    引数: models (dict)、key (tuple)、stamp (float)、delay (int)。
    返り値: 当時の数値 (dict)。将来の足へ補間しない。
    """
    m = models[key]
    index = np.searchsorted(m['time_s'] + delay, stamp, side='right') - 1
    if index < 0:
        return {name: np.nan for name in ('gap', 'slope', 'fast_slope', 'r5', 'r15', 'r30')}
    assert m['time_s'][index] + delay <= stamp
    result = {name: m[name][index] for name in ('gap', 'slope', 'fast_slope')}
    for window in (5, 15, 30):
        previous = np.searchsorted(m['time_s'], m['time_s'][index] - 60 * window, side='right') - 1
        result['r' + str(window)] = ((m['close'][index] - m['close'][previous]) / m['atr'][index]
                                    if previous >= 0 else np.nan)
    return result


def permits(spec: dict, side: int, own: dict, peer: dict) -> bool:
    """機能: 説明された見送り条件を独立に評価する。

    引数: spec (dict)、side (int)、own/peer (dict)。返り値: 許可 (bool)。
    """
    code = spec['id']
    if code == 'G00':
        return True
    number = int(code[1:])
    if number <= 9:
        key = 'r' + str(spec['window'])
        values = (own[key], peer[key])
        if not all(np.isfinite(value) for value in values):
            return False
        if number <= 3:
            return not (min(values) < 0 < max(values))
        if number <= 6:
            return min(value * side for value in values) >= 0
        return min(value * side for value in values) > spec['threshold']
    if code == 'G10':
        return all(m['gap'] * side > .15 and m['slope'] * side > .02 for m in (own, peer))
    key = 'slope' if code == 'G11' else 'fast_slope'
    values = (own[key] * side, peer[key] * side)
    return all(np.isfinite(value) and (value >= 0 if code == 'G11' else value > 0) for value in values)


def period_check(summary: dict, rows: list) -> None:
    """機能: 旧期間と追加場の主要数値を別式で確認する。

    引数: summary (dict)、rows (list)。返り値: なし (None)。
    """
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles')
    for period, symbols in summary['periods'].items():
        for symbol, expected in symbols.items():
            chosen = sorted((row for row in rows if row['symbol'] == symbol and
                             (period == '全16' or (row['session'] == NEW) == (period == '問題Night'))),
                            key=lambda row: row['session'])
            for field in fields:
                same(sum(row[field] for row in chosen), expected[field], '期間/' + field)
            assert sum(row['net_yen'] > 0 for row in chosen) == expected['win_sessions']
            assert sum(row['initial_entries'] > 0 for row in chosen) == expected['active_sessions']
            assert sum(row['initial_entries'] for row in chosen) == expected['initial_entries']
            net = peak = worst = 0.
            for row in chosen:
                worst = max(worst, row['drawdown_yen'], peak - (net + row['min_equity_yen']))
                peak = max(peak, net + row['max_equity_yen'])
                net += row['net_yen']
            same(worst, expected['drawdown_yen'], '連結時価下落')
            profit = sum(row['gross_profit_yen'] for row in chosen)
            loss = sum(row['gross_loss_yen'] for row in chosen)
            win_units = sum(row['profit_units'] for row in chosen)
            lose_units = sum(row['loss_units'] for row in chosen)
            if win_units and lose_units and loss:
                same((profit / win_units) / (loss / lose_units), expected['average_unit_payoff'], '一枚当たり勝敗金額比')


def check(expected_count: int | None) -> dict:
    """機能: 完了済み条件の全会計・初回許可・旧同一性を確認する。

    引数: expected_count (int|None) は要求する完了方式数。
    返り値: 検査件数・指紋・問題場と旧期間の比較 (dict)。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v47/inputs.pkl').read_bytes())
    for folder in SOURCES[2:]:
        inputs.update(pickle.loads((folder / 'new_inputs.pkl').read_bytes()))
    assert len(inputs) == 32 and all(np.isfinite(r['last']).all() for r in inputs.values())
    models = {key: model(ready) for key, ready in inputs.items()}
    paths = sorted((GATES / 'summaries').glob('*.json'))
    if expected_count is not None:
        assert len(paths) == expected_count, len(paths)
    results, fingerprints, baselines = [], {}, {}
    preparations = openings = accounts = 0
    for path in paths:
        summary = read(path)
        identifier = summary['id']
        rows = read(GATES / 'sessions' / (identifier + '.json.gz'))
        ledgers = read(GATES / 'ledgers' / (identifier + '.json.gz'))
        assert len(rows) == len(ledgers) == 32
        keyed = {(row['session'], row['symbol']): row for row in rows}
        if summary['gate']['id'] == 'G00':
            old = []
            for folder in SOURCES:
                old.extend(read(folder / 'ledgers' / (summary['method'] + '.json.gz')))
            baselines[summary['method']] = {(r['session'], r['symbol']): r for r in old}
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            ready = inputs[key]
            account(ledger, keyed[key], ready)
            accounts += 1
            other = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
            for preparation in ledger['prepare_events']:
                _, row, side, _, _, _, _ = preparation
                stamp = ready['time_s'][int(row)]
                assert permits(summary['gate'], side, snapshot(models, key, stamp, 0), snapshot(models, other, stamp, 60)), (identifier, key, '準備', row)
                preparations += 1
            for order in ledger['orders']:
                fill, source, _, side, _, _, reason, kind = order
                if kind != 1 or reason != 20:
                    continue
                # ----------------------------------------
                # 最終価格更新行だけでなく直前計画行の最新gateも許可している。
                for row in (int(source), int(fill) - 1):
                    stamp = ready['time_s'][row]
                    assert permits(summary['gate'], side, snapshot(models, key, stamp, 0), snapshot(models, other, stamp, 60)), (identifier, key, '初回', row)
                openings += 1
            if summary['gate']['id'] == 'G00':
                old = baselines[summary['method']][key]
                for field in ('result_fingerprints', 'shadow_fingerprints', 'scheduler_fingerprints'):
                    assert ledger[field] == old[field], (identifier, key, field)
        period_check(summary, rows)
        results.append(dict(id=identifier, method=summary['method'], gate=summary['gate']['id'],
                            旧15={s:summary['periods']['旧15'][s]['net_yen'] for s in ('TOPIX', 'NK225')},
                            問題Night={s:summary['periods']['問題Night'][s]['net_yen'] for s in ('TOPIX', 'NK225')},
                            全場取引あり=all(summary['periods']['全16'][s]['active_sessions'] == 16 for s in ('TOPIX', 'NK225'))))
        for source in (path, GATES/'sessions'/(identifier+'.json.gz'), GATES/'ledgers'/(identifier+'.json.gz')):
            fingerprints[source.relative_to(ROOT).as_posix()] = sha(source)
    output = dict(全合格=True, 要求方式数=expected_count, 方式数=len(paths), 口座数=accounts,
                  実施既存候補=sorted({r['method'] for r in results}),
                  準備許可検査数=preparations, 初回直前許可検査数=openings,
                  基準全指紋一致口座数=len(baselines)*32, 全口座金額枚数一致=True,
                  全行注文時価別式一致=True, セッション内完済=True,
                  全準備と初回直前が独立CSVゲートに一致=True, 結果=results, 出力SHA256=fingerprints)
    save('見送り比較の独立検算.json', output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected', type=int)
    args = parser.parse_args()
    result = check(args.expected)
    print({key:value for key,value in result.items() if key not in ('結果', '出力SHA256')})
