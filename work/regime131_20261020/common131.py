"""時間区分と観測状態による全場参加の比較資料を管理する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "work/daynight128_20261020"
PREV = ROOT / "work/visual_pdca129_20261020"
LAST = ROOT / "work/night_why130_20261020"
PUBLIC = ROOT / "アルゴリズム調査/00131_時間帯と値動き状態を切り替える全場参加"


def read(path):
    """
    機能: 保存済みの日本語資料を読み込む。
    引数: path(Path又はstr)は資料の場所。
    返り値: dict又はlistはJSON内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def reference(path):
    """
    機能: 保存位置と内容指紋を対応させる。
    引数: path(Path又はstr)はプロジェクト内のファイル。
    返り値: dict[str,str]は相対位置とＳＨＡ２５６。
    """
    path = Path(path)
    return dict(path=path.relative_to(ROOT).as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def save(path, data):
    """
    機能: 新しい資料を既存結果の上書きなしで保存する。
    引数: path(Path又はstr)は本作業内の場所、data(dict又はlist)は内容。
    返り値: None。
    """
    path = Path(path)
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
                    + "\n", encoding="utf-8")
