"""原公開行のsigned出来高代理とPRICE旧同値を、結果未読の小人工で固定する。"""

import ast
import copy
from decimal import Decimal,ROUND_FLOOR
import json
import numpy as np
import common
import catalog
import baseline_core
import entry_gate
import fixtures
import interface
import plan
import price_votes
import runner

FIELDS=('orders','order_uids','economic_curve','publication_events','exit_judgments','execution_events','actual_origins','geometry_trace')


def attach(packet: dict,up_side: int=3,against: int=0,known: bool=True) -> dict:
    """
    機能: 当該公開row/sideに対応する明示出来高代理辞書を小人工へ付ける。
    引数: packet(dict)、up_side/against(int)、known(bool) は人工票と資格。
    返り値: dict は同packet。原NPZ又は既金融から票を再計算しない。
    """
    for a in packet['accounts'].values():
        values={}
        for o in a['feed'][a['feed'][:,7]==1]:
            row=int(o[0]);side=int(o[3]);up,down=(up_side,against) if side>0 else (against,up_side);total=up+down
            values[row]=dict(known=known,reason=0 if known else 8,window_seconds=60,
                up_votes=up if known else None,down_votes=down if known else None,direction_votes=total if known else None,
                balance=side*(up-down)/total if known and total else None,
                candidate_raw_row=int(a['mapping'][row]),candidate_raw_seq=int(a['record']['seq'][row]),
                candidate_price_time_s=float(a['record']['time_s'][row]),underlying_proxy='明示人工。正出来高差と直前BBOの旧代理型。')
        a['trade_features']={'60':values}
    return packet


def arguments(account: dict,f: dict,c: dict,capacity: int=16) -> tuple:
    """
    機能: 109同bytes旧核心へPRICE比較の小人工を渡す。
    引数: account/f/c(dict)、capacity(int) は保存型とbuffer長。
    返り値: tuple は旧109引数。反票退出OFFとORIGINを固定する。
    """
    r,q=account['record'],account['quotes'];s=account['symbol'];num,den=catalog.FEE_RATIO[s]
    return (r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid']&np.isfinite(r['time_s']),account['feed'],account['quiet'],account['quiet_force'],
        f['own']['normal'],f['own']['known'],f['own']['count'],f['own']['balance'],f['peer_known'],f['peer_count'],f['peer_balance'],
        r['start'],r['limit'],catalog.CAP[s],r['tick'],catalog.VALUE[s],num,den,0,('TARGET','TIGHT_TRAIL','WIDE_TRAIL').index(c['exit_id']),
        c['parent_stop_fraction'],c['parent_target_fraction'],c['arm_fraction'],c['draw_fraction'],c['floor_fraction'],
        c['session_stop_fraction'],c['session_profit_fraction'],c['pull_fraction'],c['recover_fraction'],c['break_fraction'],capacity,False,entry_gate.build(account,f,c)['allowed'])


def source_delta() -> dict:
    """
    機能: 110核心との差が任意末尾引数とFAK許容の一枝だけと構文木で確認する。
    引数: なし。
    返り値: dict は差分数と同bytes依存。拒否pub診断と実経済の同値を混同しない。
    """
    before=ast.parse((common.HERE/'baseline_core.py').read_text(encoding='utf-8'));after=ast.parse((common.HERE/'core.py').read_text(encoding='utf-8'))
    for tree in (before,after):
        for node in ast.walk(tree):
            if isinstance(node,ast.FunctionDef) and node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):node.body.pop(0)
    fn=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='simulate')
    assert fn.args.args[-1].arg=='require_strong_price_min2' and fn.args.defaults[-1].value is False
    fn.args.args.pop();fn.args.defaults.pop()
    target=lambda tree:next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='allowance' for t in n.targets))
    target(after).value=copy.deepcopy(target(before).value)
    assert ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)
    return dict(末尾任意引数=1,FAK許容枝=1,他経済AST差=0,同bytesコピー=plan.clones())


