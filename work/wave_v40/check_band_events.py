"""同価格帯の状態機械を人工公開だけで反証する。収益は計算しない。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import urllib.request

import numpy as np

import band_events as band


HERE=Path(__file__).resolve().parent
CHECKS=[]


def check(name: str, value: bool) -> None:
    """機能: 人工の期待状態を検査し、成功件数を保存する。

    引数: name(str)、value(bool)。返り値: なし(None)。不一致時は停止。
    """
    assert value,name
    CHECKS.append(name)


def denied(*args: object, **kwargs: object) -> None:
    """機能: 検査からの外部取得を拒否する。

    引数: 任意(object)。返り値: なし(None)、例外。
    """
    raise AssertionError('人工状態機械に通信は不要')


def fixture(mids: list[float] | None = None, quantities: list[float] | None = None,
            times: list[float] | None = None) -> dict:
    """機能: 固定売り帯102への2試行を含む人工の公開10段を作る。

    引数: mids/quantities/times(list[float]|None)。返り値: 公開API形式(dict)。
    """
    mids=[100.5,100.5,100.5,100.5,101.5,99.5,98.5,96.5,101.5,101.5,101.5,101.5,104.5] if mids is None else mids
    quantities=[20,20,10,15,15,10,20,20,100,95,96,96,100] if quantities is None else quantities
    assert len(mids)==len(quantities)
    n=len(mids);times=np.asarray(np.arange(n)*10. if times is None else times,float)
    bp=np.asarray([[m-.5-j for j in range(10)] for m in mids],float)
    ap=np.asarray([[m+.5+j for j in range(10)] for m in mids],float)
    bq=np.full((n,10),10.);aq=np.full((n,10),10.)
    for i in range(n):aq[i,ap[i]==102.]=quantities[i]
    return dict(seq=np.arange(n,dtype=np.int64)*11,ready_index=np.arange(n,dtype=np.int64)*5,
        time_s=times,atr=np.full(n,10.),bid_prices=bp,ask_prices=ap,bid_qty=bq,ask_qty=aq,
        price_valid=np.ones(n,bool),depth_valid=np.ones(n,bool),
        block_delay_seconds=np.full(n,10.),previous_release_gap=np.r_[np.nan,np.diff(times)],
        continuity_reset_count=np.zeros(n))


def run(events: dict, **kwargs: object) -> list[dict]:
    """機能: 人工例だけの待機0秒で、他は基準規則の列挙を呼ぶ。

    引数: events(dict)、kwargs(設定)。返り値: 全帯(list[dict])。
    """
    params=dict(warmup_seconds=0.);params.update(kwargs.pop('params',{}))
    return band.build(events,0.,float(kwargs.pop('limit',5000.)),1.,params=params,**kwargs)


def cut(events: dict, count: int) -> dict:
    """機能: 全入力列を同じ公開行で切断する。

    引数: events(dict)、count(int)。返り値: 独立の接頭辞(dict)。
    """
    return {key:value[:count].copy() for key,value in events.items()}


def projection(records: list[dict], seq: int) -> list[dict]:
    """機能: 指定原本行までに観測又は確定した情報だけを投影する。

    引数: records(list[dict])、seq(int)。返り値: 先読み照合用情報(list[dict])。
    将来の終端・完成比率を比較対象へ混ぜない。
    """
    result=[]
    for record in records:
        if record['created']['seq']>seq:continue
        item={key:deepcopy(record[key]) for key in ('band_id','direction','price','atr','tick','created','expires_at','seed')}
        item['events']=[deepcopy(event) for event in record['events'] if event['seq']<=seq]
        item['observed']=[[deepcopy(sample) for sample in trial['samples'] if sample['seq']<=seq]
                         for trial in record['trials'] if trial['start']['seq']<=seq]
        item['finished']=[deepcopy(trial) for trial in record['trials'] if trial['end'] is not None and trial['end']['seq']<=seq]
        result.append(item)
    return result


def mirror(events: dict, center: float = 250.) -> dict:
    """機能: 売り板と買い板を入れ替えて価格を左右反射する。

    引数: events(dict)、center(float)。返り値: 反射入力(dict)。
    """
    other=deepcopy(events)
    other['bid_prices']=center-events['ask_prices'];other['ask_prices']=center-events['bid_prices']
    other['bid_qty']=events['ask_qty'].copy();other['ask_qty']=events['bid_qty'].copy()
    return other


def normalize_reflection(records: list[dict], center: float = 250.) -> list[dict]:
    """機能: 反射出力の符号・価格を元座標へ戻して全記録を比較する。

    引数: records(list[dict])、center(float)。返り値: 元座標の記録(list[dict])。
    """
    result=deepcopy(records)
    for item in result:
        item['direction']*=-1;item['price']=center-item['price']
        item['seed']['momentum']*=-1;item['seed']['momentum_atr']*=-1
        for trial in item['trials']:
            for sample in trial['samples']:sample['mid']=center-sample['mid']
    return result


def basic_cases() -> None:
    """機能: 手計算した二試行の数量・価格・別公開を確認する。

    引数: なし。返り値: なし(None)。
    """
    events=fixture();records=run(events);check('基本は1帯',len(records)==1)
    record=records[0];first,last=record['trials']
    check('準備40秒・初回突破120秒',record['created']['time_s']==40 and record['terminal']['time_s']==120)
    check('別公開で正規突破',record['status']=='breakout' and record['terminal']['seq']>last['end']['seq'])
    check('試行1は40〜70秒',first['start']['time_s']==40 and first['end']['time_s']==70)
    check('試行2は80〜110秒',last['start']['time_s']==80 and last['end']['time_s']==110)
    check('終了行で離脱・次の別公開で再接近',record['away']['time_s']==70 and last['start']['seq']>record['away']['seq'])
    check('試行1の減少5増加10比2',first['decrease']==5 and first['increase_after_decrease']==10 and first['recovery_ratio']==2)
    check('試行2の減少5増加1比0.2',last['decrease']==5 and last['increase_after_decrease']==1 and last['recovery_ratio']==.2)
    check('押し返し0.55から0.05',first['maximum_pushback_atr']==.55 and last['maximum_pushback_atr']==.05)
    check('弱化を記録するが採否は返さない',record['features']['quantity_weakens'] and record['features']['price_weakens'] and 'accepted' not in record)
    check('行番号を混同しない',record['created']==dict(event_index=4,ready_index=20,seq=44,time_s=40.))
    check('JSONは非有限値なし',bool(json.dumps(records,ensure_ascii=False,allow_nan=False)))
    check('標準20分前に新帯なし',band.build(events,0.,5000.,1.)==[])
    check('価格反射で全記録一致',normalize_reflection(run(mirror(events)))==records)
    activity=band.summarize(records)
    check('帯と試行と公開回数の内訳',activity['bands']==1 and activity['trials_complete']==2 and activity['seed_sample_counts']=={'4':1})
    changed=deepcopy(events)
    for i,q in zip(range(4,8),(15.,25.,20.,22.)):
        changed['ask_qty'][i,changed['ask_prices'][i]==102]=q
    value=run(changed)[0]['trials'][0]
    check('最初の減少前の増加は回復へ加算しない',value['decrease']==5 and value['increase_after_decrease']==2 and value['recovery_ratio']==.4)
    changed=deepcopy(events)
    for i,q in zip(range(4,8),(15.,10.,20.,8.)):
        changed['ask_qty'][i,changed['ask_prices'][i]==102]=q
    value=run(changed)[0]['trials'][0]
    check('底の差でなく複数回の減少合計17を使う',value['decrease']==17 and value['increase_after_decrease']==10 and value['recovery_ratio']==10/17)
    changed=deepcopy(events);changed['atr'][5:]*=10
    value=run(changed)[0]
    check('準備ATRは試行中に更新しない',value['atr']==10 and value['features']==record['features'] and value['events']==record['events'])


def boundary_cases() -> None:
    """機能: 早過ぎ・期限等号・不明品質・再準備・部分観測を反証する。

    引数: なし。返り値: なし(None)。
    """
    base=fixture()
    for when in (5,11):
        changed=deepcopy(base);changed['bid_prices'][when]=np.arange(104.,94.,-1.);changed['ask_prices'][when]=np.arange(105.,115.)
        found=run(changed)[0]
        check(f'第{when}行の早過ぎ突破を救済しない',found['status']=='early_breakout' and found['terminal']['seq']==base['seq'][when])
        if when==11:check('試行2完成と同じ行の突破も早過ぎ',found['trials'][1]['complete'] and found['features']['two_trials_complete'])
    short=run(base,params=dict(expiry_seconds=70.))[0]
    check('期限等号は試行完了より先',short['status']=='expiry' and not short['trials'][-1]['complete'] and short['terminal']['time_s']==110)
    ended=run(base,limit=80.)[0]
    check('場末等号は再接近より先',ended['status']=='session_end' and len(ended['trials'])==1)
    partial=run(cut(base,10))[0]
    check('途中末尾で架空返済・失効なし',partial['status']=='open_at_data_end' and partial['terminal'] is None and partial['trials'][-1]['end'] is None)
    just_created=run(cut(base,5));activity=band.summarize(just_created)
    check('1公開だけの未完了試行を不足へ計上',activity['trials_incomplete']==1 and activity['trials_with_fewer_than_two_samples']==1)
    for name,field in (('数量品質','depth_valid'),('数量reset','continuity_reset_count')):
        changed=deepcopy(base);changed[field][5]=False if field=='depth_valid' else 1.
        found=run(changed)[0]
        check(name+'だけでは価格経路を中止しない',found['status']=='breakout' and found['features']['price_comparable'] and not found['features']['quantity_comparable'])
        check(name+'後に数量が戻っても試行を既知へ救済しない',found['trials'][0]['recovery_ratio'] is None)
    changed=deepcopy(base);changed['bid_prices'][5]=np.arange(90.,80.,-1.);changed['ask_prices'][5]=np.arange(91.,101.)
    found=run(changed)[0]
    check('同側10段外は数量0でない',found['trials'][0]['samples'][1]['quantity'] is None and found['trials'][0]['recovery_ratio'] is None)
    changed=deepcopy(base)
    for i in range(4,8):changed['ask_qty'][i,changed['ask_prices'][i]==102]=15.
    found=run(changed)[0]
    check('可視減少0は比率不明',found['trials'][0]['decrease']==0 and found['trials'][0]['recovery_ratio'] is None)
    check('減少0でも価格比較可能',found['features']['price_comparable'] and not found['features']['quantity_comparable'])
    for field,value in (('price_valid',False),('block_delay_seconds',61.)):
        changed=deepcopy(base);changed[field][5]=value
        check('価格品質中断/'+field,run(changed)[0]['status']=='price_quality_interruption')
    changed=deepcopy(base);changed['time_s'][5:]+=51.;changed['previous_release_gap']=np.r_[np.nan,np.diff(changed['time_s'])]
    check('公開gap61秒は中断',run(changed)[0]['status']=='price_quality_interruption')
    changed=deepcopy(base);changed['time_s'][5]=changed['time_s'][4];changed['previous_release_gap']=np.r_[np.nan,np.diff(changed['time_s'])]
    check('同時刻別行は新公開の代用にしない',run(changed)[0]['status']=='price_quality_interruption')
    changed=deepcopy(base);changed['ask_qty'][:4]=10.
    check('未来の数量回復で過去40秒準備を作らない',all(r['created']['time_s']!=40 for r in run(changed)))
    independent=run(base,require_recovery=False);changed=deepcopy(base)
    changed['ask_qty'][:]=float('nan');changed['bid_qty'][:]=float('nan');changed['depth_valid'][:]=False
    altered=run(changed,require_recovery=False)
    skeleton=lambda values:[(r['created'],r['price'],r['direction'],r['events'],[t['start'] for t in r['trials']],r['terminal']) for r in values]
    check('価格独立母集団は全数量欠測でも不変',skeleton(independent)==skeleton(altered))
    mids=[100.5,100.5,100.5,100.5,101.5,104.5,98.5,96.5,101.5,101.5,101.5,101.5,104.5,100.5,100.5,100.5,101.5]
    amounts=[20,20,10,15,15,10,20,20,100,95,96,96,100,20,10,15,15]
    repeated=run(fixture(mids,amounts),params=dict(expiry_seconds=120.))
    same=[r for r in repeated if r['price']==102 and r['direction']==1]
    check('同側同帯は準備から期限内に再準備しない',[r['created']['time_s'] for r in same]==[40.,160.])
    check('消費と同じ公開行へ準備を重ねない',not any(a['terminal'] and a['terminal']['seq']==b['created']['seq'] for a,b in zip(repeated,repeated[1:])))


def causal_cases() -> None:
    """機能: 全人工切断と未来差替を、確定情報・観測記録の独立投影で比較する。

    引数: なし。返り値: なし(None)。
    """
    events=fixture();n=len(events['seq'])
    for required in (True,False):
        full=run(events,require_recovery=required)
        for end in range(1,n+1):
            prefix=run(cut(events,end),require_recovery=required);seq=int(events['seq'][end-1])
            check(f'過去部分一致/{required}/{end}',projection(prefix,seq)==projection(full,seq))
            changed=deepcopy(events)
            changed['ask_qty'][end:]*=123.;changed['bid_qty'][end:]*=.3
            changed['bid_prices'][end:]+=20.;changed['ask_prices'][end:]+=20.;changed['atr'][end:]*=3.
            future=run(changed,require_recovery=required)
            check(f'未来価格ATR数量変更/{required}/{end}',projection(future,seq)==projection(full,seq))


def main() -> None:
    """機能: 人工状態検査と実装指紋を保存する。

    引数: なし。返り値: なし(None)。実原本・売買収支・現在APIは使わない。
    """
    socket.create_connection=denied;socket.socket.connect=denied;urllib.request.urlopen=denied
    paths=[HERE/'band_events.py',Path(__file__)];before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    basic_cases();boundary_cases();causal_cases()
    after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};check('実装SHA前後不変',before==after)
    result=dict(全合格=True,人工検査数=len(CHECKS),検査=CHECKS,SHA256=before,
        価格品質と数量品質を分離=True,採否で母集団を変更しない=True,
        先行突破を未来完成で救済しない=True,実相場損益計算数=0,原本参照数=0,現在API取得数=0,
        出力例=run(fixture()))
    (HERE/'check_band_events.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(全合格=True,人工検査数=len(CHECKS),SHA256=before),ensure_ascii=False))


if __name__=='__main__':main()
