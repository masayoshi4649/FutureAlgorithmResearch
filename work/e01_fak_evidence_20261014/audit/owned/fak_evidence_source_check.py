"""完成FAK一枝だけを旧sourceへ束縛し、経済同値と拒否公開診断差を分ける。"""

import ast
import copy
from dataclasses import replace
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import traceback
import numpy as np
from evidence_state_reference import EntryReference


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_fak_evidence_20261014/engine'
PRIVATE=HERE/'private_fak_evidence'
OLD=ROOT/'work/e01_entry_information_20261014/audit/owned'
sys.dont_write_bytecode=True
sys.path.append(str(OLD))
from entry_information_source_check_v2 import tree,account,Proxy as PreviousProxy
from protect_source_check import fixture,execute_actual


def source_delta() -> None:
    """
    機能: 二価格票FAKの末尾boolと許容一枝以外が旧110同構文か検査する。
    引数: なし。完成新源と新所有旧核心copyだけを読む。
    返り値: None。入口採否・強さ閾値・費用・返済へ別差分があれば止める。
    """
    old=tree(ENGINE/'baseline_core.py');new=tree(ENGINE/'core.py')
    function=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='simulate')
    assert function.args.args[-1].arg=='require_strong_price_min2' and function.args.defaults[-1].value is False
    function.args.args.pop();function.args.defaults.pop()
    before=next(n for n in ast.walk(old) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='allowance' for t in n.targets))
    after=next(n for n in ast.walk(new) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='allowance' for t in n.targets))
    assert isinstance(after.value,ast.IfExp) and isinstance(after.value.test,ast.BoolOp)
    expected='not require_strong_price_min2 or (own_count[i] >= 2 and peer_count[i] >= 2)'
    assert ast.unparse(after.value.test.values[-1])==expected
    after.value.test.values.pop()
    assert ast.dump(after,include_attributes=False)==ast.dump(before,include_attributes=False)
    assert ast.dump(new,include_attributes=False)==ast.dump(old,include_attributes=False)
    assert (ENGINE/'baseline_core.py').read_bytes()==(ROOT/'work/e01_entry_information_20261014/engine/core.py').read_bytes()
    oldplay=next(n for n in tree(ROOT/'work/e01_entry_information_20261014/engine/interface.py').body if isinstance(n,ast.FunctionDef) and n.name=='play')
    newplay=next(n for n in tree(ENGINE/'interface.py').body if isinstance(n,ast.FunctionDef) and n.name=='play')
    call=next(n for n in ast.walk(newplay) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='fn')
    assert ast.unparse(call.args[-1])=="config['require_strong_price_min2']";call.args.pop()
    assert ast.dump(oldplay,include_attributes=False)==ast.dump(newplay,include_attributes=False)


class Proxy(PreviousProxy):
    """
    機能: 旧独立人工入力へ末尾の二価格票FAK boolだけを加える。
    引数: core(object)、allowed(ndarray[bool])、required(bool|None)、peers(dict|None)。
    返り値: Proxy は旧110引数と新111引数を同じ人工から作る。
    """
    def __init__(self,core: object,allowed: np.ndarray,required: bool|None,peers: dict|None=None):
        """
        機能: 二価格票の新枝ON/OFFを固定し、未来行で再選択しない。
        引数: core(object)、allowed(ndarray[bool])、required(bool|None)、peers(dict|None)。
        返り値: None。Noneは旧110copyへboolを足さない対照。
        """
        super().__init__(core,allowed,peers=peers);self.required=required

    def __call__(self,*args: tuple) -> tuple:
        """
        機能: 同じ旧入力を固定二価格票boolと共に私有JITへ渡す。
        引数: args(tuple) は旧独立fixture入力。
        返り値: tuple は九出力。
        """
        values=self.inputs(args)
        return self.core.simulate(*values,False,self.allowed) if self.required is None else self.core.simulate(*values,False,self.allowed,self.required)

    def py_func(self,*args: tuple) -> tuple:
        """
        機能: 同じ入力を私有Python版へ渡す。
        引数: args(tuple) は旧独立fixture入力。
        返り値: tuple は九出力。金融を実行しない。
        """
        values=self.inputs(args)
        return self.core.simulate.py_func(*values,False,self.allowed) if self.required is None else self.core.simulate.py_func(*values,False,self.allowed,self.required)


