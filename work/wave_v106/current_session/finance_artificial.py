"""未返済接頭の注文・全行清算・閉じた親と残UIDを人工だけで独立確認する。"""

from copy import deepcopy

import numpy as np

import common
import core
import partial_accounting as accounting
import runner


def fixture(symbol: str, side: int, family: int, mode: int) -> tuple:
    """
    機能: 初回決済1親と次の未返済1親を持つnative呼値の単一位置素材を作る。
    引数: symbol(str)、side/family/mode(int)は商品、方向、C/R、成行/指値。
    返り値: tuple[dict,dict,dict]は人工prepared/normal/固定config。実板は読まない。
    """
    n=400;tick,opening=(.5,4000.) if symbol=='TOPIX' else (10.,68000.)
    time=np.arange(n,dtype=float);bid=np.full(n,opening if side==1 else opening-tick);ask=bid+tick
    record=dict(symbol=symbol,session='人工接頭',seq=np.arange(n,dtype=np.int64),time_s=time,bid=bid,ask=ask,
        price=(bid+ask)/2,quote_valid=np.ones(n,bool),price_valid=np.ones(n,bool),tick=tick,start=0.,end=1000.,limit=1000.,人工素材=True)
    p=dict(record=record,reference_open=opening,signal=dict(trend_width=np.ceil(opening*.004/tick-1e-10)*tick))
    c=dict(entry_id='人工接頭',event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),entry_quality=np.ones(n,bool),
        entry_reset=np.zeros(n,bool),execution_to_raw_index=np.arange(n,dtype=np.int64),decisions=[],entry_families=np.zeros(n,np.int8),
        target_prices=np.full(n,np.nan),entry_stop_prices=np.full(n,np.nan),entry_limit_prices=np.full(n,np.nan),entry_modes=np.zeros(n,np.int8),
        range_pending_trend=np.zeros(n,bool),quiet=np.zeros(n,bool),quiet_start_s=np.full(n,np.nan))
    config=deepcopy(core.configs()[0]);config['id']='人工接頭'
    record['quote_valid'][331]=False
    if family==2 and mode==2:clear(p,333,side,opening-side*tick,334)
    first_close=opening+side*(12 if family==2 else -5)*tick;clear(p,360,side,first_close,391)
    for row in (330,392):
        support=opening if family==1 else opening-side*4*tick
        c['event'][row]=side;c['support_price'][row]=support;c['entry_families'][row]=family;c['entry_modes'][row]=mode if family==2 else 1
        roots=[dict(anchor_raw_seq=row-1,support_price=support)] if family==1 else []
        metadata=dict(row=row,normal_row=row,raw_row=row,raw_seq=row,side=side,support_price=support,selected_support_roots=roots)
        if family==2:
            c['entry_stop_prices'][row]=support;c['target_prices'][row]=opening+side*12*tick
            if mode==2:c['entry_limit_prices'][row]=record['bid'][row] if side==1 else record['ask'][row]
            metadata.update(stop_price=support,target_price=c['target_prices'][row],reference_kind='純価格範囲外停止')
        c['decisions'].append(metadata)
    if family==2 and mode==2:clear(p,396,side,opening-side*tick)
    return p,c,config


def clear(p: dict, begin: int, side: int, value: float, end: int | None=None) -> None:
    """
    機能: 人工の清算側quoteを指定区間だけ更新する。
    引数: p(dict)、begin/side(int)、value(float)、end(int|None)は素材と区間。
    返り値: None。反対側はnative1呼値差。
    """
    r=p['record'];s=slice(begin,end);r['bid'][s]=value if side==1 else value-r['tick'];r['ask'][s]=value+r['tick'] if side==1 else value


def prefix(p: dict, c: dict, length: int) -> tuple:
    """
    機能: 同一人工素材を実行前に原row接頭へ切る。
    引数: p/c(dict)、length(int)はprepared/normalと長さ。
    返り値: tuple[dict,dict]は接頭。通常end/limitはそのまま。
    """
    prepared=deepcopy(p);prepared['record']={k:v[:length].copy() if isinstance(v,np.ndarray) else v for k,v in p['record'].items()}
    case={k:v[:length].copy() if isinstance(v,np.ndarray) else deepcopy(v) for k,v in c.items()}
    case['decisions']=[v for v in case['decisions'] if v['row']<length];return prepared,case


def rejects(p: dict, c: dict, config: dict, output: dict, kind: str) -> None:
    """
    機能: 費用/気配/時刻/予約/系譜/時価の意図的不正を独立会計が拒否するか確認する。
    引数: p/c/config/output(dict)、kind(str)は正しい人工と変更種別。
    返り値: None。不正を許す場合は例外。
    """
    bad=deepcopy(output);case=deepcopy(c);first=bad['orders'][0]
    if kind=='fee':first[9]+=1
    elif kind=='price':first[6]+=p['record']['tick']
    elif kind=='late':first[0]+=1;first[11]+=1
    elif kind=='future_root':case['decisions'][0]['selected_support_roots'][0]['anchor_raw_seq']=10000
    elif kind=='curve':bad['curve'][-1]+=p['record']['tick']*config['quantity'][p['record']['symbol']]*1000
    elif kind=='cancel_revive':
        e=bad['events'][0].copy();e[0]=int(first[0])-1;e[3]=6
        bad['events']=np.vstack((bad['events'],e));bad['events']=bad['events'][np.argsort(bad['events'][:,0],kind='stable')]
    else:raise AssertionError(kind)
    try:accounting.inspect(p['record'],bad,case,config)
    except AssertionError:return
    raise AssertionError(('不正を受理した',kind))


