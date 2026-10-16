"""完了した103入力を読み、旧出口の共通素材を104へ読取接続する。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numba
import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT/'work/wave_v103'
CACHE = str(HERE/'engine/jit')


def module(name: str, path: Path) -> object:
    """
    機能: 完了した読取部品を固有名で接続する。
    引数: name(str)、path(Path)は識別名とソース位置。
    返り値: objectは読取部品。新キャッシュを104へ限定する。
    """
    if name in sys.modules:
        return sys.modules[name]
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    numba.config.CACHE_DIR = CACHE
    specification = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(specification)
    sys.modules[name] = value
    specification.loader.exec_module(value)
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    numba.config.CACHE_DIR = CACHE
    return value


def digest(path: Path) -> str:
    """
    機能: 小さい直接依存又は今回の出力の指紋を読む。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。旧巨大原本を再走査しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: 日本語UTF-8の定義と完了証跡を読む。
    引数: path(Path)はJSON位置。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def immutable(value: object) -> None:
    """
    機能: 共有する素材の全配列を読取専用にする。
    引数: value(object)は辞書・列・配列。
    返り値: None。後段が基準データを変更できないようにする。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            immutable(child)


def lineage() -> dict:
    """
    機能: 前回の完了と現在の保存場の範囲を直接資料で確認する。
    引数: なし。
    返り値: dictは32場順と完了103の指紋。原本の全内容確認は既証跡へ委譲する。
    """
    terminal = read(PREVIOUS/'今回の入口反復と次の検証方針.json')
    current = PREVIOUS/'金融全32の結果.json'
    assert digest(current) == terminal['正式結果SHA256']
    completed = read(current)
    assert completed['全合格'] and len(completed['sessions']) == 32
    public = read(PREVIOUS/'report/公開結果.json')
    public_html = ROOT/public['フォルダ']/'板の定着と進行失敗の説明と全セッション損益.html'
    assert digest(public_html) == public['公開HTML_SHA256']
    sessions = completed['sessions']
    for symbol in ('TOPIX', 'NK225'):
        assert {path.stem for path in (ROOT/'book'/symbol).glob('*.jsonl')} == set(sessions)
    return dict(sessions=sessions, 口座数=64, 前回分類='進捗：全32金融・独立監査・HTML公開が完了し次の原因を特定。安定目標は未達。',
                previous_result_SHA256=digest(current), previous_public_HTML_SHA256=digest(public_html))


def load_prepared() -> dict:
    """
    機能: 一回の旧素材準備から、64口座の共通record・signal・保存始値を得る。
    引数: なし。
    返り値: dict[tuple[str,str],dict]は103と同じ正常五列と旧出口共通信号。
    新金融再生、現在API、原本再抽出は行わない。
    """
    fixed = lineage()
    material = module('104の不変103素材', PREVIOUS/'base.py').load()
    assert material['metadata']['sessions'] == fixed['sessions']
    old_adapter = module('104の不変103出口設定', PREVIOUS/'engine/adapter.py')
    strategy = module('104の旧共通信号準備', ROOT/'work/wave_v102/strategy.py')
    prepared = strategy.prepare(material, old_adapter.reference_config())
    assert len(prepared) == 64
    immutable(prepared)
    return prepared
