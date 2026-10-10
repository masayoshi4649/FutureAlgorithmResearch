"""全84条件を選別せず、全玉会計と二入力の因果性を独立に検査する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
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

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD, V28, V29 = (HERE.parent / name for name in ('wave_v23', 'wave_v28', 'wave_v29'))
for folder in (OLD, V28, V29):
    sys.path.insert(0, str(folder))
from selected_accounting_audit import reconstruct, clipped, prefix_equal, close
import engine_context as ENGINE
import managers
sys.path.insert(0, str(HERE))
from context_structure_audit import read, save, digest, original_hashes, reject_network

INPUTS, FIXED = {}, {}
MULT = {'TOPIX': 1000., 'NK225': 10.}


def freeze() -> dict:
    """機能: 全件会計と各1点の未来検査を結果選別なしで固定する。

    引数: なし。返り値: 監査規則 (dict)。
    """
    rules = {'対象': '12入口×7管理の全84。最低基準・順位・一次反証を参照して対象を減らさない。',
             '入力源': 'entry=None、main=contexts/H、own=contexts_own/H。通常importの凍結v28 engine_contextを使う。',
             '会計': 'v29の独立reconstructを読取り再利用。注文現金・両在庫・元建値・全返済・全原本時価・DD・上限・場内完結を検査。',
             '保存値': 'セッション全フィールドを独立に再計算。Rは記録ATR×初回枚数×固定損切り幅と照合。期間全数値・None比率・全返済台帳SHAも比較する。',
             '未来検査': '全2184入力で37%位置を切断、別の73%位置以後の価格/ATR/入口/選択contextを改変。前部分の注文/全返済/全時価が一致。',
             '上下反射': '全2184入力で正価格に反射し、入口と実際の保有contextをともに反転。価格・時刻・枚数・損益・理由を比較する。',
             '独立性': '監査helperの旧ソースは変更しない。新規ルール、現在データ、追加API、対象再選抜を使わない。',
             '範囲': '注文会計の全件検査。信号生成自体のprefix/未来相手変更/反射はcontext_structure_before_pnlの全12監査で補う。'}
    record = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 規則=rules,
                  コードSHA256=digest(Path(__file__)), helperSHA256=digest(V29 / 'selected_accounting_audit.py'),
                  探索固定SHA256=digest(HERE / '探索条件の固定.json'))
    path = HERE / 'all_accounting_fixed.json'
    if path.exists():
        previous = read(path)
        assert {k: v for k, v in previous.items() if k != '固定日時'} == {k: v for k, v in record.items() if k != '固定日時'}
        return previous
    save(path, record)
    return record


def ratio(a: float, b: float) -> float | None:
    """機能: 保存仕様と同じゼロ分母の意味で独立比率を作る。

    引数: a/b (float)。返り値: 比率又は欠損 (float|None)。
    """
    return a / b if b > 1e-8 else None


def compare_fields(actual: dict, expected: dict, label: str) -> None:
    """機能: 保存フィールドを残さず照合し、欠損と非有限値を区別する。

    引数: actual/expected (dict)、label (str)。返り値: なし (None)。
    """
    assert set(expected) <= set(actual), (label, set(expected) - set(actual))
    for name, target in expected.items():
        value = actual[name]
        if target is None or value is None:
            assert value is target, (label, name, value, target)
        elif isinstance(target, (int, float, list)):
            assert np.isfinite(np.asarray(target, float)).all() and np.isfinite(np.asarray(value, float)).all()
            close(value, target, label + '/' + name)
        else:
            assert value == target, (label, name)


def session_values(ready: dict, result: dict, config: dict, identifier: str) -> tuple[dict, dict]:
    """機能: 全注文会計に加え、保存セッション表の残りの数値を元約定から再計算する。

    引数: ready/result/config (dict)、identifier (str)。返り値: 独立セッション値と曲線 (tuple[dict,dict])。
    """
    symbol = ready['symbol']
    row, series = reconstruct(ready, result, symbol)
    pnl = defaultdict(float)
    for trade in result['trades']:
        pnl[int(trade[0])] += float(trade[2] * trade[3] * (trade[5] - trade[4]))
    cycle_values, normalized = [], []
    for cycle in result['cycles']:
        value = pnl[int(cycle[0])]
        close(value, cycle[3], '組の損益を元建値から再計算')
        risk = config['initial_qty'] * config['stop_atr'] * cycle[5]
        assert cycle[5] >= ready['tick'] * 2 - 1e-9 and risk > 0
        close(risk, cycle[4], '初回枚数と固定ATRからRを再計算')
        normalized.append(value / risk)
        cycle_values.append(value * MULT[symbol])
    streak = longest = 0
    for value in cycle_values:
        streak = streak + 1 if value < 0 else 0
        longest = max(streak, longest)
    assert config['reverse_mode'] == config['add_mode'] == config['hedge_ratio'] == 0
    assert not np.any(np.isin(result['orders'][:, 6], (21, 22, 23)))
    row.update(id=identifier, net_r=float(sum(normalized)), reversals=0, longest_losing_streak=longest,
               maximum_trade_profit=max([0.] + cycle_values), maximum_trade_loss=min([0.] + cycle_values),
               two_largest_cycle_profits=sorted([v for v in cycle_values if v > 0], reverse=True)[:2])
    return row, series


def period_values(rows: list[dict], series: dict, symbol: str) -> dict:
    """機能: セッション値と全時価から保存期間表の全指標を独立に再集計する。

    引数: rows (list[dict])、series (dict)、symbol (str)。返り値: 期間指標 (dict)。
    """
    own = [r for r in rows if r['symbol'] == symbol]
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units',
              'cycles', 'cycle_wins', 'cycle_losses', 'cycle_profit_yen', 'cycle_loss_yen', 'net_r', 'closed_units')
    result = {field: sum(r[field] for r in own) for field in fields}
    bank = high = dd = 0.
    for key in sorted(key for key in series if key[1] == symbol):
        curve = series[key] * MULT[symbol] + bank
        highest = np.maximum.accumulate(np.maximum(high, curve))
        dd = max(dd, float(np.max(highest - curve)))
        bank, high = float(curve[-1]), float(highest[-1])
    best = max(own, key=lambda r: r['net_yen'])
    trimmed = [r for r in own if r is not best]
    days = defaultdict(float)
    for row in own:
        days[row['session'][:10]] += row['net_yen']
    result.update(money_ratio=ratio(result['gross_profit_yen'], result['gross_loss_yen']),
                  cycle_ratio=ratio(result['cycle_profit_yen'], result['cycle_loss_yen']),
                  win_sessions=sum(r['net_yen'] > 0 for r in own), active_sessions=sum(r['cycles'] > 0 for r in own),
                  worst_session=min(r['net_yen'] for r in own), drawdown_yen=dd,
                  best_removed_net=sum(r['net_yen'] for r in trimmed),
                  best_removed_pf=ratio(sum(r['cycle_profit_yen'] for r in trimmed), sum(r['cycle_loss_yen'] for r in trimmed)),
                  best_trade_removed_net=result['net_yen'] - max(r['maximum_trade_profit'] for r in own),
                  max_long=max(r['max_long'] for r in own), max_short=max(r['max_short'] for r in own),
                  longest_losing_streak=max(r['longest_losing_streak'] for r in own), session_count=len(own),
                  average_unit_payoff=ratio(result['gross_profit_yen'] / result['profit_units'],
                      result['gross_loss_yen'] / result['loss_units']) if result['profit_units'] and result['loss_units'] else None,
                  day_net=sum(r['net_yen'] for r in own if r['session'].endswith('Day')),
                  night_net=sum(r['net_yen'] for r in own if r['session'].endswith('Night')),
                  two_sessions_removed_net=result['net_yen'] - sum(sorted([r['net_yen'] for r in own], reverse=True)[:2]),
                  two_start_days_removed_net=result['net_yen'] - sum(sorted(days.values(), reverse=True)[:2]),
                  two_cycles_removed_net=result['net_yen'] - sum(sorted([v for r in own for v in r['two_largest_cycle_profits']], reverse=True)[:2]),
                  early_week_net=sum(r['net_yen'] for r in own if r['session'] < '2026-09-28'),
                  later_week_net=sum(r['net_yen'] for r in own if r['session'] >= '2026-09-28'))
    return result


def future_checks(ready: dict, entry: np.ndarray, context: np.ndarray | None, cfg: dict, actual: dict) -> None:
    """機能: 全件について37%切断と別点73%将来改変の前部分一致を検査する。

    引数: ready/cfg/actual (dict)、entry (ndarray)、context (ndarray|None)。返り値: なし (None)。
    """
    cut = max(2, int(len(entry) * .37))
    partial = ENGINE.run(clipped(ready, cut), entry[:cut], cfg, True, context=None if context is None else context[:cut])
    prefix_equal(actual, partial, cut)
    cut = max(2, int(len(entry) * .73))
    changed = dict(ready, last=ready['last'].copy(), atr=ready['atr'].copy())
    changed['last'][cut:] += 3 * ready['atr'][cut:]
    changed['atr'][cut:] *= 1.7
    new_entry = entry.copy(); new_entry[cut:] *= -1
    new_context = None if context is None else context.copy()
    if new_context is not None:
        new_context[cut:] = np.where(new_context[cut:] == 0, 1, -new_context[cut:]).astype(np.int8)
    modified = ENGINE.run(changed, new_entry, cfg, True, context=new_context)
    prefix_equal(actual, modified, cut)


def reflection(ready: dict, entry: np.ndarray, context: np.ndarray | None, cfg: dict, actual: dict) -> None:
    """機能: 買売と使用する保有方向を同時反転し全約定と時価の対称性を検査する。

    引数: ready/cfg/actual (dict)、entry (ndarray)、context (ndarray|None)。返り値: なし (None)。
    """
    offset = 2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick']
    data = dict(ready, last=offset - ready['last'])
    mirror = ENGINE.run(data, -entry, cfg, True, context=None if context is None else -context)
    reconstruct(data, mirror, ready['symbol'])
    left, right = actual['orders'], mirror['orders']
    close(left[:, [0, 1, 2, 4, 6, 7]], right[:, [0, 1, 2, 4, 6, 7]], '反射注文の行・枚数・理由')
    close(left[:, 3], -right[:, 3], '反射注文方向')
    close(left[:, 5], offset - right[:, 5], '反射約定価格')
    left, right = actual['trades'], mirror['trades']
    close(left[:, [0, 1, 3, 6, 7, 8, 9, 10]], right[:, [0, 1, 3, 6, 7, 8, 9, 10]], '反射返済全会計')
    close(left[:, 2], -right[:, 2], '反射元建玉方向')
    close(left[:, 4:6], offset - right[:, 4:6], '反射元建値と返済価格')
    close(actual['curve'][:, [0, 1, 4]], mirror['curve'][:, [0, 1, 4]], '反射全時価とDD')
    close(actual['curve'][:, [2, 3]], mirror['curve'][:, [3, 2]], '反射両在庫')


def initialize() -> None:
    """機能: 各ワーカーで通信を拒否し保存原本と固定管理だけを読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    assert len(INPUTS) == 26 and len(FIXED['managers']) == 7


