"""追加入口と気配予算の比較範囲及び保存資料を拘束する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
TRIAL = '126_GGU低R利益床と公開気配予算の五十三対照'
PREPARED = TASK/'input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json'
LAST_RESULT = TASK/'原版と十五改修の全四十一場会計.json'
BASELINE = TASK/'baseline/原版旧三十場の費用なし保存引用.json'
PREVIOUS = TASK/'engine/bbo_next/全十六条件の次原行BBO会計.json'
GATED = TASK/'rearm126/ＧとＧＵの全四十一場会計.json'
RESULT_NAME = 'GとGU及び低R利益床の全四十一場BBO会計.json'
ARRAY_FIELDS = ('orders','trades','cycles','curve','stats','execution_events','execution_states','order_uids')


def sha(path: Path) -> str:
    """
    機能: 所有資料の内容指紋を求める。
    引数: path(Path)は明示した保存位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 指定された小JSONを読む。
    引数: path(Path)は固定資料。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path: Path, value: dict) -> None:
    """
    機能: 所有域の未使用位置へ有限なJSONを保存する。
    引数: path(Path)、value(dict)は保存先と値。
    返り値: None。完成結果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),str(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sources() -> dict:
    """
    機能: 新しい配線源と無変更の数値源及び固定選定を指紋化する。
    引数: なし。
    返り値: dict[str,str]はリポジトリ相対位置とSHA256。
    """
    names = ('catalog126g.py','feed_filter126.py','common_gated126.py','run_gated126.py','register_gated126.py')
    paths = [HERE/name for name in names]
    paths += [TASK/'engine/bbo_next'/name for name in ('core126.py','bbo_order_kernel126.py','policy_bbo126.py')]
    paths += [TASK/'engine/policy126.py', TASK/'design/catalog126.py',TASK/'integrate126.py',TASK/'analyze126.py']
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths}
