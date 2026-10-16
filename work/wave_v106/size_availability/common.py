"""公開時の予定リスク可用性を新所有域へ保存する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 小資料又はsourceの指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。大型入力の事前走査はしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    """
    機能: 小さい由来JSONを読む。
    引数: path(Path)は対象位置。
    返り値: dictは保存資料。金融やAPIは実行しない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path: Path, value: dict) -> None:
    """
    機能: 新所有域へ未保存の証跡を新規保存する。
    引数: path(Path)、value(dict)は対象位置と値。
    返り値: None。旧資料・固定sourceを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')


def sources() -> dict:
    """
    機能: 新所有純算術と非金融射影sourceを固定する。
    引数: なし。
    返り値: dict[str,str]はroot相対位置とSHA256。
    """
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(HERE.glob('*.py'))}
