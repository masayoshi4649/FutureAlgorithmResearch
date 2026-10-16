"""独立価格分類と価格・執行源の公開対応を、入力と確定注文から復元する。"""

import numpy as np

import common
import protocol
import state_checks


PRICE_COLUMNS = ['lane','grid','price_own_index','price_peer_index','price_own_raw_seq','price_peer_raw_seq',
                 'execution_own_index','execution_peer_index','price_own_time','price_peer_time',
                 'execution_own_time','execution_peer_time','price_own_valid','price_peer_valid',
                 'price_observable','mode','context_kind','context_decision_row','context_accepted',
                 'execution_current_valid','execution_peer_valid','price_mode']


def restore_price(session: dict,execution: dict,config: dict) -> dict:
    """
    機能: 二市場の価格源だけで分類と現在新規資格を独立区間確認する。
    引数: session/ execution/ config(dict)、価格素材・旧板flow・事前条件。
    返り値: dict、状態及び価格原seqによる確認旗。正式price_stateを呼ばない。
    """
    grid=session['grid'];n=len(grid)
    valid=np.ones(n,bool);now_ok=valid.copy();known_common=valid.copy();observable=valid.copy()
    high=valid.copy();low=valid.copy();inside=valid.copy()
    values={}
    for symbol in common.SYMBOLS:
        market=session['markets'][symbol];current=market['current'];er=market['windows'][300];bounds=market['ranges'][180]
        value=current.get('value',current.get('mid'));values[symbol]=value
        now=current['valid']&np.isfinite(value)&(value>0)
        er_known=now&er['source_valid']&np.isfinite(er['efficiency'])&np.isfinite(er['total_variation'])&(er['total_variation']>0)
        bound_known=(bounds['source_valid']&bounds['position_valid']&np.isfinite(bounds['low'])
                     &np.isfinite(bounds['high'])&np.isfinite(bounds['width'])&(bounds['width']>0))
        now_ok&=now;valid&=er_known;high&=er['efficiency']>=config['high_er'];low&=er['efficiency']<=config['low_er']
        inside&=bound_known&(value>=bounds['low'])&(value<=bounds['high'])
        observed=er_known&bound_known
        for seconds in (30,300):
            window=market['windows'][seconds];known=now&window['source_valid']&np.isfinite(window['ret_bp'])
            known_common&=known;observed&=known
        observable&=observed
    common_direction=np.zeros(n,np.int8);permission={}
    for side in (-1,1):
        directional=known_common.copy();allowed=now_ok.copy();returns=[];reverse=np.zeros(n,bool)
        for symbol in common.SYMBOLS:
            market=session['markets'][symbol];long=market['windows'][300];short=market['windows'][30]
            directional&=(side*long['ret_bp']>=3)&(side*short['ret_bp']>0)
            allowed&=long['source_valid']&np.isfinite(long['ret_bp'])&(side*long['ret_bp']>0)
            returns.append(side*long['ret_bp'])
            flow=execution['markets'][symbol]['flow'][15]
            sufficient=(flow['source_valid']&flow['valid']&~flow['missing_ofi']
                        &(flow['nonzero_ofi_count']>=3)&np.isfinite(flow['ofi_ratio']))
            reverse|=sufficient&(side*flow['ofi_ratio']<=-.1)
        common_direction[directional]=side
        allowed&=(np.minimum(returns[0],returns[1])>=.25*np.maximum(returns[0],returns[1]))&~reverse
        permission[side]=allowed
    raw=np.zeros(n,np.int8)
    for side in (-1,1):raw[valid&high&(common_direction==side)&permission[side]]=side
    raw[valid&low&inside&(common_direction==0)]=2
    sources=[session['markets'][symbol]['current']['raw_seq'] for symbol in common.SYMBOLS]
    mode=np.zeros(n,np.int8)
    for candidate in (-1,1,2):
        seconds=config.get('trend_mode_confirm_seconds',config['confirm_seconds']) if candidate in (-1,1) else config['confirm_seconds']
        mode[state_checks.confirmation(grid,raw==candidate,valid,*sources,float(seconds))]=candidate
    context=np.zeros(n,np.int8)
    context[state_checks.confirmation(grid,raw==2,observable,*sources,float(config['confirm_seconds']))]=2
    return dict(grid=grid,valid=valid,raw_mode=raw,mode=mode,source_top=sources[0],source_nk=sources[1],
                efficiency_top=session['markets']['TOPIX']['windows'][300]['efficiency'],
                efficiency_nk=session['markets']['NK225']['windows'][300]['efficiency'],common=common_direction,
                arm_common=common_direction,price_observable=observable,price_current_valid=now_ok,price_mode=context)


