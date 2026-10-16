"""確定一分足だけから、欠測を区別したMA特徴と事前固定32候補を生成する。"""

import numpy as np


PERIODS=(2,3,4,5,6,8,10,12,15,20,25,30,40,50,60,90)
BAR_FIELDS=('t_s','open','high','low','close','volume','volume_known','valid','book_imbalance',
    'book_depth','book_ofi','book_quote_valid','anchor','pub_raw_row')
PEER_FIELDS=('matchedNKclose','return3','return10','efficiency10','matchedNKt_s','matchedNKknown')


def _run(valid: np.ndarray) -> np.ndarray:
    """
    機能: 現在まで連続して有効だった一分足の本数を数える。
    引数: valid(ndarray[bool,N]) は当時資格。
    返り値: ndarray[int64,N] は連続本数。欠測で0へresetする。
    """
    result=np.zeros(len(valid),np.int64);count=0
    for i,ok in enumerate(valid):
        count=count+1 if ok else 0;result[i]=count
    return result


def _lag(value: np.ndarray,period: int,run: np.ndarray) -> np.ndarray:
    """
    機能: 同じ価格連続区間内の過去値だけを参照する。
    引数: value(ndarray)、period(int)、run(ndarray[int]) は系列・過去幅・有効連続本数。
    返り値: ndarray[float] は過去値。欠測を跨ぐ値はNaN。
    """
    out=np.full(len(value),np.nan)
    if period<len(value):out[period:]=value[:-period]
    out[run<=period]=np.nan
    return out


def _rolling(value: np.ndarray,period: int,kind: str) -> np.ndarray:
    """
    機能: 有限値が連続した完備窓だけで現在までの統計量を求める。
    引数: value(ndarray)、period(int)、kind(str) は系列・分数・mean/sum/min/max/std。
    返り値: ndarray[float] は統計量。欠測補完や未来窓を用いない。
    """
    assert period>=1 and kind in ('mean','sum','min','max','std')
    result=np.full(len(value),np.nan);finite=np.isfinite(value)
    edges=np.flatnonzero(np.diff(np.r_[False,finite,False].astype(np.int8)))
    for start,end in zip(edges[::2],edges[1::2]):
        if end-start<period:continue
        windows=np.lib.stride_tricks.sliding_window_view(value[start:end],period)
        if kind=='mean':v=windows.mean(axis=1)
        elif kind=='sum':v=windows.sum(axis=1)
        elif kind=='min':v=windows.min(axis=1)
        elif kind=='max':v=windows.max(axis=1)
        else:v=windows.std(axis=1,ddof=0)
        result[start+period-1:end]=v
    return result


def _ema(value: np.ndarray,period: int) -> np.ndarray:
    """
    機能: p本のSMAをseedにしたEMAを、有限連続区間ごとに計算する。
    引数: value(ndarray)、period(int) は価格系列と分数。
    返り値: ndarray[float] はEMA。欠分でseedと履歴を破棄する。
    """
    result=np.full(len(value),np.nan);count=0;total=0.;last=np.nan;alpha=2/(period+1)
    for i,v in enumerate(value):
        if not np.isfinite(v):count=0;total=0.;last=np.nan;continue
        count+=1
        if count<=period:
            total+=v
            if count==period:last=total/period;result[i]=last
        else:last=alpha*v+(1-alpha)*last;result[i]=last
    return result


def _ratio(numerator: np.ndarray,denominator: np.ndarray) -> np.ndarray:
    """
    機能: 有限かつ正の分母を持つ比だけを求める。
    引数: numerator/denominator(ndarray) は同長の観測又は統計量。
    返り値: ndarray[float] は比。分母なしはNaN、0取引へ救済しない。
    """
    out=np.full(len(numerator),np.nan);ok=np.isfinite(numerator)&np.isfinite(denominator)&(denominator>0)
    with np.errstate(over='ignore',invalid='ignore',divide='ignore'):out[ok]=numerator[ok]/denominator[ok]
    out[~np.isfinite(out)]=np.nan
    return out


def _ordered(values: list[np.ndarray]) -> np.ndarray:
    """
    機能: 短期から長期までの厳密整列を買い1/売り−1/中立0へ写す。
    引数: values(list[ndarray]) は短期順のMA。
    返り値: ndarray[float] は整列方向。いずれか未知ならNaN。
    """
    a=np.column_stack(values);known=np.isfinite(a).all(axis=1);difference=np.diff(a,axis=1)
    out=np.full(len(a),np.nan);out[known]=0.
    out[known&(difference<0).all(axis=1)]=1.;out[known&(difference>0).all(axis=1)]=-1.
    return out


