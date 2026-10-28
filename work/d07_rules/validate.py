"""登録済みの判断式外部化を旧Go全約定と独立照合する。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OLD = ROOT/'work/d07_port'


def digest(path):
    """保存資料の指紋を計算する。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """全50場のGo再生を実行し、旧Go全約定・研究期待値と照合する。

    引数: --note(str)は実装差分、--rules(str)は外部TOML、--scene(str)は限定する一場、
    --supplement(str)は登録計画を変更せず保存した実行前の追補計画。
    返り値: None。
    金融再生は登録完了後だけ行い、原資料・期待値は変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--note', required=True)
    parser.add_argument('--rules')
    parser.add_argument('--scene')
    parser.add_argument('--supplement')
    args = parser.parse_args()
    receipt = json.loads((HERE/'登録受領.json').read_text(encoding='utf8'))
    assert receipt['returncode'] == 0
    baseline = json.loads((HERE/'基準結果指紋.json').read_text(encoding='utf8'))
    assert all(digest(ROOT/name) == value for name, value in baseline.items()), '基準結果が変更されています'
    number = 1
    while (HERE/f'run{number:02d}').exists():
        number += 1
    folder = HERE/f'run{number:02d}'
    folder.mkdir()
    app = ROOT/'App/SessionTrader'
    files = sorted((app/'internal').rglob('*.go'))
    for dirname in ('rules', 'conf'):
        files += sorted((app/dirname).rglob('*.toml'))
    files += [app/'go.mod', app/'go.sum', Path(__file__)]
    if args.rules:
        rule_path = (ROOT/args.rules).resolve()
        if rule_path not in files:
            files.append(rule_path)
    supplement = None
    if args.supplement:
        supplement_path = (ROOT/args.supplement).resolve()
        supplement = {'path': supplement_path.relative_to(ROOT).as_posix(), 'sha256': digest(supplement_path)}
        files.append(supplement_path)
    fingerprints = {path.relative_to(ROOT).as_posix(): digest(path) for path in files}
    archive = folder/'実行時実装.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, path.relative_to(ROOT).as_posix())
    command = ['go', 'test', './internal/strategy', '-run', '^TestD07Saved(Integration|Addon)$', '-count=1', '-json']
    env = dict(os.environ, SESSIONTRADER_D07_ALL='1', SESSIONTRADER_D07_REPORT=str(folder/'D07全約定照合.json'))
    env.pop('SESSIONTRADER_D07_SCENE', None)
    env.pop('SESSIONTRADER_D07_RULES', None)
    if args.rules:
        env['SESSIONTRADER_D07_RULES'] = str((ROOT/args.rules).resolve())
    if args.scene:
        env['SESSIONTRADER_D07_SCENE'] = args.scene
    manifest = {
        'trial_id': receipt['trial_id'], 'implementation': fingerprints,
        'archive_sha256': digest(archive), 'baseline': baseline,
        'note': args.note, 'command': command, 'rules': args.rules, 'scene': args.scene, 'supplement': supplement,
        'scope': '既知50場の同値確認。旧Go全831約定の全列一致を要求し、新しい収益性の証拠に数えない。',
    }
    (folder/'実行条件.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    print(folder.name+'開始', flush=True)
    with (folder/'go結果.jsonl').open('wb') as out, (folder/'go標準エラー.txt').open('wb') as err:
        result = subprocess.run(command, cwd=app, env=env, stdout=out, stderr=err)
    changed = [name for name, value in fingerprints.items() if not (ROOT/name).exists() or digest(ROOT/name) != value]
    summary = {'returncode': result.returncode, '実行中変更ファイル': changed, 'go結果_sha256': digest(folder/'go結果.jsonl')}
    report = folder/'D07全約定照合.json'
    differences = []
    if report.exists():
        rows = json.loads(report.read_text(encoding='utf8'))
        old_rows = json.loads((OLD/'run01/D07全約定照合.json').read_text(encoding='utf8'))
        if args.scene:
            old_rows = [row for row in old_rows if row['Session'] == args.scene]
            assert len(old_rows) == 1, '基準結果に指定場がありません'
        old_by_session = {row['Session']: row for row in old_rows}
        for row in rows:
            expected = old_by_session.get(row['Session'])
            if expected is None:
                differences.append({'session': row['Session'], 'reason': '基準場なし'})
                continue
            actual, want = row['Actual'], expected['Actual']
            if len(actual) != len(want):
                differences.append({'session': row['Session'], 'actual_count': len(actual), 'expected_count': len(want)})
            for index, (got, goal) in enumerate(zip(actual, want)):
                if got != goal:
                    differences.append({'session': row['Session'], 'index': index, 'actual': got, 'baseline': goal})
            if row['Gross'] != expected['Gross']:
                differences.append({'session': row['Session'], 'gross': row['Gross'], 'baseline_gross': expected['Gross']})
        missing = sorted(set(old_by_session)-{row['Session'] for row in rows})
        summary.update(sessions=len(rows), research_passed=sum(row['Passed'] for row in rows), research_exact=sum(row['Exact'] for row in rows),
            actual_orders=sum(row['Orders'] for row in rows), actual_net=sum(row['Gross'] for row in rows),
            baseline_missing_sessions=missing, baseline_differences=len(differences))
        if missing:
            differences.append({'missing_sessions': missing})
    else:
        differences.append({'reason': '結果ファイルなし'})
    events = [json.loads(line) for line in (folder/'go結果.jsonl').read_text(encoding='utf8').splitlines() if line.startswith('{')]
    summary['追加担当合格場数'] = sum(event.get('Action') == 'pass' and event.get('Test', '').startswith('TestD07SavedAddon/') for event in events)
    count = 1 if args.scene else 50
    summary['passed'] = result.returncode == 0 and not changed and not differences and summary.get('sessions') == count and summary['追加担当合格場数'] == count
    (folder/'外部化前後の差分.json').write_text(json.dumps(differences, ensure_ascii=False, indent=2), encoding='utf8')
    (folder/'結果要約.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    raise SystemExit(0 if summary['passed'] else 1)


if __name__ == '__main__':
    main()
