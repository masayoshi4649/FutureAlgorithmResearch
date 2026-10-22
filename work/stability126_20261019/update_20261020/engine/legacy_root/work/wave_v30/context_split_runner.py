"""同じ入口に対する両市場確認・自己方向だけの撤回を全84条件で比較する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import argparse
import hashlib
import os
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / 'wave_v25'
OLD = HERE.parent / 'wave_v23'
SIGNAL_ROOT = HERE.parent / 'wave_v27'
CONTEXT_ROOT = HERE.parent / 'wave_v28'
sys.path.insert(0, str(PREVIOUS))
import discovery_runner as previous
import managers
import research
sys.path.insert(0, str(CONTEXT_ROOT))
import engine_context as engine
sys.path.insert(0, str(HERE))
import context_split_design

save, read, digest = previous.save, previous.read, previous.digest
diagnostics, failures, score = previous.diagnostics, previous.failures, previous.score
INPUTS, MANAGERS, OWN = {}, [], {}


def worker_init() -> None:
    """機能: 子処理へ読取り入力と固定条件を読み込む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, MANAGERS, OWN
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    frozen = read(HERE / '探索条件の固定.json')
    MANAGERS, OWN = frozen['managers'], frozen['own_signals']


def load_arrays(path: Path) -> dict:
    """機能: 既に因果的に公開された方向配列だけを読み込む。

    引数: path (Path)。返り値: セッション・銘柄をキーとする配列 (dict)。
    """
    with np.load(path) as archive:
        return {k: archive[f'{k[0]}|{k[1]}'] for k in INPUTS}


def array_digest(arrays: dict) -> str:
    """機能: 全配列の型・範囲・長さを検査し一意性指紋を作る。

    引数: arrays (dict)。返り値: SHA256文字列 (str)。
    """
    result = hashlib.sha256()
    for key in sorted(arrays):
        value = arrays[key]
        assert value.dtype == np.int8 and len(value) == len(INPUTS[key]['seq'])
        assert np.isin(value, [-1, 0, 1]).all()
        result.update(str(key).encode())
        result.update(value.tobytes())
    return result.hexdigest()


