"""登録受領・凍結実装・切出し入力が実行直前まで同一かを検査する。"""

from pathlib import Path
import hashlib
import json
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    """ファイルの内容指紋を読む。

    引数: path(Path)。
    返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def references(value):
    """入力目録の下位にある指紋付きファイルを列挙する。

    引数: value(object)はJSON値。
    返り値: generator[dict]はpathとsha256を持つ記録。
    """
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            yield value
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def main():
    """事前登録した実装と全入力を照合する。

    引数: なし。
    返り値: None。相違があれば金融再生開始前に失敗する。
    """
    receipt = json.loads((HERE / '登録受領.json').read_text(encoding='utf-8'))
    assert receipt['returncode'] == 0
    assert receipt['plan_sha256'] == digest(HERE / '再生計画148.json')
    assert receipt['implementation_sha256'] == digest(HERE / '再生前実装148.zip')
    with zipfile.ZipFile(HERE / '再生前実装148.zip') as archive:
        for name in archive.namelist():
            assert archive.read(name) == (HERE / name).read_bytes(), name
    seen = set()
    plan = json.loads((HERE / '再生計画148.json').read_text(encoding='utf-8'))
    for item in plan['spec']['data']['input_manifests']:
        path = ROOT / item['path']
        assert digest(path) == item['sha256']
        for ref in references(json.loads(path.read_text(encoding='utf-8'))):
            if ref['path'] in seen:
                continue
            assert digest(ROOT / ref['path']) == ref['sha256'], ref['path']
            seen.add(ref['path'])
    current = json.loads((HERE / 'current_manifest.json').read_text(encoding='utf-8'))
    for prefix in ('source', 'target'):
        assert digest(ROOT / current[prefix]) == current[prefix + '_sha256']
    actual = {p.stem for p in (HERE / 'inputs').glob('*_Night.pkl')}
    assert actual == set(plan['spec']['data']['sessions']) and len(actual) == 26
    result = dict(registration=True, frozen_files=True, manifests=True, checked_references=len(seen), complete_nights=25, partial_nights=1)
    (HERE / '実行直前指紋検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('凍結照合完了', len(seen))


if __name__ == '__main__':
    main()
