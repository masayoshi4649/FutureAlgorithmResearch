"""旧strictの同じ6原行だけから、価格時計停滞の誤定義を除いた当時特徴を派生する。"""

import argparse
from copy import deepcopy
from pathlib import Path

import numpy as np

import catalog
import common
import features

HERE=Path(__file__).resolve().parent
STRICT=common.WAVE/'regime'
EVIDENCE=common.WAVE/'e01_pair_filter/UNKNOWN観測定義と原fieldの監査.json'
EVIDENCE_SHA='8c2df9b3e9181cfc7cee83045e08c42c2a3b8cd5618b5a1992cd6d3d3c6f01b9'


def derive_measure(old: dict, record: dict) -> dict:
    """
    機能: 旧測定のgap理由だけを外し、当初選択された6原行のBBOで再計算する。
    引数: old(dict)はstrict測定、record(dict)は同場の商品正常列。
    返り値: dictは新測定。別理由がある場合はUNKNOWNを維持し、未来正常行へ移さない。
    """
    result=deepcopy(old);reason=int(old['reason']);result['reason']=reason&~16
    if reason==0 or result['reason']!=0:return result
    assert reason==16 and len(old['raw_seq'])==6
    seq=np.asarray(old['raw_seq'],np.int64);rows=np.searchsorted(record['seq'],seq)
    assert np.all(rows<len(record['seq']))
    np.testing.assert_array_equal(record['seq'][rows],seq)
    np.testing.assert_array_equal(record['time_s'][rows],np.asarray(old['times']))
    bid,ask=record['bid'][rows],record['ask'][rows]
    assert np.all(record['quote_valid'][rows]&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid))
    mids=(bid+ask)/2.;net=float(mids[-1]-mids[0]);tv=float(np.abs(np.diff(mids)).sum())
    high,low=float(mids.max()),float(mids.min())
    result.update(known=True,midpoint=mids.tolist(),ER=abs(net)/tv if tv>0 else None,
        return_bp=net/mids[0]*10000.,span_ticks=(high-low)/record['tick'],
        high=high,low=low,centre=(high+low)/2.,TV=tv)
    return result


def derive_packet(old: dict) -> dict:
    """
    機能: 保存済みpreparedとC/R元候補をそのまま使い、当時特徴のみ別dictへ派生する。
    引数: old(dict)は旧strict一場packet。
    返り値: dictは同じshapeと系譜を持つgap修正版。入口イベントを新造しない。
    """
    result=dict(schema_version=2,session=old['session'],prepared=old['prepared'],cases=old['cases'],measured={})
    for symbol in ('TOPIX','NK225'):
        other='NK225' if symbol=='TOPIX' else 'TOPIX';measured={}
        for row,pair in old['measured'][symbol].items():
            current=deepcopy(pair)
            current['own']=derive_measure(pair['own'],old['prepared'][symbol]['record'])
            current['peer']=derive_measure(pair['peer'],old['prepared'][other]['record'])
            measured[row]=current
        result['measured'][symbol]=measured
    return result


