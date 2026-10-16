"""変更前設定を新しいS経路に通して、旧再生器の全配列と照合する。"""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 検査する実装を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


def main():
    """
    機能: 両商品・両約定モデルで未変更の新経路と旧器の全配列を比較する。
    引数: なし。
    返り値: None。今回領域へ一致証跡のみ保存する。
    """
    s=module('wave86_strategy',HERE/'strategy.py')
    c=module('wave86_catalog',HERE/'catalog.py')
    p=module('wave86_prepare',HERE.parent/'wave_v85/prepare.py')
    inputs,signals,_=p.load_inputs()
    features=s.initialize(inputs,signals)
    conf=dict(c.catalog()[0],id='検査用_T0_S')
    rows=[]
    keys=[('2026-09-21_Day','TOPIX'),('2026-09-29_Night','NK225'),
          ('2026-10-05_Day','TOPIX'),('2026-10-08_Night','NK225')]
    for key in keys:
        for observed in (False,True):
            a,_=s.old.play(dict(id='E01_G_U',mask=1,time_mode='U'),inputs[key],features[key],observed)
            b,_=s.play(conf,inputs[key],features[key],observed)
            checked=[]
            for field,value in a.items():
                if isinstance(value,np.ndarray):
                    np.testing.assert_array_equal(value,b[field],err_msg=str((key,observed,field)))
                    checked.append(field)
            for field,value in a['shadow'].items():
                if isinstance(value,np.ndarray):
                    np.testing.assert_array_equal(value,b['shadow'][field],err_msg=str((key,observed,'shadow',field)))
                    checked.append('shadow.'+field)
            rows.append(dict(セッション=key[0],銘柄=key[1],観測約定=observed,完全一致=True,照合配列=checked))
            print(key,observed,'完全一致',len(checked),flush=True)
    out=dict(全合格=True,基準router迂回=True,検査=rows,新候補損益未計算=True)
    (HERE/'基準S経路の旧全配列一致.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__': main()
