"""既存の公開済み30秒中値変化を、保持せず最新観測として対応させる。"""
import numpy as np


def event_model(ready, frame):
    """
    機能: 元入口と同じ公開時刻基準の30秒中値差を再計算する。
    引数: ready(dict)、frame(DataFrame)。
    返り値: dict[str,ndarray]。窓終端の元行と公開時刻を別々に保存する。
    """
    f=frame.loc[(frame.seq<=ready['seq'][-1])&(frame.time_s<=ready['time_s'][-1])]
    release=f.time_s.to_numpy(float);seq=f.seq.to_numpy(np.int64)
    source_seq=f.source_last_seq.to_numpy(np.int64);source_time=f.source_time_s.to_numpy(float)
    mid=f.source_mid_last.to_numpy(float)
    assert np.all(np.diff(seq)>0) and np.all(np.diff(release)>0)
    assert np.all(source_seq<seq) and np.all(source_time<=release)
    prior=np.searchsorted(release,release-30.,side='right')-1
    ai=np.searchsorted(ready['seq'],seq,side='right')-1
    a=np.where(ai>=0,ready['atr'][np.maximum(ai,0)],np.nan)
    value=np.full(len(seq),np.nan)
    ok=(prior>=0)&np.isfinite(a)&(a>0)&np.isfinite(mid)&(mid>0)
    ok &= np.isfinite(mid[np.maximum(prior,0)]) & (mid[np.maximum(prior,0)]>0)
    value[ok]=(mid[ok]-mid[prior[ok]])/a[ok]
    return dict(release=release,seq=seq,source_seq=source_seq,source_time=source_time,
        value=value,valid=ok,prior_event=prior,atr=a,mid=mid)


def expand(ready, own, peer):
    """
    機能: 自己は公開行順、相手は厳密過去の公開時刻だけから現在の支持を得る。
    引数: ready/own/peer(dict)。
    返り値: dict[str,ndarray]。新しい時間鮮度閾値は付加しない。
    """
    output={}
    for name,model in (('self',own),('peer',peer)):
        index=(np.searchsorted(model['seq'],ready['seq'],side='right')-1 if name=='self'
            else np.searchsorted(model['release'],ready['time_s'],side='left')-1)
        safe=np.maximum(index,0)
        valid=(index>=0)&model['valid'][safe]
        if name=='self':
            assert np.all(model['seq'][safe[index>=0]]<=ready['seq'][index>=0])
        else:
            assert np.all(model['release'][safe[index>=0]]<ready['time_s'][index>=0])
        output[name+'_value']=np.where(valid,model['value'][safe],np.nan)
        output[name+'_valid']=valid
        output[name+'_source_seq']=np.where(index>=0,model['source_seq'][safe],-1)
        output[name+'_source_time']=np.where(index>=0,model['source_time'][safe],np.nan)
        output[name+'_release_time']=np.where(index>=0,model['release'][safe],np.nan)
        output[name+'_release_seq']=np.where(index>=0,model['seq'][safe],-1)
        output[name+'_event_index']=index
    return output