def activity(packet: dict) -> dict:
    """
    機能: 全固定条件で分類と入口余地の件数だけを数え、金融を再生しない。
    引数: packet(dict)は当時6点と元C/R候補。
    返り値: dictは商品別候補数/known数/条件別採否件数。利益や将来正答率は読まない。
    """
    result={}
    for symbol in ('TOPIX','NK225'):
        p=packet['prepared'][symbol];c,r=(packet['cases'][symbol][e] for e in ('C_OWN','R_OWN'))
        measured=packet['measured'][symbol];counts={}
        for config in catalog.catalog():
            states={};reasons={};chosen={'C':0,'R':0}
            for row,pair in measured.items():
                state=features.classify(pair,config['trend_bp'],config['range_er'])
                states[state]=states.get(state,0)+1;reason=state;family=None
                if state=='RANGE':
                    if config['mode']=='C_ONLY':reason='modeでRを使わない'
                    elif not r['event'][row]:reason='RANGEだが新R候補なし'
                    else:
                        order=features.range_order(p,r,row,pair['own'],config['quantity'][symbol])
                        if order['allowed']:family='R';reason='RANGEでR許可'
                        else:reason=order['reason']
                elif state in ('TREND_UP','TREND_DOWN'):
                    direction=1 if state=='TREND_UP' else -1
                    if config['mode']=='R_ONLY':reason='modeでCを使わない'
                    elif int(c['event'][row])!=direction:reason='共通方向に一致する新C候補なし'
                    else:family='C';reason='双方進行でC許可'
                reasons[reason]=reasons.get(reason,0)+1
                if family:chosen[family]+=1
            counts[config['id']]=dict(states=states,reasons=reasons,chosen=chosen)
        result[symbol]=dict(candidate_rows=len(measured),
            both_known=sum(v['own']['known'] and v['peer']['known'] for v in measured.values()),conditions=counts)
    return result


def run() -> None:
    """
    機能: 旧strictの33cache各一回から派生入力と活動証跡を新所有域へ保存する。
    引数: なし。
    返り値: None。旧104/portfolio大packet、原板、金融は再読取・再生しない。
    """
    target=HERE/'全33の候補当時6点サンプル修正.json';assert not target.exists()
    metadata=common.read(STRICT/'全33の候補当時6点特徴.json');assert metadata['全合格']
    assert common.digest(EVIDENCE)==EVIDENCE_SHA
    for path,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/path)==sha
    paths=[HERE/n for n in ('common.py','features.py','prepare.py','catalog.py')]
    start={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}
    cache={};activities={};new_known={s:0 for s in ('TOPIX','NK225')}
    for session in metadata['sessions']:
        old=common.unpack(metadata['cache'][session]);packet=derive_packet(old)
        path=HERE/'input'/f'{session}.pkl.gz';sha=common.pack(path,packet)
        cache[session]=dict(path=str(path.relative_to(common.ROOT)),SHA256=sha,strict_source=metadata['cache'][session])
        activities[session]=activity(packet)
        for s in new_known:new_known[s]+=activities[session][s]['both_known']-metadata['activity'][session][s]['both_known']
        print(session+'：6点当時入力のgap理由だけを訂正、金融0',flush=True)
        del old,packet
    assert start=={p:common.digest(common.ROOT/p) for p in start}
    common.save(target,dict(全合格=True,sessions=metadata['sessions'],cache=cache,activity=activities,
        source_SHA256=start,開始終端source一致=True,旧strictcache読取=33,旧104cache読取=0,旧portfolio再読取=0,
        原板読取=0,新金融再生=0,API取得=0,修正だけによる新known数=new_known,
        SHA256={str((STRICT/'全33の候補当時6点特徴.json').relative_to(common.ROOT)):common.digest(STRICT/'全33の候補当時6点特徴.json'),
                str(EVIDENCE.relative_to(common.ROOT)):EVIDENCE_SHA},
        資格='6端点qualified/BBO・asof15秒と区間clock/seq/price_resetは維持。間の公表gapを板断絶へ代用しない。',
        限界='6点sample ERであり、間の全quote経路・板受信時計・真の売買方向を保証しない。'))


def load_session(session: str) -> dict:
    """
    機能: 完了した修正特徴を一回読取り、実行入力をreadonlyへ戻す。
    引数: session(str)は場名。
    返り値: dictはprepared/cases/measured。旧大cacheや原板を暗黙に読まない。
    """
    metadata=common.read(HERE/'全33の候補当時6点サンプル修正.json')
    assert metadata['全合格'] and metadata['新金融再生']==metadata['原板読取']==0
    for p,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha
    value=common.unpack(metadata['cache'][session]);common.immutable(value);return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='旧当時入力から観測定義だけ訂正する')
    parser.add_argument('--root-input-preparation-approved',action='store_true',required=True)
    parser.parse_args();run()
