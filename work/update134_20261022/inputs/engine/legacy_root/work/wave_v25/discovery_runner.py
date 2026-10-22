"""異なる方向思想と注文管理を全組合せで発見し、反証前の候補を固定する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
sys.path.insert(0, str(OLD))
import engine
import managers
import research

SYMBOLS = ['TOPIX', 'NK225']
INPUTS, FEATURES, OLD_DIRECTIONS = {}, {}, {}
MANAGERS = []


def save(path: Path, value: object) -> None:
    """機能: 有限JSONをUTF-8で保存し、途中ファイルの読取りを防ぐ。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    temporary = path.with_suffix(path.suffix + '.tmp')
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if path.suffix == '.gz':
        with gzip.open(temporary, 'wt', encoding='utf-8') as stream:
            stream.write(data)
    else:
        temporary.write_text(data, encoding='utf-8')
    temporary.replace(path)


def read(path: Path) -> object:
    """機能: 通常または圧縮JSONを読む。

    引数: path (Path)。返り値: JSON内容 (object)。
    """
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """機能: ファイルを逐次読み込んでSHA256を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def diagnostics(rows: list[dict]) -> dict:
    """機能: 探索順位とは別に、固定した弱点を銘柄別に記録する。

    引数: rows (list[dict]) セッション集計。返り値: 診断集計 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        own = [r for r in rows if r['symbol'] == symbol]
        summary = research.aggregate(own)
        day = [r for r in own if r['session'].endswith('Day')]
        night = [r for r in own if r['session'].endswith('Night')]
        ordered = sorted((r['net_yen'] for r in own), reverse=True)
        by_date = {}
        for row in own:
            key = row['session'][:10]
            by_date[key] = by_date.get(key, 0.) + row['net_yen']
        date_profits = sorted(by_date.values(), reverse=True)
        cycle_profits = sorted([v for r in own for v in r['two_largest_cycle_profits']], reverse=True)
        summary.update(day_net=sum(r['net_yen'] for r in day), night_net=sum(r['net_yen'] for r in night),
                       two_sessions_removed_net=summary['net_yen'] - sum(ordered[:2]),
                       two_start_days_removed_net=summary['net_yen'] - sum(date_profits[:2]),
                       two_cycles_removed_net=summary['net_yen'] - sum(cycle_profits[:2]),
                       early_week_net=sum(r['net_yen'] for r in own if r['session'] < '2026-09-28'),
                       later_week_net=sum(r['net_yen'] for r in own if r['session'] >= '2026-09-28'))
        output[symbol] = summary
    return output


def failures(symbols: dict) -> list[str]:
    """機能: 研究候補の最低条件を結果に関係なく同じ基準で判定する。

    引数: symbols (dict)。返り値: 不合格理由の配列 (list[str])。
    """
    reasons = []
    for symbol, row in symbols.items():
        checks = {
            '全期間赤字または同値': row['net_yen'] > 0,
            '利益損失比1.30未満': (row['money_ratio'] or 0) >= 1.30,
            '平均勝ち負け比1.20未満': (row['average_unit_payoff'] or 0) >= 1.20,
            '取引13組未満': row['cycles'] >= 13,
            '稼働7セッション未満': row['active_sessions'] >= 7,
            '勝ち7セッション未満': row['win_sessions'] >= 7,
            '最大2勝ちセッション依存': row['two_sessions_removed_net'] > 0,
            '最大2勝ち売買組依存': row['two_cycles_removed_net'] > 0,
            '日中黒字なし': row['day_net'] > 0,
            '夜間黒字なし': row['night_net'] > 0,
            '前週黒字なし': row['early_week_net'] > 0,
            '追加週黒字なし': row['later_week_net'] > 0,
        }
        reasons.extend(f'{symbol}:{name}' for name, passed in checks.items() if not passed)
    return reasons


