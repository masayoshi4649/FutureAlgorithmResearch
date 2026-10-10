"""全420の遅延対照を選別せず、全玉会計・参加時間・因果性を独立監査する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
from pathlib import Path
import pickle
import socket
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
V30 = HERE.parent / 'wave_v30'
OLD = HERE.parent / 'wave_v23'
sys.dont_write_bytecode = True
sys.path.insert(0, str(V30))
import all_accounting_audit as previous
from context_structure_audit import read, save, digest, original_hashes, reject_network
sys.path.insert(0, str(HERE))
from lag_causality_audit import expected_lanes, same

ENGINE = previous.ENGINE
MANAGERS = previous.managers
INPUTS, FIXED = {}, {}
PARTICIPATION = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders')


def freeze() -> dict:
    """機能: 全420の検査内容を損益による選別前に固定する。

    引数: なし。返り値: 監査固定仕様 (dict)。
    """
    value = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                 コードSHA256=digest(Path(__file__)),
                 会計helperSHA256=digest(V30 / 'all_accounting_audit.py'),
                 遅延独立helperSHA256=digest(HERE / 'lag_causality_audit.py'),
                 探索固定SHA256=digest(HERE / '探索条件の固定.json'),
                 対象='全12H×7L×5変形=420。収支・順位で選別しない。',
                 保存方向='元3列から独立二ポインタで再生成し、保存入口/C/Sを全件一致させる。',
                 context='entryはNone、mainは変形C、ownは変形S。価格とATRは元の現在行。',
                 会計='注文現金/両在庫/全返済元建値/部分利確/全原本行時価/DD/上限/次行約定/場末完結。',
                 参加時間='返済台帳の保有時間とは独立に、全原本行の返済後在庫×次時点までの分数を積分する。',
                 保存集計='セッション/期間の全数値とNone、参加指標、返済台帳SHA。Rは記録ATR×初回枚数×固定幅。',
                 未来検査='全10920入力で37%切断、73%以後価格/ATR/入口/使用context変更、両入力の上下反射。',
                 元条件='V000の全84は旧v30の数値・返済台帳SHAと一致。元入力と管理も同一。',
                 制限='旧コード・原本を変更しない。API/current不使用。採否や最良遅延を選ばない。')
    path = HERE / 'lag_accounting_fixed.json'
    if path.exists():
        old = read(path)
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
        return old
    save(path, value)
    return value


def participation(ready: dict, result: dict) -> dict:
    """機能: 原本行の返済後在庫を積分して、同値時刻0分の参加量を独立再計算する。

    引数: ready/result (dict)。返り値: 枚数分・新規回数・初回約定分 (dict)。
    """
    quantities = result['curve'][:, 2:4]
    delta = np.diff(ready['time_s']) / 60.
    assert np.all(delta >= 0)
    units = quantities[:-1].T @ delta
    increases = np.diff(quantities, axis=0, prepend=np.zeros((1, 2))) > 0
    openings = int(np.count_nonzero(np.any(increases, axis=1)))
    held = np.flatnonzero(np.sum(quantities, axis=1) > 0)
    assert openings == int(np.sum(result['orders'][:, 7] == 1))
    return dict(long_unit_minutes=float(units[0]), short_unit_minutes=float(units[1]),
                opening_orders=openings,
                first_entry_min=None if len(held) == 0 else float((ready['time_s'][held[0]] - ready['start']) / 60.))


def initialize() -> None:
    """機能: 通信を遮断して元入力と固定管理を子処理へ読み込む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    assert len(INPUTS) == 26 and len(FIXED['managers']) == 7 and len(FIXED['variants']) == 5
    assert FIXED['managers'] == read(V30 / '探索条件の固定.json')['managers']


def load_columns(directory: Path, identifier: str) -> tuple[dict, ...]:
    """機能: 入口・C・Sの保存配列を型と全区間集合を含めて読み込む。

    引数: directory (Path)、identifier (str)。返り値: 3列の区間辞書 (tuple[dict,...])。
    """
    columns = []
    for folder in ('directions', 'contexts', 'contexts_own'):
        with np.load(directory / folder / f'{identifier}.npz') as archive:
            assert set(archive.files) == {'|'.join(key) for key in INPUTS}
            column = {key: archive['|'.join(key)] for key in INPUTS}
        assert all(value.dtype == np.int8 and len(value) == len(INPUTS[key]['seq']) for key, value in column.items())
        columns.append(column)
    return tuple(columns)


