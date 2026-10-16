"""共通知見の正本検査、ローカル閲覧用データ生成、試行の事前照合を行う。"""

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = HERE/'data'
FILES = ('knowledge.json', 'trials.json', 'studies.json')
sys.dont_write_bytecode = True


def read(path: Path) -> dict:
    """
    機能: UTF-8のJSON正本を読み、非有限数値を拒否する。
    引数: path(Path)は正本又は新しい試行計画。
    返り値: dictは読取内容。
    """
    value = json.loads(path.read_text(encoding='utf-8'))
    json.dumps(value, allow_nan=False)
    return value


def digest(path: Path) -> str:
    """
    機能: ファイルの内容指紋を計算する。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def local_path(name: str) -> Path:
    """
    機能: 根拠パスがプロジェクト内の実在ファイルであることを確認する。
    引数: name(str)はルートからの相対パス。
    返り値: Pathは検証済み絶対パス。外部URLや上位参照を拒否する。
    """
    parts = name.replace('\\', '/').split('/')
    assert all(part and part != '..' and ':' not in part for part in parts), name
    path = ROOT.joinpath(*parts).resolve()
    assert path.is_relative_to(ROOT) and path.is_file(), name
    return path


def validate(result: dict, deep: bool = False) -> None:
    """
    機能: 正本の識別子、根拠、必須構造と任意の根拠指紋を検査する。
    引数: result(dict)は保存前又は読取済みの三正本、deep(bool)は根拠SHAの照合指定。
    返り値: None。不正なら正本を書き換える前に停止する。
    """
    groups = (result['knowledge']['findings'], result['trials']['trials'],
              result['trials']['repetition_audit'], result['studies']['studies'])
    verified = {}
    for rows in groups:
        assert len({row['id'] for row in rows}) == len(rows), '識別子が重複しています'
        for row in rows:
            assert row['id'] and (row.get('title') or row.get('name'))
            for evidence in row.get('evidence', []):
                path = local_path(evidence['path'])
                if deep and evidence.get('sha256'):
                    if path not in verified:
                        verified[path] = digest(path)
                    assert verified[path] == evidence['sha256'], evidence['path']
            for field in ('readme', 'report'):
                if row.get(field):
                    local_path(row[field])
            if row.get('spec'):
                spec = row['spec']
                manifests = spec['data']['input_manifests']
                assert isinstance(manifests, list) and manifests, '入力目録の位置とSHAが必要です'
                sessions = spec['data']['sessions']
                assert isinstance(sessions, list) and sessions and len(sessions) == len(set(sessions))
                implementation = spec['implementation']
                assert isinstance(implementation, dict) and implementation
                references = manifests + [dict(path=name, sha256=expected) for name,expected in implementation.items()]
                for reference in references:
                    path = local_path(reference['path'])
                    expected = reference['sha256']
                    assert isinstance(expected, str) and len(expected) == 64 and all(letter in '0123456789abcdef' for letter in expected)
                    if deep:
                        if path not in verified:
                            verified[path] = digest(path)
                        assert verified[path] == expected, reference['path']


def load(deep: bool = False) -> dict:
    """
    機能: 正本を読み、内容と任意の根拠指紋を照合する。
    引数: deep(bool)は根拠SHAの照合指定。
    返り値: dictは三つの正本と各指紋。
    """
    result = {Path(name).stem: read(DATA/name) for name in FILES}
    validate(result, deep)
    result['source_sha256'] = {name: digest(DATA/name) for name in FILES}
    return result


def bundle(value: dict) -> str:
    """
    機能: file方式でも開ける閲覧専用データをJSON正本から作る。
    引数: value(dict)は検証済み三正本。
    返り値: strは生成JavaScript。ビューの構造や研究判断を含めない。
    """
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return '// 自動生成。正本はdata/*.jsonです。直接編集しないでください。\nwindow.KNOWLEDGE_DATA = '+payload+';\n'


def rebuild(deep: bool = False) -> dict:
    """
    機能: ビューを変更せず閲覧専用データだけを更新する。
    引数: deep(bool)は根拠指紋確認指定。
    返り値: dictは登録件数。金融再生や外部通信はしない。
    """
    value = load(deep)
    (DATA/'view-data.js').write_text(bundle(value), encoding='utf-8', newline='\n')
    return dict(知見=len(value['knowledge']['findings']), 試行=len(value['trials']['trials']),
                重複点検=len(value['trials']['repetition_audit']), 過去資料=len(value['studies']['studies']))


def analyzer() -> object:
    """
    機能: 同じフォルダの副作用を持たない照合部品を読み込む。
    引数: なし。
    返り値: objectはanalyze関数を持つ部品。
    """
    spec = importlib.util.spec_from_file_location('共通知見の試行照合', HERE/'duplicate_check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(proposal: dict) -> dict:
    """
    機能: 新計画を既登録試行と照合する。
    引数: proposal(dict)はspecを含む実行前の計画。
    返り値: dictは同一性・差分・不足情報。旧未整理試行の不存在は証明しない。
    """
    return analyzer().analyze(proposal, read(DATA/'trials.json')['trials'])


def store_trial(proposal: dict) -> dict:
    """
    機能: 実行前の試行と照合結果を保存し、再検証理由を必須にする。
    引数: proposal(dict)は新しい識別子・条件・目的・理由・比較元を持つ計画。
    返り値: dictは保存した試行。金融を実行又は許可する機能ではない。
    """
    table = read(DATA/'trials.json')
    assert proposal.get('id') and proposal.get('name')
    assert proposal['id'] not in {row['id'] for row in table['trials']}, '既登録IDは再利用できません'
    assert proposal.get('purpose') in ('新仮説', '新データ', '不具合修正', '独立再検証', '条件比較')
    assert proposal.get('question') and proposal.get('change') and proposal.get('repeat_reason')
    result = check(proposal)
    assert result['proposal_complete'], '機械照合に必要な条件が不足しています'
    # ----------------------------------------
    # 完全一致は独立再検証又は修正確認の説明付き登録に限り、通常は既存結果を再利用します。
    exact = [item for item in result['matches'] if item['kind'] == '完全同一']
    if exact:
        assert proposal['purpose'] == '独立再検証', '完全同一です。保存済み結果を再利用してください'
        assert proposal.get('compares_to'), '独立再検証には比較元IDが必要です'
    known_ids = {row['id'] for row in table['trials']}
    assert set(proposal.get('compares_to', [])).issubset(known_ids)
    row = dict(proposal, status='未実行', preflight=result)
    table['trials'].append(row)
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    proposed_data = load()
    proposed_data['trials'] = table
    validate(proposed_data, deep=True)
    serialized = json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    proposed_data['source_sha256']['trials.json'] = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    rendered = bundle(proposed_data)
    history = DATA/'history'
    history.mkdir(exist_ok=True)
    previous = (DATA/'trials.json').read_bytes()
    old_hash = hashlib.sha256(previous).hexdigest()
    snapshot = history/('trials_'+old_hash+'.json')
    if not snapshot.exists():
        snapshot.write_bytes(previous)
    temporary = DATA/'trials.json.tmp'
    temporary.write_text(serialized, encoding='utf-8', newline='\n')
    staged_view = DATA/'view-data.js.tmp'
    staged_view.write_text(rendered, encoding='utf-8', newline='\n')
    temporary.replace(DATA/'trials.json')
    try:
        staged_view.replace(DATA/'view-data.js')
    except OSError:
        (DATA/'trials.json').write_bytes(previous)
        raise
    return row


def main() -> None:
    """
    機能: 生成・整合検査・計画照合・計画登録をCLIから実行する。
    引数: CLIのcommand(str)、--proposal(Path)、--deep(bool)。
    返り値: None。照合結果は標準出力へJSONで表示する。
    """
    parser = argparse.ArgumentParser(description='共通知見の更新と試行の重複確認')
    parser.add_argument('command', choices=('build', 'verify', 'check', 'register'))
    parser.add_argument('--proposal', type=Path)
    parser.add_argument('--deep', action='store_true')
    arguments = parser.parse_args()
    if arguments.command == 'build':
        result = rebuild(arguments.deep)
    elif arguments.command == 'verify':
        value = load(arguments.deep)
        assert (DATA/'view-data.js').read_text(encoding='utf-8') == bundle(value), '正本と閲覧データが異なります。buildを実行してください'
        result = dict(全合格=True, 正本と閲覧データ一致=True, 根拠指紋検証=arguments.deep,
                      正本SHA256=value['source_sha256'])
    else:
        assert arguments.proposal, '--proposalが必要です'
        proposal = read(arguments.proposal)
        result = check(proposal) if arguments.command == 'check' else store_trial(proposal)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
