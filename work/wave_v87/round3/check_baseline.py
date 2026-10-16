"""支持追加を無効化した二系統を、旧GUと旧P1へ完全一致で照合する。"""
from pathlib import Path
import importlib.util
import json
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 固有名で検査する実装を読む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def compare(before,after,prefix=''):
    """
    機能: 既存の全配列を再帰して完全一致を確かめる。
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
    機能: 二系統のF0を全60口座と二約定モデルで旧器へ照合する。
    引数: なし。
    返り値: None。新F1以降の損益は計算しない。
    """
    strategy=module('wave87_round3_strategy',HERE/'strategy.py')
    catalog=module('wave87_round3_catalog',HERE/'catalog.py')
    prepare=module('wave87_prepare85_check',HERE.parents[1]/'wave_v85/prepare.py')
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache')
    inputs,signals,fingerprints=prepare.load_inputs(verify=True)
    features=strategy.initialize(inputs,signals)
    configs=[c for c in catalog.catalog() if c['support_mode']==0]
    oldcatalog=module('wave87_prior_catalog_check',HERE.parents[1]/'wave_v86/phase2/catalog.py')
    pc=next(c for c in oldcatalog.catalog() if c['id']=='T2_P1')
    rows=[]
    for observed in (True,False):
        for key in sorted(inputs):
            for config in configs:
                if config['parent_id']=='GU':
                    before,settings=strategy.old.old.play(dict(id='E01_G_U',mask=1,time_mode='U'),inputs[key],features[key],observed)
                else:
                    before,settings=strategy.prior.play(pc,inputs[key],features[key],observed)
                after,aftersettings=strategy.play(config,inputs[key],features[key],observed)
                assert aftersettings==settings
                fields=compare(before,after)
                rows.append(dict(id=config['id'],session=key[0],symbol=key[1],observed=observed,fields=fields,完全一致=True))
        print('観測約定' if observed else '指定約定','両系統全60口座一致',flush=True)
    result=dict(全合格=True,口座件数=len(rows),バイパスなし=True,入力SHA256=fingerprints,検査=rows)
    (HERE/'無効F0と旧二系統の完全一致.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
