"""チャートと板を突き合わせる新調査の保存機能。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = ROOT / "work/daynight128_20261020"
PUBLIC = ROOT / "アルゴリズム調査/00129_チャートと板からの失敗機構再検証"


def read(path):
    """
    機能: 保存済みの日本語資料を読む。
    引数: path(Path)は入力位置。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 内容を変更していないことを照合する指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path):
    """
    機能: 出典位置と内容指紋を組にする。
    引数: path(Path)は対象位置。
    返り値: dictは相対位置と指紋。
    """
    return dict(path=Path(path).relative_to(ROOT).as_posix(), sha256=sha(path))


def save(path, value):
    """
    機能: この調査の未保存資料を新規保存する。
    引数: path(Path)、value(dict又はlist)は位置と内容。
    返り値: None。完成した旧資料は上書きしない。
    """
    path = Path(path)
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