# ----------------------------------------
def main() -> None:
    """
    機能: 完成sourceへ純FAK参照を接続し、旧OFF全同値と再利用経済同値を検査する。
    引数: なし。owner完成通知後だけ実行する。
    返り値: None。source指紋と必要人工だけを新ownedへ保存する。
    """
    destination=HERE/'二価格票FAK一枝と旧経済及び完成源の独立接続.json';assert not destination.exists()
    source={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    owner_path=ENGINE/'FAK追随票二以上と保存経済同値及び接頭の人工検査_v2.json'
    raw=owner_path.read_bytes();owner=json.loads(raw.decode('utf-8-sig'))
    assert len(source)==17 and owner['全合格'] and owner['source_SHA256']==source
    PRIVATE.mkdir(exist_ok=True)
    for relative,sha in source.items():
        target=PRIVATE/Path(relative).name
        if target.exists():assert hashlib.sha256(target.read_bytes()).hexdigest()==sha
        else:shutil.copyfile(ROOT/relative,target)
    sys.path.insert(0,str(PRIVATE));import core,baseline_core,catalog,entry_gate
    count=dict(旧OFF全九同値=0,独立FAK口座=0,再利用経済同値=0,配列=0,接頭=0,拒否公開許容診断差=0)
    try:
        source_delta()
        for symbol,side,exit_id,case in itertools.product(('TOPIX','NK225'),(-1,1),('TARGET','TIGHT_TRAIL','WIDE_TRAIL'),
                ('enough','single','unknown','single_failure','single_later_paper')):
            rows,events=fixture(symbol,side,'ORIGIN',exit_id,'native_protection')
            if case in ('single','single_failure','single_later_paper'):
                rows=[replace(r,own=dict(known=True,count=1,balance=float(side)),other=dict(known=True,count=1,balance=float(side))) for r in rows]
            elif case=='unknown':
                rows=[replace(r,own=dict(known=False,count=0,balance=None),other=dict(known=False,count=0,balance=None)) for r in rows]
            if case in ('single_failure','single_later_paper'):
                tick=.5 if symbol=='TOPIX' else 10.
                r=rows[2];rows[2]=replace(r,last=r.last+side*tick,bid=r.bid+side*tick,ask=r.ask+side*tick)
                if case=='single_later_paper':
                    q=5 if symbol=='TOPIX' else 10;events[5]=[dict(new=False,cid=40,side=-side,q=q,price=rows[5].last)]
                    events[6]=[dict(new=True,cid=41,side=side,q=q,price=rows[6].last)]
            a,f=account(symbol,rows,events,3,1)
            config=next(c for c in catalog.configs() if c['entry_id']=='VOL25' and c['exit_id']==exit_id)
            allowed=entry_gate.build(a,f,config)['allowed']
            former=execute_actual(SimpleNamespace(simulate=Proxy(baseline_core,allowed,None,f)),catalog,symbol,'ORIGIN',exit_id,rows,events,False)
            off=execute_actual(SimpleNamespace(simulate=Proxy(core,allowed,False,f)),catalog,symbol,'ORIGIN',exit_id,rows,events,False)
            for aa,bb in zip(former[:8],off[:8]):np.testing.assert_array_equal(aa,bb);count['配列']+=1
            assert former[8]==off[8];count['旧OFF全九同値']+=1
            adapter=SimpleNamespace(simulate=Proxy(core,allowed,True,f))
            py=execute_actual(adapter,catalog,symbol,'ORIGIN',exit_id,rows,events,False)
            jit=execute_actual(adapter,catalog,symbol,'ORIGIN',exit_id,rows,events,True)
            for aa,bb in zip(py[:8],jit[:8]):np.testing.assert_allclose(aa,bb,equal_nan=True,atol=1e-5,rtol=1e-12);count['配列']+=1
            assert py[8]==jit[8]
            model=EntryReference(symbol,exit_id,allowed.tolist())
            for row,point in enumerate(rows):model.step(row,point,events.get(row,[]))
            orders=np.array([[o[k] for k in ('row','source','cid','side','q','price')]+[int(o['new'])] for o in model.orders],float).reshape(-1,7)
            np.testing.assert_array_equal(py[0][:,[0,1,2,3,4,5,7]],orders)
            np.testing.assert_array_equal(py[1],[o['uid'] for o in model.orders])
            np.testing.assert_allclose(py[2][:,1],[r['liquidation'] for r in model.curve],atol=1e-5,rtol=1e-12)
            count['配列']+=3;count['独立FAK口座']+=1
            if case=='single':assert len(py[0])>0 and py[3][0,11]==0
            if case=='single_failure':assert len(py[0])==0
            if case=='single_later_paper':assert len(py[0])>0 and py[6][0,1]==41
            for cut in (3,7):
                pf={k:f[k][:cut] for k in ('peer_known','peer_count','peer_balance')}
                prefix=execute_actual(SimpleNamespace(simulate=Proxy(core,allowed[:cut],True,pf)),catalog,symbol,'ORIGIN',exit_id,rows[:cut],{i:v for i,v in events.items() if i<cut},False)
                np.testing.assert_array_equal(prefix[0],py[0][py[0][:,0]<cut]);np.testing.assert_allclose(prefix[2],py[2][:cut],equal_nan=True,atol=1e-5,rtol=1e-12)
                count['接頭']+=1
            for entry_id in ('PRICE_BOTH','VOL25_PRICE_BOTH'):
                reused=dict(config,entry_id=entry_id);mask=entry_gate.build(a,f,reused)['allowed']
                old=execute_actual(SimpleNamespace(simulate=Proxy(baseline_core,mask,None,f)),catalog,symbol,'ORIGIN',exit_id,rows,events,False)
                new=execute_actual(SimpleNamespace(simulate=Proxy(core,mask,True,f)),catalog,symbol,'ORIGIN',exit_id,rows,events,False)
                for index in (0,1,2,4,5,6,7):np.testing.assert_array_equal(old[index],new[index]);count['配列']+=1
                assert old[8]==new[8]
                np.testing.assert_array_equal(old[3][old[3][:,12]==1],new[3][new[3][:,12]==1])
                count['拒否公開許容診断差']+=int(not np.array_equal(old[3][:,10:12],new[3][:,10:12],equal_nan=True))
                count['再利用経済同値']+=1
        assert source=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in ENGINE.glob('*.py')}
        output=dict(全合格=True,完成source_SHA256=source,所有人工SHA256=hashlib.sha256(raw).hexdigest(),独立確認=count,
            独立source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'fak_evidence_reference.py',HERE/'evidence_state_reference.py',Path(__file__))},
            留保='旧OFFは全九出力exact。新PRICE/ANDは実経済/注文/UID/実曲線/acceptedpub同値。拒否pub許容診断の差を旧保存へ補完しない。実効能は未測。',
            金融=0,原input=0,台帳=0,旧110金融本文=0,API=0,正式登録接続=False)
    except BaseException:
        output=dict(全合格=False,完成source_SHA256=source,独立確認=count,原因=traceback.format_exc(),金融=0,原input=0,台帳=0,旧110金融本文=0,API=0)
        destination.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');raise
    destination.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,独立確認=count,SHA256=hashlib.sha256(destination.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
