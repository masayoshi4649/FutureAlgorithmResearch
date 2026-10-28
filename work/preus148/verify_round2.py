"""第二巡の凍結実装と登録成功を確認する。"""

import json
import zipfile
from pathlib import Path
from verify_frozen import main as verify_original, digest

HERE = Path(__file__).resolve().parent


def verify():
    """第二巡のコードと入力のすり替わりを実行直前に拒否する。

    引数: なし。
    返り値: None。相違は例外にする。
    """
    verify_original()
    receipt = json.loads((HERE / 'round2/登録受領.json').read_text(encoding='utf-8'))
    assert receipt['returncode'] == 0
    assert receipt['implementation_sha256'] == digest(HERE / 'round2/再生前実装.zip')
    with zipfile.ZipFile(HERE / 'round2/再生前実装.zip') as archive:
        for name in archive.namelist():
            assert archive.read(name) == (HERE / name).read_bytes(), name


if __name__ == '__main__':
    verify()
