"""元C/R候補を維持し、価格状態の観測資格だけを数量と分離する。"""

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


def build(old: dict, previous: dict) -> dict:
    """
    機能: 既104原seqから純価格6点を測り、保存済みC/R入口と正常執行列を維持する。
    引数: old/previous(dict)は旧104peerとgapだけ版の同場packet。
    返り値: dictはprepared/cases/measured。原本抽出も元候補の再生成も行わない。
    """
    assert old['session']==previous['session']
    result=dict(schema_version=4,session=old['session'],prepared=previous['prepared'],cases=previous['cases'],measured={})
    contexts={s:features.context(old['raw'][s],old['peer_features'][s]['public'],
        float(previous['prepared'][s]['record']['start']),float(previous['prepared'][s]['record']['limit'])) for s in ('TOPIX','NK225')}
    for symbol in ('TOPIX','NK225'):
        record=previous['prepared'][symbol]['record'];raw=old['raw'][symbol];mapping=raw['execution_to_raw_index']
        for a,b in (('seq','raw_seq'),('time_s','price_time_s'),('bid','bid'),('ask','ask')):
            np.testing.assert_array_equal(record[a],raw[b][mapping])
        for entry in ('C_OWN','R_OWN'):
            original=old['cases'][entry][symbol]['normal'];current=result['cases'][symbol][entry]
            for key,value in original.items():
                if isinstance(value,np.ndarray):np.testing.assert_array_equal(value,current[key])
                else:assert value==current[key]
        measured={};other='NK225' if symbol=='TOPIX' else 'TOPIX'
        for row in previous['measured'][symbol]:
            row=int(row);rawrow=int(mapping[row]);stamp=float(record['time_s'][row])
            own=features.sample(raw,contexts[symbol],stamp,record['tick'],rawrow,False)
            peer=features.sample(old['raw'][other],contexts[other],stamp,previous['prepared'][other]['record']['tick'],None,True)
            measured[row]=dict(row=row,raw_row=rawrow,raw_seq=int(record['seq'][row]),clock=stamp,
                own=own,peer=peer,current_bid=float(record['bid'][row]),current_ask=float(record['ask'][row]))
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
    機能: 同じ33場の旧104素材とgap版を各一回読んで純価格特徴を保存する。
    引数: なし。
    返り値: None。原板、旧portfolio、NPZ、金融は読取・再生しない。
    """
    target=HERE/'全33の候補当時純価格6点特徴.json';assert not target.exists()
    metadata=common.read(common.WAVE/'regime_sample/全33の候補当時6点サンプル修正.json');assert metadata['全合格']
    assert common.digest(EVIDENCE)==EVIDENCE_SHA
    for path,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/path)==sha
    paths=[HERE/n for n in ('common.py','features.py','prepare.py','catalog.py')]
    start={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}
    cache={};activities={}
    for session in metadata['sessions']:
        item=metadata['cache'][session];olditem=item['strict_source']['old_source']
        source=common.unpack(olditem);old=source['peer'] if 'peer' in source else source
        previous=common.unpack(item);packet=build(old,previous)
        path=HERE/'input_v2'/f'{session}.pkl.gz';sha=common.pack(path,packet)
        cache[session]=dict(path=str(path.relative_to(common.ROOT)),SHA256=sha,old_source=olditem,sample_source=item)
        activities[session]=activity(packet)
        print(session+'：純価格6点と元C/R候補の同原行対応を保存、金融0',flush=True)
        del source,old,previous,packet
    assert start=={p:common.digest(common.ROOT/p) for p in start}
    common.save(target,dict(全合格=True,sessions=metadata['sessions'],cache=cache,activity=activities,
        source_SHA256=start,開始終端source一致=True,旧gap修正cache読取=33,旧104cache読取=33,旧portfolio再読取=0,
        原板読取=0,NPZ読取=0,新金融再生=0,API取得=0,
        SHA256={str((common.WAVE/'regime_sample/全33の候補当時6点サンプル修正.json').relative_to(common.ROOT)):
            common.digest(common.WAVE/'regime_sample/全33の候補当時6点サンプル修正.json'),str(EVIDENCE.relative_to(common.ROOT)):EVIDENCE_SHA},
        資格='6点finite正bid/ask・ask>bid・場内有限価格時計・asof15秒、原seq断裂と全既知価格時計highwaterへの逆行。量/出来高/混合reset、公表gap、途中BBO不正は価格資格にしない。',
        限界=['6点sample ERであり、間の全quote経路を測っていない。',
            '価格資格を分離しても保存素材の欠測は回復しない。非normal BBOのNaN端点はUNKNOWNのまま。',
            'CurrentPriceTimeは板受信時計ではない。相手strictpast asofは保持する。',
            'C/R入口の元quantity/volume根拠、支持価格とepisode系譜は変更しない。']))


def load_session(session: str) -> dict:
    """
    機能: 完了した修正特徴を一回読取り、実行入力をreadonlyへ戻す。
    引数: session(str)は場名。
    返り値: dictはprepared/cases/measured。旧大cacheや原板を暗黙に読まない。
    """
    metadata=common.read(HERE/'全33の候補当時純価格6点特徴.json')
    assert metadata['全合格'] and metadata['新金融再生']==metadata['原板読取']==0
    for p,sha in metadata['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha
    value=common.unpack(metadata['cache'][session]);common.immutable(value);return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='旧当時入力から観測定義だけ訂正する')
    parser.add_argument('--root-input-preparation-approved',action='store_true',required=True)
    parser.parse_args();run()
