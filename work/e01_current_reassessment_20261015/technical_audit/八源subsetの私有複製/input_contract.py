"""二cacheの同原行と公開票を厳密照合する私有写し。paper方向や元PUBを新候補に使わない。"""

from collections import Counter
import math
import numpy as np

SYMBOLS=('TOPIX','NK225')
WINDOWS=('10','30','60')


def equal(left: object,right: object,label: str) -> None:
    """
    機能: 型・shapeと保存欠測位置を含め、二つの同原行値を照合する。
    引数: left/right(object)、label(str) は値と検査名。
    返り値: None。不一致はAssertionErrorとし別rowへ差替えない。
    """
    if isinstance(left,np.ndarray) or isinstance(right,np.ndarray):
        assert isinstance(left,np.ndarray) and isinstance(right,np.ndarray),label
        assert left.shape==right.shape and left.dtype==right.dtype,label
        np.testing.assert_array_equal(left,right,err_msg=label)
    else:assert left==right,label


def validate_public(account: dict,votes: dict,row: int,side: int,window: str) -> None:
    """
    機能: 公開scalar票と全normal票を、未知debug・既知零票・符号一回まで照合する。
    引数: account/votes(dict)、row/side(int)、window(str) は同原行の公開と窓。
    返り値: None。欠測基準seqや最後の実方向票を推定しない。
    """
    value=account['trade_features'][window][row];r=account['record'];mapping=account['mapping']
    assert value['window_seconds']==int(window)
    assert bool(votes['known'][row])==bool(value['known']) and int(votes['reason'][row])==int(value['reason'])
    assert value['candidate_raw_row']==int(mapping[row]) and value['candidate_raw_seq']==int(r['seq'][row])
    assert value['candidate_price_time_s']==float(r['time_s'][row])
    assert value['cutoff_price_time_s']==float(r['time_s'][row])-int(window)
    for name in ('reference_raw_row','first_vote_raw_row'):
        expected=-1 if value[name] is None else int(value[name])
        assert int(votes[name][row])==expected,name
    up=int(votes['up_votes'][row]);down=int(votes['down_votes'][row]);total=up+down
    assert up==int(value['measured_up_votes']) and down==int(value['measured_down_votes'])
    if value['known']:
        assert value['up_votes']==up and value['down_votes']==down and value['direction_votes']==total
        if total:
            assert math.isfinite(float(votes['balance'][row]))
            assert math.isclose(side*float(votes['balance'][row]),value['balance'],rel_tol=0.,abs_tol=1e-12)
        else:assert value['balance'] is None and np.isnan(votes['balance'][row])
    else:
        assert all(value[name] is None for name in ('up_votes','down_votes','direction_votes','balance'))
        assert np.isnan(votes['balance'][row])


def strict_join(gate: dict,exit_packet: dict) -> dict:
    """
    機能: 同sessionのrecord・両BBO・原行map・各窓・公開票を全一致させる。
    引数: gate/exit_packet(dict) は各一読の保存TradeGate/TradeExit。
    返り値: dict は検査数。型や列が不足すれば診断前に停止する。
    """
    assert gate['schema_version']==exit_packet['schema_version']==1
    assert gate['session']==exit_packet['session'] and set(gate['accounts'])==set(exit_packet['accounts'])==set(SYMBOLS)
    checks=Counter()
    for symbol in SYMBOLS:
        a=gate['accounts'][symbol];b=exit_packet['accounts'][symbol]
        assert a['symbol']==b['symbol']==symbol
        r,q=a['record'],a['quotes'];n=len(r['price']);assert n>0
        for name in ('price','seq','time_s','start','end','limit','tick'):
            equal(r[name],b['record'][name],symbol+' record '+name);checks['record全項目一致']+=1
        for name in ('bid','ask','quote_valid','seq','time_s'):
            equal(q[name],b['quotes'][name],symbol+' quote '+name);checks['quote全項目一致']+=1
        for name in ('seq','time_s'):equal(r[name],q[name],symbol+' record/quote '+name)
        assert all(len(r[name])==n for name in ('price','seq','time_s'))
        assert all(len(q[name])==n for name in ('bid','ask','quote_valid','seq','time_s'))
        assert np.all(np.isfinite(r['time_s'])) and np.all(r['time_s'][1:]>=r['time_s'][:-1])
        assert np.issubdtype(r['seq'].dtype,np.integer) and np.all(r['seq'][1:]>r['seq'][:-1])
        mapping=a['mapping'];assert mapping.shape==(n,) and np.issubdtype(mapping.dtype,np.integer)
        assert np.all(mapping>=0) and np.all(mapping[1:]>mapping[:-1])
        for name in ('quiet','quiet_force'):assert a[name].shape==(n,) and a[name].dtype==np.dtype(bool)
        feed=a['feed'];assert feed.ndim==2 and feed.shape[1]==10 and np.all(np.isfinite(feed))
        assert np.all(feed[:,0]==np.floor(feed[:,0])) and np.all((feed[:,0]>=0)&(feed[:,0]<n))
        assert np.all(feed[1:,0]>=feed[:-1,0])
        public=feed[feed[:,7]==1];assert len(set(public[:,0]))==len(public)
        assert set(b['votes'])==set(WINDOWS) and set(a['trade_features'])==set(WINDOWS)
        for window in WINDOWS:
            v=b['votes'][window]
            for name in ('known','reason','up_votes','down_votes','balance','reference_raw_row','first_vote_raw_row','candidate_raw_row','candidate_raw_seq','candidate_price_time_s'):
                assert isinstance(v[name],np.ndarray) and v[name].shape==(n,),name
            equal(v['candidate_raw_row'],mapping,symbol+' candidate/map')
            equal(v['candidate_raw_seq'],r['seq'],symbol+' candidate/seq')
            equal(v['candidate_price_time_s'],r['time_s'],symbol+' candidate/clock')
            assert v['known'].dtype==np.dtype(bool) and np.all(v['known']==(v['reason']==0))
            assert np.all(v['up_votes']>=0) and np.all(v['down_votes']>=0)
            total=v['up_votes'].astype(np.int64)+v['down_votes'];usable=v['known']&(total>0)
            assert np.all(np.isnan(v['balance'][~usable]))
            np.testing.assert_allclose(v['balance'][usable],(v['up_votes'][usable].astype(float)-v['down_votes'][usable])/total[usable],atol=0.,rtol=0.)
            assert set(a['trade_features'][window])=={int(o[0]) for o in public}
            for order in public:
                row,side=int(order[0]),int(order[3]);assert side in (-1,1)
                validate_public(a,v,row,side,window);checks['公開窓scalar全normal一致']+=1
        checks['商品原行資格照合']+=1
    return dict(checks)


