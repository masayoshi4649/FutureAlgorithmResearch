"""106の同じ小人工生成とPython旧基準接続を読取専用で使う。"""

from copy import deepcopy

import numpy as np

import common
import catalog

ENGINE=common.module('106静観offの読取旧interface',common.WAVE/'engine/interface.py')


def fixture(symbol: str, side: int=1) -> tuple[dict,dict]:
    """
    機能: 入口・初期支持・次正常気配が明示された小人工を作る。
    引数: symbol(str)、side(int)は商品と方向。
    返り値: tuple[dict,dict]はpreparedと同原行normal入口。正式入力を読まない。
    """
    opening,tick=(4000.,.5) if symbol=='TOPIX' else (50000.,10.)
    n=1005;seq=np.arange(n,dtype=np.int64)+1000;times=np.arange(n,dtype=float)
    bid=np.full(n,opening);ask=bid+tick
    record=dict(symbol=symbol,session='人工',time_s=times,seq=seq,bid=bid,ask=ask,price=(bid+ask)/2,
        quote_valid=np.ones(n,bool),price_valid=np.ones(n,bool),tick=tick,start=0.,limit=1000.,end=1005.,人工素材=True)
    prepared=dict(record=record,reference_open=opening,signal={'trend_width':100*tick})
    case=dict(entry_id='C_OWN',event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),
        entry_quality=np.ones(n,bool),entry_reset=np.zeros(n,bool),execution_to_raw_index=np.arange(n,dtype=np.int64),decisions=[])
    event(prepared,case,330,side,opening if side==1 else opening+tick)
    return prepared,case


def event(prepared: dict, case: dict, row: int, side: int, support: float) -> None:
    """
    機能: 同一原行の候補根拠を人工素材へ追加する。
    引数: prepared/case(dict)、row/side(int)、support(float)。
    返り値: None。当時より後のanchorを作らない。
    """
    seq=int(prepared['record']['seq'][row]);case['event'][row]=side;case['support_price'][row]=support
    case['decisions'].append(dict(row=row,normal_row=row,raw_row=row,raw_seq=seq,side=side,support_price=support,
        selected_support_roots=[dict(family=case['entry_id'][0],anchor_raw_seq=seq-1,support_price=support)]))
    case['decisions'].sort(key=lambda d:d['row'])


def quote(prepared: dict, begin: int, bid: float) -> None:
    """
    機能: 人工の後続気配を同spreadへ置く。
    引数: prepared(dict)、begin(int)、bid(float)は開始行と価格。
    返り値: None。原seqと時計は変更しない。
    """
    r=prepared['record'];r['bid'][begin:]=bid;r['ask'][begin:]=bid+r['tick'];r['price'][begin:]=bid+r['tick']/2


def run_leg(prepared: dict, case: dict, quantity: int, finish: bool=True) -> dict:
    """
    機能: 不変106B4を人工だけへ実量接続する。
    引数: prepared/case(dict)、quantity(int)、finish(bool)。
    返り値: dictはPython本体の物理出力。
    """
    cfg=dict(catalog.catalog()[0],id='人工B4')
    return ENGINE.play(prepared,case,cfg,quantity=quantity,finish=finish,python=True)

