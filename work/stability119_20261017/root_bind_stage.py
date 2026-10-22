"""閉鎖された独立人工証跡と実装・目録を根担当が結合する。"""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    """
    機能: source又は小証跡の同一性を確認する。
    引数: path(Path)は確認対象。
    返り値: strはSHA256。市場入力は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 独立証跡の全sourceを照合し、固定前の結合を保存する。
    引数: CLI directory/audit/sha256/additionalは所有域・独立証跡・期待指紋・追加証跡。
    返り値: None。実登録と金融は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('audit', type=Path)
    parser.add_argument('sha256')
    parser.add_argument('--additional', action='append', default=[])
    args = parser.parse_args()
    directory, audit_path = args.directory.resolve(), args.audit.resolve()
    assert directory.is_relative_to(ROOT / 'work') and audit_path.is_relative_to(ROOT)
    assert digest(audit_path) == args.sha256
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit.get('全合格', audit.get('passed')) is True
    sources = audit.get('source_SHA256', audit.get('economic_sources'))
    assert sources
    for name, expected in sources.items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT / 'work') and path.suffix == '.py'
        assert digest(path) == expected, name
    evidence = [dict(path=audit_path.relative_to(ROOT).as_posix(), sha256=args.sha256)]
    for item in args.additional:
        name, expected = item.rsplit('=', 1)
        path = Path(name).resolve()
        assert path.is_relative_to(ROOT) and digest(path) == expected
        evidence.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=expected))
    manifest = audit.get('input_manifest')
    if manifest:
        assert digest(ROOT / manifest['path']) == manifest.get('sha256', manifest.get('SHA256'))
    target = directory / '人工監査の結合.json'
    assert not target.exists()
    value = dict(passed=True, source_SHA256=sources, economic_sources=sources, input_manifest=manifest, evidence=evidence,
        root_review='根担当が全sourceと独立証跡の同一性を確認。金融及び登録0。')
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(sources)}源を独立人工証跡へ結合しました。')


if __name__ == '__main__':
    main()
