"""自動モード全口座の独立会計と実データ注文順を確認する。"""

from __future__ import annotations

import os
from pathlib import Path
import pickle
import sys

import numpy as np

from independent_audit import HERE, ROOT, read, same, save, sha
from mode_engine_check import prefix


MODE = ROOT / 'work/wave_v49/modes'
sys.path.insert(0, str(MODE))
import run as replay


def account(ledger: dict, summary: dict, ready: dict) -> tuple:
    """機能: 注文現金と返済脚の二式から各口座を照合する。

    引数: ledger/summary/ready (dict)。返り値: 口座証跡と全行円時価 (tuple)。
    """
    symbol = ledger['symbol']
    quantity, multiplier = (5, 1000.) if symbol == 'TOPIX' else (10, 10.)
    n = len(ready['last'])
    cash_delta, pos_delta = np.zeros(n), np.zeros(n)
    opens, closes = {}, {}
    for item in ledger['orders']:
        execution, source, campaign, side, size, price, reason, opening = item
        assert 0 <= source < execution < n and size == quantity and side in (-1, 1)
        i = int(execution)
        assert ready['start'] <= ready['time_s'][i] < ready.get('session_close', ready['limit'] + 600.)
        if opening:
            assert reason == 20 and ready['time_s'][i] < ready['limit']
            assert campaign not in opens
            opens[campaign] = item
        else:
            assert campaign not in closes
            closes[campaign] = item
        cash_delta[i] -= side * size * price
        pos_delta[i] += side * size
    cash, pos = cash_delta.cumsum(), pos_delta.cumsum()
    assert set(opens) == set(closes) and set(opens) == {r[0] for r in ledger['trades']}
    assert (abs(pos) <= quantity).all() and pos[-1] == 0
    equity = (cash + pos * ready['last']) * multiplier
    gains, sizes = [], []
    for trade in ledger['trades']:
        campaign, _, side, size, entry, exit_price, entry_row, exit_row, _, reason, stored = trade
        same(side * size * (exit_price - entry), stored, '脚損益')
        source, target = opens[campaign], closes[campaign]
        assert source[0] == entry_row and target[0] == exit_row
        assert source[3] == side and target[3] == -side
        assert source[4] == target[4] == size == quantity
        assert source[5] == entry and target[5] == exit_price and target[6] == reason
        gains.append(stored * multiplier)
        sizes.append(size)
    gains, sizes = np.asarray(gains), np.asarray(sizes)
    stats = dict(net=float(sum(gains)), gross_profit=float(sum(gains[gains > 0])),
                 gross_loss=float(-sum(gains[gains < 0])), trades=len(gains),
                 wins=int(sum(gains > 0)), losses=int(sum(gains < 0)),
                 win_qty=float(sum(sizes[gains > 0])), loss_qty=float(sum(sizes[gains < 0])),
                 flat_qty=float(sum(sizes[gains == 0])))
    line = np.r_[0., equity]
    stats['dd'] = float(max(np.maximum.accumulate(line) - line))
    for field, value in stats.items():
        same(value, summary[field], field)
    same(equity[-1], stats['net'], '期末時価')
    modes = np.asarray(ledger['trade_modes'])
    assert len(modes) == len(gains) and np.isin(modes, (1, 2)).all()
    for name, code in (('trend', 1), ('range', 2)):
        same(sum(modes == code), summary[name + '_trades'], 'モード件数')
        same(sum(gains[modes == code]), summary[name + '_net'], 'モード損益')
    return dict(価格数量会計一致=True, 全行時価再構成=True, 場内完済=True,
                初回枚数一定=True, 方向別保有上限内=True, 取引数=len(gains)), equity


def trace_check(ready: dict, result: tuple) -> dict:
    """機能: 前行有効注文から全新規と返済の約定条件を再判定する。

    引数: ready (dict)、result (tuple)。返り値: 監査証跡 (dict)。
    """
    orders, _, _, _, trace = result
    passed, market = 0, 0
    for order in orders:
        i, source, _, side, _, fill, reason, opening = order
        i = int(i)
        prior = trace[i - 1]
        px = ready['last'][i]
        assert source < i
        if opening:
            assert prior[0] == 0 and prior[11] == side and prior[13] == source
            expected = px if prior[18] else prior[12]
            assert prior[18] or side * (px - prior[12]) >= -1e-8
        else:
            assert prior[0] == -side
            if prior[9]:
                assert prior[9] == reason and prior[10] == source
                expected = px
                market += 1
            else:
                assert prior[7] == reason and prior[8] == source
                assert prior[0] * (px - prior[6]) <= 1e-8
                expected = prior[6]
        same(expected, fill, '前行注文からの約定')
        passed += 1
    for i in range(1, len(trace)):
        now, prior = trace[i], trace[i - 1]
        if now[0] and prior[0] and now[2] == prior[2]:
            assert now[0] * (now[6] - prior[6]) >= -1e-8
        if now[0] and now[0] * (ready['last'][i] - now[6]) <= 1e-8:
            assert now[9] != 0
    return dict(注文順照合数=passed, 次行成行件数=market, 既成立水準の遡及約定なし=True,
                既存停止線の緩和なし=True)


