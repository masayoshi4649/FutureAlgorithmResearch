"""新実行層に渡す四つの仮想規則が旧全台帳と完全一致することを検査する。"""
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
    機能: 新接続と旧準備・会計を読み取る。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


def main():
    """
    機能: 仮想四条件だけを再生し、旧全240口座の売買・料金・全行時価を照合する。
    引数: なし。
    返り値: None。次観測実行という新候補の全場損益は評価しない。
    """
    strategy=module('wave87_round10_strategy',HERE/'strategy.py')
    catalog=module('wave87_round10_catalog',HERE/'catalog.py')
    prepare=module('wave85_prepare',HERE.parents[1]/'wave_v85/prepare.py')
    accounting=module('wave85_research',HERE.parents[1]/'wave_v85/research.py')
    names=('strategy.py','engine.py','catalog.py','fee_account.py','check_baseline.py')
    hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in names}
    inputs,signals,fingerprints=prepare.load_inputs(True);features=strategy.initialize(inputs,signals)
    configs=[c for c in catalog.catalog() if c['execution_mode']=='G']
    rows=[];references={};same_row_multi=[]
    for config in configs:
        root=HERE.parents[1]/'wave_v85' if config['source_round']==85 else HERE.parent/f"round{config['source_round']}"
        path=root/'observed/ledgers'/(config['source_id']+'.pkl')
        original=pickle.loads(path.read_bytes());references[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        for key,ready in sorted(inputs.items()):
            result,settings=strategy.virtual(config,ready,features[key])
            _,ledger,_=accounting.account(strategy.prior.previous,ready,result,settings)
            for name in ('orders','trades','cycles','fees'):
                np.testing.assert_array_equal(ledger[name],original[key][name],err_msg=str((config['id'],key,name)))
            assert ledger['net_trades']==original[key]['net_trades']
            assert ledger['curve_SHA256']==original[key]['curve_SHA256']
            assert ledger['raw_curve_SHA256']==original[key]['raw_curve_SHA256']
            feed=strategy.order_feed(result)
            for row in np.unique(feed[:,0]):
                parentids=np.unique(feed[feed[:,0]==row,2])
                if len(parentids)>1:same_row_multi.append(dict(id=config['id'],session=key[0],symbol=key[1],row=int(row),組=parentids.tolist()))
            if config['source_round']==85:
                ideal=next(c for c in catalog.catalog() if c['execution_mode']=='IDEAL')
                wrapped,other=strategy.play(ideal,ready,features[key],True)
                _,copy,_=accounting.account(strategy.previous,ready,wrapped,other)
                for name in ('orders','trades','cycles','fees'):np.testing.assert_array_equal(copy[name],ledger[name])
                assert copy['curve_SHA256']==ledger['curve_SHA256'] and copy['net_trades']==ledger['net_trades']
            rows.append(dict(source=config['source_id'],session=key[0],symbol=key[1],旧仮想完全一致=True))
        print(config['source_id'],'旧仮想全60口座完全一致',flush=True)
    for name,digest in hashes.items():assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    out=dict(全合格=True,口座数=len(rows),新実行層の全場損益未評価=True,
        実装SHA256=hashes,入力SHA256=fingerprints,参照台帳SHA256=references,
        同一行複数仮想組=same_row_multi,検査=rows)
    (HERE/'四つの仮想規則と元GU対照の全会計完全一致.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
