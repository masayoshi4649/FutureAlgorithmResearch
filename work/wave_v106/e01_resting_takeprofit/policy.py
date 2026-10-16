"""最初の実建玉に、ラージ観測一呼値の常設利確又は接触後成行を適用する。"""

from decimal import Decimal,ROUND_FLOOR
import numpy as np

VALUE={'TOPIX':1000.,'NK225':10.}
TICK={'TOPIX':.5,'NK225':10.}
FEE={'TOPIX':41.8,'NK225':11.}
QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}
TRIAL_ID='106_E01最初の実建玉の一呼値常設指値と接触後成行12対照'


def fee(qty: int, symbol: str) -> int:
    """
    機能: 一注文の片道手数料を税込単価から円未満切捨てする。
    引数: qty(int)、symbol(str)は実注文枚数と商品。
    返り値: intは手数料。別注文を合算して丸めない。
    """
    return int((Decimal(qty)*Decimal(str(FEE[symbol]))).to_integral_value(rounding=ROUND_FLOOR))


def configs() -> list[dict]:
    """
    機能: 二入口・損切り4/8/16・利確二法の十二条件を結果前に返す。
    引数: なし。
    返り値: list[dict]は固定条件。一場一親で旧GUの後続や部分返済を採用しない。
    """
    return [dict(id=f'E01_FIRST_W60_{mode}_TP1_S{stop}_{method}',mode=mode,stop_ticks=stop,
        takeprofit_ticks=1,method=method,quantity=QUANTITY,cap=CAP,
        GU_id=f'E01_TRADE_W60_{mode}_D0_GU')
        for mode in ('CONFIRM','VETO') for stop in (4,8,16) for method in ('RESTING','NEXT_MARKET')]


def valid(quotes: dict) -> np.ndarray:
    """
    機能: 保存normal最良気配の有限正かつ買気配より高い売気配資格を判定する。
    引数: quotes(dict)はbid/ask/quote_valid。
    返り値: ndarray[bool]は約定モデル上の正常行。未来正常行へ補完しない。
    """
    b,a=quotes['bid'],quotes['ask']
    return quotes['quote_valid']&np.isfinite(b)&np.isfinite(a)&(b>0)&(a>b)


