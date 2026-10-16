"""既104価格時計と既106経済入力から、候補当時の6点特徴だけを保存する。"""

import argparse
from pathlib import Path

import numpy as np

import common
import features

HERE=Path(__file__).resolve().parent


def build(old: dict, portfolio: dict) -> dict:
    """
    機能: 同原seq/時計/BBOを確認し、C/R新候補rowに当時両市場の6点を付ける。
    引数: old/portfolio(dict)は既104peerと完了済み106配分入力。
    返り値: dictはprepared/cases/measured。閾値判断や注文は行わない。
    """
    assert old['session']==portfolio['session']
    result=dict(schema_version=1,session=old['session'],prepared=portfolio['prepared'],cases={},measured={})
    contexts={s:features.context(old['raw'][s],old['peer_features'][s]['public']) for s in ('TOPIX','NK225')}
    for symbol in ('TOPIX','NK225'):
        record=portfolio['prepared'][symbol]['record'];raw=old['raw'][symbol]
        mapping=raw['execution_to_raw_index']
        for a,b in (('seq','raw_seq'),('time_s','price_time_s'),('bid','bid'),('ask','ask')):
            np.testing.assert_array_equal(record[a],raw[b][mapping])
        result['cases'][symbol]={e:portfolio['cases'][e][symbol] for e in ('C_OWN','R_OWN')}
        for e in result['cases'][symbol]:
            original=old['cases'][e][symbol]['normal'];current=result['cases'][symbol][e]
            for k in original:
                if isinstance(original[k],np.ndarray):np.testing.assert_array_equal(original[k],current[k])
                else:assert original[k]==current[k]
        c,r=(result['cases'][symbol][e] for e in ('C_OWN','R_OWN'))
        rows=np.flatnonzero((c['event']!=0)|(r['event']!=0));other='NK225' if symbol=='TOPIX' else 'TOPIX'
        measured={}
        for row in rows:
            row=int(row);rawrow=int(mapping[row]);stamp=float(record['time_s'][row])
            own=features.sample(raw,contexts[symbol],stamp,record['tick'],rawrow,False)
            peer=features.sample(old['raw'][other],contexts[other],stamp,old['items'][other]['tick'],None,True)
            measured[row]=dict(row=row,raw_row=rawrow,raw_seq=int(record['seq'][row]),clock=stamp,
                own=own,peer=peer,current_bid=float(record['bid'][row]),current_ask=float(record['ask'][row]))
        result['measured'][symbol]=measured
    return result


def run() -> None:
    """
    機能: 明示した入力準備だけを各33場2cache読取で完了する。
    引数: なし。
    返り値: None。金融は生成しない。既input・原本は変更しない。
    """
    target=HERE/'全33の候補当時6点特徴.json';assert not target.exists()
    metadata=common.read(common.WAVE/'portfolio/全33の固定配分入力.json');assert metadata['全合格']
    start={str(p.relative_to(common.ROOT)):common.digest(p) for p in (HERE/'common.py',HERE/'features.py',Path(__file__))}
    caches={};activity={}
    for session in metadata['sessions']:
        item=metadata['cache'][session];source=common.unpack(item['old_source'])
        old=source['peer'] if 'peer' in source else source
        portfolio=common.unpack(item);packet=build(old,portfolio)
        path=HERE/'input'/f'{session}.pkl.gz';sha=common.pack(path,packet)
        caches[session]=dict(path=str(path.relative_to(common.ROOT)),SHA256=sha,old_source=item['old_source'],portfolio_source=item)
        activity[session]={s:dict(candidate_rows=len(packet['measured'][s]),
            both_known=sum(v['own']['known'] and v['peer']['known'] for v in packet['measured'][s].values())) for s in ('TOPIX','NK225')}
        print(session+'：当時6点/正常原行/元C/R候補対応を保存、金融0',flush=True)
        del source,old,portfolio,packet
    assert start=={p:common.digest(common.ROOT/p) for p in start}
    common.save(target,dict(全合格=True,sessions=metadata['sessions'],cache=caches,activity=activity,source_SHA256=start,
        開始終端source一致=True,旧104cache読取=33,既106portfolio入力読取=33,原板読取=0,新金融再生=0,API取得=0,
        資格='6公表点のqualified/BBO・age15秒、区間clock/reset/seqと公表gap15秒。観測外の非normal BBOは未知へ代用しない。'))


def load_session(session: str) -> dict:
    """
    機能: 完了した当時特徴を新cache一回だけ読み、配列をreadonlyへ戻す。
    引数: session(str)は場名。
    返り値: dictはprepared/cases/measured。原本や旧大packetへ再読しない。
    """
    metadata=common.read(HERE/'全33の候補当時6点特徴.json')
    assert metadata['全合格'] and metadata['新金融再生']==metadata['原板読取']==0
    for p,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha
    value=common.unpack(metadata['cache'][session]);common.immutable(value);return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='当時6点の候補特徴だけを準備する')
    parser.add_argument('--root-input-preparation-approved',action='store_true',required=True)
    parser.parse_args();run()