def evaluate(signal_id: str) -> list[dict]:
    """機能: 同じ入口の全7管理を、C/Sの保存列を明示して独立監査する。

    引数: signal_id (str)。返り値: 全7条件の監査結果 (list[dict])。
    """
    paths = [HERE / folder / f'{signal_id}.npz' for folder in ('directions', 'contexts', 'contexts_own')]
    paths += [HERE / 'sessions' / f'{signal_id}.json.gz', HERE / 'summaries' / f'{signal_id}.json']
    hashes = {str(path): digest(path) for path in paths}
    lanes = {}
    for name, path in zip(('entry', 'main', 'own'), paths[:3]):
        with np.load(path) as archive:
            assert set(archive.files) == {'|'.join(key) for key in INPUTS}
            lanes[name] = {key: archive['|'.join(key)] for key in INPUTS}
            assert all(value.dtype == np.int8 and len(value) == len(INPUTS[key]['seq']) for key, value in lanes[name].items())
    stored_rows = {item['id']: item['rows'] for item in read(paths[-2])}
    summary = read(paths[-1])
    stored_summary = {item['id']: item for item in summary['candidates']}
    output = []
    for management in FIXED['managers']:
        identifier = signal_id + '__' + management['id']
        source = management['context_source']
        assert source in ('entry', 'main', 'own')
        expected_rows = {(row['session'], row['symbol']): row for row in stored_rows[identifier]}
        assert len(stored_rows[identifier]) == len(expected_rows) == 26 and set(expected_rows) == set(INPUTS)
        hasher, rows, series = hashlib.sha256(), [], {}
        for key, ready in INPUTS.items():
            entry = lanes['entry'][key]
            context = None if source == 'entry' else lanes[source][key]
            cfg = managers.make_config(management, key[1], ready)
            result = ENGINE.run(ready, entry, cfg, True, context=context)
            hasher.update(str(key).encode()); hasher.update(result['trades'].tobytes())
            row, curve = session_values(ready, result, cfg, identifier)
            compare_fields(row, expected_rows[key], '保存セッション全項目')
            future_checks(ready, entry, context, cfg, result)
            reflection(ready, entry, context, cfg, result)
            rows.append(row); series[key] = curve['equity']
        expected = stored_summary[identifier]
        assert hasher.hexdigest() == expected['ledger_hash']
        aggregate = {symbol: period_values(rows, series, symbol) for symbol in MULT}
        for symbol in MULT:
            assert set(aggregate[symbol]) == set(expected['symbols'][symbol])
            compare_fields(aggregate[symbol], expected['symbols'][symbol], '保存期間全項目')
        output.append(dict(id=identifier, context_source=source, 全入力数=len(rows),
                           原本行会計数=sum(row['検算した観測行数'] for row in rows),
                           prefix検査数=26, 未来価格ATR両入力改変数=26, 買売反射数=26,
                           保存全数値一致=True, 台帳SHA256=hasher.hexdigest(), sessions=rows, symbols=aggregate))
    assert hashes == {str(path): digest(path) for path in paths}
    save(HERE / 'all_accounting_details' / f'{signal_id}.json.gz', dict(全7管理=output, 保存資料SHA256=hashes))
    return output