def evaluate(signal_id: str) -> list[dict]:
    """機能: 一入口の全35対照を独立会計と未来除去で監査する。

    引数: signal_id (str)。返り値: 全35条件の監査結果 (list[dict])。
    """
    source = load_columns(V30, signal_id)
    source_paths = [V30 / folder / f'{signal_id}.npz' for folder in ('directions', 'contexts', 'contexts_own')]
    result_paths = [HERE / 'sessions' / f'{signal_id}.json.gz', HERE / 'summaries' / f'{signal_id}.json']
    variant_paths = [HERE / folder / f"{signal_id}__{v['id']}.npz" for v in FIXED['variants']
                     for folder in ('directions', 'contexts', 'contexts_own')]
    before = {str(path): digest(path) for path in source_paths + result_paths + variant_paths}
    sessions = {row['id']: row['rows'] for row in read(result_paths[0])}
    summary = read(result_paths[1])
    saved = {row['id']: row for row in summary['candidates']}
    old_sessions = {row['id']: row['rows'] for row in read(V30 / 'sessions' / f'{signal_id}.json.gz')}
    old_summary = {row['id']: row for row in read(V30 / 'summaries' / f'{signal_id}.json')['candidates']}
    expected_ids = {f"{signal_id}__{m['id']}__{v['id']}" for m in FIXED['managers'] for v in FIXED['variants']}
    assert set(sessions) == set(saved) == expected_ids
    assert len(sessions) == len(saved) == 35
    output = []
    for variant in FIXED['variants']:
        columns = load_columns(HERE, f"{signal_id}__{variant['id']}")
        for key, ready in INPUTS.items():
            wanted = expected_lanes(ready['time_s'], tuple(c[key] for c in source),
                                    variant['delay_seconds'], variant['mode'] == 'start_only')
            same(tuple(c[key] for c in columns), wanted, '実際の保存3列を独立変換へ照合')
        for management in FIXED['managers']:
            base_id = signal_id + '__' + management['id']
            identifier = base_id + '__' + variant['id']
            selected = management['context_source']
            assert selected in ('entry', 'main', 'own')
            target = {(r['session'], r['symbol']): r for r in sessions[identifier]}
            assert len(sessions[identifier]) == len(target) == 26 and set(target) == set(INPUTS)
            baseline = {(r['session'], r['symbol']): r for r in old_sessions[base_id]}
            ledger, rows, series = hashlib.sha256(), [], {}
            for key, ready in INPUTS.items():
                entry = columns[0][key]
                context = None if selected == 'entry' else columns[1 if selected == 'main' else 2][key]
                config = MANAGERS.make_config(management, key[1], ready)
                result = ENGINE.run(ready, entry, config, True, context=context)
                ledger.update(str(key).encode()); ledger.update(result['trades'].tobytes())
                row, curve = previous.session_values(ready, result, config, identifier)
                row.update(participation(ready, result))
                previous.compare_fields(row, target[key], '全保存sessionと独立参加量')
                if variant['id'] == 'V000':
                    previous.compare_fields(dict(row, id=base_id), baseline[key], 'V000旧session完全一致')
                previous.future_checks(ready, entry, context, config, result)
                previous.reflection(ready, entry, context, config, result)
                rows.append(row); series[key] = curve['equity']
            assert ledger.hexdigest() == saved[identifier]['ledger_hash']
            totals = {symbol: previous.period_values(rows, series, symbol) for symbol in previous.MULT}
            for symbol in totals:
                if variant['id'] == 'V000':
                    previous.compare_fields(totals[symbol], old_summary[base_id]['symbols'][symbol], 'V000旧期間全数値')
                    assert ledger.hexdigest() == old_summary[base_id]['ledger_hash']
                totals[symbol].update({name: sum(r[name] for r in rows if r['symbol'] == symbol) for name in PARTICIPATION})
                assert set(totals[symbol]) == set(saved[identifier]['symbols'][symbol])
                previous.compare_fields(totals[symbol], saved[identifier]['symbols'][symbol], '全保存期間と独立参加量')
            output.append(dict(id=identifier, base_id=base_id, variant_id=variant['id'], context_source=selected,
                               全入力数=26, 原本行会計数=sum(r['検算した観測行数'] for r in rows),
                               prefix検査数=26, 未来価格ATR両入力改変数=26, 買売反射数=26,
                               独立参加時間一致=True, 保存全数値一致=True, 台帳SHA256=ledger.hexdigest(),
                               V000旧一致=variant['id'] == 'V000', sessions=rows, symbols=totals))
    assert before == {path: digest(Path(path)) for path in before}
    save(HERE / 'lag_accounting_details' / f'{signal_id}.json.gz', dict(全35条件=output, 保存資料SHA256=before))
    return output


