"""旧二種類の固定packetを一回ずつ読み、純価格の全行可用性だけを保存する。"""

import argparse
from pathlib import Path

import numpy as np

import catalog
import common
import features
import selection


SOURCE=common.ROOT/'work/wave_v106/regime_price/全33の候補当時純価格6点特徴.json'
ARTIFICIAL=common.HERE/'範囲内反発とAUTO接頭及び料込RRの人工検査.json'
TARGET=common.HERE/'全33場の価格境界反発準備.json'
TIME_SOURCE=common.ROOT/'work/wave_v106/time_guard/time_windows.py'
time_filter=common.module('106価格反発用の不変J静観時計',TIME_SOURCE)


def sources() -> dict:
    """
    機能: 新入力のsourceと再利用する純価格/J観測部品を事前固定する。
    引数: なし。
    返り値: dict[str,str]はroot相対sourceとSHA256。
    """
    paths=[common.HERE/n for n in ('common.py','catalog.py','features.py','selection.py','prepare.py','data.py','input_artificial.py')]
    paths += [common.ROOT/'work/wave_v106/regime_price/features.py',TIME_SOURCE,common.ROOT/'work/wave_v85/time_filter.py']
    return {p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}


def quiet(record: dict) -> dict:
    """
    機能: 旧Jのみの予定静観と、対応する初観測行の既知開始timerをそのまま使う。
    引数: record(dict)は旧正常価格/時刻列。
    返り値: dictはactive/start_s/windows。米国開場Uは使わない。
    """
    value=time_filter.features(record,'J')
    return dict(active=value['quiet'],start_s=value['quiet_start_s'],windows=value['windows'])


def build(old: dict, previous: dict) -> tuple[dict,dict]:
    """
    機能: 全normalのsix点と実境界反発を測り、元候補/執行列と旧候補six値を照合する。
    引数: old/previous(dict)は同場旧104原行packetと確定純価格候補packet。
    返り値: tuple[dict,dict]は新軽量入力と一致件数。金融や数量根拠は変更しない。
    """
    assert old['session']==previous['session'];records={s:previous['prepared'][s]['record'] for s in ('TOPIX','NK225')}
    packet=dict(schema_version=1,session=old['session'],prepared=previous['prepared'],cases=previous['cases'],measured={},quiet={})
    checks=dict(原執行対応=0,旧候補値対応=0,旧C_R列対応=0)
    for symbol in ('TOPIX','NK225'):
        record=records[symbol];raw=old['raw'][symbol];mapping=raw['execution_to_raw_index']
        for a,b in (('seq','raw_seq'),('time_s','price_time_s'),('bid','bid'),('ask','ask')):
            np.testing.assert_array_equal(record[a],raw[b][mapping]);checks['原執行対応']+=1
        for entry in ('C_OWN','R_OWN'):
            original=old['cases'][entry][symbol]['normal'];current=packet['cases'][symbol][entry]
            for key,value in original.items():
                if isinstance(value,np.ndarray):np.testing.assert_array_equal(value,current[key])
                else:assert value==current[key],(symbol,entry,key)
            checks['旧C_R列対応']+=1
        measured=features.build(old['raw'],records,symbol)
        for row,expected in previous['measured'][symbol].items():
            row=int(row);index=int(measured['normal_sample_index'][row])
            own=features.at_row(measured['sample_tables']['own'],index,bool(measured['own_known'][row]),int(measured['own_reason'][row]))
            peer=features.at_row(measured['sample_tables']['peer'],index)
            assert own==expected['own'] and peer==expected['peer'],(symbol,row)
            assert int(record['seq'][row])==expected['raw_seq'];checks['旧候補値対応']+=1
        packet['measured'][symbol]=measured;packet['quiet'][symbol]=quiet(record)
    return packet,checks


def activity(packet: dict) -> dict:
    """
    機能: 二市場状態、範囲内反発、料込RRと受付内候補の数を全24条件で測る。
    引数: packet(dict)は保存前の当時観測と旧C入力。
    返り値: dictは候補可用性。保有/休止中の消費を含む実取引数や勝敗ではない。
    """
    result={}
    for symbol in ('TOPIX','NK225'):
        prepared=packet['prepared'][symbol];record=prepared['record'];m=packet['measured'][symbol];c=packet['cases'][symbol]['C_OWN']
        time=record['time_s'];window=(time>=record['start']+300)&(time<record['limit']-300)
        reception=window&~packet['quiet'][symbol]['active']&m['qok'];conditions={}
        for config in catalog.catalog():
            state=m['states'][str(config['range_er'])];R=selection.range_arrays(prepared,m,config)
            C=((state==2)&(c['event']==1))|((state==-2)&(c['event']==-1))
            C &= c['entry_quality']&~c['entry_reset']
            if config['mode']=='R_ONLY':C[:]=False
            reasons={str(code):int(np.count_nonzero((R['event']!=0)&(R['rejection']==code))) for code in range(1,6)}
            conditions[config['id']]=dict(全行状態={features.STATE_NAMES[k]:int(np.count_nonzero(state==k)) for k in features.STATE_NAMES},
                受付内状態={features.STATE_NAMES[k]:int(np.count_nonzero((state==k)&reception)) for k in features.STATE_NAMES},
                範囲内反発=int(np.count_nonzero(R['event'])),予定RR拒否=reasons,
                R許可=int(np.count_nonzero(R['allowed'])),R受付内=int(np.count_nonzero(R['allowed']&reception)),
                R受付内買=int(np.count_nonzero(R['allowed']&reception&(R['event']==1))),
                R受付内売=int(np.count_nonzero(R['allowed']&reception&(R['event']==-1))),
                C旧pulse選択=int(np.count_nonzero(C)),C受付内=int(np.count_nonzero(C&reception)),
                受付外またはJ静観R=int(np.count_nonzero(R['allowed']&~reception)))
        result[symbol]=dict(normal行=len(time),共有公表時計=len(m['sample_tables']['own']['stamps']),
            自己known=int(np.count_nonzero(m['own_known'])),相手known=int(np.count_nonzero(m['peer_known'])),
            双方known=int(np.count_nonzero(m['own_known']&m['peer_known'])),条件=conditions)
    return result


