"""根の正式金融終端後、小会計・両比較・全実親射影だけを一読し独立検算する。"""

from collections import Counter
from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import sys
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_adaptive_price_20261014/engine'
HELPER=ROOT/'work/e01_improve_20261014/audit/owned/fak_finance_small_check.py'
spec=importlib.util.spec_from_file_location('旧独立小会計',HELPER)
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
SYMBOLS=helper.SYMBOLS
FIELDS=helper.FIELDS
COUNTS=Counter();helper.COUNTS=COUNTS
same=helper.same
PATHS=(ENGINE/'finance/結果.json',ENGINE/'試行計画.json',ENGINE/'金融事前固定.json',
       HERE/'正式23源八適応条件と旧528同値及び登録の独立接続.json',
       ENGINE.parent/'報告書選定の事前固定.json')
READS={}


def read_once(path: Path) -> dict:
    """
    機能: 根が許可した小結果・計画・固定・選定だけを各一読する。
    引数: path(Path) は予定 PATHS 内の小 JSON。
    返り値: dict は保存資料。packet・実台帳・原板・API は開かない。
    """
    assert path in PATHS and path not in READS
    raw=path.read_bytes();READS[path]=hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def parent_check(parents: list[dict], config: dict, rows: dict, label: str) -> dict:
    """
    機能: 公開票・適応許容・正気配・全返済・注文料・親 net 及び事後MAEの小算術を検算する。
    引数: parents(list[dict]) は全実親、config(dict) は同条件、rows(dict) は66場、label(str) は ID。
    返り値: dict は商品場/親キーの実親。途中清算全曲線や本当の注文到着を再トレースしない。
    """
    mapped={};buckets={key:[] for key in rows};legs={key:[] for key in rows}
    for p in parents:
        key=(p['session'],p['symbol']);pk=key+(p['parent'],)
        assert key in rows and pk not in mapped;mapped[pk]=p;buckets[key].append(p)
        symbol=p['symbol'];mult=1000 if symbol=='TOPIX' else 10;tick=.5 if symbol=='TOPIX' else 10
        cap=5 if symbol=='TOPIX' else 10
        entry=p['entry'];exits=p['exits'];q=entry['quantity']
        assert p['side'] in (-1,1) and type(q) is int and 0<q<=cap
        assert p['actual_entry_quantity']==q and entry['side']==p['side'] and exits
        assert p['published_known'] and p['published_direction_votes']>=config['min_votes']
        assert p['published_balance']>=config['balance_threshold']
        expected_allow=int(p['published_balance']>=config['strong_balance_threshold']) if 'strong_balance_threshold' in config else config['adverse_ticks']
        same(p['published_adverse_ticks'],expected_allow)
        expected_price=p['publication_ask']+tick*expected_allow if p['side']==1 else p['publication_bid']-tick*expected_allow
        same(p['published_price_cap'],expected_price)
        same(p['published_spread'],p['publication_ask']-p['publication_bid'])
        assert p['published_spread']>0 and p['published_atr']>0
        assert p['publication_row']==entry['source_row'] and p['publication_raw_seq']==entry['source_raw_seq']
        same(p['publication_price_time_s'],entry['source_price_time_s'])
        assert p['side']*(entry['price']-expected_price)<=1e-8
        assert sum(e['quantity'] for e in exits)==q
        assert all(e['side']==-p['side'] for e in exits)
        gross=p['side']*math.fsum(e['quantity']*(e['price']-entry['price'])*mult for e in exits)
        costs=helper.fee(q,symbol)+sum(helper.fee(e['quantity'],symbol) for e in exits)
        same(p['fee_yen'],costs);same(p['net_yen'],gross-costs)
        for o in [entry]+exits:
            assert o['row']>o['source_row'] and o['raw_seq']>o['source_raw_seq']
            assert o['price_time_s']>=o['source_price_time_s']
            assert o['ask']>=o['bid']>0
            same(o['price'],o['ask'] if o['side']==1 else o['bid'])
            same(o['fee_yen'],helper.fee(o['quantity'],symbol))
            COUNTS['実親小注文']+=1
        previous_row=entry['row']
        for o in exits:
            assert o['row']>=previous_row;previous_row=o['row']
            legnet=p['side']*o['quantity']*(o['price']-entry['price'])*mult-helper.fee(q,symbol)*o['quantity']/q-helper.fee(o['quantity'],symbol)
            legs[key].append(dict(net=legnet,quantity=o['quantity']))
        assert p['hindsight_only'] and p['observed_normal_rows']>0
        initial=p['side']*q*((entry['bid'] if p['side']==1 else entry['ask'])-entry['price'])*mult-2*helper.fee(q,symbol)
        assert math.isfinite(p['worst_fee_liquidation_yen'])
        if p['overlapping_parent_ids']:
            same(p['parent_worst_fee_liquidation_yen'],None);same(p['parent_observed_mae_yen'],None)
            COUNTS['親MAE未定義']+=1
        else:
            local=p['parent_worst_fee_liquidation_yen']
            assert math.isfinite(local)
            same(local+p['prior_completed_net_yen'],p['worst_fee_liquidation_yen'])
            same(p['parent_observed_mae_yen'],max(0.,-local))
            assert local<=min(initial,p['net_yen'])+1e-5
            COUNTS['事後MAE小保存整合']+=1
        COUNTS['実親小射影']+=1
    for key,group in buckets.items():
        r=rows[key];nets=[p['net_yen'] for p in group]
        same(r['親数'],len(group));same(r['勝ち親'],sum(n>0 for n in nets));same(r['負け親'],sum(n<0 for n in nets));same(r['零親'],sum(n==0 for n in nets))
        same(r['利益'],math.fsum(max(0.,n) for n in nets));same(r['損失'],math.fsum(max(0.,-n) for n in nets))
        same(r['収支'],math.fsum(nets));same(r['費用'],sum(p['fee_yen'] for p in group))
        same(r['新規枚数'],sum(p['actual_entry_quantity'] for p in group))
        same(r['注文件数'],sum(1+len(p['exits']) for p in group))
        for field,sign in (('勝ち枚数',1),('負け枚数',-1),('零枚数',0)):
            expected=sum(l['quantity'] for l in legs[key] if (l['net']>0 if sign==1 else l['net']<0 if sign==-1 else l['net']==0))
            same(r[field],expected,'実決済枚数正負')
    for p in parents:
        key=(p['session'],p['symbol']);first=p['entry']['row'];last=p['exits'][-1]['row']
        others=[o for o in buckets[key] if o['parent']!=p['parent'] and o['entry']['row']<=last and o['exits'][-1]['row']>=first]
        same(sorted(p['overlapping_parent_ids']),sorted(o['parent'] for o in others))
        same(p['prior_completed_net_yen'],math.fsum(o['net_yen'] for o in buckets[key] if o['exits'][-1]['row']<first))
    return mapped


