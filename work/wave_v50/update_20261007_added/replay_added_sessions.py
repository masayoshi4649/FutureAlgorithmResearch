"""固定三方式を保存済みの追加四セッションへ適用し、二十三場を連結検算する。"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSIONS = ('2026-10-02_Night', '2026-10-05_Day', '2026-10-05_Night', '2026-10-06_Day')
EARLIER = ROOT / 'work/wave_v50/update_20261001_day'
PRIOR = ROOT / 'work/wave_v50/update_20261002_two'
OLD = ROOT / 'work/wave_v49/early'
IDS = ('E00', 'E01', 'E08')
SYMBOLS = ('TOPIX', 'NK225')


def module(name: str, path: Path) -> object:
    """機能: 読取専用の従来実装を固有名で取り込む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


prior = module('二十三場追加の従来実装', EARLIER / 'replay_added_session.py')
previous, early = prior.previous, prior.early
integration, source = early.integration, early.source


def read(path: Path) -> object:
    """機能: JSON又は圧縮JSONから保存値を読む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    content = path.read_bytes()
    return json.loads(gzip.decompress(content) if path.suffix == '.gz' else content)


def save(path: Path, value: object) -> None:
    """機能: 今回の作業領域内へ有限JSONを原子的に保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(gzip.compress(content, mtime=0) if path.suffix == '.gz' else content)
    temporary.replace(path)