def check() -> dict:
    """機能: 全20方式の640口座と代表4口座の実データ因果性を検査する。

    引数: なし。返り値: 全件検算と代表因果検査の証跡 (dict)。
    """
    inputs, board = replay.features.load_inputs()
    results = read(MODE / '自動モードの比較.json')
    assert len(results) == 20
    checks = []
    for result in results:
        identifier = result['spec']['id']
        rows = {(r['session'], r['symbol']): r for r in result['sessions']}
        ledgers = read(MODE / 'ledgers' / (identifier + '.json.gz'))
        assert len(rows) == len(ledgers) == 32
        lines = {}
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            proof, lines[key] = account(ledger, rows[key], inputs[key])
            checks.append(dict(id=identifier, session=key[0], symbol=key[1], **proof))
        for period, symbols in result['periods'].items():
            for symbol, totals in symbols.items():
                selected = sorted((r for r in rows.values() if r['symbol'] == symbol and
                    (period == '全16' or ((r['session'] == replay.NEW) == (period == '問題Night')))), key=lambda r:r['session'])
                for field in ('net', 'gross_profit', 'gross_loss', 'trades', 'wins', 'losses', 'win_qty', 'loss_qty', 'flat_qty', 'trend_trades', 'range_trades', 'trend_net', 'range_net'):
                    same(sum(r[field] for r in selected), totals[field], '期間/' + field)
                offset = 0.
                curves = [np.array([0.])]
                for row in selected:
                    curves.append(lines[row['session'], symbol] + offset)
                    offset += row['net']
                line = np.concatenate(curves)
                same(max(np.maximum.accumulate(line) - line), totals['dd'], '期間連結時価下落')
                assert totals['win_sessions'] == sum(r['net'] > 0 for r in selected)
                assert totals['active_sessions'] == sum(r['trades'] > 0 for r in selected)
                same(offset - max(0, max(r['net'] for r in selected)), totals['without_best_session'], '最大勝ち場除外')
    # ----------------------------------------
    # 全20条件は人工監査済み。実データで入口から出口までのtraceと因果性を代表4口座で確認する。
    chosen = {key:ready for key,ready in inputs.items() if key[0] == replay.NEW}
    features = replay.features.build(chosen, {key:board[key] for key in chosen})
    causal = []
    for identifier in ('A00', 'A08'):
        spec = next(s for s in replay.catalog() if s['id'] == identifier)
        for key, ready in chosen.items():
            source = features[key]
            result = replay.execute(ready, source, spec)
            proof = trace_check(ready, result)
            n = len(ready['last'])
            tied = np.flatnonzero(np.diff(ready['time_s']) == 0) + 1
            count = int(tied[np.argmin(abs(tied - int(n * .57)))])
            clipped = {k:(v[:count].copy() if isinstance(v, np.ndarray) and v.shape == (n,) else v) for k,v in ready.items()}
            limited = {k:v[:count].copy() for k,v in source.items()}
            prefix(result, replay.execute(clipped, limited, spec, require_flat=False), count)
            changed = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
            changed['last'][count:] += 50 * ready['tick'] + np.arange(n - count) * ready['tick']
            changed['atr'][count:] *= 3
            mutated = {k:v.copy() for k,v in source.items()}
            for name in ('trend', 'range_side', 'book_score', 'absorb_side'):
                mutated[name][count:] *= -1
            prefix(result, replay.execute(changed, mutated, spec), count)
            center = 2 * np.ceil(max(ready['last']) / ready['tick']) * ready['tick']
            reflected = dict(ready, last=center - ready['last'])
            reflected_model = {k:v.copy() for k,v in source.items()}
            for name in ('trend', 'range_side', 'book_score', 'absorb_side'):
                reflected_model[name] *= -1
            reflected_model['support20'], reflected_model['resistance20'] = center - source['resistance20'], center - source['support20']
            mirror = replay.execute(reflected, reflected_model, spec)
            np.testing.assert_allclose(result[2], mirror[2], atol=1e-6, rtol=0)
            np.testing.assert_allclose(result[1][:, 10], mirror[1][:, 10], atol=1e-6, rtol=0)
            causal.append(dict(id=identifier, session=key[0], symbol=key[1], **proof,
                               同秒途中切断一致=True, 未来改変一致=True, 上下反射一致=True))
    output = dict(全合格=True, 口座数=len(checks), 全方式全口座会計一致=True,
                  全期間集計一致=True, 代表実データ因果検査=causal, 会計検査=checks,
                  参照SHA256={name:sha(MODE/name) for name in ('engine.py', 'features.py', 'run.py', '方式の事前固定.json', '自動モードの比較.json')})
    save('自動モード実データの独立監査.json', output)
    return output


if __name__ == '__main__':
    output = check()
    print({k:v for k,v in output.items() if k not in ('会計検査', '参照SHA256')})
