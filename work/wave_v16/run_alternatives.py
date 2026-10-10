"""固定済み54格子・36NT条件を、週データの探索区間と保留区間へ分離して再生する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd
import numba
import reference

OUT, OLD = reference.OUT, reference.OLD
DEVELOPMENT, HOLDOUT, SYMBOLS = reference.DEVELOPMENT, reference.HOLDOUT, reference.SYMBOLS
numba.config.CACHE_DIR = str(OUT / 'numba_cache_alternatives')
grid_engine = reference.import_v14('grid_engine')
pair_engine = reference.import_v14('pair_engine')
metrics = reference.import_v14('metrics')
research = reference.import_v14('research')


def write_json(path: Path, value: object) -> None:
    """機能: 日本語・標準数値型の監査資料を保存する。

    引数: path (Path)、value (object)。返り値: None。
    """
    def convert(item: object):
        """機能: NumPy型をJSONで表現可能な値へ変換する。

        引数: item (object)。返り値: Python標準型の値。
        """
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, np.ndarray):
            return item.tolist()
        raise TypeError(type(item).__name__)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               default=convert, allow_nan=False), encoding='utf-8')


def fixed_catalogs() -> tuple[list[dict], list[dict]]:
    """機能: 旧凍結条件と実装が一致することを確かめ、分類付き条件を返す。

    引数: なし。返り値: 格子54条件とNT36条件 (tuple[list[dict],list[dict]])。
    """
    grid = json.loads((OLD / '格子条件一覧.json').read_text(encoding='utf-8'))
    pair = json.loads((OLD / 'NT条件一覧.json').read_text(encoding='utf-8'))
    assert grid == [dict(c, engine='grid') for c in grid_engine.catalog()]
    assert pair == pair_engine.integrated_catalog()
    assert len(grid) == 54 and len(pair) == 36
    return grid, pair


def scalar_metrics(cycles: list[dict], sessions: list[str], config: dict,
                   symbol: str, auxiliary: str) -> dict:
    """機能: v14と同じ資格条件と指標で同銘柄の損小利大を集計する。

    引数: cycles (list[dict])、sessions (list[str])、config (dict)、symbol/auxiliary (str)。
    返り値: 入れ子を除く比率・資格・固定得点 (dict)。選択基準を新たに調整しない。
    """
    return research.scalar_metrics(cycles, sessions, config, symbol, auxiliary)


def evaluate_pool(by_key: dict, configs: list[dict], prefix: str,
                  sessions: list[str], auxiliary: str, forward: bool) -> None:
    """機能: 期間別集計と、過去だけで選択可能な先頭期間集計を保存する。

    引数: by_key (dict)、configs (list[dict])、prefix/auxiliary (str)、sessions (list[str])、forward (bool)。
    返り値: None。保留区間の全条件を探索表へ混ぜない。
    """
    mapping = {c['id']: c for c in configs}
    rows, prefixes = [], []
    for (method, symbol), cycles in by_key.items():
        config = mapping[method]
        rows.append(scalar_metrics(cycles, sessions, config, symbol, auxiliary))
        if forward:
            for count in range(3, len(sessions)):
                prefixes.append(scalar_metrics(cycles, sessions[:count], config, symbol, auxiliary))
    pd.DataFrame(rows).to_csv(OUT / f'{prefix}_探索集計.csv', index=False, encoding='utf-8-sig')
    if forward:
        pd.DataFrame(prefixes).to_csv(OUT / f'{prefix}_時間順候補.csv', index=False, encoding='utf-8-sig')
    with (OUT / f'{prefix}_サイクル.pkl').open('wb') as stream:
        pickle.dump(by_key, stream, protocol=pickle.HIGHEST_PROTOCOL)


def compare_values(actual: object, expected: object, label: str) -> int:
    """機能: 保存済み旧結果と再計算結果を型別に比較する。

    引数: actual/expected (object)、label (str)。返り値: 確認した末端値の数 (int)。
    """
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), f'{label}: キーが不一致'
        return sum(compare_values(actual[k], v, f'{label}/{k}') for k, v in expected.items())
    if isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected), f'{label}: 要素数が不一致'
        return sum(compare_values(a, e, f'{label}/{i}') for i, (a, e) in enumerate(zip(actual, expected)))
    if isinstance(expected, (int, float, np.number)) and not isinstance(expected, bool):
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-6, equal_nan=True,
                                   err_msg=label)
    else:
        assert actual == expected, f'{label}: 値が不一致'
    return 1


def replay_grid(prepared: dict, configs: list[dict], sessions: list[str], prefix: str,
                check_old: bool) -> dict:
    """機能: 指定済み格子条件を各銘柄の生価格全行で再生して全玉会計する。

    引数: prepared (dict)、configs (list[dict])、sessions (list[str])、prefix (str)、check_old (bool)。
    返り値: 条件数・セル数・旧結果比較件数の監査記録 (dict)。
    """
    if check_old:
        with (OLD / '格子_再生結果.pkl').open('rb') as stream:
            old_results = pickle.load(stream)
    by_key = {(c['id'], symbol): [] for c in configs for symbol in SYMBOLS}
    rows, cells = [], {}
    checked_cells, checked_scalars, checked_raw_values = 0, 0, 0
    for session in sessions:
        for symbol in SYMBOLS:
            ready = prepared[(session, symbol)]
            for cfg in configs:
                result = grid_engine.simulate(ready, cfg)
                cycles = metrics.from_raw(result['raw'], cfg['id'], symbol, session, cfg['max_legs'],
                                          ready['time_s'], result['incomplete_cycle_ids'])
                by_key[(cfg['id'], symbol)].extend(cycles)
                key = (cfg['id'], session, symbol)
                cells[key] = dict(raw=result['raw'], summary=result['summary'],
                                  incomplete_cycle_ids=result['incomplete_cycle_ids'])
                cm = metrics.summarize(cycles, [session], 'yen')
                rows.append(dict(方式=cfg['id'], 系統=cfg['family'], 思想=cfg['philosophy'],
                    セッション=session, 銘柄=symbol, 設定最大枚数=cfg['max_legs'], **result['summary'],
                    **{f'cycle_{k}': v for k, v in cm.items()
                       if not isinstance(v, (dict, list)) and k not in ('method', 'symbol')}))
                if check_old and session in DEVELOPMENT[:7]:
                    old = old_results[key]
                    np.testing.assert_allclose(result['raw'], old['raw'], rtol=1e-10, atol=1e-6,
                                               equal_nan=True, err_msg=str(key))
                    checked_raw_values += result['raw'].size
                    checked_scalars += compare_values(result['summary'], old['summary'], str(key))
                    assert result['incomplete_cycle_ids'] == old['incomplete_cycle_ids']
                    checked_cells += 1
            print(f'格子完了 {session} {symbol} {len(configs)}条件', flush=True)
    pd.DataFrame(rows).to_csv(OUT / f'{prefix}_セッション集計.csv', index=False, encoding='utf-8-sig')
    with (OUT / f'{prefix}_再生結果.pkl').open('wb') as stream:
        pickle.dump(cells, stream, protocol=pickle.HIGHEST_PROTOCOL)
    evaluate_pool(by_key, configs, prefix, sessions, 'atr_cap', len(sessions) > 1)
    return dict(条件数=len(configs), セル数=len(rows), 旧７一致セル数=checked_cells,
                旧７一致全脚値数=checked_raw_values, 旧７一致集計値数=checked_scalars,
                未完了サイクル数=sum(not c['complete'] for values in by_key.values() for c in values))


def replay_pair(prepared: dict, configs: list[dict], sessions: list[str], prefix: str,
                check_old: bool) -> dict:
    """機能: NT固定条件を遅延同期後に判断し、各脚を次の原本価格で売買する。

    引数: prepared (dict)、configs (list[dict])、sessions (list[str])、prefix (str)、check_old (bool)。
    返り値: 条件数・セル数・旧サイクルとの比較数の監査記録 (dict)。
    """
    old_cycles = {}
    if check_old:
        for cycle in json.loads((OLD / 'NT_サイクル.json').read_text(encoding='utf-8')):
            key = (cycle['method'], cycle['session'])
            old_cycles.setdefault(key, []).append(cycle)
    by_key = {(cfg['id'], 'NT'): [] for cfg in configs}
    rows, cells, checked_cells, checked_values = [], {}, 0, 0
    for session in sessions:
        tapes = [prepared[(session, symbol)] for symbol in SYMBOLS]
        ready = pair_engine.prepare_session(session, tapes=tapes)
        for cfg in configs:
            result = pair_engine.run(ready, cfg, detail=False)
            by_key[(cfg['id'], 'NT')].extend(result['cycles'])
            cells[(cfg['id'], session, 'NT')] = dict(summary=result['summary'], cycles=result['cycles'],
                                                    legs=result['legs'])
            cm = metrics.summarize(result['cycles'], [session], 'yen')
            rows.append(dict(方式=cfg['id'], 系統=cfg['family'], 思想=cfg['philosophy'],
                セッション=session, 銘柄='NT', 設定最大枚数=cfg['max_legs'], **result['summary'],
                **{f'cycle_{k}': v for k, v in cm.items()
                   if not isinstance(v, (dict, list)) and k not in ('method', 'symbol')}))
            if check_old and session in DEVELOPMENT[:7]:
                checked_values += compare_values(result['cycles'], old_cycles.get((cfg['id'], session), []),
                                                 f"{cfg['id']}/{session}")
                checked_cells += 1
        print(f'NT完了 {session} {len(configs)}条件', flush=True)
    pd.DataFrame(rows).to_csv(OUT / f'{prefix}_セッション集計.csv', index=False, encoding='utf-8-sig')
    with (OUT / f'{prefix}_再生結果.pkl').open('wb') as stream:
        pickle.dump(cells, stream, protocol=pickle.HIGHEST_PROTOCOL)
    evaluate_pool(by_key, configs, prefix, sessions, 'r', len(sessions) > 1)
    return dict(条件数=len(configs), セル数=len(rows), 旧７一致セル数=checked_cells,
                旧７一致サイクル値数=checked_values,
                未完了サイクル数=sum(not c['complete'] for values in by_key.values() for c in values))


def main() -> None:
    """機能: 探索９区間か、事前に固定した条件のみの保留１区間を再生する。

    引数: CLIの入力パス・段階・固定ID資料。返り値: None。
    保留では固定資料とそのSHA256の明示を必須とし、全条件探索を認めない。
    """
    parser = argparse.ArgumentParser(description='旧54格子・36NTの固定条件を週データへ適用')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--phase', choices=['development', 'holdout'], default='development')
    parser.add_argument('--fixed-json', type=Path)
    parser.add_argument('--fixed-sha256')
    args = parser.parse_args()
    grid, pair = fixed_catalogs()
    source_hashes = {name: hashlib.sha256((OLD / name).read_bytes()).hexdigest()
                     for name in ['grid_engine.py', 'pair_engine.py', 'metrics.py']}
    fixed_hash = None
    if args.phase == 'holdout':
        if not (OUT / '最終保留_凍結記録.json').exists():
            raise ValueError('最終保留の条件固定記録がありません。')
        if args.fixed_json is None or args.fixed_sha256 is None:
            raise ValueError('保留再生には、凍結済みID資料とそのSHA256が必要です。')
        fixed_hash = hashlib.sha256(args.fixed_json.read_bytes()).hexdigest()
        if fixed_hash != args.fixed_sha256:
            raise ValueError('固定資料のSHA256が一致しません。')
        fixed = json.loads(args.fixed_json.read_text(encoding='utf-8'))
        selected = fixed if isinstance(fixed, list) else fixed['照合ID']
        selected = set(selected)
        if not selected or len(selected & {cfg['id'] for cfg in grid + pair}) >= 90:
            raise ValueError('保留区間を全条件探索することはできません。')
        grid = [cfg for cfg in grid if cfg['id'] in selected]
        pair = [cfg for cfg in pair if cfg['id'] in selected]
    with args.input.open('rb') as stream:
        prepared = pickle.load(stream)
    sessions = DEVELOPMENT if args.phase == 'development' else [HOLDOUT]
    assert set(prepared) == {(s, k) for s in sessions for k in SYMBOLS}, '入力期間が指定段階と不一致'
    started = time.monotonic()
    suffix = '' if args.phase == 'development' else '_保留'
    audit = dict(段階=args.phase, 対象セッション=sessions, 保留区間を探索へ混入=False,
                 条件を追加変更=False, 原本通信回数=0, 入力SHA256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                 旧ソースSHA256=source_hashes, 固定資料SHA256=fixed_hash)
    if grid:
        write_json(OUT / f'格子{suffix}条件一覧.json', grid)
        audit['格子'] = replay_grid(prepared, grid, sessions, f'格子{suffix}', args.phase == 'development')
    if pair:
        write_json(OUT / f'NT{suffix}条件一覧.json', pair)
        audit['NT'] = replay_pair(prepared, pair, sessions, f'NT{suffix}', args.phase == 'development')
    assert all(hashlib.sha256((OLD / name).read_bytes()).hexdigest() == value
               for name, value in source_hashes.items())
    audit.update(合格=True, 所要秒=time.monotonic() - started)
    write_json(OUT / f'格子とNT{suffix}_再検証監査.json', audit)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
