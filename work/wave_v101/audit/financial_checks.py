"""新しい会計監査helperを、手計算した少数の注文台帳で検査する。"""

from pathlib import Path
import numpy as np

import common
import compare_utils as checks
import financial
import math_oracle as oracle


def fixture(symbol: str, side: int) -> tuple:
    """
    機能: 初回絶対1と追加1及び全量一返済の有限人工台帳を独立構成する。
    引数: symbol(str)、side(int)は±1。
    返り値: tuple[dict,dict,dict]。原板、数量宣言、手計算会計。売買本体は呼ばない。
    """
    scale,multiplier,fee_unit = (1,1000,41.8) if symbol == 'TOPIX' else (20,10,11)
    times = np.arange(6,dtype=float)+100.
    bid = np.array([3999.5,4000,4001,4002,4003,4003])*scale
    ask = bid+.5*scale
    if side == -1:
        old_bid = bid.copy()
        bid,ask = 8000*scale-ask,8000*scale-old_bid
    record = dict(symbol=symbol,time_s=times,seq=np.arange(6),bid=bid,ask=ask,
                  quote_valid=np.ones(6,bool),limit=1000.,tick=.5*scale)
    config = dict(id='人工絶対1の会計だけ',trend_initial_quantity=1,trend_growth_mode=1)
    entries = [ask[row] if side == 1 else bid[row] for row in (1,3)]
    close = bid[5] if side == 1 else ask[5]
    opening_fee = oracle.order_fee(1,fee_unit)
    closing_fee = oracle.order_fee(2,fee_unit)
    orders = np.array([
        [1,0,1,0,side,1,entries[0],1,0,opening_fee,times[0],times[1],0,1,0,side,1],
        [3,2,1,0,side,1,entries[1],1,16,opening_fee,times[2],times[3],0,1,0,side,2],
        [5,4,1,0,-side,2,close,0,2,closing_fee,times[4],times[5],0,1,0,side,3]],float)
    gross = side*((close-entries[0])+(close-entries[1]))*multiplier
    net = gross-2*opening_fee-closing_fee
    trades = np.array([[1,0,1,5,side,2,sum(entries)/2,close,2*opening_fee,closing_fee,gross,net,0,2,1,0]],float)
    first_share = (closing_fee+1)//2
    shares = (first_share,closing_fee-first_share)
    columns = ['parent_id','cohort_id','source','side','quantity','entry_row','entry_price',
               'entry_fee','exit_row','exit_price','exit_fee_share','gross','net']
    cohorts = []
    for ordinal,(row,price,share) in enumerate(zip((1,3),entries,shares),1):
        own_gross = side*(close-price)*multiplier
        cohorts.append([1,ordinal,0,side,1,row,price,opening_fee,5,close,share,
                        own_gross,own_gross-opening_fee-share])
    cash = np.zeros(6)
    cash[1:] = -side*entries[0]*multiplier-opening_fee
    cash[3:] -= side*entries[1]*multiplier+opening_fee
    cash[5] += side*2*close*multiplier-closing_fee
    quantity = np.array([0,1,1,2,2,0])
    quotation = bid if side == 1 else ask
    curve = cash+side*quantity*quotation*multiplier
    curve -= np.array([0,opening_fee,opening_fee,closing_fee,closing_fee,0])
    trace = np.zeros((6,6))
    offset = 0 if side == 1 else 1
    trace[:,offset] = quantity
    trace[:,offset+2] = quantity
    # この会計専用台帳は予約状態を表示せず、列4/5のpendingを実保有へ置換しない。
    output = dict(orders=orders,trades=trades,growth_cohorts=np.asarray(cohorts,float),
                  growth_cohort_columns=columns,curve=curve,
                  source_curve=np.column_stack((curve,np.zeros(6))),target_trace=trace)
    return record,config,output


def main() -> None:
    """
    機能: 両商品/買売の手計算台帳と未完接頭を独立会計helperへ照合する。
    引数: なし。
    返り値: None。エンジン・原板・正式101損益を実行しない。
    """
    results=[]
    for symbol in common.SYMBOLS:
        for side in (1,-1):
            record,config,output = fixture(symbol,side)
            result = financial.verify_account(record,config,output)
            assert result['counts']['注文'] == 3 and result['counts']['決済親'] == 1
            assert result['counts']['cohort'] == 2 and output['orders'][0,5] == 1
            checks.exact(result['curve'],output['curve'],'手計算全原板時価')
            prefix_record = {key:(value[:4].copy() if isinstance(value,np.ndarray) else value)
                             for key,value in record.items()}
            prefix_output = {key:(value.copy() if isinstance(value,np.ndarray) else value)
                             for key,value in output.items()}
            prefix_output['orders'] = output['orders'][:2].copy()
            prefix_output['trades'] = np.empty((0,16))
            for name in ('curve','source_curve','target_trace'):
                prefix_output[name] = output[name][:4].copy()
            prefix_output['growth_cohorts'][:,8:] = np.nan
            prefix = financial.verify_account(prefix_record,config,prefix_output,complete=False)
            assert prefix['未完親'] == 1 and prefix['counts']['決済親'] == 0
            results.append(dict(商品=symbol,方向=side,初回絶対数量=1,追加数量=1,
                                親純損益=float(output['trades'][0,11]),
                                cohort純損益=output['growth_cohorts'][:,-1].tolist(),未完親の保持=True))
    paths = [Path(__file__),common.HERE/'financial.py',common.HERE/'compare_utils.py',
             common.HERE/'common.py',common.HERE/'math_oracle.py']
    common.save(common.HERE/'独立会計helperの四台帳と未完接頭の準備確認.json',dict(
        合格=True,完成人工台帳=4,未完接頭=4,結果=results,
        範囲='手計算人工台帳による独立会計helper自身の検査。101本体又はroot保存経路の一致はまだ証明していない。',
        本体売買呼出=0,正式101損益=0,API取得=0,実注文=0,SHA256=common.fingerprints(paths)))
    print('独立会計helper: 4完成台帳と4未完接頭が合格。本体呼出0。',flush=True)


if __name__ == '__main__':
    main()