def contributions(new: dict, old: dict, key: tuple) -> dict:
    """
    機能: 同紙上親 ID の新旧小射影から削除・共通・追加の五寄与を再構築する。
    引数: new/old(dict) は全実親、key(tuple[str,str]) は商品場。
    返り値: dict は独立五寄与。事後親削除から新損益を推定する操作ではない。
    """
    a={p[2]:v for p,v in old.items() if p[:2]==key};b={p[2]:v for p,v in new.items() if p[:2]==key}
    removed=a.keys()-b.keys();common=a.keys()&b.keys();added=b.keys()-a.keys()
    return dict(収支変化=math.fsum(v['net_yen'] for v in b.values())-math.fsum(v['net_yen'] for v in a.values()),
        避けた基準損失=math.fsum(-a[p]['net_yen'] for p in removed if a[p]['net_yen']<0),
        失った基準利益=math.fsum(a[p]['net_yen'] for p in removed if a[p]['net_yen']>0),
        **{'共通入口の数量/出口差':math.fsum(b[p]['net_yen']-a[p]['net_yen'] for p in common)},
        新たな入口の収支=math.fsum(b[p]['net_yen'] for p in added))


# ----------------------------------------
def main() -> None:
    """
    機能: 根の terminal0 通知 SHA を引数として、正式結果を一読し新8と保存24を監査する。
    引数: CLI 第1引数(str) は根が通知した結果 SHA256。
    返り値: None。自所有成功/False 証跡だけ保存し経済源を変更しない。
    """
    assert len(sys.argv)==2 and len(sys.argv[1])==64
    expected_sha=sys.argv[1]
    output_path=HERE/'八適応条件528会計と旧24引用及び全実親両寄与の独立監査.json'
    false_path=HERE/'八適応条件小会計の独立監査False.json'
    scope_path=HERE/'八適応条件小会計の独立読取計画.json'
    assert not any(p.exists() for p in (output_path,false_path,scope_path))
    scope_path.write_text(json.dumps(dict(根終端0通知=True,予定結果SHA256=expected_sha,
        小資料各一読=[p.relative_to(ROOT).as_posix() for p in PATHS],予定=dict(新会計=528,保存引用=1584,期間商品集計=256,両比較場=1056),
        留保='事後MAEの保存極値を全正常曲線から再走査しない。物理FAK/mini-micro板補充/受信時計は未測。',
        入力=0,台帳=0,金融再実行=0,原板=0,NPZ=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        result,plan,fixed,preaudit,selection=[read_once(p) for p in PATHS]
        assert READS[PATHS[0]]==expected_sha and result['全合格'] and result['source開始終端一致'] and preaudit['全合格']
        assert READS[PATHS[1]]==fixed['計画SHA256']=='f048201b0e99a8ad20514443169a1fedca769c9b2d53abfedc174af98b780378'
        assert result['source_SHA256']==fixed['source_SHA256']==plan['spec']['implementation']==preaudit['source_SHA256']
        assert len(result['source_SHA256'])==23 and result['case_SHA256']==fixed['case_SHA256']
        for path,sha in result['source_SHA256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
        assert result['configs']==fixed['configs']==plan['spec']['entry']['conditions'] and len(result['configs'])==8
        sessions=result['sessions'];assert sessions==fixed['sessions'] and len(sessions)==33
        assert Counter(s.rsplit('_',1)[-1] for s in sessions)==dict(Day=17,Night=16)
        expected_counts=dict(既input一読=33,旧固定許容台帳一読=528,保存GU再利用=264,新GUengine=264,新政策会計=528,旧基準経済同値確認=528)
        same(result['counts'],expected_counts)
        for key,value in dict(会計口座数=528,新GUengine=264,保存GU再利用=264,旧基準経済同値確認=528,原板=0,NPZ=0,API=0,現在入力=0,旧金融再生=0).items():same(result[key],value)
        assert result['reused_results']==fixed['reused_results'] and len(result['results'])==8 and len(result['reused_results'])==24
        combined=dict(result['reused_results'],**result['results']);rows={};stats={}
        for cid,saved in combined.items():
            rows[cid]=helper.rows_check(saved['rows'],sessions,cid)
            stats[cid]=helper.period_check(saved,sessions,cid)
        assert result['boundary']==result['初回受理と費用後目標境界']
        assert result['diagnosis']==result['comparisons']['FAK0']['diagnosis']
        assert result['各場寄与']==result['comparisons']['FAK0']['各場寄与']
        all_parents={};parent_stats={}
        for collection in ('actual_parent_diagnostics','reused_parent_diagnostics'):
            expected_ids=set(result['results']) if collection.startswith('actual') else set(fixed['references'])
            assert set(result[collection])==expected_ids
            for cid,parents in result[collection].items():
                config=next(c for c in result['configs'] if c['id']==cid) if cid in result['results'] else fixed['reused_results'][cid]['config']
                all_parents[cid]=parent_check(parents,config,rows[cid],cid)
                parent_stats[cid]={}
                for symbol in SYMBOLS:
                    ps=[p for p in parents if p['symbol']==symbol]
                    finite=[p['parent_observed_mae_yen'] for p in ps if p['parent_observed_mae_yen'] is not None]
                    parent_stats[cid][symbol]=dict(親数=len(ps),MAE既知=len(finite),MAE未知=len(ps)-len(finite),
                        最大観測MAE=max(finite) if finite else None,二票親=sum(p['published_direction_votes']==2 for p in ps),
                        許容0親=sum(p['published_adverse_ticks']==0 for p in ps),許容1親=sum(p['published_adverse_ticks']==1 for p in ps),
                        Day親=sum(p['session'].endswith('_Day') for p in ps),Night親=sum(p['session'].endswith('_Night') for p in ps))
        full_pass={s:[] for s in SYMBOLS};trim_pass={s:[] for s in SYMBOLS};diffs={}
        for config in result['configs']:
            cid=config['id'];diffs[cid]={}
            for symbol in SYMBOLS:
                if stats[cid][symbol]['期間']['全33']['基準']['all_targets']:full_pass[symbol].append(cid)
                if stats[cid][symbol]['期間']['上位3正収支場除外']['基準']['all_targets']:trim_pass[symbol].append(cid)
            for execution,index in (('FAK0',0),('FAK1',1)):
                comparison=result['comparisons'][execution];baseline=config['comparison_ids'][index]
                items=comparison['各場寄与'][cid]
                assert len(items)==66 and {(d['session'],d['symbol']) for d in items}==set(rows[cid])
                for d in items:
                    key=(d['session'],d['symbol']);assert d['baseline_id']==baseline
                    calc=contributions(all_parents[cid],all_parents[baseline],key)
                    same(d,calc,'実親から両五寄与')
                    same(d['収支変化'],rows[cid][key]['収支']-rows[baseline][key]['収支'])
                    common=set(all_parents[cid])&set(all_parents[baseline])
                    turns={p[2]:(all_parents[baseline][p]['net_yen'],all_parents[cid][p]['net_yen'])
                           for p in common if p[:2]==key and all_parents[baseline][p]['net_yen']>0 and all_parents[cid][p]['net_yen']<0}
                    same({p['parent']:(p['old_net'],p['new_net']) for p in d['元勝ち親が赤字化']},turns)
                    COUNTS['両比較の親分類再構築場']+=1
                diffs[cid][execution]={}
                for symbol in SYMBOLS:
                    total={f:math.fsum(d[f] for d in items if d['symbol']==symbol) for f in FIELDS}
                    total['元勝ち親が赤字化']=sum(len(d['元勝ち親が赤字化']) for d in items if d['symbol']==symbol)
                    same(comparison['diagnosis'][cid][symbol],total);diffs[cid][execution][symbol]=total
            bs={(b['session'],b['symbol']):b for b in result['boundary'][cid]}
            ds={(d['session'],d['symbol']):d for d in result['fak_diagnosis'][cid]}
            assert len(bs)==len(ds)==66 and set(bs)==set(ds)==set(rows[cid])
            for key,b in bs.items():
                config_first=dict(config);first=ds[key]['first_actual']
                config_first['adverse_ticks']=0 if first is None else all_parents[cid][key+(first['paper_parent'],)]['published_adverse_ticks']
                helper.boundary_check(config_first,b,ds[key],rows[cid][key])
            for symbol in SYMBOLS:
                records=[d for d in ds.values() if d['symbol']==symbol]
                calc={g:{f:sum(r[g][f] for r in records) for f in helper.COUNT_FIELDS} for g in ('GU全試行','実政策判断行以下の試行')}
                calc.update(初受理と実初回差場数=sum(r['first_anchor_to_actual_diff'] for r in records),
                    初受理未約定から後参加への尺度持越し場数=sum(r['carryover_after_unfilled_initial'] for r in records),
                    持越し先の数量差場数=sum(r['carryover_quantity_changed'] for r in records))
                same(result['fak_summary'][cid][symbol],calc)
        act={}
        assert list(result['GU_activity'])==sessions
        for session,accounts in result['GU_activity'].items():
            assert set(accounts)==set(SYMBOLS)
            for symbol,routes in accounts.items():
                assert set(routes)=={'G25|ADAPT75','G25|ADAPT100','G50|ADAPT75','G50|ADAPT100'}
                assert len({v['paper_candidates'] for v in routes.values()})==1
                assert len({v['known_votes'] for v in routes.values()})==1
                for execution in ('ADAPT75','ADAPT100'):
                    assert routes['G50|'+execution]['gate_accepted']<=routes['G25|'+execution]['gate_accepted']
                for route,data in routes.items():
                    assert data['actual_accepted']<=data['gate_accepted']<=data['known_votes']<=data['paper_candidates']
                    assert data['actual_newfills']+data['fak_expired']<=data['actual_accepted']
                    assert sum(data['overlap_patterns'].values())==data['paper_candidates']
                    assert data['flags'].get('実予約受理',0)==data['actual_accepted']
                    for group in ('全33',session.rsplit('_',1)[-1]):
                        box=act.setdefault(route,{}).setdefault(symbol,{}).setdefault(group,
                            dict(sessions=0,**{f:0 for f in helper.ACTIVITY_FIELDS},flags=Counter(),overlap_patterns=Counter()))
                        box['sessions']+=1
                        for f in helper.ACTIVITY_FIELDS:box[f]+=data[f]
                        box['flags'].update(data['flags']);box['overlap_patterns'].update(data['overlap_patterns'])
                    COUNTS['全GU候補診断']+=1
        same(result['GU_activity_summary'],act)
        both=sorted(set(full_pass['TOPIX'])&set(full_pass['NK225']))
        both_trim=sorted(set(trim_pass['TOPIX'])&set(trim_pass['NK225']))
        assert COUNTS['場会計']==2112 and COUNTS['期間商品集計']==256
        assert COUNTS['両比較の親分類再構築場']==1056 and COUNTS['受理出口境界']==528 and COUNTS['全GU候補診断']==264
        output=dict(全合格=True,評価='小会計・実親小算術・比較接続の合格。未知成功や全日利益とは別。',
            正式結果SHA256=expected_sha,小資料一読SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            検査=dict(COUNTS),正式実行数=expected_counts,新8商品別主三基準合格=full_pass,新8両商品主三基準合格=both,
            新8商品別上位3除外三基準合格=trim_pass,新8両商品上位3除外三基準合格=both_trim,
            商品と期間=stats,両比較五寄与=diffs,全実親の票許容とMAE範囲=parent_stats,
            GU候補と昼夜分母=act,報告書選定の金融前固定=selection,
            留保=['旧24引用・528政策再会計・264GU再利用は追加有効性標本ではない。新8は同じ既知33経路の対照。',
                '実親射影から全返済価格/料/net/公開票/許容/capを算術し五寄与を分類した。原packet/台帳を再読してない。',
                'MAEは正常観測清算の事後極値。保存極値を中間全曲線から独立再走査していない。重複親はNone、旧残り16のMAEも未知。',
                '全GU試行は政策停止後suffixを含む。実政策接頭件数と実親勝率・タグ別原因の母数を区別する。',
                '強支持閾値は既知内探索。商品別選定も同既知33内で、将来日成功や板補充の因果を保証しない。',
                '未約定初受理アンカーを維持。物理FAK到着/部分成立/mini-micro板/受信時計は未測。'],
            独立sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            独立小算術helperSHA256=hashlib.sha256(HELPER.read_bytes()).hexdigest(),
            入力=0,台帳=0,金融再実行=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
        output_path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,検査=dict(COUNTS),新8両商品主三基準合格=both,
            商品別主三基準合格=full_pass,SHA256=hashlib.sha256(output_path.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        false_path.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),小資料読取SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            検査=dict(COUNTS),sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),金融再実行=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