def self_test() -> dict:
    """機能: 実相場を使わずC/S読み分けと独立会計・未来検査・反射の接続を確認する。

    引数: なし。返り値: 合成検査結果 (dict)。
    """
    from context_structure_audit import ENGINE as expected_engine
    assert ENGINE is expected_engine
    ready = dict(last=np.array([100., 100., 101., 101., 102., 102., 103., 103., 103., 103.]),
                 atr=np.full(10, 2.), time_s=np.arange(10, dtype=float), seq=np.arange(10), tick=1.,
                 start=0., limit=8., us_open=1e9, symbol='TOPIX', session='合成')
    entry = np.ones(10, np.int8)
    main = entry.copy(); main[3:] = 0
    own = entry.copy(); own[4:] = -1
    cfg = dict(managers.BASE, audit_cap=10, point_value=1000., initial_qty=5, entry_mode=2,
               warmup_min=0., entry_cutoff_min=0., cooldown_min=100., stop_atr=20.,
               main_trail=100., activation_atr=100., signal_exit=1, neutral_min=2/60)
    results = []
    for context in (main, own):
        actual = ENGINE.run(ready, entry, cfg, True, context=context)
        row, _ = session_values(ready, actual, cfg, '合成')
        future_checks(ready, entry, context, cfg, actual)
        reflection(ready, entry, context, cfg, actual)
        results.append(actual)
    assert results[0]['trades'][0, 9] == 10 and results[1]['trades'][0, 9] == 13
    return dict(合成C_S別返済=True, 全注文会計=True, 未来切断と将来改変=True, 上下反射=True)


