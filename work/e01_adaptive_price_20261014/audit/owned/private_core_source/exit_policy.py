"""固定閾値と因果利益保全を分け、旧実注文接頭の次正常UID返済へ接続する。"""

import numpy as np
import daily
import exit_core


def fixed(context: dict, goal_yen: float|None, loss_yen: float|None) -> dict:
    """
    機能: 固定円閾値だけを不変dailyへ渡し、元の初先着・次気配返済を維持する。
    引数: context(dict)、goal_yen/loss_yen(float|None) は共通文脈と円線。
    返り値: dict は実政策会計。未受理の利益目標はNoneで保持する。
    """
    for value in (goal_yen,loss_yen):assert value is None or np.isfinite(value) and value>0
    if context['anchor'] is None:
        assert goal_yen is None
        result=dict(context['base']);result['control']=dict(発動=False,目標=None,損失予算=loss_yen)
        return result
    assert goal_yen is not None and context['finish'],'固定dailyは完成場用。接頭は判断走査とclose_prefixを使う'
    symbol=context['key'][1];unit=daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]
    return daily.apply_policy(context['base'],context['quotes'],dict(profit_ticks=goal_yen/unit,
        loss_ticks=None if loss_yen is None else loss_yen/unit))


def protection(context: dict, arm_yen: float, drawdown_yen: float, floor_yen: float,
               hard_loss_yen: float|None, target_yen: float|None=None, python: bool=False) -> dict:
    """
    機能: 当時の清算高水準で保護線を上げ、固定hard又は利確と最初の退出を比べる。
    引数: context(dict)、円閾値(float/None)、python(bool) は文脈・結果前設定・人工対照。
    返り値: dict は判断行と途中trace。退出後の再参加や事後の親ピークは使わない。
    """
    assert np.isfinite(arm_yen) and arm_yen>0 and np.isfinite(drawdown_yen) and drawdown_yen>0
    assert np.isfinite(floor_yen) and floor_yen<arm_yen
    for value in (hard_loss_yen,target_yen):assert value is None or np.isfinite(value) and value>0
    if context['anchor'] is None:
        return dict(row=None,reason=None,trace=None,scope='未受理。保護線も目標も発動無し。')
    fn=exit_core.scan.py_func if python else exit_core.scan
    row,reason,trace=fn(context['base']['liquidation_yen'],context['normal'],context['anchor']['row'],
        arm_yen,drawdown_yen,floor_yen,np.nan if hard_loss_yen is None else hard_loss_yen,
        np.nan if target_yen is None else target_yen)
    return dict(row=None if row<0 else int(row),reason=None if not reason else int(reason),trace=trace,
        scope='現在行以下の清算高水準、保護線を不利に緩めない。hard/利確/保護の順で同時成立を判定。')


def close_prefix(context: dict, decision: dict) -> dict:
    """
    機能: 判断までの実注文を保持し、次正常気配で残UIDを返済して場を終了する。
    引数: context/decision(dict) は同GU文脈と因果的な初先着。
    返り値: dict は実会計。未完成接頭で次quoteが未観測なら未返済・予約を保持する。
    """
    row=decision['row'];base=context['base'];quotes=context['quotes'];finish=context['finish']
    if row is None:
        result=dict(base);result['control']=dict(発動=False,未完成接頭=not finish)
        return result
    assert 0<=row<len(context['normal']) and context['normal'][row]
    chosen=base['orders'][:,0]<=row;orders=base['orders'][chosen].copy();uids=base['order_uids'][chosen].copy()
    state=daily.outstanding_at(orders,uids,context['key'][1]);held=[v for v in state.values() if v['remaining']]
    targets=np.full(len(orders),-1,np.int64);fill=row;pending=False
    if held:
        future=np.flatnonzero(context['normal'][row+1:])
        if not len(future):
            assert not finish,'完成場なのに次正常気配が無い'
            pending=True;fill=None
        else:
            fill=row+1+int(future[0]);extra=[]
            for item in held:
                side=-item['side'];price=quotes['ask' if side>0 else 'bid'][fill]
                extra.append([fill,row,item['cid'],side,item['remaining'],price,96,0])
            orders=np.concatenate((orders,np.asarray(extra,float)));uids=np.concatenate((uids,np.full(len(extra),-1,np.int64)))
            targets=np.concatenate((targets,np.array([v['uid'] for v in held],np.int64)))
    result=daily.reconstruct(context['key'],orders,uids,quotes,targets,finish=finish and not pending)
    np.testing.assert_allclose(result['equity_yen'][:row+1],base['equity_yen'][:row+1],atol=1e-5,rtol=1e-12)
    assert not np.any(orders[(orders[:,0]>row)&(orders[:,7]==1)])
    result['control']=dict(発動=True,判断行=row,理由=decision['reason'],判断原seq=int(quotes['seq'][row]),
        判断価格時計=float(quotes['time_s'][row]),判断時清算利益=float(base['liquidation_yen'][row]),
        返済行=fill,返済予約=pending,未完成接頭=not finish,以後新規なし=True,未来親テンプレート参照=False)
    return result
