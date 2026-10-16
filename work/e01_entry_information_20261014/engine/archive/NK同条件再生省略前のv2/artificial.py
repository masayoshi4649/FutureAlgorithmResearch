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
        c['session_stop_fraction'],c['session_profit_fraction'],c['pull_fraction'],c['recover_fraction'],c['break_fraction'],capacity,False)


def source_delta() -> dict:
    """
    機能: 核心の経済差分が公開入口maskだけで、他の返済/FAK計算は同ASTと確認する。
    引数: なし。
    返り値: dict は差分の数と同bytes依存。
    """
    before=ast.parse((common.HERE/'baseline_core.py').read_text(encoding='utf-8'));after=ast.parse((common.HERE/'core.py').read_text(encoding='utf-8'))
    for tree in (before,after):
        for node in ast.walk(tree):
            if isinstance(node,ast.FunctionDef) and node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):node.body.pop(0)
    f=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='simulate')
    assert f.args.args[-1].arg=='entry_allowed' and f.args.defaults[-1].value is None;f.args.args.pop();f.args.defaults.pop()
    def gates(tree: ast.AST) -> list:
        """
        機能: reason95を代入する入口分岐だけを抽出する。
        引数: tree(AST) は純source構文木。
        返り値: list は一つの入口分岐。実データを読まない。
        """
        return [n for n in ast.walk(tree) if isinstance(n,ast.If) and any(isinstance(x,ast.Assign) and isinstance(x.value,ast.Constant) and x.value.value==95 for x in n.body)]
    old,new=gates(before),gates(after);assert len(old)==len(new)==1;new[0].test=copy.deepcopy(old[0].test)
    assert ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)
    return dict(公開入口分岐=1,末尾mask引数=1,他経済AST差=0,同bytesコピー=plan.clones())


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
    機能: PRICE保存同値と新volume三入口の全後続/UID/料/接頭を署名する。
    引数: なし。
    返り値: None。原入力/金融本文/台帳/APIは未読。
    """
    source=common.sources();delta=source_delta();arrays=0;old=0;new=0;prefixes=0
    for s in catalog.CAP:
        for side in (1,-1):
            for path in ('trend','wave','loss'):
                packet=attach(fixtures.fixture(s,side,path));f=price_votes.pair(packet)[s];a=packet['accounts'][s]
                for c in catalog.configs():
                    py=interface.play(a,f,c,'情報人工',python=True,initial_capacity=16)
                    if not c['actual_financial']:
                        former=baseline_core.simulate.py_func(*arguments(a,f,c))
                        for k,name in enumerate(FIELDS):np.testing.assert_array_equal(former[k],py[name]);arrays+=1
                        assert int(former[8])==py['buffer_capacity'];old+=1
                    else:
                        jit=interface.play(a,f,c,'情報人工',python=False,initial_capacity=16)
                        for name in FIELDS:np.testing.assert_array_equal(py[name],jit[name]);arrays+=1
                        assert py['summary']==jit['summary'];new+=1
                    charge=Decimal('41.8' if s=='TOPIX' else '11')
                    assert sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in py['orders'])==py['summary']['費用']
                    profiles=interface.parent_diagnostics(a,f,py)
                    assert len(profiles)==py['summary']['親数'] and sum(p['net_yen'] for p in profiles)==py['summary']['収支']
                    for p in profiles:
                        volume=p['published_entry_information']['volume'];assert volume['candidate_raw_seq']==p['entry']['判断']['raw_seq']
                    for cut in (311,380,601,951):
                        pre=fixtures.prefix(packet,s,cut);pf=price_votes.pair(pre)[s]
                        short=interface.play(pre['accounts'][s],pf,c,'情報接頭',finish=False,python=True,initial_capacity=16)
                        np.testing.assert_array_equal(short['orders'],py['orders'][py['orders'][:,0]<cut]);arrays+=1
                        np.testing.assert_array_equal(short['economic_curve'],py['economic_curve'][:cut]);arrays+=1;prefixes+=1
    configs=catalog.configs();proposal=dict(id=catalog.TRIAL_ID,spec=dict(entry=dict(conditions=configs),implementation=source))
    fixed=dict(configs=configs,case_SHA256=plan.case_hashes(configs),source_SHA256=source)
    proposal=json.loads(json.dumps(proposal));fixed=json.loads(json.dumps(fixed));runner.registry_guard([proposal],fixed,proposal);runner.source_scope_guard()
    count=boundaries();assert common.sources()==source
    common.write('原新規の出来高signed票とPRICE保存同値及び接頭の人工検査.json',dict(全合格=True,source_SHA256=source,
        比較条件=12,PRICE旧九出力同値口座=old,volume_PythonJIT人工口座=new,配列照合=arrays,接頭=prefixes,純境界=count,
        差分=delta,金融=0,大型input=0,元金融本文=0,台帳=0,API=0))
    print('入口情報人工合格 PRICE'+str(old)+'/volume'+str(new)+'口座、'+str(arrays)+'配列',flush=True)


def metadata_bind() -> None:
    """
    機能: 初回成功人工を保全し、ORIGIN明示と掲載件数のmetadata差だけを最終源へ束縛する。
    引数: なし。
    返り値: None。経済源/人工本体不変を検査し、経済人工を重複実行しない。
    """
    archive=common.HERE/'archive/ORIGIN明示と掲載件数補足前の人工'
    old=json.loads((archive/'原新規の出来高signed票とPRICE保存同値及び接頭の人工検査.json').read_text(encoding='utf-8'))
    assert old['全合格'];source=common.sources();changes=[]
    for path,sha in source.items():
        name=path.rsplit('/',1)[-1]
        assert data_sha(archive/name)==old['source_SHA256'][path]
        if sha!=old['source_SHA256'][path]:changes.append(name)
    assert sorted(changes)==['artificial.py','plan.py','runner.py']
    before=ast.parse((archive/'artificial.py').read_text(encoding='utf-8'));after=ast.parse((common.HERE/'artificial.py').read_text(encoding='utf-8'))
    old_functions={n.name:ast.dump(n,include_attributes=False) for n in before.body if isinstance(n,ast.FunctionDef)}
    new_functions={n.name:ast.dump(n,include_attributes=False) for n in after.body if isinstance(n,ast.FunctionDef)}
    assert all(new_functions[k]==v for k,v in old_functions.items())
    configs=catalog.configs();assert len(configs)==12 and sum(c['actual_financial'] for c in configs)==9
    assert all(c['reentry_id']=='ORIGIN' for c in configs) and 9*66==594 and 3*66==198 and 594+198==792
    proposal=dict(id=catalog.TRIAL_ID,spec=dict(entry=dict(conditions=configs),implementation=source))
    fixed=dict(configs=configs,case_SHA256=plan.case_hashes(configs),source_SHA256=source)
    runner.registry_guard(json.loads(json.dumps([proposal])),json.loads(json.dumps(fixed)),json.loads(json.dumps(proposal)))
    runner.source_scope_guard()
    old.update(source_SHA256=source,初回成功人工SHA256=data_sha(archive/'原新規の出来高signed票とPRICE保存同値及び接頭の人工検査.json'),
        metadata変更=changes,本版追加経済人工=0,最終接続=dict(全ORIGIN=True,新金融594=True,保存PRICE198=True,掲載792=True),
        初版保全='archive/ORIGIN明示と掲載件数補足前の人工')
    assert common.sources()==source
    common.write('原新規の出来高signed票とPRICE保存同値及び接頭の人工検査_v2.json',old)
    print('metadata最終接続合格。経済再人工0、17源束縛。',flush=True)


def data_sha(path) -> str:
    """
    機能: 所有人工又はsourceの同bytes署名を確認する。
    引数: path(Path) は小人工/source。
    返り値: str はSHA256。大型入力や金融を読まない。
    """
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__=='__main__':
    import sys
    if '--metadata-bind-only' in sys.argv:metadata_bind()
    else:run()
