"""追加一場とオプション検査の共通保存先を定義する。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SCENE='2026-10-19_Day'
NAME='00124_追加セッションと日経オプションの検証'


def read(path: Path) -> dict:
    """
    機能: 保存した小さいUTF-8 JSONを読む。
    引数: path(Path)は既存ファイル。
    返り値: dictは記録内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path: Path) -> str:
    """
    機能: 保存済みsource又は小資料のSHA256を求める。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path,value: dict) -> None:
    """
    機能: 新しい有限JSONを所有作業域へ一度だけ保存する。
    引数: path(Path)は未使用保存先、value(dict)はJSON互換内容。
    返り値: None。既存結果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
