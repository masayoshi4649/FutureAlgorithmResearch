"""反対価格票退出だけのOFFを、同bytes旧ON九出力と他の返済条件で確認する。"""

import ast
import copy
from decimal import Decimal, ROUND_FLOOR
import json
import numpy as np
import common
import catalog
import baseline_core
import fixtures
import interface
import plan
import price_votes
import runner

FIELDS=('orders','order_uids','economic_curve','publication_events','exit_judgments','execution_events','actual_origins','geometry_trace')


def arguments(account: dict, features: dict, config: dict, capacity: int=16) -> tuple:
    """
    機能: 同bytes旧ON核心へ新所有人工だけを渡す明示引数を組む。
    引数: account/features/config(dict)、capacity(int) は小人工とbuffer長。
    返り値: tuple は旧simulate引数。旧module/JITへ接続しない。
    """
    r,q=account['record'],account['quotes'];f=features;s=account['symbol'];num,den=catalog.FEE_RATIO[s]
    return (r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid']&np.isfinite(r['time_s']),account['feed'],account['quiet'],account['quiet_force'],
        f['own']['normal'],f['own']['known'],f['own']['count'],f['own']['balance'],f['peer_known'],f['peer_count'],f['peer_balance'],
        r['start'],r['limit'],catalog.CAP[s],r['tick'],catalog.VALUE[s],num,den,
        ('ORIGIN','PULL','BREAK','ADAPTIVE').index(config['reentry_id']),('TARGET','TIGHT_TRAIL','WIDE_TRAIL').index(config['exit_id']),
        config['parent_stop_fraction'],config['parent_target_fraction'],config['arm_fraction'],config['draw_fraction'],config['floor_fraction'],
        config['session_stop_fraction'],config['session_profit_fraction'],config['pull_fraction'],config['recover_fraction'],config['break_fraction'],capacity)


def source_delta() -> dict:
    """
    機能: 新核心差分を末尾boolとreason152のANDだけに限定してASTで確認する。
    引数: なし。
    返り値: dict は差分と同bytes複写。関数説明を経済差へ数えない。
    """
    before=ast.parse((common.HERE/'baseline_core.py').read_text(encoding='utf-8'))
    after=ast.parse((common.HERE/'core.py').read_text(encoding='utf-8'));removed=0
    for tree in (before,after):
        for node in ast.walk(tree):
            if isinstance(node,ast.FunctionDef) and node.body and isinstance(node.body[0],ast.Expr) and isinstance(node.body[0].value,ast.Constant) and isinstance(node.body[0].value.value,str):node.body.pop(0)
    function=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='simulate')
    assert function.args.args[-1].arg=='enable_opposed_price_exit' and function.args.defaults[-1].value is True
    function.args.args.pop();function.args.defaults.pop()
    for node in ast.walk(after):
        if isinstance(node,ast.If) and isinstance(node.test,ast.BoolOp) and isinstance(node.test.op,ast.And):
            if len(node.test.values)==2 and all(isinstance(x,ast.Name) for x in node.test.values) and [x.id for x in node.test.values]==['enable_opposed_price_exit','opposed']:
                node.test=node.test.values[1];removed+=1
    assert removed==1 and ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)
    return dict(末尾bool=1,reason152_AND=1,他経済AST差=0,同bytesコピー=plan.clones())


