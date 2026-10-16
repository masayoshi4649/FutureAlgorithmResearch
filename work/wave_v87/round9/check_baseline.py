"""初期停止を変えない対照を、前段の四入口および元GUへ完全一致させる。"""
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
    機能: 新実装と旧会計を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


def main():
    """
    機能: 停止変更なしだけを再生し、前段の全保存台帳・料金・時価に一致させる。
    引数: なし。
    返り値: None。新しい停止方式の性能は評価しない。
    """
    strategy=module('wave87_round9_strategy',HERE/'strategy.py')
    catalog=module('wave87_round9_catalog',HERE/'catalog.py')
    prepare=module('wave85_prepare',HERE.parents[1]/'wave_v85/prepare.py')
    accounting=module('wave85_research',HERE.parents[1]/'wave_v85/research.py')
    # ----------------------------------------
    # 並行整備中の親実行器ではなく、この検査が実際に使う売買・素材・検査コードを固定する。
    names=('strategy.py','engine.py','build_engine.py','catalog.py','prepare.py','check_baseline.py')
    hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in names}
    inputs,signals,fingerprints=prepare.load_inputs(True);features=strategy.initialize(inputs,signals)
    configs=[c for c in catalog.catalog() if c['stop_mode']==0]
    assert len(configs)==5
    records=[];references={}
    for model in ('observed','specified'):
        for config in configs:
            path=HERE.parent/'round8'/model/'ledgers'/(config['entry_reference']+'.pkl')
            original=pickle.loads(path.read_bytes());references[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
            for key,ready in sorted(inputs.items()):
                result,settings=strategy.play(config,ready,features[key],model=='observed')
                _,ledger,_=accounting.account(strategy.previous,ready,result,settings)
                for name in ('orders','trades','cycles','fees','time_events','insurance_events','satellite_events'):
                    np.testing.assert_array_equal(ledger[name],original[key][name],err_msg=str((config['id'],key,name)))
                for name in ('satellite_orders','satellite_trades','satellite_stats'):
                    np.testing.assert_array_equal(result[name],original[key][name])
                assert ledger['net_trades']==original[key]['net_trades']
                assert ledger['curve_SHA256']==original[key]['curve_SHA256']
                assert ledger['raw_curve_SHA256']==original[key]['raw_curve_SHA256']
                core=result['core_result'];oldcore=original[key]['core_ledger']
                for name in ('orders','trades','cycles'):np.testing.assert_array_equal(core[name],oldcore[name])
                structural=result['structure_events']
                if len(structural):np.testing.assert_array_equal(structural[:,5],structural[:,6])
                records.append(dict(model=model,id=config['id'],session=key[0],symbol=key[1],
                    旧入口出口料金時価完全一致=True,追加新規数=len(structural)))
            print(model,config['id'],'旧全60口座完全一致',flush=True)
    for name,digest in hashes.items():assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    output=dict(全合格=True,口座数=len(records),全条件数=17,性能未評価の新方式=[1,2,3],
        実装SHA256=hashes,入力SHA256=fingerprints,参照台帳SHA256=references,検査=records)
    (HERE/'旧停止と前段四入口の全会計完全一致.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
