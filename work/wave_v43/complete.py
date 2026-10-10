"""全固定条件と全台帳の存在・会計・監査を採否へ結合する。"""

from __future__ import annotations

import numpy as np

import runner

HERE, ROOT = runner.HERE, runner.ROOT


def complete() -> dict:
    """機能: 32条件を欠落なく検算し、監査後にのみ採否を計算する。

    引数: なし。返り値: 全体の完備監査(dict)。
    """
    fixed = runner.read(HERE/'探索条件の固定.json')
    runner.verify(fixed['参照資料SHA256'])
    finished = runner.read(HERE/'主再生の完了.json')
    assert finished['全合格'] and finished['全条件数'] == 32
    assert finished['全入力数'] == 832 and finished['因果入力数'] == 128
    assert finished['旧単一窓一致入力数'] == 156
    frozen_sha = runner.digest(HERE/'探索条件の固定.json')
    assert finished['探索固定SHA256'] == frozen_sha
    specs = runner.design.catalog()
    assert fixed['conditions'] == specs
    names = fixed['全セッション']
    expected = {(name, symbol) for name in names for symbol in runner.old.SYMBOLS}
    assert len(expected) == 26 and names[6:] == fixed['後半7セッション']
    completed = {r['id']:r for r in finished['records']}
    assert len(completed) == len(finished['records']) == 32
    assert set(completed) == {s['id'] for s in specs}
    index, session_rows, all_ledgers, output_refs = {}, {}, {}, {}
    account_count = causal_count = raw_rows = legacy_count = 0
    for spec in specs:
        identifier = spec['id']
        record = runner.read(HERE/'completed'/(identifier+'.json'))
        assert record == completed[identifier] and record['全合格']
        assert record['探索固定SHA256'] == frozen_sha
        runner.verify(record['出力SHA256'])
        output_refs.update(record['出力SHA256'])
        output_refs[(HERE/'completed'/(identifier+'.json')).relative_to(ROOT).as_posix()] = runner.digest(HERE/'completed'/(identifier+'.json'))
        rows = runner.read(HERE/'sessions'/(identifier+'.json.gz'))
        ledgers = runner.read(HERE/'ledgers'/(identifier+'.json.gz'))
        proofs = runner.read(HERE/'audits'/(identifier+'.json.gz'))
        keyed_rows = {(r['session'],r['symbol']):r for r in rows}
        keyed_ledgers = {(r['session'],r['symbol']):r for r in ledgers}
        assert set(keyed_rows) == set(keyed_ledgers) == expected
        assert len(rows) == len(ledgers) == len(proofs) == 26
        assert {(r['session'],r['symbol']) for r in proofs} == expected
        for key, row in keyed_rows.items():
            ledger = keyed_ledgers[key]
            factor = ledger['config']['point_value']
            trades = np.asarray(ledger['trades'], float).reshape((-1, 11))
            pnl = (trades[:,5]-trades[:,4])*trades[:,2]*trades[:,3]*factor
            # 全返済脚の金額と枚数は保存された利益欄から足さず、約定価格から計算する。
            calculated = dict(gross_profit_yen=float(pnl[pnl>0].sum()),
                gross_loss_yen=float(-pnl[pnl<0].sum()), net_yen=float(pnl.sum()),
                profit_units=int(trades[pnl>0,3].sum()), loss_units=int(trades[pnl<0,3].sum()),
                zero_units=int(trades[pnl==0,3].sum()), closed_units=int(trades[:,3].sum()))
            for field, value in calculated.items():
                assert abs(value-row[field]) <= 1e-6, (identifier, key, field)
            assert row['max_long'] <= ledger['config']['audit_cap']
            assert row['max_short'] <= ledger['config']['audit_cap']
        for proof in proofs:
            for flag in runner.PROOF_FLAGS:
                assert proof[flag] is True
            assert proof['全統計一致'] is True and proof['原本行数'] > 0
        count_rows = sum(p['原本行数'] for p in proofs)
        assert count_rows == record['全原本行会計数']
        checks = runner.read(HERE/'causality'/(identifier+'.json'))
        assert len(checks) == 4
        assert {(r['session'],r['symbol']) for r in checks} == {(n,s) for n in runner.REPRESENTATIVE for s in runner.old.SYMBOLS}
        assert all(r['先頭切断一致'] and r['未来変更一致'] for r in checks)
        summary = runner.read(HERE/'summaries'/(identifier+'.json'))
        assert summary['spec'] == spec and summary['探索固定SHA256'] == frozen_sha
        for period, sessions in (('all_symbols',names), ('symbols',names[6:])):
            runner.audit.statistics.equal(runner.old.period(rows,sessions), summary[period], '完備の期間再集計')
        wave = runner.read(HERE/'waves'/(identifier+'.json.gz'))
        assert len(wave) == 8 and summary['wave_passes'] == sum(r['正方向ネット20分目安達成'] for r in wave)
        index[identifier], session_rows[identifier], all_ledgers[identifier] = summary, rows, ledgers
        account_count += len(rows)
        causal_count += len(checks)
        raw_rows += count_rows
        legacy_count += record['旧単一窓一致入力数']
    assert (account_count, causal_count, legacy_count) == (832, 128, 156)
    assert raw_rows == finished['全原本行会計数']
    assessment = runner.module('window_comparison_assessment', HERE/'assessment.py')
    decision = assessment.assess(index, session_rows, names, all_ledgers, verification=True)
    runner.save(HERE/'assess_results.json', decision)
    for path in (HERE/'探索条件の固定.json', HERE/'主再生の完了.json', HERE/'assess_results.json'):
        output_refs[path.relative_to(ROOT).as_posix()] = runner.digest(path)
    runner.verify(fixed['参照資料SHA256'])
    runner.verify(output_refs)
    result = dict(全合格=True, 全条件数=32, 全入力数=account_count, 全原本行会計数=raw_rows,
        因果入力数=causal_count, 旧単一窓一致入力数=legacy_count, 探索固定SHA256=frozen_sha,
        全原本場内返済=True, 参照資料SHA256=fixed['参照資料SHA256'], 出力SHA256=output_refs,
        現在API取得数=0, 保存ライブ使用=False, 未知での有効性確認=False, 全体目標達成=False)
    runner.save(HERE/'完備監査.json', result)
    return result


if __name__ == '__main__':
    value = complete()
    print(f"全{value['全条件数']}条件・{value['全入力数']}入力の完備監査に合格。", flush=True)