def other_exits() -> int:
    """
    機能: 反票だけの退出を除き、紙上/stop/利確/保護/場/timerが残る買売反例を確認する。
    引数: なし。
    返り値: int は返済境界数。紙上残量は診断だけで資格に使わない。
    """
    checks=0
    for s in catalog.CAP:
        for side in (1,-1):
            tick=.5 if s=='TOPIX' else 10.
            for kind in ('opposed','paper','stop','target','trail','quiet','limit','scene_loss','scene_profit'):
                packet,c=fixtures.controlled(s,side);a=packet['accounts'][s];f=fixtures.explicit_votes(packet,s,side)
                f['own']['balance'][314:]=-side;f['peer_balance'][314:]=-side
                if kind=='stop':
                    c['parent_stop_fraction']=.0005;a['quotes']['bid'][316:]-=side*5*tick;a['quotes']['ask'][316:]-=side*5*tick
                elif kind=='target':
                    c['parent_target_fraction']=.00002;a['quotes']['bid'][316:]+=side*2*tick;a['quotes']['ask'][316:]+=side*2*tick
                elif kind=='trail':
                    c['exit_id']='TIGHT_TRAIL';c['arm_fraction']=.00002;c['draw_fraction']=.00001;c['floor_fraction']=.000005
                    a['quotes']['bid'][316]+=side*2*tick;a['quotes']['ask'][316]+=side*2*tick
                elif kind=='quiet':a['quiet'][316]=True
                elif kind=='limit':a['feed']=a['feed'][:1]
                elif kind=='scene_loss':
                    c['session_stop_fraction']=.0002;a['quotes']['bid'][316:]-=side*5*tick;a['quotes']['ask'][316:]-=side*5*tick
                elif kind=='scene_profit':
                    c['session_profit_fraction']=.0001;a['quotes']['bid'][316:]+=side*2*tick;a['quotes']['ask'][316:]+=side*2*tick
                off=interface.play(a,f,c,'返済反例',python=True)
                expected={'opposed':151,'paper':151,'stop':141,'target':140,'trail':142,'quiet':92,'limit':93,'scene_loss':161,'scene_profit':162}[kind]
                assert off['orders'][1,6]==expected and not np.any(off['orders'][:,6]==152)
                if kind=='opposed':
                    on=copy.deepcopy(c);on['enable_opposed_price_exit']=True
                    former=interface.play(a,f,on,'ON反例',python=True)
                    assert former['orders'][1,0]==315 and former['orders'][1,6]==152 and off['orders'][1,0]==1101
                checks+=1
            packet,c=fixtures.controlled(s,side);a=packet['accounts'][s];f=fixtures.explicit_votes(packet,s,side);v=5 if s=='TOPIX' else 10
            a['feed']=np.array([a['feed'][0],[314,313,7,-side,1,4000.,2,0,0,0],[1100,1099,7,-side,v-1,4000.,2,0,0,0]])
            f['own']['balance'][314:]=-side;f['peer_balance'][314:]=-side
            output=interface.play(a,f,c,'紙上残量人工',python=True);p=interface.parent_diagnostics(a,f,output)[0]
            assert output['orders'][1,4]==catalog.CAP[s] and p['entry_quantity']==catalog.CAP[s]
            assert p['entry']['約定']['paper_remaining_quantity']==v and p['exits'][0]['判断']['paper_remaining_quantity']==0;checks+=2
    return checks


def driver(source: dict) -> int:
    """
    機能: JSON往復したcase/登録/所有cacheと対照IDを結果未読で確認する。
    引数: source(dict) は全有効依存署名。
    返り値: int は入力前ガードの確認数。
    """
    configs=catalog.configs();proposal=dict(id=catalog.TRIAL_ID,spec=dict(entry=dict(conditions=configs),implementation=source))
    fixed=dict(configs=configs,case_SHA256=plan.case_hashes(configs),source_SHA256=source)
    proposal=json.loads(json.dumps(proposal));fixed=json.loads(json.dumps(fixed));runner.registry_guard([proposal],fixed,proposal)
    runner.source_scope_guard();assert len({c['paired_on_id'] for c in configs})==12 and all(not c['enable_opposed_price_exit'] for c in configs)
    bad=copy.deepcopy(fixed);bad['configs'][0]['enable_opposed_price_exit']=True
    try:runner.registry_guard([proposal],bad,proposal)
    except AssertionError:pass
    else:raise AssertionError('登録ON/OFF差を拒否しない')
    return 5


