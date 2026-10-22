"""方向停止の判断と後続gapを別原rowに分離し、二十四入口の接続を確認する。"""

import ast
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

import independent_engine120c as test


HERE=Path(__file__).resolve().parent
OWNER=HERE.parent
C=OWNER/'recovery_c'


def main() -> None:
    """
    機能: 停止時の清算損と次気配の実返済損を分け、全新mode買売対称と源接続を確認する。
    引数: なし。
    返り値: None。市場・結果・原NPZは読まない。
    """
    os.environ.pop('NUMBA_BOUNDSCHECK',None)
    sys.path.insert(0,str(OWNER));sys.path.insert(0,str(C))
    test.E=test.load('audit120c_stopgap_closed',C/'engine120c.py')
    path=np.r_[np.arange(100.,116.),np.arange(114.,108.,-1.),90.,90.,90.,90.,90.,90.]
    path[21]=108.75
    cases=[]
    for mode in (8,9,10,11):
        for side in (1,-1):
            x=path if side==1 else 200-path
            args=test.material(x,mode,cap=4,entry_end=18,close=25)
            answer=test.run(args);o,l,c,s=answer
            stopped=l[(l[:,1]==side)&(l[:,14]==8)]
            test.check(len(stopped)==4,'三単位方向停止で同方向四玉を全部返済')
            test.check(np.all(stopped[:,7]==21) and np.all(stopped[:,8]==22),'方向停止判断二十一行の次原rowで返済')
            q=args[3][21] if side==1 else args[4][21]
            then=float(np.sum(side*(q-stopped[:,6])))
            actual=float(np.sum(stopped[:,13]))
            test.check(then==-3 and actual==-78,'判断清算損三から次BBO清算損七十八へ悪化をそのまま計上')
            cases.append(dict(mode=mode,side=side,decision_row=21,fill_row=22,decision_liquidation=-3.,executed_net=-78.))
    # ----------------------------------------
    # 四系統×三幅×二追尾だけが新運転。settings依存を小源の拘束へ含める。
    catalog=test.load('audit120c_catalog_closed',C/'catalog120c.py')
    specs=catalog.specifications()
    test.check(len(specs)==24 and len({s['id'] for s in specs})==24,'新仕様二十四だけを一意列挙')
    test.check({s['mode'] for s in specs}=={8,9,10,11},'旧八管理を新金融へ混入しない')
    test.check(all(sum(s['mode']==mode for s in specs)==6 for mode in range(8,12)),'各新mode三幅二追尾')
    tree=ast.parse((C/'run120c.py').read_text(encoding='utf8'))
    main=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main')
    text=ast.unparse(main)
    test.check(text.index('runtime120b.verify()')<text.index("(ROOT / item['path']).read_bytes()"),'runtime人工は最初の数値入力より先')
    test.check("actual['spec'] == proposal['spec']" in text and "actual['spec']['implementation'] == fixed['sources']" in text and "actual['spec']['data']['input_manifests'] == [fixed['input_manifest']]" in text,'実登録と源目録を明示照合')
    test.check("['提案完全'] is True" in text,'登録前照合の提案完全資格を必須')
    paths=[C/f for f in ('engine120c.py','catalog120c.py','runtime120c.py','run120c.py')]+[OWNER/'catalog120.py']
    sources={p.relative_to(OWNER.parents[1]).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    initial=HERE/'新四管理の信用予約と最初次気配の独立人工'/'新四管理の信用予約と最初次気配の独立人工.json'
    primary=json.loads(initial.read_text(encoding='utf8'))
    test.check(primary['passed'] is True and primary['engine_sha256']==test.EXPECTED,'初回人工を同源で委譲')
    proof=dict(passed=True,engine_sha256=test.EXPECTED,source_SHA256=sources,primary_audit_sha256=hashlib.sha256(initial.read_bytes()).hexdigest(),audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),accounting_source_sha256=hashlib.sha256(Path(test.accounting.__file__).read_bytes()).hexdigest(),checks=dict(test.CHECKS),accounting_checks=dict(test.accounting.CHECKS),stop_gap_cases=cases,original_market_reads=0,NPZ_reads=0,result_reads=0,financial_replay=0,registry_changes=0,source_changes=0,留保='停止の予定幅は損失額保証ではない。関数の本体を変えず境界検査付きJITを同プロセス人工へ拘束。前半人工と本補足は新有効性標本へ数えない。')
    target=HERE/'新四管理の次気配gapと二十四仕様接続の独立補足人工.json'
    test.accounting.save(target,proof)
    print(json.dumps(dict(passed=True,engine_sha256=test.EXPECTED,sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
