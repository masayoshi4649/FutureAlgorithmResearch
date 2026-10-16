"""不変の数量GUと新公開maskを、初回受理尺度の固定出口又は高水準保全へ結ぶ。"""

import numpy as np
import common
import catalog
import daily
import context
import entry_policy
import exit_core
import exit_policy
import sizing_engine


def execute(account: dict, entry_id: str, execution_id: str='MARKET', peer_account: dict|None=None, python: bool=False) -> dict:
    """
    機能: 公開maskと一回FAK以外の数量経済を保ち、保存paper全feedを新GUで再生する。
    引数: account(dict)、entry_id/execution_id(str)、peer_account(dict|None)、python(bool) は入力・票・執行。
    返り値: dict は旧GU十一配列と入口/FAK証跡。正式実行は根の登録後だけ行う。
    """
    gate=entry_policy.mask(account,entry_id,peer_account);record,quotes=account['record'],account['quotes']
    symbol=account['symbol'];numerator,denominator=catalog.FEE_RATIO[symbol]
    assert execution_id in catalog.STRONG
    allowance=entry_policy.allowances(account,catalog.STRONG[execution_id])
    fn=sizing_engine.simulate.py_func if python else sizing_engine.simulate
    values=fn(record['time_s'],record['price'],quotes['bid'],quotes['ask'],quotes['quote_valid'],account['feed'],
        account['quiet'],account['quiet_force'],record['limit'],catalog.CAP[symbol],record['tick'],0.,True,
        gate['accepted'],True,catalog.BUDGET[symbol],1.,catalog.VALUE[symbol],numerator,denominator,
        True,allowance)
    return dict(values=values[:11],gate=gate,fak_events=values[11],allowance_ticks=allowance)


def prepared(session: str, account: dict, values: tuple, finish: bool=True) -> dict:
    """
    機能: 新GU又は保存GUの使用七配列を、当時清算と受理アンカーへ接続する。
    引数: session(str)、account(dict)、values(tuple)、finish(bool) は場・口座・同GU・完成範囲。
    返り値: dict は出口共通文脈。使用外のGU槽や未来親の返済を参照しない。
    """
    ledger=dict(key=(session,account['symbol']),shadow_GU_orders=values[0],shadow_GU_uids=values[5],
        execution_events=values[6],execution_states=values[7],limit_events=values[8],
        sizing_events=values[9],sizing_fee_curve=values[10])
    return context.prepare(account,ledger,ledger,finish=finish)


def calibrate(ctx: dict, config: dict) -> dict:
    """
    機能: 最初の受理q・公開ATR・spread・注文別往復料から場の全出口線を一回固定する。
    引数: ctx/config(dict) は共通文脈と結果前固定の十八条件。
    返り値: dict は純円目標・損失線・保全線。未受理は未定義で零補完しない。
    """
    anchor=ctx['anchor'];symbol=ctx['key'][1]
    out=dict(target_yen=None,hard_loss_yen=None,arm_yen=None,drawdown_yen=None,floor_yen=None,
        quantity_selection_budget_yen=catalog.BUDGET[symbol],anchor=anchor,
        definition='初受理qから一回固定、取消保持、後続q又はfillへ交換しない。Rは当該q×公開ATR×円倍率。')
    if anchor is None:return out
    risk=anchor['atr_yen'];cost=anchor['spread_fee_yen'];qty=anchor['quantity']
    p1=qty*daily.TICK[symbol]*daily.VALUE[symbol]
    out['hard_loss_yen']=catalog.BUDGET[symbol] if config['hard_basis']=='BUDGET' else config['hard_multiple']*risk+cost
    if config['exit_kind']=='fixed':
        basis=config['target_basis']
        if basis=='ATR':target=config['target_multiple']*risk
        elif basis=='P1':target=p1
        else:
            assert basis=='TICK_NET';target=p1-anchor['roundtrip_fee_yen']
        assert target>0;out['target_yen']=target
    else:
        assert config['exit_kind']=='protect'
        out['arm_yen']=p1 if config['arm_basis']=='P1' else config['arm_multiple']*risk
        out['drawdown_yen']=config['draw_multiple']*risk;out['floor_yen']=config['floor_yen']
    return out