def score(candidate: dict) -> tuple:
    """機能: 最も弱い銘柄の耐性を優先し、異銘柄の円額を合算しない。

    引数: candidate (dict)。返り値: 降順の比較キー (tuple)。
    """
    values = list(candidate['symbols'].values())
    return (not candidate['failures'], -len(candidate['failures']),
            min((r['best_removed_pf'] or 0) for r in values),
            min(r['net_yen'] / max(r['drawdown_yen'], 1.) for r in values),
            min(r['win_sessions'] for r in values))


def worker_init() -> None:
    """機能: 並列ワーカーごとに読取り専用の入力を一度だけ読み込む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FEATURES, OLD_DIRECTIONS, MANAGERS
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FEATURES = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    OLD_DIRECTIONS = pickle.loads((OLD / 'directions.pkl').read_bytes())
    MANAGERS = read(HERE / '探索条件の固定.json')['managers']


def evaluate(spec: dict) -> dict:
    """機能: 一つの方向信号と全管理条件を原本行順で再生する。

    引数: spec (dict) 固定済み方向条件。返り値: 軽量な期間集計 (dict)。
    """
    import discovery_signals
    start = time.perf_counter()
    identifier = spec['id']
    path = HERE / 'sessions' / f'{identifier}.json.gz'
    summary_path = HERE / 'summaries' / f'{identifier}.json'
    if summary_path.exists() and path.exists():
        return read(summary_path)
    direction = OLD_DIRECTIONS[identifier] if spec['source'] == '既存' else discovery_signals.build(spec, INPUTS, FEATURES)
    state_path = HERE / 'directions' / f'{identifier}.npz'
    np.savez_compressed(state_path, **{f'{key[0]}|{key[1]}': arr for key, arr in direction.items()})
    state_hash = hashlib.sha256()
    for key in sorted(direction):
        arr = direction[key]
        assert arr.dtype == np.int8 and len(arr) == len(INPUTS[key]['seq'])
        assert np.isin(arr, [-1, 0, 1]).all()
        state_hash.update(str(key).encode())
        state_hash.update(arr.tobytes())
    all_rows, results = [], []
    for management in MANAGERS:
        name = identifier + '__' + management['id']
        rows = []
        ledger_hash = hashlib.sha256()
        for key, ready in INPUTS.items():
            cfg = managers.make_config(management, key[1], ready)
            result = engine.run(ready, direction[key], cfg, detail=False)
            ledger_hash.update(str(key).encode())
            ledger_hash.update(result['trades'].tobytes())
            row = research.summarize(result, cfg, key[1], key[0], name)
            wins = sorted([float(v) * cfg['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)
            row['two_largest_cycle_profits'] = wins[:2]
            rows.append(row)
        symbols = diagnostics(rows)
        candidate = {'id': name, 'signal_id': identifier, 'manager_id': management['id'],
                     'signal_family': spec['family'], 'manager_family': management['family'],
                     'symbols': symbols, 'failures': failures(symbols), 'ledger_hash': ledger_hash.hexdigest()}
        results.append(candidate)
        all_rows.append({'id': name, 'rows': rows})
    save(path, all_rows)
    summary = {'signal': spec, 'state_hash': state_hash.hexdigest(), 'elapsed_seconds': time.perf_counter() - start, 'candidates': results}
    save(summary_path, summary)
    return summary


def main() -> None:
    """機能: 探索を事前固定し、再開可能な並列再生と候補台帳を作る。

    引数: コマンド引数 workers (int)、prepare (bool)。返り値: なし (None)。
    """
    import discovery_signals
    import discovery_managers
    args = argparse.ArgumentParser()
    args.add_argument('--workers', type=int, default=12)
    args.add_argument('--prepare', action='store_true')
    parsed = args.parse_args()
    for folder in ['directions', 'summaries', 'sessions']:
        (HERE / folder).mkdir(exist_ok=True)
    path = HERE / '探索条件の固定.json'
    if not path.exists():
        old_specs = read(OLD / '探索前の信号条件.json')
        old_keys = set(pickle.loads((OLD / 'directions.pkl').read_bytes()))
        known = {x['id'] for x in old_specs}
        for key in sorted(old_keys - known):
            old_specs.append({'id': key, 'name': '既存学習方向' + key, 'family': '既存学習', 'description': '前回の時系列学習済み方向をそのまま再生', 'params': {}})
        signal_specs = [dict(s, source='既存') for s in old_specs if s['id'] in old_keys]
        signal_specs += [dict(s, source='新規') for s in discovery_signals.catalog()]
        manager_specs = discovery_managers.catalog()
        assert len({s['id'] for s in signal_specs}) == len(signal_specs)
        assert len({s['id'] for s in manager_specs}) == len(manager_specs)
        frozen = {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 'signals': signal_specs, 'managers': manager_specs,
                  '全組合せ数': len(signal_specs) * len(manager_specs), '既知セッション数': 13,
                  '主前提': '費用0・指定価格約定・TOPIXミニ片方向10枚以内/NKマイクロ20枚以内・場内返済',
                  '解釈': '全データ既読の発見段階。合格は既知期間の研究候補であり未知相場の実証ではない。',
                  '選定': '両銘柄の最低条件・最大勝ち除外・日夜/週別黒字を要求。最弱銘柄の除外PFと収支/DDで並べ、思想別候補も残す。',
                  'SHA256': {str(p.relative_to(HERE.parent)): digest(p) for p in [Path(__file__), HERE / 'discovery_signals.py', HERE / 'discovery_managers.py', OLD / 'engine.py', OLD / 'inputs.pkl', OLD / 'features_depth.pkl', OLD / 'directions.pkl']}}
        save(path, frozen)
    frozen = read(path)
    for relative, expected in frozen['SHA256'].items():
        assert digest(HERE.parent / relative) == expected, f'固定後の変更: {relative}'
    if parsed.prepare:
        print(f"探索条件を固定: {frozen['全組合せ数']}組合せ", flush=True)
        return
    audit = read(HERE / 'data_audit.json')
    assert audit['前回と全原本が一致'] and audit['セッション数'] == 13, '原本監査の不一致'
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    start, completed, summaries = time.perf_counter(), 0, []
    specs = frozen['signals']
    print(f"全{len(specs)}信号×{len(frozen['managers'])}管理={frozen['全組合せ数']}組合せを開始", flush=True)
    with ProcessPoolExecutor(max_workers=parsed.workers, initializer=worker_init) as pool:
        futures = {pool.submit(evaluate, spec): spec['id'] for spec in specs}
        for future in as_completed(futures):
            result = future.result()
            summaries.append(result)
            completed += 1
            passed = sum(not c['failures'] for c in result['candidates'])
            print(f"{completed}/{len(specs)} {result['signal']['id']} 基準通過{passed} 経過{time.perf_counter()-start:.0f}秒", flush=True)
            save(HERE / '進捗.json', {'完了信号': completed, '全信号': len(specs), '全条件': frozen['全組合せ数'], '経過秒': time.perf_counter()-start})
    candidates = [c for summary in summaries for c in summary['candidates']]
    candidates.sort(key=lambda candidate: candidate['id'])
    candidates.sort(key=score, reverse=True)
    save(HERE / '全条件の期間集計.json.gz', candidates)
    seen, top = set(), []
    for candidate in candidates:
        if candidate['ledger_hash'] not in seen:
            seen.add(candidate['ledger_hash'])
            if len(top) < 30:
                top.append(candidate)
    family_best = {}
    for candidate in candidates:
        family_best.setdefault(candidate['signal_family'], candidate)
    selected = {c['id']: c for c in top + list(family_best.values())}
    save(HERE / '反証前の候補固定.json', {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
         '全条件数': len(candidates), '最低基準通過数': sum(not c['failures'] for c in candidates),
         '方向系列の一意数': len({s['state_hash'] for s in summaries}), '売買台帳の一意数': len(seen), '上位30': top,
         '思想別首位': family_best, '反証候補': list(selected.values()), '未知検証ではない': True})
    print(f"探索完了: {len(candidates)}条件、最低基準通過{sum(not c['failures'] for c in candidates)}、反証候補{len(selected)}", flush=True)


if __name__ == '__main__':
    main()
