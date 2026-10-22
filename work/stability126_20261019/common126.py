"""原版Ｅ０１の比較に用いる所有域と有限保存。"""

from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TRIAL = "126_原版E01の二市場利益保護と損失後再参加及び場損失の十六対照"
PUBLIC = ROOT / "アルゴリズム調査/00126_E01の損失抑制と方向偏りの再検証"


def sha(path: Path) -> str:
    """
    機能: 保存源又は完成結果の内容指紋を求める。
    引数: path(Path)は対象ファイル。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 日本語ＵＴＦ８の計画・監査・完成資料を読む。
    引数: path(Path)は対象ＪＳＯＮ。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: dict) -> None:
    """
    機能: 今回所有域へ有限ＪＳＯＮを新規保存する。
    引数: path(Path)は保存先、value(dict)は保存内容。
    返り値: None。既存の証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
