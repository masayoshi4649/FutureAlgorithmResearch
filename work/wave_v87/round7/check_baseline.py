"""無効追加の全口座を、旧GUの保存注文・料金・時価へ照合する。"""
from pathlib import Path
import importlib.util
import hashlib
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent


def module(name,path):
    """
    機能: 検査対象と旧会計の読取用モジュールを読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    out=importlib.util.module_from_spec(spec);sys.modules[name]=out;spec.loader.exec_module(out)
    return out


def compare(before,after):
    """
    機能: 旧結果の全配列を再帰的に照合する。
    引数: before/after(dict)。
    返り値: int。検査した配列数。
    """
    count=0
    for name,value in before.items():
        if isinstance(value,np.ndarray):np.testing.assert_array_equal(value,after[name]);count+=1
        elif isinstance(value,dict):count+=compare(value,after[name])
    return count


def main():
    """
    機能: 基準だけを全120口座で再生し、保存済み元GU会計へ完全一致させる。
    引数: なし。
    返り値: None。有効追加の新しい全場損益は評価しない。
    """
    strategy=module('wave87_round7_strategy',HERE/'strategy.py')
    catalog=module('wave87_round7_catalog',HERE/'catalog.py')
    oldpath=HERE.parents[1]/'wave_v85'
    prepare=module('wave85_prepare',oldpath/'prepare.py')
    accounting=module('wave85_research',oldpath/'research.py')
    source_sha={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}
    inputs,signals,fingerprints=prepare.load_inputs(verify=True)
    features=strategy.initialize(inputs,signals);config=catalog.catalog()[0]
    records=[]
    for model in ('observed','specified'):
        source=oldpath/model/'ledgers/E01_G_U.pkl'
        original=pickle.loads(source.read_bytes())
        for key,ready in sorted(inputs.items()):
            result,settings=strategy.play(config,ready,features[key],model=='observed')
            count=compare(result['core_result'],result)
            assert not len(result['satellite_orders']) and not len(result['satellite_trades'])
            row,ledger,equity=accounting.account(strategy.previous,ready,result,settings)
            for name in ('orders','trades','cycles','fees'):
                np.testing.assert_array_equal(ledger[name],original[key][name],err_msg=str((key,name)))
            assert ledger['net_trades']==original[key]['net_trades']
            assert ledger['curve_SHA256']==original[key]['curve_SHA256']
            assert ledger['raw_curve_SHA256']==original[key]['raw_curve_SHA256']
            records.append(dict(model=model,session=key[0],symbol=key[1],配列数=count,
                                旧注文返済料金時価完全一致=True))
        print(model,'旧GU全60口座一致',flush=True)
    for name,digest in source_sha.items():assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    output=dict(全合格=True,口座件数=len(records),入力SHA256=fingerprints,実装SHA256=source_sha,検査=records)
    (HERE/'追加無効と旧GUの全会計完全一致.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
