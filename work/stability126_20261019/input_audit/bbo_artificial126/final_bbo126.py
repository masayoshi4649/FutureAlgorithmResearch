"""診断境界の最終源へBBO独立人工とJIT経済同値を拘束する。"""

import hashlib
import json
from pathlib import Path
import time

import numpy as np

import check_bbo126 as test
import extend_bbo126 as extension


HERE=Path(__file__).resolve().parent


def execute() -> None:
    """
    機能: 最終BBO源で独立純人工全件を再確認し、PythonとJITも比較する。
    引数: なし。
    返り値: None。源の診断境界修正前の人工と最終人工を区別する。
    """
    sources={p.relative_to(test.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (test.BBO/'core126.py',test.BBO/'bbo_order_kernel126.py',test.BBO/'policy_bbo126.py',
                       test.ENGINE/'policy126.py',HERE.parents[1]/'design/catalog126.py',
                       HERE/'check_bbo126.py',HERE/'extend_bbo126.py',Path(__file__))}
    assert sources[(test.BBO/'core126.py').relative_to(test.ROOT).as_posix()]=='37e845db2f477b81a00402e7f42ca9c22b43f77452baa1e2851298486defe2a2'
    configs={v['id']:v for v in test.catalog()}
    test.timing_checks(configs);test.mechanisms(configs);test.future_checks(configs)
    # 追加人工は保存先だけを最終版に分けて同じ関数へ委譲する。
    # 既存証跡を書き換えないよう、実行部分のみASTで取り出す。
    import ast
    source=ast.parse((HERE/'extend_bbo126.py').read_text(encoding='utf-8'))
    fn=next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=='execute')
    assert isinstance(fn.body[2],ast.For)
    numerical=ast.Module(body=fn.body[1:3],type_ignores=[])
    namespace=dict(vars(extension))
    exec(compile(ast.fix_missing_locations(numerical),str(HERE/'extend_bbo126.py'),'exec'),namespace)
    for qty in (5,10):
        for label,value in test.mechanism_cases(qty).items():
            config=configs['I04'];python=test.run(value,config)
            jit=test.interface.play(config,value[0],value[1],value[2],value[3],use_python=False)
            test.audit(value,jit)
            for field in test.interface.FIELDS:
                test.same('JITとPythonの全九出力同値_'+str(qty)+'_'+label+'_'+field,python[field],jit[field])
    assert all(hashlib.sha256((test.ROOT/name).read_bytes()).hexdigest()==digest for name,digest in sources.items())
    proof=dict(passed=True,count=len(test.CHECKS),checks=test.CHECKS,cases=test.CASES,
        case_count=len(test.CASES),jit_case_count=6,all_nine_outputs_finite=True,sources=sources,
        prior_proofs=[dict(path=name,sha256=hashlib.sha256((HERE/name).read_bytes()).hexdigest()) for name in
                      ('次正常原行と実会計及び三部品の独立純人工.json','未来尾切断と部分利確及び固定ATRの追加独立純人工.json')],
        market_reads=0,financial_replays=0,API=0,real_orders=0,
        scope='固定人工。16設定、両数量、上下反射、実現部分益、末尾切断、未清算拒否、最終診断境界有限、Python/JIT同値。実市場の利益証明ではない。')
    target=HERE/'最終BBO源と全九出力有限性及びJITの独立純人工.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,count=len(test.CHECKS),cases=len(test.CASES),jit_cases=6),ensure_ascii=False))


if __name__=='__main__':
    try:execute()
    except Exception as error:
        target=HERE/('最終純人工停止_'+str(time.time_ns())+'.json')
        target.write_text(json.dumps(dict(passed=False,error=repr(error),checks=test.CHECKS,cases=test.CASES,
            market_reads=0,financial_replays=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
