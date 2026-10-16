"""根の八部品草案と完成経済源を結び、未登録の実金融を開始しない。"""

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
WORK=ROOT/'work/e01_current_reassessment_20261015'
REVIEW=WORK/'root_review'
OUTPUT=HERE/'九新条件と保存基準及び修正guardの独立八部品草案接続.json'
COUNTS=Counter()


def check(ok:bool,label:str) -> None:
    """
    機能: source・条件・引用・guardの接続を分類して照合する。
    引数: ok(bool)、label(str) は判断と分類。
    返り値: None。不一致を有効性未達と混同しない。
    """
    assert bool(ok),label
    COUNTS[label]+=1


def read(path:Path) -> tuple[dict,str]:
    """
    機能: 今回の小計画又は合成証跡だけを同bytesで確認する。
    引数: path(Path) は明示された計画又は証跡。
    返り値: tuple[dict,str] は内容と指紋。金融・cache・NPZを開かない。
    """
    saved=path.read_bytes();value=json.loads(saved)
    json.dumps(value,allow_nan=False)
    return value,hashlib.sha256(saved).hexdigest()


def main() -> None:
    """
    機能: 八部品draftの意味・現在source・金融前guardを接続する。
    引数: なし。
    返り値: None。正式freeze/登録は根がこの後実施する。
    """
    assert not OUTPUT.exists()
    proposal,plan_sha=read(REVIEW/'試行計画草案.json')
    fixed,fixed_sha=read(REVIEW/'準備固定.json')
    meta,meta_sha=read(REVIEW/'旧三十三場の入力と保存基準の一読目録.json')
    own,_=read(HERE/'完成signalと独立純期待及び八源不変更のSOURCE_ONLY接続.json')
    native,native_sha=read(WORK/'audit_accounting/実注文独立会計と支持非後退及び同事象一回消費の純人工.json')
    latest,latest_sha=read(REVIEW/'根の一次台帳と未知保持及び最終JSON保存の純人工_v4.json')
    supplement,supp_sha=read(WORK/'audit_accounting/根33唯一入力guardと新JITのみ初期化の独立追補.json')
    spec=proposal['spec']
    check(set(spec)=={'entry','management','exit','allocation','costs','execution','data','implementation'},'八部品が揃う草案')
    check(not proposal['正式freeze'] and not fixed['正式freeze'],'草案を正式登録済みとしない')
    check(fixed['計画SHA256']==plan_sha,'草案と準備固定の指紋一致')
    check(fixed['configs']==spec['entry']['conditions'] and len(fixed['configs'])==len({x['id'] for x in fixed['configs']})==9,'三入口三出口の九唯一条件')
    expected_hash={c['id']:hashlib.sha256(json.dumps(c,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest() for c in fixed['configs']}
    check(fixed['case_SHA256']==expected_hash,'JSON往復後の全項目条件指紋')
    check(fixed['sessions']==spec['data']['sessions']==meta['入力の固定']['sessions'] and fixed['inputs']==spec['data']['inputs']==meta['入力の固定']['inputs'],'同じ全33入力の元固定からの完全継承')
    check(len(fixed['sessions'])==len(set(fixed['sessions']))==len(fixed['inputs'])==33,'全33唯一場と無取引含む分母')
    for session,pair in fixed['inputs'].items():
        check(set(pair)=={'TradeGate','TradeExit'},'各場の二cacheだけを固定')
        for name,item in pair.items():
            base=ROOT/('work/wave_v106/e01_trade_gate/input' if name=='TradeGate' else 'work/wave_v106/e01_trade_exit/input')
            check((ROOT/item['path']).resolve().is_relative_to(base.resolve()) and item['stat_bytes']>0 and len(item['SHA256'])==64,'入力pathSHAstatの限定範囲だけを確認')
    check(meta['出典'][0]['SHA256']=='57ad4fa098f7a04d425f308070e4d89d5c9004998e66c7e9c172174318a89825','finite時計補完済み23源入力の継承出典')
    for relative,digest in meta['入力の固定']['source_SHA256'].items():
        check(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,'継承された23源と時計補完の現在指紋')
    baseline=meta['保存比較']['cases']['E01_EVID_VOL_SELECTED_TARGET']
    check(len(baseline['rows'])==66 and len({(r['session'],r['symbol']) for r in baseline['rows']})==66,'基準SEL_TARGET保存66会計の引用だけ')
    check(proposal['予定']==dict(新経済条件=9,新金融口座=594,大型cache=66,基準保存会計=66,基準再金融=0,掲載比較=10,新二場本文=0,原板=0,NPZ=0,API=0),'新594と保存66を掲載10比較へ区別')
    check(proposal['表示主候補']=='E01_CURRENT_VOL_PRICE_RESPONSE_WIDE_TRAIL' and '結果前' in proposal['選択'],'③wide主候補を結果前固定')
    check('正式な未知データ認定ではない' in spec['data']['未読の追加場'],'追加二場は本作業未読だけで未見認定しない')
    check('純入口効果とは呼ばない' in spec['data']['対照'],'旧基準との複数差分を純入口効果としない')
    for c in fixed['configs']:
        check(c['quantity']==c['cap']=={'TOPIX':10,'NK225':20},'実使用量と片方向上限')
        check(c['window_seconds']==60 and c['bar_seconds']==300 and c['volume_balance_threshold']=={'TOPIX':.5,'NK225':.25},'当時窓と閉足と方向閾値')
        check(c['min_votes']==c['price_min_votes_each']==2 and c['price_balance_threshold_each']==.25 and c['strong_price_balance']==.75 and c['strong_price_min2'],'価格入口とFAKの別閾値')
        check((c['base_progress_ticks'],c['response_progress_ticks'],c['probe_max_adverse_ticks'],c['support_margin_ticks'])==(1,2,1,1),'BBO基準と支持線の固定tick')
        check((c['parent_stop_fraction'],c['parent_target_fraction'],c['session_stop_fraction'],c['session_profit_fraction'],c['public_cost_stop_ratio'])==(.00075,.00125,.0025,.00375,.5),'親場純清算と公開費用の数値差なし')
        check((c['new_start_offset_seconds'],c['new_end_offset_seconds'])==(300,300) and c['holding_time_stop']==c['paper_withdrawal_exit']=='不使用','固定時間保有とpaper151を使わない')
        rates=(.00075,.00025,.0005) if c['exit_id']=='TIGHT_TRAIL' else (.00125,.000375,.00075)
        check((c['arm_fraction'],c['draw_fraction'],c['floor_fraction'])==rates,'Native三出口の数値固定')
        check(c['target_session_mean_net_yen']=={'TOPIX':100000,'NK225':'円額目標の対象外（未指定）'},'TOP全33場平均とNK床未指定')
    current={};texts={}
    for relative,old_sha in spec['implementation'].items():
        saved=(ROOT/relative).read_bytes();current[relative]=hashlib.sha256(saved).hexdigest();texts[relative]=saved.decode('utf-8-sig')
        ast.parse(texts[relative])
    check(len(current)==17 and len(own['source_SHA256'])==14,'経済十四と根driver三の現在集合')
    for relative,digest in own['source_SHA256'].items():
        check(current[relative]==digest==native['source_SHA256'][relative],'signalとNative独立監査の閉鎖14源同値')
    stale={k for k,v in current.items() if spec['implementation'][k]!=v}
    check(stale=={'work/e01_current_reassessment_20261015/root_review/finance.py'},'既報の草案との差はrootguardJITの一源だけ')
    for audit in (latest,supplement):
        check(audit['全合格'],'最新根保存とguard追補の人工は合格')
        for relative,digest in audit.get('source_SHA256',{}).items():
            check(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,'最新guard保存補完の全sourcehash一致')
    finance_path='work/e01_current_reassessment_20261015/root_review/finance.py'
    finance=texts[finance_path];tree=ast.parse(finance)
    run_node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    run_text=ast.get_source_segment(finance,run_node)
    check(run_text.index('guard(fixed,proposal)')<run_text.index('load_cache('),'実cacheより先に登録sourceinputguard')
    check("for session in fixed['sessions']" in run_text and "for config in configs" in run_text and 'interface.play(' in run_text,'全33と全後続9Nativeの実運転接続')
    check("len(baseline['rows'])==66" in run_text and '再金融=0' in run_text and 'source==root_plan.sources()' in run_text,'保存基準と開始終端sourceの接続')
    for token in ('import common','for module in (common,catalog,interface','CPUDispatcher','is_relative_to(ENGINE/\'jit\')'):
        check(token in finance,'新enginemoduleと新JITだけへ束縛')
    guard_node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guard')
    sandbox=HERE/'純guard擬似位置';expected_plan_sha='純合成計画指紋'
    synthetic=deepcopy(proposal);synthetic['正式freeze']=True;synthetic['spec']['implementation']=current
    synthetic_fixed=deepcopy(fixed);synthetic_fixed['正式freeze']=True;synthetic_fixed['source_SHA256']=current;synthetic_fixed['計画SHA256']=expected_plan_sha
    manifest_hash={str(ROOT/item['path']):item['sha256'] for item in synthetic['spec']['data']['input_manifests']}
    manifest_hash[str(sandbox/'試行計画.json')]=expected_plan_sha
    registry=[dict(id=synthetic['id'],spec=deepcopy(synthetic['spec']))]
    fake_plan=SimpleNamespace(sources=lambda:current,case_hashes=lambda configs:expected_hash,
        sha=lambda path:manifest_hash[str(path)],read=lambda path:dict(trials=registry))
    namespace=dict(catalog=SimpleNamespace(TRIAL_ID=synthetic['id'],configs=lambda:fixed['configs']),root_plan=fake_plan,
        HERE=sandbox,ROOT=ROOT,OUT=sandbox/'未実行finance',REGISTRY=sandbox/'仮registry')
    exec(compile(ast.Module(body=[guard_node],type_ignores=[]),'<根guardのみ純抽出>','exec'),namespace)
    namespace['guard'](synthetic_fixed,synthetic);COUNTS['実guard本文の登録済み純合成成功接続']+=1
    namespace['guard'] # 取得だけでrunは呼ばない。
    for label,mutate in (
        ('未正式freezeを拒否',lambda f,p:f.update(正式freeze=False)),
        ('実行入力の登録specとの差を拒否',lambda f,p:f['inputs'].pop(f['sessions'][0])),
        ('実行場順の登録specとの差を拒否',lambda f,p:f['sessions'].reverse()),
        ('実行sourceの登録specとの差を拒否',lambda f,p:f['source_SHA256'].update({finance_path:'異なるsource'})),
    ):
        f,p=deepcopy(synthetic_fixed),deepcopy(synthetic);mutate(f,p)
        try:namespace['guard'](f,p)
        except AssertionError:COUNTS[label]+=1
        else:raise AssertionError(label)
    for relative,digest in current.items():
        check(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,'現17源開始終端不変更')
    result=dict(全合格=True,状態='SOURCE_ONLYの八部品草案最終接続。正式freeze/実登録/金融はまだ根の次操作。',
        検査数=sum(COUNTS.values()),分類=dict(COUNTS),source_SHA256=current,
        草案SHA256=plan_sha,旧準備固定SHA256=fixed_sha,入力保存比較目録SHA256=meta_sha,
        最新根保存v4SHA256=latest_sha,最新guard新JIT追補SHA256=supp_sha,
        監査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        金融前のguard指摘と是正='固定sessions/inputsを登録spec dataへ完全一致、33唯一を検査。新engine/JIT path guardも追加。14経済源/数値/config/data/主候補は不変更。',
        正式版に必要な更新='草案旧financeSHAを現17源に更新し、旧根保存v3引用を最新v4とguard追補へ置換。根はこれを正式freezeに含める。旧草案を正式合格として使わない。',
        残不一致='現sourceと売買仕様には停止すべき不一致なし。正式source/manifestの置換と実登録は根の次操作として未完了。',
        予定=dict(新Native=594,新9条件=9,元二cache=66,保存基準=66,保存基準再金融=0,掲載比較=10),
        未測=['新9条件の実損益','新2場の全過去既読有無','物理受信因果','実mini/microの注文順位・部分約定'],
        元cache=0,金融本文=0,金融=0,NPZ=0,実台帳=0,原board=0,API=0,共有編集=0)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('八部品草案最終接続 '+str(result['検査数'])+'合格。SHA '+hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        p=HERE/'八部品草案最終接続初版False.json';assert not p.exists()
        p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),分類=dict(COUNTS),元cache=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
