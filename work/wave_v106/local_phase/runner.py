"""登録後に局所位相12を一回再生し、無RのALIGNED6はC保存経済から派生する。"""

import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import time

import numpy as np

import catalog
import common
import data
import derivation
import interface
import selection

HERE=common.HERE
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
TOTALS=common.module('106局所位相の不変102集計',common.ROOT/'work/wave_v102/accounting.py')
DIFFERENCE=common.module('106局所位相の不変同量寄与',common.ROOT/'work/wave_v106/accounting.py')
ACCOUNT=interface.module('106局所位相の方向別金融会計',HERE/'engine/accounting.py')
REGISTRY=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'
ALIAS_PROOF=HERE/'ALIGNED全6の無RとC同入口の非金融確認.json'


def stored(output: dict, normal: dict, record: dict) -> dict:
    """
    機能: 物理注文/当時根拠を保存し、全行時価と保有を変化原行へ圧縮する。
    引数: output/normal/record(dict)は同原行の経済と選択入力及び価格。
    返り値: dictは疎台帳。金融source又は当時値を後の損益で書換えない。
    """
    omitted={'curve','source_curve','target_trace','stale_equity'}
    value={key:item for key,item in output.items() if key not in omitted}
    value.update(row_count=len(record['seq']),selection_diagnostics=normal['decisions'])
    for name in ('curve','source_curve','target_trace'):
        array=output[name]
        changes=np.r_[True,np.diff(array)!=0] if array.ndim==1 else np.r_[True,np.any(np.diff(array,axis=0)!=0,axis=1)]
        rows=np.flatnonzero(changes);value[name]=dict(rows=rows,values=array[rows])
    return value


def physical_case(prepared: dict, normal: dict, config: dict, key: tuple[str,str]) -> tuple[dict,dict]:
    """
    機能: OWN/BOTHだけを実数量の新執行と最新四引数会計へ接続する。
    引数: prepared/normal/config(dict)、key(tuple[str,str])は同入力と固定条件・明示場商品。
    返り値: tuple[dict,dict]は実出力とセッション会計。ALIGNEDを新再生することは禁止する。
    """
    assert config['local_policy'] in ('OWN_VETO','BOTH_VETO')
    record=prepared['record'];symbol=record['symbol']
    output=interface.play(prepared,normal,config,quantity=config['quantity'][symbol])
    assert key[1]==symbol
    row=ACCOUNT.inspect(key,record,output,normal)
    return output,row


