"""専用キャッシュで、最終数値核のJITと純Pythonの人工結果を照合する。"""

import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_artificial")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]
sys.path.insert(0, str(WORK))
import day_core128
import night128
from check_engines128 import day_fixture, night_fixture


def main():
    """
    機能: 日中と夜間を一人工経路ずつJITで運転し全返却値を比較する。
    引数: なし。
    返り値: None。市場素材と保存金融成績は読まない。
    """
    results=[]
    dayargs,extra=day_fixture([100,100,100,99.5,98.5,98,100,101,102])
    extra[0][3]=2.
    dayargs=dayargs+(extra[0],extra[1],1)
    nightargs=night_fixture([98,100,100.5,96.5,80.5,81.5,81.5,81.5,81.5])
    for label, function,args in (("日中収縮",day_core128.simulate,dayargs),
                                ("夜間ギャップ",night128.simulate,nightargs)):
        native=function(*args)
        python=function.py_func(*args)
        assert len(native)==len(python)
        for a,b in zip(native,python):
            np.testing.assert_array_equal(a,b)
        results.append(dict(確認=label,合格=True,比較配列=len(native)))
    sources=[WORK/"day_core128.py",WORK/"night128.py",WORK/"bbo_order_kernel126.py"]
    result=dict(全合格=True,確認数=len(results),確認=results,
                数値源SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                新金融=0,市場素材読取=0,キャッシュ=str(HERE/"jit_artificial"))
    target=HERE/"最終核JITとPythonの人工同値.json"
    assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
