"""追加一場の所有位置と固定source操作だけを旧接続へ与える。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIRROR = HERE/'legacy_root'
SESSIONS = ('2026-10-19_Day',)
SYMBOLS = ('TOPIX', 'NK225')
ENGINE_NAMES = ('common.py', 'catalog.py', 'interface.py', 'entry_policy.py', 'base_policy.py',
                'sizing_engine.py', 'order_kernel.py', 'context.py', 'reuse.py', 'daily.py',
                'exit_policy.py', 'exit_core.py')
SMALL_FIXED = ('work/wave_v38/探索条件の固定.json', 'work/wave_v44/探索条件の固定.json',
               'work/wave_v27/hierarchy_design_fixed.json')


def digest(path: Path) -> str:
    """
    機能: 明示したsource又は小成果の同一性を得る。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 明示したJSON小資料だけを解釈する。
    引数: path(Path)は対象。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path: Path, value: dict) -> None:
    """
    機能: 新所有域の未使用位置に有限JSONを保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。既存成果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')


def copy_source(relative: str) -> Path:
    """
    機能: 事前コピー済み源だけを返し、実行時の依存追加を拒否する。
    引数: relative(str)は旧repo相対Python又は許可済小設定。
    返り値: Pathは所有位置。不足源は例外とする。
    """
    target = MIRROR/relative
    assert target.exists() and (target.suffix=='.py' or relative in SMALL_FIXED), str(target)
    assert target.read_bytes() == (ROOT/relative).read_bytes(), relative
    return target


def sources() -> dict:
    """
    機能: 今回の全Pythonと明示小設定だけを正式固定用に指紋化する。
    引数: なし。
    返り値: dict[str,str]はrepo相対位置とSHA256。生成キャッシュを含めない。
    """
    paths = sorted(HERE.rglob('*.py')) + [MIRROR/p for p in SMALL_FIXED]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
