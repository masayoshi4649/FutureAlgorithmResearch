"""反票OFF十二条件と保存ON十二対照の範囲を正式八部品/実登録へ結ぶ。"""

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_price_exit_ablation_20261014/engine'
READS={};CHECKS=[]


def read(path: Path) -> dict:
    """
    機能: 正式小metadata/登録/独立証跡だけを一目的一読する。
    引数: path(Path) は根が固定したJSON位置。
    返り値: dict はJSON辞書。元108金融本文/packet/台帳の読取無し。
    """
    key=path.relative_to(ROOT).as_posix();assert key not in READS
    raw=path.read_bytes();READS[key]=hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def check(condition: bool,label: str) -> None:
    """
    機能: 独立接続の論点と合否を記録する。
    引数: condition(bool)、label(str) は成立可否と論点。
    返り値: None。不成立はFalseを保存して止める。
    """
    assert condition,label;CHECKS.append(label)


# ----------------------------------------
def main() -> None:
    """
    機能: 最終16source・OFF12/保存ON12・792予定と実登録を金融前に独立確認する。
    引数: なし。正式固定と根登録終端の小証跡だけを読む。
    返り値: None。新金融/登録再実行/大入力取得をしない。
    """
    target=HERE/'反票OFF12と保存ON12及び最終16源の独立正式接続.json';assert not target.exists()
    source={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    try:
        check(len(source)==16,'最終source16')
        art=read(ENGINE/'反対価格票退出の単独OFFとON同値及び接頭の人工検査.json')
        independent=read(HERE/'反票単独OFFと旧ON九出力の独立完成16源接続.json')
        pure=read(HERE/'反票ON旧同値とOFF他停止保持の独立純期待.json')
        proposal=read(ENGINE/'試行計画.json');fixed=read(ENGINE/'金融事前固定.json')
        meta=read(ENGINE/'既33入力と108_ON十二条件の保存小目録.json')
        registration=read(ENGINE.parent/'金融前の照合と登録.json')
        registered=read(ENGINE.parent/'登録の全出力.json');preflight=read(ENGINE.parent/'重複照合の全出力.json')
        check(all(v['全合格'] for v in (art,independent,pure,fixed,meta,registration)),'所有/独立/小目録/登録は合格')
        check(source==art['source_SHA256']==independent['最終source_SHA256']==fixed['source_SHA256']==proposal['spec']['implementation'],'全16源を所有/独立/正式固定へ束縛')
        check(READS[(ENGINE/'試行計画.json').relative_to(ROOT).as_posix()]==fixed['計画SHA256']==registration['計画SHA256'],'正式計画bytesSHA一致')
        check(READS[(ENGINE.parent/'登録の全出力.json').relative_to(ROOT).as_posix()]==registration['登録SHA256'] and
              READS[(ENGINE.parent/'重複照合の全出力.json').relative_to(ROOT).as_posix()]==registration['照合SHA256'],'照合/登録の保存全出力SHA一致')
        sys.path.insert(0,str(ENGINE))
        if 'statistics' in sys.modules:del sys.modules['statistics']
        import common,catalog,runner,plan
        check(proposal['正式freeze'] and fixed['正式freeze'],'正式freeze済み')
        check(registration['登録ID']==catalog.TRIAL_ID==registered['id']==proposal['id'] and registration['状態']==registered['status']=='未実行','同trial/登録未実行')
        check(registration['金融']==registration['入力']==registration['API']==0,'登録時点の金融0')
        runner.registry_guard([registered],fixed,proposal);runner.source_scope_guard()
        roundtrip=lambda v:json.loads(json.dumps(v,ensure_ascii=False,allow_nan=False))
        runner.registry_guard(roundtrip([registered]),roundtrip(fixed),roundtrip(proposal))
        check(True,'登録実JSON/spec/source/新JIT所有域/JSON往復同値')
        configs=catalog.configs()
        check(configs==fixed['configs']==proposal['spec']['entry']['conditions'] and len(configs)==len({c['id'] for c in configs})==12,'OFF12case全項目/ID一致')
        check(plan.case_hashes(configs)==fixed['case_SHA256'],'OFF12全項目caseSHA一致')
        check(len({c['paired_on_id'] for c in configs})==12,'保存ON12との一対一対応')
        check(fixed['comparison_reference']==meta['comparison_reference'],'同目録の保存ON比較だけ再利用')
        check(len(fixed['comparison_reference']['cases'])==12 and {c['paired_on_id'] for c in configs}==set(fixed['comparison_reference']['cases']),
              '保存ON対照に欠落/余分/取り違え無し')
        for c in configs:
            check(c['enable_opposed_price_exit'] is False and c['quantity']==c['cap']=={'TOPIX':10,'NK225':20},c['id']+':独立反票OFF/実cap維持')
            check(c['paired_on_id']=='E01_PROTECT_'+c['reentry_id']+'_'+c['exit_id'],c['id']+':同入口/出口ON対照')
            check(c['target_session_mean_net_yen']=={'TOPIX':100000,'NK225':'円額目標の対象外（未指定）'},c['id']+':全場平均主/NK対象外')
        for kind in ('未登録','別trial','別spec','boolON','caseSHA','sourceSHA'):
            f,x,p=copy.deepcopy([registered]),copy.deepcopy(fixed),copy.deepcopy(proposal)
            if kind=='未登録':f=[]
            elif kind=='別trial':f[0]['id']='別trial'
            elif kind=='別spec':f[0]['spec']['exit']['追加']=True
            elif kind=='boolON':x['configs'][0]['enable_opposed_price_exit']=True
            elif kind=='caseSHA':x['case_SHA256'][configs[0]['id']]='0'*64
            else:x['source_SHA256'][next(iter(source))]='0'*64
            rejected=False
            try:runner.registry_guard(f,x,p)
            except AssertionError:rejected=True
            check(rejected,'登録guard拒否:'+kind)
        checkerpath=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
        ms=importlib.util.spec_from_file_location('独立反票八部品',checkerpath);checker=importlib.util.module_from_spec(ms);ms.loader.exec_module(checker)
        check(set(proposal['spec'])==set(checker.PARTS) and checker.analyze(proposal,[])['proposal_complete'],'八spec完全')
        check(preflight['proposal_complete'] and not any(v['kind']=='完全同一' for v in preflight['matches']) and
              bool(preflight['incomplete_history'])==registration['未照合過去あり'],'明示完全同一無し/未照合過去留保は別')
        check(plan.clones()==proposal['同bytesコピー'] and len(proposal['同bytesコピー'])==10,'旧10source同bytes/旧source実行接続無し')
        check(len(fixed['sessions'])==len(fixed['input_cache'])==33 and fixed['input_cache']==meta['input_cache'],'同33保存入力指紋目録')
        check(proposal['予定']==dict(新条件OFF=12,保存対照ON=12,既input一読=33,価格票準備口座=66,新account金融=792,ON再金融=0,旧台帳本文=0),
              '新OFF792だけ金融/旧ON再金融0/旧台帳本文0')
        tree=ast.parse((ENGINE/'runner.py').read_text(encoding='utf-8-sig'))
        run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        calls=[(n.lineno,ast.unparse(n.func)) for n in ast.walk(run) if isinstance(n,ast.Call)]
        load=next(i for i,n in calls if n=='data.load')
        check(sum(n=='data.load' for _,n in calls)==1 and all(next(i for i,n in calls if n==guard)<load for guard in ('registry_guard','source_scope_guard')),
              '大型唯一load文より前に実登録/sourceguard')
        check(sum(n=='price_votes.pair' for _,n in calls)==1 and sum(n=='interface.play' for _,n in calls)==1 and not any(n.startswith('baseline_core.') for _,n in calls),
              '票は同loaded場で一回、旧ON核心の金融run無し')
        check("assert not config['enable_opposed_price_exit']" in (ENGINE/'runner.py').read_text(encoding='utf-8-sig'),'金融各口座でOFFとreason152不使用を再assert')
        check(common.sources()==source,'監査開始終端16source不変')
        result=dict(全合格=True,最終source_SHA256=source,小資料SHA256=READS,確認数=len(CHECKS),確認観点=CHECKS,
                    独立ON旧同値144=True,独立OFF144=True,他経済AST差0=True,
                    留保=['保存ONは全場/上位3/買売の小集計だけ。親別/各場の因果寄与をここから捏造しない。',
                          '同じ既知33場の部品対照で、未知成功とは呼ばない。','source/人工合格は経済達成と別。',
                          'paper残量の副診断を入口資格へ追加しない。','Last票は攻撃方向/volumeの実測ではない。'],
                    新金融=0,元108金融本文=0,保存packet=0,台帳=0,原板=0,API=0)
    except BaseException:
        result=dict(全合格=False,最終source_SHA256=source,小資料SHA256=READS,確認観点=CHECKS,原因=traceback.format_exc(),
                    新金融=0,元108金融本文=0,保存packet=0,台帳=0,原板=0,API=0)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');raise
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('反票OFF12/保存ON12/正式16源接続合格 '+str(len(CHECKS))+' SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
