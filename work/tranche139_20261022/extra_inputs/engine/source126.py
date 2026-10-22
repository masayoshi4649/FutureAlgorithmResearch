"""原版E01の数値源を新所有域へ接続する共通定義。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIRROR = HERE / 'legacy_root'
SMALL_FIXED = ('work/wave_v38/探索条件の固定.json',
               'work/wave_v44/探索条件の固定.json',
               'work/wave_v27/hierarchy_design_fixed.json')


def digest(path: Path) -> str:
    """
    機能: 明示した保存源の同一性を得る。
    引数: path(Path)はPython源又は小設定。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 明示した小JSONを解釈する。
    引数: path(Path)は設定又は検証資料。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path: Path, value: dict) -> None:
    """
    機能: 新所有域の未使用位置に有限JSONを保存する。
    引数: path(Path)、value(dict)は保存位置と内容。
    返り値: None。旧成果と既存出力を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def copy_source(relative: str) -> Path:
    """
    機能: 準備済み同bytes所有源だけを接続する。
    引数: relative(str)は旧repo相対Python又は許可済小設定。
    返り値: Pathは新所有位置。不足源の追加コピーは行わない。
    """
    path = MIRROR / relative
    assert path.exists() and (path.suffix == '.py' or relative in SMALL_FIXED)
    assert path.read_bytes() == (ROOT / relative).read_bytes(), relative
    return path


def sources() -> dict:
    """
    機能: 今回実装と同bytes旧数値源を正式固定用に指紋化する。
    引数: なし。
    返り値: dict[str,str]はrepo相対位置とSHA256。生成JITを含めない。
    """
    paths = sorted(HERE.rglob('*.py')) + [MIRROR / p for p in SMALL_FIXED]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
