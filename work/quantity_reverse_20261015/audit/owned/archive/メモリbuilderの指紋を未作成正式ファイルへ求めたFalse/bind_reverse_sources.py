"""反転の経済一行差分と九源・八部品・登録前ガードを束縛する。"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
ROOT=BASE.parents[1]
OLD=ROOT/'work/quantity_execution_20261015'
CHECKS=0


def check(value: bool, detail: object) -> None:
    """
    機能: sourceと固定の判定を数える。
    引数: value(bool)、detail(object)。
    返り値: None。
    """
    global CHECKS
    CHECKS+=1
    assert value,detail


def sha(path: Path) -> str:
    """
    機能: 小source・固定目録・純証跡を指紋化する。
    引数: path(Path)。
    返り値: str SHA256。金融結果とNPZは開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str,path: Path):
    """
    機能: 自動実行部のない定義を読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def normalized_plan(path: Path) -> ast.Module:
    """
    機能: 許容された調査説明と主候補IDだけを正規化して比較する。
    引数: path(Path) 計画source。
    返り値: ast.Module 仕様係数と実行関数は変更しないAST。
    """
    tree=ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PUBLIC' for t in node.targets):node.value=ast.Constant(value='公開導線')
        if isinstance(node,ast.FunctionDef) and node.name=='freeze':
            for assignment in node.body:
                if not(isinstance(assignment,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='proposal' for t in assignment.targets)):continue
                call=assignment.value
                for keyword in call.keywords:
                    if keyword.arg in ('name','question','change','repeat_reason','compares_to','表示主候補'):keyword.value=ast.Constant(value='調査説明')
                    if keyword.arg=='spec':
                        entry=next(k.value for k in keyword.value.keywords if k.arg=='entry')
                        for part in entry.keywords:
                            if part.arg=='入口':part.value=ast.Constant(value='元方向を維持する反転説明')
    return tree


def main() -> None:
    """
    機能: 完成九源を独立純期待・旧固定・登録ガードへ接続する。
    引数: なし。
    返り値: None。正式freeze・登録・金融は起動しない。
    """
    plan=load('反転九源の計画定義',BASE/'plan.py')
    catalog=load('反転九源の条件',BASE/'catalog.py')
    old_catalog=load('旧条件の純参照',OLD/'catalog.py')
    source=plan.sources()
    previous_path=OLD/'audit/root/正式登録の現物と九源及び時間小固定の独立接続.json'
    previous=json.loads(previous_path.read_text(encoding='utf-8'))
    check(previous['全合格'] and sha(previous_path)=='4bb13430938fb7531a9b82fc8fc6574935207d2935e68c1cd8bc0e6d1c5e15c5','旧115の元登録源証跡')
    check(len(source)==9,'最終九源')
    for name in plan.SOURCE_NAMES:
        old_key=(OLD/name).relative_to(ROOT).as_posix()
        check(sha(OLD/name)==previous['source_SHA256'][old_key],('旧115九源を一切変更しない',name))
    for name in ('input_contract.py','artificial_root.py','metrics/metrics.py','metrics/artificial_metrics.py'):
        check(sha(BASE/name)==sha(OLD/name),('同bytes継承',name))
    old_engine=(OLD/'engine.py').read_text(encoding='utf-8')
    expected=old_engine.replace("chosen.append((row,index,d,typ,event[j['episode']]))","chosen.append((row,index,d*config['direction_multiplier'],typ,event[j['episode']]))")
    check(expected!=old_engine and ast.dump(ast.parse(expected),include_attributes=False)==ast.dump(ast.parse((BASE/'engine.py').read_text(encoding='utf-8')),include_attributes=False),'経済差は元審査後side乗数一行だけ')
    old_finance=(OLD/'finance.py').read_text(encoding='utf-8')
    expected=old_finance.replace("主候補='QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1'","主候補='QREVERSE_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1'")
    check(ast.dump(ast.parse(expected),include_attributes=False)==ast.dump(ast.parse((BASE/'finance.py').read_text(encoding='utf-8')),include_attributes=False),'金融guard/mainは主候補の表示ID以外同AST')
    check(ast.dump(normalized_plan(BASE/'plan.py'),include_attributes=False)==ast.dump(normalized_plan(OLD/'plan.py'),include_attributes=False),'planは公開先・説明・旧比較元・反転入口説明と主候補ID以外同AST')
    for old,new in zip(old_catalog.configs(),catalog.configs()):
        candidate=dict(new);factor=candidate.pop('direction_multiplier');candidate['id']=candidate['id'].replace('QREVERSE_','QEXEC_',1)
        check(factor==-1 and candidate==old,('反転以外全係数を維持',old['id']))
    check(len(catalog.configs())==12,'十二条件')
    check(sha(BASE/'入力と保存公開の固定.json')==sha(OLD/'入力と保存公開の固定.json'),'固定66原/66eventの同bytes再利用')
    subset_path=HERE/'同入口審査後のside反転と新出口再判定の独立SOURCE_ONLY接続.json'
    subset=json.loads(subset_path.read_text(encoding='utf-8'))
    check(subset['全合格'] and subset['確認数']==1910,'独立48口座と時刻再判定反例')
    for name,digest in subset['source_SHA256'].items():check(sha(BASE/name)==digest,('独立subsetと現源',name))
    owner_path=BASE/'数量公開からmarket全量と半分追尾へ接続する人工検査.json'
    owner=json.loads(owner_path.read_text(encoding='utf-8'))
    check(owner['全合格'] and sha(owner_path)=='fdc1f9c6014971acd8dfb7a70ea226bf366c01fac0409ec92393f5eb1379e4f6','所有者完成人工を引用')
    for name,digest in owner['source_SHA256'].items():check(sha(BASE/name)==digest,('所有者三源の現在同一性',name))
    root_path=BASE/'rootの可逆保存と時刻型の人工.json'
    root=json.loads(root_path.read_text(encoding='utf-8'))
    check(root['全合格'] and root['新金融']==0,'root20純人工')
    for name,digest in root['source_SHA256'].items():check(source[name]==digest,('root四源同一性',name))
    # ----------------------------------------
    # 現在のbuilderを、既存小固定と合成監査だけでメモリへ接続する。
    fixed=json.loads((BASE/'入力と保存公開の固定.json').read_text(encoding='utf-8'))
    original=copy.deepcopy(fixed)
    generated={}
    audit=dict(全合格=True,新金融=0,source_SHA256=source,evidence=[])
    def reader(path: Path) -> dict:
        """
        機能: 小固定又は合成監査をbuilderへ渡す。
        引数: path(Path)。
        返り値: dict。NPZ/結果本文は開かない。
        """
        return fixed if path.name=='入力と保存公開の固定.json' else audit
    def writer(path: Path,value: dict) -> None:
        """
        機能: builder出力をJSON roundtripしたメモリへ捕捉する。
        引数: path(Path)、value(dict)。
        返り値: None。正式固定を書かない。
        """
        generated[path.name]=json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))
    freeze=next(x for x in ast.parse((BASE/'plan.py').read_text(encoding='utf-8')).body if isinstance(x,ast.FunctionDef) and x.name=='freeze')
    sys.modules['catalog']=catalog
    namespace=dict(HERE=BASE,ROOT=ROOT,read=reader,write=writer,digest=sha,sources=lambda:source,registration_inputs=plan.registration_inputs,json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[freeze],type_ignores=[])),str(BASE/'plan.py'),'exec'),namespace)
    namespace['freeze']()
    proposal=generated['試行計画.json']
    check(proposal['id']==catalog.TRIAL_ID and proposal['compares_to']==[old_catalog.TRIAL_ID],'新IDと旧115比較元')
    check(proposal['spec']['implementation']==source and proposal['spec']['entry']['conditions']==catalog.configs(),'登録予定九源と十二経済条件')
    check(proposal['spec']['data']['inputs']==plan.registration_inputs(fixed),'空窓は登録viewだけ変換')
    check(fixed==original,'実行小固定を変更しない')
    check(len(fixed['sessions'])==len(set(fixed['sessions']))==33 and len(fixed['inputs'])==66,'既知33場/66入力')
    check(generated['金融前の正式固定.json']['実行予定']==dict(原NPZ=66,保存eventNPZ=66,新金融口座=792,原板=0,API=0),'単回792予定')
    duplicate=load('反転の既存checker純呼出',ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py')
    check(duplicate.analyze(proposal,[])['proposal_complete'] is True,'既存checkerへJSON保存後の八部品を渡し完備')
    check(source==plan.sources(),'最終九源不変更')
    evidence=[dict(path=p.relative_to(ROOT).as_posix(),SHA256=sha(p)) for p in (subset_path,previous_path,owner_path,root_path)]
    proof=dict(全合格=True,source_SHA256=source,源接続確認数=CHECKS,独立純人工確認数=1910,独立具体口座=48,新金融=0,
        原入力=0,原NPZ=0,保存eventNPZ=0,旧金融結果=0,実台帳=0,API=0,evidence=evidence,
        変更='元proxy方向でA/B/Cを審査してから、実candidate sideだけ−d。全kernel、出口、時刻、数量、費用、場停止、入力契約とmetricsを維持。',
        経済的区別='新方向でask/bid・SL/TP/trail/half・busy・場停止・後続を再運転。旧netの符号反転ではない。旧時刻を固定した逆売買は別の会計恒等式。',
        旧115結果の扱い='原本文未読。rootの全33/33各赤字という既確認事実を新計画の背景として受領しただけで、ここで再確認はしていない。',
        源監査の留保='現在のbuilderと旧ガード同ASTを確認。正式freeze/check/registerは本監査で実施0、rootの実登録終端後の現物接続は別。',
        未測定='原実NPZ/保存event/金融結果・実mini/microの板列約定と遅延・追加二場',独立源_SHA256=sha(Path(__file__)))
    output=HERE/'完成九sourceと元方向審査後反転及び登録ガードの独立接続.json'
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=CHECKS,path=str(output),SHA256=sha(output)),ensure_ascii=False))


if __name__=='__main__':main()
