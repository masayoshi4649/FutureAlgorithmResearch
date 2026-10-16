"""根の登録後だけ、公開許容を切り替える四GUを共有し八政策を保存する。"""

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
import sizing_engine_legacy
import order_kernel
import exit_core
import storage
import constant_engine
import parent_diagnostics

FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の数量/出口差','新たな入口の収支')
EXPECTED=Counter(既input一読=33,旧固定許容台帳一読=528,保存GU再利用=264,新GUengine=264,新政策会計=528,旧基準経済同値確認=528)


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
    for module in (common,catalog,data,daily,entry_policy,interface,ledger_storage,plan,reuse,sizing_engine,sizing_engine_legacy,
                   sizing_baseline,order_kernel,exit_core,storage,constant_engine,parent_diagnostics):
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


def activity(account: dict, values: tuple, gate: dict, fak: np.ndarray) -> dict:
    """
    機能: 一次GUの公開候補・重複拒否タグ・受理/約定/FAK失効を昼夜別小資料にする。
    引数: account(dict)、values(tuple)、gate(dict)、fak(ndarray) は当時の全feedとGU出力。
    返り値: dict はGU診断。政策停止後suffixを含むため実政策勝率と呼ばない。
    """
    entries=account['feed'][account['feed'][:,7]==1];sizing=values[9];flags=Counter();overlap=Counter()
    assert len(entries)==len(sizing)
    for order in entries:
        row=int(order[0]);cid=int(order[2]);v=gate['diagnostics'][row]['vote'];e=sizing[(sizing[:,0]==row)&(sizing[:,1]==cid)]
        assert len(e)==1;e=e[0];tags=[]
        if not v['known']:tags.append('票UNKNOWN')
        elif v['direction_votes']<gate['diagnostics'][row]['min_votes']:tags.append('方向票不足')
        elif v['balance']<gate['diagnostics'][row]['threshold']:tags.append('釣合い不足')
        if e[4]==0:tags.append('数量ゼロ')
        if account['quiet'][row] or account['quiet_force'][row] or account['record']['time_s'][row]>=account['record']['limit']:tags.append('予定静観期限')
        proofs=values[8][(values[8][:,0]==row)&(values[8][:,1]==1)&(values[8][:,2]==cid)]
        assert len(proofs)==1
        if proofs[0,17]==94 and (values[7][row,3]+values[7][row,4]>0 or values[7][row,9]>0):tags.append('実保有予約busy')
        if e[15]==0 and not tags:tags.append('その他の継続取消状態')
        if e[15]==1:tags.append('実予約受理')
        for tag in tags:flags[tag]+=1
        overlap['+'.join(tags) if tags else '分類無し']+=1
    return dict(paper_candidates=len(entries),known_votes=sum(v['vote']['known'] for v in gate['diagnostics'].values()),
        gate_accepted=sum(v['accepted'] for v in gate['diagnostics'].values()),actual_accepted=int(np.count_nonzero(sizing[:,15]==1)),
        actual_newfills=int(np.count_nonzero(values[0][:,7]==1)),fak_expired=int(np.count_nonzero((fak[:,1]==2)&(fak[:,13]==0))),
        flags=dict(flags),overlap_patterns=dict(overlap),
        定義='全GU公開候補の重複タグ。単独原因を断定しない。paper票は実親外の将来方向確率を意味しない。')


