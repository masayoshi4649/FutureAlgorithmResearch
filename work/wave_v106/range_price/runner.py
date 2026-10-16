"""登録済みの価格境界反発24条件だけを、一回の全33場再生へ接続する。"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

import catalog
import common
import data
import interface
import selection


HERE=common.HERE
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
TOTALS=common.module('価格境界反発の不変集計',common.ROOT/'work/wave_v102/accounting.py')
DIFFERENCE=common.module('価格境界反発の不変対応分解',common.ROOT/'work/wave_v106/accounting.py')


def save(path: Path, value: object) -> None:
    """
    機能: 根の所有する金融出力を未存在のファイルへ保存する。
    引数: path(Path)、value(object)は所有域の保存先と会計資料。
    返り値: None。元入力や完成結果を上書きしない。
    """
    common.write(path,value)


def stored(output: dict, normal: dict, record: dict) -> dict:
    """
    機能: 物理注文と当時の入口仮説を残し、全行会計は変化行だけへ圧縮する。
    引数: output/normal/record(dict)は執行結果、同原行の選択入力、保存気配。
    返り値: dictは再監査可能な台帳。判定へ将来の結果を渡さない。
    """
    omitted={'curve','source_curve','target_trace','stale_equity'}
    value={key:child for key,child in output.items() if key not in omitted}
    value.update(row_count=len(record['seq']),selection_diagnostics=normal['decisions'])
    for name in ('curve','source_curve','target_trace'):
        array=output[name]
        changes=np.r_[True,np.diff(array)!=0] if array.ndim==1 else np.r_[True,np.any(np.diff(array,axis=0)!=0,axis=1)]
        rows=np.flatnonzero(changes)
        value[name]=dict(rows=rows,values=array[rows])
    return value


def scaled_map(ledger: dict, record: dict) -> dict:
    """
    機能: 完成した全量C対照の同じ約定を、整数半量と料金へ正確に写す。
    引数: ledger/record(dict)は完成C_ONLY台帳と同じ正常価格。
    返り値: dictは5枚又は10枚の取引対応表。新しい金融再生ではない。
    """
    symbol=record['symbol'];quantity=5 if symbol=='TOPIX' else 10
    entry_fee=209 if symbol=='TOPIX' else 110
    for order in ledger['orders']:
        assert int(order[5])==2*quantity and float(order[9])==2*entry_fee
    result=DIFFERENCE.trade_map(ledger,record)
    for value in result.values():
        assert value['quantity']==2*quantity
        value.update(net=value['net']/2,gross=value['gross']/2,quantity=quantity)
    return result


def bind() -> None:
    """
    機能: 金融開始前に根の実行部と独立会計を既固定の八部品へ追加する。
    引数: なし。完成入力、根以外の固定ソース及び独立人工を読む。
    返り値: None。計画の条件は変更せず、登録待機の指紋を更新する。
    """
    plan=common.read(HERE/'試行計画.json');fixed=common.read(HERE/'事前固定.json')
    assert fixed['新金融再生']==0 and fixed['configs']==catalog.catalog()
    trials=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    assert not any(trial['id']==catalog.TRIAL_ID for trial in trials),'登録後の再束縛はできません'
    mutable={path.relative_to(common.ROOT).as_posix() for path in (HERE/'runner.py',HERE/'engine/accounting.py',HERE/'engine/accounting_artificial.py')}
    for name,sha in fixed['source_SHA256'].items():
        if name not in mutable:assert common.digest(common.ROOT/name)==sha,name
    paths=[HERE/'runner.py',HERE/'engine/accounting.py',HERE/'engine/accounting_artificial.py',HERE/'engine/accounting_guard_artificial.py',common.ROOT/'work/wave_v102/accounting.py',common.ROOT/'work/wave_v106/accounting.py']
    for path in paths:
        fixed['source_SHA256'][path.relative_to(common.ROOT).as_posix()]=common.digest(path)
    for filename in ('市場と初指値到達及び全行会計の人工検査.json','四引数会計の同原行と待機取消拒否人工.json'):
        proof_path=HERE/'engine'/filename
        proof=common.read(proof_path);assert proof['全合格'] and proof['新金融再生']==0
        for name,sha in proof['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
        proof_name=proof_path.relative_to(common.ROOT).as_posix()
        plan['evidence']=[item for item in plan['evidence'] if item['path']!=proof_name]+[dict(path=proof_name,sha256=common.digest(proof_path))]
    baseline=common.ROOT/'work/wave_v106/regime_price/finance/results.json'
    baseline_name=baseline.relative_to(common.ROOT).as_posix()
    manifests=plan['spec']['data']['input_manifests']
    plan['spec']['data']['input_manifests']=[item for item in manifests if item['path']!=baseline_name]+[dict(path=baseline_name,sha256=common.digest(baseline))]
    plan['spec']['allocation']['C_ONLY_comparison']='完成C_ONLYの同じ約定を整数半量へ派生。片道料金はTOP418→209円、NK220→110円。新規と返済双方へ適用し、金融再生を増やさない。'
    plan['spec']['implementation']=fixed['source_SHA256']
    plan['状態']='根の実行部と指値到達の独立会計を固定。登録完了前の正式金融は0。'
    path=HERE/'試行計画.json'
    path.write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    fixed.update(plan_SHA256=common.digest(path),runner_bound=True,bound_at=datetime.now(timezone.utc).isoformat())
    (HERE/'事前固定.json').write_text(json.dumps(fixed,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print('固定24条件へ根実行部と会計を接続しました。正式金融は0です。',flush=True)


def run() -> None:
    """
    機能: 正式登録済み24条件を同33入力で一度だけ再生し、源と変更寄与を保存する。
    引数: なし。根の明示フラグと試行登録及び指紋不変を要求する。
    返り値: None。元板、過去の金融、API、実注文は再実行しない。
    """
    fixed=common.read(HERE/'事前固定.json');assert fixed['全合格'] and fixed['runner_bound']
    plan_path=HERE/'試行計画.json';assert common.digest(plan_path)==fixed['plan_SHA256']
    for name,sha in fixed['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    registry=common.read(common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    registered=[trial for trial in registry if trial['id']==catalog.TRIAL_ID]
    plan=common.read(plan_path)
    assert len(registered)==1 and registered[0]['spec']==plan['spec'],'現在の仕様と登録した八部品が異なります'
    assert not (HERE/'finance/results.json').exists() and not (HERE/'finance/開始.json').exists()
    account=interface.module('価格境界反発の独立物理会計',HERE/'engine/accounting.py')
    prior_path=common.ROOT/'work/wave_v106/regime_price/finance/results.json'
    assert any(item['path']==prior_path.relative_to(common.ROOT).as_posix() and item['sha256']==common.digest(prior_path) for item in plan['spec']['data']['input_manifests'])
    prior=common.read(prior_path);assert prior['全合格']
    cases={config['id']:dict(rows=[],ledgers={}) for config in fixed['configs']}
    comparator={str(er):dict(rows=[],derived=True) for er in (.2,.4)}
    totals={config['id']:{s:{key:0. for key in FIELDS} for s in ('TOPIX','NK225')} for config in fixed['configs']}
    save(HERE/'finance/開始.json',dict(全合格=True,trial_id=catalog.TRIAL_ID,時刻=datetime.now(timezone.utc).isoformat(),条件数=24,対象口座数=1584))
    started=time.monotonic();finished=0
    try:
        for session in fixed['sessions']:
            packet=data.load_session(session);differences={}
            for symbol in ('TOPIX','NK225'):
                prepared=packet['prepared'][symbol];record=prepared['record'];baselines={};memo={}
                for er in (.2,.4):
                    ident=f'C_ONLY_B2_ER{int(er*100)}_B4'
                    item=prior['cases'][ident]['ledgers'][session][symbol]
                    old=common.unpack(item);baselines[str(er)]=scaled_map(old,record)
                    parent_rows=[row for row in prior['cases'][ident]['rows'] if row['session']==session and row['symbol']==symbol]
                    assert len(parent_rows)==1
                    original=parent_rows[0]
                    baseline={key:original[key] for key in ('session','symbol','campaigns','winning_campaigns','losing_campaigns','flat_campaigns')}
                    for key in ('profit','loss','net','gross','fees','winning_lots','losing_lots','flat_lots','lots','equity_peak','equity_trough','equity_drawdown'):
                        baseline[key]=original[key]/2
                    baseline.update(derived=True,quantity=5 if symbol=='TOPIX' else 10)
                    comparator[str(er)]['rows'].append(baseline)
                    del old
                for config in fixed['configs']:
                    normal=selection.build(packet,symbol,config)
                    output=interface.play(prepared,normal,config,quantity=config['quantity'][symbol])
                    row=account.inspect((session,symbol),record,output,normal)
                    row.update(selected_C=int(np.count_nonzero(normal['entry_families']==1)),selected_R=int(np.count_nonzero(normal['entry_families']==2)))
                    cases[config['id']]['rows'].append(row)
                    path=HERE/'finance/ledger'/config['id']/f'{session}_{symbol}.pkl.gz'
                    save(path,stored(output,normal,record))
                    cases[config['id']]['ledgers'].setdefault(session,{})[symbol]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path))
                    mapping=DIFFERENCE.trade_map(output,record);memo[config['id']]=mapping
                    delta=DIFFERENCE.contribution(baselines[str(config['range_er'])],mapping)
                    differences.setdefault(config['id'],{})[symbol]=delta
                    for key in FIELDS:totals[config['id']][symbol][key]+=delta[key]
                    finished+=1
                    del output,normal
                for config in fixed['configs']:
                    if config['mode']=='AUTO':
                        other=config['id'].replace('AUTO_','R_ONLY_',1)
                        differences[config['id']][symbol]['AUTO対R_ONLY']=DIFFERENCE.contribution(memo[other],memo[config['id']])
            save(HERE/'finance/session_contributions'/f'{session}.json',differences)
            print(session+'：価格境界反発24条件、同数量C対照、全行会計と寄与一致',flush=True)
            del packet
        for name,sha in fixed['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
        assert finished==1584
        for case in cases.values():case['summary']={s:TOTALS.aggregate(case['rows'],s,fixed['sessions']) for s in ('TOPIX','NK225')}
        # ----------------------------------------
        # 半量C対照は保存注文の派生であり、独立の金融成功数へ加えない。
        save(HERE/'finance/results.json',dict(全合格=True,sessions=fixed['sessions'],configs=fixed['configs'],cases=cases,
            derived_C_comparators=comparator,diagnosis=totals,account_count=finished,actual_financial_conditions=24,
            baseline_replays=0,original_book_reads=0,current_API_reads=0,actual_orders=0,unknown_sessions=0,
            elapsed_seconds=time.monotonic()-started))
    except BaseException as error:
        save(HERE/'finance/停止.json',dict(全合格=False,例外=repr(error),完了口座数=finished,時刻=datetime.now(timezone.utc).isoformat()))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='価格境界反発の実行部固定又は登録後一回金融')
    parser.add_argument('action',choices=('bind','run'));parser.add_argument('--root-finance-approved',action='store_true')
    args=parser.parse_args()
    if args.action=='bind':bind()
    else:assert args.root_finance_approved;run()
