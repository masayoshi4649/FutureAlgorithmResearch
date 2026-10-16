"""既知開場の静観窓を、価格を見ずに原時計へ投影する。"""

from datetime import datetime,timedelta
from pathlib import Path

import numpy as np

import common

OLD=common.module('106静観が読む2026NYSE公式保存日程',common.ROOT/'work/wave_v85/time_filter.py')


def features(record: dict, mode: str) -> dict:
    """
    機能: 予定窓内の新規禁止と窓開始の既知timerを全原行へ作る。
    引数: record(dict)はtime_sを持つ正常執行入力、mode(str)は空/J/U/JU。
    返り値: dictはquiet(bool配列)、quiet_start_s(float配列)、時刻計画。価格は参照しない。
    """
    assert mode in ('','J','U','JU')
    stamps=record['time_s'];assert stamps.ndim==1 and len(stamps)>0 and np.isfinite(stamps).all()
    assert np.all(np.diff(stamps)>=0)
    active=np.zeros(len(stamps),np.bool_);timer=np.full(len(stamps),np.nan,np.float64);plans=[]
    if not mode:return dict(quiet=active,quiet_start_s=timer,windows=plans)
    day=datetime.fromtimestamp(stamps[0],OLD.TOKYO).date()
    last_day=datetime.fromtimestamp(stamps[-1],OLD.TOKYO).date()
    while day<=last_day:
        for begin,end,reason in OLD.windows(day,mode):
            if end<=stamps[0] or begin>stamps[-1]:continue
            active|=(stamps>=begin)&(stamps<end)
            row=int(np.searchsorted(stamps,begin,side='left'))
            assert row<len(stamps)
            timer[row]=begin if not np.isfinite(timer[row]) else min(timer[row],begin)
            plans.append(dict(reason=reason,start=begin,end=end,timer_row=row,
                開始=datetime.fromtimestamp(begin,OLD.TOKYO).isoformat(),
                終了=datetime.fromtimestamp(end,OLD.TOKYO).isoformat(),
                当時初観測=datetime.fromtimestamp(stamps[row],OLD.TOKYO).isoformat(),
                開始後の初観測が静観終了後=bool(stamps[row]>=end),
                判断='既知予定開始。原clockが到達した最初row、価格資格に依存せず予約する'))
        day+=timedelta(days=1)
    return dict(quiet=active,quiet_start_s=timer,windows=plans)
