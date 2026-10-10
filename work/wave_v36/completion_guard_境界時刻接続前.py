"""全格子・別補助・独立会計・指定波・図を結び、資料不足の完了表示を拒否する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

import band_runner as runner
import band_assessment as assessment
import band_independent_statistics as statistics
from run_verified import unique, verify_catalog

HERE, ROOT = runner.HERE, runner.ROOT
OUT = ROOT / 'アルゴリズム調査/00031_出来高通過と気配維持からの方向判定'


def proof_rows(record: dict, inputs: dict) -> None:
    """機能: 独立会計の入力別証拠を、全26の原本長と照合する。

    引数: record/inputs (dict)。返り値: なし (None)。総数だけの自己申告を受理しない。
    """
    assert record['全入力数'] == 26
    for field in ('全保存台帳一致', '全会計一致', '全期間時価一致'):
        assert record[field] is True
    rows = unique(record['入力別'], ('session', 'symbol'))
    assert set(rows) == set(inputs)
    for key, row in rows.items():
        assert row['prefix'] == row['future'] == row['reflection'] == 1
        assert row['原本行会計数'] == len(inputs[key]['last'])
    for field in ('prefix', 'future', 'reflection'):
        assert record[field] == 26
    assert record['原本行会計数'] == sum(len(ready['last']) for ready in inputs.values())


def session_accounting(row: dict, ledger: dict, ready: dict) -> None:
    """機能: 金額・決済枚数・最大勝ちの採否入力を全返済明細から再集計する。

    引数: row/ledger/ready (dict)。返り値: なし (None)。注文器の再実行はしない。
    """
    trades = np.asarray(ledger['trades'], dtype=float).reshape(-1, 11)
    cycles = np.asarray(ledger['cycles'], dtype=float).reshape(-1, 10)
    factor = ledger['config']['point_value']
    pnl = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * factor
    assert np.isfinite(pnl).all()
    wins, losses = pnl > 1e-6, pnl < -1e-6
    expected = dict(gross_profit_yen=float(pnl[wins].sum()), gross_loss_yen=float(-pnl[losses].sum()),
        net_yen=float(pnl.sum()), profit_units=int(trades[wins, 3].sum()), loss_units=int(trades[losses, 3].sum()),
        zero_units=int(trades[~(wins | losses), 3].sum()), closed_units=int(trades[:, 3].sum()), cycles=len(cycles),
        two_largest_cycle_profits=sorted([float(v) * factor for v in cycles[:, 3] if v > 0], reverse=True)[:2])
    for field, value in expected.items():
        statistics.equal(row[field], value, field)
    assert ledger['stats'][9] == 0
    assert row['max_long'] <= ledger['config']['audit_cap'] and row['max_short'] <= ledger['config']['audit_cap']
    for cycle in cycles:
        assert 0 < int(cycle[1]) < int(cycle[2]) < len(ready['last'])


def collect() -> dict:
    """機能: 全資料と全入力の一致を確認し、固定主仮説だけを最終再判定する。

    引数: なし。返り値: 完備記録 (dict)。売買・入力生成・APIは呼び出さない。
    """
    hashes = {}
    def check(path: Path, expected: str | None = None) -> str:
        """機能: 参照資料の指紋をキャッシュし、元証拠と結ぶ。

        引数: path (Path)、expected (str|None)。返り値: SHA256 (str)。
        """
        relative = path.resolve().relative_to(ROOT).as_posix()
        assert '/live/' not in relative.lower() and '/current/' not in relative.lower()
        if relative not in hashes:
            hashes[relative] = runner.digest(path)
        if expected is not None:
            assert hashes[relative] == expected, '参照資料変更: ' + relative
        return hashes[relative]
    def load(path: Path):
        """機能: JSONの内容とその実体指紋を同時に取得する。

        引数: path (Path)。返り値: JSON値 (dict|list)。
        """
        check(path)
        return runner.read(path)
    def refs(value: dict, field: str, base: Path = ROOT) -> None:
        """機能: 証拠に含まれる全参照資料のSHAを照合する。

        引数: value (dict)、field (str)、base (Path)。返り値: なし (None)。
        """
        assert value[field]
        for relative, sha in value[field].items():
            check(base / relative, sha)

    fixed = load(HERE / '探索条件の固定.json')
    verify_catalog(fixed)
    start = load(HERE / '起動前監査.json')
    assert start['実行可能'] is True and start['探索固定SHA256'] == check(HERE / '探索条件の固定.json')
    refs(start, 'SHA256'); refs(fixed, 'SHA256')
    assert start['ガード固定SHA256'] == check(HERE / 'run_verified_fixed.json')
    execution = load(HERE / '起動実行の証跡.json')
    assert execution['全実行完了'] is True and execution['主終了コード'] == execution['補助終了コード'] == 0
    assert execution['主後固定SHA一致'] is True and execution['補助後固定SHA一致'] is True
    assert execution['起動前監査SHA256'] == check(HERE / '起動前監査.json')
    assert execution['探索固定SHA256'] == check(HERE / '探索条件の固定.json')
    assert execution['SHA256'] == start['SHA256']
    for label, destination in (('主', ''), ('補助', 'supplementary')):
        check(HERE / destination / '主再生の完了.json', execution[label + '完了資料SHA256'])
    inputs_path = HERE.parent / 'wave_v23/inputs.pkl'
    check(inputs_path)
    inputs = pickle.loads(inputs_path.read_bytes())
    assert len(inputs) == 26
    names = sorted({key[0] for key in inputs})
    assert names == fixed['全セッション'] and names[6:] == fixed['後半7セッション']
    account_fixed = load(HERE / 'band_accounting_fixed.json')
    refs(account_fixed, 'SHA256')
    index, sessions, saved_waves, saved_ledgers = {}, {}, {}, {}

    # ----------------------------------------
    # 主364と補助65を別々の完全集合として確認する。
    for destination, specs in (('', fixed['conditions']), ('supplementary', fixed['supplementary_conditions'])):
        folder = HERE / destination
        count = len(specs)
        complete = load(folder / '主再生の完了.json')
        assert complete['全条件数'] == count and complete['全入力数'] == count * 26 and complete['全指定波数'] == count * 8
        assert complete['探索固定SHA256'] == check(HERE / '探索条件の固定.json')
        assert complete['API取得数'] == 0 and complete['現在保存物使用'] is False
        summaries = unique(load(folder / '全条件の期間集計.json.gz'), ('id',))
        assert set(summaries) == {(spec['id'],) for spec in specs}
        header = load(folder / 'accounting_audit.json')
        assert header['全監査合格'] is True and header['対象条件数'] == count and header['全入力数'] == count * 26
        assert header['監査固定SHA256'] == check(HERE / 'band_accounting_fixed.json')
        assert header['探索固定SHA256'] == check(HERE / '探索条件の固定.json')
        assert header['API取得数'] == 0 and header['現在保存物使用'] is False
        for field in ('prefix', 'future', 'reflection'):
            assert header[field] == count * 26
        assert header['原本行会計数'] == count * sum(len(ready['last']) for ready in inputs.values())
        proofs = unique(header['条件'], ('id',))
        assert set(proofs) == set(summaries)
        for kind, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('waves', '.json.gz'),
            ('accounting', '.json.gz'), ('accounting_details', '.json.gz'), ('summaries', '.json')):
            assert {p.name for p in (folder / kind).glob('*' + suffix)} == {spec['id'] + suffix for spec in specs}
        for spec in specs:
            identifier = spec['id']
            summary = load(folder / 'summaries' / (identifier + '.json'))
            assert summary == summaries[(identifier,)] and summary['spec'] == spec and summary['id'] == identifier
            assert summary['探索固定SHA256'] == check(HERE / '探索条件の固定.json')
            proof = load(folder / 'accounting_details' / (identifier + '.json.gz'))
            assert proof == proofs[(identifier,)]
            assert proof['監査固定SHA256'] == check(HERE / 'band_accounting_fixed.json')
            proof_rows(proof, inputs)
            expected_paths = {(folder / kind / (identifier + suffix)).relative_to(ROOT).as_posix()
                for kind, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('waves', '.json.gz'),
                                    ('accounting', '.json.gz'), ('summaries', '.json'))}
            assert set(proof['保存物SHA256']) == expected_paths
            refs(proof, '保存物SHA256')
            rows = load(folder / 'sessions' / (identifier + '.json.gz'))
            records = unique(rows, ('session', 'symbol'))
            ledgers = unique(load(folder / 'ledgers' / (identifier + '.json.gz')), ('session', 'symbol'))
            assert set(records) == set(ledgers) == set(inputs)
            ledger_hash = hashlib.sha256()
            for key, ready in sorted(inputs.items()):
                assert records[key]['id'] == identifier
                session_accounting(records[key], ledgers[key], ready)
                ledger_hash.update(str(key).encode('utf-8'))
                ledger_hash.update(np.asarray(ledgers[key]['trades'], dtype=float).reshape(-1, 11).tobytes())
            assert ledger_hash.hexdigest() == summary['ledger_hash']
            statistics.equal(summary['all_symbols'], runner.period(rows, names), identifier + '/全13')
            statistics.equal(summary['symbols'], runner.period(rows, names[6:]), identifier + '/後7')
            waves = load(folder / 'waves' / (identifier + '.json.gz'))
            wave_map = unique(waves, ('method', 'wave', 'session', 'symbol'))
            expected = {(identifier, wave['id'], wave['session'], symbol) for wave in fixed['指定波'] for symbol in runner.SYMBOLS}
            assert set(wave_map) == expected and summary['wave_passes'] == sum(row['正方向ネット20分目安達成'] for row in waves)
            index[identifier], sessions[identifier], saved_ledgers[identifier] = summary, rows, ledgers
            saved_waves.update(wave_map)
        print('完備確認', destination or '主', count, '条件', flush=True)

    # ----------------------------------------
    # 波は全注文からの独立計算へ、図は全約定・原本asofへ接続する。
    wave = load(HERE / 'wave_order_audit.json')
    assert wave['主条件数'] == 364 and wave['補助条件数'] == 65 and wave['全条件数'] == 429
    assert wave['全指定波数'] == 3432 and wave['比較境界数'] == 6864
    for field in ('全合格', '注文独立会計一致', '保有時間枚数分一致', '区間内全注文一致', '波定義全件一致', '全通過数一致'):
        assert wave[field] is True
    assert wave['固定SHA256'] == check(HERE / 'wave_order_fixed.json')
    refs(wave, '保存資料SHA256', HERE)
    assert len(wave['保存資料SHA256']) == 429 * 3
    independent_waves = unique(wave['結果'], ('method', 'wave', 'session', 'symbol'))
    assert set(independent_waves) == set(saved_waves) and len(independent_waves) == 3432
    assert set(wave['条件別通過数']) == set(index)
    for identifier in index:
        assert wave['条件別通過数'][identifier] == index[identifier]['wave_passes']
    for key, row in independent_waves.items():
        assert row['保存値一致'] is True
        for field in ('開始境界', '終了境界', '正方向ネット保有分', '逆方向ネット保有分', '正方向枚数分',
                      '逆方向枚数分', '時価損益差円', '実現損益差円', '含み損益差円', '正方向ネット20分目安達成'):
            statistics.equal(row[field], saved_waves[key][field], str(key) + '/' + field)
        assert row['正方向ネット20分目安達成'] == (row['正方向ネット保有分'] >= 20 - 1e-9)
    chart = load(HERE / 'chart_audit.json')
    chart_data = load(HERE / 'chart_data_audit.json')
    for record in (chart, chart_data):
        assert record['全図示数'] == 104 and record['固定SHA256'] == check(HERE / 'chart_fixed.json')
        assert record['API取得数'] == 0 and record['現在保存物使用'] is False
        assert record['注文初回準備の誤帰属なし'] is True and record['全返済一致'] is True
    for flag in ('全収支一致', '全台帳一致', '全原本asof一致'):
        assert chart[flag] is True
    for flag in ('全新規一致', '全確定足一致', '原本asof列一致', 'ATR価格線の別式計算一致', '価格準備参考明細一致', 'ローカルリンク全有効'):
        assert chart_data[flag] is True
    refs(chart, '台帳元SHA256', HERE)
    check(OUT / '５分足と売買.html', chart_data['HTML_SHA256'])
    check(HERE / 'chart_details.json.gz', chart_data['図明細SHA256'])
    chart_fixed = load(HERE / 'chart_fixed.json')
    chart_rows = unique(chart['保存済み収支との比較'], ('id', 'session', 'symbol'))
    assert set(chart_rows) == {(identifier, session, symbol) for identifier in chart_fixed['手法'] for session, symbol in inputs}
    entry_count = exit_count = 0
    for (identifier, session, symbol), row in chart_rows.items():
        ledger = saved_ledgers[identifier][session, symbol]
        orders = np.asarray(ledger['orders'], dtype=float).reshape(-1, 8)
        entries = int(np.sum(orders[:, 7] == 1)); exits = len(ledger['trades'])
        assert row['保存値一致'] is True and row['新規件数'] == entries and row['返済件数'] == exits
        assert abs(row['収支円'] - next(r['net_yen'] for r in sessions[identifier] if r['session'] == session and r['symbol'] == symbol)) <= 1e-6
        entry_count += entries; exit_count += exits
    assert chart_data['全新規件数'] == entry_count and chart_data['全返済件数'] == exit_count

    # ----------------------------------------
    # 判定内容は固定moduleだけから再計算し、暫定版と監査フラグ以外の差を許さない。
    randoms = [index[f'Q034__R{seed:03d}'] for seed in range(64)]
    comparison = assessment.random_comparison(index[assessment.PRIMARY], randoms, index['Q034__REV'])
    provisional = assessment.assess(index, sessions, names, False, comparison)
    published = load(HERE / '暫定判定.json')
    assert published == provisional
    final = assessment.assess(index, sessions, names, True, comparison)
    assert {k: v for k, v in final.items() if k not in ('監査完了', '既知比較の採用候補')} == {
        k: v for k, v in provisional.items() if k not in ('監査完了', '既知比較の採用候補')}
    own = load(HERE / 'completion_guard_fixed.json')
    refs(own, 'SHA256')
    assert all(runner.digest(ROOT / relative) == sha for relative, sha in hashes.items()), '完備検査中に資料が変化'
    runner.save(HERE / '独立判定.json', final)
    check(HERE / '独立判定.json')
    return dict(検証完了=True, 全条件数=364, 主条件数=91, 診断条件数=273, 補助条件数=65,
        全入力数=9464, 補助全入力数=1690, 全指定波数=3432, 比較境界数=6864, 全図示数=104,
        全返済図示件数=exit_count, 全新規図示件数=entry_count, 主仮説=assessment.PRIMARY,
        主仮説の採用目安合格=final['既知比較の採用候補'], 採否条件変更=False,
        ガード実装SHA256=check(Path(__file__)), ガード固定SHA256=check(HERE / 'completion_guard_fixed.json'),
        参照資料SHA256=dict(sorted(hashes.items())), API取得数=0, 現在保存物使用=False,
        確認日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat())


def freeze() -> None:
    """機能: 完備検査の実装と人工拒否試験を固定する。

    引数: なし。返り値: なし (None)。採否moduleへ変更を加えない。
    """
    files = [HERE / name for name in ('completion_guard.py', 'completion_guard_test.py', 'completion_guard_test.json')]
    value = dict(全条件数=364, 補助条件数=65, 全指定波数=3432, 全図示数=104, 採否条件変更=False,
        SHA256={path.relative_to(ROOT).as_posix(): runner.digest(path) for path in files})
    path = HERE / 'completion_guard_fixed.json'
    if path.exists():
        assert runner.read(path) == value
    else:
        runner.save(path, value)


def main() -> None:
    """機能: 完備規則を保存し、指定時に全資料を照合する。

    引数: --prepare (bool)。返り値: なし (None)。実相場の再生やAPIは行わない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args(); freeze()
    if args.prepare:
        print('主364・別補助65・全3432波・104図の完備検査を固定。', flush=True)
        return
    result = collect()
    runner.save(HERE / '完備監査.json', result)
    print({k: result[k] for k in ('検証完了', '全条件数', '補助条件数', '全指定波数', '全図示数')}, flush=True)


if __name__ == '__main__':
    main()