def run() -> None:
    """
    機能: 旧ON九出力同値、OFF PythonJIT/UID/料/接頭と単独差分を署名する。
    引数: なし。
    返り値: None。新金融/大型入力/旧結果/台帳/APIは読まない。
    """
    source=common.sources();delta=source_delta();arrays=0;accounts=0;prefixes=0
    for s in catalog.CAP:
        for side in (1,-1):
            for path in ('trend','wave','loss'):
                packet=fixtures.fixture(s,side,path);features=price_votes.pair(packet);a=packet['accounts'][s];f=features[s]
                for c in catalog.configs():
                    on=copy.deepcopy(c);on['enable_opposed_price_exit']=True
                    previous=baseline_core.simulate.py_func(*arguments(a,f,c));same=interface.play(a,f,on,'ON人工',python=True,initial_capacity=16)
                    for k,name in enumerate(FIELDS):np.testing.assert_array_equal(previous[k],same[name]);arrays+=1
                    assert int(previous[8])==same['buffer_capacity']
                    py=interface.play(a,f,c,'OFF人工',python=True,initial_capacity=16);jit=interface.play(a,f,c,'OFF人工',python=False,initial_capacity=16);accounts+=1
                    for name in FIELDS:np.testing.assert_array_equal(py[name],jit[name]);arrays+=1
                    assert py['summary']==jit['summary'] and not np.any(py['orders'][:,6]==152)
                    charge=Decimal('41.8' if s=='TOPIX' else '11')
                    assert sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in py['orders'])==py['summary']['費用']
                    profiles=interface.parent_diagnostics(a,f,py)
                    assert len(profiles)==py['summary']['親数'] and sum(p['net_yen'] for p in profiles)==py['summary']['収支']
                    for p in profiles:
                        for event in [p['entry']]+p['exits']:
                            for label in ('判断','約定'):
                                point=event[label];assert point['paper_remaining_quantity']==py['economic_curve'][point['normal_row'],13]
                    for cut in (311,330,380,601,951):
                        pre=fixtures.prefix(packet,s,cut);pf=price_votes.pair(pre)
                        short=interface.play(pre['accounts'][s],pf[s],c,'接頭人工',finish=False,python=True,initial_capacity=16)
                        np.testing.assert_array_equal(short['orders'],py['orders'][py['orders'][:,0]<cut]);arrays+=1
                        np.testing.assert_array_equal(short['economic_curve'],py['economic_curve'][:cut]);arrays+=1;prefixes+=1
    packet=fixtures.fixture();features=price_votes.pair(packet);c=catalog.configs()[9]
    before=interface.play(packet['accounts']['TOPIX'],features['TOPIX'],c,'未来人工',python=True);future=copy.deepcopy(packet)
    for a in future['accounts'].values():
        mask=a['record']['time_s']>=600.;a['record']['price'][mask]+=500.;a['quotes']['bid'][mask]-=100.;a['quotes']['ask'][mask]+=100.;a['quotes']['quote_valid'][mask]=False
    ff=price_votes.pair(future);after=interface.play(future['accounts']['TOPIX'],ff['TOPIX'],c,'未来人工',finish=False,python=True)
    np.testing.assert_array_equal(before['orders'][before['orders'][:,0]<600],after['orders'][after['orders'][:,0]<600]);arrays+=1
    np.testing.assert_array_equal(before['economic_curve'][:600],after['economic_curve'][:600]);arrays+=1
    exits=other_exits();guard=driver(source);assert common.sources()==source
    common.write('反対価格票退出の単独OFFとON同値及び接頭の人工検査.json',dict(全合格=True,source_SHA256=source,
        条件数=12,ON旧核心同値口座=accounts,OFF_PythonJIT口座=accounts,配列照合=arrays,接頭=prefixes,返済境界=exits,driver境界=guard,
        差分=delta,paper残量='同じ観測rowの診断項目のみ。実qty/cap又は資格へ使用しない。',新金融=0,大型入力=0,旧結果本文=0,旧台帳=0,API=0))
    print('反対価格票退出OFF人工合格 '+str(accounts)+'口座/'+str(arrays)+'配列',flush=True)


if __name__=='__main__':run()