def fak_diagnosis(account: dict, output: dict) -> dict:
    """
    機能: 初受理未約定後の尺度持越しと、GU全試行/実政策判断接頭を分けて保存する。
    引数: account/output(dict) は一読入力と実政策及びGU診断。
    返り値: dict は初回の当時系譜と段階別件数。将来fillで公開アンカーを選び直さない。
    """
    fak=output['fak_events'];control=output['control'];cut=int(control.get('判断行',len(account['record']['price'])-1))
    def counts(rows: np.ndarray) -> dict:
        """
        機能: 一回FAKの公開/試行/取消を段階コードで数える。
        引数: rows(ndarray) は対象範囲のFAK19列。
        返り値: dict は公開受理・約定・失効・未試行取消の整数件数。
        """
        return dict(公開受理=int(np.count_nonzero((rows[:,1]==1)&(rows[:,15]==1))),
            試行約定=int(np.count_nonzero((rows[:,1]==2)&(rows[:,13]==1))),
            試行失効=int(np.count_nonzero((rows[:,1]==2)&(rows[:,13]==0))),
            未試行取消=int(np.count_nonzero((rows[:,1]==3)|(rows[:,1]==4))))
    new=output['orders'][output['orders'][:,7]==1];first=new[0] if len(new) else None;anchor=output['goal_anchor']
    initial=anchor['受理行'];actual=None;later=False;initial_filled=False
    if anchor['成立']:
        initial_filled=bool(np.any((new[:,1]==initial)&(new[:,2]==anchor['紙上親'])))
    if first is not None:
        row,source=int(first[0]),int(first[1]);cid=int(first[2]);event=output['sizing_events'][(output['sizing_events'][:,0]==source)&(output['sizing_events'][:,1]==cid)]
        assert len(event)==1;event=event[0]
        actual=dict(row=row,source_row=source,paper_parent=cid,quantity=int(first[4]),side=int(first[3]),price=float(first[5]),
            raw_seq=int(account['record']['seq'][row]),publication_raw_seq=int(account['record']['seq'][source]),
            price_time_s=float(account['record']['time_s'][row]),publication_price_time_s=float(account['record']['time_s'][source]),
            published_ATR=float(event[5]),published_spread=float(event[6]),
            publication_bid=float(account['quotes']['bid'][source]),publication_ask=float(account['quotes']['ask'][source]),
            fill_bid=float(account['quotes']['bid'][row]),fill_ask=float(account['quotes']['ask'][row]))
        later=bool(anchor['成立'] and not initial_filled and source!=initial)
    return dict(first_anchor=anchor,first_actual=actual,initial_accepted_actually_filled=initial_filled,
        first_anchor_to_actual_diff=bool(first is not None and initial!=int(first[1])),
        carryover_after_unfilled_initial=later,carryover_quantity_changed=bool(later and actual['quantity']!=anchor['数量']),
        fixed_exit_boundary=output['exit_boundary'],GU全試行=counts(fak),実政策判断行以下の試行=counts(fak[fak[:,0]<=cut]),
        実政策判断行=cut,実政策新規数=len(new),定義='初受理q/ATR/spreadの線を取消後も保持。GU停止後suffixの試行は実政策試行に数えない。')


def activity_summary(records: dict) -> dict:
    """
    機能: 一次GU診断をsession名のDay/Night区分へ同じ分母で合算する。
    引数: records(dict) はsession→symbol→gate執行→候補診断。
    返り値: dict はroute別・商品別の全/昼/夜候補数と重複タグ。実親確率ではない。
    """
    result={};fields=('paper_candidates','known_votes','gate_accepted','actual_accepted','actual_newfills','fak_expired')
    for session,accounts in records.items():
        kind=session.rsplit('_',1)[-1];assert kind in ('Day','Night')
        for symbol,routes in accounts.items():
            for route,values in routes.items():
                box=result.setdefault(route,{}).setdefault(symbol,{})
                for group in ('全33',kind):
                    total=box.setdefault(group,dict(sessions=0,**{f:0 for f in fields},flags={},overlap_patterns={}))
                    total['sessions']+=1
                    for f in fields:total[f]+=values[f]
                    for f in ('flags','overlap_patterns'):
                        for tag,n in values[f].items():total[f][tag]=total[f].get(tag,0)+n
    return result


