"""正式14源・十二case・八部品・実登録を独立人工の署名へ接続する。"""

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_protect_reentry_20261014/engine'
READS={}
CHECKS=[]


def read(path: Path) -> dict:
    """
    機能: 正式小metadataと独立人工だけを一目的一読する。
    引数: path(Path) は許可されたJSON小資料。
    返り値: dict は保存値。金融結果/packet/台帳/原板を読まない。
    """
    key=path.relative_to(ROOT).as_posix();assert key not in READS
    raw=path.read_bytes();READS[key]=hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def check(condition: bool, label: str) -> None:
    """
    機能: 独立した一致条件を日本語の論点へ保存する。
    引数: condition(bool)、label(str) は成立可否/論点。
    返り値: None。不一致はFalseへ保存して止める。
    """
    assert condition,label;CHECKS.append(label)


# ----------------------------------------
def main() -> None:
    """
    機能: 根freeze/登録後の唯一正式計画を独立署名・JSON境界・因果範囲へ照合する。
    引数: なし。14source/計画/固定/照合登録/独立証跡のみを扱う。
    返り値: None。金融再生や登録の再実行無しで接続証跡を作る。
    """
    target=HERE/'十二条件と最終14源及び八spec登録の独立正式接続.json';assert not target.exists()
    source={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    try:
        check(len(source)==14,'正式source14')
        for p in source:ast.parse((ROOT/p).read_text(encoding='utf-8-sig'))
        proposal=read(ENGINE/'試行計画.json');fixed=read(ENGINE/'金融事前固定.json')
        art=read(ENGINE/'十二保護と新価格票及び独立実親の人工検査_v2.json')
        independent=read(HERE/'現在票と十二実親出口の独立純期待及び完成14源接続_v3.json')
        buffer=read(HERE/'一paper八十実親の完成source動的buffer独立接続.json')
        registration=read(ENGINE.parent/'金融前の照合と登録.json')
        registered=read(ENGINE.parent/'登録の全出力.json');preflight=read(ENGINE.parent/'重複照合の全出力.json')
        metadata=read(ENGINE/'既33入力と107候補外比較の小目録.json')
        check(all(x['全合格'] for x in (fixed,art,independent,buffer,registration,metadata)),'所有/独立/登録は全合格')
        check(source==art['source_SHA256']==independent['所有最終source_SHA256']==buffer['最終source_SHA256']==fixed['source_SHA256']==proposal['spec']['implementation'],
              '14源を所有人工/独立336/動的80/正式spec固定へ束縛')
        check(READS[(ENGINE/'試行計画.json').relative_to(ROOT).as_posix()]==fixed['計画SHA256']==registration['計画SHA256'],'正式計画bytes指紋一致')
        check(READS[(ENGINE.parent/'登録の全出力.json').relative_to(ROOT).as_posix()]==registration['登録SHA256'] and
              READS[(ENGINE.parent/'重複照合の全出力.json').relative_to(ROOT).as_posix()]==registration['照合SHA256'],'実照合/登録全出力bytes一致')
        sys.path.insert(0,str(ENGINE))
        if 'statistics' in sys.modules:del sys.modules['statistics']
        import common,catalog,runner,plan,statistics
        check(proposal['正式freeze'] and fixed['正式freeze'],'正式freeze済み')
        check(registration['登録ID']==catalog.TRIAL_ID and registration['状態']==registered['status']=='未実行','実登録は同試行/未実行')
        check(registration['金融']==registration['入力']==registration['API']==0,'登録終端でも金融前')
        check(proposal['spec']==registered['spec'],'実登録八specは正式計画同値')
        roundtrip=lambda value:json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))
        runner.registry_guard([registered],fixed,proposal);runner.source_scope_guard()
        runner.registry_guard(roundtrip([registered]),roundtrip(fixed),roundtrip(proposal))
        check(True,'実JSON登録/roundtrip guardと新所有module/JIT隔離')
        configs=catalog.configs()
        check(len(configs)==len({c['id'] for c in configs})==12 and configs==fixed['configs']==proposal['spec']['entry']['conditions'],'12case全項目同値/ID重複無し')
        check(plan.case_hashes(configs)==fixed['case_SHA256'],'12case全項目SHA同値')
        for c in configs:
            check(c['quantity']==c['cap']=={'TOPIX':10,'NK225':20},c['id']+':実初回/片方向容量固定10/20')
            check(c['target_session_mean_net_yen']=={'TOPIX':100000,'NK225':'円額目標の対象外（未指定）'},c['id']+':全場平均床/未指定NK明示')
        for kind in ('未登録','別ID','別spec','別case','別指紋','別source'):
            f,x,p=copy.deepcopy([registered]),copy.deepcopy(fixed),copy.deepcopy(proposal)
            if kind=='未登録':f=[]
            elif kind=='別ID':f[0]['id']='別試行'
            elif kind=='別spec':f[0]['spec']['entry']['追加']=True
            elif kind=='別case':x['configs'][0]['parent_stop_fraction']=.5
            elif kind=='別指紋':x['case_SHA256'][configs[0]['id']]='0'*64
            else:x['source_SHA256'][next(iter(source))]='0'*64
            rejected=False
            try:runner.registry_guard(f,x,p)
            except AssertionError:rejected=True
            check(rejected,'金融前guard拒否:'+kind)
        checkerpath=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
        ms=importlib.util.spec_from_file_location('独立保護八部品',checkerpath);checker=importlib.util.module_from_spec(ms);ms.loader.exec_module(checker)
        check(set(proposal['spec'])==set(checker.PARTS) and checker.analyze(proposal,[])['proposal_complete'],'八spec完全/不明null無し')
        check(preflight['proposal_complete'] and not any(v['kind']=='完全同一' for v in preflight['matches']) and
              bool(preflight['incomplete_history'])==registration['未照合過去あり'],'比較可能完全同一無し/未照合過去留保を分離')
        check(plan.clones()==proposal['同bytesコピー'] and len(proposal['同bytesコピー'])==7,'旧7会計料金保存source同bytes/旧経済再実行無し')
        check(len(fixed['sessions'])==len(set(fixed['sessions']))==len(fixed['input_cache'])==33 and fixed['input_cache']==metadata['input_cache'],'同33場/入力目録を固定')
        check(fixed['comparison_reference']==metadata['comparison_reference'],'107候補外小引用のみ、12caseへ混ぜない')
        check(proposal['予定']==dict(新条件=12,既input一読=33,価格票準備口座=66,新account金融=792,旧GU再利用=0,旧台帳本文=0),'33×2×12=792実状態/価格票66/入力33/旧再利用0')
        tree=ast.parse((ENGINE/'runner.py').read_text(encoding='utf-8-sig'))
        run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        calls=[(n.lineno,ast.unparse(n.func)) for n in ast.walk(run) if isinstance(n,ast.Call)]
        load=next(line for line,name in calls if name=='data.load')
        check(sum(name=='data.load' for _,name in calls)==1 and all(next(line for line,name in calls if name==g)<load for g in ('registry_guard','source_scope_guard')),
              '登録/sourceguardは唯一inputload文より前')
        check(sum(name=='price_votes.pair' for _,name in calls)==1 and sum(name=='interface.play' for _,name in calls)==1 and
              dict(runner.EXPECTED)==dict(既input一読=33,価格票準備口座=66,新account金融=792),'同loaded場で票一回/各12新口座を独立全運転')
        oldpure=ROOT/'work/e01_economic_scale_20261014/audit/owned/economic_final_connection.py'
        ms=importlib.util.spec_from_file_location('独立全場平均の純算術',oldpure);pure=importlib.util.module_from_spec(ms);ms.loader.exec_module(pure)
        pure.arithmetic(statistics);check(True,'損失無取引込み33平均/trim残場平均/NKNoneの既独立純算術')
        check(common.sources()==source,'開始終端14source不変')
        value=dict(全合格=True,最終source_SHA256=source,小資料SHA256=READS,独立確認数=len(CHECKS),確認観点=CHECKS,
                   独立価格票30240=True,独立小口座336=True,独立接頭1008=True,独立一paper八十実親=True,
                   仕様確定に伴う純モデル訂正='公開拒否審査の消費、同行全paper後のorigin拒否、quiet初normal正常anchorの区別をroot確定後金融前に反映。元純/source/Falseはarchive保全。',
                   留保=['同じ既知33場探索。未知セッションの成功証拠ではない。','Last更新票は真の攻撃注文量/volume方向ではない。',
                         'paper候補と方向phaseは保存E01から継承。実親分母/CID/UIDと新価格票は別。',
                         '価格proxyのpeer strict過去は物理受信先後の証明ではない。','ラージBBO代理の全量FAKで板深度/実部分約定/到着遅延は未検証。',
                         '源と純人工の合格は利益目標の達成を示さない。'],
                   金融=0,保存入力=0,台帳=0,原板=0,NPZ=0,旧107結果=0,API=0)
    except BaseException:
        value=dict(全合格=False,最終source_SHA256=source,小資料SHA256=READS,確認観点=CHECKS,原因=traceback.format_exc(),
                   金融=0,保存入力=0,台帳=0,原板=0,NPZ=0,旧107結果=0,API=0)
        target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');raise
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('正式14源/12case独立接続合格 '+str(len(CHECKS))+' SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
