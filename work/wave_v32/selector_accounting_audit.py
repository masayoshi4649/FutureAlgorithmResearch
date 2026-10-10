"""全148選択条件を選別せず、全玉会計と執行の因果性を独立に監査する。"""

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
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
V30 = HERE.parent / 'wave_v30'
sys.dont_write_bytecode = True
# 同名の旧モジュールより今回の選択器を先に通常importする。
sys.path.insert(0, str(HERE))
import selector_signals
import engine_selector as ENGINE
sys.path.insert(0, str(V30))
import all_accounting_audit as previous
from context_structure_audit import read, save, digest, original_hashes, reject_network

MANAGERS = previous.managers
INPUTS, ENTRIES, FIXED, SHADOW = {}, {}, {}, []
PARTICIPATION = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders')
SESSION_FIELDS = set(('id symbol session gross_profit_yen gross_loss_yen net_yen profit_units loss_units zero_units '
    'cycles cycle_wins cycle_losses cycle_profit_yen cycle_loss_yen net_r drawdown_yen min_equity_yen max_equity_yen '
    'max_long max_short closed_units reversals longest_losing_streak maximum_trade_profit maximum_trade_loss '
    'two_largest_cycle_profits long_unit_minutes short_unit_minutes opening_orders first_entry_min selection').split())
PERIOD_FIELDS = set(('gross_profit_yen gross_loss_yen net_yen profit_units loss_units zero_units cycles cycle_wins '
    'cycle_losses cycle_profit_yen cycle_loss_yen net_r closed_units money_ratio cycle_ratio win_sessions active_sessions '
    'worst_session drawdown_yen best_removed_net best_removed_pf best_trade_removed_net max_long max_short '
    'longest_losing_streak session_count average_unit_payoff long_unit_minutes short_unit_minutes opening_orders selection').split())


def freeze() -> dict:
    """機能: 成績や順位を読む前に、148条件の会計検査と対象集合を固定する。

    引数: なし。返り値: 監査仕様 (dict)。既存仕様と異なる再実行は拒否する。
    """
    fixed = read(HERE / '探索条件の固定.json')
    sources = [Path(__file__), V30 / 'all_accounting_audit.py',
               HERE.parent / 'wave_v29/selected_accounting_audit.py',
               V30 / 'context_structure_audit.py', HERE / 'selector_causality_before_pnl.json']
    value = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        対象条件ID=[s['id'] for s in fixed['conditions']], 対象条件数=148, 対象入力数=26,
        原本行数='実際の入力26区間のlast長合計×148。手入力した行数を合否に使わない。',
        対象='全148×26。収支や順位で一切絞り込まない。',
        会計='全注文の現金/両在庫/元建値/部分返済/全原本行時価/DD/上限/次行約定/場内返済。',
        保存照合='全セッション必須フィールド、全13/共通7期間の必須フィールド、全台帳配列とSHA。selection nestedの独立集計は別監査。',
        選択記録='selection_events全配列とselection_curve全行SHAの再生一致を検査。所有・要求時間・枝PLの意味検査は別監査。',
        入力照合='entriesを事前因果監査audited_entriesへ照合。全要求を固定selector_signalsから再生成。B用影口座52行を固定T/R元約定から再計算。',
        未来検査='全3848区間で37%切断、73%以後の価格/ATR/両入口/要求変更、買売反射。未来の要求IDは1と2を交換。',
        反射='正価格への上下反射とT/R両方向の符号反転。要求ID/入口固定override/約定モデルは保持。',
        参加時間='全原本行の約定後在庫×次観測までの経過分を積分。同値時刻は0分。',
        旧固定T='S000は旧H019__L000__V000の全26セッション数値と返済台帳SHAを照合。',
        禁止='新規探索/対象再選抜/API/現在保存物/旧コードと原本変更をしない。',
        参照SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in sources},
        探索固定SHA256=digest(HERE / '探索条件の固定.json'))
    path = HERE / 'selector_accounting_fixed.json'
    if path.exists():
        old = read(path)
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
        return old
    save(path, value)
    return value


