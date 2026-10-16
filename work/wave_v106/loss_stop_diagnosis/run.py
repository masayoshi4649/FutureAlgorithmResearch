"""指定二例の実注文を読むだけで、比例損切りと旧回復利確の気配・料を確認する。"""

import argparse
from datetime import datetime,timezone,timedelta
from decimal import Decimal,ROUND_FLOOR
import math

import numpy as np
import common


def stamp(seconds: float) -> str:
    """
    機能: 保存価格時計をJSTで表示し、真の受信時間と区別する。
    引数: seconds(float) は価格代理時計のepoch秒。
    返り値: str は日付付きの代理時刻。
    """
    return datetime.fromtimestamp(float(seconds),timezone(timedelta(hours=9))).isoformat(timespec='milliseconds')


def observation(account: dict, row: int) -> dict:
    """
    機能: 同normal原行のseq・価格時計・BBO・現在値をそのまま取り出す。
    引数: account(dict)、row(int) は授権された保存口座と行番号。
    返り値: dict は有限値又はNoneの観測。未来正常行へ置き換えない。
    """
    record,quotes=account['record'],account['quotes'];assert record['seq'][row]==quotes['seq'][row]
    finite=lambda v:float(v) if np.isfinite(v) else None
    return dict(normal_row=row,raw_seq=int(record['seq'][row]),price_time_s=float(record['time_s'][row]),
        価格代理JST=stamp(record['time_s'][row]),last=finite(record['price'][row]),
        bid=finite(quotes['bid'][row]),ask=finite(quotes['ask'][row]),quote_valid=bool(quotes['quote_valid'][row]))


