"""元AUTOのC/R機械候補へ、現在の短期位相だけを適用する。"""

from copy import deepcopy

import numpy as np

import common
import features

legacy=common.module('106局所位相の元AUTO選択写し',common.HERE/'selection_snapshot.py')


def build(packet: dict, symbol: str, config: dict) -> dict:
    """
    機能: 元AUTO候補のCを保持し、Rだけ新規拒否と方向別待機取消を追加する。
    引数: packet(dict)、symbol(str)、config(dict)は新short付き保存入力・商品・固定18設定。
    返り値: dictは実執行normalと全R審査。拒否候補は再発行せず、後続の新候補は別原rowとして処理する。
    """
    short=packet['short'][symbol];normal=legacy.build(packet,symbol,config)
    original=normal['event'].copy();family=normal['entry_families'].copy();policy=config['local_policy']
    buy_allowed,buy_cancel=features.decisions(short,1,policy)
    sell_allowed,sell_cancel=features.decisions(short,-1,policy)
    permitted=np.where(original==1,buy_allowed,sell_allowed)
    rejected=(family==2)&(original!=0)&~permitted
    normal['local_phase_rejected']=rejected
    normal['local_cancel_buy']=buy_cancel;normal['local_cancel_sell']=sell_cancel
    normal['local_phase_candidates']=[]
    kept=[]
    for decision in normal['decisions']:
        row=int(decision['row'])
        if family[row]==2:
            value=dict(row=row,raw_row=int(decision['raw_row']),raw_seq=int(decision['raw_seq']),
                side=int(decision['side']),policy=policy,accepted=not bool(rejected[row]),
                rejection='短期位相' if rejected[row] else None,phase=features.at_phase(short,row))
            normal['local_phase_candidates'].append(value)
            if rejected[row]:continue
            decision=deepcopy(decision);decision['local_phase']=value
        kept.append(decision)
    normal['decisions']=kept
    normal['event'][rejected]=0
    normal['local_phase']=short
    normal['local_policy']=policy
    normal['original_R_event']=np.where(family==2,original,0).astype(np.int8)
    assert len(normal['decisions'])==np.count_nonzero(normal['event'])
    return normal
