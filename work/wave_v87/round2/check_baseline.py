"""先行枠ゼロの有無対照を旧GUと全配列で照合する。"""
from pathlib import Path
import importlib.util
import json
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 固有名で読取実装を読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def compare(before,after,prefix=''):
    """
    機能: 既存全配列の完全一致を再帰確認する。
    引数: before/after(dict)、prefix(str)。
    返り値: list[str]。
    """
    checked=[]
    for name,value in before.items():
        if isinstance(value,np.ndarray):
            np.testing.assert_array_equal(value,after[name],err_msg=prefix+name);checked.append(prefix+name)
        elif isinstance(value,dict):
            checked.extend(compare(value,after[name],prefix+name+'.'))
    return checked


def main():
    """
    機能: 先行0%で保護の有無とも旧GUと全口座比較する。
    引数: なし。
    返り値: None。改修候補の損益は計算しない。
    """
    strategy=module('wave87_round2_strategy',HERE/'strategy.py')
    catalog=module('wave87_round2_catalog',HERE/'catalog.py')
    prepare=module('wave87_prepare',HERE.parents[1]/'wave_v85/prepare.py')
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache')
    inputs,signals,fingerprints=prepare.load_inputs(verify=True)
    features=strategy.initialize(inputs,signals)
    configs=[c for c in catalog.catalog() if c['narrow_fraction']==0]
    rows=[]
    for observed in (True,False):
        for key in sorted(inputs):
            old,settings=strategy.old.old.play(dict(id='E01_G_U',mask=1,time_mode='U'),inputs[key],features[key],observed)
            for config in configs:
                new,newsettings=strategy.play(config,inputs[key],features[key],observed)
                assert newsettings==settings
                checked=compare(old,new)
                assert len(new['partial_events'])==0
                rows.append(dict(id=config['id'],session=key[0],symbol=key[1],observed=observed,fields=checked,完全一致=True))
        print('観測約定' if observed else '指定約定','両条件全60口座一致',flush=True)
    out=dict(全合格=True,口座件数=len(rows),基準バイパスなし=True,入力SHA256=fingerprints,検査=rows)
    (HERE/'先行ゼロ両条件と旧GUの完全一致.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