def boundaries() -> int:
    """
    機能: 買売signed値、.25/.5等号、未知、原seq、票持越し無しと価格FAK固定を反証する。
    引数: なし。
    返り値: int はpure境界数。基準方向はfeed公開rowで旧判断rowへ戻さない。
    """
    checks=0
    for s in catalog.CAP:
        for side in (1,-1):
            for up,against,known in ((0,0,True),(1,0,True),(2,0,True),(5,3,True),(3,1,True),(1,3,True),(2,0,False)):
                packet=attach(fixtures.fixture(s,side,'trend'),up,against,known);a=packet['accounts'][s];f=price_votes.pair(packet)[s]
                for c in catalog.configs()[::3]:
                    mask=entry_gate.build(a,f,c);volume=a['trade_features']['60'][310]
                    threshold=.5 if c['entry_id']=='VOL_SELECTED' and s=='TOPIX' else .25
                    vok=known and up+against>=2 and (up-against)/(up+against)>=threshold
                    pok=entry_gate.price_ok(f,310,side)
                    expected=pok if c['entry_id']=='PRICE_BOTH' else vok and pok if c['entry_id']=='VOL25_PRICE_BOTH' else vok
                    assert mask['allowed'][310]==expected and not np.any(mask['allowed'][311:]);checks+=2
            packet,c=fixtures.controlled(s,side);packet=attach(packet);a=packet['accounts'][s];f=fixtures.explicit_votes(packet,s,side)
            f['own']['known'][:]=False;f['peer_known'][:]=False
            vol=copy.deepcopy(next(x for x in catalog.configs() if x['entry_id']=='VOL25' and x['exit_id']=='TARGET'))
            vol['parent_stop_fraction']=c['parent_stop_fraction'];vol['parent_target_fraction']=c['parent_target_fraction']
            output=interface.play(a,f,vol,'未知価格窓人工',python=True)
            assert len(output['orders'])==2 and output['publication_events'][0,11]==0;checks+=1
            mixed=copy.deepcopy(vol);mixed['entry_id']='VOL25_PRICE_BOTH'
            assert len(interface.play(a,f,mixed,'価格併用人工',python=True)['orders'])==0;checks+=1
            f['own']['known'][:]=True;f['peer_known'][:]=True
            f['own']['balance'][:]=side;f['peer_balance'][:]=side
            output=interface.play(a,f,vol,'価格強さFAK人工',python=True)
            assert output['publication_events'][0,11]==1;checks+=1
            bad=copy.deepcopy(a);bad['trade_features']['60'][310]['candidate_raw_seq']+=1
            try:entry_gate.build(bad,f,vol)
            except AssertionError:checks+=1
            else:raise AssertionError('原seq不一致を拒否しない')
            # 公開のvolumeを変えず、後row価格票だけを変えても当時採否を変更しない。
            changed=copy.deepcopy(f);changed['own']['balance'][311:]*=-1;changed['peer_balance'][311:]*=-1
            np.testing.assert_array_equal(entry_gate.build(a,f,vol)['allowed'],entry_gate.build(a,changed,vol)['allowed']);checks+=1
    return checks


