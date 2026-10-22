"""中値からLastへ変える新規参照だけの対照を、保存金融無しで独立確認する。"""

import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

import independent_engine120c as common


HERE=Path(__file__).resolve().parent
OWNER=HERE.parent
C=OWNER/'recovery_c'
D=OWNER/'recovery_d'
SOURCE=D/'engine120d.py'
EXPECTED='fae6bf78149b697c724d40d444b580e217711558aa54eb3509e13c7ee452726a'
OUT=HERE/'最終約定値だけを新規参照とする独立人工'
CHECKS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: Last参照変更の独立期待を意味別に記録し不一致で停止する。
    引数: value(bool)、label(str)は判定と内容。
    返り値: None。
    """
    assert bool(value),label
    CHECKS[label]+=1


def same(actual: tuple,expected: tuple,label: str) -> None:
    """
    機能: 注文・玉・曲線・集計の全保存列を完全比較する。
    引数: actual/expected(tuple)、label(str)は比較する人工出力。
    返り値: None。
    """
    for a,b,name in zip(actual,expected,('注文','玉','曲線','集計')):
        check(a.shape==b.shape and np.array_equal(a,b,equal_nan=True),label+'の'+name+'完全同値')


def run(args: tuple) -> tuple:
    """
    機能: Last参照JITとPythonを照合し、独立UID・BBO会計へ接続する。
    引数: args(tuple)はLastとBBOを別々に持つ合成観測。
    返り値: tupleはJIT出力。市場・実金融を再生しない。
    """
    answer=common.E.replay(*args);same(answer,common.E.replay.py_func(*args),'Last参照JITとPython')
    common.account(args,answer)
    if args[10]>=8:common.features(args,answer)
    return answer


def main() -> None:
    """
    機能: 全十二管理の同値、Lastと中値の逆行、BBO執行固定、FAK、未来不変を人工だけで検査する。
    引数: なし。
    返り値: None。新源は編集せず、固定可能なpassedとengine_sha256を保存する。
    """
    original=SOURCE.read_bytes();check(hashlib.sha256(original).hexdigest()==EXPECTED,'d源開始SHA')
    ctext=(C/'engine120c.py').read_text(encoding='utf8');dtext=original.decode('utf8').replace('\r\n','\n')
    expected=ctext.replace('mid = (bid[i] + ask[i]) * .5','mid = (bid[i] + ask[i]) * .5\n        reference = last[i]')
    pairs=(('anchor[:, :] = mid','anchor[:, :] = reference'),('previous_mid = mid','previous_mid = reference'),('anchor[s, j] = mid','anchor[s, j] = reference'),('state[s, j], anchor[s, j] = 0, mid','state[s, j], anchor[s, j] = 0, reference'),('state[other, k], anchor[other, k] = 0, mid','state[other, k], anchor[other, k] = 0, reference'),('move = mid - previous_mid','move = reference - previous_mid'),('min(anchor[s, j], mid) if side == 1 else max(anchor[s, j], mid)','min(anchor[s, j], reference) if side == 1 else max(anchor[s, j], reference)'),('crossed = mid >= line and move > 0. if side == 1 else mid <= line and move < 0.','crossed = reference >= line and move > 0. if side == 1 else reference <= line and move < 0.'))
    for before,after in pairs:
        check(before in expected,'参照差分の置換元が存在');expected=expected.replace(before,after)
    check(expected==dtext,'源差分はLast参照と待機再準備だけ')
    os.environ.pop('NUMBA_BOUNDSCHECK',None)
    common.E=common.load('audit120d_closed_engine',SOURCE);c=common.load('audit120d_parent_c_engine',C/'engine120c.py')
    rng=np.random.default_rng(20261017);mid=(65000+np.cumsum(rng.integers(-4,5,100))*10).astype(float)
    legacy=[]
    for cap in (2,20):
        for mode in range(12):
            args=(np.arange(len(mid),dtype=np.int64),np.arange(len(mid),dtype=float),mid,mid-10,mid+10,cap,10.,11.,10.,.000125,mode,1.,0.,90.,95.,101.)
            answer=run(args);same(answer,c.replay(*args),'Last等中値なら全十二管理')
            legacy.append(dict(cap=cap,mode=mode,entries=int(answer[3][13])))
    # ----------------------------------------
    # 同じBBOが下降してもLastが上昇する人工では、入口方向だけが意図通り分かれる。
    mid=np.array([100,99,98,97,96,95,94,94,94,94,94,94.])
    last=np.array([100,101,102,103,104,105,106,106,106,106,106,106.])
    divergent=[]
    for mode in range(8,12):
        args=list(common.material(mid,mode,cap=1,entry_end=6,close=9));args[2]=last
        d=run(tuple(args));old=c.replay(*tuple(args))
        de=d[0][d[0][:,1]==1];ce=old[0][old[0][:,1]==1]
        check(len(de)>0 and de[0,2]==1 and de[0,3]==3,'Last上昇でdは買いを判断')
        check(len(ce)>0 and ce[0,2]==-1 and ce[0,3]==3,'同じ中値下降でcは売りを判断')
        check(de[0,7]==args[4][4],'新参照でも買いは次正常BBOのask')
        check(de[0,12]==mid[3],'判断中値の記録はLastへ置き換えない')
        divergent.append(dict(mode=mode,c_first_side=int(ce[0,2]),d_first_side=int(de[0,2]),decision_row=3,d_fill=float(de[0,7])))
    # ----------------------------------------
    # 単位は最初の中値、注文限界は判断BBO。Lastの大きさや方向へ置き換えない。
    flat=np.full(12,100.);last=np.array([500,501,502,503,504,504,504,504,504,504,504,504.])
    args=list(common.material(flat,8,cap=1,entry_end=6,close=9));args[2]=last
    answer=run(tuple(args));check(answer[3][16]==1,'単位は最初の中値のまま')
    check(np.any(answer[0][:,1]==1),'Last参照は中値が固定でも発火できる')
    for side in (1,-1):
        last=np.array([100,100,103,103,103,103,103,103,103,103,103,103.]);mid=np.array([100,100,100,102,101,101,101,101,101,101,101,101.])
        if side==-1:last=200-last;mid=200-mid
        args=list(common.material(mid,10,cap=1,entry_end=6,close=9));args[2]=last
        answer=run(tuple(args));check(not np.any((answer[0][:,1]==1)&(answer[0][:,2]==side)) and answer[3][14]>0,'Last条件成立後も最初BBO一tick超過はFAK失効')
        boundary=mid.copy();boundary[3]=101 if side==1 else 99
        args[3]=boundary-.5;args[4]=boundary+.5
        answer=run(tuple(args));check(np.any((answer[0][:,1]==1)&(answer[0][:,2]==side)),'Last参照でもBBO一tick境界は買売対称に許可')
    # ----------------------------------------
    # 実商品上限と料金で、Last未来だけの変更が前半の注文・資産を変えない。
    for mode in range(8,12):
        for cap,mult,fee,tick,base,half in ((10,1000.,41.8,.5,4000.,.25),(20,10.,11.,10.,65000.,5.)):
            n=160;mid=base+np.cumsum(rng.integers(-3,4,n))*tick
            last=base+np.cumsum(rng.integers(-5,6,n))*tick
            args=(np.arange(n,dtype=np.int64),np.arange(n,dtype=float),last,mid-half,mid+half,cap,mult,fee,tick,.000125,mode,1.,0.,150.,155.,161.)
            full=run(args);prefix=list(args);prefix[:5]=[v[:60] for v in args[:5]];short=run(tuple(prefix))
            changed=list(args);new_last=last.copy();new_last[60:]=last[59]+np.arange(n-60)*tick*5;changed[2]=new_last
            replaced=run(tuple(changed))
            same((short[0],short[1]),(replaced[0][replaced[0][:,4]<=59],replaced[1][replaced[1][:,8]<=59]),'Last未来置換の前半注文玉')
            for point in short[2][:-1]:
                check(np.array_equal(point,replaced[2][replaced[2][:,0]==point[0]][0],equal_nan=True),'Last未来置換の前半全在庫資産不変')
    sys.path.insert(0,str(OWNER));sys.path.insert(0,str(D))
    catalog=common.load('audit120d_catalog_closed',D/'catalog120d.py');specs=catalog.specifications()
    check(len(specs)==24 and len({s['id'] for s in specs})==24 and all('_LAST_' in s['id'] for s in specs),'d新二十四IDはLast対照として一意')
    check({s['mode'] for s in specs}=={8,9,10,11},'d実金融は新四管理のみ')
    paths=[D/name for name in ('engine120d.py','catalog120d.py','run120d.py','runtime120d.py')]+[OWNER/'catalog120.py']
    sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    check(SOURCE.read_bytes()==original,'d源終端SHA不変')
    proof=dict(passed=True,engine_sha256=EXPECTED,source_SHA256=sources,audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),accounting_source_sha256=hashlib.sha256(Path(common.accounting.__file__).read_bytes()).hexdigest(),checks=dict(CHECKS),causal_checks=dict(common.CHECKS),accounting_checks=dict(common.accounting.CHECKS),legacy_cases=legacy,divergent_cases=divergent,original_market_reads=0,NPZ_reads=0,result_reads=0,financial_replay=0,registry_changes=0,source_changes=0,留保='入力Lastは既118/119の正常price資格と正常BBOを持つ保存行を前提とする。Lastに変えるだけで予測が改善するという証明ではない。BBO約定・費用・停止・追加信用を固定した因果的な入口参照対照の人工検査。')
    common.accounting.save(OUT/'Last参照だけの差分と全十二管理同値の独立人工.json',proof)
    print(json.dumps(dict(passed=True,engine_sha256=EXPECTED,checks=sum(CHECKS.values()),accounting_checks=sum(common.accounting.CHECKS.values())),ensure_ascii=False),flush=True)


ROOT=OWNER.parents[1]
if __name__=='__main__':
    try:main()
    except BaseException as exc:
        target=OUT/'人工False.json'
        if not target.exists():common.accounting.save(target,dict(passed=False,error_type=type(exc).__name__,error=str(exc),engine_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),checks=dict(CHECKS),market_reads=0,NPZ_reads=0,financial_replay=0))
        raise
