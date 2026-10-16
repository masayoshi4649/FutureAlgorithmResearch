"""根の登録後だけ、旧GU再利用と四新入口の全feedを一回共有して十六政策を保存する。"""

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
import entry_policy
import interface
import ledger_storage
import plan
import reuse
import sizing_engine
import sizing_baseline
import order_kernel
import exit_core
import storage

FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の数量/出口差','新たな入口の収支')
EXPECTED=Counter(既input一読=33,旧P1台帳一読=66,保存GU再利用=66,新GUengine=264,新政策会計=1056,旧基準経済同値確認=66)


def case_hashes(configs: list[dict]) -> dict:
    """
    機能: 条件名だけで同一と見なさず、各条件の全項目を正規JSON指紋へ結ぶ。
    引数: configs(list[dict]) は結果前固定の条件。
    返り値: dict[str,str] は条件IDとSHA256。NaNや重複IDを拒否する。
    """
    result={}
    for config in configs:
        assert config['id'] not in result
        result[config['id']]=hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True,
            separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()
    return result


def registry_guard(found: list[dict], fixed: dict, prepared_plan: dict) -> None:
    """
    機能: trial・八部品spec・catalog・全sourceの一致を大型入力の前に確認する。
    引数: found(list[dict])、fixed/prepared_plan(dict) は登録候補と正式固定。
    返り値: None。不完全又は別条件の登録では実入力を読まない。
    """
    assert len(found)==1 and found[0]['id']==catalog.TRIAL_ID==prepared_plan['id']
    assert found[0]['spec']==prepared_plan['spec']
    configs=catalog.configs();assert configs==fixed['configs']==prepared_plan['spec']['entry']['conditions']
    assert case_hashes(configs)==fixed['case_SHA256']==case_hashes(found[0]['spec']['entry']['conditions'])
    assert common.sources()==fixed['source_SHA256']==prepared_plan['spec']['implementation']


def source_scope_guard() -> None:
    """
    機能: 数量/注文/高水準JITの所有先が新領域であり旧sourceを実行importしていないことを確認する。
    引数: なし。
    返り値: None。旧module又は旧cacheへ書込む混在を拒否する。
    """
    for module in (common,catalog,data,daily,entry_policy,interface,ledger_storage,plan,reuse,sizing_engine,
                   sizing_baseline,order_kernel,exit_core,storage):
        assert Path(module.__file__).resolve().parent==common.HERE
        for value in vars(module).values():
            if isinstance(value,CPUDispatcher):
                assert Path(value._cache._impl._locator._cache_path).resolve().is_relative_to(common.HERE/'jit')


