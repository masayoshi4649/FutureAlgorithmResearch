"""正式20源・十八政策・六保存比較と登録接続を、実金融前に独立監査する。"""

from copy import deepcopy
from pathlib import Path
import ast
import hashlib
import json
import sys

import fak_reference as oracle
from fak_core_check_v2 import material


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_improve_20261014/engine'
sys.dont_write_bytecode=True
sys.path.insert(0,str(ENGINE))
import numpy as np
import runner
import interface
import daily


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 正式固定・登録小証跡・独立人工・旧公開会計のみを一読する。
    引数: path(Path) は明示小 JSON。
    返り値: tuple[dict,str] は保存内容と同bytes指紋。金融結果原本は読まない。
    """
    assert '/finance/' not in path.as_posix()
    saved=path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def same(a: object,b: object) -> None:
    """
    機能: 純人工の有限値と固定線を比較する。
    引数: a/b(object) は測定値と独立算術値。
    返り値: None。未知値は同じ None を要求する。
    """
    if b is None:
        assert a is None
    else:
        np.testing.assert_allclose(a,b,atol=1e-5,rtol=1e-12)


def main() -> None:
    """
    機能: 全20署名・8spec・396旧比較・登録guardと新interfaceの受理線を金融前に検査する。
    引数: なし。根のfreeze/register小証跡が揃った時点だけ実行する。
    返り値: None。所有proof又はFalseだけ保存し、入力・台帳・金融・APIは0。
    """
    target=HERE/'正式20源十八政策と六市場保存比較及び登録の独立接続.json'
    failed=HERE/'正式20源の独立接続False.json'
    assert not any(p.exists() for p in (target,failed))
    paths=[ENGINE/'試行計画.json',ENGINE/'金融事前固定.json',
        ENGINE/'十八対照のFAKと登録前拒否及び保存比較の人工検査.json',
        ENGINE.parent/'金融前の照合と登録.json',
        HERE/'署名済みFAK核心11源と純小feed及び旧市場の独立人工_v2.json',
        ROOT/'アルゴリズム調査/00104_E01の銘柄差の原因と修正検証/E01の銘柄差と固定16対照の公開会計.json']
    reads=[read(p) for p in paths];plan,fixed,owner,registered,core,pub=[v for v,h in reads]
    sources=runner.common.sources();counts={}
    try:
        assert plan['正式freeze'] and fixed['全合格'] and owner['全合格'] and registered['全合格'] and core['全合格'] and pub['全合格']
        assert len(sources)==20 and sources==plan['spec']['implementation']==fixed['source_SHA256']==owner['source_SHA256']
        assert reads[2][1]=='c548c154229d837f9e17e663495035deb68ff5d496237b53698bd17baaf52db4'
        assert reads[0][1]==fixed['計画SHA256']==registered['計画SHA256']=='fceefa7d703bbbed8e8a9ac158bf46365544c2d923c3a8777483ed1e056b7472'
        assert plan['id']==registered['登録ID']==runner.catalog.TRIAL_ID=='105_E01公開気配FAK二許容と票強度四条件の十八対照'
        assert registered['状態']=='未実行' and registered['未照合過去あり']
        assert registered['金融']==registered['入力']==registered['API']==0
        assert all(sources[path]==sha for path,sha in core['source_SHA256'].items())
        assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
        assert len(fixed['sessions'])==33 and fixed['sessions']==pub['sessions']
        assert fixed['input_cache']==plan['spec']['data']['input_cache']
        assert len(fixed['input_cache'])==33
        assert fixed['configs']==plan['spec']['entry']['conditions']==runner.catalog.configs()
        assert len(fixed['configs'])==18 and runner.case_hashes(fixed['configs'])==fixed['case_SHA256']
        expected=dict(既input一読=33,旧市場台帳一読=396,保存GU再利用=198,
            新GUengine=594,新政策会計=1188,旧基準経済同値確認=396)
        assert runner.EXPECTED==expected and plan['予定']==dict(新条件=18,**expected)
        assert runner.plan.clones()==plan['同bytesコピー'] and len(plan['同bytesコピー'])==13
        assert fixed['references']==plan['spec']['data']['reference_ledger_manifests']
        assert len(fixed['references'])==len(fixed['reused_results'])==6
        refs=[]
        for key,cid in fixed['reference_mapping'].items():
            gate,profit=key.split('|');assert runner.catalog.OLD_IDS[gate,profit]==cid
            info=fixed['reused_results'][cid];config=info['config'];before=pub['cases'][cid]
            assert config['entry_id']==gate and config['target_id']==profit and config['execution_id']=='MARKET'
            assert info['source_config']==before['config']
            assert len(info['rows'])==len(fixed['references'][cid])==66
            current={(r['session'],r['symbol']):r for r in info['rows']}
            for row in before['rows']:
                actual=current[row['session'],row['symbol']]
                for a,b in (('利益','profit'),('損失','loss'),('収支','net'),('費用','fees'),
                    ('親数','campaigns'),('勝ち親','winning_campaigns'),('負け親','losing_campaigns'),
                    ('勝ち枚数','winning_lots'),('負け枚数','losing_lots')):
                    same(actual[a],row[b])
            assert info['SHA256']==('8959ab1bf2f532e5358c458fc81590b8f88964233b231cb78d48293afd07d0f7'
                if gate=='G25' and profit=='P1' else 'dd52f4401096942c5001b73306a3365759826611f18936192d7ec524c3a48585')
            refs.extend(r['path'] for r in fixed['references'][cid].values())
        assert len(refs)==len(set(refs))==396
        for config in fixed['configs']:
            source=config['baseline_id']
            assert source in fixed['reused_results'] or any(c['id']==source and c['entry_id']=='G50N4' and c['execution_id']=='MARKET' for c in fixed['configs'])
        assert len(runner.catalog.new_gu_routes())==9 and len(set(runner.catalog.new_gu_routes()))==9
        counts['旧小会計行']=396;counts['旧GU再利用予定']=198;counts['新GU予定']=594;counts['政策予定']=1188
        # ----------------------------------------
        # 完成源の登録guardを実行するが、run・data.load・金融登録は呼ばない。
        found=[dict(id=plan['id'],spec=plan['spec'])]
        runner.registry_guard(found,fixed,plan);runner.source_scope_guard()
        variants=[('未登録',[],fixed,plan),('重複登録',found+found,fixed,plan)]
        bad=deepcopy(found);bad[0]['id']='別trial';variants.append(('別trial',bad,fixed,plan))
        bad=deepcopy(found);bad[0]['spec']['management']['アンカー']='後の実fillq';variants.append(('spec差',bad,fixed,plan))
        bad=deepcopy(fixed);bad['configs'][0]['adverse_ticks']=2;variants.append(('catalog差',found,bad,plan))
        bad=deepcopy(fixed);bad['case_SHA256'][fixed['configs'][0]['id']]='0'*64;variants.append(('casehash差',found,bad,plan))
        bad=deepcopy(fixed);bad['source_SHA256'][next(iter(sources))]='0'*64;variants.append(('source差',found,bad,plan))
        rejected=[]
        for label,registered_variant,saved_variant,plan_variant in variants:
            try:runner.registry_guard(registered_variant,saved_variant,plan_variant)
            except AssertionError:rejected.append(label)
            else:raise AssertionError(label)
        assert len(rejected)==7
        # source順序をASTで確認し、未来quoteでgateを拒否する追加ロードが無いことを確かめる。
        source=(ENGINE/'runner.py').read_text(encoding='utf-8');tree=ast.parse(source)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        lines=ast.unparse(fn)
        assert lines.index('registry_guard(')<lines.index('source_scope_guard(')<lines.index("'finance/開始.json'")<lines.index('data.load(')
        loads=[ast.unparse(n) for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='data.load']
        assert len(loads)==2 and set(loads)=={"data.load(fixed['input_cache'][session])","data.load(fixed['references'][refid][key])"}
        assert "for gate_id in ('G25', 'G50', 'G75')" in lines and "for target_id in ('P1', 'ATR25')" in lines
        assert 'reuse.pair(pair[0], pair[1], n)' in lines and 'baseline_exact(before, interface.market_reference(ctx, gate_id, target_id), n)' in lines
        assert "(('G50N4', 'MARKET'),)" in lines and 'interface.execute(account, gate_id, execution_id)' in lines
        assert "new_market[config['baseline_id']]" in lines and "originals[config['baseline_id']]" in lines
        assert "if execution_id == 'MARKET':" in lines and 'new_market[cid] = fresh' in lines
        assert '自動再開始=False' in source and 'finance/False.json' in source and '金融前False.json' in source
        # ----------------------------------------
        # 新interfaceの18線と旧六参照を独立10進の小注文帳簿へつなぐ。
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for kind in ('再参加数量','静観と第一正常が同列','期限と第一正常が同列'):
                    fixture=oracle.fixture(symbol,side,kind);book=oracle.run(fixture,'FAK0');account=material(fixture)
                    orders=np.array([[o['row'],o['source'],o['cid'],o['side'],o['quantity'],o['price'],o['reason'],int(o['new'])] for o in book['orders']],float).reshape(-1,8)
                    uids=np.array([o['uid'] for o in book['orders']],np.int64)
                    base=daily.reconstruct(('純人工',symbol),orders,uids,account['quotes'])
                    event=book['anchor'];anchor=None
                    if event is not None:
                        qty=event['selected_quantity'];mult=runner.catalog.VALUE[symbol]
                        anchor=dict(row=event['row'],raw_seq=int(account['record']['seq'][event['row']]),price_time_s=float(event['row']),
                            parent=event['cid'],quantity=qty,full_quantity=runner.catalog.QUANTITY[symbol],
                            published_atr=event['published_atr'],published_spread=event['published_spread'],
                            atr_yen=qty*event['published_atr']*mult,
                            roundtrip_fee_yen=2*oracle.fee(qty,symbol),spread_fee_yen=qty*event['published_spread']*mult+2*oracle.fee(qty,symbol))
                    ctx=dict(key=('純人工',symbol),anchor=anchor,base=base,quotes=account['quotes'],finish=True)
                    for config in fixed['configs']:
                        lines=interface.calibrate(ctx,config)
                        expected_target=anchor['quantity']*daily.TICK[symbol]*daily.VALUE[symbol] if config['target_id']=='P1' else .25*anchor['atr_yen']
                        same(lines['target_yen'],expected_target);same(lines['hard_loss_yen'],runner.catalog.BUDGET[symbol])
                        counts['最終interface線']=counts.get('最終interface線',0)+1
                    for gate in ('G25','G50','G75'):
                        for profit in ('P1','ATR25'):
                            current=interface.market_reference(ctx,gate,profit)
                            goal=anchor['quantity']*daily.TICK[symbol]*daily.VALUE[symbol] if profit=='P1' else .25*anchor['atr_yen']
                            direct=daily.apply_policy(base,account['quotes'],dict(
                                profit_ticks=goal/(daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]),loss_ticks=2.))
                            assert current['summary']==direct['summary'] and current['control']==direct['control']
                            np.testing.assert_array_equal(current['orders'],direct['orders'])
                            counts['旧六出口純人工']=counts.get('旧六出口純人工',0)+1
                empty=daily.reconstruct(('純人工',symbol),np.empty((0,8)),np.empty(0,np.int64),account['quotes'])
                ctx=dict(key=('純人工',symbol),anchor=None,base=empty,quotes=account['quotes'],finish=True)
                for gate in ('G25','G50','G75'):
                    for profit in ('P1','ATR25'):
                        current=interface.market_reference(ctx,gate,profit)
                        assert current['control']['目標'] is None and not current['control']['発動']
                        assert current['control']['損失予算']==(runner.catalog.BUDGET[symbol] if (gate,profit)==('G25','P1') else None)
                        counts['旧未受理control']=counts.get('旧未受理control',0)+1
        assert sources==runner.common.sources() and not (ENGINE/'finance').exists() and not (ENGINE/'金融前False.json').exists()
        output=dict(全合格=True,source_SHA256=sources,資料SHA256={p.relative_to(ROOT).as_posix():h for p,(v,h) in zip(paths,reads)},
            八部品=sorted(plan['spec']),予定=expected,同bytes13部品=plan['同bytesコピー'],登録拒否反例=rejected,検査=counts,
            留保=['20源と最終interface/driverを今回別に確認。11核心合格だけで全部署名合格とはしていない。',
                '旧198GU/396政策は同値再利用の比較で、新有効性標本396とは数えない。18政策も同じ33価格経路を共有。',
                '過去の不完全試行は未照合の留保を保持。00096の判断価格制限と今回FAK部品の差は別prepared証跡へ記録済み。',
                '最初受理の尺度を未約定後も維持。幅拡大・物理mini/micro到達/部分成立・次気配返済超過は未保証。',
                '金融前登録/全source/一読計画の接続だけで、新18の損益や目標達成をまだ主張しない。'],
            独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            実金融=0,金融結果読取=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,共有又は金融源変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,源=20,登録拒否=7,検査=counts,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=__import__('traceback').format_exc(),source_SHA256=sources,
            検査=counts,金融=0,入力=0,台帳=0,API=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
