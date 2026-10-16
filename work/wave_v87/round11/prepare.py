"""相手の無変更GU注文と、厳密過去の価格参照だけを接続する。"""
from pathlib import Path
import hashlib
import json
import pickle
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v85/observed/ledgers/E01_G_U.pkl'
SOURCE_RESULT=SOURCE.parent.parent/'results/E01_G_U.json'


def digest(path):
    """
    機能: 読取元のSHA256を計算する。
    引数: path(Path)。
    返り値: str。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def feed_from_ledger(ledger):
    """
    機能: 注文と新規時に公開済みの準備ATRだけを十列の素材へ変換する。
    引数: ledger(dict)。cycles/trades/将来収支は参照しない。
    返り値: ndarray[float,10列]。
    """
    orders=ledger['orders'];out=np.zeros((len(orders),10));out[:,:8]=orders
    preparations={int(x[0]):x for x in ledger['prepare_events']}
    links={int(x[0]):x for x in ledger['entry_preparations']}
    for j,o in enumerate(orders):
        if o[7]:
            link=links[int(o[2])];prep=preparations[int(link[2])]
            assert int(link[1])==int(o[0]) and int(prep[1])<=int(o[1])<int(o[0])
            assert prep[4]>0 and np.isfinite(prep[4])
            out[j,9]=prep[4]
    return out


def strict_refs(own_times,peer_times,peer_prices):
    """
    機能: 自己時計より厳密に過去の相手最新有効価格行を返す。
    引数: own_times/peer_times/peer_prices(ndarray)。
    返り値: ndarray[int32]。参照不能は-1、同時計は全て除外する。
    """
    assert np.all(np.diff(own_times)>=0) and np.all(np.diff(peer_times)>=0)
    good=np.flatnonzero(np.isfinite(peer_prices)&(peer_prices>0))
    if not len(good):return np.full(len(own_times),-1,np.int32)
    before=np.searchsorted(peer_times[good],own_times,side='left')-1
    refs=np.where(before>=0,good[np.maximum(before,0)],-1).astype(np.int32)
    valid=refs>=0
    assert np.all(peer_times[refs[valid]]<own_times[valid])
    return refs


def build(inputs):
    """
    機能: 全入力に相手原価格と凍結元GU注文を接続する。
    引数: inputs(dict[tuple,dict])。
    返り値: dict[tuple,dict]。新しい改修条件の損益は計算しない。
    """
    fingerprint=digest(SOURCE)
    saved=json.loads(SOURCE_RESULT.read_text(encoding='utf-8-sig'))
    assert saved['ledger_SHA256']==fingerprint
    ledgers=pickle.loads(SOURCE.read_bytes())
    feeds={key:feed_from_ledger(ledgers[key]) for key in inputs}
    result={}
    for key,own in inputs.items():
        other=(key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX');peer=inputs[other]
        result[key]=dict(time_s=peer['time_s'],last=peer['last'],seq=peer['seq'],feed=feeds[other],
            ref=strict_refs(own['time_s'],peer['time_s'],peer['last']),
            value=1000. if other[1]=='TOPIX' else 10.,fee=41.8 if other[1]=='TOPIX' else 11.,
            source_SHA256=fingerprint,symbol=other[1])
    return result
