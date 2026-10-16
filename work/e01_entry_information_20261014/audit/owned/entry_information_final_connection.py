"""495唯一金融・99内部同値・198保存PRICEを正式八部品と実登録へ独立接続する。"""

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENGINE = ROOT / 'work/e01_entry_information_20261014/engine'
READS = {}
CHECKS = []


def read(path: Path) -> dict:
    """
    機能: 正式小metadataと登録証跡だけを同bytes一目的一読する。
    引数: path(Path) は許可されたJSON位置。
    返り値: dict はJSON構造。金融本文・保存packet・台帳を読まない。
    """
    key = path.relative_to(ROOT).as_posix()
    assert key not in READS
    raw = path.read_bytes(); READS[key] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def check(value: bool, label: str) -> None:
    """
    機能: 接続論点の成立と意味を一緒に記録する。
    引数: value(bool)、label(str) は合否と説明。
    返り値: None。不成立はFalse保存へ伝える。
    """
    assert value, label
    CHECKS.append(label)


# ----------------------------------------
def main() -> None:
    """
    機能: 最終17源・12掲載・唯一495金融と登録を正式実行前に検査する。
    引数: なし。root正式freeze/登録終端後だけ実行する。
    返り値: None。新金融・登録再実行・巨大入力取得を行わない。
    """
    target = HERE / '四入口十二掲載と495唯一及び最終17源の独立正式接続.json'
    assert not target.exists()
    source = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    try:
        art = read(ENGINE / '原新規の出来高signed票とPRICE保存同値及び接頭の人工検査_v3.json')
        independent = read(HERE / '入口情報一枝と旧PRICE九出力及び完成17源の独立接続_v2.json')
        pure = read(HERE / '原公開signed票と価格票分離の独立純期待.json')
        proposal = read(ENGINE / '試行計画.json'); fixed = read(ENGINE / '金融事前固定.json')
        metadata = read(ENGINE / '既33入力とPRICE三条件の保存小目録.json')
        registration = read(ENGINE.parent / '金融前の照合と登録.json')
        registered = read(ENGINE.parent / '登録の全出力.json'); preflight = read(ENGINE.parent / '重複照合の全出力.json')
        check(len(source)==17 and all(v['全合格'] for v in (art,independent,pure,fixed,metadata,registration)), '完成17源と所有/独立人工及び小固定の合格')
        check(source==art['source_SHA256']==independent['完成source_SHA256']==fixed['source_SHA256']==proposal['spec']['implementation'], '全17源の当時署名を所有/独立/正式固定へ束縛')
        check(READS[(ENGINE/'試行計画.json').relative_to(ROOT).as_posix()]==fixed['計画SHA256']==registration['計画SHA256'], '正式計画bytes指紋一致')
        check(READS[(ENGINE.parent/'登録の全出力.json').relative_to(ROOT).as_posix()]==registration['登録SHA256'] and READS[(ENGINE.parent/'重複照合の全出力.json').relative_to(ROOT).as_posix()]==registration['照合SHA256'], '照合/登録の保存全出力指紋一致')
        sys.path.insert(0,str(ENGINE))
        if 'statistics' in sys.modules:
            del sys.modules['statistics']
        import common,catalog,runner,plan
        check(proposal['正式freeze'] and fixed['正式freeze'], '根の正式freeze完了')
        check(registration['登録ID']==registered['id']==proposal['id']==catalog.TRIAL_ID and registration['状態']==registered['status']=='未実行', '実登録同trial/specで未金融')
        check(registration['金融']==registration['入力']==registration['API']==0, '登録証跡の金融/入力/APIは零')
        runner.registry_guard([registered],fixed,proposal); runner.source_scope_guard()
        normalized = lambda value:json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))
        runner.registry_guard(normalized([registered]),normalized(fixed),normalized(proposal))
        check(True, '実登録及びJSON往復一致と新source/JIT所有域guard')
        configs = catalog.configs()
        check(configs==fixed['configs']==proposal['spec']['entry']['conditions'] and len(configs)==len({c['id'] for c in configs})==12, '12掲載全条件の全項目一致')
        check(plan.case_hashes(configs)==fixed['case_SHA256'], '12条件全項目SHA一致')
        check(sum(c['actual_financial'] for c in configs)==9 and sum(c['actual_financial_by_symbol']['TOPIX'] for c in configs)==9 and sum(c['actual_financial_by_symbol']['NK225'] for c in configs)==6, 'TOP9/NK6の唯一金融15条件')
        check(fixed['comparison_reference']==metadata['comparison_reference'] and len(fixed['comparison_reference']['cases'])==3, '保存PRICE三退出の同bytes小比較')
        expected_ids = {c['paired_price_id'] for c in configs if c['entry_id']=='PRICE_BOTH'}
        check(expected_ids==set(fixed['comparison_reference']['cases']), '保存PRICE三IDの欠落/余分/退出違い無し')
        for c in configs:
            check(c['reentry_id']=='ORIGIN' and c['enable_opposed_price_exit'] is False and c['quantity']==c['cap']=={'TOPIX':10,'NK225':20}, c['id']+':ORIGIN/反票退出OFF/cap固定')
            check(c['volume_balance_threshold']=={'TOPIX':.5 if c['entry_id']=='VOL_SELECTED' else .25,'NK225':.25}, c['id']+':signed閾値の直接比較')
            check(c['target_session_mean_net_yen']=={'TOPIX':100000,'NK225':'円額目標の対象外（未指定）'}, c['id']+':TOP全33場平均主/NK対象外')
            if c['entry_id']=='VOL25':
                check(c['economic_source_id_by_symbol']['NK225']=='E01_INFO_VOL_SELECTED_'+c['exit_id'] and c['execution_kind_by_symbol']['NK225']=='内部同値保存再利用', c['id']+':NK同出口SELECTEDへの事前alias')
        parts_path = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
        spec = importlib.util.spec_from_file_location('入口情報の独立八部品',parts_path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        check(set(proposal['spec'])==set(module.PARTS) and module.analyze(proposal,[])['proposal_complete'], '八spec完全性')
        check(preflight['proposal_complete'] and not any(x['kind']=='完全同一' for x in preflight['matches']) and bool(preflight['incomplete_history'])==registration['未照合過去あり'], '完全比較可能同一無しと未照合過去ありを区別')
        check(plan.clones()==proposal['同bytesコピー'] and len(proposal['同bytesコピー'])==10, '旧10源同bytesと実行先所有域の分離')
        check(len(fixed['sessions'])==len(fixed['input_cache'])==33 and fixed['input_cache']==metadata['input_cache'], '同33入力の指紋小目録')
        expected_counts = dict(比較条件=12,新volume表示条件=9,唯一金融商品条件=15,内部同値商品条件=3,保存PRICE条件=3,
            既input一読=33,価格票準備口座=66,新account金融=495,内部同値会計再利用=99,内部同値再金融=0,
            保存PRICE会計=198,掲載口座=792,PRICE再金融=0,旧台帳本文=0)
        check(proposal['予定']==expected_counts, '唯一495＋NKalias99＋保存PRICE198の792掲載')
        for label in ('未登録','別spec','別source','別case','ORIGIN違い','alias違い'):
            found,x,p = copy.deepcopy([registered]),copy.deepcopy(fixed),copy.deepcopy(proposal)
            if label=='未登録':found=[]
            elif label=='別spec':found[0]['spec']['exit']['追加']=True
            elif label=='別source':x['source_SHA256'][next(iter(source))]='0'*64
            elif label=='別case':x['case_SHA256'][configs[0]['id']]='0'*64
            elif label=='ORIGIN違い':x['configs'][0]['reentry_id']='PULL'
            else:x['configs'][6]['economic_source_id_by_symbol']['NK225']='別ID'
            failed = False
            try:runner.registry_guard(found,x,p)
            except AssertionError:failed=True
            check(failed, '登録guard拒否:'+label)
        run_tree = ast.parse((ENGINE/'runner.py').read_text(encoding='utf-8-sig'))
        run = next(n for n in run_tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        calls = [(n.lineno,ast.unparse(n.func)) for n in ast.walk(run) if isinstance(n,ast.Call)]
        load = next(i for i,n in calls if n=='data.load')
        check(sum(n=='data.load' for _,n in calls)==1 and all(next(i for i,n in calls if n==guard)<load for guard in ('registry_guard','source_scope_guard')), '唯一大型loadより先に登録/sourceguard')
        check(sum(n=='price_votes.pair' for _,n in calls)==1 and sum(n=='interface.play' for _,n in calls)==1 and not any(n.startswith('baseline_core.') for _,n in calls), '同packet価格票一回と保存PRICE再金融無し')
        alias_branch = next(n for n in ast.walk(run) if isinstance(n,ast.If) and ast.unparse(n.test)=="not config['actual_financial_by_symbol'][s]")
        check(isinstance(alias_branch.body[-1],ast.Continue) and not any(isinstance(n,ast.Call) and ast.unparse(n.func)=='interface.play' for child in alias_branch.body for n in ast.walk(child)), 'NKaliasは保存コピー後continueし新coreを運転しない')
        check(common.sources()==source, '監査開始終端17source不変')
        result = dict(全合格=True,最終source_SHA256=source,小資料SHA256=READS,確認数=len(CHECKS),確認観点=CHECKS,
            留保=['同じ既知33場の情報入口対照であり、未知成功ではない。','PRICE三対照は保存小会計で、旧親経路の時刻対応を補完しない。',
                  'NK同値99場は別効能又は追加標本に数えない。','出来高代理票を真の攻撃数量又は物理受信時計の証明と呼ばない。'],
            新金融=0,原入力=0,原板=0,台帳=0,元109金融本文=0,API=0)
    except BaseException:
        result = dict(全合格=False,最終source_SHA256=source,小資料SHA256=READS,確認観点=CHECKS,原因=traceback.format_exc(),新金融=0,原入力=0,台帳=0,API=0)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8'); raise
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=len(CHECKS),SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
