"""反票退出の唯一差分を静的拘束し、旧ON九出力と独立OFF実玉を結ぶ。"""

import ast
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import traceback
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_price_exit_ablation_20261014/engine'
PRIVATE=HERE/'private_price_exit'
OLD=ROOT/'work/e01_protect_reentry_20261014/audit/owned'
sys.dont_write_bytecode=True;sys.path.append(str(OLD))
from protect_source_check import fixture,execute_actual
from price_exit_reference import Reference
COUNT={'ON旧九出力口座':0,'OFF独立口座':0,'配列照合':0,'接頭':0}


def economic_tree(path: Path) -> ast.Module:
    """
    機能: コメント/docstringを除いた経済構文を別々に取り出す。
    引数: path(Path) は許可された核心source。
    返り値: ast.Module は変換前の独立構文木。source本文は変えない。
    """
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    for n in ast.walk(tree):
        if isinstance(n,(ast.Module,ast.FunctionDef)) and n.body and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Constant) and isinstance(n.body[0].value.value,str):n.body.pop(0)
    return tree


def static_difference() -> None:
    """
    機能: 新boolの末尾追加と反票if一枝だけを独立に消して旧核心同値を確認する。
    引数: なし。新sourceと新所有旧ON copyだけを読む。
    返り値: None。入口又は他出口に追加差分があれば止める。
    """
    old=economic_tree(ENGINE/'baseline_core.py');new=economic_tree(ENGINE/'core.py')
    simulate=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='simulate')
    assert simulate.args.args[-1].arg=='enable_opposed_price_exit' and simulate.args.defaults[-1].value is True
    simulate.args.args.pop();simulate.args.defaults.pop();removed=0
    for n in ast.walk(new):
        if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp) and isinstance(n.test.op,ast.And) and [ast.unparse(v) for v in n.test.values]==['enable_opposed_price_exit','opposed']:
            assert any(isinstance(x,ast.Assign) and ast.unparse(x)=='reason = 152' for x in n.body)
            n.test=n.test.values[1];removed+=1
    assert removed==1 and ast.dump(new,include_attributes=False)==ast.dump(old,include_attributes=False)
    oldsource=ROOT/'work/e01_protect_reentry_20261014/engine/core.py'
    assert oldsource.read_bytes()==(ENGINE/'baseline_core.py').read_bytes()
    before=economic_tree(ROOT/'work/e01_protect_reentry_20261014/engine/interface.py')
    after=economic_tree(ENGINE/'interface.py')
    oldplay=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='play')
    newplay=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='play')
    call=next(n for n in ast.walk(newplay) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='fn')
    assert ast.unparse(call.args[-1])=="config['enable_opposed_price_exit']";call.args.pop()
    assert ast.dump(oldplay,include_attributes=False)==ast.dump(newplay,include_attributes=False)
    usage=[]
    for n in ast.walk(after):
        if isinstance(n,ast.keyword) and n.arg=='paper_remaining_quantity':usage.append(ast.unparse(n.value))
    assert usage==['int(curve[row, 13])']


class Proxy:
    """
    機能: 同じ入力を保ち、末尾反票boolだけを新核心へ追加する。
    引数: core(object)、on(bool) は私有核心と対照状態。
    返り値: Proxy は旧引数形を受ける純試験用アダプタ。
    """
    def __init__(self,core: object,on: bool):
        """
        機能: PythonとJITの両呼出へ同じboolを固定する。
        引数: core(object)、on(bool) は所有私有moduleと固定値。
        返り値: None。票や価格入力を書き換えない。
        """
        self.core=core;self.on=on
    def __call__(self,*args: tuple) -> tuple:
        """
        機能: 旧入力末尾へ固定boolだけを追加して私有JITを呼ぶ。
        引数: args(tuple) は旧simulate引数。
        返り値: tuple は新九出力。
        """
        return self.core.simulate(*args,self.on)
    def py_func(self,*args: tuple) -> tuple:
        """
        機能: 同一引数へ同一boolを追加してPython版を呼ぶ。
        引数: args(tuple) は旧simulate引数。
        返り値: tuple は新九出力。
        """
        return self.core.simulate.py_func(*args,self.on)


