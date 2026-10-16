"""静観の予定timer・取消・夏冬日程・接頭因果を小人工で確認する。"""

from copy import deepcopy
from datetime import date
from pathlib import Path
import time
import traceback

import numpy as np

import time_windows as calendar
import catalog
import common
import interface

HERE=Path(__file__).resolve().parent
CHECKS={}
FIXTURE=common.module('106静観の人工生成部品',HERE/'fixture.py')


def check(label: str, value: bool) -> None:
    """
    機能: 人工の独立期待値を件数付きで確認する。
    引数: label(str)、value(bool)は条件名と期待値。
    返り値: None。失敗の元sourceを保持して停止する。
    """
    assert value,label;CHECKS[label]=CHECKS.get(label,0)+1


def run(prepared: dict, case: dict, cfg: dict, qty: int, finish: bool=True,
        native: bool=False) -> dict:
    """
    機能: 人工だけに新静観coreを接続する。
    引数: prepared/case/cfg(dict)、qty(int)、finish/native(bool)。
    返り値: dictは物理注文・判断・時価。正式入力を読まない。
    """
    return interface.play(prepared,case,cfg,quantity=qty,finish=finish,python=not native)


def main() -> None:
    """
    機能: 静観off経済一致、予定返済の遅れ/再開、夏冬/休場を人工検算する。
    引数: なし。
    返り値: None。金融全33はまだ実行しない。
    """
    target=HERE/'開場静観timerと不変B4の人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('common.py','time_windows.py','catalog.py','core.py','interface.py','artificial.py')]
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}
    for symbol in ('TOPIX','NK225'):
        qty=10 if symbol=='TOPIX' else 20
        for side in (1,-1):
            cfg=dict(catalog.catalog()[0]);p,c=FIXTURE.fixture(symbol,side)
            original=FIXTURE.run_leg(p,c,qty)
            off=run(p,c,cfg,qty)
            for name in ('orders','trades','growth_cohorts','events','stats','curve','source_curve','target_trace','judgments','candidate_diagnostics'):
                np.testing.assert_array_equal(off[name],original[name])
            check('quiet offは旧106 B4経済exact一致',True)
            # ----------------------------------------
            # 窓開始は予定時刻で予約し、正常自己quoteならそのrow返済ができる。
            n=len(c['event']);c['quiet']=np.zeros(n,bool);c['quiet'][340:370]=True
            c['quiet_start_s']=np.full(n,np.nan);c['quiet_start_s'][340]=340.
            out=run(p,c,cfg,qty)
            check('予定静観開始は最初正常quote同row返済',out['orders'][1,0]==340 and out['orders'][1,1]==339 and out['orders'][1,10]==340 and out['orders'][1,8]==9)
            # ----------------------------------------
            # 開始価格不明なら予約継続。終了後の初気配でも古い保有を清算する。
            bad=deepcopy(p);bad['record']['quote_valid'][340:373]=False
            late=run(bad,c,cfg,qty)
            check('不正開始quoteは待機し静観終了後もtimer予約を保持',late['orders'][1,0]==373 and late['orders'][1,1]==339 and late['orders'][1,10]==340)
            # ----------------------------------------
            # 新規予約の次行が静観開始なら、同row fillより取消を優先。
            pending=deepcopy(c);pending['quiet_start_s'][:]=np.nan;pending['quiet_start_s'][331]=331.
            pending['quiet'][:]=False;pending['quiet'][331:370]=True
            cancelled=run(p,pending,cfg,qty)
            check('開始同rowの未約定新規は取消が先',len(cancelled['orders'])==0 and np.any(cancelled['control_events'][:,4]==13))
            # ----------------------------------------
            # 予定窓のpulseはそのrowで拒否し、終了後の新pulseだけを受理。
            resume=deepcopy(c);FIXTURE.event(p,resume,350,side,float(c['support_price'][330]))
            FIXTURE.event(p,resume,390,side,float(c['support_price'][330]))
            resumed=run(p,resume,cfg,qty)
            check('静観pulseは拒否理由10で復活しない',resumed['candidate_controls'][resumed['candidate_controls'][:,0]==350][0,6]==10 and resumed['orders'][2,1]==390)
            # ----------------------------------------
            # 場末forceとの同時計では元のforce理由6を維持する。
            endcase=deepcopy(c);endcase['quiet'][:]=False;endcase['quiet_start_s'][:]=np.nan
            endcase['quiet'][940:]=True;endcase['quiet_start_s'][940]=940.
            ending=run(p,endcase,cfg,qty)
            check('同rowの場末forceが静観より優先',ending['orders'][1,0]==940 and ending['orders'][1,8]==6)
            # ----------------------------------------
            # 保有接頭は予約だけ残し、未来端点の架空清算をしない。
            small=deepcopy(bad);length=341;small['record']={k:v[:length].copy() if isinstance(v,np.ndarray) else v for k,v in small['record'].items()}
            reduced={k:v[:length].copy() if isinstance(v,np.ndarray) else deepcopy(v) for k,v in c.items()}
            reduced['decisions']=[v for v in reduced['decisions'] if v['row']<length]
            prefix=run(small,reduced,cfg,qty,False)
            check('不正開始の保有接頭へfuture返済を足さない',len(prefix['orders'])==1 and len(prefix['trades'])==0 and prefix['target_trace'][-1,5]==qty)
            np.testing.assert_array_equal(prefix['curve'],late['curve'][:length]);check('未来変更前の接頭時価一致',True)
    # ----------------------------------------
    # 時計だけの予定日程: 夏22:30/冬23:30、米休日は窓なし。
    for day,opening in ((date(2026,9,21),'22:15:00'),(date(2026,12,1),'23:15:00')):
        win=calendar.OLD.windows(day,'U');assert len(win)==1
        local=calendar.OLD.datetime.fromtimestamp(win[0][0],calendar.OLD.TOKYO).isoformat()
        check('NYSE夏冬のZoneInfo開始予定',opening in local)
    check('NYSE定義済み休場日には静観窓なし',calendar.OLD.windows(date(2026,11,26),'U')==[])
    check('週末NYSEは静観窓なし',calendar.OLD.windows(date(2026,9,26),'U')==[])
    start,end,_=calendar.OLD.windows(date(2026,9,21),'U')[0]
    rr={'time_s':np.array([start-1,start,start,start+1,end,end+1])}
    f=calendar.features(rr,'U')
    np.testing.assert_array_equal(f['quiet'],[False,True,True,True,False,False])
    check('静観開始包含・終了除外・同時計timer一度',np.flatnonzero(np.isfinite(f['quiet_start_s'])).tolist()==[1])
    # ----------------------------------------
    # 一素材だけJITとの一致を確認。source/旧cacheを変更しない。
    p,c=FIXTURE.fixture('TOPIX');n=len(c['event']);c['quiet']=np.zeros(n,bool);c['quiet'][340:370]=True
    c['quiet_start_s']=np.full(n,np.nan);c['quiet_start_s'][340]=340.
    python=run(p,c,cfg,10);native=run(p,c,cfg,10,native=True)
    for name in ('orders','trades','growth_cohorts','events','curve','target_trace','control_events','candidate_controls'):
        np.testing.assert_array_equal(python[name],native[name])
    check('新timerのPythonとJIT全経済制御一致',True)
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=CHECKS,source_SHA256=before,開始終端source一致=True,
        新金融再生=0,正式input読取=0,原板読取=0,API取得=0,旧source変更=0))
    print('人工合格 '+str(sum(CHECKS.values()))+'検査',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        folder=HERE/('人工False_'+time.strftime('%Y%m%d_%H%M%S'));folder.mkdir()
        for n in ('artificial.py','core.py','interface.py','time_windows.py','catalog.py'):(folder/n).write_bytes((HERE/n).read_bytes())
        common.save(folder/'False.json',dict(全合格=False,例外=str(error),traceback=traceback.format_exc(),完了検査=CHECKS,新金融再生=0))
        raise
