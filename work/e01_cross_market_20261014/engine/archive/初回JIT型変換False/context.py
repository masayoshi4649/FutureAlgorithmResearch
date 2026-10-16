"""保存GU・同原行気配・初回受理の尺度を、出口の共通文脈へ結ぶ。"""

import numpy as np
import daily
import reuse


def prepare(account: dict, ledger_p1: dict, ledger_p2: dict, finish: bool=True) -> dict:
    """
    機能: 二政策で同値の保存GUを復元し、当時までの実料・初回受理情報を確かめる。
    引数: account/ledger_p1/ledger_p2(dict)、finish(bool) は保存入力、二台帳、完全場か。
    返り値: dict は出口共通文脈。GUI・原板・APIを再実行しない。
    """
    symbol=account['symbol'];record,quotes=account['record'],account['quotes'];count=len(record['price'])
    np.testing.assert_array_equal(record['seq'],quotes['seq'])
    np.testing.assert_array_equal(record['time_s'],quotes['time_s'])
    assert count>0 and np.all(np.isfinite(record['time_s']))
    assert np.all(np.diff(record['seq'])>0) and np.all(np.diff(record['time_s'])>=0)
    if finish:assert record['time_s'][-1]>=record['limit'],'未完成接頭を完成場へ扱わない'
    values=reuse.pair(ledger_p1,ledger_p2,count);assert ledger_p1['key'][1]==symbol
    base=daily.reconstruct(ledger_p1['key'],values[0],values[5],quotes,finish=finish)
    for index,name in ((0,'cumulative_fees'),(1,'reserved_exit_fees'),(2,'equity_yen'),(3,'liquidation_yen')):
        np.testing.assert_allclose(values[10][:,index],base[name],atol=1e-5,rtol=1e-12)
    accepted=np.flatnonzero(values[9][:,15]==1);anchor=None
    if len(accepted):
        event=values[9][int(accepted[0])];row=int(event[0]);qty=int(event[4]);full=daily.QUANTITY[symbol]
        assert 0<=row<count and 0<qty<=full and qty==event[4]
        assert event[13]==0 and event[14]==1 and event[3]==full
        assert np.isfinite(event[5]) and event[5]>0 and np.isfinite(event[6]) and event[6]>0
        assert not np.any(values[0][:,1]<row)
        anchor=dict(row=row,raw_seq=int(record['seq'][row]),price_time_s=float(record['time_s'][row]),
            parent=int(event[1]),side=int(event[2]),quantity=qty,full_quantity=full,
            published_atr=float(event[5]),published_spread=float(event[6]),
            published_liquidation_yen=float(event[8]),selection_available_yen=float(event[9]),
            roundtrip_fee_yen=2*daily.fee(qty,symbol),multiplier=daily.VALUE[symbol],
            atr_yen=qty*float(event[5])*daily.VALUE[symbol],
            spread_fee_yen=qty*float(event[6])*daily.VALUE[symbol]+2*daily.fee(qty,symbol))
    else:assert len(values[0])==0
    return dict(account=account,key=base['key'],quotes=quotes,record=record,normal=daily.normal_mask(quotes),
        values=values,base=base,anchor=anchor,finish=finish,
        scope='初回受理は将来取消でも保持。清算には前親実現・発動前partial・現在保有・全支払料・残UID返済料を含む。出口後は場終了し再参加を作らない。')