def register() -> dict:
    """
    機能: 小目録だけから対象33と全旧cache指紋、抽出禁止と書込先を事前登録する。
    引数: なし。
    返り値: dictは固定計画。旧大packetをまだ読まない。
    """
    meta=common.read(SOURCE);proof=common.read(ARTIFICIAL);assert meta['全合格'] and proof['全合格']
    for path,sha in proof['source_SHA256'].items():assert common.digest(common.ROOT/path)==sha,path
    plan=dict(全合格=True,sessions=meta['sessions'],cache=meta['cache'],source_SHA256=sources(),
        source_metadata=dict(path=SOURCE.relative_to(common.ROOT).as_posix(),SHA256=common.digest(SOURCE)),
        人工=dict(path=ARTIFICIAL.relative_to(common.ROOT).as_posix(),SHA256=common.digest(ARTIFICIAL)),
        条件=catalog.catalog(),金融再生=0,原本再読=0,API取得=0,
        入力読取='各場の旧104packetと純価格第二版packetを各1回、同bytesでhash。旧金融結果は読まない。',
        出力='新cache33＋全normal可用性。自己同時計末尾の不正は各候補原rowで再確認。')
    assert len(plan['sessions'])==33
    common.write(common.HERE/'価格境界反発の入力事前固定.json',plan);return plan


def run() -> None:
    """
    機能: 根レビュー済み指紋の一回準備を行い、失敗も所有域に残す。
    引数: なし。
    返り値: None。正式金融を開始せず、旧原本/旧cacheを変更しない。
    """
    assert not TARGET.exists();plan=common.read(common.HERE/'価格境界反発の入力事前固定.json')
    assert plan['source_SHA256']==sources();source_item=plan['source_metadata']
    assert common.digest(common.ROOT/source_item['path'])==source_item['SHA256']
    cache,activities,checks={},{},{}
    try:
        for session in plan['sessions']:
            item=plan['cache'][session];source=common.unpack(item['old_source']);old=source['peer'] if 'peer' in source else source
            previous=common.unpack(item);packet,checked=build(old,previous)
            activities[session]=activity(packet);checks[session]=checked
            path=common.HERE/'input'/f'{session}.pkl.gz';common.write(path,packet)
            cache[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path),
                old_source=item['old_source'],price_source=dict(path=item['path'],SHA256=item['SHA256']))
            print(session+'：全normalの価格境界と元C列対応、金融0',flush=True)
            del source,old,previous,packet
        assert plan['source_SHA256']==sources()
        common.write(TARGET,dict(全合格=True,sessions=plan['sessions'],cache=cache,activity=activities,一致検査=checks,
            source_SHA256=plan['source_SHA256'],開始終端source一致=True,旧104cache読取=33,旧純価格cache読取=33,
            新金融再生=0,旧金融結果読取=0,原板読取=0,API取得=0,
            事前固定SHA256=common.digest(common.HERE/'価格境界反発の入力事前固定.json'),
            注意=['候補件数は実注文/勝ち数ではない。無候補は勝ちとして扱わない。',
                '6点ERの間の全価格経路が往復した保証はない。CurrentPriceTimeは受信時刻ではない。',
                '非normal端点NaNは未来正常行へ差替えない。実当行midはsample範囲内限定。',
                '予定RRは丸め中心/停止と当時quoteの料込計算。次quote悪化後の実RRを保証しない。']))
    except BaseException as exc:
        common.write(common.HERE/'価格境界反発の入力準備失敗.json',dict(全合格=False,例外=repr(exc),完了場=list(cache),新金融再生=0))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='新価格反発の因果的全normal可用性を保存')
    parser.add_argument('--register-only',action='store_true')
    parser.add_argument('--root-range-input-reviewed',action='store_true')
    args=parser.parse_args()
    assert args.register_only != args.root_range_input_reviewed,'事前固定か根レビュー済み本準備を選ぶ'
    if args.register_only:register()
    else:run()
