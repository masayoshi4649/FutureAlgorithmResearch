"""旧E01経済と新日付の所有接続を、実市場なしの人工素材で確認する。"""

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

import numpy as np

import adapter_v6 as adapter
import clock_adapter as clock
import legacy_runtime as legacy
import run124 as runner
from source_v6 import HERE, ROOT, MIRROR, SESSIONS, ENGINE_NAMES, save, digest, sources


def compare(expected: object, actual: object) -> int:
    """
    機能: すべての通常・高速返却配列を同じ添字で比較する。
    引数: expected/actual(object)はtuple又はNumPy配列。
    返り値: intは照合配列数。同じ誤りの検出を外部期待値の代わりにはしない。
    """
    if isinstance(expected,tuple):
        assert isinstance(actual,tuple) and len(expected)==len(actual)
        return sum(compare(a,b) for a,b in zip(expected,actual))
    np.testing.assert_array_equal(expected,actual)
    return 1


def main() -> None:
    """
    機能: 同bytes源、二固定設定、両方向、全配列と費用・新日付時計を確認する。
    引数: なし。
    返り値: None。原市場、保存入力配列、新金融、登録は0。
    """
    before=sources();checks=0;arrays=0;cases=[]
    assert SESSIONS==('2026-10-19_Day',)
    start,end=adapter.bounds(SESSIONS[0])
    zone=timezone(timedelta(hours=9))
    assert datetime.fromtimestamp(start,zone).isoformat()=='2026-10-19T08:45:00+09:00'
    assert datetime.fromtimestamp(end,zone).isoformat()=='2026-10-19T15:40:00+09:00'
    assert adapter.ORIGINAL_STAGE==HERE.parent/'inputs'
    assert adapter.ACTUAL=={'TOPIX':'E01_ADAPT_G50_ADAPT75_P1','NK225':'E01_ADAPT_G25_ADAPT100_P1'}
    checks+=5
    for path in sorted((MIRROR/'work').rglob('*.py')):
        assert path.read_bytes()==(ROOT/path.relative_to(MIRROR)).read_bytes();checks+=1
    for name in ENGINE_NAMES:
        assert (HERE/'engine'/name).read_bytes()==(ROOT/'work/stability119_20261017/v6_resume/engine'/name).read_bytes()
        checks+=1

    # ----------------------------------------
    # 当時までの高水位資格だけを使い、翌日補完も未来による接頭変更もしない。
    base=datetime(2026,10,19,9,tzinfo=zone)
    raw=dict(CurrentPrice=4000.,CurrentPriceTime=base.isoformat(),TradingVolume=100,
        TradingVolumeTime=base.isoformat(),Buy1=dict(Price=3999.5,Qty=10),Sell1=dict(Price=4000.,Qty=20))
    rows=[dict(raw,CurrentPriceTime=(base+timedelta(seconds=s)).isoformat()) for s in (0,0,-86400,-1,1,2)]
    outputs,reasons=clock.transform(rows,start,end)
    assert reasons==[0,0,12,8,0,0];checks+=1
    for cut in range(1,len(rows)+1):
        assert clock.transform(rows[:cut],start,end)==(outputs[:cut],reasons[:cut]);checks+=1
    for a,b,r in zip(rows,outputs,reasons):
        assert {k:v for k,v in a.items() if k!='CurrentPriceTime'}=={k:v for k,v in b.items() if k!='CurrentPriceTime'}
        assert b['CurrentPriceTime']==(None if r else a['CurrentPriceTime']);checks+=2
    with legacy.isolated(discover=True):
        rt=legacy.runtime();modules=adapter.engine_modules();selected=adapter.selected_configs(modules)
        fixture=legacy.function('work/e01_adaptive_price_20261014/engine/artificial.py','fixture',
            dict(np=np,catalog=modules['catalog'],daily=modules['daily']))
        for symbol in adapter.ACTUAL:
            for side in (1,-1):
                account=fixture(symbol,side,1);config=selected[symbol]
                py=modules['interface'].execute(account,config['entry_id'],config['execution_id'],python=True)
                jit=modules['interface'].execute(account,config['entry_id'],config['execution_id'],python=False)
                arrays+=compare(py['values'],jit['values'])
                arrays+=compare(py['fak_events'],jit['fak_events'])
                result=[]
                for source,pure in ((py,True),(jit,False)):
                    context=modules['interface'].prepared(SESSIONS[0],account,source['values'],True)
                    value=modules['interface'].apply(context,config,source['gate'],python=pure,fak_events=source['fak_events'])
                    assert value['summary']['全会計合格']
                    assert len(value['orders'])>=2 and len(value['parent'])>=1
                    assert value['long_qty'][-1]==value['short_qty'][-1]==0
                    row=adapter.account_row(SESSIONS[0],symbol,value)
                    assert row['net']==sum(p['収支'] for p in value['parent'])
                    assert row['profit']-row['loss']==row['net']
                    assert row['fees']==sum(value['order_fees'])
                    orders=runner.normalize_orders(value,account)
                    for order in orders:
                        direction=int(order['order'][3]);quantity=int(order['order'][4])
                        assert order['order'][5]==order['ask' if direction>0 else 'bid']
                        num,den=modules['catalog'].FEE_RATIO[symbol]
                        assert order['fee']==quantity*num//den
                        checks+=2
                    result.append(value);checks+=6
                for key in ('orders','order_uids','order_fees','long_qty','short_qty',
                            'equity_yen','liquidation_yen','reserved_exit_fees','cumulative_fees'):
                    arrays+=compare(result[0][key],result[1][key])
                cases.append(dict(symbol=symbol,side=side,orders=len(result[1]['orders']),
                    parents=len(result[1]['parent']),net=result[1]['summary']['収支']))
        runner.scope_guard(before)
        for path in (MIRROR/'book/TOPIX/人工.jsonl',ROOT/'book/TOPIX/人工.jsonl',MIRROR/'work/人工.npz'):
            rejected=False
            try:path.read_bytes()
            except AssertionError:rejected=True
            assert rejected;checks+=1
    assert sources()==before
    path=HERE/'同bytes源と固定二設定及び新日付の純人工.json'
    save(path,dict(passed=True,sources=before,checks=checks,arrays=arrays,cases=cases,
        original_market_reads=0,saved_array_reads=0,financial_accounts=0,API=0,real_orders=0,
        limitation='計算接続と人工の契約であり、新一場や過去40場の予測優位性を測定したものではない。'))
    print('追加E01の純人工合格 '+str(checks)+'確認/'+str(arrays)+'配列、SHA '+digest(path),flush=True)


if __name__=='__main__':
    main()