def evaluate(spec: dict) -> dict:
    """機能: 一入口の7管理を同じ原本行順に再生し全玉を集計する。

    引数: spec (dict)。返り値: 一入口の全結果 (dict)。
    """
    started = time.perf_counter()
    identifier = spec['id']
    summary_path = HERE / 'summaries' / f'{identifier}.json'
    rows_path = HERE / 'sessions' / f'{identifier}.json.gz'
    if summary_path.exists() and rows_path.exists():
        return read(summary_path)
    direction = load_arrays(SIGNAL_ROOT / 'directions' / f'{identifier}.npz')
    main = load_arrays(CONTEXT_ROOT / 'contexts' / f'{identifier}.npz')
    own = load_arrays(CONTEXT_ROOT / 'contexts' / f"{OWN[identifier]['id']}.npz")
    for folder, values in [('directions', direction), ('contexts', main), ('contexts_own', own)]:
        np.savez_compressed(HERE / folder / f'{identifier}.npz',
                            **{f'{k[0]}|{k[1]}': v for k, v in values.items()})
    hashes = [array_digest(v) for v in (direction, main, own)]
    for key in INPUTS:
        assert np.all((main[key] == 0) | (main[key] == own[key]))
        assert np.all(main[key][own[key] == 0] == 0)
    results, all_rows = [], []
    for management in MANAGERS:
        name = identifier + '__' + management['id']
        context = {'entry': None, 'main': main, 'own': own}[management['context_source']]
        ledger_hash, rows = hashlib.sha256(), []
        for key, ready in INPUTS.items():
            config = managers.make_config(management, key[1], ready)
            result = engine.run(ready, direction[key], config, detail=False,
                                context=None if context is None else context[key])
            ledger_hash.update(str(key).encode())
            ledger_hash.update(result['trades'].tobytes())
            row = research.summarize(result, config, key[1], key[0], name)
            row['two_largest_cycle_profits'] = sorted(
                [float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
            rows.append(row)
        symbols = diagnostics(rows)
        results.append({'id': name, 'signal_id': identifier, 'manager_id': management['id'],
                        'signal_family': spec['family'], 'manager_family': management['family'],
                        'symbols': symbols, 'failures': failures(symbols), 'ledger_hash': ledger_hash.hexdigest()})
        all_rows.append({'id': name, 'rows': rows})
    save(rows_path, all_rows)
    summary = {'signal': spec, 'state_hash': hashes[0], 'context_hash': hashes[1],
               'own_context_hash': hashes[2], 'elapsed_seconds': time.perf_counter() - started,
               'candidates': results}
    save(summary_path, summary)
    return summary


def main() -> None:
    """機能: 第6反復の全条件を固定し、全84を反証対象として保存する。

    引数: --workers (int)、--prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    for name in ['directions', 'contexts', 'contexts_own', 'sessions', 'summaries']:
        (HERE / name).mkdir(exist_ok=True)
    path = HERE / '探索条件の固定.json'
    if not path.exists():
        design = context_split_design.freeze()
        signals, own = design['signals'], design['own_signals']
        paths = [Path(__file__), HERE / 'context_split_design.py', HERE / '管理設計の固定.json',
                 CONTEXT_ROOT / 'engine_context.py', SIGNAL_ROOT / 'hierarchy_signals.py',
                 SIGNAL_ROOT / 'hierarchy_design_fixed.json', PREVIOUS / 'discovery_runner.py',
                 OLD / 'signals.py', OLD / 'engine.py', OLD / 'managers.py', OLD / 'research.py',
                 OLD / 'inputs.pkl', OLD / 'features_depth.pkl']
        paths += [SIGNAL_ROOT / 'directions' / f"{s['id']}.npz" for s in signals]
        paths += [CONTEXT_ROOT / 'contexts' / f"{s['id']}.npz" for s in signals + list(own.values())]
        save(path, {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
             'signals': signals, 'own_signals': own, 'managers': design['managers'],
             '全組合せ数': 84, '既知セッション数': 13,
             '前提': '費用０・指定価格約定・片方向上限TOPIX10枚/NK20枚・全玉場内返済',
             '選別': '全84条件を最低基準未達も含め一次反証・乱数64×2・指定8波へ送る。',
             '二入力': '入口全て元H。C=contexts、S=contexts_own。新規取消も入口のまま。',
             '現在データ': '追加取得・v27保存物再生禁止。既知期間の再探索。',
             'SHA256': {p.relative_to(HERE.parent).as_posix(): digest(p) for p in paths}})
    frozen = read(path)
    for relative, expected in frozen['SHA256'].items():
        assert digest(HERE.parent / relative) == expected, f'固定後の変更: {relative}'
    if args.prepare:
        print('第6反復の84条件を固定', flush=True)
        return
    for prerequisite in ['反証規則の固定.json', 'context_structure_before_pnl.json']:
        assert (HERE / prerequisite).exists(), f'結果前監査が必要: {prerequisite}'
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    started, summaries = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
        futures = [pool.submit(evaluate, s) for s in frozen['signals']]
        for future in as_completed(futures):
            result = future.result()
            summaries.append(result)
            print(f"{len(summaries)}/12 {result['signal']['id']} 完了、経過{time.perf_counter()-started:.0f}秒", flush=True)
            save(HERE / '進捗.json', {'完了信号': len(summaries), '全信号': 12,
                 '全条件': 84, '経過秒': time.perf_counter() - started})
    candidates = [c for s in summaries for c in s['candidates']]
    candidates.sort(key=lambda c: c['id'])
    save(HERE / '全条件の期間集計.json.gz', candidates)
    save(HERE / '反証前の候補固定.json', {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
         '全条件数': 84, '最低基準通過数': sum(not c['failures'] for c in candidates),
         '方向系列の一意数': len({s['state_hash'] for s in summaries}),
         '売買台帳の一意数': len({c['ledger_hash'] for c in candidates}),
         '中期撤回系列の一意数': len({s['context_hash'] for s in summaries}),
         '自己撤回系列の一意数': len({s['own_context_hash'] for s in summaries}),
         '反証候補': candidates, '未知検証ではない': True})
    print(f"全84条件完了、最低基準通過{sum(not c['failures'] for c in candidates)}。全件反証へ。", flush=True)


if __name__ == '__main__':
    main()