def play(account: dict, entry: dict | None, config: dict, finish: bool=True) -> dict:
    """
    機能: 保存最初newfill後だけを逐次観測し、単一玉の利確/損切り/既知timerを執行する。
    引数: account(dict)はquotes/record/quiet二列、entry(dict|None)は最初実注文、config(dict)、finish(bool)。
    返り値: dictは実注文・親・全行清算と予約系譜。常設の触れ全量約定は仮定である。
    """
    symbol=account['symbol'];q=account['quotes'];record=account['record'];qok=valid(q);n=len(qok)
    assert n>0 and np.all(np.isfinite(q['time_s'])) and len(account['quiet'])==len(account['quiet_force'])==n
    if finish:assert q['time_s'][-1]>=record['limit'],'切断入力を完成と扱わない'
    orders=[];exitrow=-1;decision=-1;reason='未発動';price=None;scheduled=False;timerrow=-1
    target=stop=None;pending=None;pending_decision=-1;entryrow=-1;side=qty=cid=uid=0;E=0.
    if entry is not None:
        o=np.asarray(entry['order'],float);assert o.shape==(8,) and o[7]==1
        entryrow,source,cid,side,qty=map(int,(o[0],o[1],o[2],o[3],o[4]));uid=int(entry['uid']);E=float(o[5])
        assert 0<=source<entryrow<n and side in (-1,1) and qty==QUANTITY[symbol] and uid>=0
        assert qok[entryrow] and E==q['ask' if side>0 else 'bid'][entryrow]
        assert not account['quiet'][entryrow] and not account['quiet_force'][entryrow] and q['time_s'][entryrow]<record['limit']
        target=E+side*TICK[symbol];stop=E-side*config['stop_ticks']*TICK[symbol];orders.append(o.copy())
        for i in range(entryrow,n):
            # ----------------------------------------
            # 公開quiet/場内期限を先に確定する。予約や利確接触より優先し、不正気配中も保持する。
            if not scheduled and (account['quiet'][i] or account['quiet_force'][i] or q['time_s'][i]>=record['limit']):
                scheduled=True;timerrow=i
            if scheduled:
                if qok[i] and i>entryrow:
                    exitrow=i;decision=max(entryrow,timerrow-1);reason='場内期限' if q['time_s'][timerrow]>=record['limit'] else '既知quiet'
                    price=float(q['bid' if side>0 else 'ask'][i]);break
                continue
            # ----------------------------------------
            # 判断後予約は次正常気配で不可逆に執行する。後の利確到達で損切り予約を戻さない。
            if pending is not None:
                if qok[i] and i>decision:
                    exitrow=i;reason=pending;price=float(q['bid' if side>0 else 'ask'][i]);break
                continue
            if not qok[i]:continue
            liquidation=float(q['bid' if side>0 else 'ask'][i])
            if side*(liquidation-stop)<=0:
                decision=i;pending_decision=i;pending='損切り';continue
            if i>entryrow and side*(liquidation-target)>=0:
                if config['method']=='RESTING':
                    exitrow=i;decision=entryrow;reason='常設利確指値';price=float(target);break
                decision=i;pending_decision=i;pending='利確判断後成行'
        if finish:assert exitrow>=0,'場内正常返済quoteなし'
        if exitrow>=0:
            codes={'常設利確指値':101,'利確判断後成行':102,'損切り':103,'既知quiet':104,'場内期限':105}
            orders.append(np.array([exitrow,decision,cid,-side,qty,price,codes[reason],0.]))
    output=np.asarray(orders,float).reshape((-1,8));equity=np.zeros(n);liquidation=np.zeros(n);held=np.zeros(n,np.int64)
    entryfee=fee(qty,symbol) if entry is not None else 0;exitfee=entryfee if exitrow>=0 else 0
    net=0.;gross=0.
    if entry is not None:
        last=np.maximum.accumulate(np.where(qok,np.arange(n),-1));assert np.all(last[entryrow:]>=0)
        end=exitrow if exitrow>=0 else n
        marks=q['bid' if side>0 else 'ask'][last[entryrow:end]]
        equity[entryrow:end]=side*qty*(marks-E)*VALUE[symbol]-entryfee
        liquidation[entryrow:end]=equity[entryrow:end]-fee(qty,symbol);held[entryrow:end]=qty
        if exitrow>=0:
            gross=side*qty*(price-E)*VALUE[symbol];net=gross-entryfee-exitfee
            equity[exitrow:]=liquidation[exitrow:]=net
    parents=[]
    if entry is not None and exitrow>=0:
        parents=[dict(親=cid,新規行=entryrow,最終返済行=exitrow,方向=side,枚数=qty,費用=entryfee+exitfee,粗損益=gross,収支=net)]
    gain=max(0.,net);loss=max(0.,-net);closed=len(parents)
    summary=dict(session=account['session'],symbol=symbol,利益=gain,損失=loss,収支=net,親数=closed,
        勝ち親=int(net>0),負け親=int(net<0),零親=int(closed and net==0),
        勝ち枚数=qty if net>0 else 0,負け枚数=qty if net<0 else 0,零枚数=qty if closed and net==0 else 0,
        新規枚数=qty if entry is not None else 0,費用=entryfee+exitfee,注文件数=len(output),全会計合格=bool(finish))
    control=dict(発動=exitrow>=0,種別=reason,新規行=entryrow,利確公開行=entryrow,固定利確価格=target,
        固定損切り価格=stop,判断行=decision,返済行=exitrow,timer開始行=timerrow,
        pending=pending,元観測予約判断行=pending_decision,単一親=True,最初実newfillのみ=True,原GU出口使用=False,同新規行利確不可=True,
        常設到達全量約定仮定=config['method']=='RESTING')
    return dict(key=(account['session'],symbol),orders=output,order_uids=np.array([uid,-1][:len(output)],np.int64),
        parent=parents,summary=summary,control=control,equity_yen=equity,liquidation_yen=liquidation,
        long_qty=held if side>0 else np.zeros(n,np.int64),short_qty=held if side<0 else np.zeros(n,np.int64),
        source_entry=entry,fee_model='一注文別floor、常設指値は固定line価格仮定。',
        呼値定義='ラージ板観測幅TOPIX0.5pt/NK10円。実ミニ/マイクロの2呼値。')