def signal_check(material: dict,session: str,symbol: str,config: dict,signal: dict) -> dict:
    """
    機能: 旧執行源と新価格源を別々に独立検算し、差替え又はQ貼り合わせを拒絶する。
    引数: material(dict)、session/symbol(str)、config/signal(dict)。
    返り値: dict、照合件数。
    """
    executed=material['grids'][session];entry=material['entries'][session]
    old=state_checks.restore(executed,entry,config);opposite=state_checks.reversal(executed,entry,config)
    old.update(opposite);old.update(state_checks.new_sources(material,session,symbol,config))
    lane=config.get('price_lane','I0');prices=material['price_lanes'][lane][session]
    predicted=restore_price(prices,executed,config)
    if lane!='I0':old.update(predicted)
    else:
        for name in ('price_observable','price_current_valid','price_mode'):old[name]=predicted[name]
    peer='NK225' if symbol=='TOPIX' else 'TOPIX'
    for label,market_symbol in (('own',symbol),('peer',peer)):
        current=prices['markets'][market_symbol]['current']
        for published,source in (('index','index'),('raw_seq','raw_seq'),('time','time_s'),('valid','valid')):
            old['price_'+label+'_'+published]=current[source]
    for name,value in old.items():
        if name=='price_current_valid' and name not in signal:continue
        common.same(signal[name],value)
    common.same(signal['mapped'],state_checks.mapping(signal['grid'],material['prices'][session,symbol]['time_s']))
    common.same(signal['peer_mid'],executed['markets'][peer]['current']['mid'])
    common.same(signal['peer_source'],executed['markets'][peer]['current']['index'])
    common.same(signal['peer_valid'],executed['markets'][peer]['current']['valid'])
    return dict(価格分類及び旧執行源独立接続=1)


def restore_sources(record: dict,signal: dict,config: dict,risk: np.ndarray) -> np.ndarray:
    """
    機能: 公開済み格子と独立入口状態から22列を復元し、潜在源traceを正答にしない。
    引数: record/signal/config(dict)、risk(ndarray[n,40])は確定fillから独立再構成した状態。
    返り値: ndarray[n,22]。価格index・原seq・時計と旧BBOindex・時計を混同しない。
    """
    latest,fresh,current,_=protocol.current(record,signal,config);n=len(latest);size=len(signal['grid'])
    safe=np.maximum(latest,0);present=latest>=0
    output=np.zeros((n,22),float)
    lane={'I0':0,'I1':1,'I2':2,'I3':3}[config.get('price_lane','I0')]
    context={'legacy':0,'observable':1,'confirmed_range':2}[config.get('range_entry_context','legacy')]
    output[:,0]=lane;output[:,1]=latest;output[:,16]=context
    for column,name in ((2,'price_own_index'),(3,'price_peer_index'),(4,'price_own_raw_seq'),(5,'price_peer_raw_seq'),
                        (6,'own_source'),(7,'peer_source')):
        output[:,column]=np.where(present,signal.get(name,np.full(size,-1))[safe],-1)
    for column,name in ((8,'price_own_time'),(9,'price_peer_time'),(10,'own_source_time'),(11,'peer_source_time')):
        output[:,column]=np.where(present,signal.get(name,np.full(size,np.nan))[safe],np.nan)
    for column,name in ((12,'price_own_valid'),(13,'price_peer_valid')):
        output[:,column]=present&signal.get(name,np.zeros(size,bool))[safe]
    output[:,14]=fresh&signal.get('price_observable',np.zeros(size,bool))[safe]
    output[:,15]=protocol.modes(record,signal)
    output[:,17]=risk[:,1] if context else -1
    output[:,18]=risk[:,2] if context else 0
    output[:,19]=current
    output[:,20]=(fresh&signal['peer_valid'][safe]&np.isfinite(signal['peer_mid'][safe])&(signal['peer_mid'][safe]>0))
    output[:,21]=np.where(fresh,signal.get('price_mode',signal['mode'])[safe],0)
    return output


def verify_sources(record: dict,signal: dict,config: dict,result: dict,risk: np.ndarray) -> dict:
    """
    機能: 22列の別源対応とG1/G2当時資格及び初回判定消費を全行照合する。
    引数: record/signal/config/result(dict)、risk(ndarray[n,40])。
    返り値: dict、全行と入口判定の検査件数。
    """
    expected=restore_sources(record,signal,config,risk)
    common.same(result['price_source_trace'],expected)
    context=int(expected[0,16])
    gates=np.unique(risk[risk[:,1]>=0,1]).astype(int)
    if context:
        for row in gates:
            accepted=bool(expected[row,14]) and (context!=2 or expected[row,21]==2)
            assert risk[row,2]==accepted,(row,'現在価格資格の受理が違う')
            if not accepted:
                next_prepare=np.flatnonzero((np.arange(len(risk))>row)&(risk[:,1]<0))
                stop=int(next_prepare[0]) if len(next_prepare) else len(risk)
                entries=result['events'][(result['events'][:,2]==1)&(result['events'][:,3]==1)]
                assert not np.any((entries[:,0]>row)&(entries[:,0]<stop)),('初回見送り消費の復活',row)
    return dict(全行価格と執行源の独立対応=len(expected),現在価格入口の独立資格判定=len(gates) if context else 0)
