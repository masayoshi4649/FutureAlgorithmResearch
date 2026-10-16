"""104の19入口から必要3入口だけを、106正常入力と完全対応して保存する。"""

import argparse
from copy import deepcopy
from pathlib import Path

import numpy as np

import common

HERE=Path(__file__).resolve().parent
ENTRIES=('C_OWN','C_N30','R_OWN')


def connect(old: dict, current: dict) -> dict:
    """
    機能: 新しい価格・将来行を足さず、104入口と106正常経済列を結ぶ。
    引数: old/current(dict)は104peerと106軽量packet。
    返り値: dictは3入口とpreparedだけの新cache。原seq・時刻・BBOを全行比較する。
    """
    assert old['session']==current['session'] and old['schema_version']==current['schema_version']==1
    result=dict(schema_version=1,session=current['session'],prepared=current['prepared'],cases={})
    for symbol in ('TOPIX','NK225'):
        left,right=old['normal'][symbol]['record'],current['prepared'][symbol]['record']
        assert set(left)==set(right)
        for key in left:
            if isinstance(left[key],np.ndarray): np.testing.assert_array_equal(left[key],right[key],err_msg=key)
            else: assert left[key]==right[key],key
    for entry in ENTRIES:
        result['cases'][entry]={}
        for symbol in ('TOPIX','NK225'):
            value=old['cases'][entry][symbol]['normal']
            n=len(result['prepared'][symbol]['record']['seq'])
            assert value['event'].shape==(n,) and value['entry_id']==entry
            if entry!='R_OWN':
                for key in value:
                    original=current['cases'][entry][symbol][key]
                    if isinstance(value[key],np.ndarray): np.testing.assert_array_equal(value[key],original,err_msg=entry+key)
                    else: assert value[key]==original,entry+key
            result['cases'][entry][symbol]=value
    return result


def run() -> None:
    """
    機能: 明示許可された入力準備を33場各一読取で完了する。
    引数: なし。
    返り値: None。B4の金融を一回も呼ばず、新入力manifestだけ保存する。
    """
    target=HERE/'全33の固定配分入力.json';assert not target.exists()
    prior=common.read(common.ROOT/'work/wave_v104/入口準備の全32結果.json')
    added=common.read(common.ROOT/'work/wave_v104/holdout_input/追加Dayの活動と19入口.json')
    now=common.read(common.WAVE/'input/全33場の因果特徴準備.json')
    assert prior['全合格'] and added['全合格'] and now['全合格']
    start={str(p.relative_to(common.ROOT)):common.digest(p) for p in (Path(__file__),HERE/'common.py')}
    caches={}
    for session in sorted(now['sessions']):
        if session in prior['cache']:
            old=common.unpack(prior['cache'][session]); old_ref=prior['cache'][session]
        else:
            assert session==added['session']; large=common.unpack(added);old=large['peer'];old_ref={'path':added['path'],'SHA256':added['SHA256']}
        current=common.unpack(now['cache'][session])
        packet=connect(old,current)
        path=HERE/'input'/f'{session}.pkl.gz'
        sha=common.pack(path,packet)
        caches[session]=dict(path=str(path.relative_to(common.ROOT)),SHA256=sha,
            old_source=deepcopy(old_ref),current_source=deepcopy(now['cache'][session]),
            shapes={s:len(packet['prepared'][s]['record']['seq']) for s in ('TOPIX','NK225')})
        print(session+'：3入口・2商品、正常原seq/時計/BBO/資格と旧C入口一致、金融0',flush=True)
        del packet,current,old
        if session==added['session']:del large
    assert start=={p:common.digest(common.ROOT/p) for p in start}
    common.save(target,dict(全合格=True,sessions=sorted(now['sessions']),対象場数=33,口座数=66,
        入口=list(ENTRIES),cache=caches,source_SHA256=start,開始終端source一致=True,
        既104packet読取=33,各場一読取=True,既106packet読取=33,新金融再生=0,原板読取=0,
        NPZ読取=0,API取得=0,旧source変更=0))


def load_session(session: str) -> dict:
    """
    機能: 完了済み固定配分入力cacheを一回読む。
    引数: session(str)は場名。
    返り値: dictはprepared/cases、全配列readonly。旧大packetを再読しない。
    """
    metadata=common.read(HERE/'全33の固定配分入力.json')
    assert metadata['全合格'] and metadata['対象場数']==33 and metadata['新金融再生']==0
    for p,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha
    result=common.unpack(metadata['cache'][session]);common.immutable(result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='固定配分の入力だけを準備する')
    parser.add_argument('--root-input-preparation-approved',action='store_true',required=True)
    parser.parse_args();run()
