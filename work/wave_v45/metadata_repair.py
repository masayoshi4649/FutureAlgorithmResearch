"""売買成果を変えず、新規完了記録の省略された由来欄だけを補う。"""

from __future__ import annotations

from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

import runner

HERE, ROOT = runner.HERE, runner.ROOT


def amended(record: dict, expected_id: str) -> dict:
    """機能: 新規完了記録だけへ既知再利用なしを明示する。

    引数: record(dict)、expected_id(str)。返り値: 一欄だけ補完した記録(dict)。
    売買配列・集計・指紋を変更せず、不整合を拒否する。
    """
    assert record['id'] == expected_id and record['全合格'] is True
    assert record['既知成果引継ぎ'] is False and record['新売買再生'] is True
    assert 'reuse_source' not in record
    assert (record['全入力数'], record['因果入力数']) == (26, 4)
    assert len(record['出力SHA256']) == 7
    result = deepcopy(record)
    result['reuse_source'] = None
    assert {k:v for k,v in result.items() if k != 'reuse_source'} == record
    return result


def check() -> dict:
    """機能: 一欄補完と、既知記録・不整合の拒否を人工資料で確かめる。

    引数: なし。返り値: 人工検査証跡(dict)。実損益は読まない。
    """
    sample = dict(id='人工', 全合格=True, 既知成果引継ぎ=False, 新売買再生=True,
                  全入力数=26, 因果入力数=4, 出力SHA256={str(i):'a'*64 for i in range(7)})
    result = amended(sample, '人工')
    assert 'reuse_source' not in sample and result['reuse_source'] is None
    corruptions = [dict(id='別条件'), dict(全合格=False), dict(既知成果引継ぎ=True),
        dict(新売買再生=False), dict(reuse_source=None), dict(全入力数=25),
        dict(因果入力数=3), dict(出力SHA256={})]
    for difference in corruptions:
        try:
            amended(dict(sample, **difference), '人工')
        except AssertionError:
            continue
        raise AssertionError(difference)
    return dict(全合格=True, 正常件数=1, 不整合拒否件数=len(corruptions), 新実損益読取=False)


def repair() -> dict:
    """機能: 元144資料を保全し、新規142完了記録と2一覧を一欄だけ補う。

    引数: なし。返り値: 前後指紋と経済資料不変の証跡(dict)。
    両実行が完了した後だけ実行する。採否・固定コード・七成果は編集しない。
    """
    proof_path = HERE/'metadata_repair.json'
    if proof_path.exists():
        proof = runner.read(proof_path)
        for group in ('入力資料SHA256','出力資料SHA256','全経済成果SHA256','既知11SHA256'):
            runner.verify(proof[group])
        assert proof['実装SHA256'] == runner.digest(Path(__file__))
        return proof
    fixed_path = HERE/'探索条件の固定.json'
    fixed = runner.read(fixed_path)
    runner.verify(fixed['参照資料SHA256'])
    fixed_sha = runner.digest(fixed_path)
    specs = fixed['conditions'] + fixed['supplementary']
    known = set(fixed['既知再利用'])
    assert len(specs) == 153 and len(known) == 11
    staged, economic, known_sha = {}, {}, {}
    fresh_count = 0
    for directory, count in ((HERE,25),(HERE/'supplementary',128)):
        path = directory/'主再生の完了.json'
        header = runner.read(path)
        assert header['全合格'] is True and header['探索固定SHA256'] == fixed_sha
        assert (header['全条件数'],header['全入力数'],header['因果入力数']) == (count,count*26,count*4)
        records = {r['id']:r for r in header['records']}
        selected = [s for s in specs if (s['role']=='supplementary') == (directory != HERE)]
        assert len(records) == len(header['records']) == count and set(records) == {s['id'] for s in selected}
        modified = deepcopy(header)
        for spec in selected:
            identifier = spec['id']
            record_path = directory/'completed'/(identifier+'.json')
            record = runner.read(record_path)
            assert record == records[identifier] and record['探索固定SHA256'] == fixed_sha
            assert not (set(economic) & set(record['出力SHA256']))
            economic.update(record['出力SHA256'])
            if identifier in known:
                assert record['既知成果引継ぎ'] is True and record['新売買再生'] is False
                assert record['reuse_source'] == fixed['既知再利用'][identifier]
                known_sha[record_path.relative_to(ROOT).as_posix()] = runner.digest(record_path)
                continue
            current = amended(record, identifier)
            staged[record_path] = current
            offset = next(i for i,r in enumerate(modified['records']) if r['id'] == identifier)
            modified['records'][offset] = current
            fresh_count += 1
        assert {k:v for k,v in modified.items() if k != 'records'} == {k:v for k,v in header.items() if k != 'records'}
        staged[path] = modified
    assert fresh_count == 142 and len(staged) == 144 and len(economic) == 1071 and len(known_sha) == 11
    runner.verify(economic)
    # ----------------------------------------
    # 全候補の検証後に原本メタ資料をバイト保存し、それから補完する。
    saved, before, changes = {}, {}, []
    for path in staged:
        relative = path.relative_to(ROOT).as_posix()
        target = HERE/'補完前の完了記録'/path.relative_to(HERE)
        raw = path.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == raw
        else:
            target.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        saved[target.relative_to(ROOT).as_posix()] = digest
        before[relative] = digest
    runner.verify(saved)
    after = {}
    for path, value in staged.items():
        runner.save(path, value)
        assert runner.read(path) == value
        relative = path.relative_to(ROOT).as_posix()
        after[relative] = runner.digest(path)
        changes.append(dict(対象=relative, 補完前SHA256=before[relative], 補完後SHA256=after[relative],
                            保全先=(HERE/'補完前の完了記録'/path.relative_to(HERE)).relative_to(ROOT).as_posix()))
    runner.verify(economic)
    runner.verify(known_sha)
    runner.verify(fixed['参照資料SHA256'])
    assert runner.digest(fixed_path) == fixed_sha
    result = dict(全合格=True, 新規条件数=fresh_count, 修復資料数=len(staged), 元資料全バイト保全=True,
        変更はreuse_sourceのnull補完のみ=True, 全七成果不変=True, 既知11完了記録不変=True,
        売買再生数=0, 新損益値の読取=False, 探索固定SHA256=fixed_sha,
        実装SHA256=runner.digest(Path(__file__)), 人工検査=check(),
        原資料SHA256=before, 入力資料SHA256=saved, 出力資料SHA256=after,
        全経済成果SHA256=economic, 既知11SHA256=known_sha, 変更前後=changes,
        理由='新規実行の完了記録は由来欄を省略したが、凍結済み完備監査は明示nullを要求した。')
    runner.save(proof_path, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    value = check() if args.check else repair()
    print({k:v for k,v in value.items() if not isinstance(v,(dict,list))}, flush=True)
