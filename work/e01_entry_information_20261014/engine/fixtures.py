"""十二保護再参加を小人工で検査し、価格票・影/実親・料金・接頭を分離する。"""

import copy
from decimal import Decimal,ROUND_FLOOR
import numpy as np
import common
import catalog
import price_votes
import interface
import runner
import plan
import json
import importlib.util


def fixture(symbol: str='TOPIX', side: int=1, path: str='wave', n: int=1201) -> dict:
    """
    機能: 二商品価格時計と長く活動する一paper親を持つ小口座を作る。
    引数: symbol(str)、side(int)、path(str)、n(int) は商品・反射方向・人工推移・長さ。
    返り値: dict は人工二市場packet。原入力/金融結果を読まない。
    """
    packet={'session':'人工','accounts':{}}
    for s in catalog.CAP:
        tick=.5 if s=='TOPIX' else 10.;base=4000. if s=='TOPIX' else 65000.;times=np.arange(n,dtype=float)
        if s!=symbol:times-=.5
        move=np.floor(np.arange(n)/5.)
        if path=='wave':
            for i in range(300,n):
                cycle,phase=divmod(i-300,120)
                level=phase//5 if phase<80 else 16-(phase-80)//5 if phase<110 else 10+(phase-110)//5
                move[i]=60+cycle*12+level
        elif path=='loss':move[311:]=move[310]-np.floor(np.arange(n-311)/3.)
        bid=base+side*move*tick;ask=bid+tick
        price=bid+.5*tick
        seq=np.arange(n,dtype=np.int64)*2+1
        feed=np.zeros((2,10));v=5 if s=='TOPIX' else 10
        feed[0]=[310,309,7,side,v,price[310],20,1,0,4*tick]
        feed[1]=[n-101,n-102,7,-side,v,price[n-101],2,0,0,0]
        account=dict(symbol=s,record=dict(price=price,seq=seq,time_s=times,start=0.,end=float(n-1),limit=float(n-1),tick=tick),
            quotes=dict(bid=bid,ask=ask,quote_valid=np.ones(n,bool),seq=seq,time_s=times),feed=feed,
            quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),mapping=np.arange(n,dtype=np.int64)*2)
        packet['accounts'][s]=account
    return packet


def prefix(packet: dict, own_symbol: str, cut: int) -> dict:
    """
    機能: 自己normal行と相手価格時計境界を切り、既知limitは未来清算へ変更しない。
    引数: packet(dict)、own_symbol(str)、cut(int) は人工二市場と自己接頭。
    返り値: dict は同時刻以後のpeerを含まない接頭素材。受信順の再現ではない。
    """
    out=copy.deepcopy(packet);clock=packet['accounts'][own_symbol]['record']['time_s'][cut-1]
    for s,a in out['accounts'].items():
        count=cut if s==own_symbol else int(np.searchsorted(a['record']['time_s'],clock,side='right'))
        for part in ('record','quotes'):
            for key,value in list(a[part].items()):
                if isinstance(value,np.ndarray):a[part][key]=value[:count]
        a['feed']=a['feed'][a['feed'][:,0]<count]
        for key in ('quiet','quiet_force','mapping'):a[key]=a[key][:count]
    return out


def controlled(symbol: str='TOPIX', side: int=1, mode: str='ORIGIN') -> tuple:
    """
    機能: 正常Last形状と窓票を別に操作できる、小さい予約境界専用の人工を作る。
    引数: symbol(str)、side(int)、mode(str) は商品・買売・再参加方式。
    返り値: tuple はpacket/config。票を明示人工へ置換し、原素材を読まない。
    """
    packet=fixture(symbol,side,'trend')
    for s,a in packet['accounts'].items():
        base=4000. if s=='TOPIX' else 65000.;tick=a['record']['tick']
        a['record']['price'][:]=base
        a['quotes']['bid'][:]=base;a['quotes']['ask'][:]=base+tick
        a['feed'][0,5]=base
    config=copy.deepcopy(next(c for c in catalog.configs() if c['reentry_id']==mode and c['exit_id']=='TARGET'))
    config['parent_stop_fraction']=1.;config['parent_target_fraction']=1.
    config['session_stop_fraction']=1e6;config['session_profit_fraction']=1e6
    return packet,config


