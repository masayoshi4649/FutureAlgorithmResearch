"""夜間の三段階原因分析と新しい検証結果の保存を支える。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREV = ROOT / "work/visual_pdca129_20261020"
BASE = ROOT / "work/daynight128_20261020"
PUBLIC = ROOT / "アルゴリズム調査/00130_夜間損失のなぜ三段階と再改善"


def read(path):
    """
    機能: 保存済みの日本語JSONを読む。
    引数: path(Path)は入力位置。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: ファイルの内容指紋を計算する。
    引数: path(Path)は対象位置。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path):
    """
    機能: 相対位置と内容指紋を対応させる。
    引数: path(Path)は出典位置。
    返り値: dictは位置と指紋。
    """
    return dict(path=Path(path).relative_to(ROOT).as_posix(), sha256=sha(path))


def save(path, value):
    """
    機能: この作業内の新しい資料を重複なく保存する。
    引数: path(Path)、value(dict又はlist)は位置と内容。
    返り値: None。完成済みファイルと旧作業は上書きしない。
    """
    path = Path(path)
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
