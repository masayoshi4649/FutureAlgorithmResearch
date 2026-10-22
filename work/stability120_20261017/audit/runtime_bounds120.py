"""実市場を使わず、通常JITのUID消失と境界検査付き源の会計を切り分ける。"""

from collections import Counter
import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
OLD = OWNER / 'engine120.py'
NEW = OWNER / 'recovery_b' / 'engine120b.py'
OLD_SHA = 'aaa2f4ed234f49c4f00b6dcfff7d66db6dd23c684ed0d6dbee15aebea27e4c16'
OUT = HERE / '通常JIT反例と境界検査修正の独立人工_環境既定'
CHECKS = Counter()


def check(value: bool, label: str) -> None:
    """
    機能: 人工だけの独立期待を判定して失敗を停止させる。
    引数: value(bool)、label(str)は条件と意味。
    返り値: None。
    """
    assert bool(value), label
    CHECKS[label] += 1


def sha(value: bytes) -> str:
    """
    機能: 同bytes保全とsource不変を識別する。
    引数: value(bytes)は人工又は実装source。
    返り値: strはSHA256。
    """
    return hashlib.sha256(value).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 人工の反例と成功証跡を所有領域へ新規保存する。
    引数: path(Path)、value(dict)は保存先と有限JSON。
    返り値: None。既存を上書きしない。
    """
    assert path.is_relative_to(OUT) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')


def load(name: str, path: Path):
    """
    機能: 閉鎖済み実装だけを新しいmodule名で読み込む。
    引数: name(str)、path(Path)は固有名とsource。
    返り値: module。実市場・NPZ・結果・登録台帳を読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def arguments(path: np.ndarray, cap: int, mode: int, fee: float=11., multiplier: float=10.) -> tuple:
    """
    機能: 原row厳密増加の場内人工経路を作る。
    引数: path(np.ndarray)、cap/mode(int)、fee/multiplier(float)。
    返り値: tupleはreplay用の全引数。終端に実返済用の観測を残す。
    """
    count=len(path)
    return (np.arange(count,dtype=np.int64), np.arange(count,dtype=float), path,
            path-10.,path+10.,cap,multiplier,fee,10.,.000125,mode,1.,0.,
            float(count-10),float(count-5),float(count+1))


def exact(actual: tuple, expected: tuple, label: str) -> None:
    """
    機能: JITとPythonの全注文・玉・曲線・集計を列ごと完全比較する。
    引数: actual/expected(tuple)、label(str)は同じ人工入力の出力。
    返り値: None。整数円素材なので許容丸めを設けない。
    """
    check(len(actual)==len(expected)==4,label+'の出力四組')
    for name, a, b in zip(('注文','玉','曲線','集計'),actual,expected):
        check(a.shape==b.shape and np.array_equal(a,b,equal_nan=True),label+'の'+name+'完全同値')


def conservation(result: tuple, fee: float) -> None:
    """
    機能: 実注文UIDだけから消失・重複・未返済隠蔽と現金を検査する。
    引数: result(tuple)、fee(float)は人工出力と片道料金。
    返り値: None。返済済みと未返済を混同しない。
    """
    orders,lots,curve,summary=result
    entries=orders[orders[:,1]==1.];exits=orders[orders[:,1]==2.]
    en=set(entries[:,0].astype(int));ex=set(exits[:,0].astype(int));held=en-ex
    check(len(en)==len(entries),'実新規UID一意')
    check(len(ex)==len(exits) and ex<=en,'返済UIDは実新規へ一意対応')
    check(len(held)==int(summary[8]),'全実新規は返済又は残在庫へ保存')
    check(len(lots)==len(exits)==int(summary[5]),'返済注文と決済玉の同数')
    check(len(entries)==len(lots)+len(held)==int(summary[13]),'新規数は決済玉と未返済の和')
    check(summary[1]==summary[2]-summary[3]-len(held)*math.floor(fee+1e-9),'現金と確定損益と残入口料の恒等式')
    check(summary[2]==sum(max(0.,v) for v in lots[:,13]) and summary[3]==sum(max(0.,-v) for v in lots[:,13]),'決済玉正負と総利益総損失')
    check(np.all(orders[:,4]>orders[:,3]),'判断と同原rowでは約定しない')