def explicit_votes(packet: dict, symbol: str, side: int=1) -> dict:
    """
    機能: 状態機械反例だけの現在票を明示し、normalLast資格は本物の測定へ残す。
    引数: packet(dict)、symbol(str)、side(int) は小人工と支持方向。
    返り値: dict は全行既知二票の人工特徴。価格票数式の検査とは分ける。
    """
    feature=price_votes.pair(packet)[symbol]
    feature['own']['known'][:]=True;feature['own']['count'][:]=2;feature['own']['balance'][:]=side
    feature['peer_known'][:]=True;feature['peer_count'][:]=2;feature['peer_balance'][:]=side
    return feature


def vote_boundaries() -> int:
    """
    機能: 60秒の基準/票対象、自己当行、peer厳密過去と欠測境界を逐次数式で確認する。
    引数: なし。
    返り値: int は照合件数。実input又は旧台帳は読まない。
    """
    packet=fixture(n=701);checks=0
    a=packet['accounts']['TOPIX'];a['record']['price'][:]=4000.
    a['record']['price'][60:]=4000.5;a['record']['price'][61:]=4001.
    a['record']['price'][120:]=4000.5;a['record']['price'][121:]=4001.
    measured=price_votes.measure(a)
    assert not measured['known'][59] and measured['known'][60]
    assert measured['reference_row'][120]==60 and measured['count'][120]==2 and measured['balance'][120]==0.
    assert measured['reference_row'][121]==61 and measured['count'][121]==2 and measured['balance'][121]==0.;checks+=6
    # ----------------------------------------
    # 同時計の後行更新は、先行の自己票へ遡及しない。
    a['record']['time_s'][122]=121.;a['quotes']['time_s'][122]=121.;a['record']['price'][122]=4000.
    same=price_votes.measure(a)
    assert same['count'][121]==measured['count'][121] and same['count'][122]==3;checks+=2
    for symbol,account in packet['accounts'].items():
        measured=price_votes.measure(account);valid=np.flatnonzero(measured['normal'])
        for row in valid:
            end=account['record']['time_s'][row];past=valid[(valid<=row)&(account['record']['time_s'][valid]<=end-60.)]
            if len(past)==0:assert not measured['known'][row]
            else:
                base=int(past[-1]);rows=valid[(valid>base)&(valid<=row)]
                previous=np.r_[base,rows[:-1]];delta=account['record']['price'][rows]-account['record']['price'][previous]
                assert measured['reference_row'][row]==base
                assert measured['up'][row]==np.sum(delta>0) and measured['down'][row]==np.sum(delta<0)
            checks+=1
    pair=price_votes.pair(packet)
    for s,feature in pair.items():
        own=packet['accounts'][s];p='NK225' if s=='TOPIX' else 'TOPIX';peer=packet['accounts'][p]
        rows=np.flatnonzero(price_votes.normal(peer))
        for row in np.flatnonzero(feature['own']['normal']):
            eligible=rows[peer['record']['time_s'][rows]<own['record']['time_s'][row]]
            selected=int(eligible[-1]) if len(eligible) else -1
            assert feature['peer_row'][row]==selected;checks+=1
    # ----------------------------------------
    # 時計欠測又は未来逆行を、過去の票/系譜へ混入しない。
    original=price_votes.pair(packet);changed=copy.deepcopy(packet)
    for account in changed['accounts'].values():
        account['record']['time_s'][500:]=np.nan;account['quotes']['time_s'][500:]=np.nan
        account['record']['price'][500:]=1e6
    after=price_votes.pair(changed)
    for s in pair:
        for field in original[s]['own']:
            np.testing.assert_array_equal(original[s]['own'][field][:500],after[s]['own'][field][:500]);checks+=1
        for field in ('peer_known','peer_count','peer_balance','peer_row','peer_raw_seq','peer_price_age_seconds'):
            np.testing.assert_array_equal(original[s][field][:500],after[s][field][:500]);checks+=1
    # peer同clockは直前正常、age=60は許可、60超は未知。
    times=np.array([0.,60.,120.,180.]);small=fixture(n=701)
    for s,account in small['accounts'].items():
        for part in ('record','quotes'):
            for key,value in list(account[part].items()):
                if isinstance(value,np.ndarray):account[part][key]=value[:4].copy()
        account['record']['time_s'][:]=times;account['quotes']['time_s'][:]=times
    equal=price_votes.pair(small)
    assert equal['TOPIX']['peer_row'][2]==1 and equal['TOPIX']['peer_known'][2]
    small['accounts']['NK225']['quotes']['quote_valid'][2:]=False
    small['accounts']['TOPIX']['record']['time_s'][2]=120.+1e-6
    farther=price_votes.pair(small)
    assert farther['TOPIX']['peer_row'][2]==1 and not farther['TOPIX']['peer_known'][2]
    assert farther['TOPIX']['peer_price_age_seconds'][2]>60.;checks+=3
    return checks