def run() -> None:
    """
    機能: 鏡像/native/市場指値/未返済/未約定/無取引/接頭因果と不正拒否を確認する。
    引数: なし。
    返り値: None。現場入力gzip、API、原本、新正式金融は一切読まない。
    """
    assert not runner.ARTIFICIAL.exists();engine=runner.runtime(True);before=runner.sources();checks=[]
    for symbol in core.SYMBOLS:
        for side in (1,-1):
            for family,mode in ((1,1),(2,1),(2,2)):
                p,c,config=fixture(symbol,side,family,mode);q=config['quantity'][symbol]
                output=engine.play(p,c,config,quantity=q,finish=False,python=True)
                result=accounting.inspect(p['record'],output,c,config)
                assert result['closed_campaigns']==1 and len(result['open_positions'])==1
                assert result['held_long']+result['held_short']==q
                assert result['actual_liquidation_value']==result['realized_net']+result['open_mark_net']
                assert result['reserved_exit_fees']==accounting.fee(q,symbol)
                pp,cc=prefix(p,c,350);short=engine.play(pp,cc,config,quantity=q,finish=False,python=True)
                partial=accounting.inspect(pp['record'],short,cc,config)
                assert partial['closed_campaigns']==0 and partial['realized_net']==0 and partial['held_long']+partial['held_short']==q
                np.testing.assert_array_equal(short['orders'],output['orders'][output['orders'][:,0]<350])
                np.testing.assert_array_equal(short['curve'],output['curve'][:350])
                np.testing.assert_array_equal(short['target_trace'],output['target_trace'][:350])
                future=deepcopy(p);clear(future,355,side,p['reference_open']-side*20*p['record']['tick'])
                changed=engine.play(future,c,config,quantity=q,finish=False,python=True)
                np.testing.assert_array_equal(short['orders'],changed['orders'][changed['orders'][:,0]<350])
                np.testing.assert_array_equal(short['curve'],changed['curve'][:350])
                checks.append(symbol+str(side)+'源'+str(family)+'注文'+str(mode)+'：実現/残UID料/全行/prefix不変')
                if family==1:
                    for kind in ('fee','price','late','future_root','curve','cancel_revive'):rejects(p,c,config,output,kind)
                    checks.append(symbol+str(side)+'：独立会計の6不正拒否')
    p,c,config=fixture('TOPIX',1,2,2);p,c=prefix(p,c,333)
    pending=engine.play(p,c,config,quantity=5,finish=False,python=True);a=accounting.inspect(p['record'],pending,c,config)
    assert a['pending_entry']==5 and a['held_long']==a['held_short']==0 and a['actual_liquidation_value']==a['total_paid_fees']==0
    assert a['profit_share'] is None;checks.append('未約定5枚はexposure/料金0、無取引の比率を勝ちにしない')
    p,c,config=fixture('TOPIX',1,1,1);c['event'][:]=0;c['entry_families'][:]=0;c['decisions']=[]
    empty=engine.play(p,c,config,quantity=5,finish=False,python=True);e=accounting.inspect(p['record'],empty,c,config)
    assert e['order_count']==e['closed_campaigns']==e['actual_liquidation_value']==0 and e['profit_share'] is None
    checks.append('完全無発火は勝ちでなく未測定、全curve0')
    # ----------------------------------------
    # 本物の原JSON→C/six/R_PRICE接続は既入力fixtureを用い、人工限定のPython執行を行う。
    input_art=common.module('106現Night接頭会計の原JSON人工だけ',common.HERE/'artificial.py')
    actual=core.build(input_art.range_fixture(),python=True);cfg=core.configs()[1];case=core.normal(actual,'TOPIX',cfg)
    actual['prepared']['TOPIX']['record']['人工素材']=True
    true_output=engine.play(actual['prepared']['TOPIX'],case,cfg,quantity=5,finish=False,python=True)
    true_account=accounting.inspect(actual['prepared']['TOPIX']['record'],true_output,case,cfg)
    assert true_account['held_long']==5 and true_account['realized_net']==0 and true_account['open_mark_net']<0
    checks.append('実原JSONfactoryのR_PRICE候補から未返済損失も隠さず独立分解')
    p,c,config=fixture('NK225',-1,2,2);common.immutable(p);common.immutable(c)
    native=engine.play(p,c,config,quantity=10,finish=False,python=False)
    a=accounting.inspect(p['record'],native,c,config)
    assert a['all_row_order_equity_verification'];checks.append('正式readonly signatureでもPython/JITの全経済同値')
    reference=engine.play(p,c,config,quantity=10,finish=False,python=True)
    for field in ('orders','trades','curve','target_trace'):np.testing.assert_array_equal(native[field],reference[field])
    runner.check_sources(before)
    common.write(runner.ARTIFICIAL,dict(全合格=True,人工専用=True,検査数=len(checks),検査=checks,
        source_SHA256=before,開始終端source一致=True,現入力gzip読取=0,現在API取得=0,現Night内容読取=0,
        旧33cache読取=0,新正式金融再生=0,旧accounting_account利用=0,
        限界='固定単一位置/追加なし/全量約定返済の仕様を検算。一般の部分数量返済・複数UID両建て会計とは呼ばない。'))
    print('接頭会計と初約定/未返済の人工検査合格',flush=True)


if __name__=='__main__':run()
