"""比例損失二例の固定資料だけを読む、金融を実行しない診断共通処理。"""

import gzip
import hashlib
import json
from pathlib import Path
import pickle

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def small(path: Path) -> tuple[dict,str]:
    """
    機能: 保存小JSONを同bytes一回で読み、出典SHAを返す。
    引数: path(Path) は小資料。
    返り値: tuple[dict,str] は内容と指紋。市場や金融へ接続しない。
    """
    saved=path.read_bytes();return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def sources() -> dict:
    """
    機能: 診断源三本を結果前に固定する。
    引数: なし。
    返り値: dict[str,str] はroot相対sourceとSHA256。
    """
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def saved(item: dict) -> dict:
    """
    機能: 授権後に対象cache又は台帳を同bytes一読して指紋を確認する。
    引数: item(dict) は固定path/SHA256。
    返り値: dict は保存値。対象を探し直したり原板を読んだりしない。
    """
    path=(ROOT/item['path']).resolve();assert path.is_relative_to(ROOT/'work')
    data=path.read_bytes();assert hashlib.sha256(data).hexdigest()==item['SHA256']
    return pickle.loads(gzip.decompress(data))


def write(name: str, value: dict) -> None:
    """
    機能: 未保存の診断証跡だけを新所有域へ書く。
    引数: name(str)、value(dict) はファイル名と証跡。
    返り値: None。旧源や完成資料を上書きしない。
    """
    path=HERE/name;assert not path.exists() and path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