def state_boundaries() -> tuple:
    """
    機能: 欠測保持・失効/撤回・先着約定・未知保留・場停止を買売別に反証する。
    引数: なし。
    返り値: tuple は確認観点と配列照合数。非normalを窓未知と同一視しない。
    """
    checks=[];arrays=0
    for symbol in catalog.CAP:
        for side in (1,-1):
            tick=.5 if symbol=='TOPIX' else 10.;base=4000. if symbol=='TOPIX' else 65000.
            for mode in ('PULL','BREAK'):
                packet,config=controlled(symbol,side,mode);a=packet['accounts'][symbol];p=a['record']['price']
                step=base*.00025;recover=base*.000125
                if mode=='PULL':p[311]=base+side*2*step;p[312]=base;p[313]=np.nan;p[314:]=base+side*recover
                else:p[311]=base+side*step*.5;p[312]=np.nan;p[313:]=base+side*step
                feature=explicit_votes(packet,symbol,side);feature['own']['known'][310]=False
                out=interface.play(a,feature,config,'形状人工',python=True)
                bad=313 if mode=='PULL' else 312;before=bad-1;publication=314 if mode=='PULL' else 313
                np.testing.assert_array_equal(out['geometry_trace'][bad],out['geometry_trace'][before]);arrays+=1
                accepted=out['publication_events'][out['publication_events'][:,12]==1]
                assert int(accepted[0,0])==publication and int(accepted[0,4])==(1 if mode=='PULL' else 2)
                assert out['orders'][0,0]==publication+1
                checks.append(symbol+str(side)+'/'+mode+'正常→非正常→正常でgeometry保持')
            # ----------------------------------------
            # 窓未知は正常Last形状を消さない。後の現在票で新geometryだけを公開する。
            packet,config=controlled(symbol,side,'PULL');a=packet['accounts'][symbol];p=a['record']['price']
            p[311]=base+side*base*.0005;p[312]=base;p[313:]=base+side*base*.000125
            feature=explicit_votes(packet,symbol,side);feature['own']['known'][310:313]=False
            out=interface.play(a,feature,config,'窓未知人工',python=True)
            assert out['geometry_trace'][312,4]==1 and out['publication_events'][1,0]==313 and out['publication_events'][1,12]==1
            checks.append(symbol+str(side)+'/正常Lastと60秒known分離')
            # ----------------------------------------
            # 一回FAKは初正常で失効し、後の有利気配で同じ注文を復活させない。
            packet,config=controlled(symbol,side);a=packet['accounts'][symbol]
            a['quotes']['bid'][311]+=side*2*tick;a['quotes']['ask'][311]+=side*2*tick
            feature=explicit_votes(packet,symbol,side);out=interface.play(a,feature,config,'FAK人工',python=True)
            assert len(out['orders'])==0 and len(out['publication_events'])==1
            assert out['execution_events'][0,8]==98 and out['publication_events'][0,12]==1
            assert out['summary']['費用']==0;checks.append(symbol+str(side)+'/FAK一回失効料0')
            # ----------------------------------------
            # nonnormalで待つ間のpaper部分退出は未約定予約だけ撤回する。
            packet,config=controlled(symbol,side);a=packet['accounts'][symbol]
            v=5 if symbol=='TOPIX' else 10
            a['feed']=np.array([a['feed'][0],[311,310,7,-side,1,base,2,0,0,0],[1100,1099,7,-side,v-1,base,2,0,0,0]])
            a['quotes']['quote_valid'][311]=False;feature=explicit_votes(packet,symbol,side)
            out=interface.play(a,feature,config,'未約定撤回人工',python=True)
            assert len(out['orders'])==0 and out['execution_events'][0,1]==3 and out['execution_events'][0,8]==151
            assert out['geometry_trace'][311,0]==-1 and out['geometry_trace'][312,0]==312
            checks.append(symbol+str(side)+'/非正常部分撤回→次正常anchor初期化')
            # 同行の最初正常fillはpaper部分退出より先。実量はpaper部分量へ減らさない。
            a['quotes']['quote_valid'][311]=True;feature=explicit_votes(packet,symbol,side)
            live=interface.play(a,feature,config,'先行約定人工',python=True)
            assert live['orders'][0,0]==311 and live['orders'][0,4]==catalog.CAP[symbol]
            assert live['orders'][1,0]==1101 and live['orders'][1,4]==catalog.CAP[symbol]
            checks.append(symbol+str(side)+'/同行FAKfill先/filled部分無視/全退出次正常')
            # paper新規と部分EXITが同行でも撤回済みoriginを遅く公開しない。
            a['feed'][1,0]=310;out=interface.play(a,feature,config,'同行撤回人工',python=True)
            assert len(out['orders'])==0 and out['publication_events'][0,13]==151
            checks.append(symbol+str(side)+'/同行新規後EXITは公開撤回')
            # ----------------------------------------
            # 現在未知票は保有を撤回せず、両反対票だけ次行返済へ固定する。
            packet,config=controlled(symbol,side);a=packet['accounts'][symbol];feature=explicit_votes(packet,symbol,side)
            feature['own']['known'][312:314]=False;feature['peer_known'][312:314]=False
            feature['own']['balance'][314:]=-side;feature['peer_balance'][314:]=-side
            out=interface.play(a,feature,config,'反対票人工',python=True)
            assert out['orders'][1,0]==315 and out['orders'][1,1]==314 and out['orders'][1,6]==152
            checks.append(symbol+str(side)+'/未知保留→両反対票当行予約/次正常返済')
            # 窓既知flagに矛盾するNaN balanceは採用しない。
            feature=explicit_votes(packet,symbol,side);feature['own']['balance'][310]=np.nan
            out=interface.play(a,feature,config,'NaN票人工',python=True)
            assert len(out['orders'])==0 and out['publication_events'][0,13]==95
            checks.append(symbol+str(side)+'/NaNbalance拒否')
            # ----------------------------------------
            # 静観/期限は旧予約より優先し、pub時点へ未来価格を逆算しない。
            packet,config=controlled(symbol,side);a=packet['accounts'][symbol];a['quiet'][311]=True
            feature=explicit_votes(packet,symbol,side);out=interface.play(a,feature,config,'静観人工',python=True)
            assert len(out['orders'])==0 and out['execution_events'][0,8]==92
            packet,config=controlled(symbol,side);a=packet['accounts'][symbol];feature=explicit_votes(packet,symbol,side)
            a['quiet'][312]=True;out=interface.play(a,feature,config,'保有静観人工',python=True)
            assert out['orders'][1,0]==312 and out['orders'][1,1]==311 and out['orders'][1,6]==92
            checks.append(symbol+str(side)+'/既知静観timer優先')
            # ----------------------------------------
            # 場停止は当時清算firstcrossから次normal。後候補を再開しない。
            for sign,reason in ((1,162),(-1,161)):
                packet,config=controlled(symbol,side);a=packet['accounts'][symbol];feature=explicit_votes(packet,symbol,side)
                if sign>0:config['session_profit_fraction']=.0001
                else:config['session_stop_fraction']=.0002
                a['quotes']['bid'][312:]+=side*sign*2*tick;a['quotes']['ask'][312:]+=side*sign*2*tick
                a['feed']=np.array([a['feed'][0],[320,319,7,-side,v,base,2,0,0,0],
                    [321,320,8,side,v,base,20,1,0,4*tick],[1100,1099,8,-side,v,base,2,0,0,0]])
                out=interface.play(a,feature,config,'場停止人工',python=True)
                assert out['orders'][1,0]==313 and out['orders'][1,1]==312 and out['orders'][1,6]==reason
                assert out['publication_events'][-1,13]==reason and len(out['orders'])==2
                checks.append(symbol+str(side)+'/場firstcross'+str(reason)+'次正常/以後永久停止')
    return checks,arrays


