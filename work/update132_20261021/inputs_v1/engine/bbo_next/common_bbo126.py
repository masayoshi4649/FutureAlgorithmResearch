"""次原行ＢＢＯ段階の所有範囲と固定資料の操作。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
ROOT = TASK.parents[1]
TRIAL = '126_BBO_原版影と実建値予算を分けた次正常原行十六対照'
LAST_RESULT = TASK / '原版と十五改修の全四十一場会計.json'
BASELINE = TASK / 'baseline/原版旧三十場の費用なし保存引用.json'
PREPARED = TASK / 'input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json'


def sha(path: Path) -> str:
    """
    機能: 指定資料の内容を指紋化する。
    引数: path(Path)は所有源又は明示保存資料。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 明示した小JSONを解釈する。
    引数: path(Path)は設定又は監査資料。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path: Path, value: dict) -> None:
    """
    機能: この別段階の未使用位置に有限JSONを保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。完成資料を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sources() -> dict:
    """
    機能: この段階の実行源と参照するLast条件関数を明示して固定する。
    引数: なし。
    返り値: dict[str,str]は固定源の位置と指紋。人工実装は別証跡で拘束する。
    """
    names = ('common_bbo126.py','core126.py','bbo_order_kernel126.py','policy_bbo126.py',
             'run_bbo126.py','register_bbo126.py','source_engine.py')
    paths = [HERE/name for name in names]+[TASK/'engine/policy126.py',TASK/'design/catalog126.py']
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths}
