"""当時の初回受理数量で利益及び損失の停止線を固定し、不変UID返済へ接続する。"""

import numpy as np

import catalog
import daily


def observe_anchor(account: dict, config: dict, values: tuple) -> dict:
    """
    機能: 全影feedを消さず、最初の実新規予約の受理行から目標を固定する。
    引数: account/config(dict)、values(tuple) は当時口座と元数量engineの11配列。
    返り値: dict は初回受理数量・公開時計・原seq・円利益目標。受理無しは未定義。
    """
    symbol=account['symbol'];events=values[9]
    assert events.shape==(len(events),16)
    accepted=np.flatnonzero(events[:,15]==1)
    full=catalog.QUANTITY[symbol];original=float(config['profit_goal_yen'][symbol])
    if not len(accepted):
        assert len(values[0])==0,'受理無しから実注文を作らない'
        return dict(成立=False,数量=None,通常全量=full,元利益目標円=original,利益目標円=None,
            受理行=None,受理原seq=None,受理価格時計=None,紙上親=None,
            定義='最初に受理した新規qで固定。q0/UNKNOWN/拒否はアンカー無し。')
    event=events[int(accepted[0])]
    row=int(event[0]);quantity=int(event[4])
    assert quantity==event[4] and 0<quantity<=full
    assert event[13]==0 and event[14]==1 and event[3]==full
    record=account['record'];goal=original*quantity/full
    assert 0<=row<len(record['seq']) and np.isfinite(goal) and goal>0
    return dict(成立=True,数量=quantity,通常全量=full,元利益目標円=original,利益目標円=goal,
        受理行=row,受理原seq=int(record['seq'][row]),受理価格時計=float(record['time_s'][row]),紙上親=int(event[1]),
        定義='最初に受理した新規qで固定。約定無しや後の取消でも保持し、以後のqへ追従しない。')


def apply(base: dict, quotes: dict, config: dict, anchor: dict) -> dict:
    """
    機能: 初回受理数量の比例利益及び比例損失停止線へ最初到達した時に場内停止する。
    引数: base/quotes/config/anchor(dict) は実GU会計、気配、条件、当時確定の目標。
    返り値: dict は不変dailyによる実UID返済会計。新規数量選択予算と損失停止線を分ける。
    """
    symbol=base['key'][1];selection_budget=float(catalog.BUDGET[symbol])
    loss_stop=None if not anchor['成立'] else selection_budget*anchor['数量']/anchor['通常全量']
    if not anchor['成立']:
        assert len(base['orders'])==0 and not np.any(base['long_qty']) and not np.any(base['short_qty'])
        result=dict(base)
        result['control']=dict(発動=False,目標=None,損失予算=None)
    else:
        unit=daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]
        result=daily.apply_policy(base,quotes,dict(profit_ticks=anchor['利益目標円']/unit,
            loss_ticks=2*anchor['数量']/anchor['通常全量']))
        assert result['control']['目標']==anchor['利益目標円']
        assert result['control']['損失予算']==loss_stop
        if result['control']['発動']:
            assert result['control']['判断行']>=anchor['受理行']
    result['goal_anchor']=anchor
    result['loss_anchor']=dict(新規数量選択予算円=selection_budget,比例損失停止線円=loss_stop,
        初回受理数量=anchor['数量'],通常全量=anchor['通常全量'],
        定義='数量選択予算は元5000/2000円。実損失停止線だけ初回受理q/fullへ比例。未受理は停止線未定義。')
    return result
