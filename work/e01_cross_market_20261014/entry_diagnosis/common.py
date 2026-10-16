"""公開票と実親の追加診断だけを新所有域へ保存する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def sources() -> dict:
    """
    機能: 非金融readerだけのsourceを結果前指紋へ結ぶ。
    引数: なし。
    返り値: dict[str,str] はroot相対pathとSHA256。frozen金融源は変更しない。
    """
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def read_json(path: Path) -> tuple[dict,str]:
    """
    機能: 許可済み小JSONを同bytes一読して指紋も求める。
    引数: path(Path) は計画又は保存小会計。
    返り値: tuple[dict,str] は保存辞書とSHA256。
    """
    value=path.read_bytes();return json.loads(value.decode('utf-8-sig')),hashlib.sha256(value).hexdigest()


def write(name: str, value: dict) -> None:
    """
    機能: 新所有域の未保存証跡だけへUTF-8 JSONを保存する。
    引数: name(str)、value(dict) は新証跡名と内容。
    返り値: None。旧金融・公開・共通へ書込まない。
    """
    path=HERE/name;assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
