"""新候補損益を見る前に元GUと無条件の次観測実行だけを全口座照合する。"""
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
    機能: 読取元と今回の対照実装を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


def same(a,b,label):
    """
    機能: 実注文・決済脚・親組・料金・全行時価の保存結果を照合する。
    引数: a/b(dict)、label(str)。
    返り値: None。
    """
    for name in ('orders','trades','cycles','fees'):
        np.testing.assert_array_equal(a[name],b[name],err_msg=label+' '+name)
    assert a['net_trades']==b['net_trades'],label
    assert a['curve_SHA256']==b['curve_SHA256'],label
    assert a['raw_curve_SHA256']==b['raw_curve_SHA256'],label


def main():
    """
    機能: 60口座の元仮想と旧次観測対照を全一致確認し、制限条件の新損益は計算しない。
    引数: なし。
    返り値: None。実装と参照元の指紋付き日本語JSONを保存する。
    """
    strategy=module('wave87_round11_strategy',HERE/'strategy.py')
    catalog=module('wave87_round11_catalog',HERE/'catalog.py')
    prepare=module('wave85_prepare',ROOT/'work/wave_v85/prepare.py')
    accounting=module('wave85_research',ROOT/'work/wave_v85/research.py')
    names=('strategy.py','engine.py','catalog.py','prepare.py','check_baseline.py')
    hashes={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in names}
    oldpath=ROOT/'work/wave_v85/observed/ledgers/E01_G_U.pkl'
    nextpath=HERE.parent/'round10/observed/ledgers/GU_N.pkl'
    original=pickle.loads(oldpath.read_bytes());following=pickle.loads(nextpath.read_bytes())
    refs={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in (oldpath,nextpath)}
    inputs,signals,fingerprints=prepare.load_inputs(True);features=strategy.initialize(inputs,signals)
    configs={c['id']:c for c in catalog.catalog()};checks=[]
    for key,ready in sorted(inputs.items()):
        core,settings=strategy.virtual(configs['P_GU_IDEAL'],ready,features[key])
        _,ledger,_=accounting.account(strategy.previous,ready,core,settings)
        same(ledger,original[key],str((key,'元GU')))
        stored_feed=strategy.prepare.feed_from_ledger(original[key]);new_feed=strategy.prior.order_feed(core)
        np.testing.assert_array_equal(stored_feed,new_feed)
        wrapped,_=strategy.play(configs['P_GU_IDEAL'],ready,features[key],True)
        _,ideal,_=accounting.account(strategy.previous,ready,wrapped,settings)
        same(ideal,original[key],str((key,'理想対照')))
        actual,newsettings=strategy.play(configs['P_E0_H0'],ready,features[key],True)
        _,nextledger,_=accounting.account(strategy.previous,ready,actual,newsettings)
        same(nextledger,following[key],str((key,'無条件次観測')))
        np.testing.assert_array_equal(actual['order_uids'],following[key]['order_uids'])
        checks.append(dict(session=key[0],symbol=key[1],元GU完全一致=True,新規時ATR素材完全一致=True,
            理想対照完全一致=True,無条件次観測完全一致=True,同じ入口条件件数=int(np.sum(actual['peer_events'][:,1]==1))))
        print(key[0],key[1],'三対照一致',flush=True)
    for name,digest in hashes.items():assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest
    result=dict(全合格=True,口座数=len(checks),相手制限条件の新性能未計算=True,実装SHA256=hashes,
        参照台帳SHA256=refs,入力SHA256=fingerprints,検査=checks)
    (HERE/'元GUと無条件次観測の全台帳一致.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