def apply(ctx: dict, config: dict, gate: dict|None=None, python: bool=False, fak_events: np.ndarray|None=None) -> dict:
    """
    機能: 固定線又は当時までの清算高水準の初先着で、次正常UID返済と場停止を行う。
    引数: ctx/config(dict)、gate(dict|None)、python(bool)、fak_events(ndarray|None) はGU・出口・執行証跡。
    返り値: dict は実親・玉・注文・曲線と固定境界。FAKの場停止後GU診断は実親へ数えない。
    """
    lines=calibrate(ctx,config);trace=None;protection=None
    if config['exit_kind']=='fixed':
        result=exit_policy.fixed(ctx,lines['target_yen'],lines['hard_loss_yen']) if ctx['finish'] else fixed_prefix(ctx,lines)
    else:
        if ctx['anchor'] is None:
            decision=dict(row=None,reason=None,trace=None)
        else:
            decision=exit_policy.protection(ctx,lines['arm_yen'],lines['drawdown_yen'],lines['floor_yen'],
                lines['hard_loss_yen'],python=python)
        result=exit_policy.close_prefix(ctx,decision);trace=decision['trace'];protection=decision
        result['control'].update(目標=None,損失予算=lines['hard_loss_yen'],
            種別={None:None,1:'損失予算',2:'利益目標',3:'利益保全'}[decision['reason']])
    anchor=ctx['anchor'];goal=dict(成立=anchor is not None,数量=None if anchor is None else anchor['quantity'],
        通常全量=catalog.QUANTITY[ctx['key'][1]],受理行=None if anchor is None else anchor['row'],
        受理原seq=None if anchor is None else anchor['raw_seq'],受理価格時計=None if anchor is None else anchor['price_time_s'],
        紙上親=None if anchor is None else anchor['parent'],利益目標円=lines['target_yen'],
        定義='最初受理の予定q/ATR/spreadから固定。取消でも保持。後の実fill又は再参加qへ非追従。')
    values=ctx['values'];legs=result['actual_legs'];gain=sum(max(0.,v['収支']) for v in legs);loss=sum(max(0.,-v['収支']) for v in legs)
    if ctx['finish']:assert np.isclose(gain-loss,result['summary']['収支'],atol=1e-5,rtol=1e-12)
    result.update(case=config,goal_anchor=goal,exit_boundary=lines,protection_trace=trace,
        gate_accepted=None if gate is None else gate['accepted'],gate_reasons=None if gate is None else gate['reasons'],
        entry_diagnostics=None if gate is None else gate['diagnostics'],
        shadow_GU_orders=values[0],shadow_GU_uids=values[5],execution_events=values[6],execution_states=values[7],
        limit_events=values[8],sizing_events=values[9],sizing_fee_curve=values[10],shadow_GU_summary=ctx['base']['summary'],
        actual_leg_totals=dict(profit=gain,loss=loss,net=gain-loss,profit_share=gain/(gain+loss) if gain+loss else None),
        quantity_semantics='公開リスク数量と影5/10は不変。FAK失効と票拒否後も全feedで後参加のq/busyを更新。',
        source_scope='GU全feed診断と、場停止後新規無しの実政策を分離。途中保全は前親実現・partial・料込みの場清算。')
    if fak_events is not None:
        assert fak_events.shape==(len(fak_events),19)
        result['fak_events']=fak_events
        result['fak_event_raw_seq']=ctx['record']['seq'][fak_events[:,0].astype(np.int64)]
        result['fak_publication_raw_seq']=ctx['record']['seq'][fak_events[:,3].astype(np.int64)]
        result['fak_columns']=('row','stage','paper_parent','publication_row','side','planned_qty','price_cap',
            'published_bid','published_ask','adverse_observed_ticks','price_time_s','attempt_bid','attempt_ask',
            'price_pass','attempted','pending_after','cancel_reason','actual_uid','publication_price_time_s')
        result['fak_scope']='全GU執行診断。実政策はorders/parentで識別し、停止後試行を実取引へ数えない。'
    return result


def fixed_prefix(ctx: dict, lines: dict) -> dict:
    """
    機能: 未完成接頭の固定線だけを走査し、未観測の次正常清算を補わない。
    引数: ctx/lines(dict) は未完成GUと受理時に固定済みの純円線。
    返り値: dict は観測済みの実注文接頭。返済理由94/95は完成dailyと同じ。
    """
    assert not ctx['finish']
    if ctx['anchor'] is None:
        result=dict(ctx['base']);result['control']=dict(発動=False,目標=None,損失予算=None,未完成接頭=True)
        return result
    row,reason,_=exit_core.scan.py_func(ctx['base']['liquidation_yen'],ctx['normal'],ctx['anchor']['row'],
        np.inf,1.,0.,lines['hard_loss_yen'],lines['target_yen'])
    decision=dict(row=None if row<0 else int(row),reason=None if not reason else int(reason))
    old=exit_policy.close_prefix(ctx,decision)
    orders=old['orders'].copy()
    if row>=0:orders[(orders[:,0]>row)&(orders[:,6]==96),6]=94 if reason==2 else 95
    result=daily.reconstruct(ctx['key'],orders,old['order_uids'],ctx['quotes'],old['exit_target_uids'],finish=False)
    result['control']=dict(old['control'],目標=lines['target_yen'],損失予算=lines['hard_loss_yen'])
    return result


def baseline(ctx: dict) -> dict:
    """
    機能: 新条件数に加えない旧P1利確アンカーの注文経済を、保存GUから確認する。
    引数: ctx(dict) は旧CONFIRM GU文脈。
    返り値: dict は旧不変dailyの同値対照。元受理取消保持を維持する。
    """
    symbol=ctx['key'][1];anchor=ctx['anchor']
    goal=None if anchor is None else anchor['quantity']*daily.TICK[symbol]*daily.VALUE[symbol]
    return exit_policy.fixed(ctx,goal,catalog.BUDGET[symbol])


def market_reference(ctx: dict, gate: str, target: str) -> dict:
    """
    機能: 旧市場六対照を保存GUから同一出口線で再会計し、新金融へ数えない。
    引数: ctx(dict)、gate/target(str) は旧三routeのGU文脈と二純目標。
    返り値: dict は旧政策の経済同値。未受理の旧G25P1だけ旧固定B表示を保持する。
    """
    assert gate in ('G25','G50','G75') and target in ('P1','ATR25')
    anchor=ctx['anchor'];symbol=ctx['key'][1]
    goal=None if anchor is None else (anchor['quantity']*daily.TICK[symbol]*daily.VALUE[symbol] if target=='P1' else .25*anchor['atr_yen'])
    hard=catalog.BUDGET[symbol] if anchor is not None or (gate=='G25' and target=='P1') else None
    return exit_policy.fixed(ctx,goal,hard)
