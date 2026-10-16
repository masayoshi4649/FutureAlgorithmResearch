"""空の静観窓を登録表現だけへ分離した二源差分を監査する。"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]
OLD = BASE / 'archive/正式照合が静観窓の空配列を拒否した版'
CHECKS = 0


def check(value: bool, detail: object) -> None:
    """
    機能: 差分の判定を数える。
    引数: value(bool)、detail(object)。
    返り値: None。
    """
    global CHECKS
    CHECKS += 1
    assert value, detail


def sha(path: Path) -> str:
    """
    機能: 小source又は登録metadataの指紋を求める。
    引数: path(Path)。
    返り値: str SHA256。NPZを読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str, path: Path):
    """
    機能: 自動処理部を起動せず純sourceを読み込む。
    引数: name(str)、path(Path)。
    返り値: module 定義。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def function(path: Path, name: str) -> ast.FunctionDef:
    """
    機能: 関数の定義だけを抽出する。
    引数: path(Path)、name(str)。
    返り値: ast.FunctionDef。
    """
    return next(x for x in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(x,ast.FunctionDef) and x.name==name)


def equal_ast(left: str, right: str) -> bool:
    """
    機能: 行番号・空白を除くsourceの同一性を検査する。
    引数: left/right(str) Python source。
    返り値: bool ASTの完全一致。
    """
    return ast.dump(ast.parse(left),include_attributes=False)==ast.dump(ast.parse(right),include_attributes=False)


def main() -> None:
    """
    機能: 登録用viewのみの訂正を現九源へ束縛する。
    引数: なし。
    返り値: None。正式登録・金融・NPZ読取は行わない。
    """
    plan=load('登録viewの現在計画',BASE/'plan.py')
    catalog=load('登録viewの現在条件',BASE/'catalog.py')
    previous_path=HERE/'完成九sourceと入力境界及び金融前ガードの独立接続.json'
    previous=json.loads(previous_path.read_text(encoding='utf-8'))
    check(previous['全合格'] and sha(previous_path)=='b2999415edaea87a69f427fbdb08325fbc4e2ac6a254474e0801f6429b60b20e','旧成功を保全')
    source=plan.sources()
    keys={(BASE/name).relative_to(ROOT).as_posix() for name in ('plan.py','finance.py')}
    check(len(source)==9 and set(source)==set(previous['source_SHA256']),'九源集合不変')
    for key in source:
        if key not in keys:
            check(source[key]==previous['source_SHA256'][key],('経済等七源同bytes',key))
    for name in ('plan.py','finance.py'):
        check(sha(OLD/name)==previous['source_SHA256'][(BASE/name).relative_to(ROOT).as_posix()],('旧二源は当時源',name))
    old_plan=(OLD/'plan.py').read_text(encoding='utf-8')
    current_tree=ast.parse((BASE/'plan.py').read_text(encoding='utf-8'))
    removed=ast.Module(body=[x for x in current_tree.body if not(isinstance(x,ast.FunctionDef) and x.name=='registration_inputs')],type_ignores=[])
    expected=old_plan.replace("inputs=fixed['inputs'],","inputs=registration_inputs(fixed),")
    check(expected!=old_plan and old_plan.count("inputs=fixed['inputs'],")==1,'freeze登録inputs一箇所のみ置換')
    check(equal_ast(expected,ast.unparse(removed)),'planはview関数追加と登録data.inputs変更だけ')
    old_finance=(OLD/'finance.py').read_text(encoding='utf-8')
    expected=old_finance.replace("assert proposal['spec']['data']['inputs'] == fixed['inputs']","assert proposal['spec']['data']['inputs'] == plan.registration_inputs(fixed)")
    check(expected!=old_finance and equal_ast(expected,(BASE/'finance.py').read_text(encoding='utf-8')),'financeはguard比較先一箇所だけ')
    check(sha(BASE/'入力と保存公開の固定.json')==previous['入力目録']['SHA256'],'実行小固定不変更')
    synthetic=dict(inputs=[dict(raw=dict(path='合成日中'),time_policy=dict(quiet_windows=[],entry_start_s=1.,entry_end_s=2.)),
                           dict(raw=dict(path='合成夜間'),time_policy=dict(quiet_windows=[[100.,200.]],entry_start_s=3.,entry_end_s=4.))])
    before=copy.deepcopy(synthetic)
    view=plan.registration_inputs(synthetic)
    check(synthetic==before,'実行用空配列を変更しない')
    check(view[0]['time_policy']['quiet_windows']=='対象窓なし（実行小固定は空配列）','登録だけ明示語')
    check(view[1]==before['inputs'][1],'非空の実時刻窓を変えない')
    check(json.loads(json.dumps(view,ensure_ascii=False))==view,'登録表現のJSON roundtrip')
    view[1]['time_policy']['quiet_windows'][0][0]=-1
    check(synthetic==before,'登録コピーと実行元の深い分離')
    # ----------------------------------------
    # 旧正式proposalとcheck出力は小metadataとして一読し、実入力本文は開かない。
    old_proposal=json.loads((OLD/'試行計画.json').read_text(encoding='utf-8'))
    failed=json.loads((OLD/'正式照合の全出力.json').read_text(encoding='utf-8'))
    checked=json.loads(failed['stdout'])
    check(failed['終了コード']==0 and checked['proposal_complete'] is False,'終了0でも不完備だった正式checkを保持')
    fixed=dict(sessions=old_proposal['spec']['data']['sessions'],inputs=copy.deepcopy(old_proposal['spec']['data']['inputs']))
    baseline=copy.deepcopy(fixed)
    generated={}
    digest=lambda p:'1'*64
    audit=dict(全合格=True,新金融=0,source_SHA256=source,evidence=[])
    def reader(path: Path) -> dict:
        """
        機能: 正式builderへ旧登録metadataと合成監査だけを渡す。
        引数: path(Path)。
        返り値: dict。実行小固定の本文を再読しない。
        """
        return fixed if path.name=='入力と保存公開の固定.json' else audit
    def writer(path: Path,value: dict) -> None:
        """
        機能: freezeの出力をメモリへ捕捉する。
        引数: path(Path)、value(dict)。
        返り値: None。正式ファイルを書かない。
        """
        generated[path.name]=copy.deepcopy(value)
    import sys
    sys.modules['catalog']=catalog
    ns=dict(HERE=BASE,ROOT=ROOT,read=reader,write=writer,sources=lambda:source,digest=digest,json=json,registration_inputs=plan.registration_inputs)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function(BASE/'plan.py','freeze')],type_ignores=[])),str(BASE/'plan.py'),'exec'),ns)
    ns['freeze']()
    proposal=generated['試行計画.json']
    wanted=copy.deepcopy(old_proposal)
    wanted['spec']['data']['inputs']=plan.registration_inputs(fixed)
    wanted['spec']['data']['input_manifests'][0]['sha256']='1'*64
    wanted['spec']['implementation']=source
    check(proposal==wanted,'builder全項目は登録窓表示/源指紋以外同一')
    check(fixed==baseline,'66の実行窓を非破壊保持')
    duplicate=load('既存checkerの純照合',ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py')
    raw_result=duplicate.analyze(old_proposal,[])
    corrected_result=duplicate.analyze(proposal,[])
    check(raw_result['proposal_complete'] is False and corrected_result['proposal_complete'] is True,'既存checkerで表現だけの不完備を解消')
    # ----------------------------------------
    # 新guardは実行入力の文字列化を使わず、登録viewとだけ一致させる。
    frozen=generated['金融前の正式固定.json']
    frozen.update(input_SHA256='1'*64,proposal_SHA256='1'*64,audit_SHA256='1'*64)
    table={'金融前の正式固定.json':frozen,'試行計画.json':proposal,'金融初読前の人工と独立監査.json':audit,
           '入力と保存公開の固定.json':dict(fixed,全合格=True),'正式照合の全出力.json':dict(終了コード=0,stdout=json.dumps({'proposal_complete':True})),
           '正式登録の全出力.json':dict(終了コード=0),'trials.json':dict(trials=[dict(id=catalog.TRIAL_ID,spec=copy.deepcopy(proposal['spec']))])}
    stub=SimpleNamespace(HERE=BASE,ROOT=ROOT,read=lambda p:table[p.name],sources=lambda:source,digest=digest,registration_inputs=plan.registration_inputs)
    gs=dict(OUT=SimpleNamespace(exists=lambda:False),plan=stub,catalog=catalog,json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function(BASE/'finance.py','guard')],type_ignores=[])),str(BASE/'finance.py'),'exec'),gs)
    gs['guard']()
    check(fixed==baseline,'登録比較後も実行窓は空配列')
    proposal['spec']['data']['inputs']=copy.deepcopy(fixed['inputs'])
    table['trials.json']['trials'][0]['spec']=copy.deepcopy(proposal['spec'])
    refused=False
    try:gs['guard']()
    except AssertionError:refused=True
    check(refused,'旧空窓表現のregistry specを新guardが拒否')
    check(source==plan.sources(),'検査中の九源不変更')
    output=HERE/'空静観窓の登録表現だけの修正と九source再接続_v2.json'
    proof=dict(全合格=True,source_SHA256=source,確認数=CHECKS,新金融=0,入力本文=0,原NPZ=0,保存eventNPZ=0,過去金融=0,API=0,
        evidence=[dict(path=previous_path.relative_to(ROOT).as_posix(),SHA256=sha(previous_path))],
        元検査='旧b299成功の入力/因果/会計/保存検査をsource差分拘束で継承。経済の再試験・新有効性標本ではない。',
        変更='plan.registration_inputsの深いコピーで登録時だけ空quietを明示語へ。finance.guard比較も同viewへ。実main・実時間窓・入力小固定・残七源・十二条件は不変。',
        旧不成立=dict(path=(OLD/'正式照合の全出力.json').relative_to(ROOT).as_posix(),SHA256=sha(OLD/'正式照合の全出力.json'),終了コード=0,proposal_complete=False,実登録未実行=True),
        現照合='既存duplicate_check.analyzeへメモリbuilderを渡す純検査でproposal_complete=True。rootの正式check/実登録成功はまだ別。',
        読取範囲='旧正式proposal/checkと旧sourceの小metadataのみ。原入力/event NPZ・旧114結果・新金融は0。',
        独立源_SHA256=sha(Path(__file__)))
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=CHECKS,path=str(output),SHA256=sha(output)),ensure_ascii=False))


if __name__=='__main__':main()