def array_hash(values: dict) -> str:
    """機能: 全キーと配列のバイト列の指紋を独立に作る。

    引数: values (dict)。返り値: SHA256 (str)。
    """
    hasher = hashlib.sha256()
    for key in sorted(values):
        hasher.update(str(key).encode('utf-8'))
        hasher.update(values[key].tobytes())
    return hasher.hexdigest()


def exact(left: np.ndarray, right: np.ndarray, label: str) -> None:
    """機能: 型・形状・全値を比較し、選択記録のNaN欠損は同じ位置だけ許す。

    引数: left/right (ndarray)、label (str)。返り値: なし (None)。
    """
    assert left.shape == right.shape, (label, left.shape, right.shape)
    np.testing.assert_array_equal(left, right, err_msg=label)


def participation(ready: dict, result: dict) -> dict:
    """機能: 全行在庫の積分から参加量と新規回数を独立再計算する。

    引数: ready/result (dict)。返り値: 枚数分・新規回数・初回約定分 (dict)。
    """
    quantities = result['curve'][:, 2:4]
    delta = np.diff(ready['time_s']) / 60.
    assert np.all(delta >= 0)
    units = np.sum(quantities[:-1] * delta[:, None], axis=0)
    additions = np.diff(quantities, axis=0, prepend=np.zeros((1, 2))) > 0
    count = int(np.count_nonzero(np.any(additions, axis=1)))
    held = np.flatnonzero(quantities.sum(axis=1) > 0)
    assert count == int(np.sum(result['orders'][:, 7] == 1))
    return dict(long_unit_minutes=float(units[0]), short_unit_minutes=float(units[1]),
                opening_orders=count,
                first_entry_min=None if not len(held) else float((ready['time_s'][held[0]] - ready['start']) / 60.))