def inspect(selected: dict, new: dict, old: dict, account: dict) -> dict:
    """
    機能: 同じ初回新規から、新損失停止と旧実利確の時刻・料・必要幅を比較する。
    引数: selected/new/old/account(dict) は固定二例の指定、実新旧台帳と入力。
    返り値: dict は旧実会計との診断。政策再生や未測定救済損益を計算しない。
    """
    symbol=selected['symbol'];parent=selected['parent'];multiplier=1000. if symbol=='TOPIX' else 10.
    fee=Decimal('41.8' if symbol=='TOPIX' else '11');tick=float(account['record']['tick'])
    key=selected['session'],symbol;assert new['key']==old['key']==key
    newfirst=new['orders'][new['orders'][:,7]==1][0];oldfirst=old['orders'][old['orders'][:,7]==1][0]
    np.testing.assert_array_equal(newfirst,oldfirst)
    assert int(newfirst[2])==parent and newfirst[4]==selected['first']['quantity']
    source,fill=int(newfirst[1]),int(newfirst[0]);qty=int(newfirst[4]);side=int(newfirst[3]);entry=float(newfirst[5])
    posts=[p for p in account['feed'] if int(p[0])==source and int(p[2])==parent and int(p[7])==1]
    assert len(posts)==1
    control=new['control'];assert control['発動'] and control['種別']=='損失予算'
    decision,exitrow=int(control['判断行']),int(control['返済行'])
    rows=[p for p in new['parent'] if p['親']==parent];oldrows=[p for p in old['parent'] if p['親']==parent]
    assert len(rows)==len(oldrows)==1 and rows[0]['収支']==selected['new_net'] and oldrows[0]['収支']==selected['old_net']
    actual_close=new['orders'][(new['orders'][:,2]==parent)&(new['orders'][:,7]==0)]
    previous_orders=new['orders'][new['orders'][:,0]<fill]
    partial=new['orders'][(new['orders'][:,7]==0)&(new['orders'][:,0]<=decision)]
    conditions=dict(初回実親=len(previous_orders)==0,過去損益ゼロ=len(previous_orders)==0,
        判断前部分返済無し=len(partial)==0,アンカー数量一致=new['goal_anchor']['数量']==qty)
    math_result=None
    start=observation(account,fill);spread=start['ask']-start['bid']
    costs=2*int((Decimal(qty)*fee).to_integral_value(rounding=ROUND_FLOOR))
    initial=-qty*spread*multiplier-costs
    if all(conditions.values()):
        loss=float(control['損失予算']);goal=float(control['目標'])
        adverse=(loss-qty*spread*multiplier-costs)/(qty*multiplier)
        favorable=(goal+qty*spread*multiplier+costs)/(qty*multiplier)
        clearing=start['bid'] if side>0 else start['ask']
        math_result=dict(初期清算気配=clearing,初期気配差=spread,往復注文料=costs,初期費用後清算=initial,
            損失線円=loss,利益線円=goal,初期清算気配から必要逆行幅=adverse,初期清算気配から必要順行幅=favorable,
            必要逆行の観測呼値数=max(0,math.ceil(adverse/tick-1e-12)),必要順行の観測呼値数=math.ceil(favorable/tick-1e-12),
            式='逆行=(L−q×spread×倍率−往復料)/(q×倍率)、順行=(P＋q×spread×倍率＋往復料)/(q×倍率)。正常呼値へ上方切上げ。')
    old_closes=old['orders'][(old['orders'][:,2]==parent)&(old['orders'][:,7]==0)]
    quote=account['quotes'];qok=quote['quote_valid']&np.isfinite(quote['bid'])&np.isfinite(quote['ask'])&(quote['bid']>0)&(quote['ask']>quote['bid'])
    assert exitrow==decision+1+int(np.flatnonzero(qok[decision+1:])[0])
    at=observation(account,decision)
    direct=side*qty*((at['bid'] if side>0 else at['ask'])-entry)*multiplier-costs
    if all(conditions.values()):assert abs(direct-control['判断時清算利益'])<1e-5
    return dict(session=key[0],symbol=symbol,parent=parent,旧利益=oldrows[0]['収支'],新損失=rows[0]['収支'],
        公開=observation(account,source),公開ATR=float(posts[0][9]),W60公開票=account['trade_features']['60'][source],
        初回実新規=dict(**start,side=side,quantity=qty,entry_price=entry,費用後初期清算円=initial),
        比例損失判断=dict(**at,清算利益円=control['判断時清算利益'],損失線円=control['損失予算']),
        次正常返済=dict(**observation(account,exitrow),実返済注文=actual_close.tolist()),
        旧後続の実返済=[dict(**observation(account,int(o[0])),注文=o.tolist()) for o in old_closes],
        旧停止判断=old['control'],単純数式の前提=conditions,単純数式=math_result,
        範囲='既存の実親・実注文・気配だけ。板の厚さ/補充、真の到着時刻、新たな救済PLは推定しない。')


def run() -> None:
    """
    機能: 根の明示授権後、固定四台帳と1〜2packetだけを各一読して二例を保存する。
    引数: なし。CLIのroot-review-completeを根が指定する。
    返り値: None。結果前固定の対象と源を変えず、追加金融/APIを実行しない。
    """
    plan,_=common.small(common.HERE/'二例の初回同数量回復勝ちを調べる固定計画.json')
    assert common.sources()==plan['source_SHA256']
    for relative,sha in plan['metadata_SHA256'].items():
        assert common.small(common.ROOT/relative)[1]==sha
    packets={session:common.saved(item) for session,item in plan['input_packets'].items()}
    results=[]
    for selected in plan['selected']:
        new=common.saved(selected['new_ledger']);old=common.saved(selected['old_ledger'])
        packet=packets[selected['session']];assert packet['session']==selected['session']
        results.append(inspect(selected,new,old,packet['accounts'][selected['symbol']]))
    assert common.sources()==plan['source_SHA256']
    common.write('同一初回の比例損切りと旧回復実利確の二例.json',dict(全合格=True,results=results,
        台帳一読=4,input一読=len(packets),金融再生=0,原板読取=0,NPZ読取=0,API=0,source開始終端一致=True,
        source_SHA256=plan['source_SHA256']))
    print('授権した四台帳だけの二例診断完了。新金融0。',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root-review-complete',action='store_true',required=True)
    args=parser.parse_args();run()