def freeze() -> dict:
    """機能: 損益計算前に追加原本・従来条件・既存出力・使用実装を固定する。

    引数: なし。返り値: 固定資料(dict)。
    """
    variants = [v for v in early.catalog() if v['id'] in IDS]
    assert variants == [v for v in read(OLD / '条件の事前固定.json')['条件'] if v['id'] in IDS]
    protected = [OLD / '条件の事前固定.json']
    for folder in (OLD, EARLIER, PRIOR):
        completion_path = folder / ('完了.json' if folder == OLD else 'complete.json')
        completion = read(completion_path)
        assert completion['全合格']
        previous.verify(completion['出力SHA256'])
        protected += [completion_path] + [ROOT / name for name in completion['出力SHA256']]
    protected += [PRIOR / name for name in ('固定.json', 'new_inputs.pkl', 'new_features_depth.pkl')]
    raw = [ROOT / folder / symbol / (session + suffix)
           for session in SESSIONS
           for folder, suffix in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))
           for symbol in SYMBOLS]
    assert all(path.exists() for path in raw)
    sources = [Path(__file__)]
    for value in tuple(sys.modules.values()):
        name = getattr(value, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.suffix == '.py' and path.is_relative_to(ROOT / 'work'):
                sources.append(path)
    fixed = dict(対象=list(SESSIONS), 条件=variants, 条件変更=False, 過去探索条件の再調整=False,
                 基準=early.BASE_ID, 原本SHA256=previous.fingerprints(raw),
                 既存結果SHA256=previous.fingerprints(protected), 実装SHA256=previous.fingerprints(sources),
                 初回枚数={'TOPIX': 5, 'NK225': 10}, 片方向上限={'TOPIX': 10, 'NK225': 20},
                 円倍率={'TOPIX': 1000, 'NK225': 10}, API追加取得数=0, 費用=0, 指定価格約定=True,
                 検証位置='旧16セッションで固定した3方式の追加4セッション追試。今回の損益による条件調整なし。')
    if (HERE / '固定.json').exists():
        assert read(HERE / '固定.json') == fixed
    else:
        save(HERE / '固定.json', fixed)
    return fixed


def prepare() -> tuple[dict, dict, dict]:
    """機能: 各セッションを独立に抽出・信号監査して八入力を結合する。

    引数: なし。返り値: 入力・板特徴・信号(tuple[dict,dict,dict])。
    """
    inputs, features, signals, input_proofs, signal_proofs = {}, {}, {}, [], []
    for session in SESSIONS:
        folder = HERE / 'prepared' / session
        folder.mkdir(parents=True, exist_ok=True)
        previous.HERE = folder
        if (folder / '入力監査.json').exists():
            proof = read(folder / '入力監査.json')
            assert proof['全合格'] and proof['対象'] == session
            previous.verify(proof['出力SHA256'])
            own_inputs = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
            own_features = pickle.loads((folder / 'new_features_depth.pkl').read_bytes())
        else:
            own_inputs, own_features = previous.extract(session)
        own_signals = previous.signal_audit(own_inputs, own_features)
        assert len(own_inputs) == 2 and {key[0] for key in own_inputs} == {session}
        assert not (set(inputs) & set(own_inputs))
        inputs.update(own_inputs)
        features.update(own_features)
        for code, rows in own_signals.items():
            signals.setdefault(code, {}).update(rows)
        input_proofs.append(read(folder / '入力監査.json'))
        signal_proofs += read(folder / '信号監査.json')['検査']
        print(session + ' 二入力と信号の因果監査完了', flush=True)
    previous.HERE = HERE
    for name, value in (('new_inputs.pkl', inputs), ('new_features_depth.pkl', features)):
        (HERE / name).write_bytes(pickle.dumps(value, pickle.HIGHEST_PROTOCOL))
    save(HERE / '入力監査.json', dict(全合格=True, 対象=list(SESSIONS),
         入力被覆=[r for p in input_proofs for r in p['入力被覆']],
         原本監査=[r | {'session': p['対象']} for p in input_proofs for r in p['原本監査']],
         出力SHA256=previous.fingerprints([HERE / 'new_inputs.pkl', HERE / 'new_features_depth.pkl']), API追加取得数=0))
    save(HERE / '信号監査.json', dict(全合格=True, 検査=signal_proofs, API追加取得数=0))
    return inputs, features, signals


def reproduce(inputs: dict, signals: dict, fixed: dict) -> None:
    """機能: 直前二場の十二口座を指紋再現し、固定条件で追加二十四口座を再生する。

    引数: inputs/signals/fixed(dict)。返り値: なし(None)。
    """
    integration.reference.initialize()
    prior_inputs = pickle.loads((PRIOR / 'new_inputs.pkl').read_bytes())
    prior_features = pickle.loads((PRIOR / 'new_features_depth.pkl').read_bytes())
    old_signals = previous.signals(prior_inputs, prior_features, ROOT)
    for variant in fixed['条件']:
        identifier = variant['id']
        prior.activate(prior_inputs, old_signals)
        stored = {(r['session'], r['symbol']): r for r in read(PRIOR / 'ledgers' / (identifier + '.json.gz'))}
        calibration = []
        for key, ready in sorted(prior_inputs.items()):
            _, ledger, _, _ = prior.replay_one(variant, key, ready, False)
            for field in ('result_fingerprints', 'shadow_fingerprints', 'scheduler_fingerprints'):
                assert ledger[field] == stored[key][field], (identifier, key, field)
            calibration.append(dict(session=key[0], symbol=key[1], 実口座と両影の指紋一致=True))
        prior.activate(inputs, signals)
        rows, ledgers, proofs = [], [], []
        for key, ready in sorted(inputs.items()):
            row, ledger, proof, curve = prior.replay_one(variant, key, ready, True)
            config = ledger['config']
            assert config['initial_qty'] == fixed['初回枚数'][key[1]]
            assert config['audit_cap'] == fixed['片方向上限'][key[1]]
            assert config['point_value'] == fixed['円倍率'][key[1]]
            rows.append(row)
            ledgers.append(ledger)
            proofs.append(proof)
            target = HERE / 'curves' / (identifier + '_' + key[0] + '_' + key[1] + '.npz')
            target.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(target, equity=curve)
        for folder, value in (('sessions', rows), ('ledgers', ledgers), ('audits', proofs)):
            save(HERE / folder / (identifier + '.json.gz'), value)
        save(HERE / 'completed' / (identifier + '.json'), dict(id=identifier, 全合格=True,
             旧直前場再現=calibration, 条件変更=False, 新監査数=8, 新因果監査数=8))
        print(identifier + ' 旧四口座指紋一致・新八口座再生と因果検査完了', flush=True)


def assess(inputs: dict) -> None:
    """機能: 旧十九場の統計不変と追加四場を、注文列から再構築して検算する。

    引数: inputs(dict)。返り値: なし(None)。
    """
    old_inputs = pickle.loads((ROOT / 'work/wave_v47/inputs.pkl').read_bytes())
    for folder in (ROOT / 'work/wave_v48/update_20260930', ROOT / 'work/wave_v48/update_20261001', EARLIER, PRIOR):
        more = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
        assert not (set(more) & set(old_inputs))
        old_inputs.update(more)
    assert len(old_inputs) == 38 and not (set(old_inputs) & set(inputs))
    combined = old_inputs | inputs
    old_names = sorted({key[0] for key in old_inputs})
    names = sorted({key[0] for key in combined})
    output = {}
    for identifier in IDS:
        rows, ledgers = [], []
        for folder in (OLD, EARLIER, PRIOR, HERE):
            rows += read(folder / 'sessions' / (identifier + '.json.gz'))
            ledgers += read(folder / 'ledgers' / (identifier + '.json.gz'))
        by_key = {(r['session'], r['symbol']): r for r in rows}
        assert len(rows) == len(ledgers) == len(by_key) == len(combined) == 46
        series = {}
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            curve, totals = previous.charts.chart.reconstruct(combined[key], ledger)
            for field, value in totals.items():
                assert abs(by_key[key][field] - value) < 1e-6, (identifier, key, field)
            series[key] = curve[:, 0]
        periods = {}
        for label, chosen in (('旧19', old_names), ('追加4', list(SESSIONS)), ('全23', names)):
            periods[label] = {symbol: source.period(rows, series, chosen, symbol) for symbol in SYMBOLS}
        expected = read(PRIOR / 'summaries' / (identifier + '.json'))['periods']['全19']
        for symbol in SYMBOLS:
            source.followup.audit.statistics.equal(periods['旧19'][symbol], expected[symbol], '旧十九場不変')
        output[identifier] = periods['全23']
        save(HERE / 'summaries' / (identifier + '.json'), dict(id=identifier, 全合格=True,
             旧十九場全統計一致=True, periods=periods, 対象=list(SESSIONS), 条件変更=False))
    save(HERE / 'assessment.json', output)


def main() -> None:
    """機能: 保存原本だけを使い追加四場の再生と全二十三場の不変検査を実行する。

    引数: なし。返り値: なし(None)。
    """
    socket.socket.connect = previous.deny
    socket.create_connection = previous.deny
    fixed = freeze()
    inputs, features, signals = prepare()
    reproduce(inputs, signals, fixed)
    assess(inputs)
    for field in ('原本SHA256', '既存結果SHA256', '実装SHA256'):
        previous.verify(fixed[field])
    files = [HERE / name for name in ('assessment.json', '入力監査.json', '信号監査.json',
                                      'new_inputs.pkl', 'new_features_depth.pkl')]
    files += [HERE / folder / (identifier + suffix) for identifier in IDS
              for folder, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('audits', '.json.gz'),
                                     ('summaries', '.json'), ('completed', '.json'))]
    files += list((HERE / 'curves').glob('*.npz'))
    save(HERE / 'complete.json', dict(全合格=True, 対象=list(SESSIONS), 条件数=3, 新口座数=24,
         旧再現口座数=12, 全期間場数=23, 旧十九場全統計一致=True, 条件変更=False, API追加取得数=0,
         固定SHA256=previous.sha(HERE / '固定.json'), 出力SHA256=previous.fingerprints(files), 原本実装不変=True))
    print('追加二十四口座と旧十九場不変の全検算完了', flush=True)


if __name__ == '__main__':
    main()