def driver_connection(source: dict) -> int:
    """
    機能: 全source/JSON往復の登録ガードとplateau・期間分母を小人工だけで検査する。
    引数: source(dict) は最終所有署名。
    返り値: int は拒否又は同値確認数。照合/登録/金融は実行しない。
    """
    configs=catalog.configs();spec=dict(entry=dict(conditions=configs),implementation=source)
    proposal=json.loads(json.dumps(dict(id=catalog.TRIAL_ID,spec=spec),ensure_ascii=False))
    fixed=json.loads(json.dumps(dict(configs=configs,case_SHA256=plan.case_hashes(configs),source_SHA256=source),ensure_ascii=False))
    registered=[copy.deepcopy(proposal)];runner.registry_guard(registered,fixed,proposal);runner.source_scope_guard();checks=2
    for kind in range(5):
        bad=copy.deepcopy(registered);ff=copy.deepcopy(fixed)
        if kind==0:bad=[]
        elif kind==1:bad[0]['id']='別試行'
        elif kind==2:bad[0]['spec']['entry']['conditions'][0]['parent_target_fraction']*=2
        elif kind==3:ff['configs'][0]['quantity']['TOPIX']=1
        else:ff['source_SHA256']['別源']='不一致'
        try:runner.registry_guard(bad,ff,proposal)
        except AssertionError:checks+=1
        else:raise AssertionError('入力前ガードが差分を拒否しない')
    values=np.array([[np.nan,1.,0.],[np.nan,1.,0.],[2.,1.,0.],[2.,1.,0.]])
    packed=runner.packed(values)
    np.testing.assert_array_equal(values,packed['values'][np.searchsorted(packed['rows'],np.arange(len(values)),side='right')-1]);checks+=1
    checker_path=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
    module_spec=importlib.util.spec_from_file_location('保護再参加人工の純完全性',checker_path)
    checker=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(checker)
    complete=dict(id=catalog.TRIAL_ID,spec={k:dict(明示='適用する構造') for k in ('entry','management','exit','allocation','costs','execution','data','implementation')})
    complete['spec']['entry']=dict(conditions=configs)
    assert checker.analyze(json.loads(json.dumps(complete)),[])['proposal_complete'];checks+=1
    assert len(plan.clones())==7;checks+=1
    return checks