def _signed_run(state: np.ndarray) -> np.ndarray:
    """
    機能: 同じ非零方向が現在まで続いた本数を符号付きで数える。
    引数: state(ndarray) は−1/0/1又は未知。
    返り値: ndarray[float] は継続本数。中立0と未知NaNを分ける。
    """
    result=np.full(len(state),np.nan);last=0;count=0
    for i,value in enumerate(state):
        if not np.isfinite(value):last=0;count=0;continue
        d=int(np.sign(value));count=count+1 if d and d==last else 1 if d else 0
        last=d;result[i]=d*count
    return result


def _publish(long: np.ndarray,short: np.ndarray,known: np.ndarray,persistence: int) -> np.ndarray:
    """
    機能: 当時条件が必要本数続いた最初だけ方向事象を公開する。
    引数: long/short/known(ndarray[bool])、persistence(int) は方向条件と確認本数。
    返り値: ndarray[int8] は新規事象。連続成立中の毎分連射や未知跨ぎを行わない。
    """
    assert not np.any(long&short&known)
    result=np.zeros(len(known),np.int8);last=0;count=0
    for i in range(len(known)):
        d=1 if known[i] and long[i] else -1 if known[i] and short[i] else 0
        count=count+1 if d and d==last else 1 if d else 0;last=d
        if d and count==persistence:result[i]=d
    return result


