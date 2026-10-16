"""登録前の半量診断だけを修正し、元396入力確認を保持して再束縛する。"""

import ast
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

import common

ARCHIVE=common.HERE/'登録前_半量診断修正前'


def function_source(path: Path, name: str) -> str:
    """
    機能: 指定関数のsourceをAST位置で取り出す。
    引数: path(Path)、name(str)はPython sourceと関数名。
    返り値: strは関数全文。実入力照合の関数が変わっていないことだけを確認する。
    """
    source=path.read_text(encoding='utf8');tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.get_source_segment(source,node)


def write_replacement(path: Path, value: dict) -> None:
    """
    機能: 元SHAがarchiveに保存済みの正式資料だけを訂正する。
    引数: path(Path)、value(dict)は所有領域の元資料と新内容。
    返り値: None。未保存の旧資料や金融結果は上書きしない。
    """
    old=ARCHIVE/path.name
    assert old.exists() and path.exists() and common.digest(path)==common.digest(old)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')


def main() -> None:
    """
    機能: 元396入力証跡と unchanged入力関数を照合し、新診断32人工へ正式spec/固定を結ぶ。
    引数: なし。小資料とsourceだけを読む。
    返り値: None。33cache再読/金融/登録/APIを行わない。
    """
    target=common.HERE/'半量診断の単位修正と旧入力照合の補完.json';assert not target.exists()
    old_shas=common.read(ARCHIVE/'元SHA保持.json')['元SHA256']
    for name,sha in old_shas.items():assert common.digest(ARCHIVE/name)==sha,name
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    old_plan=common.read(ARCHIVE/'試行計画.json');assert not any(t['id']==old_plan['id'] for t in registry)
    art_path=common.HERE/'実行部と半量C派生の結合人工検査.json';art=common.read(art_path)
    assert art['全合格'] and art['検査件数']==32 and art['新金融再生']==0
    for name,sha in art['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    old_derivation=ARCHIVE/'derivation.py';new_derivation=common.HERE/'derivation.py'
    unchanged={}
    for name in ('c_normal','verify_alias','expand','scale_columns','baseline_metadata'):
        before=function_source(old_derivation,name);after=function_source(new_derivation,name);assert before==after,name
        unchanged[name]=hashlib.sha256(before.encode('utf8')).hexdigest()
    old_proof_path=ARCHIVE/'ALIGNED全6の無RとC同入口の非金融確認.json'
    proof=common.read(old_proof_path);assert proof['全合格'] and proof['alias照合口座数']==396
    for name,sha in proof['source_SHA256'].items():
        if name.endswith('/derivation.py'):continue
        assert common.digest(common.ROOT/name)==sha,name
    for name,sha in proof['SHA256'].items():
        if name==art_path.relative_to(common.ROOT).as_posix():continue
        assert common.digest(common.ROOT/name)==sha,name
    supplement=dict(全合格=True,登録前=True,新金融再生=0,今回入力cache読取=0,旧金融台帳読取=0,原板読取=0,API取得=0,
        修正='code2 detailのraw_r価格を据置、code1/10 initial_risk円のみ半量。control_statsの予算/停止時価/超過円を半量、行/時計/flagを据置。',
        金融算式変更=0,core変更=0,入力関数同source=unchanged,
        元396入力照合=dict(path=old_proof_path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(old_proof_path),
            口座数=396,scope='既知33場ALIGNED6×両商品。新規再照合数0、元照合を変更のない入力関数へ委譲。'),
        修正後人工=dict(path=art_path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(art_path),検査件数=32),
        source_SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in
            (Path(__file__),new_derivation,common.HERE/'runner.py',common.HERE/'runner_artificial.py')})
    common.write(target,supplement)
    proof['source_SHA256'][new_derivation.relative_to(common.ROOT).as_posix()]=common.digest(new_derivation)
    proof['SHA256'][art_path.relative_to(common.ROOT).as_posix()]=common.digest(art_path)
    proof['SHA256'][target.relative_to(common.ROOT).as_posix()]=common.digest(target)
    proof['元入力照合証跡']=supplement['元396入力照合']
    proof['診断修正補完']=dict(path=target.relative_to(common.ROOT).as_posix(),SHA256=common.digest(target))
    proof['元入力cache読取']=proof['新入力cache読取'];proof['新入力cache読取']=0
    proof['限界']+=' 本版は元396照合の委譲。今回の実入力再検査は0であり、同じ照合を新しい有効性証拠にしない。'
    proof_path=common.HERE/old_proof_path.name;write_replacement(proof_path,proof)
    fixed=common.read(ARCHIVE/'事前固定.json');plan=old_plan
    for name,sha in fixed['source_SHA256'].items():
        if name.endswith('/derivation.py') or name.endswith('/runner_artificial.py'):continue
        assert common.digest(common.ROOT/name)==sha,name
    for path in (new_derivation,common.HERE/'runner_artificial.py',Path(__file__)):
        fixed['source_SHA256'][path.relative_to(common.ROOT).as_posix()]=common.digest(path)
    changed={art_path.relative_to(common.ROOT).as_posix(),proof_path.relative_to(common.ROOT).as_posix()}
    for container in (fixed['proofs'],plan['evidence'],plan['spec']['data']['input_manifests']):
        for item in container:
            if item['path'] in changed:item['sha256']=common.digest(common.ROOT/item['path'])
    for container in (fixed['proofs'],plan['evidence']):
        container.append(dict(path=target.relative_to(common.ROOT).as_posix(),sha256=common.digest(target)))
    plan['repeat_reason']+=' 登録前の独立レビューで半量診断の価格/円単位2点を訂正。売買/費用/時価/18数値は変更せず、元396入力証跡を保持し診断32人工で補完した。'
    plan['spec']['implementation']=fixed['source_SHA256']
    plan['spec']['execution']['diagnostic_units']='half_outputのcontrol2 raw_rは価格幅として据置。control1/10とcontrol_statsの円欄だけ半量。旧/修正sourceと証跡を保存。'
    write_replacement(common.HERE/'試行計画.json',plan)
    fixed.update(plan_SHA256=common.digest(common.HERE/'試行計画.json'),bound_at=datetime.now(timezone.utc).isoformat(),
        diagnostic_repaired=True,diagnostic_repair_proof=dict(path=target.relative_to(common.ROOT).as_posix(),SHA256=common.digest(target)))
    write_replacement(common.HERE/'事前固定.json',fixed)
    print('半量診断を補完し正式plan/fixedへ再束縛、登録0金融0',flush=True)


if __name__=='__main__':main()
