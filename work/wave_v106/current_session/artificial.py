"""未取得Nightの同原行接続と、後のquoteを持ち込まない接頭会計を人工で検査する。"""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
import io
import json
import sys

import numpy as np

import common
import core
import prepare


JST=timezone(timedelta(hours=9))
NIGHT='2000-01-03_Night'


def raw_row(symbol: str, offset: float, seq: int, bid: float, ask: float, opening: float) -> dict:
    """
    機能: 原本無関係のNight日時/十段/二時計を持つ正常JSONを作る。
    引数: symbol(str)、offset/bid/ask/opening(float)、seq(int)は商品・経過・価格・原seq。
    返り値: dictは人工原行。後日の価格又は結果から生成しない。
    """
    tick=.5 if symbol=='TOPIX' else 10.
    start=datetime(2000,1,3,17,0,tzinfo=JST);stamp=(start+timedelta(seconds=float(offset))).isoformat()
    value=dict(Symbol='人工'+symbol,SymbolName='人工限月',Exchange=2,CurrentPrice=float(bid),CurrentPriceTime=stamp,
        OpeningPrice=opening,OpeningPriceTime=start.isoformat(),TradingVolume=100.+seq,TradingVolumeTime=stamp)
    for depth in range(1,11):
        value['Buy'+str(depth)]=dict(Price=float(bid-(depth-1)*tick),Qty=100.)
        value['Sell'+str(depth)]=dict(Price=float(ask+(depth-1)*tick),Qty=100.)
    return value


def rows(symbol: str, length: int=241) -> list:
    """
    機能: 最初5分を含む20分の上昇/下降Nightを、接頭でも同じ順に作る。
    引数: symbol(str)、length(int)は商品と行数。
    返り値: list[tuple[int,dict]]は原行順人工。通常場のend/limitは切り詰めない。
    """
    tick,opening=(.5,4000.) if symbol=='TOPIX' else (10.,68000.)
    return [(i,raw_row(symbol,i*5.,i,opening+tick*(i if i<120 else 240-i),
        opening+tick*(i if i<120 else 240-i)+tick,opening)) for i in range(length)]


def extract(values: list, symbol: str) -> dict:
    """
    機能: 人工行をNDJSON bytes化し、新一回wrapperへ渡す。
    引数: values(list[tuple[int,dict]])、symbol(str)は同順人工と商品。
    返り値: dictはcurrent extract_streamの返り値。API/原本読取なし。
    """
    payload=b''.join((json.dumps(value,ensure_ascii=False)+'\n').encode('utf8') for _,value in values)
    return core.extract_stream(io.BytesIO(payload),NIGHT,symbol)


def equal(a: object, b: object) -> int:
    """
    機能: 型/NaNを含め人工値を再帰的に照合する。
    引数: a/b(object)は配列、辞書、リスト又は数値。
    返り値: intは比較した配列数。不一致は例外。
    """
    if isinstance(a,np.ndarray):
        assert isinstance(b,np.ndarray) and a.dtype==b.dtype;np.testing.assert_array_equal(a,b);return 1
    if isinstance(a,dict):
        assert a.keys()==b.keys();return sum(equal(a[k],b[k]) for k in a)
    if isinstance(a,(list,tuple)):
        assert type(a)==type(b) and len(a)==len(b);return sum(equal(x,y) for x,y in zip(a,b))
    if isinstance(a,float) and np.isnan(a):assert np.isnan(b)
    else:assert a==b,(a,b)
    return 0


def range_fixture() -> dict:
    """
    機能: 最初5分のsix点往復と下端2呼値からの反発を原JSONで作る。
    引数: なし。
    返り値: dictは新抽出二商品。自己TOPと相手NKのstrictpastを維持する。
    """
    times=[0.,60.,120.,180.,240.,300.,300.,300.,300.,310.]
    mids=[101.5,117.5,101.5,117.5,105.5,102.5,102.5,103.5,104.5,102.5]
    result={}
    for symbol in core.SYMBOLS:
        tick,opening=(.5,4000.) if symbol=='TOPIX' else (10.,68000.)
        data=[]
        for i,(t,mid) in enumerate(zip(times,mids)):
            if symbol=='NK225' and i in (5,6,7,8):t=299.
            bid=opening+(mid-101.5)*tick;data.append((i,raw_row(symbol,t,i,bid,bid+tick,opening)))
        result[symbol]=extract(data,symbol)
    return result


def engine_module() -> object:
    """
    機能: 確定range engine sourceをprivate同一bytes複製へだけ接続する。
    引数: なし。
    返り値: objectは数学不変の人工執行接口。JITはcurrent_session内。
    """
    owner=common.HERE/'engine_art';owner.mkdir(exist_ok=True)
    source=common.ROOT/'work/wave_v106/range_price'
    for name in ('interface.py','engine/core.py'):
        target=owner/name;target.parent.mkdir(exist_ok=True)
        payload=(source/name).read_bytes()
        if not target.exists():target.write_bytes(payload)
        assert target.read_bytes()==payload
    return common.module('106現ナイト接頭の私有range接口',owner/'interface.py')


