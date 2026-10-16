"""不変数量engineから初回受理目標アンカーと、不変UID返済会計へ接続する。"""

import numpy as np

import catalog
import daily
import engine
import goal_policy
import policy


SIZE_COLUMNS=('row','paper_parent','side','virtual_initial','selected_actual_quantity','published_ATR','published_spread',
    'risk_per_lot_without_fees','published_liquidation_yen','remaining_budget_yen','planned_risk_yen',
    'paid_fees','reserved_exit_fees','size_reason','gate_accepted','actual_pending')
FEE_COLUMNS=('paid_fees','reserved_exit_fees','equity_yen','liquidation_yen','remaining_budget_yen')


def execute(account: dict, config: dict, python: bool=False, sizing_enabled: bool=True) -> tuple:
    """
    機能: 元paper全feedを進め、公開時の予定リスクから実数量だけを選ぶ。
    引数: account/config(dict)、python/sizing_enabled(bool) は人工対照の選択。
    返り値: tuple は旧数量版と同じ11配列。目標アンカーはこのengineへ戻さない。
    """
    symbol=account['symbol'];r=account['record'];q=account['quotes']
    accepted,_=policy.mask(account['feed'],len(r['price']),account['trade_features']['60'],config['mode'])
    numerator,denominator=catalog.FEE_RATIO[symbol]
    fn=engine.simulate.py_func if python else engine.simulate
    return fn(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],
        account['quiet'],account['quiet_force'],r['limit'],catalog.CAP[symbol],r['tick'],
        config['offset_atr'],True,accepted,sizing_enabled,catalog.BUDGET[symbol],config['risk_atr_multiple'],
        catalog.VALUE[symbol],numerator,denominator)


def account_output(session: str, account: dict, config: dict, values: tuple) -> dict:
    """
    機能: 元数量GUの実料清算を確認し、最初の受理qへ比例したP1/P2だけ変更する。
    引数: session(str)、account/config(dict)、values(tuple) は共有GUの実出力。
    返り値: dict は新目標の実政策と影GU診断。停止後suffixは実政策に含めない。
    """
    symbol=account['symbol'];q=account['quotes'];base=daily.reconstruct((session,symbol),values[0],values[5],q)
    fee_curve=values[10]
    for index,name in ((0,'cumulative_fees'),(1,'reserved_exit_fees'),(2,'equity_yen'),(3,'liquidation_yen')):
        np.testing.assert_allclose(fee_curve[:,index],base[name],atol=1e-5,rtol=1e-12)
    anchor=goal_policy.observe_anchor(account,config,values)
    result=goal_policy.apply(base,q,config,anchor)
    legs=result['actual_legs'];leg_gain=sum(max(0.,leg['収支']) for leg in legs);leg_loss=sum(max(0.,-leg['収支']) for leg in legs)
    assert np.isclose(leg_gain-leg_loss,result['summary']['収支'],atol=1e-5,rtol=1e-12)
    result['actual_leg_totals']=dict(profit=leg_gain,loss=leg_loss,net=leg_gain-leg_loss,
        profit_share=leg_gain/(leg_gain+leg_loss) if leg_gain+leg_loss else None,
        actual_legs=len(legs),winning_legs=sum(leg['収支']>0 for leg in legs),losing_legs=sum(leg['収支']<0 for leg in legs),
        定義='実部分返済玉ごとの新規料配分及び実返済料控除後netの正負合計。主評価の完結親とは別。')
    accepted,reasons=policy.mask(account['feed'],len(account['record']['price']),account['trade_features']['60'],config['mode'])
    result.update(case=config,gate_accepted=accepted,gate_reasons=reasons,limit_events=values[8],
        execution_events=values[6],execution_states=values[7],sizing_events=values[9],sizing_event_columns=SIZE_COLUMNS,
        sizing_fee_curve=fee_curve,sizing_fee_columns=FEE_COLUMNS,shadow_feed_SHA256=account.get('paper_SHA256'),
        shadow_GU_orders=values[0],shadow_GU_uids=values[5],shadow_GU_summary=base['summary'],
        quantity_semantics='元数量版と同じ公開q、影5/10、部分floor。最初の受理qだけから場の利益目標を固定。',
        source_scope='数量events/fee曲線/執行statesは共有GUの全feed診断。政策停止後suffixは実政策会計ではない。')
    return result