def self_test() -> dict:
    """機能: 実相場を使わず独立会計と同値時刻参加量・部分返済を確認する。

    引数: なし。返り値: 合成検査結果 (dict)。
    """
    base = previous.self_test()
    ready = dict(time_s=np.array([0., 0., 60., 60., 120., 180.]), start=0.)
    result = dict(curve=np.array([[0, 0, 0, 0], [0, 0, 5, 0], [0, 0, 3, 0],
                                 [0, 0, 3, 0], [0, 0, 0, 0], [0, 0, 0, 0]], float),
                  orders=np.array([[1, 0, 1, 1, 5, 100, 20, 1],
                                   [2, 1, 1, 1, 2, 102, 7, 0], [4, 3, 1, 1, 3, 101, 2, 0]], float))
    value = participation(ready, result)
    assert value == dict(long_unit_minutes=8., short_unit_minutes=0., opening_orders=1, first_entry_min=0.)
    result['curve'][:, [2, 3]] = result['curve'][:, [3, 2]]
    value = participation(ready, result)
    assert value == dict(long_unit_minutes=0., short_unit_minutes=8., opening_orders=1, first_entry_min=0.)
    return dict(**base, 同値時刻と部分返済の枚数分=True, 買売参加量反射=True)


def main() -> None:
    """機能: 全420の全玉会計を選別せず実行し、前後の原本指紋も検査する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    protocol, synthetic = freeze(), self_test()
    save(HERE / 'lag_accounting_selftest.json', synthetic)
    if args.prepare:
        print('全420会計・37%切断・73%将来改変・上下反射・独立参加積分を固定。', flush=True)
        return
    began = time.perf_counter()
    fixed = read(HERE / '探索条件の固定.json')
    before = {name: digest(HERE.parent / name) for name in fixed['SHA256']}
    assert before == fixed['SHA256']
    structure = read(HERE / 'lag_causality_before_pnl.json')
    assert structure['構造検査合格'] and structure['全方向列数'] == 4680
    assert structure['lag_design_SHA256'] == digest(HERE / 'lag_design.py')
    originals = original_hashes()
    assert originals == structure['原本78SHA256']
    output = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, signal['id']): signal['id'] for signal in fixed['signals']}
        for future in as_completed(futures):
            output.extend(future.result())
            print(f"{len(output)}/420 {futures[future]} 全35条件の会計・参加量・未来・反射一致", flush=True)
    wanted = {f"{s['id']}__{m['id']}__{v['id']}" for s in fixed['signals'] for m in fixed['managers'] for v in fixed['variants']}
    assert len(output) == 420 and {r['id'] for r in output} == wanted
    assert originals == original_hashes()
    assert before == {name: digest(HERE.parent / name) for name in before}
    assert freeze() == protocol
    result = dict(全監査合格=True, 対象条件数=420, 全入力数=sum(r['全入力数'] for r in output),
                  全原本行会計数=sum(r['原本行会計数'] for r in output),
                  prefix検査数=sum(r['prefix検査数'] for r in output),
                  未来価格ATR両入力改変数=sum(r['未来価格ATR両入力改変数'] for r in output),
                  買売反射数=sum(r['買売反射数'] for r in output), V000旧一致条件数=sum(r['V000旧一致'] for r in output),
                  全方向保存列一致=True, 独立参加時間一致=True, 保存全数値と全台帳SHA一致=True,
                  監査規則=protocol, 合成検査=synthetic,
                  条件=[{k: v for k, v in row.items() if k != 'sessions'} for row in sorted(output, key=lambda r: r['id'])],
                  詳細='lag_accounting_details/Hxxx.json.gz', 原本78SHA256=originals, 探索固定SHA256=before,
                  API取得数=0, 現在データ使用=False, 成績による対象選別=False, ルール変更=False,
                  実行秒=time.perf_counter() - began)
    save(HERE / 'lag_accounting_audit.json', result)
    lines = ['# 全420の独立全玉会計監査', '',
             f'全420×26＝{result["全入力数"]:,}入力を監査。注文から再構成した原本行は{result["全原本行会計数"]:,}行。', '',
             '- 変形入口/C/Sの保存列を独立二ポインタで再生成して照合。管理のentry/main/ownを読み分けた。',
             '- 注文現金・両在庫・部分利確・残玉・全行時価・最大下落・上限・次行以降約定・場内返済が一致。',
             '- 枚数分は全原本行の在庫を積分して独立照合。同じ時刻の行は0分として扱った。',
             '- 保存セッション/期間の全指標と返済台帳SHAが一致。V000全84は旧v30結果に一致。',
             '- 全10,920入力で37%切断、73%以後の価格/ATR/入口/使用context改変、上下反射が一致。',
             '- 原本78と凍結資料のSHAは監査前後で不変。API/currentを使用せず、最良遅延を選んでいない。', '',
             '実装・会計検査の合格は未知期間の収益性や円損失の上限を保証しない。']
    (HERE / 'lag_accounting_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print({k: result[k] for k in ('全監査合格', '対象条件数', '全入力数', '全原本行会計数', '実行秒')}, flush=True)


if __name__ == '__main__':
    main()
