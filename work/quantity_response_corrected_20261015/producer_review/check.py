"""生産schemaから修正版runnerへの型・逆写像・保存を実入力無しで点検する。"""

import ast
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np

sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
PRODUCER=ROOT/'work/wave_v103/input/core.py'
CORRECTION=ROOT/'work/wave_v103/input_v2/correction.py'
RUNNER=BASE/'run.py'
ENGINE=BASE/'engine.py'


def sha(path: Path) -> str:
    """
    機能: 対象source又は私有証跡の同bytes指紋を得る。
    引数: path(Path)は源又は自所有小資料。
    返り値: strはSHA256。原NPZや金融へ呼び出さない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extracted(path: Path,names: set,scope: dict) -> dict:
    """
    機能: 指定純関数だけをAST抽出し、driverのimport/main/実readを実行しない。
    引数: path(Path)、names(set[str])、scope(dict)は源・純関数名・必要binding。
    返り値: dictは純関数namespace。
    """
    tree=ast.parse(path.read_text(encoding='utf-8'));nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes}==names
    result=dict(scope);exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'::独立型接続','exec'),result)
    return result


def fixture() -> tuple[list,dict,float,float]:
    """
    機能: 二十段・累計・時計・欠測を含む六原行をメモリだけで生成する。
    引数: なし。
    返り値: tupleはJSON行素材/normal列/場上下限。実データを使わない。
    """
    start=datetime(2026,1,1,9,tzinfo=timezone(timedelta(hours=9)));rows=[];sequences=[0,1,2,4,5,6]
    for i,seq in enumerate(sequences):
        stamp=(start+timedelta(seconds=i)).isoformat()
        raw=dict(Symbol='合成',SymbolName='合成指数先物',Exchange=23,
            CurrentPrice=100.5,CurrentPriceTime=stamp,TradingVolume=[100,101,103,2,3,4][i],TradingVolumeTime=stamp,TradingValue=100000+i*1000)
        for k in range(10):
            raw['Buy'+str(k+1)]=dict(Price=100.-k*.5,Qty=10+k)
            raw['Sell'+str(k+1)]=dict(Price=100.5+k*.5,Qty=20+k)
        if i==2:raw['Buy4']['Qty']=-1
        if i==3:raw['Sell5']['Qty']=None
        if i==4:raw['ReceivedAt']=None
        rows.append((seq,raw))
    select=[0,2,5]
    normal=dict(seq=np.array([sequences[i] for i in select],np.int64),time_s=np.array([(start+timedelta(seconds=i)).timestamp() for i in select]),
        price=np.full(3,100.5),bid=np.full(3,100.),ask=np.full(3,100.5))
    return rows,normal,start.timestamp()-1,start.timestamp()+600


def main() -> None:
    """
    機能: producer44列と修正runnerの型契約を純合成で閉じ、旧失敗と本体を変更しない。
    引数: なし。
    返り値: None。私有成功/Falseだけ保存。原NPZ/cache/金融/API0。
    """
    paths=[PRODUCER,CORRECTION,RUNNER,ENGINE];before={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    output=HERE/'生産44列と修正runnerの逆写像及び保存型の独立接続.json';assert not output.exists()
    try:
        spec=importlib.util.spec_from_file_location('数量型監査_原行producerのみ',PRODUCER)
        producer=importlib.util.module_from_spec(spec);spec.loader.exec_module(producer)
        target=extracted(RUNNER,{'validate','primitive','group','summarize'},{'np':np})
        correction=extracted(CORRECTION,{'correct_arrays'},{'np':np,'CHANGED':('volume_delta_usable','volume_delta')})
        rows,normal,start,end=fixture();arrays,_=producer.extract_rows(rows,start,end,normal)
        schema=producer.schema()['columns'];assert len(arrays)==len(schema)==44
        revised,_=correction['correct_arrays'](arrays)
        frozen={name:value.copy() for name,value in revised.items()}
        target['validate'](revised,schema)
        assert revised['normal_execution_row'].dtype==np.int32 and revised['execution_to_raw_index'].dtype==np.int64
        np.testing.assert_array_equal(revised['normal_execution_row'],[0,-1,1,-1,-1,2])
        np.testing.assert_array_equal(revised['execution_to_raw_index'],[0,2,5])
        checks=0;rejected=0
        for name,value in revised.items():
            np.testing.assert_array_equal(value,frozen[name]);assert not value.flags.writeable;checks+=2
        assert np.isnan(revised['trading_value_time_s']).all() and np.isnan(revised['ask_quantities'][3,4])
        assert revised['bid_quantities'][2,3]==-1 and not revised['bid_element_valid'][2,3];checks+=4
        # ----------------------------------------
        # 欠測/負の観測値は保存のまま、bool/shape/mapの型誤認は拒否する。
        bad=[]
        a={k:v.copy() for k,v in revised.items()};a['normal_execution_row']=a['normal_execution_row'].astype(bool);bad.append(('逆写像bool',a))
        a={k:v.copy() for k,v in revised.items()};a['normal_execution_row'][1]=-2;bad.append(('未対応−2',a))
        a={k:v.copy() for k,v in revised.items()};a['normal_execution_row'][0]=2;bad.append(('正常0番の誤ID',a))
        a={k:v.copy() for k,v in revised.items()};a['execution_to_raw_index'][1]=3;bad.append(('双方向不一致',a))
        a={k:v.copy() for k,v in revised.items()};a['execution_to_raw_index']=a['execution_to_raw_index'].astype(np.int32);bad.append(('map int32',a))
        a={k:v.copy() for k,v in revised.items()};a['price_reset_reason']=a['price_reset_reason'].astype(bool);bad.append(('reset bool',a))
        a={k:v.copy() for k,v in revised.items()};a['bid_element_valid']=a['bid_element_valid'][:,:9];bad.append(('十段9列',a))
        a={k:v.copy() for k,v in revised.items()};a['bid_qty']=a['bid_qty'].astype(bool);bad.append(('Qty bool',a))
        for name,a in bad:
            try:target['validate'](a,schema)
            except AssertionError:rejected+=1
            else:raise AssertionError(('型/対応を拒否しない',name))
        empty={k:v.copy() for k,v in revised.items()};empty['normal_execution_row'][:]=-1;empty['execution_to_raw_index']=np.array([],np.int64)
        target['validate'](empty,schema);checks+=2
        # ----------------------------------------
        # 保存型は正常row0をFalseにせず、−1とNoneも区別する。
        primitive=target['primitive'](dict(normal0=np.int32(0),unknownrow=np.int32(-1),flag=np.bool_(False),empty=None,count=np.int64(3),ratio=np.float64(.5)))
        assert type(primitive['normal0']) is int and primitive['normal0']==0
        assert type(primitive['unknownrow']) is int and primitive['unknownrow']==-1
        assert type(primitive['flag']) is bool and primitive['empty'] is None
        assert json.loads(json.dumps(primitive,allow_nan=False))==primitive;checks+=5
        for value in (np.nan,np.float64(np.inf)):
            try:target['primitive']({'value':value})
            except AssertionError:rejected+=1
            else:raise AssertionError('非有限保存の拒否漏れ')
        tree=ast.parse(ENGINE.read_text(encoding='utf-8'))
        fields=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FIELDS' for t in n.targets))
        assert len(fields)==31
        ev=[];out=[]
        for ep,(ratio,minimum,code) in enumerate(((.5,.4,1),(1.,.8,-1),(1.2,1.,0),(1.1,.9,3),(1.,1.,2))):
            for kind in (0,1):
                row=np.zeros(len(fields))
                for name,value in dict(type=kind,episode=ep,d=1 if ep%2==0 else -1,bid=100.,ask=100.5,opposite_q0=10.,quantity_ratio=ratio,
                    minimum_quantity_ratio=minimum,total_volume=12.,npositive=2.).items():row[fields.index(name)]=value
                ev.append(row);out.append([code,10+ep])
        groups=target['summarize'](np.array(ev),np.array(out,float),fields,.5)
        assert groups['type1_all']['n']==5 and groups['type1_all']['resolved']==2 and groups['type1_all']['rate']==.5
        assert groups['type1_all']['unknown']==groups['type1_all']['eof']==groups['type1_all']['window_end']==1
        assert groups['type1_decreased']['n']==1 and groups['type1_maintained']['n']==4
        assert groups['type1_never_below']['n']==2 and groups['type1_recovered']['n']==2
        assert groups['type0_reached']==groups['type1_all'];checks+=13
        zero=target['summarize'](np.empty((0,31)),np.empty((0,2)),fields,.5)
        assert zero['type1_all']['rate'] is None and zero['type1_all']['n']==0;checks+=2
        json.dumps(target['primitive'](groups),allow_nan=False)
        assert before=={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
        proof=dict(全合格=True,source_SHA256=before,監査source_SHA256=sha(Path(__file__)),検査項目=checks,拒否境界=rejected,
            生産元='103 input/core.extract_rowsの6私有JSON行→v2二列訂正→修正run.validate。生産sourceを改変しない。',
            確認=['int32未対応−1と正常0を保持','int64 mapの双方向/単調/範囲を照合','44列の全値dtype/shape不変更/readonly',
                'NaNと負数量の保存を維持し、資格で使用と分離','31event列とfloat outcomes/group/空群を接続','numpy int32/int64/bool/Noneを原始型保存'],
            限界='producer/runner型接続のSOURCE_ONLY補足。coreの独立数値/正式登録検証は別担当。実NPZ品質や率を確認した証拠ではない。',
            原NPZ=0,原板=0,cache=0,金融=0,API=0)
        output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,proof_SHA256=sha(output),検査項目=checks,拒否境界=rejected),ensure_ascii=False))
    except BaseException:
        path=HERE/'型接続_初回False.json';assert not path.exists()
        path.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),source_SHA256=before,実NPZ=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8');raise


if __name__=='__main__':main()
