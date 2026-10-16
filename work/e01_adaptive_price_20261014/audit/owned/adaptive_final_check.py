"""八適応条件の全23署名・保存比較・登録 guard・実親小射影を金融前に独立確認する。"""

from copy import deepcopy
from pathlib import Path
import ast
import hashlib
import json
import sys
import traceback
import adaptive_reference as oracle
from adaptive_core_check import material

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_adaptive_price_20261014/engine'
sys.dont_write_bytecode=True
sys.path.insert(0,str(ENGINE))
import numpy as np
import runner
import interface
import daily
import parent_diagnostics


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 正式小計画・登録・人工・過去独立小会計だけを各一読する。
    引数: path(Path) は明示した JSON。
    返り値: tuple[dict,str] は保存資料と指紋。金融結果原本・実台帳は開かない。
    """
    assert '/finance/' not in path.as_posix()
    raw=path.read_bytes()
    return json.loads(raw.decode('utf-8-sig')),hashlib.sha256(raw).hexdigest()


def same(actual: object, expected: object) -> None:
    """
    機能: 未定義を保って線・小会計の独立値を照合する。
    引数: actual/expected(object) は保存値と算術値。
    返り値: None。不一致は例外にする。
    """
    if expected is None:assert actual is None
    elif isinstance(expected,dict):
        for key,value in expected.items():same(actual[key],value)
    elif isinstance(expected,(bool,str,list)):assert actual==expected
    else:np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=1e-12)


def main() -> None:
    """
    機能: 根の正式 freeze/register 終端後だけ、全23 source と八部品の接続を確認する。
    引数: なし。凍結後の源を変更せず小人工だけを動かす。
    返り値: None。自所有証跡を保存し、実入力・台帳・金融・API は0。
    """
    target=HERE/'正式23源八適応条件と旧528同値及び登録の独立接続.json'
    failed=HERE/'適応全23源の独立接続False.json'
    assert not target.exists() and not failed.exists()
    paths=[ENGINE/'試行計画.json',ENGINE/'金融事前固定.json',
           ENGINE/'公開支持の許容固定と八政策接続の人工検査_v2.json',
           ENGINE.parent/'金融前の照合と登録.json',
           HERE/'適応価格核心と定数12槽及び公開予約未来保全の独立人工.json',
           ROOT/'work/e01_improve_20261014/audit/owned/十八新条件1188小会計と192期間及びFAK持越しの独立監査.json']
    values=[read(p) for p in paths]
    plan,fixed,owner,registered,core,previous=[v for v,h in values]
    sources=runner.common.sources();counts={}
    try:
        assert all(v['全合格'] for v in (fixed,owner,registered,core,previous))
        assert plan['正式freeze'] and fixed['正式freeze']
        assert len(sources)==23 and sources==plan['spec']['implementation']==fixed['source_SHA256']==owner['source_SHA256']
        assert values[2][1]=='ad08e032342b657ef6e82f198112c8de139b55b6f1565d3efd1958e140ef900d'
        assert values[0][1]==fixed['計画SHA256']==registered['計画SHA256']
        assert plan['id']==registered['登録ID']==runner.catalog.TRIAL_ID=='106_E01公開支持強度による一回FAK許容切替八対照'
        assert registered['状態']=='未実行' and registered['未照合過去あり']
        assert registered['金融']==registered['入力']==registered['API']==0
        assert all(sources[path]==sha for path,sha in core['source_SHA256'].items())
        assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
        assert len(fixed['sessions'])==33 and len(fixed['input_cache'])==33
        assert fixed['input_cache']==plan['spec']['data']['input_cache']
        assert fixed['configs']==runner.catalog.configs()==plan['spec']['entry']['conditions']
        assert len(fixed['configs'])==8 and runner.case_hashes(fixed['configs'])==fixed['case_SHA256']
        expected=dict(既input一読=33,旧固定許容台帳一読=528,保存GU再利用=264,新GUengine=264,新政策会計=528,旧基準経済同値確認=528)
        assert runner.EXPECTED==expected
        assert plan['予定']==dict(新条件=8,**expected,旧保存表示条件=24)
        assert runner.plan.clones()==plan['同bytesコピー'] and len(plan['同bytesコピー'])==14
        assert fixed['references']==plan['spec']['data']['reference_ledger_manifests'] and len(fixed['references'])==8
        assert len(fixed['reused_results'])==24 and len(fixed['reference_mapping'])==8
        assert set(fixed['reused_results'])==set(previous['商品と期間'])
        refs=[]
        for key,cid in fixed['reference_mapping'].items():
            gate,execution,target_id=key.split('|')
            assert runner.catalog.reference_id(gate,execution,target_id)==cid
            ref=fixed['reused_results'][cid]
            assert ref['config']['entry_id']==gate and ref['config']['execution_id']==execution and ref['config']['target_id']==target_id
            assert len(ref['rows'])==len(fixed['references'][cid])==66
            assert ref['SHA256']=='bc50b5db84cb3f9afe329c9966863a302b0b11a8722e050207cc49c1862860b6'
            refs.extend(item['path'] for item in fixed['references'][cid].values())
        assert len(refs)==len(set(refs))==528
        for cid,ref in fixed['reused_results'].items():
            for symbol in ('TOPIX','NK225'):
                for period in ('全33','前16','後17','上位3正収支場除外'):
                    old=previous['商品と期間'][cid][symbol]['期間'][period]
                    same(ref['periods'][symbol][period]['aggregate'],old['金額'])
                    same(ref['periods'][symbol][period]['stability'],old['基準'])
                    counts['保存引用期間商品']=counts.get('保存引用期間商品',0)+1
        for config in fixed['configs']:
            assert config['baseline_id']==config['comparison_ids'][0]
            assert config['comparison_ids']==[runner.catalog.reference_id(config['entry_id'],e,config['target_id']) for e in ('FAK0','FAK1')]
            assert config['strong_balance_threshold'] in (.75,1.) and config['weak_adverse_ticks']==0 and config['strong_adverse_ticks']==1
        assert len(runner.catalog.new_gu_routes())==len(set(runner.catalog.new_gu_routes()))==4
        # ----------------------------------------
        # 登録 guard は金融runを呼ばず、正常登録と七つの壊れた小登録だけで確認する。
        found=[dict(id=plan['id'],spec=plan['spec'])]
        runner.registry_guard(found,fixed,plan);runner.source_scope_guard()
        variants=[('未登録',[],fixed),('重複登録',found+found,fixed)]
        bad=deepcopy(found);bad[0]['id']='別trial';variants.append(('別trial',bad,fixed))
        bad=deepcopy(found);bad[0]['spec']['management']['アンカー']='未来fillから尺度選択';variants.append(('spec差',bad,fixed))
        bad=deepcopy(fixed);bad['configs'][0]['strong_balance_threshold']=.7;variants.append(('catalog差',found,bad))
        bad=deepcopy(fixed);bad['case_SHA256'][fixed['configs'][0]['id']]='0'*64;variants.append(('casehash差',found,bad))
        bad=deepcopy(fixed);bad['source_SHA256'][next(iter(sources))]='0'*64;variants.append(('source差',found,bad))
        rejected=[]
        for label,found_variant,fixed_variant in variants:
            try:runner.registry_guard(found_variant,fixed_variant,plan)
            except AssertionError:rejected.append(label)
            else:raise AssertionError(label)
        assert len(rejected)==7
        text=(ENGINE/'runner.py').read_text(encoding='utf-8');tree=ast.parse(text)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run');body=ast.unparse(fn)
        assert body.index('registry_guard(')<body.index('source_scope_guard(')<body.index("'finance/開始.json'")<body.index('data.load(')
        loads=[ast.unparse(n) for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='data.load']
        assert set(loads)=={"data.load(fixed['input_cache'][session])","data.load(fixed['references'][refid][key])"} and len(loads)==2
        assert 'reuse.pair(pair[0], pair[1], n)' in body and "np.testing.assert_array_equal(pair[0]['fak_events'], pair[1]['fak_events'])" in body
        assert 'baseline_exact(before, same, n)' in body and 'interface.execute(account, gate_id, execution_id)' in body
        assert "for index, refid in enumerate(config['comparison_ids'])" in body
        assert "parent_diagnostics.project(account, same)" in body and 'parent_diagnostics.project(account, fresh)' in body
        assert '自動再開始=False' in text and 'finance/False.json' in text and '金融前False.json' in text
        # ----------------------------------------
        # 最終interfaceを当公開票から純Python実行し、予約値と出口・実親射影を独立帳簿へつなぐ。
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for balances in ((.7,1.),(.75,.5),(1.,.7)):
                    source=oracle.fixture(symbol,side,'再参加数量');account=material(source)
                    for i,balance in zip((1,6),balances):account['trade_features']['60'][i]['balance']=balance
                    for gate_id,execution_id in runner.catalog.new_gu_routes():
                        executed=interface.execute(account,gate_id,execution_id,python=True)
                        expected_allowed={i:int(b>=runner.catalog.STRONG[execution_id]) for i,b in zip((1,6),balances)}
                        book=oracle.run(source,'FAK0',adverse_by_publication=expected_allowed)
                        orders=np.array([[o['row'],o['source'],o['cid'],o['side'],o['quantity'],o['price'],o['reason'],int(o['new'])] for o in book['orders']],float).reshape(-1,8)
                        np.testing.assert_array_equal(executed['values'][0],orders)
                        np.testing.assert_array_equal(executed['values'][5],np.array([o['uid'] for o in book['orders']],np.int64))
                        ctx=interface.prepared('純人工',account,executed['values'])
                        for config in (c for c in fixed['configs'] if c['entry_id']==gate_id and c['execution_id']==execution_id):
                            line=interface.calibrate(ctx,config);anchor=ctx['anchor']
                            target_yen=anchor['quantity']*daily.TICK[symbol]*daily.VALUE[symbol] if config['target_id']=='P1' else .25*anchor['atr_yen']
                            same(line['target_yen'],target_yen);same(line['hard_loss_yen'],runner.catalog.BUDGET[symbol])
                            fresh=interface.apply(ctx,config,executed['gate'],fak_events=executed['fak_events'])
                            projected=parent_diagnostics.project(account,fresh)
                            assert len(projected)==fresh['summary']['親数']
                            for parent in projected:
                                start=parent['entry'];exits=parent['exits'];qty=start['quantity'];mult=runner.catalog.VALUE[symbol]
                                net=parent['side']*(sum(e['price']*e['quantity'] for e in exits)-start['price']*qty)*mult
                                cost=oracle.fee(qty,symbol)+sum(oracle.fee(e['quantity'],symbol) for e in exits)
                                same(parent['net_yen'],net-cost);same(parent['fee_yen'],cost)
                                same(parent['published_adverse_ticks'],expected_allowed[parent['publication_row']])
                                same(parent['published_price_cap'],parent['publication_ask']+source['tick']*parent['published_adverse_ticks'] if parent['side']==1 else parent['publication_bid']-source['tick']*parent['published_adverse_ticks'])
                                assert parent['hindsight_only'] is True and not parent['overlapping_parent_ids']
                                pub=parent['publication_row'];close=exits[-1]['row'];firstrow=start['row']
                                normal=daily.normal_mask(account['quotes']);indices=np.flatnonzero(normal[firstrow:close+1])+firstrow
                                prior=sum(p['収支'] for p in fresh['parent'] if int(p['最終返済行'])<firstrow)
                                local=fresh['liquidation_yen'][indices]-prior
                                same(parent['parent_worst_fee_liquidation_yen'],float(np.min(local)))
                                same(parent['parent_observed_mae_yen'],max(0.,-float(np.min(local))))
                                for order in [start]+exits:
                                    assert order['source_row']<order['row'] and order['source_raw_seq']<order['raw_seq']
                                    same(order['price'],order['ask'] if order['side']==1 else order['bid'])
                                counts['小実親射影']=counts.get('小実親射影',0)+1
                            counts['最終interface八政策接続']=counts.get('最終interface八政策接続',0)+1
        assert runner.common.sources()==sources and not (ENGINE/'finance').exists()
        output=dict(全合格=True,source_SHA256=sources,資料SHA256={p.relative_to(ROOT).as_posix():h for p,(v,h) in zip(paths,values)},
            八部品=sorted(plan['spec']),予定=expected,検査=counts,登録拒否反例=rejected,
            留保=['核心11の合格に加え今回全23源・最終interface/driver・新実親射影を別に確認した。',
                '旧528政策/264GUは保存経済の同値確認で、追加有効性標本ではない。新8も同じ既知33価格経路。',
                '将来極値MAEは事後診断専用。親期間重複時にはNoneを保持し、全玉清算の損失を個別親損失へ流用しない。',
                '公開.75/1.0は既知内探索。強支持が値上がり/値下がりや未知将来の利益を保証することは示していない。',
                '初受理未約定のq/ATR尺度保持・spreadガード無し・観測ラージ気配とmini/micro実板差は不変。',
                '過去の不完全登録の未照合留保を保持。正式金融・input・旧台帳本文をこの監査で開かない。'],
            独立sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            金融=0,金融結果読取=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,source数=23,検査=counts,登録拒否=7,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),source_SHA256=sources,
            検査=counts,金融=0,入力=0,台帳=0,API=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