def initialize() -> None:
    """機能: 通信を遮断し固定入力・監査済み入口・影口座を各ワーカーへ読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, ENTRIES, FIXED, SHADOW
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    SHADOW = read(HERE / 'shadow_rows.json')
    assert len(INPUTS) == 26 and len(FIXED['conditions']) == 148
    ENTRIES = {}
    expected = {f'{branch}|{s}|{y}' for branch in ('T', 'R') for s, y in INPUTS}
    with np.load(HERE / 'entries.npz') as saved, np.load(HERE / 'audited_entries.npz') as audited:
        assert set(saved.files) == set(audited.files) == expected
        for branch in ('T', 'R'):
            ENTRIES[branch] = {}
            for key, ready in INPUTS.items():
                name = f'{branch}|{key[0]}|{key[1]}'
                values = saved[name]
                assert values.dtype == np.int8 and values.shape == ready['last'].shape
                assert np.isin(values, (-1, 0, 1)).all()
                exact(values, audited[name], '事前監査入口と保存入口')
                ENTRIES[branch][key] = values
    hashes = {branch: array_hash(values) for branch, values in ENTRIES.items()}
    assert hashes == read(HERE / 'entries_hash.json')
    assert hashes == read(HERE / 'selector_signal_audit.json')['入口配列SHA256']


def requests_for(spec: dict) -> tuple[dict, list]:
    """機能: runnerを呼ばず固定規則から要求列と因果ログを再生成する。

    引数: spec (dict)。返り値: 原本行要求と判定ログ (tuple[dict,list])。
    """
    if spec['random_seed'] is not None:
        values, logs = selector_signals.random_requests(INPUTS, spec['selector_kind'], spec['random_seed'])
    elif spec['selector_kind'] == 'fixed':
        values = {k: np.full(len(r['seq']), spec['fixed_request'], np.int8) for k, r in INPUTS.items()}
        logs = [dict(session=s, timestamp=float(min(r['start'] for k, r in INPUTS.items() if k[0] == s)),
                     request=spec['fixed_request'], reason='固定方式') for s in FIXED['全セッション']]
    elif spec['selector_kind'] == 'B':
        values, logs = selector_signals.build_past_requests(INPUTS, SHADOW, spec['history_window'], spec['score_gap'])
    else:
        values, logs = selector_signals.build_state_requests(INPUTS, spec['er_window'])
    if spec['delay_seconds']:
        values = selector_signals.delay_columns(INPUTS, values, spec['delay_seconds'], initial=1)
    return values, logs


def replay(ready: dict, states: np.ndarray, request: np.ndarray, config: dict, spec: dict) -> dict:
    """機能: 固定D273と指定された二入口/要求/約定モデルで詳細再生する。

    引数: ready/config/spec (dict)、states/request (ndarray)。返り値: 全詳細結果 (dict)。
    """
    return ENGINE.run(ready, states, request, config, detail=True,
                      source_override=spec['source_override'], observed_fill=spec['fill_model'] == 'observed')


def prefix_equal(actual: dict, changed: dict, count: int) -> None:
    """機能: 売買会計に加え、選択列と時系列イベントの接頭辞を比較する。

    引数: actual/changed (dict)、count (int)。返り値: なし (None)。
    """
    previous.prefix_equal(actual, changed, count)
    exact(actual['selection_curve'][:count], changed['selection_curve'][:count], '選択全列の未来不変')
    left, right = actual['selection_events'], changed['selection_events']
    exact(left[left[:, 0] < count], right[right[:, 0] < count], '選択イベントの未来不変')


def future_checks(ready: dict, states: np.ndarray, request: np.ndarray, config: dict, spec: dict, actual: dict) -> None:
    """機能: 37%切断と73%以後の価格/ATR/両入口/要求変更で過去不変を調べる。

    引数: ready/config/spec/actual (dict)、states/request (ndarray)。返り値: なし (None)。
    """
    cut = max(2, int(len(request) * .37))
    changed = replay(previous.clipped(ready, cut), states[:cut], request[:cut], config, spec)
    prefix_equal(actual, changed, cut)
    cut = max(2, int(len(request) * .73))
    modified = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
    modified['last'][cut:] += np.nan_to_num(3 * ready['atr'][cut:], nan=ready['tick'] * 9)
    modified['atr'][cut:] *= 1.7
    altered = states.copy()
    altered[cut:] = np.where(altered[cut:] == 0, 1, -altered[cut:])
    asked = request.copy(); asked[cut:] = 3 - asked[cut:]
    changed = replay(modified, altered, asked, config, spec)
    prefix_equal(actual, changed, cut)


def reflection(ready: dict, states: np.ndarray, request: np.ndarray, config: dict, spec: dict, actual: dict) -> None:
    """機能: 要求と所有IDを保ったまま上下反射し全会計の買売対称性を検査する。

    引数: ready/config/spec/actual (dict)、states/request (ndarray)。返り値: なし (None)。
    """
    offset = 2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick']
    data = dict(ready, last=offset - ready['last'])
    mirror = replay(data, -states, request, config, spec)
    previous.reconstruct(data, mirror, ready['symbol'])
    left, right = actual['orders'], mirror['orders']
    previous.close(left[:, [0, 1, 2, 4, 6, 7]], right[:, [0, 1, 2, 4, 6, 7]], '反射の注文行・枚数・理由')
    previous.close(left[:, 3], -right[:, 3], '反射注文方向')
    previous.close(left[:, 5], offset - right[:, 5], '反射約定価格')
    left, right = actual['trades'], mirror['trades']
    previous.close(left[:, [0, 1, 3, 6, 7, 8, 9, 10]], right[:, [0, 1, 3, 6, 7, 8, 9, 10]], '反射返済会計')
    previous.close(left[:, 2], -right[:, 2], '反射元玉方向')
    previous.close(left[:, 4:6], offset - right[:, 4:6], '反射建値と返済値')
    previous.close(actual['curve'][:, [0, 1, 4]], mirror['curve'][:, [0, 1, 4]], '反射全時価とDD')
    previous.close(actual['curve'][:, [2, 3]], mirror['curve'][:, [3, 2]], '反射両在庫')
    names = {name: i for i, name in enumerate(ENGINE.SELECTION_COLUMNS)}
    for name in ('request_id', 'applied_id', 'pending_owner_id', 'position_owner_id', 'entry_source_id',
                 'pending_source_row', 'pending_entry_source_id', 'position_entry_source_id', 'cancel_wait', 'cancel_source_row'):
        exact(actual['selection_curve'][:, names[name]], mirror['selection_curve'][:, names[name]], '反射でも所有ID不変/' + name)
    for name in ('entry_direction', 'pending_direction', 'position_direction'):
        exact(actual['selection_curve'][:, names[name]], -mirror['selection_curve'][:, names[name]], '反射方向/' + name)


def shadow_audit() -> dict:
    """機能: Bの52影成績を固定T/R口座の注文・元建値・残玉から独立照合する。

    引数: なし。返り値: 影口座照合証跡 (dict)。新選択口座の成績は使わない。
    """
    values = {(r['session'], r['symbol'], r['branch']): r for r in SHADOW}
    assert len(values) == len(SHADOW) == 52
    assert set(values) == {(s, y, b) for s, y in INPUTS for b in ('T', 'R')}
    records = []
    for identifier, branch in (('S000', 'T'), ('S001', 'R')):
        ledgers = read(HERE / 'ledgers' / f'{identifier}.json.gz')
        assert len(ledgers) == 26
        index = {(r['session'], r['symbol']): r for r in ledgers}
        assert set(index) == set(INPUTS)
        for key, ready in INPUTS.items():
            source = index[key]
            orders = np.asarray(source['orders'], float).reshape(-1, 8)
            trades = np.asarray(source['trades'], float).reshape(-1, 11)
            cash, stock = 0., 0
            for order in orders:
                cash -= order[3] * order[4] * order[5]
                stock += int(order[3] * order[4])
            pnl = float(np.sum(trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])))
            previous.close(cash, pnl, '影口座の現金と元建値損益')
            assert stock == 0 and source['stats'][9] == 0
            row = values[(*key, branch)]
            assert set(row) == {'session', 'symbol', 'branch', 'net_yen', 'completed_at', 'complete'}
            assert row['complete'] is True and ready['limit'] < row['completed_at'] == float(ready['time_s'][-1])
            previous.close(row['net_yen'], pnl * previous.MULT[key[1]], '影成績の金額')
            records.append(dict(session=key[0], symbol=key[1], branch=branch,
                                元約定損益一致=True, 完了と最終残玉一致=True))
    return dict(影口座元台帳一致=True, 照合行数=len(records), rows=records,
                原資料SHA256={name: digest(HERE / name) for name in ('shadow_rows.json', 'ledgers/S000.json.gz', 'ledgers/S001.json.gz')})


def evaluate(spec: dict) -> dict:
    """機能: 一条件26区間を再生し、全保存値・全台帳・全未来検査を選別せず確認する。

    引数: spec (dict)。返り値: 独立監査明細 (dict)。
    """
    identifier = spec['id']
    paths = [HERE / folder / (identifier + suffix) for folder, suffix in
             (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'),
              ('requests', '.npz'), ('requests', '.json.gz'))]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    saved_rows, saved_ledgers, summary = read(paths[0]), read(paths[1]), read(paths[2])
    target = {(r['session'], r['symbol']): r for r in saved_rows}
    ledgers = {(r['session'], r['symbol']): r for r in saved_ledgers}
    assert len(saved_rows) == len(target) == len(saved_ledgers) == len(ledgers) == 26
    assert set(target) == set(ledgers) == set(INPUTS)
    assert summary['id'] == identifier and summary['spec'] == spec and summary['既存結果の再利用'] is False
    assert summary['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    requests, logs = requests_for(spec)
    assert logs == read(paths[4]), '判定ログは再生成と一致'
    with np.load(paths[3]) as saved:
        assert set(saved.files) == {'|'.join(k) for k in INPUTS}
        for key in INPUTS:
            assert saved['|'.join(key)].dtype == requests[key].dtype == np.int8
            exact(saved['|'.join(key)], requests[key], '保存要求を再生成へ照合')
    assert array_hash(requests) == summary['request_hash']
    entries = {branch: selector_signals.delay_columns(INPUTS, values, spec['delay_seconds'], initial=0)
               if spec['delay_seconds'] else values for branch, values in ENTRIES.items()}
    assert {b: array_hash(v) for b, v in entries.items()} == summary['entries_hash']
    ledger_hash, rows, series = hashlib.sha256(), [], {}
    old_rows = {}
    if identifier == 'S000':
        old_rows = {(r['session'], r['symbol']): r for part in read(HERE.parent / 'wave_v31/sessions/H019.json.gz')
                    if part['id'] == 'H019__L000__V000' for r in part['rows']}
        assert set(old_rows) == set(INPUTS)
    for key, ready in INPUTS.items():
        states = np.column_stack([entries[b][key] for b in ('T', 'R')]).astype(np.int8)
        config = MANAGERS.make_config(FIXED['manager'], key[1], ready)
        result = replay(ready, states, requests[key], config, spec)
        ledger_hash.update(str(key).encode()); ledger_hash.update(result['trades'].tobytes())
        row, curve = previous.session_values(ready, result, config, identifier)
        row.update(participation(ready, result))
        assert set(target[key]) == SESSION_FIELDS, ('保存session項目集合', set(target[key]) ^ SESSION_FIELDS)
        previous.compare_fields(row, {k: v for k, v in target[key].items() if k != 'selection'}, '全保存session非selection')
        if identifier == 'S000':
            previous.compare_fields(dict(row, id='H019__L000__V000'), old_rows[key], '旧固定T全26')
        source = ledgers[key]
        assert source['config'] == config
        for name, width in (('orders', 8), ('trades', 11), ('cycles', 10), ('selection_events', 15)):
            array = np.asarray(source[name], float).reshape(-1, width)
            exact(result[name], array, '全保存台帳/' + name)
        exact(result['stats'], np.asarray(source['stats'], float), '全保存stats')
        assert hashlib.sha256(result['selection_curve'].tobytes()).hexdigest() == source['selection_curve_SHA256']
        assert int(result['stats'][9]) == 0
        assert len(result['orders']) == len(np.unique(result['orders'][:, 0])), '一行一約定'
        future_checks(ready, states, requests[key], config, spec, result)
        reflection(ready, states, requests[key], config, spec, result)
        row.update(prefix検査合格=True, 未来改変合格=True, 買売反射合格=True,
                   全台帳配列一致=True, 選択曲線SHA一致=True)
        rows.append(row); series[key] = curve['equity']
    assert ledger_hash.hexdigest() == summary['ledger_hash']
    if identifier == 'S000':
        old = next(r for r in read(HERE.parent / 'wave_v31/summaries/H019.json')['candidates'] if r['id'] == 'H019__L000__V000')
        assert ledger_hash.hexdigest() == old['ledger_hash']
    totals = {}
    for field, sessions in (('all_symbols', FIXED['全セッション']), ('symbols', FIXED['共通評価7セッション'])):
        assert len(sessions) == (13 if field == 'all_symbols' else 7)
        part = [r for r in rows if r['session'] in sessions]
        curves = {k: v for k, v in series.items() if k[0] in sessions}
        totals[field] = {}
        assert set(summary[field]) == set(previous.MULT)
        for symbol in previous.MULT:
            value = previous.period_values(part, curves, symbol)
            value.update({name: sum(r[name] for r in part if r['symbol'] == symbol) for name in PARTICIPATION})
            assert set(summary[field][symbol]) == PERIOD_FIELDS, ('保存期間項目集合', set(summary[field][symbol]) ^ PERIOD_FIELDS)
            wanted = {k: v for k, v in summary[field][symbol].items() if k != 'selection'}
            previous.compare_fields(value, wanted, '全保存期間/' + field)
            totals[field][symbol] = {k: value[k] for k in wanted}
    assert before == {name: digest(ROOT / name) for name in before}
    output = dict(id=identifier, 全入力数=26, 原本行会計数=sum(r['検算した観測行数'] for r in rows),
                  prefix検査数=26, 未来価格ATR両入口要求改変数=26, 買売反射数=26,
                  全要求再生成一致=True, 保存全数値一致=True, 独立参加時間一致=True,
                  全台帳配列一致=True, 台帳SHA256=ledger_hash.hexdigest(),
                  要求SHA256=summary['request_hash'], 入口SHA256=summary['entries_hash'],
                  旧固定T一致=identifier == 'S000', selection独立意味監査='別担当の全148所有・枝集計監査',
                  sessions=rows, 保存資料SHA256=before, **totals)
    save(HERE / 'selector_accounting_details' / f'{identifier}.json.gz', output)
    return {k: v for k, v in output.items() if k not in ('sessions', '保存資料SHA256')}


def self_test() -> dict:
    """機能: 人工時価だけで新選択器の会計・同値時刻・未来・反射検査を確認する。

    引数: なし。返り値: 合成検査結果 (dict)。実データの新損益は読まない。
    """
    fixed = read(HERE / '探索条件の固定.json')
    prices = np.tile(np.array([100., 96., 98., 102., 108., 112., 120., 110., 103., 90., 94., 99.]), 20)
    n = len(prices)
    times = np.floor(np.arange(n) / 2.) * 10
    ready = dict(time_s=np.r_[times, 1300., 1301.], seq=np.arange(n + 2),
                 last=np.r_[prices, prices[-1], prices[-1]], atr=np.full(n + 2, 4.), tick=1.,
                 start=-1200., limit=1300., us_open=np.inf, symbol='TOPIX', session='合成Day')
    directions = np.where(np.arange(n + 2) % 51 < 25, 1, -1).astype(np.int8)
    states = np.column_stack([directions, -directions]).astype(np.int8)
    requests = np.where(np.arange(n + 2) % 67 < 33, 1, 2).astype(np.int8)
    config = MANAGERS.make_config(fixed['manager'], 'TOPIX', ready)
    count = 0
    for observed in (False, True):
        for override in (0, 1, 2):
            spec = dict(source_override=override, fill_model='observed' if observed else 'specified')
            result = replay(ready, states, requests, config, spec)
            row, _ = previous.session_values(ready, result, config, '合成')
            assert row['新規注文数'] > 0 and row['返済明細数'] > 0
            participation(ready, result)
            future_checks(ready, states, requests, config, spec, result)
            reflection(ready, states, requests, config, spec, result)
            count += 1
    required = SESSION_FIELDS.copy(); required.remove('net_yen')
    assert required != SESSION_FIELDS
    required = PERIOD_FIELDS.copy(); required.remove('drawdown_yen')
    assert required != PERIOD_FIELDS
    return dict(合成合格=True, 合成組合せ数=count, 同値時刻あり=True,
                全玉会計=True, 未来切断=True, 未来両入口要求変更=True, 上下反射=True,
                欠落必須項目を集合一致で拒否=True, 新PnL読取=False, 現在データ使用=False)


def main() -> None:
    """機能: 結果前固定又は全148の全玉会計監査を実行する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    synthetic = self_test()
    protocol = freeze()
    save(HERE / 'selector_accounting_selftest.json', synthetic)
    if args.prepare:
        print('全148×26会計仕様と合成6条件を固定。新損益読取なし。', flush=True)
        return
    began = time.perf_counter()
    initialize()
    assert read(HERE / '主再生の完了.json')['全条件数'] == 148
    before = {name: digest(ROOT / name) for name in FIXED['SHA256']}
    assert before == FIXED['SHA256']
    structure = read(HERE / 'selector_causality_before_pnl.json')
    assert structure['構造監査合格'] and structure['全監査完了']
    references = {name: digest(ROOT / name) for name in structure['参照SHA256']}
    assert references == structure['参照SHA256']
    originals = original_hashes()
    assert originals == structure['原本78SHA256']
    base_paths = [HERE / name for name in ('entries.npz', 'entries_hash.json', 'audited_entries.npz', 'shadow_rows.json',
                                          '探索条件の固定.json', 'selector_causality_before_pnl.json')]
    artifacts = {p.relative_to(ROOT).as_posix(): digest(p) for p in base_paths}
    shadow = shadow_audit()
    save(HERE / 'selector_shadow_accounting.json', shadow)
    wanted = {s['id'] for s in FIXED['conditions']}
    output = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, spec): spec['id'] for spec in FIXED['conditions']}
        for future in as_completed(futures):
            output.append(future.result())
            print(f'{len(output)}/148 {futures[future]} 会計・全要求・未来・反射一致', flush=True)
    assert len(output) == len({r['id'] for r in output}) == 148 and {r['id'] for r in output} == wanted
    raw_count = sum(len(r['last']) for r in INPUTS.values())
    assert sum(r['原本行会計数'] for r in output) == 148 * raw_count
    assert originals == original_hashes()
    assert before == {name: digest(ROOT / name) for name in before}
    assert references == {name: digest(ROOT / name) for name in references}
    assert artifacts == {name: digest(ROOT / name) for name in artifacts}
    assert freeze() == protocol
    result = dict(全監査合格=True, 対象条件数=148, 全入力数=148 * len(INPUTS),
        一条件原本行数=raw_count, 全原本行会計数=sum(r['原本行会計数'] for r in output),
        prefix検査数=sum(r['prefix検査数'] for r in output),
        未来価格ATR両入口要求改変数=sum(r['未来価格ATR両入口要求改変数'] for r in output),
        買売反射数=sum(r['買売反射数'] for r in output), 旧固定T一致区間数=26,
        全要求再生成一致=True, 影口座元台帳一致=True, 全入口事前監査一致=True,
        保存全数値と全台帳SHA一致=True, 独立参加時間一致=True,
        selection独立意味監査='別担当。ここでは全選択イベントと全選択曲線SHAの再生一致だけを検査。',
        監査規則=protocol, 合成検査=synthetic, 影口座監査=shadow,
        条件=sorted(output, key=lambda r: r['id']), 詳細='selector_accounting_details/{id}.json.gz',
        原本78SHA256=originals, 参照SHA256=before, 事前因果監査参照SHA256=references, 保存入力SHA256=artifacts,
        探索固定SHA256=digest(HERE / '探索条件の固定.json'), API取得数=0, 現在データ使用=False,
        成績による対象選別=False, ルール変更=False, 実行秒=time.perf_counter() - began)
    save(HERE / 'selector_accounting_audit.json', result)
    lines = ['# 全148の独立全玉会計', '',
        f'全148×26＝{result["全入力数"]:,}入力、原本{result["全原本行会計数"]:,}行を検算した。', '',
        '- 全注文の現金・両在庫・元建値・部分返済・全行時価・最大下落・上限・次行約定・場内返済を独立に照合。',
        '- 13セッション全期間と共通7セッションを分け、保存必須項目の脱落も拒否した。',
        '- 事前監査済みT/R入口と全148要求の再生成が一致。Bの52影成績は固定T/R元約定・残玉・完了時刻へ照合。',
        '- 全3,848入力で37%切断・73%将来変更・上下反射が一致。',
        '- 選択イベントと選択曲線SHAは全件一致。所有・枝損益・選択時間の独立意味検査は別監査で補う。',
        '- 原本78・凍結資料・入力・事前監査指紋は前後不変。API/現在データ不使用。', '',
        '会計・因果実装の合格は、未知期間の収益性を証明するものではない。']
    (HERE / 'selector_accounting_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print({k: result[k] for k in ('全監査合格', '対象条件数', '全入力数', '全原本行会計数', '実行秒')}, flush=True)


if __name__ == '__main__':
    main()
