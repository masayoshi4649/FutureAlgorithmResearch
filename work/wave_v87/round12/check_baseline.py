"""指値条件の全場成績を計算せず、元GUと無条件次観測の基準を照合する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(name,path):
    """
    機能: 今回の対照と旧会計・入力を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj)
    return obj


def same(a,b,label):
    """
    機能: 注文・決済脚・親組・料金・全行時価の保存会計を比較する。
    引数: a/b(dict)、label(str)。
    返り値: None。
    """
    for name in ('orders','trades','cycles','fees'):np.testing.assert_array_equal(a[name],b[name],err_msg=label+' '+name)
    assert a['net_trades']==b['net_trades'],label
    assert a['curve_SHA256']==b['curve_SHA256'],label
    assert a['raw_curve_SHA256']==b['raw_curve_SHA256'],label


def main():
    """
    機能: 二つの無変更対照を全60口座で照合して指紋を保存する。
    引数: なし。
    返り値: None。新規指値八幅の全場損益は評価しない。
    """
    strategy=module('wave87_round12_strategy',HERE/'strategy.py')
    catalog=module('wave87_round12_catalog',HERE/'catalog.py')
    prepare=module('wave85_prepare',ROOT/'work/wave_v85/prepare.py')
    accounting=module('wave85_research',ROOT/'work/wave_v85/research.py')
    names=('strategy.py','engine.py','catalog.py','check_baseline.py')
    hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in names}
    sourcepath=ROOT/'work/wave_v85/observed/ledgers/E01_G_U.pkl'
    nextpath=HERE.parent/'round10/observed/ledgers/GU_G.pkl'
    original=pickle.loads(sourcepath.read_bytes());following=pickle.loads(nextpath.read_bytes())
    inputs,signals,fingerprints=prepare.load_inputs(True);features=strategy.initialize(inputs,signals)
    configs={c['id']:c for c in catalog.catalog()};checks=[]
    for key,ready in sorted(inputs.items()):
        result,settings=strategy.play(configs['L_GU_IDEAL'],ready,features[key],True)
        _,ledger,_=accounting.account(strategy.previous,ready,result,settings)
        same(ledger,original[key],str((key,'元GU')))
        actual,newsettings=strategy.play(configs['L_GU_NEXT'],ready,features[key],True)
        _,newledger,_=accounting.account(strategy.previous,ready,actual,newsettings)
        same(newledger,following[key],str((key,'無条件次観測')))
        np.testing.assert_array_equal(actual['order_uids'],following[key]['order_uids'])
        checks.append(dict(session=key[0],symbol=key[1],元GU完全一致=True,無条件次観測完全一致=True))
        print(key[0],key[1],'二対照完全一致',flush=True)
    for name,digest in hashes.items():assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    proof=dict(全合格=True,口座数=len(checks),指値八幅の新全場性能未計算=True,
        実装SHA256=hashes,入力SHA256=fingerprints,
        参照台帳SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (sourcepath,nextpath)},検査=checks)
    (HERE/'元GUと無条件次観測の全台帳一致.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
