"""数量が減らない逆板の条件を、実入力を読まず独立逐次判定する。"""

from copy import deepcopy
from pathlib import Path
import json

import numpy as np

from range_engine_check import digest, load


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def fixture(side: int = 1) -> dict:
    """
    機能: 窓内同一反対価格に三接触し、数量一定・支持非進行となる原行人工を作る。
    引数: side(int)は買い又は売り。
    返り値: dictは未来同時計行も含む人工原列。金融入力は使用しない。
    """
    times = np.array([0.,5.,10.,15.,20.,21.,25.,30.,30.,31.,40.,80.,80.,81.])
    n = len(times); bid = np.full(n,100.); ask = np.full(n,101.); last = np.full(n,100.5)
    volume = np.zeros(n); volume[[7,8,11,12,13]] = 1; last[[7,8,11,12,13]] = 101.
    if side < 0:
        bid,ask,last = 201.-ask,201.-bid,201.-last
    raw = dict(raw_seq=np.arange(100,100+n,dtype=np.int64),price_time_s=times,last=last,bid=bid,ask=ask,
        bid_qty=np.full(n,10.),ask_qty=np.full(n,10.),volume_delta=volume,
        volume_delta_usable=np.ones(n,bool),volume_reset_reason=np.zeros(n,np.uint16),
        best_quantity_valid=np.ones(n,bool),price_row_valid=np.ones(n,bool),price_transition_valid=np.ones(n,bool))
    raw['volume_delta_usable'][0] = False; raw['volume_delta'][0] = np.nan; raw['price_transition_valid'][0] = False
    return raw


def oracle(raw: dict, direction: np.ndarray, vote: dict, side: int) -> dict:
    """
    機能: 当時票と当時までの末尾同価格区間から非減少・非進行・反復接触を逐次確認する。
    引数: raw(dict)、direction(ndarray)、vote(dict)、side(int)は原列と不変当時票。
    返り値: dictは既知・成立と監査値。未来rawseqや数量を補完しない。
    """
    if side not in (-1,1) or not vote['known'] or vote['direction_votes']<2:
        return dict(known=False,matched=False,category='票資格')
    row = int(vote['candidate_raw_row']); first = vote['first_vote_raw_row']
    if first is None or not (0<=first<=row<len(direction)):
        return dict(known=False,matched=False,category='原行資格')
    opposite = raw['ask'] if side>0 else raw['bid']; supporting = raw['bid'] if side>0 else raw['ask']
    quantities = raw['ask_qty'] if side>0 else raw['bid_qty']; price = opposite[row]
    if not np.isfinite(price) or price<=0:
        return dict(known=False,matched=False,category='同価格境界')
    start = row
    while start>first:
        previous = opposite[start-1]
        if not np.isfinite(previous) or previous<=0:
            return dict(known=False,matched=False,category='同価格境界')
        if previous!=price:
            break
        start -= 1
    quantity = quantities[start]; support = supporting[start]
    if not np.isfinite(quantity) or quantity<=0 or not np.isfinite(support) or support<=0:
        return dict(known=False,matched=False,category='数量気配')
    touches = []; minimum = quantity; advance = 0.
    for pos in range(start,row+1):
        b,a = raw['bid'][pos],raw['ask'][pos]; bq,aq = raw['bid_qty'][pos],raw['ask_qty'][pos]
        finite = all(np.isfinite(v) for v in (b,a,bq,aq,raw['price_time_s'][pos]))
        if not finite or not(0<b<a and bq>0 and aq>0) or not raw['price_row_valid'][pos] or not raw['best_quantity_valid'][pos]:
            return dict(known=False,matched=False,category='数量気配')
        if pos>start:
            if raw['raw_seq'][pos]!=raw['raw_seq'][pos-1]+1 or not raw['price_transition_valid'][pos] or raw['price_time_s'][pos]<raw['price_time_s'][pos-1]:
                return dict(known=False,matched=False,category='隣接資格')
            if raw['volume_delta_usable'][pos] and raw['volume_reset_reason'][pos]==0 and np.isfinite(raw['volume_delta'][pos]) and raw['volume_delta'][pos]>0 and raw['last'][pos]==price and direction[pos]==side:
                touches.append(pos)
        minimum = min(minimum,float(quantities[pos])); advance = max(advance,float(side*(supporting[pos]-support)))
    return dict(known=True,matched=bool(minimum>=quantity and advance<=0 and len(touches)>=2),category='既知',
        start=start,end=row,opposite_price=float(price),initial_quantity=float(quantity),minimum_quantity=float(minimum),
        supporting_advance=float(advance),touch_rows=touches,touch_count=len(touches))


def static_scope() -> dict:
    """
    機能: 旧完全C/Rの数量減少門が、数量一定の枝を準備へ送れないことを静的に記録する。
    引数: なし。
    返り値: dictは限定した静的重複範囲。全過去仮説の未試行を主張しない。
    """
    path = ROOT/'work/wave_v103/engine/states.py'; text = path.read_text(encoding='utf-8')
    assert 'decrease = max(0., v[10] - opposite_q)' in text
    assert '(not use_supply or v[7] >= .5 * v[4])' in text
    assert 'if decrease > 0 and aligned:' in text
    return dict(旧状態機械SHA256=digest(path),対象='完全C/Rのuse_supply=true枝',
        反例='Q0>0の同価格表示量が一定ならdecrease累積0で0.5Q0へ到達せずphase0の準備門を通らない。',
        限界='price-only/volume-only等のuse_supply=false枝にはこの門を省く条件がある。過去全方式が未捕捉とは主張しない。')


if __name__=='__main__':
    path = HERE/'absorption_独立述語と旧減少門の静的設計.json'; assert not path.exists()
    proposal = ROOT/'work/wave_v106/price_review/cause107_静的部品と固定閾値案.json'
    path.write_text(json.dumps(dict(全合格=True,範囲='独立逐次oracleと人工定義だけ。対象sourceはまだ未実行。',
        旧方式の限定確認=static_scope(),固定案SHA256=digest(proposal),レビューsourceSHA256=digest(Path(__file__)),
        大型入力=0,原板=0,NPZ=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('吸収の独立述語と旧減少門の静的設計を保存',digest(path))