# ----------------------------------------
def main() -> None:
    """
    機能: 新所有16源を私有copyへ結び、必要なON/OFF対照だけを合成で検査する。
    引数: なし。完成人工/sourceだけを読み、金融/packet/台帳/APIは取得しない。
    返り値: None。Falseを保持して経済sourceへ無言で修正を加えない。
    """
    target=HERE/'反票単独OFFと旧ON九出力の独立完成16源接続.json';assert not target.exists()
    source={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    artpath=ENGINE/'反対価格票退出の単独OFFとON同値及び接頭の人工検査.json';raw=artpath.read_bytes();art=json.loads(raw.decode('utf-8-sig'))
    assert art['全合格'] and art['source_SHA256']==source and len(source)==16
    PRIVATE.mkdir(exist_ok=True)
    for relative,sha in source.items():
        path=ROOT/relative;destination=PRIVATE/path.name
        if destination.exists():assert hashlib.sha256(destination.read_bytes()).hexdigest()==sha
        else:shutil.copyfile(path,destination)
    sys.path.insert(0,str(PRIVATE));import common,core,baseline_core,catalog
    on=SimpleNamespace(simulate=Proxy(core,True));off=SimpleNamespace(simulate=Proxy(core,False))
    try:
        static_difference()
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for mode in ('ORIGIN','PULL','BREAK','ADAPTIVE'):
                    for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
                        for kind in ('opposed_reentry','native_protection','partial_cancel'):
                            rows,events=fixture(symbol,side,mode,exit_id,kind)
                            former=execute_actual(baseline_core,catalog,symbol,mode,exit_id,rows,events,False)
                            current_on=execute_actual(on,catalog,symbol,mode,exit_id,rows,events,False)
                            for a,b in zip(former[:8],current_on[:8]):np.testing.assert_array_equal(a,b);COUNT['配列照合']+=1
                            assert former[8]==current_on[8];COUNT['ON旧九出力口座']+=1
                            py=execute_actual(off,catalog,symbol,mode,exit_id,rows,events,False)
                            jit=execute_actual(off,catalog,symbol,mode,exit_id,rows,events,True)
                            for a,b in zip(py[:8],jit[:8]):np.testing.assert_allclose(a,b,equal_nan=True,atol=1e-5,rtol=1e-12);COUNT['配列照合']+=1
                            assert py[8]==jit[8] and not np.any(py[0][:,6]==152)
                            reference=Reference(symbol,mode,exit_id,price_exit_enabled=False)
                            for i,row in enumerate(rows):reference.step(i,row,events.get(i,[]))
                            expected=np.array([[o[k] for k in ('row','source','cid','side','q','price')]+[int(o['new'])] for o in reference.orders],float).reshape(-1,7)
                            np.testing.assert_array_equal(py[0][:,[0,1,2,3,4,5,7]],expected)
                            np.testing.assert_array_equal(py[1],[o['uid'] for o in reference.orders])
                            np.testing.assert_allclose(py[2][:,1],[r['liquidation'] for r in reference.curve],atol=1e-5,rtol=1e-12)
                            COUNT['配列照合']+=3;COUNT['OFF独立口座']+=1
                            for cut in (4,7):
                                prefix=execute_actual(off,catalog,symbol,mode,exit_id,rows[:cut],{i:v for i,v in events.items() if i<cut},False)
                                np.testing.assert_array_equal(prefix[0],py[0][py[0][:,0]<cut])
                                np.testing.assert_allclose(prefix[2],py[2][:cut],equal_nan=True,atol=1e-5,rtol=1e-12);COUNT['接頭']+=1
        assert source=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in ENGINE.glob('*.py')}
        value=dict(全合格=True,最終source_SHA256=source,所有人工SHA256=hashlib.sha256(raw).hexdigest(),独立確認=COUNT,
                   独立source_SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in
                       (HERE/'price_exit_reference.py',Path(__file__),OLD/'protect_source_check.py')},
                   静的結論='core末尾bool+reason152AND1だけ。他経済AST同値。interface.play差も末尾boolだけ。paper残量はpoint診断で入口/制御不使用。',
                   元108金融本文=0,新金融=0,保存packet=0,台帳=0,原板=0,API=0)
    except BaseException:
        value=dict(全合格=False,最終source_SHA256=source,独立確認=COUNT,原因=traceback.format_exc(),
                   元108金融本文=0,新金融=0,保存packet=0,台帳=0,原板=0,API=0)
        target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');raise
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('反票OFF/ON完成16源接続合格 '+str(COUNT)+' SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
