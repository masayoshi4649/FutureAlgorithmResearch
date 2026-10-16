"""既公開行だけの出来高代理と現在二市場価格票を別に測り、入口採否へ結ぶ。"""

import math
import numpy as np


def price_ok(features: dict,row: int,side: int) -> bool:
    """
    機能: 109と同じ現在自己/peer価格票の両市場入口資格を確認する。
    引数: features(dict)、row/side(int) は価格窓・当行・paper方向。
    返り値: bool は既知/各2票/.25以上。FAKの強さ判定とは別。
    """
    f=features
    return bool(f['own']['known'][row] and f['peer_known'][row] and f['own']['count'][row]>=2 and f['peer_count'][row]>=2
        and side*f['own']['balance'][row]>=.25 and side*f['peer_balance'][row]>=.25)


def volume(account: dict,row: int,side: int) -> dict:
    """
    機能: 保存60秒出来高代理の公開原行/時計/分母/既signed釣合いを検査する。
    引数: account(dict)、row/side(int) は同packet口座とpaper公開行/方向。
    返り値: dict は元当時特徴。未知を反票や零へ補完しない。
    """
    value=account['trade_features']['60'][int(row)];r=account['record'];mapping=account['mapping']
    assert value['window_seconds']==60
    for key,expected in (('candidate_raw_row',int(mapping[row])),('candidate_raw_seq',int(r['seq'][row])),('candidate_price_time_s',float(r['time_s'][row]))):
        if key in value and value[key] is not None:assert value[key]==expected,key
    if value['known']:
        assert all(key in value and value[key] is not None for key in ('candidate_raw_row','candidate_raw_seq','candidate_price_time_s'))
        up,down,count=value['up_votes'],value['down_votes'],value['direction_votes']
        assert isinstance(up,(int,np.integer)) and isinstance(down,(int,np.integer)) and up>=0 and down>=0 and count==up+down
        if count:
            assert value['balance'] is not None and math.isclose(value['balance'],side*(up-down)/count,rel_tol=0.,abs_tol=1e-12)
        else:assert value['balance'] is None
    return dict(value)


def build(account: dict,features: dict,config: dict) -> dict:
    """
    機能: 各paper原新規rowだけへ入口情報を適用し、後rowへ票を持ち越さない。
    引数: account/features/config(dict) は同口座の保存公開票・現在価格票・入口条件。
    返り値: dict はbool採否配列と公開時の分離診断。新しい票を原入力から再計算しない。
    """
    n=len(account['record']['price']);allowed=np.zeros(n,bool);diagnostics={}
    entries=account['feed'][account['feed'][:,7]==1];assert len({int(o[0]) for o in entries})==len(entries)
    entry_id=config['entry_id'];assert entry_id in ('PRICE_BOTH','VOL_SELECTED','VOL25','VOL25_PRICE_BOTH')
    for order in entries:
        row=int(order[0]);side=int(order[3]);assert side in (-1,1)
        value=volume(account,row,side);price=price_ok(features,row,side)
        threshold=config['volume_balance_threshold'][account['symbol']]
        vol=bool(value['known'] and value['direction_votes']>=2 and value['balance'] is not None and value['balance']>=threshold)
        accepted=price if entry_id=='PRICE_BOTH' else vol and price if entry_id=='VOL25_PRICE_BOTH' else vol
        allowed[row]=accepted
        diagnostics[row]=dict(entry_id=entry_id,volume=dict(value),volume_accepted=vol,price_accepted=price,accepted=accepted,
            balance_definition='出来高balanceは保存時にpaper方向signed済み。採否で再signしない。',
            price_definition='価格票は絶対方向balanceをpaper sideへ向ける。出来高票とは別。',
            volume_scope='自市場の当該paper公開rowだけ。peerVolume補完/後row持越し0。')
    return dict(allowed=allowed,diagnostics=diagnostics)
