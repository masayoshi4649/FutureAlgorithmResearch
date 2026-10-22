"""旧E01経済と新日付の所有接続を、実市場なしの人工素材で確認する。"""

from datetime import datetime, timedelta, timezone
import ast
import csv
import hashlib
from io import StringIO
from pathlib import Path

import numpy as np
import numba

import adapter_v6 as adapter
import clock_adapter as clock
import csv_view124
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


def csv_checks(start: float,end: float) -> tuple[int,dict]:
    """
    機能: 末尾15:40追加による旧窓内表示の不変と不正時計拒否を人工で確認する。
    引数: start/end(float)は10月19日デイの旧観測窓。
    返り値: tuple[int,dict]は確認数と旧方向信号に渡す同じ人工足。
    """
    zone=timezone(timedelta(hours=9));times=[end-60*(120-i) for i in range(120)]
    records=[]
    for i,stamp in enumerate(times):
        close=4000.+i*.5 if i<75 else 4037.5-(i-75)*.7
        records.append(dict(time=datetime.fromtimestamp(stamp,zone).isoformat(),open=str(close-.1),
            high=str(close+.5),low=str(close-.5),close=str(close),volume='10',closed='true',volume_complete='true'))
    fields=list(records[0]);out=StringIO(newline='');writer=csv.DictWriter(out,fieldnames=fields,lineterminator='\n')
    writer.writeheader();writer.writerows(records);original=out.getvalue().encode('utf8')
    tail=dict(records[-1],time=datetime.fromtimestamp(end,zone).isoformat(),close='99999')
    writer.writerow(tail);extended=out.getvalue().encode('utf8')
    a,first=csv_view124.view(original,start,end);b,second=csv_view124.view(extended,start,end)
    assert a==b and first['kept_rows']==second['kept_rows']==120
    assert first['excluded_rows']==0 and second['excluded_rows']==1
    assert second['excluded']==[dict(original_row=120,time=tail['time'],epoch=end,reason='旧観測窓終端以上の合法末尾')]
    count=3
    for bad in ('時刻不明','2026-10-19T15:40:00','2026-10-18T15:40:00+09:00',records[-1]['time'],
                '2026-10-19T15:39:00+09:00','2026-10-19T15:46:00+09:00'):
        broken=StringIO(newline='');w=csv.DictWriter(broken,fieldnames=fields,lineterminator='\n')
        w.writeheader();w.writerows(records);w.writerow(dict(tail,time=bad))
        rejected=False
        try:csv_view124.view(broken.getvalue().encode('utf8'),start,end)
        except AssertionError:rejected=True
        assert rejected,bad;count+=1
    values=list(csv.DictReader(StringIO(a.decode('utf8'))));closes=np.asarray([float(r['close']) for r in values])
    bars=dict(close=closes,high=np.asarray([float(r['high']) for r in values]),
        low=np.asarray([float(r['low']) for r in values]),atr=np.ones(120),
        vwap=np.cumsum(closes)/np.arange(1,121),time_s=np.asarray(times))
    return count,dict(before=bars,after={k:v.copy() for k,v in bars.items()},tail=second)


def main() -> None:
    """
    機能: 同bytes源、二固定設定、両方向、全配列と費用・新日付時計を確認する。
    引数: なし。
    返り値: None。原市場、保存入力配列、新金融、登録は0。
    """
    before=sources();checks=0;arrays=0;cases=[]
    default_cache=HERE/'jit_legacy';financial_cache=HERE/'jit_financial'
    assert Path(legacy.CACHE)==default_cache and not financial_cache.exists()
    source=ast.parse((HERE/'run124.py').read_text(encoding='utf8'))
    function=next(v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='execute')
    financial_scope=next(i for i,v in enumerate(function.body) if isinstance(v,ast.With)
        and any('legacy.isolated' in ast.unparse(item.context_expr) for item in v.items))
    assert ast.unparse(function.body[financial_scope-2]).startswith("assert not (HERE / 'jit_financial').exists()")
    assert ast.unparse(function.body[financial_scope-1])=="legacy.CACHE = str(HERE / 'jit_financial')"
    checks+=3
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
    csv_count,csv_fixture=csv_checks(start,end);checks+=csv_count
    with legacy.isolated(discover=True):
        assert Path(numba.config.CACHE_DIR)==default_cache
        checks+=1
        rt=legacy.runtime();modules=adapter.engine_modules();selected=adapter.selected_configs(modules)
        hierarchy=legacy.module('csv_tail_hierarchy','work/wave_v27/hierarchy_signals.py')
        signal_checks=[]
        for kind in hierarchy.DESIGN['主方向']:
            params=dict(main_kind=kind,time_multiplier=1.,clock_multiplier=1.)
            left=hierarchy._main_from_bars(csv_fixture['before'],params)
            right=hierarchy._main_from_bars(csv_fixture['after'],params)
            np.testing.assert_array_equal(left,right)
            assert np.any(left!=0),kind
            signal_checks.append(dict(main_kind=kind,nonzero=int(np.count_nonzero(left)),rows=len(left)))
            checks+=2;arrays+=1
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
    assert Path(legacy.CACHE)==default_cache and not financial_cache.exists()
    checks+=1
    path=HERE/'同bytes源と固定二設定及び新日付の純人工.json'
    save(path,dict(passed=True,sources=before,checks=checks,arrays=arrays,cases=cases,
        csv_window_tail=csv_fixture['tail'],csv_main_direction_signals=signal_checks,
        cache_separation=dict(artificial=str(default_cache),financial=str(financial_cache),
            artificial_used_default=True,financial_directory_created=False,
            financial_switch_verified_in_ast=True,financial_run=0),
        original_market_reads=0,saved_array_reads=0,financial_accounts=0,API=0,real_orders=0,
        limitation='計算接続と人工の契約であり、新一場や過去40場の予測優位性を測定したものではない。'))
    print('追加E01の純人工合格 '+str(checks)+'確認/'+str(arrays)+'配列、SHA '+digest(path),flush=True)


if __name__=='__main__':
    main()