def baseline_exact(old: dict, current: dict, count: int) -> None:
    """
    機能: 同一保存GUから旧P1を再会計し、全66基準の注文・親・曲線・停止をexact確認する。
    引数: old/current(dict)、count(int) は旧台帳・同値対照・同normal長。
    返り値: None。新GUや旧金融を再実行せず、同値を追加有効性証拠に数えない。
    """
    for field in ('orders','order_uids','order_fees','equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty'):
        before=reuse.expand(old[field],count,field in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty'))
        np.testing.assert_array_equal(current[field],before)
    for field in ('summary','parent','uid_accounts','actual_legs','control'):assert current[field]==old[field],field


def stability(rows: list[dict]) -> dict:
    """
    機能: 同商品場の赤字率・無取引・平均黒字netと最悪赤字を正しい分母で求める。
    引数: rows(list[dict]) は完了場の会計。
    返り値: dict は金額65/赤字20/最悪<=平均黒字の判定。無取引は勝ちに含めない。
    """
    positive=[r['収支'] for r in rows if r['収支']>0];negative=[r['収支'] for r in rows if r['収支']<0]
    active=sum(r['親数']>0 for r in rows);gain=sum(r['利益'] for r in rows);loss=sum(r['損失'] for r in rows)
    share=gain/(gain+loss) if gain+loss else None;mean=float(np.mean(positive)) if positive else None
    worst=max([0.]+[-n for n in negative]);rate=len(negative)/len(rows) if rows else None
    return dict(session_count=len(rows),active_sessions=active,positive_sessions=len(positive),losing_sessions=len(negative),
        no_trade_sessions=len(rows)-active,flat_active_sessions=active-len(positive)-len(negative),
        red_full_rate=rate,red_active_rate=len(negative)/active if active else None,
        profit_share=share,mean_positive_session_net_yen=mean,worst_negative_session_abs_yen=worst,
        target65=share is not None and share>=.65,target_red20=rate is not None and rate<=.2,
        target_worst_mean=mean is not None and worst<=mean,
        all_targets=share is not None and mean is not None and share>=.65 and rate<=.2 and worst<=mean)


def summarize(rows: list[dict], parents: list[dict], sessions: list[str], symbol: str) -> dict:
    """
    機能: 全33・前16・後17・上位三正収支場除外を同商品親netから別集計する。
    引数: rows/parents(list[dict])、sessions(list[str])、symbol(str) は保存実会計と固定場順。
    返り値: dict は期間別金額・枚数・活動。大勝ち除外はpositive session netの上位三だけ。
    """
    own=[r for r in rows if r['symbol']==symbol];ps=[p for p in parents if p['symbol']==symbol]
    assert len(own)==len(sessions) and {r['session'] for r in own}==set(sessions)
    top=sorted((r for r in own if r['収支']>0),key=lambda r:(-r['収支'],r['session']))[:3]
    excluded={r['session'] for r in top};groups={'全33':sessions,'前16':sessions[:16],'後17':sessions[16:],
        '上位3正収支場除外':[s for s in sessions if s not in excluded]};result={}
    for name,scope in groups.items():
        subset=[r for r in own if r['session'] in scope];pp=[p for p in ps if p['session'] in scope]
        aggregate=ledger_storage.aggregate(subset,pp,scope);assert np.isclose(aggregate['収支'],sum(r['収支'] for r in subset),atol=1e-5)
        assert np.isclose(aggregate['利益'],sum(r['利益'] for r in subset),atol=1e-5)
        assert np.isclose(aggregate['損失'],sum(r['損失'] for r in subset),atol=1e-5)
        result[name]=dict(aggregate=aggregate,stability=stability(subset),sessions=scope)
    result['除外場']=[r['session'] for r in top];return result


def directional(parents: list[dict], symbol: str) -> dict:
    """
    機能: 完結親の実新規方向別netを主基準と同じ定義で小集計する。
    引数: parents(list[dict])、symbol(str) は保存親と商品。
    返り値: dict はlong/shortの利益・損失・net・勝負枚数。決済玉とは混同しない。
    """
    result={}
    for name,side in (('long',1),('short',-1)):
        group=[p for p in parents if p['symbol']==symbol and p['方向']==side]
        result[name]=dict(**daily.metric([p['収支'] for p in group]),
            勝ち枚数=sum(p['枚数'] for p in group if p['収支']>0),負け枚数=sum(p['枚数'] for p in group if p['収支']<0),
            枚数=sum(p['枚数'] for p in group),定義='完結親の方向別net正負。内部の決済玉正負とは別。')
    return result


def boundary(output: dict) -> dict:
    """
    機能: 受理固定尺度・純円線・費用後初先着を小JSONへ保存する。
    引数: output(dict) は新実政策会計。
    返り値: dict は旧goal互換anchorと新exit境界。未受理の線はNoneのまま。
    """
    return dict(anchor=output['goal_anchor'],exit_boundary=output['exit_boundary'],停止判断=output['control'],
        目標円=output['exit_boundary']['target_yen'],損失予算円=output['exit_boundary']['hard_loss_yen'],
        新規数量選択予算円=output['exit_boundary']['quantity_selection_budget_yen'],
        保全理由='合成注文96は走査返済。損失/保護の発動内容は停止判断.種別と理由で区別する。')


# ----------------------------------------
def run(registry: Path) -> None:
    """
    機能: 根の登録後、旧GU66と四新GU264を共有し十六政策1056を一回だけ保存する。
    引数: registry(Path) は根が登録した共通試行台帳。
    返り値: None。Falseを保持し自動再開・原板/API/旧金融再生を行わない。
    """
    fixed=data.read(common.HERE/'金融事前固定.json');prepared=data.read(common.HERE/'試行計画.json')
    found=[t for t in data.read(registry)['trials'] if t['id']==catalog.TRIAL_ID]
    registry_guard(found,fixed,prepared);source_scope_guard()
    assert data.digest(common.HERE/'試行計画.json')==fixed['計画SHA256'] and plan.clones()==prepared['同bytesコピー']
    for item in prepared['spec']['data']['input_manifests']:assert data.digest(common.ROOT/item['path'])==item['sha256']
    assert not (common.HERE/'finance').exists() and not (common.HERE/'金融前False.json').exists()
    source=common.sources();configs=fixed['configs'];(common.HERE/'finance').mkdir()
    common.write('finance/開始.json',dict(正式一回=True,source_SHA256=source,case_SHA256=fixed['case_SHA256'],予定=dict(EXPECTED)))
    counts=Counter();started=time.monotonic();rows={c['id']:[] for c in configs};parents={k:[] for k in rows};legs={k:[] for k in rows}
    ledgers={k:[] for k in rows};changes={k:[] for k in rows};boundaries={k:[] for k in rows}
    try:
        for session in fixed['sessions']:
            packet=data.load(fixed['input_cache'][session]);assert packet['session']==session;counts['既input一読']+=1
            for symbol in catalog.QUANTITY:
                account=packet['accounts'][symbol];peer=packet['accounts']['NK225' if symbol=='TOPIX' else 'TOPIX']
                n=len(account['record']['price']);before=data.load(fixed['baseline']['ledgers'][session+'|'+symbol]);counts['旧P1台帳一読']+=1
                assert before['key']==(session,symbol)
                original=reuse.values(before,n);ctx=interface.prepared(session,account,original);counts['保存GU再利用']+=1
                baseline_exact(before,interface.baseline(ctx),n);counts['旧基準経済同値確認']+=1
                gate=entry_policy.mask(account,catalog.BASE_ENTRY);oldgate=reuse.expand(before['gate_accepted'],n,True)
                np.testing.assert_array_equal(gate['accepted'],oldgate)
                for route in catalog.entry_ids():
                    if route!=catalog.BASE_ENTRY:
                        executed=interface.execute(account,route,peer);counts['新GUengine']+=1
                        gate=executed['gate'];ctx=interface.prepared(session,account,executed['values'])
                    for config in (c for c in configs if c['entry_id']==route):
                        cid=config['id'];fresh=interface.apply(ctx,config,gate);counts['新政策会計']+=1
                        difference=ledger_storage.delta(before,fresh)
                        oldparents={p['親']:p for p in before['parent']};newparents={p['親']:p for p in fresh['parent']}
                        turned=[dict(parent=int(p),old_net=oldparents[p]['収支'],new_net=newparents[p]['収支'])
                            for p in oldparents.keys()&newparents.keys() if oldparents[p]['収支']>0 and newparents[p]['収支']<0]
                        changes[cid].append(dict(session=session,symbol=symbol,baseline_id=catalog.BASELINE_ID,**difference,元勝ち親が赤字化=turned))
                        rows[cid].append(fresh['summary']);parents[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent'])
                        legs[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['actual_legs'])
                        boundaries[cid].append(dict(session=session,symbol=symbol,**boundary(fresh)))
                        target=common.HERE/f'finance/ledgers/{cid}/{session}_{symbol}.pkl.gz'
                        compressed=ledger_storage.stored(fresh,n)
                        if fresh['protection_trace'] is not None:
                            compressed['protection_trace']=storage.pack(fresh['protection_trace'])
                            np.testing.assert_array_equal(storage.expand(compressed['protection_trace']),fresh['protection_trace'])
                        data.save(target,compressed);ledgers[cid].append(dict(session=session,symbol=symbol,
                            path=target.relative_to(common.ROOT).as_posix(),SHA256=data.digest(target)))
                        del fresh,compressed
                    if route!=catalog.BASE_ENTRY:del executed
                del before,original,ctx,gate
            del packet;gc.collect();print(session+' 十六政策の実会計完了',flush=True)
        assert counts==EXPECTED and common.sources()==source==fixed['source_SHA256']
        results={};diagnosis={}
        for cid in rows:
            periods={s:summarize(rows[cid],parents[cid],fixed['sessions'],s) for s in catalog.QUANTITY}
            results[cid]=dict(rows=rows[cid],ledgers=ledgers[cid],symbols={s:periods[s]['全33']['aggregate'] for s in catalog.QUANTITY},
                periods=periods,stability={s:periods[s]['全33']['stability'] for s in catalog.QUANTITY},
                directional_symbols={s:directional(parents[cid],s) for s in catalog.QUANTITY},
                actual_leg_symbols={s:dict(**daily.metric([p['収支'] for p in legs[cid] if p['symbol']==s]),
                    定義='実決済玉net正負の副表。主指標は完結親net。') for s in catalog.QUANTITY})
            diagnosis[cid]={s:dict(**{f:sum(d[f] for d in changes[cid] if d['symbol']==s) for f in FIELDS},
                元勝ち親が赤字化=sum(len(d['元勝ち親が赤字化']) for d in changes[cid] if d['symbol']==s)) for s in catalog.QUANTITY}
        common.write('finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,diagnosis=diagnosis,
            各場寄与=changes,boundary=boundaries,初回受理と費用後目標境界=boundaries,counts=dict(counts),
            baseline={k:v for k,v in fixed['baseline'].items() if k!='ledgers'},
            source開始終端一致=True,source_SHA256=source,case_SHA256=fixed['case_SHA256'],
            会計口座数=1056,新GUengine=264,保存GU再利用=66,旧基準経済同値確認=66,
            主評価='完結実親net正負。玉と方向の副表は定義を分離。',原板=0,NPZ=0,API=0,現在入力=0,旧金融再生=0,経過秒=time.monotonic()-started))
    except BaseException:
        common.write('finance/False.json',dict(全合格=False,原因=traceback.format_exc(),counts=dict(counts),source開始SHA256=source,自動再開始=False));raise


def main() -> None:
    """
    機能: 非金融準備と根登録後の唯一正式金融を分離し、失敗後の自動再開始を拒否する。
    引数: CLI --prepare-only/--freeze/--root-trial-registered(bool)、--registry(Path)。
    返り値: None。金融開始は根だけが行う。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-only',action='store_true');group.add_argument('--freeze',action='store_true');group.add_argument('--root-trial-registered',action='store_true')
    parser.add_argument('--registry',type=Path,default=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args=parser.parse_args()
    if args.prepare_only or args.freeze:plan.prepare(formal=args.freeze);return
    try:run(args.registry)
    except BaseException:
        if not (common.HERE/'finance').exists() and not (common.HERE/'金融前False.json').exists():
            common.write('金融前False.json',dict(全合格=False,原因=traceback.format_exc(),金融開始=0,実入力=0,自動再開始=False))
        raise


if __name__=='__main__':main()
