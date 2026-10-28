"""登録済み移植照合を一度だけ実行し、実装・原資料・期待結果の改変がないことを確認する。"""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """機能: 固定JSONを読む。引数: path(Path)。返り値: dict。"""
    return json.loads(path.read_text(encoding='utf-8-sig'))


def stamp() -> str:
    """機能: 現在のローカル時刻を記録する。引数: なし。返り値: str。"""
    return datetime.now().astimezone().isoformat()


def fingerprint(path: Path) -> dict:
    """機能: 全内容を読み指紋と読取中の変更を検査する。引数: path(Path)。返り値: dict。"""
    a = path.stat()
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    b = path.stat()
    assert (a.st_size, a.st_mtime_ns) == (b.st_size, b.st_mtime_ns), f'指紋読取中に変更: {path}'
    return {'path': str(path.resolve()), 'sha256': sha, 'bytes': b.st_size}


def references(items: list[dict]) -> list[dict]:
    """機能: 登録時指紋への全一致を確認する。引数: items(list[dict])。返り値: list[dict]。"""
    out = []
    for item in items:
        path = Path(item['path'])
        if not path.is_absolute():
            path = ROOT / path
        actual = fingerprint(path)
        assert actual['sha256'] == item['sha256'], f'登録時指紋と不一致: {path}'
        if 'bytes' in item:
            assert actual['bytes'] == item['bytes'], f'登録時サイズと不一致: {path}'
        out.append(actual)
    return out


def verify() -> dict:
    """機能: ソース、入力、期待結果の実行時指紋を記録する。引数: なし。返り値: dict。"""
    receipt = read(HERE/'登録受領155.json')
    assert receipt['registered'] is True and receipt['returncode'] == 0, '登録未完了'
    entries = [receipt['plan'], receipt['implementation'], *receipt['sources'], *receipt['inputs']]
    registered = references(entries)
    manifest = read(HERE/'inputs155.json')
    raw = references([f for scene in manifest['sessions'] for f in scene['fingerprints']])
    assert len(raw) == 312 and len({x['path'] for x in raw}) == 312
    expected = []
    for scene in manifest['sessions']:
        expected.append(fingerprint(ROOT/'work/d07_154/results_go'/f"{scene['session']}_D07.json"))
        if scene['kind'] == 'Day':
            expected.append(fingerprint(ROOT/'work/d07_154/results_round2'/f"{scene['session']}_D07.json"))
    assert len(expected) == 79 and len({x['path'] for x in expected}) == 79
    return {'at': stamp(), 'registered': registered, 'raw': raw, 'expected': expected,
            'registered_count': len(registered), 'raw_count': len(raw), 'expected_count': len(expected)}


def save(path: Path, value: dict) -> None:
    """機能: 監査JSONをUTF-8で保存する。引数: path(Path)、value(dict)。返り値: None。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main() -> None:
    """機能: 許可された移植照合と前後改変検査を行う。引数: なし。返り値: None。"""
    record_path = HERE/'金融実行155.json'
    out = HERE/'results'
    assert not record_path.exists(), '同じ実行記録の再使用は禁止'
    assert not out.exists(), '同じ結果フォルダの再使用は禁止'
    started = time.perf_counter()
    print('登録実装・312原資料・79期待結果の指紋を全読照合します。', flush=True)
    before = verify()
    save(HERE/'実行前全指紋155.json', before)
    command = ['go','run','.', '-manifest','../inputs155.json','-registration','../登録受領155.json',
               '-expected-first','../../d07_154/results_go','-expected-second','../../d07_154/results_round2',
               '-out','../results','-workers','4']
    record = {'開始': stamp(), 'command': command, 'cwd': str(HERE/'replay_go'),
              '金融実行回数': 1, '目的': 'S01の移植同値照合と旧D07不変確認', '場数': 52, '条件場数': 79,
              '監査ラッパー': fingerprint(Path(__file__))}
    save(record_path, record)
    print('全指紋一致。固定79条件場の移植照合を開始します。', flush=True)
    with (HERE/'金融実行155.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=HERE/'replay_go', stdout=log, stderr=subprocess.STDOUT,
                                encoding='utf-8', errors='replace')
    record.update({'終了': stamp(), '終了コード': result.returncode, '所要秒': time.perf_counter()-started})
    save(record_path, record)
    after = verify()
    save(HERE/'実行後全指紋155.json', after)
    for group in ('registered','raw','expected'):
        assert before[group] == after[group], f'実行前後で改変: {group}'
    assert record['監査ラッパー'] == fingerprint(Path(__file__)), '監査ラッパーの実行中変更'
    record['前後改変数'] = 0
    files = sorted(out.glob('*.json'))
    record['結果ファイル数'] = len(files)
    if result.returncode == 0:
        assert len(files) == 52
        reports = [read(p) for p in files]
        cases = [c for r in reports for c in r['cases']]
        assert len(cases) == 79 and all(c['equal'] for c in cases)
        record['一致条件場数'] = len(cases)
        record['一致全約定数'] = sum(c['fills'] for c in cases)
        record['一致全発注数'] = sum(c['signals'] for c in cases)
    save(record_path, record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