def run() -> None:
    """
    機能: 任意OFF旧九出力exact、新PythonJIT/接頭と旧六条件の経済同値を固定する。
    引数: なし。
    返り値: None。旧JIT/金融本文/台帳/大型input/APIを使用しない。
    """
    source=common.sources();delta=source_delta();arrays=off_count=active_count=reuse_count=prefixes=0
    fields=tuple(name for name in FIELDS if name!='publication_events')
    for s in catalog.CAP:
        for side in (1,-1):
            for path in ('trend','wave','loss'):
                packet=attach(fixtures.fixture(s,side,path));a=packet['accounts'][s];f=price_votes.pair(packet)[s]
                for c in catalog.configs():
                    previous=baseline_core.simulate.py_func(*arguments(a,f,c))
                    switched_off=interface.core.simulate.py_func(*arguments(a,f,c),False)
                    for i in range(8):np.testing.assert_array_equal(previous[i],switched_off[i]);arrays+=1
                    assert previous[8]==switched_off[8];off_count+=1
                    py=interface.play(a,f,c,'FAK票数人工',python=True,initial_capacity=16)
                    jit=interface.play(a,f,c,'FAK票数人工',python=False,initial_capacity=16)
                    for name in FIELDS:np.testing.assert_array_equal(py[name],jit[name]);arrays+=1
                    assert py['buffer_capacity']==jit['buffer_capacity'] and py['summary']==jit['summary'];active_count+=1
                    if not c['actual_financial']:
                        for name in fields:np.testing.assert_array_equal(previous[FIELDS.index(name)],py[name]);arrays+=1
                        np.testing.assert_array_equal(previous[3][previous[3][:,12]==1],py['publication_events'][py['publication_events'][:,12]==1]);arrays+=1
                        reuse_count+=1
                    for cut in (311,380,601,951):
                        prefix=fixtures.prefix(packet,s,cut);pf=price_votes.pair(prefix)[s]
                        short=interface.play(prefix['accounts'][s],pf,c,'FAK票数接頭',finish=False,python=True,initial_capacity=16)
                        np.testing.assert_array_equal(short['orders'],py['orders'][py['orders'][:,0]<cut]);arrays+=1
                        np.testing.assert_array_equal(short['economic_curve'],py['economic_curve'][:cut]);arrays+=1;prefixes+=1
    checks=boundaries();changed_rejected=0;thin_new=0
    for s in catalog.CAP:
        for side in (1,-1):
            for own_count in (0,1,2,3):
                for peer_count in (0,1,2,3):
                    packet,_=fixtures.controlled(s,side);packet=attach(packet);a=packet['accounts'][s];f=fixtures.explicit_votes(packet,s,side)
                    f['own']['count'][:]=own_count;f['peer_count'][:]=peer_count
                    f['own']['known'][:]=True;f['peer_known'][:]=True
                    f['own']['balance'][:]=side;f['peer_balance'][:]=side
                    for entry_id in ('PRICE_BOTH','VOL_SELECTED','VOL25','VOL25_PRICE_BOTH'):
                        c=next(x for x in catalog.configs() if x['entry_id']==entry_id and x['exit_id']=='TARGET')
                        py=interface.play(a,f,c,'FAK薄票境界',python=True)
                        previous=baseline_core.simulate.py_func(*arguments(a,f,c))
                        assert len(py['publication_events'])==1
                        pub=py['publication_events'][0];expected=int(own_count>=2 and peer_count>=2)
                        assert pub[11]==expected;checks+=1
                        if not c['actual_financial']:
                            assert np.array_equal(previous[0],py['orders']) and np.array_equal(previous[1],py['order_uids'])
                            if expected==0:
                                assert pub[12]==0 and previous[3][0,11]==1;changed_rejected+=1
                        elif expected==0:
                            assert pub[12]==1;thin_new+=1
                            assert py['published_adverse_ticks']==0 if 'published_adverse_ticks' in py else True
    configs=catalog.configs();assert len(configs)==12 and sum(c['actual_financial'] for c in configs)==6
    assert sum(sum(c['actual_financial_by_symbol'].values()) for c in configs)==9
    assert 297+99+396==792 and changed_rejected>0 and thin_new>0
    source=common.sources();proposal=dict(id=catalog.TRIAL_ID,spec=dict(entry=dict(conditions=configs),implementation=source))
    fixed=dict(configs=configs,case_SHA256=plan.case_hashes(configs),source_SHA256=source)
    runner.registry_guard(json.loads(json.dumps([proposal])),json.loads(json.dumps(fixed)),json.loads(json.dumps(proposal)))
    runner.source_scope_guard()
    assert dict(runner.EXPECTED)==dict(既input一読=33,価格票準備口座=66,新account金融=297,内部同値会計再利用=99)
    assert common.sources()==source
    common.write('FAK追随票二以上と保存経済同値及び接頭の人工検査.json',dict(全合格=True,source_SHA256=source,差分=delta,
        比較条件=12,任意OFF旧九出力exact口座=off_count,新PythonJIT口座=active_count,保存六条件の実経済同値口座=reuse_count,
        配列照合=arrays,接頭=prefixes,純境界=checks,拒否pub診断差=changed_rejected,薄票volume入口保持=thin_new,
        保存同値範囲='注文/UID/実曲線/受理pub/返済/実親経済同値。拒否pubの許容表示が異なるため全九出力exactとは呼ばない。',
        金融=0,大型input=0,元金融本文=0,台帳=0,API=0))
    print('FAKmin2人工合格 OFF'+str(off_count)+'/新'+str(active_count)+'/保存経済'+str(reuse_count)+'、'+str(arrays)+'配列',flush=True)


if __name__=='__main__':run()
