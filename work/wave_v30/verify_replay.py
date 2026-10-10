"""第6反復の既存結果を全照合し、記録した来歴が一致するときだけ再利用を許す。"""

from __future__ import annotations

import argparse
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
import subprocess
import sys
from zoneinfo import ZoneInfo

import numpy as np
import context_split_runner as runner

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'result_manifest.json'
SYMBOLS = ('TOPIX', 'NK225')


def digest(path: Path) -> str:
    """機能: 保存済みのバイト列の指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: object) -> None:
    """機能: 保存集計にNaN又は無限数があれば拒否する。

    引数: value (object)。返り値: なし (None)。
    """
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite(item)
    elif isinstance(value, float):
        assert math.isfinite(value), '集計に非有限値'


def unique(rows: list[dict], label: str) -> dict:
    """機能: IDを一意の辞書にし、重複を拒否する。

    引数: rows (list[dict])、label (str)。返り値: ID対応 (dict)。
    """
    result = {row['id']: row for row in rows}
    assert len(result) == len(rows), label + 'のID重複'
    return result


def array_hash(arrays: dict, inputs: dict) -> str:
    """機能: 全26入力の配列集合・型・長さ・方向を検査して指紋を作る。

    引数: arrays/inputs (dict)。返り値: 内容指紋 (str)。
    """
    assert set(arrays) == set(inputs), '方向配列の入力集合が不一致'
    hasher = hashlib.sha256()
    for key in sorted(inputs):
        array = arrays[key]
        assert array.dtype == np.int8 and array.shape == (len(inputs[key]['seq']),)
        assert np.isin(array, [-1, 0, 1]).all(), '方向値域が不正'
        hasher.update(str(key).encode())
        hasher.update(array.tobytes())
    return hasher.hexdigest()


def verify_materials(fixed: dict, inputs: dict, summaries: dict, sessions: dict,
                     arrays: dict, all_candidates: list[dict], before: dict) -> dict:
    """機能: 12入口の7管理×26区間と全保存集計を独立に再集計する。

    引数: fixed/inputs/summaries/sessions/arrays/before (dict)、all_candidates (list[dict])。
    返り値: 件数と検算結果 (dict)。売買の新しい再生は行わない。
    """
    finite([fixed, summaries, sessions, all_candidates, before])
    signals = unique(fixed['signals'], '入口仕様')
    managers = unique(fixed['managers'], '管理仕様')
    assert len(signals) == 12 and len(managers) == 7 and fixed['全組合せ数'] == 84
    assert set(managers) == {f'L{i:03d}' for i in range(7)}
    assert len(inputs) == 26 and len({key[0] for key in inputs}) == 13
    assert all({symbol for session, symbol in inputs if session == name} == set(SYMBOLS)
               for name in {key[0] for key in inputs})
    assert set(summaries) == set(sessions) == set(arrays) == set(signals)
    candidates, states, mains, owns = [], set(), set(), set()
    for identifier, signal in signals.items():
        summary = summaries[identifier]
        assert summary['signal'] == signal, 'summaryと固定仕様が不一致'
        hashes = {source: array_hash(arrays[identifier][source], inputs) for source in ('entry', 'main', 'own')}
        assert hashes['entry'] == summary['state_hash']
        assert hashes['main'] == summary['context_hash']
        assert hashes['own'] == summary['own_context_hash']
        for key in inputs:
            main, own = arrays[identifier]['main'][key], arrays[identifier]['own'][key]
            assert np.all((main == 0) | (main == own)) and np.all(main[own == 0] == 0)
        states.add(hashes['entry']); mains.add(hashes['main']); owns.add(hashes['own'])
        current = unique(summary['candidates'], 'summary候補')
        details = unique(sessions[identifier], 'セッション候補')
        expected_ids = {identifier + '__' + manager for manager in managers}
        assert set(current) == set(details) == expected_ids, '7管理の不足・余分'
        for name in sorted(expected_ids):
            candidate, detail = current[name], details[name]
            manager_id = name.split('__')[1]
            assert candidate['signal_id'] == identifier and candidate['manager_id'] == manager_id
            assert candidate['signal_family'] == signal['family']
            assert candidate['manager_family'] == managers[manager_id]['family']
            rows = detail['rows']
            assert len(rows) == 26 and {(r['session'], r['symbol']) for r in rows} == set(inputs)
            for row in rows:
                assert row['id'] == name
                assert row['gross_profit_yen'] >= 0 and row['gross_loss_yen'] >= 0 and row['drawdown_yen'] >= 0
                assert abs(row['net_yen'] - (row['gross_profit_yen'] - row['gross_loss_yen'])) < 1e-6
                assert abs(row['net_yen'] - (row['cycle_profit_yen'] - row['cycle_loss_yen'])) < 1e-6
                for field in ('profit_units', 'loss_units', 'zero_units', 'closed_units', 'cycles', 'cycle_wins', 'cycle_losses'):
                    assert not isinstance(row[field], bool) and float(row[field]).is_integer() and row[field] >= 0
                assert row['closed_units'] == row['profit_units'] + row['loss_units'] + row['zero_units']
                assert row['cycle_wins'] + row['cycle_losses'] <= row['cycles']
                cap = 10 if row['symbol'] == 'TOPIX' else 20
                assert 0 <= row['max_long'] <= cap and 0 <= row['max_short'] <= cap
                profits = row['two_largest_cycle_profits']
                assert len(profits) <= 2 and profits == sorted(profits, reverse=True) and all(v > 0 for v in profits)
                assert sum(profits) <= row['cycle_profit_yen'] + 1e-6
            repeated = runner.diagnostics(rows)
            assert repeated == candidate['symbols'], 'セッション明細と期間集計が不一致'
            assert candidate['failures'] == runner.failures(repeated), '最低基準判定が不一致'
            assert isinstance(candidate['ledger_hash'], str) and len(candidate['ledger_hash']) == 64
            int(candidate['ledger_hash'], 16)
            candidates.append(candidate)
    candidates.sort(key=lambda row: row['id'])
    assert all_candidates == candidates, '全期間集計と12保存summaryが不一致'
    expected_before = {'全条件数': 84, '最低基準通過数': sum(not c['failures'] for c in candidates),
        '方向系列の一意数': len(states), '売買台帳の一意数': len({c['ledger_hash'] for c in candidates}),
        '中期撤回系列の一意数': len(mains), '自己撤回系列の一意数': len(owns),
        '反証候補': candidates, '未知検証ではない': True}
    assert {key: value for key, value in before.items() if key != '日時'} == expected_before
    return {'全12入口確認': True, '全84管理結果確認': True, '全2184区間明細確認': True,
            '保存方向36集合確認': True, '全期間再集計一致': True, '最低基準再判定一致': True}


def verify_fingerprints(expected: dict, actual: dict) -> None:
    """機能: 登録後のファイル追加・削除・内容変更を拒否する。

    引数: expected/actual (dict[str,str])。返り値: なし (None)。
    """
    assert actual == expected, '登録済み成果又は固定元のSHAに変更があるため再利用を拒否'


def load_arrays(path: Path, expected_keys: set) -> dict:
    """機能: 余分なキーを含めてNPZの区間集合を検査し読み込む。

    引数: path (Path)、expected_keys (set)。返り値: 方向配列 (dict)。
    """
    with np.load(path, allow_pickle=False) as archive:
        assert set(archive.files) == {'|'.join(key) for key in expected_keys}
        return {key: archive['|'.join(key)] for key in expected_keys}


def collect() -> tuple[dict, dict, dict]:
    """機能: 全固定元・全科学成果を同じ読取りバイト列で検算する。

    引数: なし。返り値: 監査・ファイルSHA・意味内容SHA (tuple[dict,dict,dict])。
    進捗表示は科学成果ではないため登録対象外。現在データを参照しない。
    """
    fingerprints, meanings = {}, {}

    def tracked(path: Path) -> object:
        """機能: JSONの読取りと同じバイト列から指紋を採取する。

        引数: path (Path)。返り値: JSONの内容 (object)。
        """
        raw = path.read_bytes()
        fingerprints[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        value = json.loads((gzip.decompress(raw) if path.suffix == '.gz' else raw).decode('utf-8'))
        semantic = {key: item for key, item in value.items() if key != '日時'} if path.name == '反証前の候補固定.json' else value
        meanings[str(path.resolve())] = hashlib.sha256(json.dumps(semantic, ensure_ascii=False, sort_keys=True,
                                              separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        return value

    fixed = tracked(HERE / '探索条件の固定.json')
    for relative, expected in fixed['SHA256'].items():
        path = HERE.parent / relative
        actual = digest(path)
        assert actual == expected, '固定した元入力又はコードが変更された'
        fingerprints[str(path.resolve())] = actual
    implementation = tracked(HERE / '反証実装の固定.json')
    for relative, expected in implementation['SHA256'].items():
        path = HERE.parent / relative
        actual = digest(path)
        assert actual == expected, '反証固定とコードが不一致'
        fingerprints[str(path.resolve())] = actual
    structure = tracked(HERE / 'context_structure_before_pnl.json')
    assert structure['構造検査合格'] is True and structure['損益前監査完了'] is True
    assert structure['損益ファイル読取'] is False and structure['売買再生'] is False
    assert structure['API取得数'] == 0 and structure['現在データ使用'] is False
    assert structure['探索仕様SHA256'] == digest(HERE / '探索条件の固定.json')
    for path, expected in structure['参照SHA256'].items():
        actual = digest(Path(path))
        assert actual == expected, '構造監査の元ファイルが不一致'
        fingerprints[str(Path(path).resolve())] = actual
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    summaries, sessions, arrays = {}, {}, {}
    for signal in fixed['signals']:
        identifier = signal['id']
        summaries[identifier] = tracked(HERE / 'summaries' / (identifier + '.json'))
        sessions[identifier] = tracked(HERE / 'sessions' / (identifier + '.json.gz'))
        arrays[identifier] = {}
        for source, folder, old_directory, old_id in (
            ('entry', 'directions', HERE.parent / 'wave_v27/directions', identifier),
            ('main', 'contexts', HERE.parent / 'wave_v28/contexts', identifier),
            ('own', 'contexts_own', HERE.parent / 'wave_v28/contexts', fixed['own_signals'][identifier]['id']),
        ):
            path = HERE / folder / (identifier + '.npz')
            fingerprints[str(path.resolve())] = digest(path)
            generated = load_arrays(path, set(inputs))
            original = load_arrays(old_directory / (old_id + '.npz'), set(inputs))
            for key in inputs:
                np.testing.assert_array_equal(generated[key], original[key])
            arrays[identifier][source] = generated
            meanings[str(path.resolve())] = array_hash(generated, inputs)
    audit = verify_materials(fixed, inputs, summaries, sessions, arrays,
            tracked(HERE / '全条件の期間集計.json.gz'), tracked(HERE / '反証前の候補固定.json'))
    for path, expected in fingerprints.items():
        assert digest(Path(path)) == expected, '検算中の原本又は生成物変更'
    audit['全保存配列と凍結元一致'] = True
    audit['構造監査と参照SHA一致'] = True
    return audit, fingerprints, meanings


def run(workers: int, initialize: bool = False, replay: bool = False) -> dict:
    """機能: 初回整合証跡の登録又は既存証跡照合後だけ凍結runnerを起動する。

    引数: workers (int)、initialize/replay (bool)。返り値: 来歴記録 (dict)。
    今回の初回再利用0は親の起動時確認であり、後日の集計照合から推定しない。
    """
    assert not (initialize and replay), '初回登録と再実行は分ける'
    assert workers > 0
    previous = None
    if MANIFEST.exists():
        assert not initialize, '既存証跡の初期化は禁止'
        previous = runner.read(MANIFEST)
        assert previous['検査コードSHA256'] == digest(Path(__file__))
    else:
        assert initialize and not replay, '最初に --initialize で既存全資料を登録する'
    audit, fingerprints, meanings = collect()
    if previous is not None:
        verify_fingerprints(previous['ファイルSHA256'], fingerprints)
        verify_fingerprints(previous['意味内容SHA256'], meanings)
    record = previous or {'作成日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        '用途': '結果公開後に追加した整合ガード。選抜条件・利益順位・凍結実装は変更しない。',
        '初回主探索の再利用件数': 0,
        '初回来歴の根拠': '親エージェントが新規領域の保存結果0件から起動して完了したと確認。後日の集計だけで過去の実行を証明する記録ではない。',
        '対象外': '進捗表示、後続の反証・乱数・波成果はこの主探索の再利用記録に含めない。',
        '会計範囲': '保存セッションの全玉収支と期間集計を照合。台帳SHAは集計間の一致であり、原取引台帳を再生して再計算していない。',
        '再実行記録': []}
    if replay:
        previous_manifest_sha = digest(MANIFEST)
        subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'context_split_runner.py'), '--workers', str(workers)],
                       cwd=HERE.parents[1], check=True)
        after_audit, after_fingerprints, after_meanings = collect()
        verify_fingerprints(meanings, after_meanings)
        variable = {str((HERE / '全条件の期間集計.json.gz').resolve()), str((HERE / '反証前の候補固定.json').resolve())}
        assert set(after_fingerprints) == set(fingerprints)
        assert all(after_fingerprints[path] == value for path, value in fingerprints.items() if path not in variable)
        record['再実行記録'].append({'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
            '前記録SHA256': previous_manifest_sha, '保存結果再利用入口数': 12,
            '科学内容の変更なし': True, '許容バイト差': '全期間gzipヘッダー、反証前候補の日時のみ。解析内容は日時以外全一致。'})
        audit, fingerprints, meanings = after_audit, after_fingerprints, after_meanings
    record.update(最終確認日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                  検査コードSHA256=digest(Path(__file__)), 監査=audit,
                  ファイルSHA256=fingerprints, 意味内容SHA256=meanings, 現在データ使用=False, API取得数=0)
    runner.save(MANIFEST, record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, default=12)
    options = parser.parse_args()
    result = run(options.workers, options.initialize, options.run)
    print('主探索の全84・2184区間・保存方向36集合と来歴を検証。現在使用なし。', flush=True)
