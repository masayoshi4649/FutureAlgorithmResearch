"""登録一致を入力前に確認し、初回受理目標四条件を一回だけ再生する。"""

import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np
from numba.core.registry import CPUDispatcher

import common
import catalog
import data
import daily
import engine
import interface
import plan
import storage


FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の数量/出口差','新たな入口の収支')


def case_hashes(configs: list[dict]) -> dict:
    """
    機能: 条件名だけで同一とみなさず、各条件の全項目を正規JSON指紋へ結ぶ。
    引数: configs(list[dict]) は結果前固定の条件一覧。
    返り値: dict[str,str] は条件IDとSHA256。NaNや重複IDを拒否する。
    """
    result={}
    for config in configs:
        assert config['id'] not in result
        saved=json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        result[config['id']]=hashlib.sha256(saved).hexdigest()
    return result


def registry_guard(found: list[dict], fixed: dict, prepared_plan: dict) -> None:
    """
    機能: 新trial・八部品spec・現catalogと条件指紋を大型入力の前に照合する。
    引数: found(list[dict])、fixed/prepared_plan(dict) は登録候補と結果前固定。
    返り値: None。不完全・別条件・旧trialを拒否し、データ読取は行わない。
    """
    assert len(found)==1 and found[0]['id']==catalog.TRIAL_ID==prepared_plan['id']
    assert found[0]['spec']==prepared_plan['spec']
    configs=catalog.configs();assert configs==fixed['configs']==prepared_plan['spec']['entry']['conditions']
    assert case_hashes(configs)==fixed['case_SHA256']==case_hashes(found[0]['spec']['entry']['conditions'])
    assert common.sources()==fixed['source_SHA256']==prepared_plan['spec']['implementation']


def source_scope_guard() -> None:
    """
    機能: 今回の金融部品とNumba保存先が新所有域であることを入力前に確認する。
    引数: なし。
    返り値: None。旧module・旧JITへ金融実行を書き込む混在を拒否する。
    """
    for module in (common,catalog,data,daily,engine,interface,storage):
        assert Path(module.__file__).resolve().parent==common.HERE
        for value in vars(module).values():
            if isinstance(value,CPUDispatcher):
                target=Path(value._cache._impl._locator._cache_path).resolve()
                assert target.is_relative_to(common.HERE/'jit'),target


def boundary(account: dict, output: dict) -> dict:
    """
    機能: 初回受理qと利益・損失の費用後清算境界を小さい診断へ保存する。
    引数: account/output(dict) は同場の商品入力と実政策台帳。
    返り値: dict は目標アンカー・受理時清算・実初回新規・停止の系譜。
    """
    anchor=output['goal_anchor'];new=output['orders'][output['orders'][:,7]==1]
    first=new[0] if len(new) else None
    row=anchor['受理行'];control=output['control']
    return dict(anchor=anchor,受理行の費用後清算円=None if row is None else float(output['sizing_fee_curve'][row,3]),
        実政策初回新規=None if first is None else dict(row=int(first[0]),source_row=int(first[1]),paper_parent=int(first[2]),
            quantity=int(first[4]),price=float(first[5]),raw_seq=int(account['record']['seq'][int(first[0])])),
        目標円=control['目標'],損失予算円=control['損失予算'],停止判断=control,
        定義='受理アンカーと実fillは区別する。未約定取消や後続実数量が違っても目標を交換しない。')


