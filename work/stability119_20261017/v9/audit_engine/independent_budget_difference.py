"""予約時spreadを加えた一行差分を旧独立人工へ拘束し、原因対照を小人工で検査する。"""

import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
V9=HERE.parent
BASE=V9.parent
ROOT=BASE.parents[1]


def load(path: Path,name: str) -> object:
    """
    機能: 閉鎖SOURCEだけを標準名で接続しJITのmodule名を一致させる。
    引数: path(Path)、name(str)はSOURCEとmodule名。
    返り値: objectは数値部品。市場又は完成結果は読まない。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


def main() -> None:
    """
    機能: 初期清算損の旧新差と変えない極値・実費用・数量・因果性を独立確認する。
    引数: なし。
    返り値: None。小証跡のみ保存し市場/cache/既v8結果/金融/登録は使用しない。
    """
    paths={name:V9/name for name in ('engine_v9.py','run_v9.py','plan_v9.py')}
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()}
    expected=['c6da10245a2157d684e362b04bc5b6d4afde927693be82acbad129f5d22b0314','534d13ad7e5afa80e3e926fe68e61dc0104624715be6b7a26083e3d51d5ec406','e54a4b4cbe4e79c2395e76330847badcb2aba59677af579f110e0f7e0ed70bda']
    assert list(sources.values())==expected
    old_payload=(BASE/'v8/engine_v8.py').read_bytes();new_payload=paths['engine_v9.py'].read_bytes()
    assert hashlib.sha256(old_payload).hexdigest()=='499d00b4fd88418ee1e3a6894d64eb31fe95b25479403e8f9bb106a51d07b1fc'
    old_line=b'budget = (extreme - signed) * nominal + roundtrip_fee'
    new_line=b'budget = (extreme - signed) * nominal + estimated'
    assert new_payload.count(new_line)==1 and new_payload.replace(new_line,old_line)==old_payload
    previous=BASE/'v8/audit_engine/固定準備と二確認reset及び共同時計の独立人工.json'
    assert json.loads(previous.read_bytes())['passed'] is True
    old=load(BASE/'v8/engine_v8.py','engine_v8');new=load(paths['engine_v9.py'],'engine_v9')
    fixture_path=BASE/'v8/audit_engine/independent_v8.py';tree=ast.parse(fixture_path.read_text(encoding='utf-8'))
    outer=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=='main')
    case_ast=next(v for v in outer.body if isinstance(v,ast.FunctionDef) and v.name=='case')
    namespace={'np':np,'math':math,'engine':new}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[case_ast],type_ignores=[])),str(fixture_path),'exec'),namespace)
    case=namespace['case'];checks=[]
    def check(value: bool,label: str) -> None:
        """
        機能: 旧新差の独立期待を記録する。
        引数: value(bool)、label(str)は判定と内容。
        返り値: None。不一致なら停止する。
        """
        assert value,label
        checks.append(label)
    base=[(120.,.01),(121.,.0094),(122.,.0094),(123.,.0094),(124.,.0094)]
    width={t:(50.,1.) for t,_ in base}
    for sign in (1,-1):
        path=[(t,sign*d) for t,d in base]
        for mode in (0,1):
            namespace['engine']=old;i=case(path,mode,widths=width)
            namespace['engine']=new;j=case(path,mode,widths=width)
            check(i[1][0,5]==3. and i[1][0,4]==123. and i[1][0,1]==1.,'旧予算はLast不変の初回清算損だけで停止')
            check(j[1][0,5]==0. and j[1][0,1]==0. and len(j[0])==2,'新予算はLast不変の初回清算損だけでは停止しない')
            spread_cost=j[4][0,15]*10.*50.+j[4][0,16]*1000.*1.
            check(math.isclose(j[4][0,12]-i[4][0,12],spread_cost,abs_tol=1e-6),'増やした予算額は予約時両spreadだけ')
            check(j[4][0,7]==i[4][0,7] and np.array_equal(i[0][:2],j[0][:2],equal_nan=True),'固定極値と実新規約定及び徴収料は旧新同一')
            expected_fee=2.*sum(math.floor(j[4][0,15+k]*(11. if k==0 else 41.8)+1e-9) for k in (0,1))
            check(j[4][0,14]==expected_fee+spread_cost,'予約時estimatedは往復明示料とspreadを別加算')
    namespace['engine']=new
    wider=dict(width,**{})
    wider[123.]=(500.,10.)
    changed=case(base,widths=wider)
    normal=case(base,widths=width)
    check(changed[1][0,5]==3. and changed[4][0,12]==normal[4][0,12],'約定時の不利気配でも予約予算を後から広げない')
    peak=case(base+[(125.,.0101),(126.,.0101)],widths=width)
    check(peak[1][0,5]==2. and peak[1][0,4]==125.,'予算拡大後も同じ固定極値で撤回')
    prefix=case(base,cut=123.,widths=width)
    future=case(base[:4]+[(124.,-.1),(125.,-.1)],widths=width)
    check(np.array_equal(prefix[0],future[0][future[0][:,6]<=123.],equal_nan=True),'予算変更後も未来置換で過去注文不変')

    # ----------------------------------------
    # driverと目録は同八仕様を保ち、旧320行を売買へ渡さない。
    sys.path.insert(0,str(V9));runner=load(paths['run_v9.py'],'run_v9')
    specs=runner.make_specs();check(len(specs)==8 and all(s['id']==s['baseline_id']+'_CB' for s in specs),'八仕様は旧IDへの明示的予算差分')
    metadata_path=V9/'入力目録.json';metadata_bytes=metadata_path.read_bytes();metadata=json.loads(metadata_bytes)
    inherited=(ROOT/metadata['inherited_manifest']['path']).read_bytes()
    check(hashlib.sha256(inherited).hexdigest()==metadata['inherited_manifest']['sha256'],'元v8小目録SHA一致')
    original=json.loads(inherited)
    check(metadata['inputs']==original['inputs'] and metadata['sessions']==original['sessions'] and metadata['splits']==original['splits'],'80入力と40場及び区分を不変更')
    driver_tree=ast.parse(paths['run_v9.py'].read_text(encoding='utf-8'))
    main_fn=next(v for v in driver_tree.body if isinstance(v,ast.FunctionDef) and v.name=='main')
    run_calls=[v for v in ast.walk(main_fn) if isinstance(v,ast.Call) and isinstance(v.func,ast.Attribute) and v.func.attr=='run_pair']
    check(len(run_calls)==1 and not any(isinstance(v,ast.Name) and v.id.startswith('baseline') for v in ast.walk(run_calls[0])),'保存baselineは実売買入力へ戻さない')
    check(metadata['saved_baseline']['sha256']=='2f7c15e27d7c0e20b6b14de8ab682ac62d49a55b6ba35d2079b6245d9699dcf4','旧320引用の完成SHAを固定')

    # ----------------------------------------
    # 終了反映は許可ID定数一行以外、直前の全人工合格源と同bytes。
    finalizer=BASE/'finalize119.py';final_bytes=finalizer.read_bytes()
    identity='119j_相対復帰の初期気配差を含む清算予算の対照'
    lines=final_bytes.decode('utf-8').splitlines(keepends=True)
    matches=[i for i,line in enumerate(lines) if line.strip()==repr(identity)+',']
    assert len(matches)==1;del lines[matches[0]]
    check(hashlib.sha256(''.join(lines).encode('utf-8')).hexdigest()=='2a75784d45c3781c8b93a985563ed600b042bc7c63b9f06ae9895d2263b92e2d','finalizerはj許可定数一行だけの変更')
    assert all(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha for path,sha in sources.items())
    proof={'passed':True,'economic_sources':sources,'checks':checks,'core_difference':'budgetのroundtrip_feeをestimatedへ一行だけ変更。他の全bytesはv8と同一。','delegated_v8_51':{'path':previous.relative_to(ROOT).as_posix(),'SHA256':hashlib.sha256(previous.read_bytes()).hexdigest()},'input_manifest':{'path':metadata_path.relative_to(ROOT).as_posix(),'SHA256':hashlib.sha256(metadata_bytes).hexdigest()},'finalizer':{'SHA256':hashlib.sha256(final_bytes).hexdigest(),'許可ID定数だけ':True},'market_reads':0,'cache_reads':0,'old_v8_result_reads':0,'formal_financial_replay':0,'registry_changes':0,'source_changes':0,'留保':'cashの損失許容を増やす設計対照であり、会計誤り修正や価格損失額の保証ではない。'}
    target=HERE/'初期spread予算一行差分と同値fill及び旧源拘束の独立人工.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(len(checks),hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