def main() -> None:
    """機能: 全84を無選別で監査し、原本・凍結資料の前後不変を記録する。

    引数: --workers (int)、--prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    protocol = freeze()
    synthetic = self_test()
    save(HERE / 'all_accounting_selftest.json', synthetic)
    if args.prepare:
        print('全84会計・prefix37%・未来改変73%・反射を固定、合成C/S検算合格。', flush=True)
        return
    began = time.perf_counter()
    fixed = read(HERE / '探索条件の固定.json')
    before = {relative: digest(HERE.parent / relative) for relative in fixed['SHA256']}
    assert before == fixed['SHA256']
    originals = original_hashes()
    structure = read(HERE / 'context_structure_before_pnl.json')
    assert structure['構造検査合格'] and structure['実際の保存C_S配列一致数'] == 624
    assert len(fixed['signals']) == 12 and len(fixed['managers']) == 7
    output = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(evaluate, signal['id']): signal['id'] for signal in fixed['signals']}
        for future in as_completed(futures):
            result = future.result(); output.extend(result)
            print(f'{len(output)}/84 {futures[future]} 全7管理の会計・未来・反射一致', flush=True)
    expected = {s['id'] + '__' + m['id'] for s in fixed['signals'] for m in fixed['managers']}
    assert len(output) == 84 and {r['id'] for r in output} == expected
    assert before == {relative: digest(HERE.parent / relative) for relative in before}
    assert originals == original_hashes()
    result = dict(全監査合格=True, 対象条件数=84, 全入力数=sum(r['全入力数'] for r in output),
                  全原本行会計数=sum(r['原本行会計数'] for r in output),
                  prefix検査数=sum(r['prefix検査数'] for r in output),
                  未来価格ATR両入力改変数=sum(r['未来価格ATR両入力改変数'] for r in output),
                  買売反射数=sum(r['買売反射数'] for r in output), 監査規則=protocol, 合成検査=synthetic,
                  条件=[{k: v for k, v in row.items() if k != 'sessions'} for row in sorted(output, key=lambda row: row['id'])],
                  詳細='all_accounting_details/Hxxx.json.gz', 保存全数値と全台帳SHA一致=True,
                  原本78SHA256=originals, 探索固定SHA256=before, 現在データ使用=False, API取得数=0,
                  成績による対象選別=False, ルール変更=False, 実行秒=time.perf_counter() - began)
    save(HERE / 'all_accounting_audit.json', result)
    lines = ['# 全84条件・独立会計と因果性の監査', '',
             f'全84×26＝{result["全入力数"]:,}入力を選別せず監査した。注文から独立再構成した原本行は{result["全原本行会計数"]:,}行。', '',
             '- B0はcontext=None、Cはcontexts、Sはcontexts_ownを明示して読み分けた。入口は全7管理で同じ列。',
             '- 元建値・部分利確・残枚数・損失玉を含む全注文会計、全原本行時価と最大DD、片方向上限、場末全返済、次行以降約定が一致。',
             '- セッション表と期間表の全数値・None比率・返済台帳SHAが一致。Rは記録ATRと初回枚数・固定幅の整合を検査した。',
             f'- 全{result["全入力数"]:,}入力で37%未来切断、別点73%の将来価格/ATR/入口/context改変、上下反射が一致。',
             '- 凍結コード/入力と78原本のSHAは監査前後で不変。旧コード・現在保存物の変更、追加通信、対象再選抜はない。',
             '- 信号そのものの未来足/相手情報/反射は、損益前のcontext_structure_before_pnl監査が補完する。',
             '', 'これは実装・会計・因果性の検査であり、収益性や損失額の無条件保証ではない。全件の明細はall_accounting_detailsに保存した。', '']
    (HERE / 'all_accounting_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    print({key: result[key] for key in ('全監査合格', '対象条件数', '全入力数', '全原本行会計数', '実行秒')}, flush=True)


if __name__ == '__main__':
    main()
