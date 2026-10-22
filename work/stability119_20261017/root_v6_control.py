"""追加七場を原本読取前に固定・照合・登録する根担当の手順。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent / 'v6'


def digest(path: Path) -> str:
    """
    機能: 指定ファイルの同一性を確認する。
    引数: path(Path)は確認対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 根担当の固定確認をUTF-8で保存する。
    引数: path(Path)は保存先、value(dict)は確認内容。
    返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def bind() -> None:
    """
    機能: 人工証跡を現行120源と入力目録へ結合する。
    引数: なし。
    返り値: None。金融及び登録を行わない。
    """
    sys.path.insert(0, str(HERE))
    from plan_v6 import sources
    evidence_names = {
        'audit_source/旧源全百二十と初期化差分及び入力目録結合の独立監査_v2.json': 'fa4c5c28d5545c47150b90b87923451b949cec1c584c6fc05dc6227df50cdb38',
        '旧源所有と修正四十四列及び固定二設定の純接続.json': 'bb0b29c117c390eb8a0062f346f3fd47357ba89b7222f4dfd75b6dcd07820802',
        '所有数値源とadapter差分の対応.json': '3cabd8efbd5ea5034a45526c3b8cf57d09a03dc4c1c5e51083c9bcc9032031c9',
        'audit_source/旧三十三場の終端flat保証を数量補完せず委譲するSOURCE確認.json': 'cad15e47f14e6e4ff526019437c440e0f9cad023369e420deb0c13a8a633f431',
    }
    evidence = []
    for name, expected in evidence_names.items():
        path = HERE / name
        assert digest(path) == expected, name
        evidence.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=expected))
    audit = json.loads((HERE / next(iter(evidence_names))).read_text(encoding='utf-8'))
    current = sources()
    assert audit['全合格'] and len(current) == 120 and audit['source_SHA256'] == current
    manifest = audit['input_manifest']
    assert digest(ROOT / manifest['path']) == manifest['sha256']
    save(HERE / '人工監査の結合.json', dict(passed=True, source_SHA256=current,
        input_manifest=manifest, evidence=evidence, root_review='全120源と入力目録及び独立437確認を固定。新金融0。'))
    print('根担当が全120源と入力目録を人工証跡へ結合しました。')


def registry(action: str) -> None:
    """
    機能: 完全な計画を照合又は登録し、全出力を保存する。
    引数: action(str)はcheck又はregister。
    返り値: None。非ゼロ終了時は停止する。
    """
    assert action in ('check', 'register')
    manager = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(manager), action,
        '--proposal', str(HERE / '試行計画.json')], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    name = '正式照合の全出力.json' if action == 'check' else '正式登録の全出力.json'
    save(HERE / name, dict(終了コード=result.returncode, stdout=result.stdout, stderr=result.stderr))
    print(action, '終了コード', result.returncode, '保存先', name)
    assert result.returncode == 0, result.stderr[-2000:]


if __name__ == '__main__':
    if sys.argv[1] == 'bind':
        bind()
    else:
        registry(sys.argv[1])
