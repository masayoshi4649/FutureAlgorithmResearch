"""根の入力集合guardと新JIT-only初期化の変更部分だけを追補する。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import traceback

sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
SOURCE=BASE/'root_review/finance.py'
ENGINE=BASE/'engine'


def sha(path: Path) -> str:
    """
    機能: source又は所有小証跡の同bytes指紋を返す。
    引数: path(Path)は源又は私有の人工証跡。
    返り値: strはSHA256。実入力を対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pure_guard(raw: bytes) -> tuple[int,int]:
    """
    機能: guardだけをAST抽出し、追加された33唯一集合・登録同値を独立反例で確認する。
    引数: raw(bytes)は現在finance.pyの源。
    返り値: tuple[int,int]は合格toy数・拒否toy数。実登録やinputを読まない。
    """
    tree=ast.parse(raw.decode('utf-8'));nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard']
    assert len(nodes)==1
    source={'源.py':'source'};case={'合成':'case'};configs=[dict(id='合成')]
    registry=HERE/'読まない登録.json';state={};plan_hash={HERE/'試行計画.json':'plan',ROOT/'読まない目録.json':'manifest'}
    def read(path: Path) -> dict:
        """
        機能: 実ファイルを開かず合成登録だけを返す。
        引数: path(Path)はfixture内の識別先。
        返り値: dictは現在のtoy登録。
        """
        assert path==registry
        return deepcopy(state)
    target=dict(HERE=HERE,ROOT=ROOT,OUT=HERE/'未存在の金融',REGISTRY=registry,
        catalog=SimpleNamespace(TRIAL_ID='合成',configs=lambda:deepcopy(configs)),
        root_plan=SimpleNamespace(case_hashes=lambda c:deepcopy(case),sources=lambda:deepcopy(source),
                                  sha=lambda p:plan_hash[p],read=read))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE)+'::guard追補','exec'),target)
    sessions=[f'合成_{i:02d}' for i in range(33)]
    inputs={s:dict(TradeGate={'path':s+'_G','SHA256':s},TradeExit={'path':s+'_E','SHA256':s}) for s in sessions}
    proposal=dict(id='合成',正式freeze=True,spec=dict(entry=dict(conditions=deepcopy(configs)),implementation=deepcopy(source),
        data=dict(sessions=deepcopy(sessions),inputs=deepcopy(inputs),input_manifests=[dict(path='読まない目録.json',sha256='manifest')])))
    fixed=dict(全合格=True,正式freeze=True,configs=deepcopy(configs),case_SHA256=deepcopy(case),source_SHA256=deepcopy(source),
               計画SHA256='plan',sessions=deepcopy(sessions),inputs=deepcopy(inputs))
    cases=[]
    f,p=deepcopy(fixed),deepcopy(proposal);f['sessions'].reverse();cases.append(('登録場順序不一致',f,p))
    f,p=deepcopy(fixed),deepcopy(proposal);f['inputs'][sessions[0]]['TradeGate']['path']='他入力';cases.append(('登録input不一致',f,p))
    for number in (0,32,34):
        f,p=deepcopy(fixed),deepcopy(proposal);ids=[f'合成_{i:02d}' for i in range(number)]
        ins={s:{} for s in ids};f['sessions']=ids;f['inputs']=ins;p['spec']['data']['sessions']=deepcopy(ids);p['spec']['data']['inputs']=deepcopy(ins)
        cases.append((f'登録同値でも{number}場',f,p))
    f,p=deepcopy(fixed),deepcopy(proposal);f['sessions'][-1]=f['sessions'][0];p['spec']['data']['sessions']=deepcopy(f['sessions'])
    cases.append(('登録同値でも重複33場',f,p))
    f,p=deepcopy(fixed),deepcopy(proposal);f['inputs']['別場']=f['inputs'].pop(sessions[-1]);p['spec']['data']['inputs']=deepcopy(f['inputs'])
    cases.append(('場数33同値でも集合不一致',f,p))
    f,p=deepcopy(fixed),deepcopy(proposal);f['inputs'].pop(sessions[-1]);p['spec']['data']['inputs']=deepcopy(f['inputs'])
    cases.append(('登録同値でもinput32',f,p))
    state['trials']=[dict(id='合成',spec=deepcopy(proposal['spec']))];target['guard'](fixed,proposal)
    for label,f,p in cases:
        state['trials']=[dict(id='合成',spec=deepcopy(p['spec']))]
        try:target['guard'](f,p)
        except AssertionError:pass
        else:raise AssertionError(('追加guardの拒否漏れ',label))
    return 1,len(cases)


