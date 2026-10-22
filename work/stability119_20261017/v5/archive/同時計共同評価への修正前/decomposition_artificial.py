"""実運転を再実行せず、厳密な二脚分解の保存診断と既接続人工の由来を確認する。"""

import ast
import hashlib
import json
from pathlib import Path

import numpy as np

import run_v5 as R


HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 二脚・単脚・未清算の分解境界を合成値で確認し、現三源へ再接続する。
    引数: なし。
    返り値: None。元57接続人工・市場・正式金融は再実行しない。
    """
    target=HERE/'相対と共通元本差の厳密分解及び接続人工の委譲.json';assert not target.exists()
    cols={name:i for i,name in enumerate(R.engine_v5.PARENT_COLUMNS)};examples=[]
    for side in (1.,-1.):
        row=np.zeros(len(cols));entry_nk=60000.;entry_top=4000.;exit_nk=entry_nk+side*1000;exit_top=entry_top+side*20
        values=dict(parent=len(examples),complete=1.,side_nk=side,target_quantity_nk=20.,target_quantity_top=3.,entry_nk=entry_nk,entry_top=entry_top,
            exit_nk=exit_nk,exit_top=exit_top,beta=1.1,gross_nk=200000.,gross_top=-60000.,fees_nk=440.,fees_top=250.,net=139310.,filled_legs=2.)
        for key,value in values.items():row[cols[key]]=value
        examples.append(row)
    single=np.zeros(len(cols));single[cols['parent']]=2;single[cols['complete']]=1;single[cols['filled_legs']]=1
    single[cols['gross_nk']]=1000.;single[cols['fees_nk']]=22.;single[cols['net']]=978.;examples.append(single)
    unclosed=np.zeros(len(cols));unclosed[cols['parent']]=3;unclosed[cols['complete']]=0;unclosed[cols['filled_legs']]=1
    unclosed[cols['fees_nk']]=22.;unclosed[cols['net']]=478.;examples.append(unclosed)
    result=R.decompose_parents(np.asarray(examples))
    assert result['totals']['paired_parents']==2 and result['totals']['single_leg_parents']==result['totals']['unclosed_parents']==1
    assert np.isclose(result['totals']['paired_gross'],280000.) and result['totals']['paired_fees']==1380. and result['totals']['paired_net']==278620.
    assert np.isclose(result['totals']['relative_gross'],268000.) and np.isclose(result['totals']['common_gross'],12000.)
    assert all(p['relative_gross'] is None and p['common_gross'] is None for p in result['parents'][2:])
    assert result['totals']['single_leg_net']==978. and result['parents'][3]['net']==478.
    before=HERE/'archive/相対と共通要因の保存診断追加前/run_v5.py'
    parse=lambda p:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(p.read_text(encoding='utf8')).body if isinstance(n,ast.FunctionDef)}
    a,b=parse(before),parse(HERE/'run_v5.py')
    untouched=('read','clean','save','make_specs','settings','load_market','verify_run_contract','pack_answer','store_npz')
    assert all(a[k]==b[k] for k in untouched)
    oldproof=HERE/'archive/相対と共通要因の保存診断追加前/二脚核心と固定四条件及び保存接口の人工検査.json'
    inherited=json.loads(oldproof.read_text(encoding='utf8'));assert inherited['passed'] and inherited['total_checks']==57
    sources={p.relative_to(R.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'run_v5.py',HERE/'plan_v5.py',HERE/'engine_v5.py')}
    assert inherited['source_SHA256'][(HERE/'engine_v5.py').relative_to(R.ROOT).as_posix()]==sources[(HERE/'engine_v5.py').relative_to(R.ROOT).as_posix()]
    proof=dict(passed=True,scope='事後保存の分解恒等式と現sourceへの由来接続。核心又は四条件の正式再生ではない。',checks=8,
        source_SHA256=sources,delegate=dict(path=oldproof.relative_to(R.ROOT).as_posix(),sha256=hashlib.sha256(oldproof.read_bytes()).hexdigest(),checks=57,再実行=0),
        diagnosis=result,market_reads=0,owned_cache_reads=0,formal_finance=0,API=0,registry_changes=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=8,sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
