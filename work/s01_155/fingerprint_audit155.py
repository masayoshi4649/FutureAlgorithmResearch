"""実アプリと独立照合コピーの同一性だけを記録する。金融再生は行わない。"""
from pathlib import Path
import hashlib
import json


def digest(path: Path) -> str:
    """機能: 内容指紋を得る。引数: path(Path)。返り値: str。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: コピーと人工結果を固定する。引数: なし。返り値: None。"""
    root = Path(__file__).resolve().parents[2]
    work = root / 'work/s01_155'
    app = root / 'App/SessionTrader'
    replay = work / 'replay_go'
    matches = []
    for package in ('strategy', 'rules', 'e01'):
        for src in sorted((app / 'internal' / package).glob('*.go')):
            if src.name.endswith('_test.go'):
                continue
            dst = replay / 'internal' / package / src.name
            a, b = digest(src), digest(dst)
            assert a == b, (src, dst)
            matches.append({'app': str(src), 'copy': str(dst), 'sha256': a})
    for name in ('NK225_D07.toml', 'NK225_S01.toml'):
        src, dst = app / 'conf/rules' / name, replay / name
        assert digest(src) == digest(dst), name
        matches.append({'app': str(src), 'copy': str(dst), 'sha256': digest(src)})
    assert digest(work / 'inputs155.json') == digest(root / 'work/d07_154/inputs154.json')
    events = [json.loads(s) for s in (work / '独立人工155.jsonl').read_text(encoding='utf-8-sig').splitlines() if s]
    assert not any(e['Action'] == 'fail' for e in events)
    tests = [e['Test'] for e in events if e['Action'] == 'pass' and e.get('Test') and '/' not in e['Test']]
    assert len(tests) == 9, tests
    files = [*replay.rglob('*.go'), replay/'go.mod', replay/'go.sum', replay/'NK225_D07.toml', replay/'NK225_S01.toml', work/'inputs155.json', work/'spec155.json', work/'spec155.md']
    out = {'purpose': '実装移植の金融前独立照合。金融再生0。', 'copy_matches': matches, 'tests_passed': tests,
           'source_fingerprints': [{'path': str(p), 'sha256': digest(p)} for p in sorted(files)],
           'input_equal_154': True, 'financial_replays': 0}
    (work/'独立監査指紋155.json').write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'matched_files':len(matches),'tests':len(tests),'fingerprints':len(files)},ensure_ascii=False))


if __name__ == '__main__':
    main()