# ----------------------------------------
def run(registry: Path) -> None:
    """
    機能: 根登録後だけGU132を共有し、四政策264と旧数量264の同親寄与を作る。
    引数: registry(Path) は根が登録した試行台帳。
    返り値: None。失敗をFalse保存し、自動再開や旧金融再生を行わない。
    """
    fixed=common.read(common.HERE/'金融事前固定.json');prepared_plan=common.read(common.HERE/'試行計画.json')
    found=[t for t in common.read(registry)['trials'] if t['id']==catalog.TRIAL_ID]
    registry_guard(found,fixed,prepared_plan);source_scope_guard()
    assert common.digest(common.HERE/'試行計画.json')==fixed['計画SHA256']
    assert plan.check_clones()==prepared_plan['同bytesコピー']
    for item in prepared_plan['spec']['data']['input_manifests']:
        assert common.digest(common.ROOT/item['path'])==item['sha256']
    assert not (common.HERE/'finance').exists()
    source_begin=common.sources()
    common.write(common.HERE/'finance/開始.json',dict(正式1回=True,source_SHA256=source_begin,case_SHA256=fixed['case_SHA256'],
        新GUengine=132,新政策会計=264,旧数量台帳一読=264,既input一読=33))
    configs=fixed['configs'];rows={c['id']:[] for c in configs};parents={k:[] for k in rows};legs={k:[] for k in rows}
    ledgers={k:[] for k in rows};changes={k:[] for k in rows};anchors={k:[] for k in rows};counts=Counter();started=time.monotonic()
    try:
        for session in fixed['sessions']:
            packet=data.load(fixed['input_cache'][session]);assert packet['session']==session;counts['既input一読']+=1
            for symbol in catalog.QUANTITY:
                account=packet['accounts'][symbol];key=session+'|'+symbol;n=len(account['record']['price'])
                for mode in ('CONFIRM','VETO'):
                    group=[c for c in configs if c['mode']==mode]
                    values=interface.execute(account,group[0]);counts['新GUengine']+=1
                    for config in group:
                        cid=config['id'];fresh=interface.account_output(session,account,config,values);counts['新政策会計']+=1
                        before=data.load(fixed['comparisons'][cid]['ledgers'][key]);counts['旧数量台帳一読']+=1
                        assert before['key']==fresh['key']
                        difference=storage.delta(before,fresh)
                        oldparents={p['親']:p for p in before['parent']};newparents={p['親']:p for p in fresh['parent']}
                        turned=[dict(parent=int(p),old_net=oldparents[p]['収支'],new_net=newparents[p]['収支'])
                            for p in oldparents.keys()&newparents.keys() if oldparents[p]['収支']>0 and newparents[p]['収支']<0]
                        changes[cid].append(dict(session=session,symbol=symbol,baseline_id=config['baseline_id'],**difference,元勝ち親が赤字化=turned))
                        rows[cid].append(fresh['summary']);parents[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent'])
                        legs[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['actual_legs'])
                        anchors[cid].append(dict(session=session,symbol=symbol,**boundary(account,fresh)))
                        target=common.HERE/f'finance/ledgers/{cid}/{session}_{symbol}.pkl.gz'
                        common.write(target,storage.stored(fresh,n))
                        ledgers[cid].append(dict(session=session,symbol=symbol,path=target.relative_to(common.ROOT).as_posix(),SHA256=common.digest(target)))
                        del before,fresh
                    del values
            del packet;gc.collect();print(session+' 初回受理目標4会計完了',flush=True)
        assert counts==Counter(既input一読=33,新GUengine=132,新政策会計=264,旧数量台帳一読=264)
        assert common.sources()==source_begin==fixed['source_SHA256']
        results={cid:dict(rows=rows[cid],ledgers=ledgers[cid],symbols={s:storage.aggregate([r for r in rows[cid] if r['symbol']==s],
            [p for p in parents[cid] if p['symbol']==s],fixed['sessions']) for s in catalog.QUANTITY},
            actual_leg_symbols={s:dict(実決済玉数=len([p for p in legs[cid] if p['symbol']==s]),
                **daily.metric([p['収支'] for p in legs[cid] if p['symbol']==s]),
                定義='actual_legs net正負。ここだけ親数は実決済玉数。主評価は完結親で不変。') for s in catalog.QUANTITY}) for cid in rows}
        diagnosis={cid:{s:dict(**{f:sum(d[f] for d in changes[cid] if d['symbol']==s) for f in FIELDS},
            元勝ち親が赤字化=sum(len(d['元勝ち親が赤字化']) for d in changes[cid] if d['symbol']==s)) for s in catalog.QUANTITY} for cid in rows}
        common.write(common.HERE/'finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,
            diagnosis=diagnosis,各場寄与=changes,初回受理と費用後目標境界=anchors,counts=dict(counts),
            保存旧代表=fixed['旧fullP1L8参考rows'],参考利用範囲='保存rowsだけ。旧fullP1L8台帳読取・金融再生0。',
            新GUengine=132,新政策会計=264,会計口座数=264,主評価='完結実親net正負。部分実玉は副表。',
            source開始終端一致=True,source_SHA256=source_begin,case_SHA256=fixed['case_SHA256'],
            元paper再計算=0,旧金融再生=0,原板読取=0,NPZ読取=0,現在入力読取=0,API=0,経過秒=time.monotonic()-started))
    except BaseException:
        common.write(common.HERE/'finance/False.json',dict(全合格=False,原因=traceback.format_exc(),自動再開始=False,
            counts=dict(counts),source開始SHA256=source_begin));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze',action='store_true');action.add_argument('--root-trial-registered',action='store_true')
    parser.add_argument('--registry',type=Path,default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args();plan.freeze() if args.freeze else run(args.registry)