def check_alias_proof() -> dict:
    """
    機能: 全33のC同値と無R、人工半量派生の証跡を要求する。
    引数: なし。小証跡と現source指紋のみを読む。
    返り値: dictは合格証跡。無発火を勝ちと呼ばない。
    """
    proof=common.read(ALIAS_PROOF)
    assert proof['全合格'] and proof['alias照合口座数']==396 and proof['商品口座数']==66
    assert proof['新金融再生']==0 and proof['比較元ID']==derivation.C_ID
    for name,sha in proof['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    for name,sha in proof['SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    return proof


def bind() -> None:
    """
    機能: 未登録の18表示/12新再生/6派生を、driverと基準目録へ最終束縛する。
    引数: なし。既固定数値、人工、無R入力証明と旧結果目録を読む。
    返り値: None。初版草案/固定を保存し、登録や金融を自動実行しない。
    """
    assert not (HERE/'試行計画.json').exists()
    fixed=common.read(HERE/'事前固定.json');plan=common.read(HERE/'試行計画草案.json')
    assert fixed['全合格'] and fixed['configs']==catalog.catalog() and fixed['新金融再生']==0
    assert not any(t['id']==catalog.TRIAL_ID for t in common.read(REGISTRY)['trials'])
    for name,sha in fixed['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    check_alias_proof();derivation.baseline_metadata(fixed['sessions'],fixed['configs'])
    proof_paths=[HERE/'実行部と半量C派生の結合人工検査.json',ALIAS_PROOF,
        common.ROOT/'work/wave_v106/current_session/phase_review/直近位相の価格資格と同原行の独立確認.json']
    for path in proof_paths:
        proof=common.read(path);assert proof['全合格']
        for name,sha in proof.get('source_SHA256',{}).items():assert common.digest(common.ROOT/name)==sha,name
    common.write(HERE/'driver束縛前の事前固定.json',fixed)
    paths=[HERE/n for n in ('runner.py','derivation.py','alias_proof.py','runner_artificial.py')]
    paths += [HERE/'engine/old_regime_core.py',common.ROOT/'work/wave_v102/accounting.py',common.ROOT/'work/wave_v106/accounting.py']
    for path in paths:fixed['source_SHA256'][path.relative_to(common.ROOT).as_posix()]=common.digest(path)
    real=[c['id'] for c in fixed['configs'] if c['local_policy']!='ALIGNED']
    alias=[c['id'] for c in fixed['configs'] if c['local_policy']=='ALIGNED']
    assert len(real)==12 and len(alias)==6
    plan['change']+=' 実金融はOWN/BOTH12のみ。ALIGNED6は全33のR無発火証明に基づき保存C_ONLYの整数半量を再利用する。'
    plan['repeat_reason']+=' 活動確認でALIGNED全6のR候補が0だったため、新金融を重複実行せず保存C_ONLY経済へ派生する。これをR改善成功へ数えない。'
    plan['spec']['entry'].update(display_condition_count=18,actual_financial_conditions=12,alias_conditions=6,
        no_R_alias='既知33のALIGNEDはR候補0。元C_ONLY_B2_ER40_B4の同約定を5/10枚へ派生、独立成功ではない。')
    plan['spec']['allocation']['alias_derivation']='C_ONLY元10/20枚の同価格/時刻/親。各注文418→209円/220→110円が厳密半分、数量も整数半分。新金融0。'
    plan['spec']['data']['input_manifests'] += [dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (derivation.C_RESULTS,ALIAS_PROOF)]
    plan['spec']['implementation']=fixed['source_SHA256']
    plan['evidence'] += [dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in proof_paths]
    plan['状態']='18表示/基準6。OWN/BOTH12×66=792新口座を根が登録後一回実行。ALIGNED6は旧C派生、基準6AUTO再生0。まだ金融0。'
    fixed.update(actual_condition_ids=real,alias_condition_ids=alias,actual_financial_conditions=12,alias_conditions=6,
        target_actual_accounts=792,target_display_accounts=1188,runner_bound=True,
        C_comparator=dict(id=derivation.C_ID,quantity={'TOPIX':5,'NK225':10},source_quantity={'TOPIX':10,'NK225':20}),
        proofs=fixed['proofs']+[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in proof_paths])
    common.write(HERE/'試行計画.json',plan)
    fixed.update(plan_SHA256=common.digest(HERE/'試行計画.json'),bound_at=datetime.now(timezone.utc).isoformat())
    (HERE/'事前固定.json').write_text(__import__('json').dumps(fixed,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print('直近位相の12新金融/6派生へdriver束縛、金融0',flush=True)


def run() -> None:
    """
    機能: 登録済み12条件だけを一回再生し、ALIGNED6と基準6は保存経済を再利用する。
    引数: なし。根のCLI明示指示、登録specと現在指紋の完全一致を必須とする。
    返り値: None。新792口座/表示1188口座と5寄与を保存、原本/API/旧金融再生は0。
    """
    fixed=common.read(HERE/'事前固定.json');assert fixed['全合格'] and fixed['runner_bound']
    assert fixed['configs']==catalog.catalog() and fixed['actual_financial_conditions']==12
    plan_path=HERE/'試行計画.json';assert common.digest(plan_path)==fixed['plan_SHA256']
    plan=common.read(plan_path)
    for name,sha in fixed['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    registered=[t for t in common.read(REGISTRY)['trials'] if t['id']==catalog.TRIAL_ID]
    assert len(registered)==1 and registered[0]['spec']==plan['spec']
    for item in plan['spec']['data']['input_manifests']:
        assert common.digest(common.ROOT/item['path'])==item['sha256'],item['path']
    assert not (HERE/'finance/results.json').exists() and not (HERE/'finance/開始.json').exists()
    check_alias_proof();prior,c_prior=derivation.baseline_metadata(fixed['sessions'],fixed['configs'])
    configs=fixed['configs'];cases={c['id']:dict(rows=[],ledgers={}) for c in configs}
    totals={c['id']:{s:{f:0. for f in FIELDS} for s in ('TOPIX','NK225')} for c in configs}
    baselines={b:prior['cases'][b] for b in fixed['base_ids']}
    derived_C=[];finished=0;displayed=0;started=time.monotonic()
    common.write(HERE/'finance/開始.json',dict(全合格=True,trial_id=catalog.TRIAL_ID,
        時刻=datetime.now(timezone.utc).isoformat(),表示条件数=18,新金融条件数=12,派生条件数=6,新金融口座数=792))
    try:
        for session in fixed['sessions']:
            packet=data.load_session(session);deltas={}
            for symbol in ('TOPIX','NK225'):
                prepared=packet['prepared'][symbol];record=prepared['record'];record_key=(session,symbol)
                oldmaps={}
                for base in fixed['base_ids']:
                    item=prior['cases'][base]['ledgers'][session][symbol];old=common.unpack(item)
                    assert old['row_count']==len(record['seq'])
                    assert np.all(old['orders'][:,5]==(5 if symbol=='TOPIX' else 10))
                    oldmaps[base]=DIFFERENCE.trade_map(old,record);del old
                    saved_row=next(r for r in prior['cases'][base]['rows'] if r['session']==session and r['symbol']==symbol)
                    assert abs(sum(v['net'] for v in oldmaps[base].values())-saved_row['net'])<1e-4
                c_item=c_prior['cases'][derivation.C_ID]['ledgers'][session][symbol]
                c_old=common.unpack(c_item);half=derivation.half_output(c_old,record,c_item);del c_old
                c_normal=derivation.c_normal(packet,symbol)
                c_row=ACCOUNT.inspect(record_key,record,half,c_normal)
                c_row.update(derived=True,quantity=5 if symbol=='TOPIX' else 10,source_id=derivation.C_ID)
                derived_C.append(c_row);cmap=DIFFERENCE.trade_map(half,record)
                c_path=HERE/'finance/derived_C'/f'{session}_{symbol}.pkl.gz'
                common.write(c_path,stored(half,c_normal,record))
                c_reference=dict(path=c_path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(c_path),
                    derived=True,source=c_item,source_id=derivation.C_ID,quantity=c_row['quantity'],financial_replays=0)
                del half
                for config in configs:
                    ident=config['id'];normal=selection.build(packet,symbol,config)
                    if config['local_policy']=='ALIGNED':
                        derivation.verify_alias(packet,symbol,normal)
                        row=deepcopy(c_row);mapping=cmap;item=dict(c_reference,alias_id=ident)
                    else:
                        output,row=physical_case(prepared,normal,config,record_key)
                        mapping=DIFFERENCE.trade_map(output,record)
                        path=HERE/'finance/ledger'/ident/f'{session}_{symbol}.pkl.gz'
                        common.write(path,stored(output,normal,record))
                        item=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path),derived=False)
                        finished+=1;del output
                    row.update(selected_C=int(np.count_nonzero((normal['event']!=0)&(normal['entry_families']==1))),
                        selected_R=int(np.count_nonzero((normal['event']!=0)&(normal['entry_families']==2))),
                        local_R_rejections=int(normal['local_phase_rejected'].sum()),
                        quantity=config['quantity'][symbol],derived=config['local_policy']=='ALIGNED')
                    cases[ident]['rows'].append(row);cases[ident]['ledgers'].setdefault(session,{})[symbol]=item
                    delta=DIFFERENCE.contribution(oldmaps[config['base_id']],mapping)
                    deltas.setdefault(ident,{})[symbol]=delta
                    for f in FIELDS:totals[ident][symbol][f]+=delta[f]
                    displayed+=1;del normal
            common.write(HERE/'finance/session_contributions'/f'{session}.json',deltas)
            print(session+'：局所位相12新再生、ALIGNED6保存派生、同量基準6寄与一致',flush=True)
            del packet
        assert finished==792 and displayed==1188 and len(derived_C)==66
        for name,sha in fixed['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
        for item in plan['spec']['data']['input_manifests']:
            assert common.digest(common.ROOT/item['path'])==item['sha256'],item['path']
        for case in cases.values():case['summary']={s:TOTALS.aggregate(case['rows'],s,fixed['sessions']) for s in ('TOPIX','NK225')}
        common.write(HERE/'finance/results.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,cases=cases,
            baselines=baselines,derived_C_comparator=dict(rows=derived_C,id=derivation.C_ID,derived=True),diagnosis=totals,
            account_count=finished,display_account_count=displayed,actual_financial_conditions=12,alias_conditions=6,
            actual_condition_ids=fixed['actual_condition_ids'],alias_condition_ids=fixed['alias_condition_ids'],
            alias_replays=0,baseline_replays=0,derived_C_quantity={'TOPIX':5,'NK225':10},
            derived_C_source_quantity={'TOPIX':10,'NK225':20},original_book_reads=0,current_API_reads=0,actual_orders=0,
            input_cache_reads=33,unknown_sessions=0,elapsed_seconds=time.monotonic()-started,
            alias_definition='ALIGNED全6は既知期間R無候補、旧C_ONLY整数半量の同経済。R反転成功/新独立金融の証拠ではない。'))
    except BaseException as error:
        common.write(HERE/'finance/停止.json',dict(全合格=False,例外=repr(error),完了新口座数=finished,完了表示口座数=displayed,
            時刻=datetime.now(timezone.utc).isoformat()))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='局所位相driver束縛又は根登録後一回金融')
    parser.add_argument('action',choices=('bind','run'));parser.add_argument('--root-finance-approved',action='store_true')
    args=parser.parse_args()
    if args.action=='bind':bind()
    else:assert args.root_finance_approved;run()