def main() -> None:
    """
    機能: 同bytes新moduleの反例を保存し、境界検査の局所修正を全八管理で確認する。
    引数: なし。
    返り値: None。新市場・金融標本を追加せず、旧人工の不足も明示する。
    """
    original=OLD.read_bytes();new=NEW.read_bytes()
    check(sha(original)==OLD_SHA,'原源SHA不変')
    check(new.replace(b'\r\n',b'\n')==original.replace(b'\r\n',b'\n').replace(b'@njit(cache=True)',b'@njit(cache=False, boundscheck=True)'), '改行を除く修正はdecorator二箇所だけ')
    oldtree=ast.parse(original.decode('utf8'));newtree=ast.parse(new.decode('utf8'))
    for tree in (oldtree,newtree):
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):node.decorator_list=[]
    check(ast.dump(oldtree)==ast.dump(newtree),'経済関数本体と定数AST不変')
    check(not OUT.exists(),'人工保存先は未使用')
    OUT.mkdir(parents=True)
    oldcopy=OUT/'engine_same_bytes.py';oldcopy.write_bytes(original)
    newcopy=OUT/'engine_bounds_bytes.py';newcopy.write_bytes(new)
    os.environ['NUMBA_CACHE_DIR']=str(OUT/'fresh_normal_cache')
    os.environ.pop('NUMBA_BOUNDSCHECK',None)
    same=load('audit120_same_bytes',oldcopy)
    fixed=load('audit120_fixed_bounds',newcopy)
    generator=np.random.default_rng(20261017)
    path=(65000+np.cumsum(generator.integers(-4,5,50))*10).astype(float)
    fixture=arguments(path,20,2)
    save(OUT/'市場と無関係な五十行反例.json',dict(seed=20261017,mid=path.tolist(),rows=fixture[0].tolist(),time=fixture[1].tolist(),cap=20,multiplier=10,fee=11,spread_half=10,observed_tick=10,fraction=.000125,mode=2,trail=1,session_start=0,entry_end=40,close_time=45,session_end=51,market_reads=0))
    wrong=same.replay(*fixture);reference=same.replay.py_func(*fixture)
    check(not np.array_equal(wrong[3],reference[3],equal_nan=True),'空cache同bytes新moduleでも通常JIT反例')
    check(wrong[3][8]==0 and wrong[3][13]!=wrong[3][5],'通常JITは実在UIDを未返済にも残さない')
    check(wrong[3][1]-(wrong[3][2]-wrong[3][3])==-253.,'整数円でも通常JITに二十三入口料の差')
    save(OUT/'旧通常JIT不整合の人工False.json',dict(passed=False,engine_sha256=OLD_SHA,reason='同SHA同bytes新module・空cacheの通常JITで実新規UIDが消失。Pythonでは再現しない。',JIT_summary=wrong[3].tolist(),Python_summary=reference[3].tolist(),missing_UIDs=sorted(set(wrong[0][wrong[0][:,1]==1.,0].astype(int).tolist())-set(wrong[0][wrong[0][:,1]==2.,0].astype(int).tolist())),JIT_orders=wrong[0].tolist(),Python_orders=reference[0].tolist(),market_reads=0,financial_replay=0))
    fixed_answer=fixed.replay(*fixture);exact(fixed_answer,reference,'五十行の局所修正')
    cases=[]
    rng=np.random.default_rng(12017)
    paths=[('多段急反転', (65000+np.cumsum(rng.integers(-7,8,700))*10).astype(float)),
           ('同時計を含む反復',np.tile(np.r_[np.arange(65000.,65410.,10.),np.arange(65400.,64590.,-10.),np.arange(64600.,65010.,10.)],3))]
    for name,mid in paths:
        for cap in (1,2,5,10,20):
            for mode in range(8):
                args=list(arguments(mid,cap,mode))
                if name=='同時計を含む反復':args[1]=np.floor(args[1]/2.)
                # 同時計素材も場内返済用の後続気配を必ず残す。
                args[13]=float(args[1][-1]-10);args[14]=float(args[1][-1]-5)
                args[15]=float(args[1][-1]+1)
                args=tuple(args)
                jit=fixed.replay(*args);plain=fixed.replay.py_func(*args)
                exact(jit,plain,name);conservation(jit,11.)
                cases.append(dict(path=name,cap=cap,mode=mode,entries=int(jit[3][13]),closed=int(jit[3][5]),unclosed=int(jit[3][8])))
    # ----------------------------------------
    # TOPIX料金も一枚ごとの切捨てで、通常JIT修正後に全八管理を比較する。
    for mode in range(8):
        args=arguments(path,10,mode,41.8,1000.)
        jit=fixed.replay(*args);plain=fixed.replay.py_func(*args)
        exact(jit,plain,'TOPIX料金');conservation(jit,41.8)
    check(OLD.read_bytes()==original and NEW.read_bytes()==new,'監査終端両源不変')
    proof=dict(passed=True,engine_sha256=sha(new),original_engine_sha256=OLD_SHA,audit_source_sha256=sha(Path(__file__).read_bytes()),checks=dict(CHECKS),total_checks=sum(CHECKS.values()),cases=cases,market_reads=0,NPZ_reads=0,result_reads=0,financial_replay=0,registry_changes=0,source_changes=0,留保='旧cap2等の人工監査は本反例を含まず安全性検査が不足していた。通常JITの低水準原因は未確定でありLLVM等に断定帰属しない。境界検査付き同論理源を対象に人工会計が成立したことだけを示し、有効性標本には数えない。')
    save(OUT/'境界検査付き源の全八管理とUID保存の独立人工.json',proof)
    print(json.dumps(dict(passed=True,engine_sha256=sha(new),checks=sum(CHECKS.values()),proof=str(OUT/'境界検査付き源の全八管理とUID保存の独立人工.json')),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
