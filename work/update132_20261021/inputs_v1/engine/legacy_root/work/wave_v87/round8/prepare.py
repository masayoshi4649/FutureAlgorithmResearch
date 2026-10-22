"""既に独立照合済みの公開30秒支持を、再定義せず読み取る。"""
from pathlib import Path
import importlib.util
import hashlib
import json
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.dont_write_bytecode=True


def load(verify=True):
    """
    機能: 元の終端・公開時計を保った支持配列を読む。
    引数: verify(bool)。
    返り値: tuple[dict,dict]。旧展開配列と旧準備証拠。
    """
    name='wave87_round8_support_source'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,HERE.parent/'round3/prepare.py')
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return sys.modules[name].load(verify)


def manifest():
    """
    機能: 再利用する支持配列・公開元証拠の指紋を保存する。
    引数: なし。
    返り値: dict。配列の再生成や再正規化はしない。
    """
    _,proof=load(True)
    paths=[HERE.parent/'round3/prepared/short.pkl',HERE.parent/'round3/prepared/支持準備の照合.json',
           HERE.parent/'round3/prepared/終端元時計の照合.json']
    output=dict(意味=proof['意味'],元入力SHA256=proof['入力SHA256'],
        読取資料SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        元公開特徴SHA256=proof['公開特徴SHA256'])
    path=HERE/'prepared/支持参照固定.json';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==output
    else:path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return output


if __name__=='__main__':
    manifest();print('旧公開支持の参照指紋を保存しました')
