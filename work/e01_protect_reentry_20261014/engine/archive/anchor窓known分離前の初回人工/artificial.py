"""十二保護再参加を小人工で検査し、価格票・影/実親・料金・接頭を分離する。"""

import copy
from decimal import Decimal,ROUND_FLOOR
import numpy as np
import common
import catalog
import price_votes
import interface


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
    assert common.sources()==source
    common.write('十二保護と新価格票及び独立実親の人工検査.json',dict(全合格=True,source_SHA256=source,
        条件数=12,人工口座=accounts,配列照合=arrays,確認観点=checks,金融=0,大型入力=0,台帳=0,原board=0,NPZ=0,API=0))
    print('保護再参加人工合格 '+str(accounts)+'口座/'+str(arrays)+'配列',flush=True)


if __name__=='__main__':run()
