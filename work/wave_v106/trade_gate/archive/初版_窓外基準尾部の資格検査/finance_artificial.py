"""外部新規maskだけを元単一執行へ接続する最小人工。"""

from copy import deepcopy
import json

import numpy as np

import common
import interface
import runner
import votes


FACTORY=common.module('取引更新確認の私有元fixture',common.HERE/'engine/fixture_snapshot.py')


def main() -> None:
    """
    機能: 全拒否・全肯定・scope分離・既待機不変更・料金と次qokを薄い人工で確認する。
    引数: なし。
    返り値: None。正式入力/金融は実行せず、結合証跡と実署名JITの確認だけ保存する。
    """
    counts={};aliases=0
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10
        for side in (1,-1):
            for family,mode in ((1,1),(2,1),(2,2)):
                p,n,cfg=FACTORY.fixture(symbol,side,family,mode)
                if family==2:
                    if mode==2:FACTORY.clearing(p,350,side,n['entry_limit_prices'][330]-side*p['record']['tick'])
                    FACTORY.clearing(p,400,side,n['target_prices'][330])
                baseline=interface.play(p,n,cfg,quantity=q,python=True)
                accepted=np.ones(len(n['event']),bool);reason=np.zeros(len(n['event']),np.int32)
                changed=interface.play(p,n,cfg,quantity=q,python=True,entry_filter=accepted,filter_reason=reason)
                for field in ('orders','trades','curve','target_trace','growth_cohorts','source_curve'):
                    np.testing.assert_array_equal(changed[field],baseline[field])
                row=runner.ACCOUNT.inspect(('人工',symbol),p['record'],changed,n)
                assert row['fees']==sum(o[9] for o in changed['orders']) and len(changed['trades'])==1
                assert all(o[9]==(209 if symbol=='TOPIX' else 110) for o in changed['orders'])
                rejected=interface.play(p,n,cfg,quantity=q,python=True,entry_filter=np.zeros(len(accepted),bool),filter_reason=np.full(len(accepted),201,np.int32))
                assert len(rejected['orders'])==len(rejected['trades'])==0 and np.all(rejected['curve']==0)
                counts['全肯定元経済同値と全拒否新規0及び独立料金']=counts.get('全肯定元経済同値と全拒否新規0及び独立料金',0)+1
                expected=350 if family==2 and mode==2 else 331
                assert int(changed['orders'][0,0])==expected
                counts['市場次quoteと指値初到達を維持']=counts.get('市場次quoteと指値初到達を維持',0)+1
                if family==2 and mode==2:
                    n['range_pending_trend'][350]=True
                    waiting=np.zeros(len(accepted),bool);waiting[330]=True
                    waiting_out=interface.play(p,n,cfg,quantity=q,python=True,entry_filter=waiting,filter_reason=reason)
                    assert int(waiting_out['orders'][0,0])==350
                    runner.ACCOUNT.inspect(('人工',symbol),p['record'],waiting_out,n)
                    counts['公開後gateを再利用せず同rowlivefillを取消より先']=counts.get('公開後gateを再利用せず同rowlivefillを取消より先',0)+1
            # ----------------------------------------
            # 入口のscopeだけを変え、共有単一位置の実C/R数を独立に数える。
            p,n,cfg=FACTORY.fixture(symbol,side,2,1);FACTORY.clearing(p,400,side,n['target_prices'][330])
            FACTORY.add_event(p,n,500,side,1,1)
            f={330:dict(accepted=False,known=True,reason=0,direction_votes=2),500:dict(accepted=False,known=True,reason=0,direction_votes=2)}
            for scope in ('R','C','BOTH'):
                mask,reasons=votes.entry_filter(n,f,scope)
                out=interface.play(p,n,cfg,quantity=q,python=True,entry_filter=mask,filter_reason=reasons)
                actual=out['orders'][out['orders'][:,7]!=0,3].astype(int).tolist()
                assert actual==([0] if scope=='R' else [1] if scope=='C' else [])
                runner.ACCOUNT.inspect(('人工',symbol),p['record'],out,n)
                counts['C_R_scope分離を実親数で確認']=counts.get('C_R_scope分離を実親数で確認',0)+1
            cfg1=dict(cfg,id='人工表示1',baseline_id='同一基準',trade_window_seconds=10,gate_scope='R',minimum_direction_votes=2,minimum_direction_balance=.25)
            cfg2=dict(cfg1,id='人工表示2',trade_window_seconds=30,gate_scope='BOTH')
            yes=np.ones(len(n['event']),bool);zero=np.zeros(len(n['event']),np.int32)
            hash1=runner.execution_fingerprint(p,n,cfg1,yes,zero);hash2=runner.execution_fingerprint(p,n,cfg2,yes,zero)
            assert hash1==hash2
            altered=yes.copy();altered[330]=False
            assert hash1!=runner.execution_fingerprint(p,n,cfg2,altered,zero)
            changed_reason=zero.copy();changed_reason[330]=201
            assert hash1!=runner.execution_fingerprint(p,n,cfg2,yes,changed_reason)
            aliases+=1
            counts['全執行数値と拒否理由同値のみalias']=counts.get('全執行数値と拒否理由同値のみalias',0)+1
    # ----------------------------------------
    # 正式prepared/normal readonly、maskだけwritableという新consumerの署名を一回束縛する。
    p,n,cfg=FACTORY.fixture('TOPIX',1,2,2);FACTORY.clearing(p,350,1,n['entry_limit_prices'][330]-.5);FACTORY.clearing(p,400,1,n['target_prices'][330])
    common.immutable(p);common.immutable(n);mask=np.ones(len(n['event']),bool);reasons=np.zeros(len(mask),np.int32)
    py=interface.play(p,n,cfg,quantity=5,python=True,entry_filter=mask,filter_reason=reasons)
    jit=interface.play(p,n,cfg,quantity=5,python=False,entry_filter=mask,filter_reason=reasons)
    for field in ('orders','trades','curve','source_curve','target_trace'):np.testing.assert_array_equal(py[field],jit[field])
    counts['readonly正式署名のPython_JIT同経済']=1
    proof=dict(全合格=True,人工専用=True,検査件数=counts,source_SHA256=runner.sources(),
        会計四引数source同bytes=common.digest(common.HERE/'engine/accounting.py')==common.digest(common.ROOT/'work/wave_v106/range_price/engine/accounting.py'),
        完成口座の会計を使用=True,未決済prefixへflat会計使用=False,
        全肯定同値は人工比較だけ=True,正式入力読取=0,新金融再生=0,API取得=0,原book読取=0,現在snapshot読取=0)
    common.write(common.HERE/'取引更新maskと単一執行及び料金の結合人工.json',proof)
    print(json.dumps(dict(全合格=True,検査件数=counts),ensure_ascii=False))


if __name__=='__main__':main()
