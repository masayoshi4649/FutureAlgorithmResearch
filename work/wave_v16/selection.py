"""先頭９区間だけから既存規則で候補を選び、最終保留の評価条件を固定する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import reference

OUT = reference.OUT
research = reference.import_v14('research')
CAUSAL_EXCLUSIONS = ['N17', 'N18']
FIXED = [('N03_R-1_L3_U1', 'NK225'), ('N15_R-1_A4_U0', 'TOPIX'),
    ('N10_R1_E3_X2_U1', 'NK225'), ('N10_R1_E3_X2_U1_G1', 'NK225'),
    ('N02_R-1_E1_X2_U0', 'TOPIX'), ('NT_ratio_mom_Z1_S1', 'NT'),
    ('G01_T10', 'NK225'), ('G01_T10', 'TOPIX'), ('G15_T10', 'NK225'), ('G15_T10', 'TOPIX'),
    ('G16_A10', 'NK225'), ('G16_A10', 'TOPIX'), ('旧T12', 'NK225'), ('旧T12', 'TOPIX')]


def select() -> None:
    """機能: 前９区間と過去３〜８区間の指標から代表と時間順選択を保存する。

    引数: なし。返り値: なし (None)。最終夜の結果を読む処理はない。
    """
    if (OUT / '最終保留_凍結記録.json').exists():
        raise RuntimeError('最終保留固定後は候補を選び直せません')
    frame = pd.concat([pd.read_csv(OUT / f'{name}_探索集計.csv') for name in ['単独', '格子', 'NT']], ignore_index=True)
    pool = pd.concat([pd.read_csv(OUT / f'{name}_時間順候補.csv') for name in ['単独', '格子', 'NT']], ignore_index=True)
    assert frame.train_count.eq(9).all()
    for source in [frame, pool]:
        source['因果性監査による除外'] = source.family.isin(CAUSAL_EXCLUSIONS)
        source.loc[source['因果性監査による除外'], 'diagnostic_only'] = True
    primary = {symbol: research.choose(frame, symbol) for symbol in ['NK225', 'TOPIX', 'NT']}
    representatives = {}
    for symbol in ['NK225', 'TOPIX', 'NT']:
        for philosophy in sorted(frame.loc[frame.symbol.eq(symbol), 'philosophy'].unique()):
            representatives[f'{symbol}|{philosophy}'] = research.choose(frame, symbol, philosophy)
    walks = []
    for count in range(3, 10):
        past = frame if count == 9 else pool[pool.train_count.eq(count)]
        for symbol in ['NK225', 'TOPIX', 'NT']:
            walks.append(dict(学習=reference.SESSIONS[:count], 評価=reference.SESSIONS[count],
                **research.choose(past, symbol)))
    targets = set(FIXED)
    for record in [*primary.values(), *representatives.values(), *walks]:
        if record['採用'] is not None:
            targets.add((record['採用']['method'], record['銘柄']))
    reference.save(OUT / '最終選択.json', dict(選択時刻=pd.Timestamp.now(tz='Asia/Tokyo').isoformat(),
        選択用セッション=reference.DEVELOPMENT, 最終保留=reference.HOLDOUT,
        主候補=primary, 思想別代表=representatives, 前回候補=reference.FIXED_TARGETS,
        固定比較=[dict(method=m, symbol=s) for m, s in FIXED],
        因果性監査による採用除外系統=CAUSAL_EXCLUSIONS,
        照合対象=[dict(method=m, symbol=s) for m, s in sorted(targets)],
        照合ID=sorted({m for m, _ in targets}), 円額の銘柄横断順位=False))
    reference.save(OUT / '時間順選択.json', walks)
    frame.to_csv(OUT / '全思想_探索集計.csv', index=False, encoding='utf-8-sig')
    print(json.dumps({s: dict(方式=r['採用']['method'] if r['採用'] else None, 判定=r['判定']) for s, r in primary.items()}, ensure_ascii=False), flush=True)


def tracked_files() -> list[Path]:
    """機能: 最終夜を開く前に固定する実行コード・選択・入力の一覧を返す。

    引数: なし。返り値: list[Path]。
    """
    local = ['reference.py', 'single_research.py', 'selection.py', 'details.py', 'data_prepare.py',
        'run_alternatives.py', '検証計画.md', '最終選択.json', '時間順選択.json', '入力_development.pkl',
        'データ棚卸し.json', '入力準備記録.json']
    old_sources = [reference.OLD / f'{name}.py' for name in ['details', 'metrics', 'risk_guard', 'grid_engine', 'pair_engine', 'research']]
    old_sources += [reference.ROOT / f'work/wave_v13/{name}.py' for name in ['research', 'catalog', 'data', 'exact_engine', 'new_signals']]
    old_sources += [reference.ROOT / f'work/{name}' for name in ['wave_v11/signals.py', 'wave_v10/signals.py',
        'wave_v9/turning_signals.py', 'wave_v9/execution.py', 'wave_v8/raw_features.py']]
    old_sources += [reference.OLD / '全条件一覧.json', reference.ROOT / 'work/wave_v15/現在入力.pkl']
    holdout = [reference.ROOT / folder / symbol / f'{reference.HOLDOUT}.{suffix}'
        for folder, suffix in [('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv')]
        for symbol in reference.SYMBOLS]
    return [OUT / p for p in local] + old_sources + holdout


def freeze() -> None:
    """機能: 採用済みID・元条件・実装・最終夜原本を上書きなしで固定する。

    引数: なし。返り値: なし (None)。損益評価しない。
    """
    selection = json.loads((OUT / '最終選択.json').read_text(encoding='utf-8'))
    mapping = {c['id']: c for c in reference.configs()}
    record = dict(固定時刻=pd.Timestamp.now(tz='Asia/Tokyo').isoformat(), 最終保留=reference.HOLDOUT,
        選択用セッション=reference.DEVELOPMENT, 照合対象=selection['照合対象'],
        照合設定=[mapping[m] for m in selection['照合ID']],
        SHA256={p.relative_to(reference.ROOT).as_posix(): reference.sha256(p) for p in tracked_files()},
        現在API取得=0, 最終保留の全条件順位付け=False, 固定後再選択=False)
    with (OUT / '最終保留_凍結記録.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f'最終保留へ持ち込む{len(selection["照合対象"])}銘柄条件を固定しました。', flush=True)


def freeze_check() -> dict:
    """機能: 最終保留の評価前後に固定対象と条件の不変性を確認する。

    引数: なし。返り値: dict: 凍結記録。
    """
    value = json.loads((OUT / '最終保留_凍結記録.json').read_text(encoding='utf-8'))
    for name, digest in value['SHA256'].items():
        if reference.sha256(reference.ROOT / name) != digest:
            raise RuntimeError(f'最終保留の固定後変更: {name}')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='先頭９区間だけでの選択と最終保留条件固定')
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    freeze() if args.freeze else select()