# ----------------------------------------
def run(registry: Path) -> None:
    """
    機能: 根登録後、固定許容八比較を一読で再利用し新四GUから八政策を一回保存する。
    引数: registry(Path) は根が登録した共通試行台帳。
    返り値: None。失敗を保存し自動再開、旧金融、原板/APIの取得を行わない。
    """
    fixed=data.read(common.HERE/'金融事前固定.json');prepared=data.read(common.HERE/'試行計画.json')
    found=[t for t in data.read(registry)['trials'] if t['id']==catalog.TRIAL_ID]
    registry_guard(found,fixed,prepared);source_scope_guard()
    assert fixed['正式freeze'] and prepared['正式freeze']
    assert data.digest(common.HERE/'試行計画.json')==fixed['計画SHA256'] and plan.clones()==prepared['同bytesコピー']
    for item in prepared['spec']['data']['input_manifests']:assert data.digest(common.ROOT/item['path'])==item['sha256']
    assert not (common.HERE/'finance').exists() and not (common.HERE/'金融前False.json').exists()
    source=common.sources();configs=fixed['configs'];(common.HERE/'finance').mkdir()
    common.write('finance/開始.json',dict(正式一回=True,source_SHA256=source,case_SHA256=fixed['case_SHA256'],予定=dict(EXPECTED)))
    counts=Counter();started=time.monotonic();rows={c['id']:[] for c in configs};parents={k:[] for k in rows};legs={k:[] for k in rows}
    ledgers={k:[] for k in rows};changes={k:[] for k in rows};secondary={k:[] for k in rows}
    boundaries={k:[] for k in rows};fak_diagnostics={k:[] for k in rows};parent_records={k:[] for k in rows};gu_activity={}
    reused_parent_records={cid:[] for cid in fixed['references']}
    try:
        for session in fixed['sessions']:
            packet=data.load(fixed['input_cache'][session]);assert packet['session']==session;counts['既input一読']+=1
            gu_activity[session]={}
            for symbol in catalog.QUANTITY:
                account=packet['accounts'][symbol];n=len(account['record']['price']);key=session+'|'+symbol
                originals={};gu_activity[session][symbol]={}
                for gate_id in catalog.GATES:
                    gate=entry_policy.mask(account,gate_id)
                    for fixed_execution in ('FAK0','FAK1'):
                        pair=[]
                        for target_id in ('P1','ATR25'):
                            refid=fixed['reference_mapping'][gate_id+'|'+fixed_execution+'|'+target_id]
                            before=data.load(fixed['references'][refid][key]);counts['旧固定許容台帳一読']+=1
                            assert before['key']==(session,symbol) and before['case']==fixed['reused_results'][refid]['config']
                            originals[refid]=before;pair.append(before)
                            np.testing.assert_array_equal(gate['accepted'],reuse.expand(before['gate_accepted'],n,True))
                        original=reuse.pair(pair[0],pair[1],n);ctx=interface.prepared(session,account,original);counts['保存GU再利用']+=1
                        np.testing.assert_array_equal(pair[0]['fak_events'],pair[1]['fak_events'])
                        for before in pair:
                            same=interface.apply(ctx,before['case'],gate,fak_events=before['fak_events'])
                            baseline_exact(before,same,n);counts['旧基準経済同値確認']+=1
                            reused_parent_records[before['case']['id']].extend(dict(session=session,symbol=symbol,**v)
                                for v in parent_diagnostics.project(account,same))
                        del ctx,original,pair,same
                for gate_id,execution_id in catalog.new_gu_routes():
                    executed=interface.execute(account,gate_id,execution_id);counts['新GUengine']+=1
                    gate=executed['gate'];ctx=interface.prepared(session,account,executed['values'])
                    gu_activity[session][symbol][gate_id+'|'+execution_id]=activity(account,executed['values'],gate,executed['fak_events'])
                    for config in (c for c in configs if c['entry_id']==gate_id and c['execution_id']==execution_id):
                        cid=config['id'];fresh=interface.apply(ctx,config,gate,fak_events=executed['fak_events']);counts['新政策会計']+=1
                        for index,refid in enumerate(config['comparison_ids']):
                            before=originals[refid];difference=ledger_storage.delta(before,fresh)
                            oldparents={p['親']:p for p in before['parent']};newparents={p['親']:p for p in fresh['parent']}
                            turned=[dict(parent=int(p),old_net=oldparents[p]['収支'],new_net=newparents[p]['収支'])
                                for p in oldparents.keys()&newparents.keys() if oldparents[p]['収支']>0 and newparents[p]['収支']<0]
                            destination=changes if index==0 else secondary
                            destination[cid].append(dict(session=session,symbol=symbol,baseline_id=refid,**difference,元勝ち親が赤字化=turned))
                        rows[cid].append(fresh['summary']);parents[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['parent'])
                        legs[cid].extend(dict(**p,session=session,symbol=symbol) for p in fresh['actual_legs'])
                        boundaries[cid].append(dict(session=session,symbol=symbol,**boundary(fresh)))
                        fak_diagnostics[cid].append(dict(session=session,symbol=symbol,**fak_diagnosis(account,fresh)))
                        parent_records[cid].extend(dict(session=session,symbol=symbol,**v) for v in parent_diagnostics.project(account,fresh))
                        target=common.HERE/f'finance/ledgers/{cid}/{session}_{symbol}.pkl.gz'
                        compressed=ledger_storage.stored(fresh,n)
                        data.save(target,compressed);ledgers[cid].append(dict(session=session,symbol=symbol,
                            path=target.relative_to(common.ROOT).as_posix(),SHA256=data.digest(target)))
                        del fresh,compressed
                    del executed,ctx
                del originals,gate,before
            del packet;gc.collect();print(session+' 八政策の実会計完了',flush=True)
        assert counts==EXPECTED and common.sources()==source==fixed['source_SHA256']
        results={};diagnosis={};diagnosis1={}
        for cid in rows:
            periods={s:summarize(rows[cid],parents[cid],fixed['sessions'],s) for s in catalog.QUANTITY}
            results[cid]=dict(rows=rows[cid],ledgers=ledgers[cid],symbols={s:periods[s]['全33']['aggregate'] for s in catalog.QUANTITY},
                periods=periods,stability={s:periods[s]['全33']['stability'] for s in catalog.QUANTITY},
                directional_symbols={s:directional(parents[cid],s) for s in catalog.QUANTITY},
                actual_leg_symbols={s:dict(**daily.metric([p['収支'] for p in legs[cid] if p['symbol']==s]),
                    定義='実決済玉net正負の副表。主指標は完結親net。') for s in catalog.QUANTITY})
            for collection,destination in ((changes,diagnosis),(secondary,diagnosis1)):
                destination[cid]={s:dict(**{f:sum(d[f] for d in collection[cid] if d['symbol']==s) for f in FIELDS},
                    元勝ち親が赤字化=sum(len(d['元勝ち親が赤字化']) for d in collection[cid] if d['symbol']==s)) for s in catalog.QUANTITY}
        fak_summaries={}
        for cid,records in fak_diagnostics.items():
            fak_summaries[cid]={}
            for symbol in catalog.QUANTITY:
                subset=[r for r in records if r['symbol']==symbol]
                fak_summaries[cid][symbol]=dict(
                    GU全試行={k:sum(r['GU全試行'][k] for r in subset) for k in ('公開受理','試行約定','試行失効','未試行取消')},
                    実政策判断行以下の試行={k:sum(r['実政策判断行以下の試行'][k] for r in subset) for k in ('公開受理','試行約定','試行失効','未試行取消')},
                    初受理と実初回差場数=sum(r['first_anchor_to_actual_diff'] for r in subset),
                    初受理未約定から後参加への尺度持越し場数=sum(r['carryover_after_unfilled_initial'] for r in subset),
                    持越し先の数量差場数=sum(r['carryover_quantity_changed'] for r in subset))
        common.write('finance/結果.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,results=results,
            reused_results=fixed['reused_results'],diagnosis=diagnosis,各場寄与=changes,
            comparisons=dict(FAK0=dict(diagnosis=diagnosis,各場寄与=changes),FAK1=dict(diagnosis=diagnosis1,各場寄与=secondary)),
            boundary=boundaries,初回受理と費用後目標境界=boundaries,counts=dict(counts),
            fak_diagnosis=fak_diagnostics,fak_summary=fak_summaries,GU_activity=gu_activity,GU_activity_summary=activity_summary(gu_activity),
            actual_parent_diagnostics=parent_records,reused_parent_diagnostics=reused_parent_records,
            実親診断定義='実政策完結親のみ。旧比較8も同じ一読範囲で射影し、残り旧16のMAEは未測。最悪清算は事後診断で規則へ不使用。時計は価格代理。',
            source開始終端一致=True,source_SHA256=source,case_SHA256=fixed['case_SHA256'],
            会計口座数=528,新GUengine=264,保存GU再利用=264,旧基準経済同値確認=528,
            主評価='完結実親net正負。旧24保存結果は追加有効性の標本にしない。',原板=0,NPZ=0,API=0,現在入力=0,旧金融再生=0,経過秒=time.monotonic()-started))
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
