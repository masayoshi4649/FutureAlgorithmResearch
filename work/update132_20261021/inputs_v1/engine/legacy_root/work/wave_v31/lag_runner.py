"""旧84方式に5つの鮮度対照を同じ注文器で適用し、全420を保存する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import argparse
import hashlib
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v23'
BASE = HERE.parent / 'wave_v30'
sys.path.insert(0, str(BASE))
import context_split_runner as previous
sys.path.insert(0, str(HERE))
import lag_design

save, read, digest = previous.save, previous.read, previous.digest
diagnostics, failures = previous.diagnostics, previous.failures
engine, managers, research = previous.engine, previous.managers, previous.research
INPUTS, FIXED = {}, {}


def worker_init() -> None:
    """機能: 固定された入力と全対照条件を子処理へ読み込む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')


def array_digest(arrays: dict) -> str:
    """機能: セッション・銘柄順に配列の内容指紋を作る。

    引数: arrays (dict)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    for key in sorted(arrays):
        value.update(str(key).encode())
        value.update(arrays[key].tobytes())
    return value.hexdigest()


def participation(result: dict, ready: dict) -> dict:
    """機能: 全返済の新規・返済時刻から、買売別の枚数分を集計する。

    引数: result/ready (dict)。返り値: 部分返済を含む保有参加量 (dict)。
    """
    totals = {1: 0., -1: 0.}
    for trade in result['trades']:
        duration = (ready['time_s'][int(trade[7])] - ready['time_s'][int(trade[6])]) / 60.
        totals[int(trade[2])] += duration * int(trade[3])
    opening = result['orders'][result['orders'][:, 7] == 1]
    return {'long_unit_minutes': totals[1], 'short_unit_minutes': totals[-1],
            'opening_orders': len(opening),
            'first_entry_min': None if len(opening) == 0 else float((ready['time_s'][int(opening[0, 0])] - ready['start']) / 60.)}


def evaluate(spec: dict) -> dict:
    """機能: 一入口の7管理×5変形を全原本行で再生し、既存結果を再利用せず保存する。

    引数: spec (dict)。返り値: 35条件の保存集計 (dict)。
    """
    started, identifier = time.perf_counter(), spec['id']
    raw = []
    for folder in ('directions', 'contexts', 'contexts_own'):
        with np.load(BASE / folder / f'{identifier}.npz') as archive:
            raw.append({k: archive[f'{k[0]}|{k[1]}'] for k in INPUTS})
    old = {c['id']: c for c in read(BASE / 'summaries' / f'{identifier}.json')['candidates']}
    old_sessions = {c['id']: c['rows'] for c in read(BASE / 'sessions' / f'{identifier}.json.gz')}
    output, all_rows, fingerprints, compatibility = [], [], {}, []
    for variant in FIXED['variants']:
        arrays = [{}, {}, {}]
        for key, ready in INPUTS.items():
            transformed = lag_design.transform(ready['time_s'], *(a[key] for a in raw), variant)
            for i in range(3):
                arrays[i][key] = transformed[i]
        for folder, values in zip(('directions', 'contexts', 'contexts_own'), arrays):
            np.savez_compressed(HERE / folder / f"{identifier}__{variant['id']}.npz",
                                **{f'{k[0]}|{k[1]}': v for k, v in values.items()})
        fingerprints[variant['id']] = [array_digest(a) for a in arrays]
        for management in FIXED['managers']:
            base_id = identifier + '__' + management['id']
            name = base_id + '__' + variant['id']
            source = management['context_source']
            context = {'entry': None, 'main': arrays[1], 'own': arrays[2]}[source]
            ledger_hash, rows = hashlib.sha256(), []
            for key, ready in INPUTS.items():
                config = managers.make_config(management, key[1], ready)
                result = engine.run(ready, arrays[0][key], config, detail=False,
                                    context=None if context is None else context[key])
                ledger_hash.update(str(key).encode())
                ledger_hash.update(result['trades'].tobytes())
                row = research.summarize(result, config, key[1], key[0], name)
                row['two_largest_cycle_profits'] = sorted(
                    [float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
                if variant['id'] == 'V000':
                    reference = next(r for r in old_sessions[base_id] if r['session'] == key[0] and r['symbol'] == key[1])
                    assert {k: v for k, v in row.items() if k != 'id'} == {k: v for k, v in reference.items() if k != 'id'}
                row.update(participation(result, ready))
                rows.append(row)
            symbols = diagnostics(rows)
            for symbol in ('TOPIX', 'NK225'):
                if variant['id'] == 'V000':
                    assert symbols[symbol] == old[base_id]['symbols'][symbol]
                for key in ('long_unit_minutes', 'short_unit_minutes', 'opening_orders'):
                    symbols[symbol][key] = sum(r[key] for r in rows if r['symbol'] == symbol)
            if variant['id'] == 'V000':
                assert ledger_hash.hexdigest() == old[base_id]['ledger_hash']
                compatibility.append(base_id)
            output.append({'id': name, 'base_id': base_id, 'signal_id': identifier,
                           'manager_id': management['id'], 'variant_id': variant['id'],
                           'signal_family': spec['family'], 'manager_family': management['family'],
                           'symbols': symbols, 'failures': failures(symbols), 'ledger_hash': ledger_hash.hexdigest()})
            all_rows.append({'id': name, 'rows': rows})
    output.sort(key=lambda c: c['id'])
    all_rows.sort(key=lambda c: c['id'])
    save(HERE / 'sessions' / f'{identifier}.json.gz', all_rows)
    summary = {'signal': spec, 'array_hashes': fingerprints,
               'candidates': output, '旧管理の全数値と台帳一致': compatibility,
               'elapsed_seconds': time.perf_counter() - started,
               '探索固定SHA256': digest(HERE / '探索条件の固定.json'), '既存結果の再利用': False}
    save(HERE / 'summaries' / f'{identifier}.json', summary)
    return summary


def prepare() -> dict:
    """機能: 新しい損益の前に、全420条件と読取り元・実装の指紋を固定する。

    引数: なし。返り値: 固定仕様 (dict)。旧作業の仕様も先に検査する。
    """
    for folder in ('directions', 'contexts', 'contexts_own', 'sessions', 'summaries'):
        (HERE / folder).mkdir(exist_ok=True)
    old = read(BASE / '探索条件の固定.json')
    for name, expected in old['SHA256'].items():
        assert digest(HERE.parent / name) == expected
    path = HERE / '探索条件の固定.json'
    if not path.exists():
        files = [Path(__file__), HERE / 'lag_design.py', HERE / 'freshness_diagnostic_fixed.json',
                 BASE / 'context_split_runner.py', BASE / '探索条件の固定.json',
                 HERE.parent / 'wave_v28/engine_context.py',
                 OLD / 'inputs.pkl', OLD / 'features_depth.pkl', OLD / 'engine.py',
                 OLD / 'managers.py', OLD / 'research.py', HERE.parent / 'wave_v25/discovery_runner.py']
        for spec in old['signals']:
            files += [BASE / folder / (spec['id'] + extension) for folder, extension in
                      [('directions', '.npz'), ('contexts', '.npz'), ('contexts_own', '.npz'),
                       ('sessions', '.json.gz'), ('summaries', '.json')]]
        save(path, {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
             'signals': old['signals'], 'own_signals': old['own_signals'], 'managers': old['managers'],
             'variants': lag_design.catalog(), '全組合せ数': 420, '元条件数': 84, '新補助対照数': 336,
             '用途': '情報の鮮度と開始待ちを分ける診断。新候補の選択ではない。最良遅延へ差替禁止。',
             '価格とATR': '遅延させない。現在行までに公開されたATRと価格を従来通り注文器へ渡す。',
             'Wの意味': '同セッション・銘柄の遅延入口が初めて非0になった現在行から解放する累積フラグ。約定開始・活動時間・方向・保有時間はVと同一ではない。',
             '執行': '費用０、指定価格約定、初回TOPIX5枚/NK10枚、片方向上限10/20枚、全玉場内返済。',
             '原本行': '同値時刻は原本行順。V000はidentity、正の遅延は同セッション内の過去時刻asof、先頭不足は0。',
             '現在データ': '追加API取得・既存現在snapshot読取も再生も禁止。',
             '再現': '既存集計のcacheを再利用せず、毎回全420を元入力から計算する。',
             'SHA256': {p.relative_to(HERE.parent).as_posix(): digest(p) for p in files}})
    fixed = read(path)
    for name, expected in fixed['SHA256'].items():
        assert digest(HERE.parent / name) == expected, f'固定後の変更: {name}'
    return fixed


def main() -> None:
    """機能: 結果前監査の後だけ、全420の鮮度対照を保存する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。採否や順位は決めない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=12)
    args = parser.parse_args()
    fixed = prepare()
    if args.prepare:
        print('全84×5=420対照を結果前固定', flush=True)
        return
    assert (HERE / 'lag_causality_before_pnl.json').exists(), '損益前の遅延因果監査を必要とする'
    started, results = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
        pending = [pool.submit(evaluate, spec) for spec in fixed['signals']]
        for future in as_completed(pending):
            value = future.result()
            results.append(value)
            print(f"{len(results)}/12 {value['signal']['id']} 完了", flush=True)
    candidates = sorted([c for result in results for c in result['candidates']], key=lambda c: c['id'])
    assert len(candidates) == 420 and len({c['id'] for c in candidates}) == 420
    save(HERE / '全条件の期間集計.json.gz', candidates)
    save(HERE / '主再生の完了.json', {'全条件数': 420, '全入力数': 420 * 26,
         'V000旧84一致': all(len(r['旧管理の全数値と台帳一致']) == 7 for r in results),
         '経過秒': time.perf_counter() - started, '現在データ使用': False, 'API取得数': 0,
         '新候補選抜': False, '既存結果の再利用': False,
         '用途': '元84と補助336を全件診断。独立した420相場や420発見仮説ではない。'})
    print('全420対照完了。最良遅延の選抜はしません。', flush=True)


if __name__ == '__main__':
    main()
