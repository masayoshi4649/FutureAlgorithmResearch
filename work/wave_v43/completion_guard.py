"""凍結済み完備処理の前後へ、成果集合・旧単一窓・指定波の完全性を追加する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import math
from pathlib import Path

import numpy as np

import runner

HERE, ROOT = runner.HERE, runner.ROOT
FOLDERS = (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('audits', '.json.gz'),
           ('waves', '.json.gz'), ('causality', '.json'), ('signal_use', '.json'), ('summaries', '.json'))


def paths_for(identifier: str) -> set[str]:
    """機能: 一条件の保存必須7実体の相対パス集合を返す。

    引数: identifier(str)。返り値: 固定された7パス(set[str])。
    """
    assert isinstance(identifier, str) and identifier and '/' not in identifier and '\\' not in identifier
    return {(HERE/folder/(identifier+suffix)).relative_to(ROOT).as_posix() for folder, suffix in FOLDERS}


def record_check(spec: dict, record: dict, frozen_sha: str) -> None:
    """機能: 成果指紋の欠落・余分・別ID参照と旧同値件数の付替えを拒否する。

    引数: spec/record(dict)、frozen_sha(str)。返り値: なし(None)。
    """
    assert record['id'] == spec['id'] and record['全合格'] is True
    assert record['探索固定SHA256'] == frozen_sha
    assert record['全入力数'] == 26 and record['因果入力数'] == 4
    assert type(record['旧単一窓一致入力数']) is int
    assert record['旧単一窓一致入力数'] == (26 if runner.legacy_id(spec) else 0)
    assert set(record['出力SHA256']) == paths_for(spec['id'])
    assert all(isinstance(v, str) and len(v) == 64 and set(v) <= set('0123456789abcdef')
               for v in record['出力SHA256'].values())


def keyed(records: list[dict], expected: set[tuple]) -> dict:
    """機能: 26場銘柄が一意で全て揃うことを確認する。

    引数: records(list[dict])、expected(set[tuple])。返り値: 場銘柄による辞書(dict)。
    """
    result = {(r['session'], r['symbol']): r for r in records}
    assert len(records) == len(result) == len(expected) == 26 and set(result) == expected
    return result


def wave_check(identifier: str, rows: list[dict], episodes: list[dict]) -> None:
    """機能: 固定4波×2銘柄の一意集合と方向・時刻・20分判定を照合する。

    引数: identifier(str)、rows/episodes(list[dict])。返り値: なし(None)。
    保有時間の独立再積分ではなく、凍結済み計測の対象と保存判定の完全性を検査する。
    """
    expected = {(e['id'], e['session'], symbol): e for e in episodes for symbol in runner.old.SYMBOLS}
    actual = {(r['wave'], r['session'], r['symbol']): r for r in rows}
    assert len(episodes) == 4 and len(expected) == len(actual) == len(rows) == 8
    assert set(actual) == set(expected)
    for key, row in actual.items():
        episode = expected[key]
        assert row['method'] == identifier
        assert (row['波方向'], row['開始'], row['終了'], row['波名']) == (
            episode['side'], episode['start'], episode['end'], episode['name'])
        duration = (datetime.fromisoformat(episode['end'])-datetime.fromisoformat(episode['start'])).total_seconds()/60
        assert type(row['区間分']) in (int, float) and math.isfinite(row['区間分'])
        assert abs(row['区間分']-duration) <= 1e-8
        minutes = row['正方向ネット保有分']
        assert type(minutes) in (int, float) and math.isfinite(minutes) and -1e-8 <= minutes <= duration+1e-8
        assert type(row['正方向ネット20分目安達成']) is bool
        assert row['正方向ネット20分目安達成'] == (minutes >= 20-1e-9)


def array_fingerprints(ledger: dict) -> None:
    """機能: 保存配列の型・形状を復元し、台帳に記録した指紋と再比較する。

    引数: ledger(dict)。返り値: なし(None)。保存されない全行曲線は旧指紋との一致で結合する。
    """
    fingerprints = ledger['result_fingerprints']
    assert set(fingerprints) == set(runner.FIELDS)
    for field in runner.STORED:
        entry = fingerprints[field]
        values = np.asarray(ledger[field], dtype=np.dtype(entry['dtype'])).reshape(entry['shape'])
        assert list(values.shape) == entry['shape'] and values.dtype.str == entry['dtype']
        assert hashlib.sha256(values.tobytes()).hexdigest() == entry['SHA256'], field


def legacy_check(current: list[dict], previous: list[dict], expected: set[tuple]) -> int:
    """機能: 元単一窓の26口座について旧15結果・影10結果の全指紋を実物照合する。

    引数: current/previous(list[dict])、expected(set[tuple])。返り値: 一致口座数(int)。
    """
    new, old = keyed(current, expected), keyed(previous, expected)
    for key in expected:
        array_fingerprints(new[key])
        array_fingerprints(old[key])
        assert new[key]['result_fingerprints'] == old[key]['result_fingerprints'], (key, '元単一結果')
        assert new[key]['shadow_fingerprints'] == old[key]['shadow_fingerprints'], (key, '元単一影')
    return len(expected)


def sources() -> dict:
    """機能: 探索前に凍結された人工・信号・採否の成功と指紋を確認する。

    引数: なし。返り値: 旧探索固定(dict)。新損益の保存物は読み込まない。
    """
    fixed = runner.read(HERE/'探索条件の固定.json')
    assert fixed['conditions'] == runner.design.catalog()
    assert (fixed['全条件数'], fixed['全入力数'], fixed['因果入力数'], fixed['旧単一窓一致入力数']) == (32,832,128,156)
    runner.verify(fixed['参照資料SHA256'])
    signal = runner.read(HERE/'signal_audit.json')
    assert signal['全合格'] is True and signal['旧3倍率完全一致数'] == 78
    assert all(signal[k] == 312 for k in ('全方向セル数','prefix数','future数','reflection数','同時刻切断数'))
    artificial = runner.read(HERE/'check_runner.json')
    assert artificial['全合格'] is True and artificial['人工入力検査数'] == 128
    assert artificial['新実相場損益'] is False
    assessment = runner.read(HERE/'check_assessment.json')
    assert assessment['全合格'] is True and assessment['新実相場損益'] is False
    assert assessment['合成検査数'] == 54 and assessment['不正資料拒否数'] == 26
    return fixed


def prepare() -> dict:
    """機能: 結果を読む前に追加する完全性検査と人工反例を別固定へ保存する。

    引数: なし。返り値: 追加の固定資料(dict)。旧固定・売買・採否のファイルは変更しない。
    """
    original = sources()
    episodes = runner.read(HERE.parent/'wave_v38/探索条件の固定.json')['指定波']
    tests = runner.read(HERE/'completion_guard_test.json')
    assert tests['全合格'] is True and tests['新損益読取'] is False
    assert tests['実装SHA256'] == runner.digest(Path(__file__))
    files = [Path(__file__), HERE/'completion_guard_test.py', HERE/'completion_guard_test.json',
             HERE/'探索条件の固定.json']
    refs = dict(original['参照資料SHA256'])
    for path in files:
        relative, sha = path.relative_to(ROOT).as_posix(), runner.digest(path)
        assert relative not in refs or refs[relative] == sha
        refs[relative] = sha
    output = dict(対象条件=original['conditions'], 必須出力={s['id']:sorted(paths_for(s['id'])) for s in original['conditions']},
        元単一窓対応={s['id']:runner.legacy_id(s) for s in original['conditions'] if runner.legacy_id(s)},
        指定波=episodes, 全条件数=32, 全必須出力数=224, 旧単一窓一致入力数=156, 全指定波数=256,
        原完備を呼ぶ前に実施=True, 売買変更=False, 採否変更=False, 対象変更=False,
        新損益読取=False, SHA256=refs)
    path = HERE/'追加完備の固定.json'
    if path.exists():
        assert runner.read(path) == output
    else:
        runner.save(path, output)
    return output


def collect() -> dict:
    """機能: 全成果の前検査を通した後だけ旧完備を呼び、前後の全指紋を結合する。

    引数: なし。返り値: 追加完備証跡(dict)。元completeの採否式や返り値は変更しない。
    """
    extra = runner.read(HERE/'追加完備の固定.json')
    runner.verify(extra['SHA256'])
    original = sources()
    assert extra['対象条件'] == original['conditions']
    frozen_sha = runner.digest(HERE/'探索条件の固定.json')
    finished = runner.read(HERE/'主再生の完了.json')
    assert finished['全合格'] is True and finished['探索固定SHA256'] == frozen_sha
    assert (finished['全条件数'], finished['全入力数'], finished['因果入力数'], finished['旧単一窓一致入力数']) == (32,832,128,156)
    records = {r['id']:r for r in finished['records']}
    assert len(records) == len(finished['records']) == 32 and set(records) == {s['id'] for s in original['conditions']}
    expected = {(n,s) for n in original['全セッション'] for s in runner.old.SYMBOLS}
    refs = dict(extra['SHA256'])

    def bind(path: Path, expected_sha: str | None = None) -> None:
        """機能: 前後検査する実体指紋を競合なく追加する。

        引数: path(Path)、expected_sha(str|None)。返り値: なし(None)。
        """
        relative, actual = path.relative_to(ROOT).as_posix(), runner.digest(path)
        assert expected_sha is None or actual == expected_sha
        assert relative not in refs or refs[relative] == actual, relative
        refs[relative] = actual

    bind(HERE/'追加完備の固定.json')
    bind(HERE/'主再生の完了.json')
    legacy_count = wave_count = 0
    required_outputs = {}
    checks = []
    for spec in original['conditions']:
        identifier = spec['id']
        path = HERE/'completed'/(identifier+'.json')
        record = runner.read(path)
        assert record == records[identifier]
        record_check(spec, record, frozen_sha)
        bind(path)
        assert not (set(required_outputs) & set(record['出力SHA256']))
        required_outputs.update(record['出力SHA256'])
        for relative, sha in record['出力SHA256'].items():
            bind(ROOT/relative, sha)
        waves = runner.read(HERE/'waves'/(identifier+'.json.gz'))
        wave_check(identifier, waves, extra['指定波'])
        wave_count += len(waves)
        old_id = runner.legacy_id(spec)
        proofs = keyed(runner.read(HERE/'audits'/(identifier+'.json.gz')), expected)
        assert all(p['旧単一窓一致'] is bool(old_id) for p in proofs.values())
        actual_count = 0
        if old_id:
            previous = HERE.parent/'wave_v38/ledgers'/(old_id+'.json.gz')
            relative = previous.relative_to(ROOT).as_posix()
            assert relative in original['参照資料SHA256']
            bind(previous, original['参照資料SHA256'][relative])
            actual_count = legacy_check(runner.read(HERE/'ledgers'/(identifier+'.json.gz')),
                                        runner.read(previous), expected)
        assert actual_count == record['旧単一窓一致入力数']
        legacy_count += actual_count
        checks.append(dict(id=identifier, 必須七実体一致=True, 旧全指紋一致入力数=actual_count, 指定八波一意=True))
    assert legacy_count == 156 and wave_count == 256
    runner.verify(refs)
    complete = runner.module('window_additional_guard_original_complete', HERE/'complete.py')
    result = complete.complete()
    assert result['全合格'] is True and (result['全条件数'],result['全入力数'],result['因果入力数']) == (32,832,128)
    assert result['旧単一窓一致入力数'] == legacy_count
    for relative, sha in result['出力SHA256'].items():
        bind(ROOT/relative, sha)
    bind(HERE/'完備監査.json')
    runner.verify(refs)
    output = dict(全合格=True, 追加完備完了=True, 全条件数=32, 全入力数=832,
        全必須出力数=224, 旧単一窓一致入力数=legacy_count, 全指定波数=wave_count,
        元完備全合格=True, 前後全参照不変=True, 売買変更=False, 採否変更=False,
        元完備SHA256=runner.digest(HERE/'完備監査.json'),
        追加固定SHA256=runner.digest(HERE/'追加完備の固定.json'),
        実装SHA256=runner.digest(Path(__file__)), 必須成果SHA256=required_outputs,
        検査=checks, 参照資料SHA256=refs, 現在API取得数=0, 保存ライブ使用=False)
    runner.save(HERE/'追加完備監査.json', output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    result = prepare() if args.prepare else collect()
    print('追加完全性規則を結果未読で固定しました。' if args.prepare else '32条件・旧156口座・256波の追加完備監査に合格しました。', flush=True)
