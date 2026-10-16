"""一読の目的・源指紋・失敗保全を管理し、金融やAPIへ接続しない。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
INPUT_MANIFESTS={
    'TradeGate':'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json',
    'TradeExit':'work/wave_v106/e01_trade_exit/全33場の保有中取引更新票.json',
    'TradeExit有限時計補完':'work/wave_v106/e01_trade_exit/非有限clock系譜修正と完成全33入力の同値補完.json'}
BOUND_SOURCES=(
    'work/wave_v106/trade_gate/votes.py','work/wave_v106/e01_trade_gate/votes.py',
    'work/wave_v106/e01_trade_gate/prepare.py','work/wave_v106/e01_trade_gate/data.py',
    'work/wave_v106/e01_trade_exit/votes.py','work/wave_v106/e01_trade_exit/features.py',
    'work/wave_v106/e01_trade_exit/prepare.py','work/wave_v106/e01_trade_exit/data.py',
    'work/wave_v106/e01_trade_exit/rebind_input.py',
    'work/e01_fak_evidence_20261014/engine/price_votes.py',
    'work/e01_fak_evidence_20261014/engine/entry_gate.py',
    'work/e01_fak_evidence_20261014/engine/core.py',
    'work/e01_fak_evidence_20261014/engine/catalog.py',
    'work/wave_v87/round10/strategy.py')


def digest(path: Path) -> str:
    """
    機能: 許可されたsource又はowned小資料をSHA256へ結ぶ。
    引数: path(Path) は検査対象。
    返り値: str は指紋。大型cacheの事前digestには使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> dict:
    """
    機能: 実行に有効な私有pyと参照sourceを全部束縛する。
    引数: なし。
    返り値: dict はroot相対path/SHA256。入力本文を読まない。
    """
    paths=list(HERE.glob('*.py'))+[ROOT/name for name in BOUND_SOURCES]
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths)}


def old_sources() -> dict:
    """
    機能: 111金融source17が準備開始終端で不変だったことを検査する。
    引数: なし。
    返り値: dict は17pyの指紋。旧JITや金融を実行しない。
    """
    paths=sorted((ROOT/'work/e01_fak_evidence_20261014/engine').glob('*.py'));assert len(paths)==17
    return {p.relative_to(ROOT).as_posix():digest(p) for p in paths}


def write(path: Path,value: dict) -> None:
    """
    機能: owned新資料だけを非有限JSON禁止で保存する。
    引数: path(Path)、value(dict) は保存先と小射影。
    返り値: None。既成功又はFalseを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),str(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def read_json(path: Path) -> tuple[dict,str]:
    """
    機能: 授権された小目録を同bytes一読し指紋と内容を返す。
    引数: path(Path) は目録又はowned固定。
    返り値: tuple[dict,str] はJSON値とSHA256。cache本文には使わない。
    """
    saved=path.read_bytes();return json.loads(saved),hashlib.sha256(saved).hexdigest()