def run() -> None:
    """
    機能: 旧collector同値/開場5分/支持/純価格/接頭とHTTP拒否を純人工で確認する。
    引数: なし。
    返り値: None。現API/現Night/旧33素材/新金融を読まない。
    """
    target=prepare.ARTIFICIAL;assert not target.exists();before=prepare.sources();checks={};counts={}
    full={s:extract(rows(s),s) for s in core.SYMBOLS}
    for symbol in core.SYMBOLS:
        old=core.holdout.extract_rows(iter(rows(symbol)),NIGHT,symbol)
        for name in ('raw','normal','lp','execution_lp_index'):counts[symbol+name]=equal(full[symbol][name],old[name])
        checks[symbol+'NDJSON一走査は旧collector全44列/normal/LP同値']=True
    packet=core.build(full,python=True);short=core.build({s:extract(rows(s,180),s) for s in core.SYMBOLS},python=True)
    for symbol in core.SYMBOLS:
        p=packet['prepared'][symbol];q=short['prepared'][symbol];record=p['record'];count=len(q['record']['seq'])
        for key,value in q['record'].items():equal(value,record[key][:count] if isinstance(value,np.ndarray) else record[key])
        assert p['reference_open']==q['reference_open'] and p['signal']['trend_width']==q['signal']['trend_width']
        assert packet['references'][NIGHT+'|'+symbol]['ref_open']['known_from_i']==0
        assert record['time_s'][0]==record['start'] and (record['time_s']<=record['start']+300).sum()==61
        checks[symbol+'Night開場始値と最初5分を当時from_i0で取得']=True
        c=packet['cases'][symbol]['C_OWN'];d=short['cases'][symbol]['C_OWN']
        for field in ('event','support_price','entry_quality','entry_reset','execution_to_raw_index'):equal(d[field],c[field][:count])
        assert d['decisions']==[v for v in c['decisions'] if v['row']<count]
        for cfg in core.configs():
            long=core.normal(packet,symbol,cfg);prefix=core.normal(short,symbol,cfg)
            for field,value in prefix.items():
                if isinstance(value,np.ndarray):equal(value,long[field][:count])
                elif field=='decisions':assert value==[v for v in long[field] if v['row']<count]
                else:equal(value,long[field])
        checks[symbol+'未来行追加後もC支持系譜と三固定入口prefix不変']=True
        assert q['record']['end']==p['record']['end'] and q['record']['limit']==p['record']['limit']
        checks[symbol+'途中終端でも通常end/limitを保存']=True
    R=core.build(range_fixture(),python=True);cfg=core.configs()[1];case=core.normal(R,'TOPIX',cfg)
    assert case['event'][7]==1 and case['entry_families'][7]==2
    assert case['entry_quality'][7] and not case['entry_reset'][7] and not case['decisions'][0]['selected_support_roots']
    checks['原JSONNight→nativeTOP5の固定R_PRICE反発発火']=True
    old_c=core.normal(R,'TOPIX',core.configs()[2]);assert not old_c['event'].any()
    checks['C_ONLYは新Rだけを外しCの旧全行資格を保持']=True
    engine=engine_module();R['prepared']['TOPIX']['record']['人工素材']=True;common.immutable(R['prepared']['TOPIX'])
    out=engine.play(R['prepared']['TOPIX'],case,cfg,quantity=5,finish=False,python=True)
    assert len(out['orders'])==1 and out['orders'][0,0]==9 and out['target_trace'][-1,0]==5
    checks['接頭finishFalseは指値fill後の5枚を保持、端点架空返済なし']=True
    before_source=prepare.sources();assert before_source==before
    fake=common.HERE/'人工契約確定ヘッダー.txt';assert not fake.exists()
    text='HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\nX-History-Session-Id: 2026-10-13_Night\r\nX-History-Generation: 私有人工\r\nX-History-Code: TOPIX\r\nX-History-As-Of: 2026-10-14T05:20:00+09:00\r\nX-History-Sequence: 1\r\nTrailer: X-History-Complete\r\n\r\nX-History-Complete: true\r\n'
    fake.write_bytes(text.encode('utf8'))
    capture=common.module('106現場取得の完結ヘッダー検査だけ',common.HERE.parent/'current_capture/capture.py')
    item=dict(curl終了コード=0,HTTP要求回数=1,自動再試行=0,ヘッダー位置=str(fake),snapshot=capture.headers(fake,'TOPIX'))
    assert prepare.snapshot(item,'TOPIX')['sequence']==1
    bad=deepcopy(item);bad['snapshot']['complete']='false'
    try:prepare.snapshot(bad,'TOPIX');raise RuntimeError('不一致トレーラーを合格にした')
    except AssertionError:pass
    checks['根capture契約の完結HTTP検査とsnapshot不一致拒否']=True
    common.write(target,dict(全合格=True,人工専用=True,検査件数=len(checks),検査=checks,配列照合=counts,
        source_SHA256=before,開始終端source一致=True,現在API取得=0,現在Night内容読取=0,旧33cache読取=0,
        原板読取=0,新金融再生=0,純人工執行=1,
        限界='小人工はfixtureの経路同値。現在Nightの履歴完全性、未知結果の黒字又は通常場flatを保証しない。'))
    print('現Nightの旧原行/完全prepare/C/six/接頭人工が合格',flush=True)


if __name__=='__main__':run()
