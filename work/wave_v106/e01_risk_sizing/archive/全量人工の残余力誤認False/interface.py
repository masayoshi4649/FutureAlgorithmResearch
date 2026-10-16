"""旧紙上GUを保持した可変実数量と、不変UID会計を接続する。"""

import numpy as np

import common
import catalog
import daily
import engine
import policy

SIZE_COLUMNS=('row','paper_parent','side','virtual_initial','selected_actual_quantity','published_ATR','published_spread',
    'risk_per_lot_without_fees','published_liquidation_yen','remaining_budget_yen','planned_risk_yen',
    'paid_fees','reserved_exit_fees','size_reason','gate_accepted','actual_pending')
FEE_COLUMNS=('paid_fees','reserved_exit_fees','equity_yen','liquidation_yen','remaining_budget_yen')


def execute(account: dict, config: dict, python: bool=False, sizing_enabled: bool=True) -> tuple:
    """
    機能: 元paper全feedを進め、公開時の予定リスクから実数量だけを選ぶ。
    引数: account/config(dict)、python/sizing_enabled(bool) は人工対照の選択。
    返り値: tuple は旧9配列と数量判断16列・実料清算5列。正式金融は根登録後だけ。
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
    機能: 実注文からUID別料と清算を再構成し、固定P1/P2・L2へつなぐ。
    引数: session(str)、account/config(dict)、values(tuple) は共有GUの実出力。
    返り値: dict は実政策会計と影GU診断。停止後のGU suffixを実利益へ足さない。
    """
    symbol=account['symbol'];q=account['quotes'];base=daily.reconstruct((session,symbol),values[0],values[5],q)
    fee_curve=values[10]
    for index,name in ((0,'cumulative_fees'),(1,'reserved_exit_fees'),(2,'equity_yen'),(3,'liquidation_yen')):
        np.testing.assert_allclose(fee_curve[:,index],base[name],atol=1e-5,rtol=1e-12)
    result=daily.apply_policy(base,q,dict(profit_ticks=config['profit_ticks'],loss_ticks=2))
    accepted,reasons=policy.mask(account['feed'],len(account['record']['price']),account['trade_features']['60'],config['mode'])
    result.update(case=config,gate_accepted=accepted,gate_reasons=reasons,limit_events=values[8],
        execution_events=values[6],execution_states=values[7],sizing_events=values[9],sizing_event_columns=SIZE_COLUMNS,
        sizing_fee_curve=fee_curve,sizing_fee_columns=FEE_COLUMNS,shadow_feed_SHA256=account.get('paper_SHA256'),
        shadow_GU_orders=values[0],shadow_GU_uids=values[5],shadow_GU_summary=base['summary'],
        quantity_semantics='paper/vcoreは元5/10。実数量は公開時固定し、累積virtual返済率floorと最終残全返済。',
        source_scope='sizing_events/fee_curve/執行statesは共有GU全feedの診断。P1/P2停止後のsuffixは実政策会計ではない。')
    return result