def run() -> None:
    """
    機能: 両商品/買売反射/PythonJITと動的容量・料金・撤回・未来接頭を検査する。
    引数: なし。
    返り値: None。所有source署名の人工証跡を保存。金融/大型入力/API0。
    """
    source=common.sources();configs=catalog.configs();checks=[];arrays=0;accounts=0
    for symbol in catalog.CAP:
        for side in (1,-1):
            for path in ('trend','wave','loss'):
                packet=fixture(symbol,side,path);features=price_votes.pair(packet);a=packet['accounts'][symbol]
                for c in configs:
                    py=interface.play(a,features[symbol],c,'人工',python=True,initial_capacity=16)
                    jit=interface.play(a,features[symbol],c,'人工',python=False,initial_capacity=16);accounts+=1
                    for field in ('orders','order_uids','economic_curve','publication_events','exit_judgments','execution_events','actual_origins','geometry_trace'):
                        np.testing.assert_array_equal(py[field],jit[field]);arrays+=1
                    assert py['summary']==jit['summary'] and py['parent']==jit['parent']
                    profiles=interface.parent_diagnostics(a,features[symbol],py)
                    assert len(profiles)==py['summary']['親数'] and sum(p['net_yen'] for p in profiles)==py['summary']['収支']
                    charge=Decimal('41.8' if symbol=='TOPIX' else '11')
                    cost=sum(int((Decimal(int(o[4]))*charge).to_integral_value(rounding=ROUND_FLOOR)) for o in py['orders'])
                    assert cost==py['summary']['費用']
                    assert all(p['entry_quantity']==catalog.CAP[symbol] for p in profiles)
                    for cut in (310,311,330,380,601,951):
                        pre=prefix(packet,symbol,cut);pf=price_votes.pair(pre)
                        short=interface.play(pre['accounts'][symbol],pf[symbol],c,'人工',finish=False,python=True,initial_capacity=16)
                        np.testing.assert_array_equal(short['orders'],py['orders'][py['orders'][:,0]<cut]);arrays+=1
                        np.testing.assert_array_equal(short['economic_curve'],py['economic_curve'][:cut]);arrays+=1
                    checks.append(symbol+str(side)+'/'+path+'/'+c['id'])
    # ----------------------------------------
    # 同じpaper親に多数の別実親が生じても、実UID/名目額/会計の分母を保つ。
    packet=fixture();features=price_votes.pair(packet);config=copy.deepcopy(configs[6])
    config['session_profit_fraction']=1e6;config['session_stop_fraction']=1e6
    output=interface.play(packet['accounts']['TOPIX'],features['TOPIX'],config,'人工',python=True,initial_capacity=16)
    assert len(output['parent'])>2 and len({int(v[1]) for v in output['actual_origins']})==1
    assert len({int(v[0]) for v in output['actual_origins']})==len(output['parent'])
    assert output['buffer_capacity']>24
    checks.append('一paperより多い独立実親/UIDと動的buffer拡張')
    # ----------------------------------------
    # 未来列を書き換えても、過去公開の票/許容/注文/清算を変更しない。
    packet=fixture();features=price_votes.pair(packet);c=configs[9];cut=601
    before=interface.play(packet['accounts']['TOPIX'],features['TOPIX'],c,'人工',python=True)
    future=copy.deepcopy(packet)
    for a in future['accounts'].values():
        mark=a['record']['time_s']>=600.
        a['record']['price'][mark]+=500.;a['quotes']['bid'][mark]-=100.;a['quotes']['ask'][mark]+=100.
        a['quotes']['quote_valid'][mark]=False
    ff=price_votes.pair(future);after=interface.play(future['accounts']['TOPIX'],ff['TOPIX'],c,'人工',finish=False,python=True)
    np.testing.assert_array_equal(before['orders'][before['orders'][:,0]<600],after['orders'][after['orders'][:,0]<600]);arrays+=1
    np.testing.assert_array_equal(before['economic_curve'][:600],after['economic_curve'][:600]);arrays+=1
    checks.append('未来price/quote資格で過去prefix不変')
    vote_checks=vote_boundaries();boundary_checks,boundary_arrays=state_boundaries();arrays+=boundary_arrays;checks.extend(boundary_checks)
    driver_checks=driver_connection(source)
    assert common.sources()==source
    common.write('十二保護と新価格票及び独立実親の人工検査_v2.json',dict(全合格=True,source_SHA256=source,
        条件数=12,人工口座=accounts,配列照合=arrays,価格票照合=vote_checks,driver照合=driver_checks,確認観点=checks,
        初版保全='archive/anchor窓known分離前の初回人工',変更理由='通常非正常行の形状保持、normalLastと窓knownの分離、driver最終接続。',
        金融=0,大型入力=0,台帳=0,原board=0,NPZ=0,API=0))
    print('保護再参加人工合格 '+str(accounts)+'口座/'+str(arrays)+'配列',flush=True)


if __name__=='__main__':run()
