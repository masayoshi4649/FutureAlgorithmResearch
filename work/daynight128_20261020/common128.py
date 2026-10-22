"""昼夜独立研究の保存資料と共通会計。"""

import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "work/stability126_20261019"
PUBLIC = ROOT / "アルゴリズム調査/00128_日中改修と夜間新造の反復検証"


def read(path):
    """
    機能: 日本語の保存資料を読む。
    引数: path(Path)は入力位置。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 保存入力と実装の指紋を計算する。
    引数: path(Path)は対象位置。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    """
    機能: 完成資料を上書きせず新規保存する。
    引数: path(Path)、value(dict又はlist)は位置と内容。
    返り値: None。
    """
    path = Path(path)
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def reference(path):
    """
    機能: 相対位置と内容指紋を保存可能な参照にする。
    引数: path(Path)は対象位置。
    返り値: dictはpathとsha256。
    """
    return dict(path=Path(path).relative_to(ROOT).as_posix(), sha256=sha(path))


def packets():
    """
    機能: 既知四十三場の準備済み原行素材を重複なしで列挙する。
    引数: なし。
    返り値: list[dict]は既存固定計画で拘束された素材参照。
    """
    old = read(OLD / "gated_bbo126/固定計画.json")["packets"]
    new = read(OLD / "update_20261020/追加二場の非金融入力準備.json")["packets"]
    items = [dict(session=p["session"], path=p["path"], sha256=p["sha256"]) for p in old + new]
    assert len(items) == len({p["session"] for p in items}) == 43
    return sorted(items, key=lambda p: p["session"])


def metrics(rows):
    """
    機能: 合計だけでなく場別の安定性を集計する。
    引数: rows(list[dict])は手数料後netを持つ商品場会計。
    返り値: dictは勝敗・中央値・最大損失・上位場除外等。
    """
    values = np.array([r["net"] for r in rows])
    positive, negative = values[values > 0], values[values < 0]
    return dict(sessions=len(rows), profit=sum(r["profit"] for r in rows),
        loss=sum(r["loss"] for r in rows), fees=sum(r["fees"] for r in rows),
        net=float(values.sum()), black=len(positive), red=len(negative),
        flat=int((values == 0).sum()), active=sum(r["entries"] > 0 for r in rows),
        median=float(np.median(values)), worst=float(values.min()),
        mean_black=float(positive.mean()) if len(positive) else 0.,
        mean_red=float(-negative.mean()) if len(negative) else 0.,
        without_top3=float(values.sum() - sum(sorted(positive, reverse=True)[:3])),
        entries=sum(r["entries"] for r in rows))
