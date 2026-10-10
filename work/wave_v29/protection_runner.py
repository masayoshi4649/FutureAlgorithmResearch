"""入口と数量を固定し、最高利益の保護を既知の13セッションで比較する。"""

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
sys.path.insert(0, str(PREVIOUS))
import discovery_runner as previous
import protection_design
import engine_protection as engine
import managers
import research
sys.path.insert(0, str(SIGNAL_ROOT))
import hierarchy_signals

save, read, digest = previous.save, previous.read, previous.digest
diagnostics, failures, score = previous.diagnostics, previous.failures, previous.score
INPUTS, FEATURES, MANAGERS = {}, {}, []


def worker_init() -> None:
    """機能: ワーカーの読取り入力と固定済み管理条件を用意する。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FEATURES, MANAGERS
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FEATURES = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    MANAGERS = read(HERE / '探索条件の固定.json')['managers']


def evaluate(spec: dict) -> dict:
    """機能: 一つの中期階層信号と全管理条件を順序どおりに再生する。

    引数: spec (dict) は事前固定条件。返り値: 期間集計と一意性情報 (dict)。
    """
    started = time.perf_counter()
    identifier = spec['id']
    summary_path = HERE / 'summaries' / f'{identifier}.json'
    rows_path = HERE / 'sessions' / f'{identifier}.json.gz'
    if summary_path.exists() and rows_path.exists():
        return read(summary_path)
    with np.load(SIGNAL_ROOT / 'directions' / f'{identifier}.npz') as archive:
        direction = {k: archive[f'{k[0]}|{k[1]}'] for k in INPUTS}
    context = hierarchy_signals.main_directions(spec, INPUTS)
    np.savez_compressed(HERE / 'directions' / f'{identifier}.npz',
                        **{f'{k[0]}|{k[1]}': a for k, a in direction.items()})
    np.savez_compressed(HERE / 'contexts' / f'{identifier}.npz',
                        **{f'{k[0]}|{k[1]}': a for k, a in context.items()})
    state_hash = hashlib.sha256()
    context_hash = hashlib.sha256()
    for key in sorted(direction):
        values = direction[key]
        assert values.dtype == np.int8 and len(values) == len(INPUTS[key]['seq'])
        assert np.isin(values, [-1, 0, 1]).all()
        state_hash.update(str(key).encode())
        state_hash.update(values.tobytes())
        main = context[key]
        assert main.dtype == np.int8 and len(main) == len(values) and np.isin(main, [-1, 0, 1]).all()
        context_hash.update(str(key).encode())
        context_hash.update(main.tobytes())
    results, all_rows = [], []
    for management in MANAGERS:
        name = identifier + '__' + management['id']
        ledger_hash, rows = hashlib.sha256(), []
        for key, ready in INPUTS.items():
            config = managers.make_config(management, key[1], ready)
            result = engine.run(ready, direction[key], config, detail=False,
                                context=context[key] if management['context_source'] == 'main' else None)
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
    summary = {'signal': spec, 'state_hash': state_hash.hexdigest(), 'context_hash': context_hash.hexdigest(),
               'elapsed_seconds': time.perf_counter() - started, 'candidates': results}
    save(summary_path, summary)
    return summary


def main() -> None:
    """機能: 第五反復の条件を固定し、全探索と次の反証対象を保存する。

    引数: --workers (int)、--prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    for name in ['directions', 'contexts', 'sessions', 'summaries']:
        (HERE / name).mkdir(exist_ok=True)
    frozen_path = HERE / '探索条件の固定.json'
    if not frozen_path.exists():
        signals = hierarchy_signals.catalog()
        protection_design.freeze()
        management = protection_design.catalog()
        assert len(signals) == 96 and len(management) == 50
        paths = [Path(__file__), HERE / 'engine_protection.py', HERE / 'protection_design.py', HERE / '管理設計の固定.json',
                 SIGNAL_ROOT / 'hierarchy_signals.py', SIGNAL_ROOT / 'hierarchy_design_fixed.json',
                 PREVIOUS / 'discovery_signals.py', PREVIOUS / 'discovery_runner.py',
                 OLD / 'signals.py', OLD / 'engine.py', OLD / 'managers.py', OLD / 'research.py',
                 OLD / 'inputs.pkl', OLD / 'features_depth.pkl']
        paths += [SIGNAL_ROOT / 'directions' / f"{spec['id']}.npz" for spec in signals]
        frozen = {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 'signals': signals,
                  'managers': management, '全組合せ数': len(signals) * len(management),
                  '既知セッション数': 13, '前提': '費用０・指定価格約定・片方向TOPIX10枚/NK20枚以内・全玉場内返済',
                  '解釈': '四反復と一回照合を知った後の改善案。現在snapshotは除外し、既知13セッションのみの発見。未知検証ではない。',
                  '選別': '前四反復と同じ最低基準・順位。上位30一意台帳と各思想首位を反証対象とする。',
                  '二入力': '入口はv27保存state。参考帯用に同仕様main_directionsも保存するが、本探索の退出にcontextを使わない。',
                  '比較': '同一入口K000がD273に全台帳一致することを要求。全条件の初回TOPIX5/NK10は同一。残玉1ATR幅capは既存trailとの包含があるため探索軸から除外。',
                  'SHA256': {p.relative_to(HERE.parent).as_posix(): digest(p) for p in paths}}
        save(frozen_path, frozen)
    frozen = read(frozen_path)
    for relative, expected in frozen['SHA256'].items():
        assert digest(HERE.parent / relative) == expected, f'固定後の変更: {relative}'
    if args.prepare:
        print(f"第５反復を固定: {frozen['全組合せ数']}条件", flush=True)
        return
    data_audit = read(PREVIOUS / 'data_audit.json')
    assert data_audit['前回と全原本が一致'] and data_audit['セッション数'] == 13
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    started, summaries = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
        futures = [pool.submit(evaluate, s) for s in frozen['signals']]
        for future in as_completed(futures):
            result = future.result()
            summaries.append(result)
            count = sum(not c['failures'] for c in result['candidates'])
            print(f"{len(summaries)}/96 {result['signal']['id']} 最低基準通過{count} 経過{time.perf_counter()-started:.0f}秒", flush=True)
            save(HERE / '進捗.json', {'完了信号': len(summaries), '全信号': 96,
                 '全条件': frozen['全組合せ数'], '経過秒': time.perf_counter() - started})
    candidates = [c for s in summaries for c in s['candidates']]
    candidates.sort(key=lambda c: c['id'])
    candidates.sort(key=score, reverse=True)
    save(HERE / '全条件の期間集計.json.gz', candidates)
    seen, top, families = set(), [], {}
    for candidate in candidates:
        if candidate['ledger_hash'] not in seen:
            seen.add(candidate['ledger_hash'])
            if len(top) < 30:
                top.append(candidate)
        families.setdefault(candidate['signal_family'], candidate)
    selected = {c['id']: c for c in top + list(families.values())}
    save(HERE / '反証前の候補固定.json', {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
         '全条件数': len(candidates), '最低基準通過数': sum(not c['failures'] for c in candidates),
         '方向系列の一意数': len({s['state_hash'] for s in summaries}), '売買台帳の一意数': len(seen),
         '中期撤回系列の一意数': len({s['context_hash'] for s in summaries}),
         '上位30': top, '思想別首位': families, '反証候補': list(selected.values()), '未知検証ではない': True})
    print(f"第５反復完了: {len(candidates)}条件、通過{sum(not c['failures'] for c in candidates)}、反証{len(selected)}", flush=True)


if __name__ == '__main__':
    main()