def prepare(bars: dict,other: dict) -> dict:
    """
    機能: 同一一分軸の多数MA・価格出来高板・先行NK特徴と32仮説を因果生成する。
    引数: bars(dict[str,ndarray,N]) は14契約列、other(dict) は先行NK6列。1回は1セッション。
    返り値: dict は有限X/names/feature_groups、int8 signals、32仕様、known/raw MA診断。
    未来足・時刻/日付ラベル・ATR・目的変数・外部IO・原配列変更を用いない。
    """
    assert all(k in bars for k in BAR_FIELDS) and all(k in other for k in PEER_FIELDS)
    n=len(bars['t_s']);assert all(np.asarray(bars[k]).shape==(n,) for k in BAR_FIELDS)
    assert all(np.asarray(other[k]).shape==(n,) for k in PEER_FIELDS)
    time=np.asarray(bars['t_s']);assert np.isfinite(time).all() and np.all(np.diff(time)==60.)
    for name in ('valid','volume_known','book_quote_valid'):assert np.asarray(bars[name]).dtype==bool
    assert np.asarray(other['matchedNKknown']).dtype==bool and np.issubdtype(np.asarray(bars['pub_raw_row']).dtype,np.integer)
    price_ok=np.asarray(bars['valid']);o,h,l,c=(np.asarray(bars[k],float) for k in ('open','high','low','close'))
    assert np.all(~price_ok|(np.isfinite(o)&np.isfinite(h)&np.isfinite(l)&np.isfinite(c)&(l>0)&(l<=o)&(o<=h)&(l<=c)&(c<=h)))
    close=np.where(price_ok,c,np.nan);high=np.where(price_ok,h,np.nan);low=np.where(price_ok,l,np.nan)
    run=_run(price_ok);anchor=np.asarray(bars['anchor'],float);decision=price_ok&np.isfinite(anchor)&(anchor>0)&(bars['pub_raw_row']>=0)
    vol_ok=price_ok&bars['volume_known'];volume=np.asarray(bars['volume'],float)
    assert np.all(~vol_ok|(np.isfinite(volume)&(volume>=0)))
    vol=np.where(vol_ok,volume,np.nan);vol_run=_run(vol_ok)
    book_ok=price_ok&bars['book_quote_valid'];book={}
    for name in ('book_imbalance','book_depth','book_ofi'):
        a=np.asarray(bars[name],float)
        assert not np.any(book_ok&np.isinf(a)) and np.all(~(book_ok&np.isfinite(a))|(np.abs(a)<=1+1e-12))
        book[name]=np.where(book_ok&np.isfinite(a),a,np.nan)
    peer_ok=np.asarray(other['matchedNKknown']);peer_time=np.asarray(other['matchedNKt_s'],float)
    assert np.all(~peer_ok|(np.isfinite(peer_time)&(peer_time<=time-60.)))
    peer={}
    for name in ('matchedNKclose','return3','return10','efficiency10'):
        a=np.asarray(other[name],float);assert np.all(~peer_ok|np.isfinite(a));peer[name]=np.where(peer_ok,a,np.nan)
    assert np.all(~peer_ok|(peer['matchedNKclose']>0)) and np.all(~peer_ok|((peer['efficiency10']>=0)&(peer['efficiency10']<=1+1e-12)))
    raw={};groups={};notes={}

    def add(name: str,value: np.ndarray,group: str,note: str) -> None:
        """
        機能: 未知を保持した特徴を、その意味と分類とともに登録する。
        引数: name/group/note(str)、value(ndarray) は特徴の定義。
        返り値: None。Xへの数値化時だけ0＋known flagへ分離する。
        """
        assert name not in raw and value.shape==(n,)
        raw[name]=value;groups[name]=group;notes[name]=note

    for name,a in (('open',o),('high',h),('low',l),('close',c)):
        add(name,np.where(price_ok,a,np.nan),'price','当該確定一分足。日時・未来足を含まない。')
    add('anchor',np.where(decision,anchor,np.nan),'price','足を閉じた公開原rowの現在Last。足closeとは別。')
    add('bar_body',_ratio(c-o,c),'price','確定足実体のclose比。')
    raw['bar_body'][~price_ok]=np.nan
    add('bar_range',_ratio(high-low,close),'price','確定足高安幅のclose比。ATRではない。')
    for period in (1,2,3,5,10,15,20,30,60):
        add(f'return{period}',_ratio(close,_lag(close,period,run))-1,'price','同じ価格連続区間の過去close比。')
    changes=np.abs(close-_lag(close,1,run));eff={};std={}
    for period in (3,5,10,20,30,60):
        numerator=np.abs(close-_lag(close,period,run));denom=_rolling(changes,period,'sum')
        value=_ratio(numerator,denom);value[(np.isfinite(numerator))&(denom==0)]=0.
        eff[period]=value;add(f'efficiency{period}',value,'price','方向変位/close更新絶対量。静止完備窓は0、未知と区別。')
    for period in (5,10,20,30):
        std[period]=_rolling(close,period,'std');add(f'close_std{period}',std[period],'price','確定close標準偏差、ddof0。')
    add('direction_run',_signed_run(np.sign(raw['return1'])),'price','close方向の同符号継続本数。')
    ema={};sma={};slope={}
    for kind,bank in (('ema',ema),('sma',sma)):
        for period in PERIODS:
            value=_ema(close,period) if kind=='ema' else _rolling(close,period,'mean');bank[period]=value
            add(f'{kind}{period}',value,'ma','各セッション内でp本完備から算出。EMAseedは最初p本のSMA。')
            add(f'{kind}{period}_gap',_ratio(np.where(decision,anchor,np.nan),value)-1,'ma','現在anchor/当時MA−1。')
            for past in (1,3,5):
                sl=_ratio(value,_lag(value,past,run))-1;slope[kind,period,past]=sl
                add(f'{kind}{period}_slope{past}',sl,'ma','同じ有効連続区間内のMA変化比。')
    ribbons={'fast':(2,3,4,5,6,8),'medium':(5,10,15,20),'slow':(10,20,40,60),'all':PERIODS}
    band={};order={};agreement={}
    for name,periods in ribbons.items():
        a=np.column_stack([ema[p] for p in periods]);known=np.isfinite(a).all(axis=1)
        width=np.full(n,np.nan);width[known]=(a[known].max(axis=1)-a[known].min(axis=1))/close[known]
        band[name]=width;order[name]=_ordered([ema[p] for p in periods])
        votes=np.column_stack([slope['ema',p,1] for p in periods]);ok=np.isfinite(votes).all(axis=1)
        agreement[name]=np.where(ok,np.sign(votes).sum(axis=1)/len(periods),np.nan)
        add('ribbon_'+name,width,'ma','同時点EMA最大−最小のclose比。多数MAは相関しており独立票でない。')
        add('order_'+name,order[name],'ma','期間昇順MAの厳密整列、買1/売−1/中立0。')
        add('agreement_'+name,agreement[name],'ma','同時点EMA傾き符号の平均。独立証拠数ではない。')
        add('order_run_'+name,_signed_run(order[name]),'ma','厳密整列の同符号継続本数。')
    for period in (3,5,10,20):
        mean=_lag(_rolling(vol,period,'mean'),1,vol_run)
        add(f'volume_ratio{period}',_ratio(vol,mean),'volume','現在確定出来高/それ以前p本平均。未知窓/分母0は未知。')
    for period in (5,20):
        vwap=_ratio(_rolling(close*vol,period,'sum'),_rolling(vol,period,'sum'))
        add(f'close_volume_proxy{period}',vwap,'volume','確定close×出来高の加重平均。真の約定VWAP/保有原価ではない。')
        add(f'close_volume_gap{period}',_ratio(np.where(decision,anchor,np.nan),vwap)-1,'volume','現在anchorと確定close出来高proxyの比。')
    for name,a in book.items():add(name,a,'book','閉足内の正常気配からの比。depthも量ではなく距離重みimbalance。')
    for name,a in peer.items():add('peer_'+name,a,'peer','自身t_s−60以前に確定したNK足からrootが照合。真受信同期の証明でない。')
    add('peer_age_seconds',np.where(peer_ok,time-peer_time,np.nan),'peer','自己足基準の先行NK足age。')
    hh={p:_lag(_rolling(high,p,'max'),1,run) for p in (3,5,10,15,20,30)}
    ll={p:_lag(_rolling(low,p,'min'),1,run) for p in (3,5,10,15,20,30)}
    for period in (5,10,20,30):
        add(f'prior_range{period}',_ratio(hh[period]-ll[period],close),'price','現在足を含めない過去高安幅のclose比。')
        add(f'prior_position{period}',_ratio(close-ll[period],hh[period]-ll[period]),'price','過去確定高安に対する位置。定幅0は未知。')
    signals=[];specs=[];candidate_known=[]

    def emit(identity: str,family: str,title: str,long: np.ndarray,short: np.ndarray,requirements: list[np.ndarray],condition: str,persistence: int=1) -> None:
        """
        機能: 事前固定一条件を必要特徴の当時資格付きで事象化する。
        引数: identity/family/title/condition(str)、long/short(ndarray)、requirements(list)、persistence(int)。
        返り値: None。将来ラベルや結果に基づく候補の選択・係数変更を行わない。
        """
        known=decision.copy()
        for item in requirements:known&=np.isfinite(item)
        signal=_publish(long,short,known,persistence);signals.append(signal);candidate_known.append(known)
        specs.append(dict(id=identity,family=family,name=title,condition=condition,persistence_minutes=persistence,
            publication='必要本数成立した現在pubだけ。同方向が続く間は再公開0。未知/中立/不成立で再武装。',
            anchor='確定足closeではなく、閉足を公表した原row Last。現在anchorが必要水準を維持していることも審査。',
            warmup='この条件が参照する期間だけ完備必須。欠分でreset、長期MA未完でも短期候補を一律停止しない。',
            limitations='未測仮説。形の未来予測/心理/補充の事実や独立した複数証拠とは扱わない。'))

    # ----------------------------------------
    # 整列継続4条件。各異尺度又は異なるMA定義を事前に固定する。
    for identity,kind,periods,past,persist,ep,title in (
        ('T01','ema',(3,8,20),1,3,10,'短中EMA整列の3分確認'),
        ('T02','sma',(5,15,40),3,2,20,'SMA整列と3分傾き'),
        ('T03','ema',(10,30,60),5,2,30,'長いEMA整列と5分傾き')):
        bank=ema if kind=='ema' else sma;ordered=_ordered([bank[p] for p in periods]);sl=[slope[kind,p,past] for p in periods]
        positive=np.logical_and.reduce([a>0 for a in sl]);negative=np.logical_and.reduce([a<0 for a in sl])
        emit(identity,'整列継続',title,(ordered==1)&positive&(anchor>bank[periods[0]])&(eff[ep]>=.3),
            (ordered==-1)&negative&(anchor<bank[periods[0]])&(eff[ep]>=.3),[ordered,eff[ep],*sl],
            f'{kind}{periods}厳密整列、各MAの{past}分傾き同向、efficiency{ep}>=.3、anchorが短期MA同方向側。',persist)
    agree=np.column_stack([slope['ema',p,3] for p in (5,20,60,90)])
    emit('T04','整列継続','四尺度の傾き全合意',np.all(agree>0,axis=1)&(anchor>ema[20])&(eff[30]>=.4),
        np.all(agree<0,axis=1)&(anchor<ema[20])&(eff[30]>=.4),[ema[20],eff[30],*agree.T],
        'EMA5/20/60/90の3分傾きが全同向、efficiency30>=.4、anchorはEMA20同方向側。',3)
    # ----------------------------------------
    # 収束拡散4条件。収束の基準は過去に確定した幅だけで作る。
    for identity,name,bank,periods,lookback in (
        ('S01','短期EMA',ema,(2,3,4,5,6,8),10),('S02','中期SMA',sma,(5,10,15,20),20)):
        a=np.column_stack([bank[p] for p in periods]);ok=np.isfinite(a).all(axis=1)
        width=np.where(ok,(np.max(a,axis=1)-np.min(a,axis=1))/close,np.nan)
        previous=_lag(width,1,run);earlier_min=_lag(_rolling(width,lookback,'min'),2,run)
        ready=(previous<=earlier_min)&(width>previous);ordered=_ordered([bank[p] for p in periods])
        upper=np.max(a,axis=1);lower=np.min(a,axis=1)
        emit(identity,'収束拡散',name+'過去最小幅から拡散',ready&(ordered==1)&(close>upper)&(anchor>upper),
            ready&(ordered==-1)&(close<lower)&(anchor<lower),[width,previous,earlier_min,ordered],
            f'{periods}MA帯の前足幅がそれ以前{lookback}足最小以下、現在幅が拡大、厳密整列とclose/anchorの帯外同向。')
    prior_fast=_lag(band['fast'],1,run);past_order=_lag(order['fast'],1,run)
    emit('S03','収束拡散','狭いレンジから短期整列',((hh[5]-ll[5])<=(hh[20]-ll[20])*.5)&(band['fast']>prior_fast)&(past_order!=1)&(order['fast']==1)&(anchor>hh[5]),
        ((hh[5]-ll[5])<=(hh[20]-ll[20])*.5)&(band['fast']>prior_fast)&(past_order!=-1)&(order['fast']==-1)&(anchor<ll[5]),
        [hh[5],ll[5],hh[20],ll[20],prior_fast,band['fast'],past_order,order['fast']],
        '過去5分高安幅<=過去20分幅/2、EMA短期帯拡大と新しい厳密整列、anchorが過去5分帯を同向離脱。')
    returns=raw['return1'];rstd5=_rolling(returns,5,'std');rstd20=_rolling(returns,20,'std')
    a5=_lag(rstd5,1,run);a20=_lag(rstd20,1,run)
    emit('S04','収束拡散','close変動収縮後の新変化',(a5<=a20*.5)&(returns>a20)&(ema[3]>ema[12])&(anchor>ema[3]),
        (a5<=a20*.5)&(returns<-a20)&(ema[3]<ema[12])&(anchor<ema[3]),[a5,a20,returns,ema[3],ema[12]],
        '前足時点return標準偏差5<=20/2、現在returnが前20分標準偏差を越える。EMA3/12とanchorも同向。ATR不使用。')
    # ----------------------------------------
    # 変化点4条件。クロス認定は現在足に置き、過去足へ巻き戻さない。
    for identity,bank,kind,fast,slow in (('C01',ema,'ema',3,12),('C02',sma,'sma',5,20)):
        gap=bank[fast]-bank[slow];old=_lag(gap,1,run);sl=slope[kind,slow,3]
        emit(identity,'変化点',f'{kind}{fast}/{slow}新クロス',(gap>0)&(old<=0)&(sl>=0)&(anchor>bank[fast]),
            (gap<0)&(old>=0)&(sl<=0)&(anchor<bank[fast]),[gap,old,sl],
            f'{kind}{fast}と{slow}が当足で新クロス。長期MA3分傾きが反対でなくanchorも短期MA同向側。')
    sl=slope['ema',20,3];old=_lag(sl,1,run)
    emit('C03','変化点','中期傾きの符号転換',(sl>0)&(old<=0)&(ema[5]>ema[20])&(anchor>ema[5]),
        (sl<0)&(old>=0)&(ema[5]<ema[20])&(anchor<ema[5]),[sl,old,ema[5],ema[20]],
        'EMA20の3分傾きが当足で0を越え、EMA5/20とanchorも同向。')
    consensus=np.column_stack([slope['ema',p,1] for p in (3,8,20,50)])
    known=np.isfinite(consensus).all(axis=1);vote=np.where(known,np.sign(consensus).mean(axis=1),np.nan);old=_lag(vote,1,run)
    emit('C04','変化点','傾き合意の中立越え',(vote>=.75)&(old<=0)&(anchor>ema[8]),
        (vote<=-.75)&(old>=0)&(anchor<ema[8]),[vote,old,ema[8]],
        'EMA3/8/20/50の一分傾き符号平均が前足非順行から±.75へ。相関MAを独立票として数えない。')
    # ----------------------------------------
    # 離脱4条件。高安は現在足より前に固定し、現在anchorでも維持を要求する。
    emit('B01','レンジ離脱','過去10分帯の新離脱',(close>hh[10])&(anchor>hh[10])&(eff[10]>=.25),
        (close<ll[10])&(anchor<ll[10])&(eff[10]>=.25),[hh[10],ll[10],eff[10]],'現在足を含まない過去10分高安をcloseとanchorが離脱、efficiency10>=.25。')
    emit('B02','レンジ離脱','過去30分帯と中期MA',(close>hh[30])&(anchor>hh[30])&(ema[10]>ema[30]),
        (close<ll[30])&(anchor<ll[30])&(ema[10]<ema[30]),[hh[30],ll[30],ema[10],ema[30]],'過去30分高安離脱、EMA10/30同向、anchorが水準を維持。')
    opening_high=np.full(n,np.nan);opening_low=np.full(n,np.nan)
    if n>=15 and np.all(price_ok[:15]):opening_high[15:]=np.max(high[:15]);opening_low[15:]=np.min(low[:15])
    emit('B03','レンジ離脱','最初15分の固定帯',(close>opening_high)&(anchor>opening_high),
        (close<opening_low)&(anchor<opening_low),[opening_high,opening_low],
        'セッション最初15本が全て有効な時だけ固定高安を使用。以後のclose/anchor離脱。欠けた開始帯を後から作り直さない。')
    narrow=(hh[5]-ll[5])<=(hh[20]-ll[20])*.5
    emit('B04','レンジ離脱','短期停滞後の中期帯離脱',narrow&(close>hh[20])&(anchor>hh[20]),
        narrow&(close<ll[20])&(anchor<ll[20]),[hh[5],ll[5],hh[20],ll[20]],'過去5分帯幅<=過去20分帯幅/2、現在closeとanchorが20分帯を離脱。')
    # ----------------------------------------
    # 押し戻り4条件。先に確定した逆行/停滞から現在の再進行を確認する。
    pc=_lag(close,1,run);pl=_lag(low,1,run);ph=_lag(high,1,run)
    e8p=_lag(ema[8],1,run);e20p=_lag(ema[20],1,run);e60p=_lag(ema[60],1,run)
    emit('P01','押し戻り','短期EMA接触後の回復',(ema[8]>ema[20])&(ema[20]>ema[40])&(pl<=e8p)&(pc>=e20p)&(close>ema[8])&(anchor>ema[8]),
        (ema[8]<ema[20])&(ema[20]<ema[40])&(ph>=e8p)&(pc<=e20p)&(close<ema[8])&(anchor<ema[8]),
        [ema[8],ema[20],ema[40],pl,ph,pc,e8p,e20p],'EMA8/20/40整列、前足がEMA8へ接触しEMA20をcloseで維持、現在close/anchorがEMA8へ回復。')
    emit('P02','押し戻り','中期EMAの再獲得',(ema[20]>ema[60])&(pc<=e20p)&(pc>=e60p)&(close>ema[20])&(anchor>ema[20])&(slope['ema',5,1]>0),
        (ema[20]<ema[60])&(pc>=e20p)&(pc<=e60p)&(close<ema[20])&(anchor<ema[20])&(slope['ema',5,1]<0),
        [ema[20],ema[60],pc,e20p,e60p,slope['ema',5,1]],'EMA20/60整列の中で前足が20を逆側へ、60は維持。現在20を再獲得しEMA5傾き同向。')
    past_return=_lag(raw['return3'],1,run)
    emit('P03','押し戻り','三分押し後の前足抜け',(ema[10]>ema[30])&(past_return<0)&(close>ph)&(anchor>ph),
        (ema[10]<ema[30])&(past_return>0)&(close<pl)&(anchor<pl),[ema[10],ema[30],past_return,ph,pl],
        'EMA10/30整列、前足まで3分が逆行、現在close/anchorが直前足高安を順側へ抜ける。')
    pause=(hh[3]-ll[3])<=(hh[10]-ll[10])*.5
    emit('P04','押し戻り','整列中の小休止離脱',pause&(ema[5]>ema[15])&(ema[15]>ema[40])&(close>hh[3])&(anchor>hh[3]),
        pause&(ema[5]<ema[15])&(ema[15]<ema[40])&(close<ll[3])&(anchor<ll[3]),
        [hh[3],ll[3],hh[10],ll[10],ema[5],ema[15],ema[40]],'EMA5/15/40整列中、過去3分幅<=過去10分幅/2。現在close/anchorが小休止帯を離脱。')
    # ----------------------------------------
    # 反発4条件。極値が未来に確定したpivotであるとの補完をしない。
    earlier_high=_lag(hh[15],1,run);earlier_low=_lag(ll[15],1,run)
    emit('R01','反発','失敗した帯抜けから反発',(pl<earlier_low)&(pc>=earlier_low)&(close>ph)&(anchor>ph)&(slope['ema',3,1]>0),
        (ph>earlier_high)&(pc<=earlier_high)&(close<pl)&(anchor<pl)&(slope['ema',3,1]<0),
        [pl,ph,pc,earlier_low,earlier_high,slope['ema',3,1]],'前足がそれ以前15分帯をヒゲで抜けcloseで戻る。現在足が前足高安を逆へ抜けて初めて認定。')
    lower=sma[20]-2*std[20];upper=sma[20]+2*std[20];old_lower=_lag(lower,1,run);old_upper=_lag(upper,1,run)
    emit('R02','反発','二標準偏差帯への復帰',(pc<old_lower)&(close>=lower)&(anchor>=lower)&(slope['ema',3,1]>0),
        (pc>old_upper)&(close<=upper)&(anchor<=upper)&(slope['ema',3,1]<0),
        [pc,old_lower,old_upper,lower,upper,slope['ema',3,1]],'前足closeが当時SMA20±2close標準偏差の外、現在帯内へ復帰しEMA3傾き同向。')
    old_fast=_lag(slope['ema',3,1],1,run)
    emit('R03','反発','長期逆向き中の短中転換',(slope['ema',3,1]>0)&(old_fast<=0)&(slope['ema',8,3]>0)&(slope['ema',20,5]<0)&(anchor>sma[5]),
        (slope['ema',3,1]<0)&(old_fast>=0)&(slope['ema',8,3]<0)&(slope['ema',20,5]>0)&(anchor<sma[5]),
        [slope['ema',3,1],old_fast,slope['ema',8,3],slope['ema',20,5],sma[5]],'EMA20傾きはまだ逆向き、EMA3が新転換しEMA8傾き同向。anchorはSMA5同向側。')
    position=_ratio(pc-ll[30],hh[30]-ll[30])
    emit('R04','反発','既知帯の端から短期回復',(position<=.25)&(raw['return2']>0)&(close>ema[5])&(anchor>ema[5])&(eff[5]>=.3),
        (position>=.75)&(raw['return2']<0)&(close<ema[5])&(anchor<ema[5])&(eff[5]>=.3),
        [position,raw['return2'],ema[5],eff[5]],'前足closeが既知30分帯の端25%内、現在2分変化・EMA5回復・efficiency5>=.3。')
    # ----------------------------------------
    # 二市場4条件。NKはrootが作った厳密先行足だけを利用する。
    p3=peer['return3'];p10=peer['return10'];pe=peer['efficiency10']
    emit('M01','二市場','三分方向の二市場一致',(raw['return3']>0)&(raw['return10']>0)&(p3>0)&(ema[3]>ema[10])&(anchor>ema[3]),
        (raw['return3']<0)&(raw['return10']<0)&(p3<0)&(ema[3]<ema[10])&(anchor<ema[3]),
        [raw['return3'],raw['return10'],p3,ema[3],ema[10]],'自己3/10分変化と先行NK3分方向一致。EMA3/10とanchor同向。')
    emit('M02','二市場','二市場の効率付き十分快走',(raw['return10']>0)&(p10>0)&(eff[10]>=.4)&(pe>=.4)&(sma[5]>sma[20])&(anchor>sma[5]),
        (raw['return10']<0)&(p10<0)&(eff[10]>=.4)&(pe>=.4)&(sma[5]<sma[20])&(anchor<sma[5]),
        [raw['return10'],p10,eff[10],pe,sma[5],sma[20]],'両市場10分変化一致、各efficiency10>=.4、自己SMA5/20とanchor同向。')
    emit('M03','二市場','先行市場後の自己転換',(p3>0)&(p10>0)&(past_return<=0)&(raw['return1']>0)&(anchor>sma[5]),
        (p3<0)&(p10<0)&(past_return>=0)&(raw['return1']<0)&(anchor<sma[5]),
        [p3,p10,past_return,raw['return1'],sma[5]],'先行NK3/10分一致、自己前3分は反対/中立、現在一分が同向転換しanchorがSMA5を維持。因果先導の証明でない。')
    emit('M04','二市場','帯離脱の先行市場確認',(close>hh[15])&(anchor>hh[15])&(p3>0)&(pe>=.3),
        (close<ll[15])&(anchor<ll[15])&(p3<0)&(pe>=.3),[hh[15],ll[15],p3,pe],
        '自己過去15分帯のclose/anchor離脱、先行NK3分が同向かつefficiency10>=.3。')
    # ----------------------------------------
    # 板・出来高4条件。closed足比を真の攻撃・同一主体補充へ読み替えない。
    bi=book['book_imbalance'];bd=book['book_depth'];bf=book['book_ofi']
    emit('Q01','板','最良と距離重み数量の合意',(bi>=.25)&(bd>=.25)&(ema[5]>ema[20])&(raw['return3']>0)&(anchor>ema[5]),
        (bi<=-.25)&(bd<=-.25)&(ema[5]<ema[20])&(raw['return3']<0)&(anchor<ema[5]),
        [bi,bd,ema[5],ema[20],raw['return3']],'閉足L1/depth imbalanceが同向±.25以上、EMA5/20と3分価格も同向。')
    emit('Q02','板','OFI付き短期MA再獲得',(bf>=.25)&(bi>=0)&(pc<=e8p)&(close>ema[8])&(anchor>ema[8]),
        (bf<=-.25)&(bi<=0)&(pc>=e8p)&(close<ema[8])&(anchor<ema[8]),
        [bf,bi,pc,e8p,ema[8]],'閉足正規化OFI±.25、L1比が反対でなく、前足からEMA8を再獲得。')
    emit('Q03','板','深さと最良の不一致後の離脱',(bd>=.25)&(bi<=0)&(bf>0)&(close>hh[10])&(anchor>hh[10]),
        (bd<=-.25)&(bi>=0)&(bf<0)&(close<ll[10])&(anchor<ll[10]),[bd,bi,bf,hh[10],ll[10]],
        '最良比は反対/中立でも距離重み比±.25とOFIが同向、現在過去10分帯を離脱。')
    vr=raw['volume_ratio5']
    emit('Q04','板','公表活動拡大と価格効率',(vr>=1.5)&(eff[5]>=.5)&(bf>0)&(ema[3]>ema[10])&(anchor>ema[3]),
        (vr>=1.5)&(eff[5]>=.5)&(bf<0)&(ema[3]<ema[10])&(anchor<ema[3]),[vr,eff[5],bf,ema[3],ema[10]],
        '完全既知出来高が過去5分平均の1.5倍以上、efficiency5>=.5、OFI/EMA3対10/anchorが同向。')
    # ----------------------------------------
    # 学習値には絶対価格を入れない。自己価格距離を10pt単位へ統一し、NKは割合/効率だけ使う。
    names=[];columns=[];feature_groups={};feature_notes={}
    for original,value in raw.items():
        name=original;note=notes[original]
        if original in ('close','peer_matchedNKclose','peer_age_seconds'):continue
        if original in ('open','high','low','anchor'):
            value=(value-close)/10.;name=original+'_minus_close_10pt';note='(当時値−確定close)/10pt。絶対価格は保持しない。'
        elif original.startswith(('ema','sma')):
            parts=original.split('_');kind=parts[0][:3];period=int(parts[0][3:]);bank=ema if kind=='ema' else sma
            if len(parts)==1:value=(bank[period]-close)/10.;note='(当時MA−確定close)/10pt。全16期間を計算し未知を区別。'
            elif parts[1]=='gap':value=(np.where(decision,anchor,np.nan)-bank[period])/10.;note='(現在anchor−当時MA)/10pt。'
            else:
                past=int(parts[1][5:]);value=(bank[period]-_lag(bank[period],past,run))/10.;note=f'MAの過去{past}分変化/10pt。'
            name=original+'_10pt'
        elif original.startswith('return'):
            period=int(original[6:]);value=(close-_lag(close,period,run))/10.;name=original+'_10pt';note=f'確定closeの過去{period}分変化/10pt。'
        elif original.startswith(('ribbon_','prior_range')) or original in ('bar_body','bar_range'):
            value=value*close/10.;name=original+'_10pt';note='自己価格幅/10pt。ATR又は絶対価格ではない。'
        elif original.startswith('close_std'):
            value=value/10.;name=original+'_10pt';note='確定close標準偏差/10pt。'
        elif original.startswith('close_volume_proxy'):
            value=(value-close)/10.;name=original+'_minus_close_10pt';note='(確定close出来高加重proxy−close)/10pt。真の約定VWAPではない。'
        elif original.startswith('close_volume_gap'):
            period=int(original[len('close_volume_gap'):]);proxy=raw[f'close_volume_proxy{period}']
            value=(np.where(decision,anchor,np.nan)-proxy)/10.;name=original+'_10pt';note='(現在anchor−確定close出来高加重proxy)/10pt。'
        known=np.isfinite(value);columns.extend((np.where(known,value,0.),known.astype(float)));names.extend((name,name+'_known'))
        feature_groups[name]=groups[original];feature_groups[name+'_known']=groups[original]
        feature_notes[name]=note;feature_notes[name+'_known']='対応数値の既知1/未知0。数値0の代用と実測0を区別する。'
    x=np.column_stack(columns) if columns else np.empty((n,0))
    signal=np.column_stack(signals).astype(np.int8);assert signal.shape==(n,32) and np.isfinite(x).all()
    assert len(set(names))==len(names) and len(specs)==len({s['id'] for s in specs})==32
    return dict(X=x,names=names,feature_groups=feature_groups,feature_notes=feature_notes,signals=signal,specifications=specs,
        candidate_known=np.column_stack(candidate_known),decision_valid=decision.copy(),periods=list(PERIODS),
        ema=np.column_stack([ema[p] for p in PERIODS]),sma=np.column_stack([sma[p] for p in PERIODS]),
        definitions=dict(missing='数値0+known0は未知の符号化。signalは必要known必須。観測値0とは別。',
            warmup='価格欠分で全価格MA/rollingをreset。出来高/板/peerだけの欠測で価格MAをresetしない。EMAseedはp本SMA。',
            time='全一分grid、確定足のみ。公開anchorは現在原rowLast。NKは自己足より最低一足先行。',
            ml='feature_groupsはprice/ma/volume/book/peer。自己価格は10pt距離、NKは割合/効率。絶対価格/日時/行番号/未来目的変数を含めない。相関するMAは独立証拠でない。',
            scope='純特徴/仮説生成。到達・先着・金融・心理の証明や学習結果ではない。ATR不使用。'))


def specifications() -> list[dict]:
    """
    機能: 結果や入力本文を使わず、事前固定32候補の定義を取得する。
    引数: なし。
    返り値: list[dict] はprepareと同じ32仕様。0足の純定義経路で取得し外部IOを行わない。
    """
    bars={name:np.empty(0,dtype=bool if name in ('valid','volume_known','book_quote_valid') else np.int64 if name=='pub_raw_row' else float) for name in BAR_FIELDS}
    other={name:np.empty(0,dtype=bool if name=='matchedNKknown' else float) for name in PEER_FIELDS}
    return prepare(bars,other)['specifications']
