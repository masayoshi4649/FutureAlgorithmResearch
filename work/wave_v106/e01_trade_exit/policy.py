"""実残玉の反対票が強く、清算損失が4呼値へ達した時だけ早く場を終える。"""

import numpy as np

import daily


def early_mask(base: dict, observed: dict, symbol: str, ticks: float=4.) -> np.ndarray:
    """
    機能: 当行実fill/部分返済後の残玉方向・当時票・fee清算損失から追加退出を判定する。
    引数: base/observed(dict)、symbol(str)、ticks(float)は実GU接頭と4呼値損失幅。
    返り値: ndarray[bool]は保有中だけの追加退出。flat・未知・2票未満は発火しない。
    """
    assert not np.any((base['long_qty']>0)&(base['short_qty']>0)),'元GU単一方向契約'
    side=np.sign(base['long_qty']-base['short_qty'])
    total=observed['up_votes'].astype(np.int64)+observed['down_votes']
    unit=daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]
    return (side!=0)&observed['known']&(total>=2)&np.isfinite(observed['balance'])&\
        (side*observed['balance']<=-.25)&(base['liquidation_yen']<=-ticks*unit)


def apply_policy(base: dict, quotes: dict, observed: dict, config: dict) -> dict:
    """
    機能: P1利益/hard8損失/逆票かつ4損失の最初到達で次正常気配UID別返済・場停止する。
    引数: base/quotes/observed/config(dict)は保存実GU・同normal票・固定政策。
    返り値: dictは実UID会計と判断根拠。未来返済テンプレートやpaperを再生しない。
    """
    symbol=base['key'][1];valid=daily.normal_mask(quotes)
    unit=daily.TICK[symbol]*daily.QUANTITY[symbol]*daily.VALUE[symbol]
    goal=config['profit_ticks']*unit;loss=config['loss_ticks']*unit
    early=early_mask(base,observed,symbol,config['early_loss_ticks'])
    profit=base['liquidation_yen']>=goal;hard=base['liquidation_yen']<=-loss
    positions=np.flatnonzero(valid&(profit|hard|early))
    if not len(positions):
        result=daily.reconstruct(base['key'],base['orders'],base['order_uids'],quotes)
        result['control']=dict(発動=False,目標=goal,損失予算=loss,逆票損失閾値=config['early_loss_ticks']*unit)
        return result
    decision=int(positions[0]);is_profit=bool(profit[decision]);is_hard=bool(hard[decision])
    kind='利益目標' if is_profit else '損失予算' if is_hard else '逆票かつ4呼値損失'
    reason=94 if is_profit else 95 if is_hard else 96
    prefix=base['orders'][:,0]<=decision;orders=base['orders'][prefix].copy();uids=base['order_uids'][prefix].copy()
    outstanding=daily.outstanding_at(orders,uids,symbol);remaining=[v for v in outstanding.values() if v['remaining']]
    targets=np.full(len(orders),-1,np.int64);fill_row=decision
    if remaining:
        future=np.flatnonzero(valid[decision+1:]);assert len(future),'場内次正常気配なし'
        fill_row=decision+1+int(future[0]);appended=[]
        for item in remaining:
            side=-item['side'];price=quotes['ask' if side>0 else 'bid'][fill_row]
            appended.append([fill_row,decision,item['cid'],side,item['remaining'],price,reason,0])
        orders=np.concatenate((orders,np.asarray(appended,float)));uids=np.concatenate((uids,np.full(len(appended),-1,np.int64)))
        targets=np.concatenate((targets,np.asarray([v['uid'] for v in remaining],np.int64)))
    result=daily.reconstruct(base['key'],orders,uids,quotes,targets)
    np.testing.assert_allclose(result['equity_yen'][:decision+1],base['equity_yen'][:decision+1],atol=1e-5,rtol=0.)
    np.testing.assert_array_equal(orders[:prefix.sum()],base['orders'][prefix])
    assert not np.any(orders[(orders[:,0]>decision)&(orders[:,7]==1)])
    assert result['long_qty'][fill_row:].sum()==result['short_qty'][fill_row:].sum()==0
    balance=float(observed['balance'][decision]) if np.isfinite(observed['balance'][decision]) else None
    result['control']=dict(発動=True,種別=kind,判断行=decision,判断原seq=int(quotes['seq'][decision]),
        判断価格時計=float(quotes['time_s'][decision]),返済行=fill_row,返済原seq=int(quotes['seq'][fill_row]),
        返済価格時計=float(quotes['time_s'][fill_row]),判断時清算利益=float(base['liquidation_yen'][decision]),
        実返済後収支=result['summary']['収支'],判断から返済の悪化=result['summary']['収支']-float(base['liquidation_yen'][decision]),
        元接頭注文件数=int(prefix.sum()),残UID別注文数=len(remaining),目標=goal,損失予算=loss,
        逆票損失閾値=config['early_loss_ticks']*unit,既知票=bool(observed['known'][decision]),
        買票=int(observed['up_votes'][decision]),売票=int(observed['down_votes'][decision]),
        買方向釣合い=balance,実残玉方向=int(np.sign(base['long_qty'][decision]-base['short_qty'][decision])),
        以後新規なし=True,未来返済テンプレート参照=False)
    return result
