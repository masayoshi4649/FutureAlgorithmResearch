"""固定した新候補二方式と元基準を、保存済み追加デイだけへ適用する。"""

from __future__ import annotations

from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSION = '2026-10-01_Day'
OLD = ROOT / 'work/wave_v49/early'
IDS = ('E00', 'E01', 'E08')
SYMBOLS = ('TOPIX', 'NK225')


def module(name: str, path: Path) -> object:
    """機能: 既存ファイルを変更せず固有名で読む。

    引数: name(str)、path(Path)。返り値: 読込モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


previous = module('追加入力の既存実装', ROOT / 'work/wave_v48/update_20261001/replay_added_session.py')
early = module('早期保護の既存実装', OLD / 'run.py')
previous.HERE = HERE
integration, source = early.integration, early.source


def read(path: Path) -> object:
    """機能: JSON又は圧縮JSONを読む。

    引数: path(Path)。返り値: 格納値(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path: Path, value: object) -> None:
    """機能: 追加専用領域に有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == '.gz' else raw)


def freeze() -> dict:
    """機能: 追加原本と過去固定条件を損益計算前に固定する。

    引数: なし。返り値: 固定資料(dict)。
    """
    variants = [v for v in early.catalog() if v['id'] in IDS]
    old_fixed = read(OLD / '条件の事前固定.json')
    assert variants == [v for v in old_fixed['条件'] if v['id'] in IDS]
    old_complete = read(OLD / '完了.json')
    assert old_complete['全合格']
    previous.verify(old_complete['出力SHA256'])
    raw = [ROOT / folder / symbol / (SESSION + suffix)
           for folder, suffix in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))
           for symbol in SYMBOLS]
    assert all(p.exists() for p in raw)
    old_paths = [OLD / name for name in ('条件の事前固定.json', '完了.json')]
    old_paths += [ROOT / p for p in old_complete['出力SHA256']]
    sources = [Path(__file__)]
    for value in tuple(sys.modules.values()):
        name = getattr(value, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.suffix == '.py' and path.is_relative_to(ROOT / 'work'):
                sources.append(path)
    fixed = dict(対象=SESSION, 条件=variants, 条件変更=False, 過去探索条件の再調整=False,
        基準=early.BASE_ID, 原本SHA256=previous.fingerprints(raw),
        既存結果SHA256=previous.fingerprints(old_paths), 実装SHA256=previous.fingerprints(sources),
        初回枚数={'TOPIX': 5, 'NK225': 10}, 片方向上限={'TOPIX': 10, 'NK225': 20},
        円倍率={'TOPIX': 1000, 'NK225': 10}, API追加取得数=0, 費用=0, 指定価格約定=True,
        検証位置='旧16セッションで固定した3方式の追加1セッション追試。今回の損益による条件調整なし。')
    target = HERE / '固定.json'
    if target.exists():
        assert read(target) == fixed
    else:
        save(target, fixed)
    return fixed


def activate(inputs: dict, signals: dict) -> None:
    """機能: 固定実装へ対象入力と同じ生成器の信号を設定する。

    引数: inputs/signals(dict)。返り値: なし(None)。
    """
    source.INPUTS = inputs
    source.followup.INPUTS = inputs
    source.replay.INPUTS = inputs
    source.replay.MID = signals


def replay_one(variant: dict, key: tuple, ready: dict, causal: bool) -> tuple:
    """機能: 一口座を元通常影時計と同じ初回で再生し検算する。

    引数: variant/ready(dict)、key(tuple)、causal(bool)。返り値: 集計・台帳・監査・曲線(tuple)。
    """
    spec = deepcopy(next(s for s in source.followup.catalog('new') if s['id'] == early.BASE_ID))
    spec['id'] = early.BASE_ID + '__' + variant['id']
    columns, valid = source.replay.new_columns(spec, key)
    base, config = early.configs(spec, ready, variant)
    actual = early.play(spec, ready, columns, valid, base, config)
    row, curve, proof = early.inspect(spec, ready, actual, config)
    result = actual[0]
    ledger = dict(session=key[0], symbol=key[1], config=config,
        **{field: result[field].tolist() for field in integration.STORED},
        result_fingerprints=integration.reference.old.fingerprints(result),
        shadow_fingerprints=integration.reference.old.fingerprints(result['shadow'], integration.reference.reference.EXPECTED_SHADOW_FIELDS),
        scheduler_fingerprints=integration.reference.old.fingerprints(result['shadow']['scheduler'], integration.reference.reference.EXPECTED_SHADOW_FIELDS),
        scheduler_cycles=result['shadow']['scheduler']['cycles'].tolist(),
        scheduler_orders=result['shadow']['scheduler']['orders'].tolist())
    if causal:
        proof['因果'] = early.causal(spec, ready, columns, valid, base, config, actual)
    proof.update(session=key[0], symbol=key[1])
    row['initial_entries'] = len(result['entry_preparations'])
    row['active_session'] = bool(row['initial_entries'])
    return row, ledger, proof, curve


def reproduce(inputs: dict, features: dict, fixed: dict) -> None:
    """機能: 直前ナイトの既存六口座を再現し、追加デイの六口座を再生する。

    引数: inputs/features/fixed(dict)。返り値: なし(None)。
    """
    integration.reference.initialize()
    new_signals = previous.signal_audit(inputs, features)
    folder = ROOT / 'work/wave_v48/update_20261001'
    prior_inputs = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
    prior_features = pickle.loads((folder / 'new_features_depth.pkl').read_bytes())
    old_signals = previous.signals(prior_inputs, prior_features, ROOT)
    for variant in fixed['条件']:
        identifier = variant['id']
        activate(prior_inputs, old_signals)
        stored = {(r['session'], r['symbol']): r for r in read(OLD / 'ledgers' / (identifier + '.json.gz'))}
        calibration = []
        for key, ready in sorted(prior_inputs.items()):
            _, ledger, _, _ = replay_one(variant, key, ready, False)
            for field in ('result_fingerprints', 'shadow_fingerprints', 'scheduler_fingerprints'):
                assert ledger[field] == stored[key][field], (identifier, key, field)
            calibration.append(dict(session=key[0], symbol=key[1], 実口座と両影の指紋一致=True))
        activate(inputs, new_signals)
        rows, ledgers, proofs = [], [], []
        for key, ready in sorted(inputs.items()):
            row, ledger, proof, curve = replay_one(variant, key, ready, True)
            rows.append(row)
            ledgers.append(ledger)
            proofs.append(proof)
            path = HERE / 'curves' / (identifier + '_' + key[1] + '.npz')
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(path, equity=curve)
        for name, value in (('sessions', rows), ('ledgers', ledgers), ('audits', proofs)):
            save(HERE / name / (identifier + '.json.gz'), value)
        save(HERE / 'completed' / (identifier + '.json'), dict(id=identifier, 全合格=True, 旧直前場再現=calibration,
            条件変更=False, 新監査数=2, 新因果監査数=2))
        print(identifier + ' 旧2口座指紋一致・新2口座再生と因果検査完了', flush=True)


def assess(inputs: dict) -> None:
    """機能: 旧十六場を保存台帳のまま、新一場と合わせ期間会計を計算する。

    引数: inputs(dict)。返り値: なし(None)。
    """
    old_inputs = pickle.loads((ROOT / 'work/wave_v47/inputs.pkl').read_bytes())
    for name in ('update_20260930', 'update_20261001'):
        more = pickle.loads((ROOT / 'work/wave_v48' / name / 'new_inputs.pkl').read_bytes())
        assert not (set(more) & set(old_inputs))
        old_inputs.update(more)
    assert len(old_inputs) == 32 and not (set(old_inputs) & set(inputs))
    combined = old_inputs | inputs
    old_names = sorted({k[0] for k in old_inputs})
    names = sorted({k[0] for k in combined})
    output = {}
    for identifier in IDS:
        rows = read(OLD / 'sessions' / (identifier + '.json.gz')) + read(HERE / 'sessions' / (identifier + '.json.gz'))
        ledgers = read(OLD / 'ledgers' / (identifier + '.json.gz')) + read(HERE / 'ledgers' / (identifier + '.json.gz'))
        by_key = {(r['session'], r['symbol']): r for r in rows}
        assert len(rows) == len(ledgers) == len(by_key) == len(combined) == 34
        series = {}
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            curve, totals = previous.charts.chart.reconstruct(combined[key], ledger)
            for field, value in totals.items():
                assert abs(by_key[key][field] - value) < 1e-6, (identifier, key, field)
            series[key] = curve[:, 0]
        periods = {}
        for label, chosen in (('旧16', old_names), ('追加1', [SESSION]), ('全17', names)):
            periods[label] = {symbol: source.period(rows, series, chosen, symbol) for symbol in SYMBOLS}
        expected = read(OLD / 'summaries' / (identifier + '.json'))['periods']['全16']
        for symbol in SYMBOLS:
            source.followup.audit.statistics.equal(periods['旧16'][symbol], expected[symbol], '旧十六場不変')
        output[identifier] = periods['全17']
        save(HERE / 'summaries' / (identifier + '.json'), dict(id=identifier, 全合格=True, 旧十六場全統計一致=True,
            periods=periods, 対象=SESSION, 条件変更=False))
    save(HERE / 'assessment.json', output)


def main() -> None:
    """機能: 保存原本の追加追試と変化していない条件・原本の検算を実行する。

    引数: なし。返り値: なし(None)。
    """
    socket.socket.connect = previous.deny
    socket.create_connection = previous.deny
    fixed = freeze()
    if (HERE / '入力監査.json').exists():
        proof = read(HERE / '入力監査.json')
        assert proof['全合格'] and proof['対象'] == SESSION
        previous.verify(proof['出力SHA256'])
        inputs = pickle.loads((HERE / 'new_inputs.pkl').read_bytes())
        features = pickle.loads((HERE / 'new_features_depth.pkl').read_bytes())
    else:
        inputs, features = previous.extract(SESSION)
    reproduce(inputs, features, fixed)
    assess(inputs)
    for field in ('原本SHA256', '既存結果SHA256', '実装SHA256'):
        previous.verify(fixed[field])
    files = [HERE / name for name in ('assessment.json', '入力監査.json', '信号監査.json')]
    files += [HERE / folder / (identifier + suffix) for identifier in IDS
        for folder, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('audits', '.json.gz'),
                               ('summaries', '.json'), ('completed', '.json'))]
    files += list((HERE / 'curves').glob('*.npz'))
    save(HERE / 'complete.json', dict(全合格=True, 対象=SESSION, 条件数=3, 新口座数=6,
        旧再現口座数=6, 全期間場数=17, 旧十六場全統計一致=True, 条件変更=False, API追加取得数=0,
        固定SHA256=previous.sha(HERE / '固定.json'), 出力SHA256=previous.fingerprints(files), 原本実装不変=True))
    print('追加六口座と旧十六場不変の全検算完了', flush=True)


if __name__ == '__main__':
    main()
