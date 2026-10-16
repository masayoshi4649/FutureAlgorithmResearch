"""旧R市場/初指値到達会計へ、方向別の未fill取消だけを独立に加える。"""

import importlib.util
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
NAME='106局所位相の旧R独立会計コピー'
if NAME not in sys.modules:
    spec=importlib.util.spec_from_file_location(NAME,HERE/'accounting_reference.py')
    reference=importlib.util.module_from_spec(spec);sys.modules[NAME]=reference;spec.loader.exec_module(reference)
reference=sys.modules[NAME]


def inspect(key: tuple, record: dict, output: dict, normal: dict) -> dict:
    """
    機能: 元全行会計と初到達約定に加え、実R約定前に局所取消がなかったことを検算する。
    引数: key(tuple[str,str])、record/output/normal(dict)は場商品・価格・実台帳・同原行の取消配列。
    返り値: dictは旧会計と局所確認件数。実fill行の到達は取消より先なので除外する。
    """
    value=reference.inspect(key,record,output,normal)
    count=0
    for order in output['orders']:
        if not order[7] or int(order[3])!=1:continue
        start,stop=int(order[1])+1,int(order[0]);side=int(order[4])
        cancel=normal['local_cancel_buy'] if side==1 else normal['local_cancel_sell']
        assert not np.any(cancel[start:stop]),'局所取消したR親を後で約定させています'
        count+=1
    value['局所方向取消の実fill前検算']=count
    return value
