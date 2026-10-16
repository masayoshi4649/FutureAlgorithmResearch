"""新規価格と初期返済気配を混同しない、残目標・残損失の純算術oracle。"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
import hashlib
import json


HERE=Path(__file__).resolve().parent


def decimal(value: float|int|str) -> Decimal:
    """
    機能: 数値を十進文字列経由で純算術へ変換する。
    引数: value(float|int|str)は保存小値又は人工値。
    返り値: Decimalは二進誤差を持ち込まない数値。
    """
    return Decimal(str(value))


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一注文の税込片道料を整数円へ独立切捨てする。
    引数: quantity(int)、symbol(str)は実注文枚数と商品。
    返り値: intは注文料。過去親の料金を含めない。
    """
    unit=Decimal('41.8') if symbol=='TOPIX' else Decimal('11')
    return int((quantity*unit).to_integral_value(rounding=ROUND_FLOOR))


def distances(symbol: str, quantity: int, goal: float, loss: float, previous_net: float, spread: float) -> dict:
    """
    機能: 過去親netを二重課金せず、今親の入口価格と初期返済側価格から残幅を算出する。
    引数: symbol(str)、quantity(int)、goal/loss/previous_net/spread(float)は商品・q・固定線・過去net・実fill気配差。
    返り値: dictは純算術の符号付き幅。今親は未部分返済・全q一括往復だけを仮定する。
    """
    value=Decimal(1000 if symbol=='TOPIX' else 10);tick=Decimal('.5') if symbol=='TOPIX' else Decimal('10')
    now_fee=Decimal(2*fee(quantity,symbol));denominator=quantity*value
    previous=decimal(previous_net);g=decimal(goal);budget=decimal(loss);s=decimal(spread)
    profit_entry=(g-previous+now_fee)/denominator
    loss_entry=(budget+previous-now_fee)/denominator
    profit_quote=profit_entry+s;loss_quote=loss_entry-s
    initial_net=previous-denominator*s-now_fee
    return dict(新規価格から利益方向幅=float(profit_entry),新規価格から許容逆行幅=float(loss_entry),
        初期返済気配から利益方向幅=float(profit_quote),初期返済気配から許容逆行幅=float(loss_quote),
        新規価格から利益呼値=int((profit_entry/tick).to_integral_value(rounding=ROUND_CEILING)),
        初期返済気配から利益呼値=int((profit_quote/tick).to_integral_value(rounding=ROUND_CEILING)),
        初期返済気配から損失呼値=int((loss_quote/tick).to_integral_value(rounding=ROUND_CEILING)),
        初期清算=float(initial_net),今親一括往復予定料=int(now_fee),
        起点='profit_entryは実新規価格。profit_quoteは初期清算側bid/askで実fill spreadを加算。loss_quoteはspreadを減算。')


def main() -> None:
    """
    機能: 二起点・過去親net・左右対称・今親料だけの純人工を固定する。
    引数: なし。正式結果・計画・packet・台帳を読まない。
    返り値: Noneは自所有の非金融証跡。原因診断の結果を待つ準備に限定する。
    """
    checks=0
    for symbol,full in (('TOPIX',5),('NK225',10)):
        value=1000 if symbol=='TOPIX' else 10;tick=.5 if symbol=='TOPIX' else 10.;budget=5000 if symbol=='TOPIX' else 2000.
        for quantity in range(1,full+1):
            for previous in (-582.,-82.,-22.,0.,78.):
                for spread in (tick,2*tick):
                    result=distances(symbol,quantity,quantity*tick*value,budget,previous,spread)
                    den=quantity*value;now_fee=result['今親一括往復予定料'];goal=quantity*tick*value
                    for side in (1,-1):
                        entry=4145.5 if symbol=='TOPIX' else 65720.
                        initial_quote=entry-side*spread
                        profit_exit=entry+side*result['新規価格から利益方向幅']
                        loss_exit=entry-side*result['新規価格から許容逆行幅']
                        assert abs(previous+side*den*(profit_exit-entry)-now_fee-goal)<1e-6
                        assert abs(previous+side*den*(loss_exit-entry)-now_fee+budget)<1e-6
                        assert abs(side*(profit_exit-initial_quote)-result['初期返済気配から利益方向幅'])<1e-9
                        assert abs(side*(initial_quote-loss_exit)-result['初期返済気配から許容逆行幅'])<1e-9
                        checks+=4
    examples=dict(TOPIX=distances('TOPIX',2,1000.,2000.,0.,.5),NK225=distances('NK225',3,300.,600.,0.,10.))
    assert examples['TOPIX']['新規価格から利益方向幅']==.583 and examples['TOPIX']['初期返済気配から利益方向幅']==1.083
    assert examples['NK225']['新規価格から利益方向幅']==12.2 and examples['NK225']['初期返済気配から利益方向幅']==22.2
    assert all(v['新規価格から利益呼値']==2 and v['初期返済気配から利益呼値']==3 for v in examples.values())
    path=HERE/'残目標二起点と今親料だけの純算術人工.json';assert not path.exists()
    output=dict(全合格=True,独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),人工算術照合数=checks,
        計算例=examples,式=dict(新規価格利益='(g−前親net清算＋今親新規料＋今親予定全返済料)/(実q×倍率)',
            初期返済気配利益='新規価格利益幅＋実fill spread',新規価格損失='(L＋前親net清算−今親新規料−今親予定全返済料)/(実q×倍率)',
            初期返済気配損失='新規価格損失幅−実fill spread'),
        留保=['全q一括返済の算術。今親部分返済や後続qがある場合の実取引保証ではない。',
              '前親netには過去料が控除済み。今親予定料だけを追加する。',
              '符号付き幅は瞬間の線超過も表せる。負値を安全な待機幅と扱わない。',
              '初期返済気配を起点とする呼値数は、新規価格起点よりspread分だけ大きい。'],
        正式結果=0,計画JSON=0,原板=0,NPZ=0,packet=0,ledger=0,金融=0,API=0)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,人工算術=checks,SHA256=hashlib.sha256(path.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
