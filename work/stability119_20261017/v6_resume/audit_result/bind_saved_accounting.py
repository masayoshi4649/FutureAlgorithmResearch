"""h保存会計adapterを旧1020人工の同一算術へ拘束する。"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def main() -> None:
    """
    機能: 会計関数同一と引用metadataだけの変換、経済値変更拒否を確認する。
    引数: なし。
    返り値: None。SOURCEと人工辞書だけの証跡を保存し結果/cacheを読まない。
    """
    here=Path(__file__).resolve().parent;new=here/'audit_result_v6_resume.py'
    old=here.parents[1]/'v6/audit_result/audit_result_v6.py'
    previous=old.parent/'二UID部分返済と注文別料及び全原行時価の監査源純人工.json'
    proof=json.loads(previous.read_bytes())
    assert proof['全合格'] and proof['検査数']==1020 and hashlib.sha256(old.read_bytes()).hexdigest()==proof['監査源SHA256']
    trees=[ast.parse(p.read_text(encoding='utf-8')) for p in (old,new)]
    functions=[{v.name:ast.dump(v,include_attributes=False) for v in tree.body if isinstance(v,ast.FunctionDef)} for tree in trees]
    names=[name for name in functions[0] if name!='main']
    assert all(functions[0][name]==functions[1][name] for name in names)
    spec=importlib.util.spec_from_file_location('_h_saved_accounting_only',new)
    value=importlib.util.module_from_spec(spec);sys.modules[spec.name]=value;spec.loader.exec_module(value)
    given={'method':'旧表示','profit':500.,'loss':200.,'net':300.,'fees':83}
    current=dict(given,method='E01_006_FIXED',actual_config='人工設定',origin='旧33保存会計の引用')
    excluded={'method','actual_config','origin','unclosed','verified_flat','verified_flat_basis','保存範囲'}
    expected={k:v for k,v in given.items() if k not in excluded}
    value.compare(current,expected,'人工引用metadata')
    current['profit']=999.;rejected=False
    try:value.compare(current,expected,'人工経済値改変')
    except AssertionError:rejected=True
    assert rejected
    result={'全合格':True,'監査源SHA256':hashlib.sha256(new.read_bytes()).hexdigest(),'旧1020人工委譲':{'path':str(previous),'SHA256':hashlib.sha256(previous.read_bytes()).hexdigest()},'算術不変関数':names,'h差分':'開始終端122源・原新読0/既stage42・新14識別・旧66表示metadataと経済値の分離。入口/出口の再生なし。','引用表示だけの差を許容':True,'経済値の差を拒否':True,'結果読取':0,'cache読取':0,'原市場':0,'金融':0,'登録':0}
    target=here/'h保存監査と旧1020人工算術の同一拘束.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