def source_import() -> dict:
    """
    機能: fresh processで現在financeをfile-spec importし、全moduleとJIT locatorの新領域を検算する。
    引数: なし。
    返り値: dictは源importだけのmodule/locator数と開いたproject file種別。run/mainは呼ばない。
    """
    opened=[]
    def audit(name: str,args: tuple) -> None:
        """
        機能: import中のproject内ファイルopenを記録し、実input本文を読まないと検証する。
        引数: name(str)、args(tuple)はPython監査event。
        返り値: None。価格/数量やファイル内容は記録しない。
        """
        if name=='open' and args and isinstance(args[0],(str,bytes)):
            path=Path(args[0]).resolve()
            if path.is_relative_to(ROOT):opened.append(path)
    sys.addaudithook(audit)
    spec=importlib.util.spec_from_file_location('独立_根finance初期化のみ',SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    from numba.core.registry import CPUDispatcher
    modules=(module.common,module.catalog,module.interface,module.interface.core,module.interface.signals,module.interface.daily,
             module.interface.input_contract,module.interface.price_features,module.interface.flows,module.interface.bars)
    compiled_count=0;paths=[]
    for item in modules:
        assert Path(item.__file__).resolve().parent==ENGINE
        for value in vars(item).values():
            if isinstance(value,CPUDispatcher):
                path=Path(value._cache._impl._locator._cache_path).resolve()
                assert path.is_relative_to(ENGINE/'jit');paths.append(path.relative_to(ROOT).as_posix());compiled_count+=1
    assert compiled_count>0
    for path in opened:
        assert path.suffix in ('.py','.pyc') or path.is_relative_to(ENGINE/'jit'), ('source/import以外を開いた',path)
    assert not module.OUT.exists()
    return dict(module数=len(modules),JITlocator数=compiled_count,JIT保存先=sorted(set(paths)),
                開いたprojectファイル数=len(opened),読取区分='源/pyc又はengine私有JITの初期化だけ。run/load_cache/main呼出0。')


def main() -> None:
    """
    機能: 今回の追加assert/importだけを現源へ束縛し、451旧証跡を保持した追補を保存する。
    引数: なし。
    返り値: None。新2場/旧cache/金融/APIを読まず自所有証跡だけ作る。
    """
    raw=SOURCE.read_bytes();before=hashlib.sha256(raw).hexdigest();path=HERE/'根33唯一入力guardと新JITのみ初期化の独立追補.json'
    assert not path.exists()
    try:
        tree=ast.parse(raw.decode('utf-8'));imports=[n.names[0].name for n in tree.body if isinstance(n,ast.Import)]
        assert imports.index('common')<imports.index('interface')
        passed,rejected=pure_guard(raw);runtime=source_import();assert sha(SOURCE)==before
        proof=dict(全合格=True,source=dict(path=SOURCE.relative_to(ROOT).as_posix(),SHA256=before),監査source_SHA256=sha(Path(__file__)),
            追加入力guard正例=passed,追加入力guard拒否=rejected,初期化=runtime,
            旧451証跡=dict(path='audit_accounting/根snapshotとguard及び未知保持の独立保存純人工.json',保持=True),
            範囲='追加4assertとcommon-before-interface初期化だけ。旧保存/会計/経済係数へ新有効性証拠を追加しない。',
            原入力=0,実金融=0,原板=0,NPZ=0,API=0)
        path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,proof_SHA256=sha(path),source_SHA256=before,追加入力guard拒否=rejected,初期化=runtime),ensure_ascii=False))
    except BaseException:
        out=HERE/'追加guard初期化_初回False.json';assert not out.exists()
        out.write_text(json.dumps(dict(全合格=False,source_SHA256=before,原因=traceback.format_exc(),実入力=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8');raise


if __name__=='__main__':main()
